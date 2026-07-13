from __future__ import annotations

import hashlib
import json
import os
import uuid

import frappe
from frappe import _
from frappe.utils import add_days, cint, now_datetime


CONVERSATION_TABLE = "tabMyApp AI Conversation"
MESSAGE_TABLE = "tabMyApp AI Message"
RUN_TABLE = "tabMyApp AI Run"
FEEDBACK_TABLE = "tabMyApp AI Feedback"
DRAFT_TABLE = "tabMyApp AI Draft"
DRAFT_LINE_TABLE = "tabMyApp AI Draft Line"
DEFAULT_RETENTION_DAYS = 30
MAX_CONVERSATION_PAGE_SIZE = 50


def _name(prefix: str) -> str:
	return f"{prefix}-{uuid.uuid4().hex}"


def _retention_days() -> int:
	try:
		value = int(os.environ.get("MYAPP_AI_RETENTION_DAYS", DEFAULT_RETENTION_DAYS))
	except (TypeError, ValueError):
		value = DEFAULT_RETENTION_DAYS
	return max(1, min(value, 365))


def _ensure_tables():
	if not frappe.db.table_exists("MyApp AI Conversation"):
		frappe.throw(_("AI 会话表尚未初始化，请先执行 bench migrate。"))


def _safe_json_loads(value, default):
	if not value:
		return default
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return default


def _serialize_conversation(row) -> dict:
	return {
		"name": row.name,
		"title": row.title or _("新会话"),
		"status": row.status,
		"company": row.company_scope,
		"message_count": cint(row.message_count),
		"last_message_at": str(row.last_message_at or "") or None,
		"creation": str(row.creation or "") or None,
		"modified": str(row.modified or "") or None,
	}


def _get_owned_conversation(conversation_id: str, user: str, *, for_update: bool = False):
	lock_sql = " FOR UPDATE" if for_update else ""
	rows = frappe.db.sql(
		f"""
		SELECT name, title, status, company_scope, message_count, last_message_at, creation, modified
		FROM `{CONVERSATION_TABLE}`
		WHERE name = %s AND owner = %s
		LIMIT 1{lock_sql}
		""",
		(conversation_id, user),
		as_dict=True,
	)
	if not rows:
		raise frappe.PermissionError(_("AI 会话不存在或无权访问。"))
	return rows[0]


def create_conversation(*, user: str, title: str | None = None, company: str | None = None) -> dict:
	_ensure_tables()
	now = now_datetime()
	conversation_id = _name("AI-CONV")
	resolved_title = " ".join((title or "").split())[:120] or _("新会话")
	frappe.db.sql(
		f"""
		INSERT INTO `{CONVERSATION_TABLE}`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 status, title, company_scope, message_count, last_message_at, retention_until)
		VALUES (%s, %s, %s, %s, %s, 0, 0, 'active', %s, %s, 0, %s, %s)
		""",
		(
			conversation_id,
			now,
			now,
			user,
			user,
			resolved_title,
			(company or "").strip() or None,
			now,
			add_days(now, _retention_days()),
		),
	)
	return _serialize_conversation(_get_owned_conversation(conversation_id, user))


def list_conversations(*, user: str, status: str = "active", start: int = 0, limit: int = 20) -> dict:
	_ensure_tables()
	resolved_status = (status or "active").strip().lower()
	if resolved_status not in {"active", "archived", "all"}:
		frappe.throw(_("AI 会话状态筛选不正确。"))
	start = max(0, cint(start))
	limit = max(1, min(MAX_CONVERSATION_PAGE_SIZE, cint(limit) or 20))
	status_sql = "" if resolved_status == "all" else " AND status = %s"
	params = [user]
	if resolved_status != "all":
		params.append(resolved_status)
	count_rows = frappe.db.sql(
		f"SELECT COUNT(*) AS total FROM `{CONVERSATION_TABLE}` WHERE owner = %s{status_sql}",
		tuple(params),
		as_dict=True,
	)
	rows = frappe.db.sql(
		f"""
		SELECT name, title, status, company_scope, message_count, last_message_at, creation, modified
		FROM `{CONVERSATION_TABLE}`
		WHERE owner = %s{status_sql}
		ORDER BY last_message_at DESC, creation DESC
		LIMIT %s OFFSET %s
		""",
		(*params, limit, start),
		as_dict=True,
	)
	return {
		"items": [_serialize_conversation(row) for row in rows],
		"pagination": {"start": start, "limit": limit, "total": cint(count_rows[0].total if count_rows else 0)},
	}


