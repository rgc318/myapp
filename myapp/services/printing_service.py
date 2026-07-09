from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from html import escape
import json
from uuid import uuid4

import frappe
from frappe import _
from frappe.core.api.file import create_new_folder
from frappe.utils import get_datetime, now_datetime
from frappe.utils.file_manager import save_file

from myapp.printing.registry import get_print_doctype_options, get_print_template_options, resolve_print_template
from myapp.printing.templates import ensure_managed_print_format


PRINT_OUTPUT_HTML = "html"
PRINT_OUTPUT_PDF = "pdf"
SUPPORTED_PRINT_OUTPUTS = (PRINT_OUTPUT_HTML, PRINT_OUTPUT_PDF)
PRINT_ARCHIVE_FOLDER = "Home/Attachments/MyApp Print Files/Archive"
PRINT_STORAGE_STREAM = "stream"
PRINT_STORAGE_ARCHIVE = "archive"
PRINT_JOB_TABLE = "MyApp Print Job"
PRINT_JOB_ACTIONS = ("preview", "download", "print", "share", "archive")
PRINT_JOB_STATUSES = ("success", "failed", "skipped")


def list_print_doctypes_v1():
	doctypes = get_print_doctype_options()
	return {
		"status": "success",
		"message": _("可打印单据类型已获取。"),
		"data": {
			"doctypes": doctypes,
			"count": len(doctypes),
		},
	}


def get_print_templates_v1(doctype: str):
	resolved_doctype = _normalize_required_str(doctype, field_label="doctype")
	default_template = resolve_print_template(resolved_doctype)
	templates = get_print_template_options(resolved_doctype)
	return {
		"status": "success",
		"message": _("打印模板已获取。"),
		"data": {
			"doctype": resolved_doctype,
			"default_template": default_template["key"],
			"templates": templates,
			"capabilities": ["preview", "download_pdf", "archive_pdf"],
		},
		"meta": {
			"doctype": resolved_doctype,
			"default_template": default_template["key"],
		},
	}


def record_print_job_v1(
	doctype: str,
	docname: str,
	template: str | None = None,
	action: str = "print",
	output: str = PRINT_OUTPUT_PDF,
	status: str = "success",
	filename: str | None = None,
	file_url: str | None = None,
	error: str | None = None,
	metadata: dict | str | None = None,
):
	resolved_doctype = _normalize_required_str(doctype, field_label="doctype")
	resolved_docname = _normalize_required_str(docname, field_label="docname")
	resolved_action = _resolve_print_job_action(action)
	resolved_output = _resolve_output(output)
	resolved_status = _resolve_print_job_status(status)
	template_info = resolve_print_template(resolved_doctype, template)
	document = _load_print_document(resolved_doctype, resolved_docname)
	if not _print_job_table_exists():
		return {
			"status": "success",
			"message": _("打印记录表尚未创建，已跳过记录。"),
			"data": {
				"recorded": False,
				"reason": "table_missing",
				"doctype": document.doctype,
				"docname": document.name,
			},
		}

	now = now_datetime()
	user = _current_user()
	job_name = f"PRN-JOB-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
	metadata_json = _coerce_metadata_json(_build_print_job_metadata(metadata, template_info))
	request = getattr(frappe.local, "request", None)
	frappe.db.sql(
		"""
		INSERT INTO `tabMyApp Print Job`
			(`name`, `creation`, `modified`, `modified_by`, `owner`, `docstatus`, `idx`,
			 `reference_doctype`, `reference_name`, `template`, `template_label`, `print_format`,
			 `action`, `output`, `status`, `filename`, `file_url`, `printed_by`, `printed_at`,
			 `user_agent`, `ip_address`, `error`, `metadata_json`)
		VALUES
			(%s, %s, %s, %s, %s, 0, 0,
			 %s, %s, %s, %s, %s,
			 %s, %s, %s, %s, %s, %s, %s,
			 %s, %s, %s, %s)
		""",
		(
			job_name,
			now,
			now,
			user,
			user,
			resolved_doctype,
			resolved_docname,
			template_info["key"],
			template_info["label"],
			template_info.get("print_format"),
			resolved_action,
			resolved_output,
			resolved_status,
			_normalize_optional_str(filename),
			_normalize_optional_str(file_url),
			user,
			now,
			_get_request_user_agent(request),
			_get_request_ip_address(request),
			_normalize_optional_str(error),
			metadata_json,
		),
	)
	frappe.db.commit()

	return {
		"status": "success",
		"message": _("打印记录已保存。"),
		"data": {
			"recorded": True,
			"job_id": job_name,
			"doctype": resolved_doctype,
			"docname": resolved_docname,
			"template": template_info,
			"action": resolved_action,
			"output": resolved_output,
			"status": resolved_status,
			"printed_by": user,
			"printed_at": now,
		},
	}


