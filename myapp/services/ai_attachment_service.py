from __future__ import annotations

import base64
import hashlib
from datetime import timedelta

import frappe
from frappe import _
from frappe.core.api.file import create_new_folder
from frappe.utils import cint, now_datetime
from frappe.utils.file_manager import save_file

from myapp.services.data_permission_service import current_user
from myapp.services.media_service import cleanup_temporary_item_image, upload_item_image
from myapp.utils.image_processing import AI_VISION_ATTACHMENT_PROFILE, normalize_image_upload


ATTACHMENT_TABLE = "tabMyApp AI Attachment"
AI_ATTACHMENT_FOLDER = "Home/Attachments/MyApp AI Inputs"
MAX_ATTACHMENTS_PER_MESSAGE = 4
MAX_SOURCE_BYTES = 20 * 1024 * 1024
RETENTION_HOURS = 24
SUPPORTED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
SOURCE_FORMAT_BY_CONTENT_TYPE = {
	"image/jpeg": "jpeg",
	"image/png": "png",
	"image/webp": "webp",
}


def _ensure_table():
	if not frappe.db.table_exists("MyApp AI Attachment"):
		raise frappe.ValidationError(_("AI 多模态数据表尚未迁移，请先执行 bench migrate。"))


def _name() -> str:
	return f"AI-ATT-{frappe.generate_hash(length=32)}"


def _normalize_ids(value) -> list[str]:
	if value in (None, "", []):
		return []
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except Exception as error:
			raise frappe.ValidationError(_("AI 附件编号格式不正确。")) from error
	if not isinstance(value, list):
		raise frappe.ValidationError(_("AI 附件编号必须是数组。"))
	result = []
	for item in value:
		resolved = str(item or "").strip()
		if resolved and resolved not in result:
			result.append(resolved)
	if len(result) > MAX_ATTACHMENTS_PER_MESSAGE:
		raise frappe.ValidationError(_("单条 AI 消息最多上传 {0} 张图片。").format(MAX_ATTACHMENTS_PER_MESSAGE))
	return result


def _decode_content(value: str) -> bytes:
	payload = str(value or "").strip()
	if payload.startswith("data:") and "," in payload:
		payload = payload.split(",", 1)[1]
	try:
		content = base64.b64decode(payload, validate=True)
	except Exception as error:
		raise frappe.ValidationError(_("AI 图片内容不是有效的 Base64。")) from error
	if not content:
		raise frappe.ValidationError(_("AI 图片内容不能为空。"))
	if len(content) > MAX_SOURCE_BYTES:
		raise frappe.ValidationError(_("AI 图片不能超过 20MB。"))
	return content


def _validate_source_content_type(*, source_format: str, content_type: str) -> None:
	expected_format = SOURCE_FORMAT_BY_CONTENT_TYPE.get(content_type)
	if not expected_format or str(source_format or "").strip().lower() != expected_format:
		raise frappe.ValidationError(_("AI 图片实际格式与声明格式不一致。"))


def _ensure_folder() -> str:
	current = "Home"
	for segment in ("Attachments", "MyApp AI Inputs"):
		next_folder = f"{current}/{segment}"
		if not frappe.db.exists("File", next_folder):
			create_new_folder(segment, current)
		current = next_folder
	return current


def _serialize(row) -> dict:
	return {
		"attachment_id": row.name,
		"filename": row.file_name,
		"content_type": row.content_type,
		"file_size": cint(row.file_size),
		"width": cint(row.width),
		"height": cint(row.height),
		"sha256": row.content_sha256,
		"preview_url": row.file_url,
		"status": row.status,
		"retention_until": str(row.retention_until or "") or None,
	}


def upload_ai_image_attachment(
	*, filename: str, file_content_base64: str, content_type: str,
) -> dict:
	user = current_user()
	_ensure_table()
	resolved_content_type = str(content_type or "").strip().lower()
	if resolved_content_type not in SUPPORTED_CONTENT_TYPES:
		raise frappe.ValidationError(_("AI 图片只支持 JPG、PNG 和 WebP。"))
	content = _decode_content(file_content_base64)
	normalized = normalize_image_upload(
		filename=str(filename or "ai-input").strip() or "ai-input",
		content=content,
		profile=AI_VISION_ATTACHMENT_PROFILE,
	)
	_validate_source_content_type(
		source_format=normalized.source_format,
		content_type=resolved_content_type,
	)
	file_doc = save_file(
		fname=normalized.filename,
		content=normalized.content,
		dt=None,
		dn=None,
		folder=_ensure_folder(),
		is_private=1,
	)
	now = now_datetime()
	attachment_id = _name()
	content_hash = hashlib.sha256(normalized.content).hexdigest()
	frappe.db.sql(
		f"""
		INSERT INTO `{ATTACHMENT_TABLE}`
			(name, creation, modified, modified_by, owner, docstatus, idx, status, purpose,
			 file_id, file_url, file_name, content_type, file_size, width, height,
			 content_sha256, retention_until)
		VALUES (%s, %s, %s, %s, %s, 0, 0, 'uploaded', 'vision_input',
			%s, %s, %s, %s, %s, %s, %s, %s, %s)
		""",
		(
			attachment_id, now, now, user, user, file_doc.name, file_doc.file_url,
			normalized.filename, normalized.content_type, normalized.file_size,
			normalized.width, normalized.height, content_hash,
			now + timedelta(hours=RETENTION_HOURS),
		),
	)
	row = frappe.db.sql(
		f"SELECT * FROM `{ATTACHMENT_TABLE}` WHERE name = %s", (attachment_id,), as_dict=True,
	)[0]
	frappe.db.commit()
	return {"status": "success", "message": _("AI 图片已安全暂存。"), "data": _serialize(row)}


