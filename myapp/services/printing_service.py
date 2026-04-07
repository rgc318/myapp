from __future__ import annotations

from html import escape
from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe import _
from frappe.core.api.file import create_new_folder
from frappe.utils.file_manager import save_file

from myapp.printing.registry import get_print_template_options, resolve_print_template
from myapp.printing.templates import ensure_managed_print_format


PRINT_OUTPUT_HTML = "html"
PRINT_OUTPUT_PDF = "pdf"
SUPPORTED_PRINT_OUTPUTS = (PRINT_OUTPUT_HTML, PRINT_OUTPUT_PDF)
PRINT_ARCHIVE_FOLDER = "Home/Attachments/MyApp Print Files/Archive"
PRINT_STORAGE_STREAM = "stream"
PRINT_STORAGE_ARCHIVE = "archive"


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
		try:
			return Decimal(str(candidate or 0))
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