def list_print_jobs_v1(
	doctype: str,
	docname: str,
	action: str | None = None,
	template: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	user: str | None = None,
	limit: int = 20,
):
	resolved_doctype = _normalize_required_str(doctype, field_label="doctype")
	resolved_docname = _normalize_required_str(docname, field_label="docname")
	_load_print_document(resolved_doctype, resolved_docname)
	if not _print_job_table_exists():
		return {
			"status": "success",
			"message": _("打印记录表尚未创建。"),
			"data": {
				"jobs": [],
				"count": 0,
				"table_ready": False,
			},
		}

	conditions = ["reference_doctype = %s", "reference_name = %s"]
	values: list = [resolved_doctype, resolved_docname]
	resolved_action = (action or "").strip().lower()
	if resolved_action:
		if resolved_action not in PRINT_JOB_ACTIONS:
			frappe.throw(_("不支持的打印动作。"))
		conditions.append("action = %s")
		values.append(resolved_action)

	resolved_template = (template or "").strip()
	if resolved_template:
		conditions.append("template = %s")
		values.append(resolved_template)

	resolved_user = (user or "").strip()
	if resolved_user:
		conditions.append("printed_by = %s")
		values.append(resolved_user)

	if date_from:
		conditions.append("printed_at >= %s")
		values.append(get_datetime(date_from))
	if date_to:
		conditions.append("printed_at <= %s")
		values.append(get_datetime(date_to))

	resolved_limit = _coerce_positive_int(limit, default=20, maximum=100)
	values.append(resolved_limit)
	rows = frappe.db.sql(
		f"""
		SELECT
			name, reference_doctype, reference_name, template, template_label, print_format,
			action, output, status, filename, file_url, printed_by, printed_at, error, metadata_json
		FROM `tabMyApp Print Job`
		WHERE {" AND ".join(conditions)}
		ORDER BY printed_at DESC, creation DESC
		LIMIT %s
		""",
		tuple(values),
		as_dict=True,
	)
	jobs = [_serialize_print_job(row) for row in rows]
	return {
		"status": "success",
		"message": _("打印记录已获取。"),
		"data": {
			"jobs": jobs,
			"count": len(jobs),
			"table_ready": True,
		},
		"meta": {
			"doctype": resolved_doctype,
			"docname": resolved_docname,
			"limit": resolved_limit,
		},
	}


def get_print_preview_v1(
	doctype: str,
	docname: str,
	template: str | None = None,
	output: str = PRINT_OUTPUT_HTML,
):
	resolved_doctype = _normalize_required_str(doctype, field_label="doctype")
	resolved_docname = _normalize_required_str(docname, field_label="docname")
	resolved_output = _resolve_output(output)
	template_info = resolve_print_template(resolved_doctype, template)
	_ensure_template_ready(template_info)
	document = _load_print_document(resolved_doctype, resolved_docname)
	preview_payload = _render_print_preview_payload(
		document=document,
		template_info=template_info,
		output=resolved_output,
	)

	return {
		"status": "success",
		"message": _("打印预览已生成。"),
		"data": preview_payload,
		"meta": {
			"doctype": resolved_doctype,
			"docname": resolved_docname,
			"template": template_info["key"],
			"output": resolved_output,
		},
	}