def get_conversation(*, conversation_id: str, user: str) -> dict:
	_ensure_tables()
	conversation = _get_owned_conversation((conversation_id or "").strip(), user)
	messages = frappe.db.sql(
		f"""
		SELECT name, sequence_no, role, content, scenario, run_id, citations_json, prompt_version, creation
		FROM `{MESSAGE_TABLE}`
		WHERE conversation = %s
		ORDER BY sequence_no ASC
		LIMIT 200
		""",
		(conversation.name,),
		as_dict=True,
	)
	return {
		"conversation": _serialize_conversation(conversation),
		"messages": [
			{
				"name": row.name,
				"sequence": cint(row.sequence_no),
				"role": row.role,
				"content": row.content or "",
				"scenario": row.scenario,
				"run_id": row.run_id,
				"citations": _safe_json_loads(row.citations_json, []),
				"prompt_version": row.prompt_version,
				"creation": str(row.creation or "") or None,
			}
			for row in messages
		],
	}


def archive_conversation(*, conversation_id: str, user: str) -> dict:
	conversation = _get_owned_conversation((conversation_id or "").strip(), user, for_update=True)
	if conversation.status != "archived":
		frappe.db.sql(
			f"UPDATE `{CONVERSATION_TABLE}` SET status = 'archived', modified = %s, modified_by = %s WHERE name = %s",
			(now_datetime(), user, conversation.name),
		)
	return _serialize_conversation(_get_owned_conversation(conversation.name, user))


def append_message(
	*,
	conversation_id: str,
	user: str,
	role: str,
	content: str,
	scenario: str,
	run_id: str | None = None,
	citations: list[dict] | None = None,
	prompt_version: str | None = None,
) -> dict:
	conversation = _get_owned_conversation(conversation_id, user, for_update=True)
	if conversation.status != "active":
		frappe.throw(_("已归档的 AI 会话不能继续发送消息。"))
	now = now_datetime()
	sequence_no = cint(conversation.message_count) + 1
	message_id = _name("AI-MSG")
	frappe.db.sql(
		f"""
		INSERT INTO `{MESSAGE_TABLE}`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 conversation, sequence_no, role, content, content_hash, scenario,
			 run_id, citations_json, prompt_version)
		VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s)
		""",
		(
			message_id,
			now,
			now,
			user,
			user,
			conversation_id,
			sequence_no,
			role,
			content,
			hashlib.sha256(content.encode("utf-8")).hexdigest(),
			scenario,
			run_id,
			frappe.as_json(citations or []),
			prompt_version,
		),
	)
	frappe.db.sql(
		f"""
		UPDATE `{CONVERSATION_TABLE}`
		SET modified = %s, modified_by = %s, message_count = %s,
			last_message_at = %s, retention_until = %s
		WHERE name = %s
		""",
		(now, user, sequence_no, now, add_days(now, _retention_days()), conversation_id),
	)
	return {"name": message_id, "sequence": sequence_no}


def load_model_messages(*, conversation_id: str, user: str, limit: int = 20) -> list[dict]:
	_get_owned_conversation(conversation_id, user)
	rows = frappe.db.sql(
		f"""
		SELECT role, content
		FROM `{MESSAGE_TABLE}`
		WHERE conversation = %s
		ORDER BY sequence_no DESC
		LIMIT %s
		""",
		(conversation_id, max(1, min(20, cint(limit) or 20))),
		as_dict=True,
	)
	return [{"role": row.role, "content": row.content or ""} for row in reversed(rows)]