def resolve_ai_attachments(
	attachment_ids,
	*,
	user: str | None = None,
	conversation_id: str | None = None,
	message_id: str | None = None,
	run_id: str | None = None,
) -> tuple[list[dict], list[dict]]:
	ids = _normalize_ids(attachment_ids)
	if not ids:
		return [], []
	_ensure_table()
	user = user or current_user()
	placeholders = ", ".join(["%s"] * len(ids))
	now = now_datetime()
	rows = frappe.db.sql(
		f"""
		SELECT a.* FROM `{ATTACHMENT_TABLE}` a
		LEFT JOIN `tabMyApp AI Conversation` c ON c.name = a.conversation
		WHERE a.name IN ({placeholders}) AND a.owner = %s
			AND (
				(a.status = 'uploaded' AND (a.retention_until IS NULL OR a.retention_until >= %s))
				OR (
					a.status = 'bound' AND (
						(a.conversation IS NOT NULL AND c.name IS NOT NULL
							AND (
								COALESCE(
									GREATEST(c.retention_until, a.retention_until),
									c.retention_until,
									a.retention_until
								) IS NULL
								OR COALESCE(
									GREATEST(c.retention_until, a.retention_until),
									c.retention_until,
									a.retention_until
								) >= %s
							))
						OR (a.conversation IS NULL AND (a.retention_until IS NULL OR a.retention_until >= %s))
					)
				)
			)
		FOR UPDATE
		""",
		(*ids, user, now, now, now),
		as_dict=True,
	)
	by_id = {row.name: row for row in rows}
	if len(by_id) != len(ids):
		raise frappe.PermissionError(_("AI 附件不存在、已过期或不属于当前账号。"))
	refs = []
	model_payloads = []
	conversation_retention_until = None
	if conversation_id:
		retention_rows = frappe.db.sql(
			"SELECT retention_until FROM `tabMyApp AI Conversation` WHERE name = %s LIMIT 1",
			(conversation_id,),
			as_dict=True,
		)
		conversation_retention_until = (
			retention_rows[0].retention_until if retention_rows else None
		)
	for attachment_id in ids:
		row = by_id[attachment_id]
		if conversation_id and row.conversation and row.conversation != conversation_id:
			raise frappe.ValidationError(_("AI 附件已经绑定到其他会话，不能重复提交。"))
		if message_id and row.message_id and row.message_id != message_id:
			raise frappe.ValidationError(_("AI 附件已经随其他消息提交，不能重复提交。"))
		file_doc = frappe.get_doc("File", row.file_id)
		content = file_doc.get_content()
		if isinstance(content, str):
			content = content.encode()
		if hashlib.sha256(content).hexdigest() != row.content_sha256:
			raise frappe.ValidationError(_("AI 附件完整性校验失败。"))
		ref = _serialize(row)
		refs.append(ref)
		model_payloads.append({
			"attachment_id": attachment_id,
			"filename": row.file_name,
			"mime_type": row.content_type,
			"sha256": row.content_sha256,
			"width": cint(row.width),
			"height": cint(row.height),
			"data_base64": base64.b64encode(content).decode(),
		})
		if conversation_id or message_id or run_id:
			frappe.db.sql(
				f"""
				UPDATE `{ATTACHMENT_TABLE}`
				SET status = 'bound', conversation = COALESCE(conversation, %s),
					message_id = COALESCE(message_id, %s), source_run = COALESCE(source_run, %s),
					retention_until = CASE
						WHEN %s IS NULL THEN retention_until
						WHEN retention_until IS NULL OR retention_until < %s THEN %s
						ELSE retention_until
					END,
					modified = %s, modified_by = %s
				WHERE name = %s AND owner = %s
				""",
				(
					conversation_id, message_id, run_id,
					conversation_retention_until, conversation_retention_until,
					conversation_retention_until, now_datetime(), user, attachment_id, user,
				),
			)
	return refs, model_payloads