def get_print_file_v1(
	doctype: str,
	docname: str,
	template: str | None = None,
	filename: str | None = None,
	archive: bool | int | str = False,
):
	resolved_doctype = _normalize_required_str(doctype, field_label="doctype")
	resolved_docname = _normalize_required_str(docname, field_label="docname")
	should_archive = _coerce_bool_flag(archive)
	template_info = resolve_print_template(resolved_doctype, template)
	_ensure_template_ready(template_info)
	document = _load_print_document(resolved_doctype, resolved_docname)
	file_name = _resolve_file_name(
		doctype=resolved_doctype,
		docname=resolved_docname,
		template_info=template_info,
		filename=filename,
	)
	pdf_bytes = _render_print_pdf(document=document, template_info=template_info)
	file_doc = None
	if should_archive:
		file_doc = _save_print_pdf_file(
			doctype=resolved_doctype,
			docname=resolved_docname,
			filename=file_name,
			pdf_bytes=pdf_bytes,
		)

	return {
		"status": "success",
		"message": _("打印文件已归档。") if should_archive else _("打印文件元数据已生成。"),
		"data": {
			"doctype": resolved_doctype,
			"docname": resolved_docname,
			"title": _build_print_title(document),
			"template": template_info,
			"available_templates": get_print_template_options(resolved_doctype),
			"output": PRINT_OUTPUT_PDF,
			"filename": file_name,
			"mime_type": "application/pdf",
			"file_url": file_doc.file_url if file_doc else None,
			"is_private": bool(file_doc.is_private) if file_doc else True,
			"status": "archived" if should_archive else "ready",
			"file_size": len(pdf_bytes),
			"archived": should_archive,
			"storage_mode": PRINT_STORAGE_ARCHIVE if should_archive else PRINT_STORAGE_STREAM,
		},
		"meta": {
			"doctype": resolved_doctype,
			"docname": resolved_docname,
			"template": template_info["key"],
			"output": PRINT_OUTPUT_PDF,
			"storage_mode": PRINT_STORAGE_ARCHIVE if should_archive else PRINT_STORAGE_STREAM,
		},
	}


def build_print_file_download_v1(
	doctype: str,
	docname: str,
	template: str | None = None,
	filename: str | None = None,
):
	resolved_doctype = _normalize_required_str(doctype, field_label="doctype")
	resolved_docname = _normalize_required_str(docname, field_label="docname")
	template_info = resolve_print_template(resolved_doctype, template)
	_ensure_template_ready(template_info)
	document = _load_print_document(resolved_doctype, resolved_docname)
	file_name = _resolve_file_name(
		doctype=resolved_doctype,
		docname=resolved_docname,
		template_info=template_info,
		filename=filename,
	)
	pdf_bytes = _render_print_pdf(document=document, template_info=template_info)

	return {
		"filename": file_name,
		"content": pdf_bytes,
		"doctype": resolved_doctype,
		"docname": resolved_docname,
		"template": template_info["key"],
	}


def _normalize_required_str(value: str | None, *, field_label: str):
	resolved = (value or "").strip()
	if not resolved:
		frappe.throw(_("{0} 不能为空。").format(field_label))
	return resolved


def _resolve_output(output: str | None):
	resolved = (output or PRINT_OUTPUT_HTML).strip().lower()
	if resolved not in SUPPORTED_PRINT_OUTPUTS:
		frappe.throw(_("仅支持 html 或 pdf 输出。"))
	return resolved


def _coerce_bool_flag(value) -> bool:
	if isinstance(value, bool):
		return value
	return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_print_job_action(action: str | None):
	resolved = (action or "print").strip().lower()
	if resolved not in PRINT_JOB_ACTIONS:
		frappe.throw(_("不支持的打印动作。"))
	return resolved


def _resolve_print_job_status(status: str | None):
	resolved = (status or "success").strip().lower()
	if resolved not in PRINT_JOB_STATUSES:
		frappe.throw(_("不支持的打印记录状态。"))
	return resolved