def create_run(*, conversation_id: str, user: str, scenario: str, tool_calls: list[dict] | None = None) -> str:
	_get_owned_conversation(conversation_id, user)
	now = now_datetime()
	run_id = _name("AI-RUN")
	frappe.db.sql(
		f"""
		INSERT INTO `{RUN_TABLE}`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 conversation, requested_by, scenario, status, tool_calls_json, started_at)
		VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, 'running', %s, %s)
		""",
		(run_id, now, now, user, user, conversation_id, user, scenario, frappe.as_json(tool_calls or []), now),
	)
	return run_id


def complete_run(*, run_id: str, user: str, result: dict, latency_ms: int, tool_calls: list[dict] | None = None):
	usage = result.get("usage") or {}
	frappe.db.sql(
		f"""
		UPDATE `{RUN_TABLE}`
		SET modified = %s, modified_by = %s, status = 'completed', model_alias = %s,
			model = %s, trace_id = %s, prompt_tokens = %s, completion_tokens = %s,
			total_tokens = %s, reasoning_tokens = %s, latency_ms = %s,
			tool_calls_json = %s, completed_at = %s, error_code = NULL, error = NULL
		WHERE name = %s AND requested_by = %s
		""",
		(
			now_datetime(),
			user,
			result.get("model_alias"),
			result.get("model"),
			result.get("trace_id"),
			cint(usage.get("prompt_tokens")),
			cint(usage.get("completion_tokens")),
			cint(usage.get("total_tokens")),
			cint(usage.get("reasoning_tokens")),
			max(0, cint(latency_ms)),
			frappe.as_json(tool_calls or []),
			now_datetime(),
			run_id,
			user,
		),
	)


def fail_run(*, run_id: str, user: str, error: Exception, latency_ms: int):
	frappe.db.sql(
		f"""
		UPDATE `{RUN_TABLE}`
		SET modified = %s, modified_by = %s, status = 'failed', latency_ms = %s,
			error_code = %s, error = %s, completed_at = %s
		WHERE name = %s AND requested_by = %s
		""",
		(
			now_datetime(),
			user,
			max(0, cint(latency_ms)),
			type(error).__name__,
			str(error)[:2000],
			now_datetime(),
			run_id,
			user,
		),
	)


def submit_feedback(
	*,
	run_id: str,
	user: str,
	rating: str,
	category: str | None = None,
	comment: str | None = None,
) -> dict:
	_ensure_tables()
	rows = frappe.db.sql(
		f"""
		SELECT name, conversation, status, trace_id
		FROM `{RUN_TABLE}`
		WHERE name = %s AND requested_by = %s
		LIMIT 1
		""",
		(run_id, user),
		as_dict=True,
	)
	if not rows:
		raise frappe.PermissionError(_("AI Run 不存在或无权反馈。"))
	if rows[0].status != "completed":
		frappe.throw(_("只有已完成的 AI Run 可以提交反馈。"))
	now = now_datetime()
	feedback_id = _name("AI-FEEDBACK")
	frappe.db.sql(
		f"""
		INSERT INTO `{FEEDBACK_TABLE}`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 conversation, run_id, rating, category, comment)
		VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, %s)
		ON DUPLICATE KEY UPDATE
			modified = VALUES(modified), modified_by = VALUES(modified_by),
			rating = VALUES(rating), category = VALUES(category), comment = VALUES(comment)
		""",
		(
			feedback_id,
			now,
			now,
			user,
			user,
			rows[0].conversation,
			run_id,
			rating,
			category,
			comment,
		),
	)
	return {
		"run_id": run_id,
		"conversation": rows[0].conversation,
		"trace_id": rows[0].trace_id,
		"rating": rating,
		"category": category,
		"comment": comment,
	}