def hydrate_ai_message_attachments(messages: list[dict], *, user: str) -> list[dict]:
	"""Resolve persisted message attachment references into private model payloads."""
	hydrated = []
	for message in messages:
		row = dict(message)
		attachment_ids = [
			str(item.get("attachment_id") or "").strip()
			for item in row.get("attachments") or []
			if isinstance(item, dict) and str(item.get("attachment_id") or "").strip()
		]
		if attachment_ids:
			_refs, payloads = resolve_ai_attachments(attachment_ids, user=user)
			row["attachments"] = payloads
		else:
			row.pop("attachments", None)
		hydrated.append(row)
	return hydrated


def stage_attachment_as_item_image(*, attachment_id: str, user: str | None = None) -> str | None:
	user = user or current_user()
	_ensure_table()
	rows = frappe.db.sql(
		f"SELECT * FROM `{ATTACHMENT_TABLE}` WHERE name = %s AND owner = %s LIMIT 1 FOR UPDATE",
		(str(attachment_id or "").strip(), user),
		as_dict=True,
	)
	if not rows:
		return None
	row = rows[0]
	if row.derived_item_image_url:
		return str(row.derived_item_image_url)
	file_doc = frappe.get_doc("File", row.file_id)
	content = file_doc.get_content()
	if isinstance(content, str):
		content = content.encode()
	try:
		result = upload_item_image(
			filename=row.file_name,
			file_content_base64=base64.b64encode(content).decode(),
			content_type=row.content_type,
			item_code=None,
			is_private=False,
		)
	except frappe.ValidationError:
		return None
	file_url = str((result.get("data") or {}).get("file_url") or "").strip() or None
	if file_url:
		frappe.db.sql(
			f"UPDATE `{ATTACHMENT_TABLE}` SET derived_item_image_url = %s WHERE name = %s AND owner = %s",
			(file_url, row.name, user),
		)
	return file_url


def discard_ai_attachment(*, attachment_id: str) -> dict:
	user = current_user()
	_ensure_table()
	rows = frappe.db.sql(
		f"SELECT * FROM `{ATTACHMENT_TABLE}` WHERE name = %s AND owner = %s LIMIT 1 FOR UPDATE",
		(str(attachment_id or "").strip(), user),
		as_dict=True,
	)
	if not rows:
		return {"status": "success", "message": _("AI 附件已不存在。"), "data": {"discarded": False}}
	row = rows[0]
	if row.message_id or row.source_run:
		raise frappe.ValidationError(_("已经随消息提交的 AI 附件不能单独删除。"))
	if row.derived_item_image_url:
		cleanup_temporary_item_image(file_url=row.derived_item_image_url)
	frappe.delete_doc("File", row.file_id, ignore_permissions=True, force=True)
	frappe.db.sql(f"DELETE FROM `{ATTACHMENT_TABLE}` WHERE name = %s", (row.name,))
	frappe.db.commit()
	return {"status": "success", "message": _("AI 附件已删除。"), "data": {"discarded": True}}


def cleanup_expired_ai_attachments() -> dict:
	_ensure_table()
	rows = frappe.db.sql(
		f"""
		SELECT a.* FROM `{ATTACHMENT_TABLE}` a
		LEFT JOIN `tabMyApp AI Conversation` c ON c.name = a.conversation
		WHERE a.status <> 'expired' AND (
			(a.status = 'uploaded' AND a.retention_until < %s)
			OR (
				a.status = 'bound'
				AND COALESCE(
					GREATEST(c.retention_until, a.retention_until),
					c.retention_until,
					a.retention_until
				) < %s
			)
		)
		LIMIT 200
		""",
		(now_datetime(), now_datetime()),
		as_dict=True,
	)
	deleted = 0
	for row in rows:
		if frappe.db.table_exists("MyApp AI Draft"):
			active_draft = frappe.db.sql(
				"""
				SELECT name FROM `tabMyApp AI Draft`
				WHERE status = 'draft' AND payload_json LIKE %s
				LIMIT 1
				""",
				(f"%{row.name}%",),
			)
			if active_draft:
				frappe.db.sql(
					f"UPDATE `{ATTACHMENT_TABLE}` SET retention_until = %s, modified = %s WHERE name = %s",
					(
						now_datetime() + timedelta(hours=RETENTION_HOURS),
						now_datetime(),
						row.name,
					),
				)
				continue
		if row.derived_item_image_url:
			cleanup_temporary_item_image(file_url=row.derived_item_image_url)
		if frappe.db.exists("File", row.file_id):
			frappe.delete_doc("File", row.file_id, ignore_permissions=True, force=True)
		frappe.db.sql(
			f"UPDATE `{ATTACHMENT_TABLE}` SET status = 'expired', modified = %s WHERE name = %s",
			(now_datetime(), row.name),
		)
		deleted += 1
	frappe.db.commit()
	return {"status": "success", "data": {"expired_count": deleted}}