def _normalize_optional_str(value):
	resolved = (str(value) if value is not None else "").strip()
	return resolved or None


def _coerce_positive_int(value, *, default: int, maximum: int):
	try:
		resolved = int(value)
	except Exception:
		return default
	if resolved <= 0:
		return default
	return min(resolved, maximum)


def _coerce_metadata_json(metadata):
	if metadata is None or metadata == "":
		return None
	if isinstance(metadata, str):
		return metadata
	return json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str)


def _build_print_job_metadata(metadata, template_info: dict):
	base = {}
	if isinstance(metadata, dict):
		base.update(metadata)
	elif metadata:
		base["source_metadata"] = metadata

	base.setdefault("template_version", template_info.get("template_version"))
	base.setdefault("template_hash", template_info.get("template_hash"))
	base.setdefault("template_managed", template_info.get("managed"))
	base.setdefault("print_format", template_info.get("print_format"))
	return base


def _current_user():
	session = getattr(frappe, "session", None)
	user = getattr(session, "user", None)
	return user or "Administrator"


def _get_request_user_agent(request):
	if not request:
		return None
	headers = getattr(request, "headers", None)
	if headers and hasattr(headers, "get"):
		return headers.get("User-Agent")
	return None


def _get_request_ip_address(request):
	if not request:
		return None
	return getattr(request, "remote_addr", None)


def _print_job_table_exists():
	try:
		return bool(frappe.db.table_exists(PRINT_JOB_TABLE))
	except Exception:
		return False


def _serialize_print_job(row):
	metadata = None
	metadata_json = row.get("metadata_json")
	if metadata_json:
		try:
			metadata = json.loads(metadata_json)
		except Exception:
			metadata = metadata_json
	return {
		"job_id": row.get("name"),
		"doctype": row.get("reference_doctype"),
		"docname": row.get("reference_name"),
		"template": {
			"key": row.get("template"),
			"label": row.get("template_label") or row.get("template"),
			"print_format": row.get("print_format"),
		},
		"action": row.get("action"),
		"output": row.get("output"),
		"status": row.get("status"),
		"filename": row.get("filename"),
		"file_url": row.get("file_url"),
		"printed_by": row.get("printed_by"),
		"printed_at": row.get("printed_at"),
		"error": row.get("error"),
		"metadata": metadata,
	}


def _load_print_document(doctype: str, docname: str):
	if not frappe.db.exists(doctype, docname):
		raise frappe.DoesNotExistError(_("{0} {1} 不存在。").format(doctype, docname))

	document = frappe.get_doc(doctype, docname)
	if not frappe.has_permission(doctype, ptype="read", doc=document):
		raise frappe.PermissionError(_("你没有权限打印该单据。"))
	_attach_printing_derived_fields(document)
	return document


def _attach_printing_derived_fields(document):
	total_amount = _coerce_decimal_print_amount(
		getattr(document, "rounded_total", None),
		fallback=getattr(document, "grand_total", None),
	)
	document.myapp_amount_in_words_zh = _to_chinese_financial_words(total_amount)
	status_label = _resolve_print_status_label(document)
	history_summary = _get_print_history_summary(document.doctype, document.name)
	document.myapp_print_status_label = status_label
	document.myapp_print_history_summary = history_summary
	document.myapp_print_copy_label = _resolve_print_copy_label(history_summary)
	document.myapp_print_watermark = _resolve_print_watermark(
		status_label=status_label,
		history_summary=history_summary,
	)


def _resolve_print_status_label(document):
	docstatus = getattr(document, "docstatus", None)
	if docstatus == 0:
		return "草稿"
	if docstatus == 2:
		return "已作废"
	return "正式"