def _serialize_draft(row, lines=None) -> dict:
	return {
		"name": row.name,
		"conversation": row.conversation,
		"source_run": row.source_run,
		"draft_type": row.draft_type,
		"status": row.status,
		"company": row.company,
		"title": row.title,
		"version": cint(row.version_no),
		"payload": _safe_json_loads(row.payload_json, {}),
		"validation": _safe_json_loads(row.validation_json, {}),
		"lines": lines or [],
		"creation": str(row.creation or "") or None,
		"modified": str(row.modified or "") or None,
	}


def create_draft(
	*,
	user: str,
	conversation_id: str,
	source_run: str,
	draft_type: str,
	company: str,
	title: str,
	payload: dict,
	validation: dict,
) -> dict:
	_get_owned_conversation(conversation_id, user)
	now = now_datetime()
	draft_id = _name("AI-DRAFT")
	frappe.db.sql(
		f"""
		INSERT INTO `{DRAFT_TABLE}`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 conversation, source_run, draft_type, status, company, title,
			 version_no, payload_json, validation_json, retention_until)
		VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, 'draft', %s, %s, 1, %s, %s, %s)
		""",
		(
			draft_id,
			now,
			now,
			user,
			user,
			conversation_id,
			source_run,
			draft_type,
			company,
			title[:255],
			frappe.as_json(payload),
			frappe.as_json(validation),
			add_days(now, _retention_days()),
		),
	)
	for index, line in enumerate(payload.get("items") or [], 1):
		frappe.db.sql(
			f"""
			INSERT INTO `{DRAFT_LINE_TABLE}`
				(name, creation, modified, modified_by, owner, docstatus, idx,
				 draft, line_no, item_query, item_code, item_name, uom, uom_display,
				 qty, rate, warehouse, conversion_factor, candidates_json, warnings_json, user_overrides_json)
			VALUES (%s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s,
				%s, %s, %s, %s, %s, %s, %s)
			""",
			(
				_name("AI-DRAFT-LINE"), now, now, user, user, index, draft_id, index,
				line.get("item_query"), line.get("item_code"), line.get("item_name"),
				line.get("uom"), line.get("uom_display"), line.get("qty") or 0,
				line.get("price"), line.get("warehouse"), line.get("conversion_factor"),
				frappe.as_json(line.get("candidates") or []),
				frappe.as_json(line.get("warnings") or []), frappe.as_json({}),
			),
		)
	return get_draft(draft_id=draft_id, user=user)


def get_draft(*, draft_id: str, user: str) -> dict:
	rows = frappe.db.sql(
		f"""
		SELECT name, conversation, source_run, draft_type, status, company, title,
			version_no, payload_json, validation_json, creation, modified
		FROM `{DRAFT_TABLE}` WHERE name = %s AND owner = %s LIMIT 1
		""",
		(draft_id, user),
		as_dict=True,
	)
	if not rows:
		raise frappe.PermissionError(_("AI 草稿不存在或无权访问。"))
	return _serialize_draft(rows[0])


def mark_draft_handed_off(*, draft_id: str, user: str) -> dict:
	draft = get_draft(draft_id=draft_id, user=user)
	if draft["status"] == "draft":
		frappe.db.sql(
			f"UPDATE `{DRAFT_TABLE}` SET status = 'handed_off', modified = %s, modified_by = %s WHERE name = %s",
			(now_datetime(), user, draft_id),
		)
	return get_draft(draft_id=draft_id, user=user)


