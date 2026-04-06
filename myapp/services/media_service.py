from __future__ import annotations

import base64
import mimetypes
import os
import re

import frappe
from frappe import _
from frappe.utils.file_manager import save_file


DEFAULT_IMAGE_EXTENSION = ".bin"
SUPPORTED_IMAGE_EXTENSIONS = {
	".jpg",
	".jpeg",
	".png",
	".webp",
	".gif",
	".bmp",
	".heic",
	".heif",
}
SUPPORTED_IMAGE_MIME_TYPES = {
	"image/jpeg",
	"image/png",
	"image/webp",
	"image/gif",
	"image/bmp",
	"image/heic",
	"image/heif",
}
STORAGE_PROVIDER_FRAPPE = "frappe_file"


def upload_item_image(
	*,
	filename: str,
	file_content_base64: str,
	content_type: str | None = None,
	item_code: str | None = None,
	is_private: bool = False,
):
	resolved_filename = _normalize_image_filename(filename, content_type)
	resolved_item_code = _normalize_optional_text(item_code)
	resolved_content_type = _normalize_optional_text(content_type)
	_validate_image_content_type(resolved_filename, resolved_content_type)
	file_bytes = _decode_base64_file_content(file_content_base64)
	file_doc = _save_item_image_via_frappe(
		filename=resolved_filename,
		file_bytes=file_bytes,
		item_code=resolved_item_code,
		is_private=is_private,
	)

	return {
		"status": "success",
		"message": _("商品图片已上传。"),
		"data": {
			"file_url": file_doc.file_url,
			"file_name": getattr(file_doc, "file_name", resolved_filename),
			"file_id": getattr(file_doc, "name", None),
			"is_private": cint_bool(getattr(file_doc, "is_private", is_private)),
			"attached_to_doctype": getattr(file_doc, "attached_to_doctype", "Item" if resolved_item_code else None),
			"attached_to_name": getattr(file_doc, "attached_to_name", resolved_item_code),
			"storage_provider": STORAGE_PROVIDER_FRAPPE,
		},
	}


def replace_item_image(
	*,
	item_code: str,
	filename: str,
	file_content_base64: str,
	content_type: str | None = None,
	is_private: bool = False,
):
	resolved_item_code = _normalize_optional_text(item_code)
	if not resolved_item_code:
		raise frappe.ValidationError(_("商品编码不能为空。"))

	item = frappe.get_doc("Item", resolved_item_code)
	previous_image_url = _normalize_optional_text(getattr(item, "image", None))
	upload_result = upload_item_image(
		filename=filename,
		file_content_base64=file_content_base64,
		content_type=content_type,
		item_code=resolved_item_code,
		is_private=is_private,
	)
	new_file_url = upload_result["data"]["file_url"]

	try:
		item.image = new_file_url
		item.save()
	except Exception:
		_delete_managed_file_by_url(
			file_url=new_file_url,
			item_code=resolved_item_code,
			skip_if_shared=False,
		)
		raise

	cleanup_result = _cleanup_previous_item_image(
		item_code=resolved_item_code,
		previous_image_url=previous_image_url,
		current_image_url=new_file_url,
	)

	return {
		"status": "success",
		"message": _("商品图片已替换。"),
		"data": {
			**upload_result["data"],
			"item_code": resolved_item_code,
			"previous_file_url": previous_image_url,
			"cleanup": cleanup_result,
		},
	}


def _save_item_image_via_frappe(*, filename: str, file_bytes: bytes, item_code: str | None, is_private: bool):
	doctype = "Item" if item_code else None
	docname = item_code if item_code else None
	return save_file(
		fname=filename,
		content=file_bytes,
		dt=doctype,
		dn=docname,
		df="image" if item_code else None,
		is_private=1 if is_private else 0,
	)


def _cleanup_previous_item_image(*, item_code: str, previous_image_url: str | None, current_image_url: str | None):
	if not previous_image_url or previous_image_url == current_image_url:
		return {
			"attempted": False,
			"deleted": False,
			"reason": "same_or_empty",
		}

	deleted = _delete_managed_file_by_url(
		file_url=previous_image_url,
		item_code=item_code,
		skip_if_shared=True,
	)
	return {
		"attempted": True,
		"deleted": deleted,
		"reason": "deleted" if deleted else "skipped",
	}


def _delete_managed_file_by_url(*, file_url: str, item_code: str, skip_if_shared: bool) -> bool:
	resolved_file_url = _normalize_optional_text(file_url)
	if not resolved_file_url:
		return False

	if skip_if_shared and _is_file_url_referenced_by_other_items(file_url=resolved_file_url, item_code=item_code):
		return False

	file_name = frappe.db.get_value(
		"File",
		{
			"file_url": resolved_file_url,
			"attached_to_doctype": "Item",
			"attached_to_name": item_code,
			"attached_to_field": "image",
		},
		"name",
	)
	if not file_name:
		return False

	frappe.delete_doc("File", file_name, ignore_permissions=True, force=True)
	return True


def _is_file_url_referenced_by_other_items(*, file_url: str, item_code: str) -> bool:
	referenced_items = frappe.get_all(
		"Item",
		filters={"image": file_url},
		pluck="name",
	)
	return any(name != item_code for name in referenced_items)


def _decode_base64_file_content(file_content_base64: str) -> bytes:
	if not isinstance(file_content_base64, str) or not file_content_base64.strip():
		raise frappe.ValidationError(_("图片内容不能为空。"))

	payload = file_content_base64.strip()
	if payload.startswith("data:") and "," in payload:
		payload = payload.split(",", 1)[1]

	try:
		decoded = base64.b64decode(payload, validate=True)
	except Exception as exc:
		raise frappe.ValidationError(_("图片内容不是有效的 Base64 数据。")) from exc

	if not decoded:
		raise frappe.ValidationError(_("图片内容不能为空。"))

	return decoded


def _normalize_image_filename(filename: str, content_type: str | None) -> str:
	resolved_filename = os.path.basename((filename or "").strip())
	if not resolved_filename:
		raise frappe.ValidationError(_("文件名不能为空。"))

	resolved_filename = re.sub(r"[^A-Za-z0-9._-]+", "-", resolved_filename).strip(".-")
	if not resolved_filename:
		raise frappe.ValidationError(_("文件名无效。"))

	root, extension = os.path.splitext(resolved_filename)
	if extension:
		return f"{root}{extension.lower()}"

	guessed_extension = mimetypes.guess_extension((content_type or "").strip()) or DEFAULT_IMAGE_EXTENSION
	return f"{resolved_filename}{guessed_extension.lower()}"


def _validate_image_content_type(filename: str, content_type: str | None):
	extension = os.path.splitext(filename)[1].lower()
	if extension not in SUPPORTED_IMAGE_EXTENSIONS:
		raise frappe.ValidationError(_("暂不支持该图片格式。"))

	if content_type and content_type not in SUPPORTED_IMAGE_MIME_TYPES:
		raise frappe.ValidationError(_("暂不支持该图片格式。"))


def _normalize_optional_text(value: str | None) -> str | None:
	if value is None:
		return None
	trimmed = value.strip()
	return trimmed or None


def cint_bool(value) -> int:
	return 1 if bool(value) else 0