def _get_print_history_summary(doctype: str, docname: str):
	summary = {
		"total_count": 0,
		"successful_count": 0,
		"latest_printed_by": None,
		"latest_printed_at": None,
	}
	if not _print_job_table_exists():
		return summary

	try:
		rows = frappe.db.sql(
			"""
			SELECT
				COUNT(*) AS total_count,
				SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successful_count,
				MAX(printed_at) AS latest_printed_at
			FROM `tabMyApp Print Job`
			WHERE reference_doctype = %s AND reference_name = %s
			""",
			(doctype, docname),
			as_dict=True,
		)
		if not rows:
			return summary
		row = rows[0]
		summary["total_count"] = int(row.get("total_count") or 0)
		summary["successful_count"] = int(row.get("successful_count") or 0)
		summary["latest_printed_at"] = row.get("latest_printed_at")
		if summary["latest_printed_at"]:
			user_rows = frappe.db.sql(
				"""
				SELECT printed_by
				FROM `tabMyApp Print Job`
				WHERE reference_doctype = %s AND reference_name = %s AND printed_at = %s
				ORDER BY creation DESC
				LIMIT 1
				""",
				(doctype, docname, summary["latest_printed_at"]),
				as_dict=True,
			)
			if user_rows:
				summary["latest_printed_by"] = user_rows[0].get("printed_by")
	except Exception:
		return {
			"total_count": 0,
			"successful_count": 0,
			"latest_printed_by": None,
			"latest_printed_at": None,
		}
	return summary


def _resolve_print_copy_label(history_summary: dict):
	successful_count = int(history_summary.get("successful_count") or 0)
	if successful_count <= 0:
		return "首次打印"
	return f"第 {successful_count + 1} 次打印"


def _resolve_print_watermark(*, status_label: str, history_summary: dict):
	if status_label == "草稿":
		return "草稿"
	if status_label == "已作废":
		return "已作废"
	if int(history_summary.get("successful_count") or 0) > 0:
		return "补打"
	return None


def _ensure_template_ready(template_info: dict):
	ensure_managed_print_format(template_info.get("print_format"))


def _render_print_preview_payload(*, document, template_info: dict, output: str):
	html = _render_print_html(document=document, template_info=template_info)
	return {
		"doctype": document.doctype,
		"docname": document.name,
		"title": _build_print_title(document),
		"template": template_info,
		"available_templates": get_print_template_options(document.doctype),
		"output": output,
		"html": html,
		"mime_type": "text/html" if output == PRINT_OUTPUT_HTML else "application/pdf",
	}


def _render_print_html(*, document, template_info: dict):
	get_print = _get_print_function()
	if get_print:
		kwargs = {"doc": document}
		if template_info.get("print_format"):
			kwargs["print_format"] = template_info["print_format"]
		return get_print(document.doctype, document.name, **kwargs)

	return (
		"<html><body>"
		f"<h1>{escape(str(document.doctype))}</h1>"
		f"<p>{escape(str(document.name))}</p>"
		"</body></html>"
	)


def _render_print_pdf(*, document, template_info: dict):
	get_print = _get_print_function()
	if not get_print:
		frappe.throw(_("当前环境未启用 PDF 打印能力。"))

	base_kwargs = {
		"doc": document,
		"as_pdf": True,
	}
	if template_info.get("print_format"):
		base_kwargs["print_format"] = template_info["print_format"]

	try:
		return _call_get_print_with_pdf_generator(
			get_print,
			document=document,
			base_kwargs=base_kwargs,
			pdf_generator="chrome",
		)
	except Exception:
		return _call_get_print_with_pdf_generator(
			get_print,
			document=document,
			base_kwargs=base_kwargs,
			pdf_generator=None,
		)


def _get_print_function():
	try:
		from frappe.utils.print_utils import get_print
	except Exception:
		return None
	return get_print