def update_draft(*, draft_id: str, user: str, payload: dict, validation: dict) -> dict:
	draft = get_draft(draft_id=draft_id, user=user)
	if draft["status"] != "draft":
		frappe.throw(_("只有 draft 状态的 AI 草稿可以修改。"))
	now = now_datetime()
	frappe.db.sql(
		f"""
		UPDATE `{DRAFT_TABLE}` SET modified = %s, modified_by = %s,
			version_no = version_no + 1, payload_json = %s, validation_json = %s,
			retention_until = %s WHERE name = %s AND owner = %s
		""",
		(now, user, frappe.as_json(payload), frappe.as_json(validation), add_days(now, _retention_days()), draft_id, user),
	)
	frappe.db.sql(f"DELETE FROM `{DRAFT_LINE_TABLE}` WHERE draft = %s", (draft_id,))
	for index, line in enumerate(payload.get("items") or [], 1):
		frappe.db.sql(
			f"""
			INSERT INTO `{DRAFT_LINE_TABLE}`
				(name, creation, modified, modified_by, owner, docstatus, idx,
				 draft, line_no, item_query, item_code, item_name, uom, uom_display,
				 qty, rate, warehouse, conversion_factor, candidates_json, warnings_json, user_overrides_json)
			VALUES (%s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s,
				%s, %s, %s, %s, %s, %s, %s)
			""",
			(
				_name("AI-DRAFT-LINE"), now, now, user, user, index, draft_id, index,
				line.get("item_query"), line.get("item_code"), line.get("item_name"), line.get("uom"),
				line.get("uom_display"), line.get("qty") or 0, line.get("price"), line.get("warehouse"),
				line.get("conversion_factor"), frappe.as_json(line.get("candidates") or []),
				frappe.as_json(line.get("warnings") or []), frappe.as_json({"updated_by_user": True}),
			),
		)
	return get_draft(draft_id=draft_id, user=user)


def discard_draft(*, draft_id: str, user: str) -> dict:
	draft = get_draft(draft_id=draft_id, user=user)
	if draft["status"] == "handed_off":
		frappe.throw(_("已交接的 AI 草稿不能放弃。"))
	if draft["status"] != "discarded":
		frappe.db.sql(
			f"UPDATE `{DRAFT_TABLE}` SET status = 'discarded', modified = %s, modified_by = %s WHERE name = %s",
			(now_datetime(), user, draft_id),
		)
	return get_draft(draft_id=draft_id, user=user)


def cleanup_expired_ai_conversations(batch_size: int = 200) -> dict:
	_ensure_tables()
	batch_size = max(1, min(1000, cint(batch_size) or 200))
	rows = frappe.db.sql(
		f"""
		SELECT name FROM `{CONVERSATION_TABLE}`
		WHERE retention_until IS NOT NULL AND retention_until < %s
		ORDER BY retention_until ASC
		LIMIT %s
		""",
		(now_datetime(), batch_size),
		as_dict=True,
	)
	names = [row.name for row in rows]
	if not names:
		return {"deleted": 0}
	placeholders = ", ".join(["%s"] * len(names))
	draft_rows = frappe.db.sql(
		f"SELECT name FROM `{DRAFT_TABLE}` WHERE conversation IN ({placeholders})",
		tuple(names),
		as_dict=True,
	) if frappe.db.table_exists("MyApp AI Draft") else []
	draft_names = [row.name for row in draft_rows]
	if draft_names:
		draft_placeholders = ", ".join(["%s"] * len(draft_names))
		frappe.db.sql(f"DELETE FROM `{DRAFT_LINE_TABLE}` WHERE draft IN ({draft_placeholders})", tuple(draft_names))
		frappe.db.sql(f"DELETE FROM `{DRAFT_TABLE}` WHERE name IN ({draft_placeholders})", tuple(draft_names))
	frappe.db.sql(f"DELETE FROM `{MESSAGE_TABLE}` WHERE conversation IN ({placeholders})", tuple(names))
	frappe.db.sql(f"DELETE FROM `{FEEDBACK_TABLE}` WHERE conversation IN ({placeholders})", tuple(names))
	frappe.db.sql(f"DELETE FROM `{RUN_TABLE}` WHERE conversation IN ({placeholders})", tuple(names))
	frappe.db.sql(f"DELETE FROM `{CONVERSATION_TABLE}` WHERE name IN ({placeholders})", tuple(names))
	frappe.db.commit()
	return {"deleted": len(names)}