def _call_get_print_with_pdf_generator(get_print, *, document, base_kwargs: dict, pdf_generator: str | None):
	form_dict = getattr(frappe.local, "form_dict", None)
	original_marker = object()
	original_value = original_marker
	if form_dict is not None:
		try:
			original_value = form_dict.get("pdf_generator", original_marker)
			if hasattr(form_dict, "pop"):
				form_dict.pop("pdf_generator", None)
		except Exception:
			original_value = original_marker

	try:
		if pdf_generator:
			return get_print(document.doctype, document.name, pdf_generator=pdf_generator, **base_kwargs)
		return get_print(document.doctype, document.name, **base_kwargs)
	finally:
		if form_dict is not None:
			try:
				if original_value is original_marker:
					if hasattr(form_dict, "pop"):
						form_dict.pop("pdf_generator", None)
				else:
					form_dict["pdf_generator"] = original_value
			except Exception:
				pass


def _build_print_title(document):
	return f"{document.doctype} {document.name}"


def _resolve_file_name(*, doctype: str, docname: str, template_info: dict, filename: str | None = None):
	custom_name = (filename or "").strip()
	if custom_name:
		return custom_name

	template_suffix = template_info["key"]
	return f"{doctype}-{docname}-{template_suffix}.pdf".replace("/", "-")


_CN_DIGITS = "零壹贰叁肆伍陆柒捌玖"
_CN_SMALL_UNITS = ["", "拾", "佰", "仟"]
_CN_BIG_UNITS = ["", "万", "亿", "兆"]


def _coerce_decimal_print_amount(value, *, fallback=None):
	for candidate in (value, fallback, 0):
		if candidate is None or candidate == "":
			continue
		try:
			return Decimal(str(candidate))
		except Exception:
			continue
	return Decimal("0")


def _to_chinese_financial_words(amount) -> str:
	value = _coerce_decimal_print_amount(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
	sign = "负" if value < 0 else ""
	value = abs(value)
	integer_part = int(value)
	fraction_part = int((value - Decimal(integer_part)) * 100)

	integer_words = _integer_to_chinese(integer_part)
	if fraction_part == 0:
		return f"{sign}{integer_words}元整"

	jiao = fraction_part // 10
	fen = fraction_part % 10
	fraction_words = ""
	if jiao:
		fraction_words += f"{_CN_DIGITS[jiao]}角"
	if fen:
		if not jiao:
			fraction_words += "零"
		fraction_words += f"{_CN_DIGITS[fen]}分"
	return f"{sign}{integer_words}元{fraction_words}"


def _integer_to_chinese(number: int) -> str:
	if number == 0:
		return "零"

	parts: list[str] = []
	unit_index = 0
	need_zero = False

	while number > 0:
		section = number % 10000
		if section == 0:
			if parts:
				need_zero = True
		else:
			section_words = _section_to_chinese(section)
			if need_zero:
				parts.append("零")
				need_zero = False
			if unit_index > 0:
				section_words += _CN_BIG_UNITS[unit_index]
			parts.append(section_words)
			if section < 1000:
				need_zero = True
		number //= 10000
		unit_index += 1

	return "".join(reversed(parts)).rstrip("零")


def _section_to_chinese(section: int) -> str:
	result: list[str] = []
	zero_pending = False
	for idx in range(4):
		divisor = 10 ** (3 - idx)
		digit = section // divisor
		section %= divisor
		if digit == 0:
			if result:
				zero_pending = True
			continue
		if zero_pending:
			result.append("零")
			zero_pending = False
		result.append(_CN_DIGITS[digit] + _CN_SMALL_UNITS[3 - idx])
	return "".join(result)


def _save_print_pdf_file(*, doctype: str, docname: str, filename: str, pdf_bytes: bytes):
	folder = _ensure_folder_path(PRINT_ARCHIVE_FOLDER)
	return save_file(
		fname=filename,
		content=pdf_bytes,
		dt=doctype,
		dn=docname,
		folder=folder,
		is_private=1,
	)


def _ensure_folder_path(folder_path: str) -> str:
	segments = [segment for segment in folder_path.split("/") if segment]
	if not segments:
		return "Home"

	current = segments[0]
	for segment in segments[1:]:
		next_folder = f"{current}/{segment}"
		if not frappe.db.exists("File", next_folder):
			create_new_folder(segment, current)
		current = next_folder
	return current
