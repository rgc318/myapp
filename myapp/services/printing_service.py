from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from html import escape
from io import BytesIO
import json
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import frappe
from frappe import _
from frappe.core.api.file import create_new_folder
from frappe.utils import add_days, get_datetime, now_datetime
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
PRINT_BATCH_TABLE = "MyApp Print Batch"
PRINT_SETTING_TABLE = "MyApp Print Setting"
PRINT_JOB_ACTIONS = ("preview", "download", "print", "share", "archive")
PRINT_JOB_STATUSES = ("success", "failed", "skipped")
PRINT_BATCH_STATUSES = ("queued", "processing", "cancel_requested", "canceled", "completed", "partial_failed", "failed")
MAX_PRINT_BATCH_ITEMS = 100
PRINT_BATCH_CLEANUP_RETENTION_DAYS = 90
PRINT_BATCH_CLEANUP_BATCH_SIZE = 100
PRINT_BATCH_FINAL_STATUSES = ("completed", "partial_failed", "failed", "canceled")


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


def get_print_settings_v1():
	settings = _get_print_settings()
	return {
		"status": "success",
		"message": _("打印设置已获取。"),
		"data": {
			"settings": settings,
			"count": len(settings),
			"table_ready": _print_setting_table_exists(),
		},
	}


def set_print_default_template_v1(
	doctype: str,
	template: str,
	enabled: bool | int | str = True,
	metadata: dict | str | None = None,
):
	_require_print_settings_manager()
	resolved_doctype = _normalize_required_str(doctype, field_label="doctype")
	resolved_template = _normalize_required_str(template, field_label="template")
	template_info = resolve_print_template(resolved_doctype, resolved_template)
	if not _print_setting_table_exists():
		return {
			"status": "success",
			"message": _("打印设置表尚未创建。"),
			"data": {
				"saved": False,
				"reason": "table_missing",
				"doctype": resolved_doctype,
				"template": template_info,
			},
		}

	now = now_datetime()
	user = _current_user()
	setting_name = f"PRINT-SETTING-{resolved_doctype}"
	frappe.db.sql(
		"""
		INSERT INTO `tabMyApp Print Setting`
			(`name`, `creation`, `modified`, `modified_by`, `owner`, `docstatus`, `idx`,
			 `reference_doctype`, `default_template`, `enabled`, `metadata_json`)
		VALUES
			(%s, %s, %s, %s, %s, 0, 0,
			 %s, %s, %s, %s)
		ON DUPLICATE KEY UPDATE
			modified = VALUES(modified),
			modified_by = VALUES(modified_by),
			default_template = VALUES(default_template),
			enabled = VALUES(enabled),
			metadata_json = VALUES(metadata_json)
		""",
		(
			setting_name,
			now,
			now,
			user,
			user,
			resolved_doctype,
			template_info["key"],
			1 if _coerce_bool_flag(enabled) else 0,
			_coerce_metadata_json(metadata),
		),
	)
	frappe.db.commit()
	return {
		"status": "success",
		"message": _("默认打印模板已保存。"),
		"data": {
			"saved": True,
			"doctype": resolved_doctype,
			"default_template": template_info["key"],
			"template": template_info,
			"enabled": _coerce_bool_flag(enabled),
		},
	}


def create_print_batch_v1(
	documents,
	output: str = PRINT_OUTPUT_PDF,
	template: str | None = None,
	run_async: bool | int | str = True,
	metadata: dict | str | None = None,
	request_id: str | None = None,
):
	resolved_output = _resolve_output(output)
	if resolved_output != PRINT_OUTPUT_PDF:
		frappe.throw(_("批量打印当前仅支持 PDF 输出。"))
	items = _coerce_print_batch_items(documents, default_template=template)
	resolved_request_id = _normalize_print_batch_request_id(request_id)
	if not _print_batch_table_exists():
		return {
			"status": "success",
			"message": _("打印批次表尚未创建，已跳过批次创建。"),
			"data": {
				"queued": False,
				"reason": "table_missing",
				"total_count": len(items),
			},
		}

	if resolved_request_id:
		existing_batch = _get_print_batch_by_request_id(_current_user(), resolved_request_id)
		if existing_batch:
			batch = get_print_batch_v1(existing_batch["name"])
			batch["data"]["deduplicated"] = True
			batch["data"]["request_id"] = resolved_request_id
			return batch

	try:
		batch_name = _insert_print_batch(
			items=items,
			output=resolved_output,
			metadata=metadata,
			request_id=resolved_request_id,
		)
	except Exception:
		if resolved_request_id:
			existing_batch = _get_print_batch_by_request_id(_current_user(), resolved_request_id)
			if existing_batch:
				batch = get_print_batch_v1(existing_batch["name"])
				batch["data"]["deduplicated"] = True
				batch["data"]["request_id"] = resolved_request_id
				return batch
		raise
	should_enqueue = _coerce_bool_flag(run_async)
	enqueue_job_id = None
	if should_enqueue:
		enqueue_job_id = _enqueue_print_batch(batch_name)
		_update_print_batch_enqueue_job_id(batch_name, enqueue_job_id)
	else:
		process_print_batch_v1(batch_name)

	batch = get_print_batch_v1(batch_name)
	return {
		"status": "success",
		"message": _("批量打印任务已创建。"),
		"data": {
			**batch["data"],
			"queued": should_enqueue,
			"enqueue_job_id": enqueue_job_id or batch["data"].get("enqueue_job_id"),
			"deduplicated": False,
			"request_id": resolved_request_id,
		},
	}


def get_print_batch_v1(batch_id: str):
	resolved_batch_id = _normalize_required_str(batch_id, field_label="batch_id")
	if not _print_batch_table_exists():
		return {
			"status": "success",
			"message": _("打印批次表尚未创建。"),
			"data": {
				"batch_id": resolved_batch_id,
				"table_ready": False,
			},
		}
	row = _get_print_batch_row(resolved_batch_id)
	if not row:
		raise frappe.DoesNotExistError(_("打印批次 {0} 不存在。").format(resolved_batch_id))
	_require_print_batch_access(row)
	return {
		"status": "success",
		"message": _("打印批次已获取。"),
		"data": _serialize_print_batch(row),
	}


def list_print_batches_v1(
	status: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	requested_by: str | None = None,
	start: int = 0,
	limit: int = 20,
):
	if not _print_batch_table_exists():
		return {
			"status": "success",
			"message": _("打印批次表尚未创建。"),
			"data": {"batches": [], "count": 0, "total": 0, "table_ready": False},
		}

	conditions = []
	values: list = []
	resolved_status = (status or "").strip().lower()
	if resolved_status:
		if resolved_status not in PRINT_BATCH_STATUSES:
			frappe.throw(_("不支持的打印批次状态。"))
		conditions.append("status = %s")
		values.append(resolved_status)

	current_user = _current_user()
	resolved_requested_by = (requested_by or "").strip()
	if _is_system_manager():
		if resolved_requested_by:
			conditions.append("requested_by = %s")
			values.append(resolved_requested_by)
	else:
		conditions.append("requested_by = %s")
		values.append(current_user)

	if date_from:
		conditions.append("requested_at >= %s")
		values.append(get_datetime(date_from))
	if date_to:
		conditions.append("requested_at <= %s")
		values.append(get_datetime(date_to))

	where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
	resolved_start = _coerce_non_negative_int(start, default=0, maximum=100000)
	resolved_limit = _coerce_positive_int(limit, default=20, maximum=100)
	count_rows = frappe.db.sql(
		f"SELECT COUNT(*) AS total FROM `tabMyApp Print Batch` {where_clause}",
		tuple(values),
		as_dict=True,
	)
	total = int(count_rows[0].get("total") or 0) if count_rows else 0
	rows = frappe.db.sql(
		f"""
		SELECT
			name, creation, modified, owner, status, output, request_id, requested_by, requested_at,
			started_at, completed_at, enqueue_job_id, total_count, success_count,
			failed_count, skipped_count, items_json, results_json, metadata_json, error
		FROM `tabMyApp Print Batch`
		{where_clause}
		ORDER BY requested_at DESC, creation DESC
		LIMIT %s OFFSET %s
		""",
		tuple([*values, resolved_limit, resolved_start]),
		as_dict=True,
	)
	batches = [_serialize_print_batch_summary(row) for row in rows]
	return {
		"status": "success",
		"message": _("打印批次列表已获取。"),
		"data": {
			"batches": batches,
			"count": len(batches),
			"total": total,
			"start": resolved_start,
			"limit": resolved_limit,
			"table_ready": True,
		},
	}


def cancel_print_batch_v1(batch_id: str):
	resolved_batch_id = _normalize_required_str(batch_id, field_label="batch_id")
	if not _print_batch_table_exists():
		return {
			"status": "success",
			"message": _("打印批次表尚未创建。"),
			"data": {
				"batch_id": resolved_batch_id,
				"canceled": False,
				"reason": "table_missing",
			},
		}
	row = _get_print_batch_row(resolved_batch_id)
	if not row:
		raise frappe.DoesNotExistError(_("打印批次 {0} 不存在。").format(resolved_batch_id))
	_require_print_batch_access(row)

	current_status = row.get("status")
	if current_status == "queued":
		items = _parse_json_list(row.get("items_json"))
		results = [_build_skipped_print_batch_result(item, reason="canceled") for item in items]
		_update_print_batch_results(
			resolved_batch_id,
			results=results,
			success_count=0,
			failed_count=0,
			skipped_count=len(results),
			final_status="canceled",
			completed=True,
		)
		return {
			"status": "success",
			"message": _("打印批次已取消。"),
			"data": {
				"batch_id": resolved_batch_id,
				"canceled": True,
				"status": "canceled",
			},
		}
	if current_status == "processing":
		_update_print_batch_status(resolved_batch_id, "cancel_requested")
		return {
			"status": "success",
			"message": _("打印批次已请求取消，当前正在处理的单据完成后停止后续单据。"),
			"data": {
				"batch_id": resolved_batch_id,
				"canceled": False,
				"cancel_requested": True,
				"status": "cancel_requested",
			},
		}
	return {
		"status": "success",
		"message": _("当前批次状态不需要取消。"),
		"data": {
			"batch_id": resolved_batch_id,
			"canceled": current_status == "canceled",
			"status": current_status,
			"reason": "final_or_not_cancellable",
		},
	}


def retry_print_batch_failed_v1(
	batch_id: str,
	run_async: bool | int | str = True,
	metadata: dict | str | None = None,
):
	resolved_batch_id = _normalize_required_str(batch_id, field_label="batch_id")
	batch = get_print_batch_v1(resolved_batch_id)
	data = batch["data"]
	if not data.get("table_ready"):
		return {
			"status": "success",
			"message": _("打印批次表尚未创建。"),
			"data": {
				"queued": False,
				"reason": "table_missing",
				"retry_of": resolved_batch_id,
			},
		}
	failed_results = [item for item in data.get("results") or [] if item.get("status") == "failed"]
	if not failed_results:
		frappe.throw(_("该打印批次没有失败项可重试。"))

	retry_documents = [
		{
			"doctype": item.get("doctype"),
			"docname": item.get("docname"),
			"template": item.get("template"),
			"filename": item.get("filename"),
		}
		for item in failed_results
	]
	retry_metadata = _merge_retry_metadata(metadata, retry_of=resolved_batch_id)
	result = create_print_batch_v1(
		documents=retry_documents,
		output=data.get("output") or PRINT_OUTPUT_PDF,
		run_async=run_async,
		metadata=retry_metadata,
		request_id=None,
	)
	result["data"]["retry_of"] = resolved_batch_id
	return result


def process_print_batch_v1(batch_name: str):
	resolved_batch_id = _normalize_required_str(batch_name, field_label="batch_name")
	if not _print_batch_table_exists():
		return {"status": "skipped", "reason": "table_missing", "batch_id": resolved_batch_id}
	row = _get_print_batch_row(resolved_batch_id)
	if not row:
		raise frappe.DoesNotExistError(_("打印批次 {0} 不存在。").format(resolved_batch_id))

	initial_status = row.get("status")
	if initial_status in {"completed", "partial_failed", "failed", "canceled"}:
		return {"status": initial_status, "batch_id": resolved_batch_id, "already_final": True}

	requested_by = row.get("requested_by")
	if requested_by:
		try:
			frappe.set_user(requested_by)
		except Exception:
			pass

	items = _parse_json_list(row.get("items_json"))
	if initial_status != "cancel_requested":
		_update_print_batch_status(resolved_batch_id, "processing", started=True)
	results = []
	success_count = 0
	failed_count = 0
	skipped_count = 0
	for item in items:
		if _is_print_batch_cancel_requested(resolved_batch_id):
			result = _build_skipped_print_batch_result(item, reason="canceled")
			results.append(result)
			skipped_count += 1
			continue
		result = _process_print_batch_item(resolved_batch_id, item)
		results.append(result)
		if result["status"] == "success":
			success_count += 1
		elif result["status"] == "skipped":
			skipped_count += 1
		else:
			failed_count += 1
		_update_print_batch_results(
			resolved_batch_id,
			results=results,
			success_count=success_count,
			failed_count=failed_count,
			skipped_count=skipped_count,
			final_status="processing",
		)

	if skipped_count and _is_print_batch_cancel_requested(resolved_batch_id):
		final_status = "canceled"
	elif failed_count:
		final_status = "failed" if success_count == 0 and skipped_count == 0 else "partial_failed"
	else:
		final_status = "completed"
	_update_print_batch_results(
		resolved_batch_id,
		results=results,
		success_count=success_count,
		failed_count=failed_count,
		skipped_count=skipped_count,
		final_status=final_status,
		completed=True,
	)
	return {
		"status": final_status,
		"batch_id": resolved_batch_id,
		"total_count": len(items),
		"success_count": success_count,
		"failed_count": failed_count,
		"skipped_count": skipped_count,
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


def list_print_jobs_v2(
	doctype: str | None = None,
	docname: str | None = None,
	action: str | None = None,
	status: str | None = None,
	template: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	user: str | None = None,
	start: int = 0,
	limit: int = 20,
):
	if not _print_job_table_exists():
		return {
			"status": "success",
			"message": _("打印记录表尚未创建。"),
			"data": {"jobs": [], "count": 0, "total": 0, "table_ready": False},
		}

	conditions = []
	values: list = []
	resolved_doctype = (doctype or "").strip()
	resolved_docname = (docname or "").strip()
	if resolved_docname and not resolved_doctype:
		frappe.throw(_("按单据号筛选时必须同时提供 doctype。"))
	if resolved_doctype:
		conditions.append("reference_doctype = %s")
		values.append(resolved_doctype)
	if resolved_docname:
		_load_print_document(resolved_doctype, resolved_docname)
		conditions.append("reference_name = %s")
		values.append(resolved_docname)

	resolved_action = (action or "").strip().lower()
	if resolved_action:
		if resolved_action not in PRINT_JOB_ACTIONS:
			frappe.throw(_("不支持的打印动作。"))
		conditions.append("action = %s")
		values.append(resolved_action)
	resolved_status = (status or "").strip().lower()
	if resolved_status:
		if resolved_status not in PRINT_JOB_STATUSES:
			frappe.throw(_("不支持的打印记录状态。"))
		conditions.append("status = %s")
		values.append(resolved_status)
	resolved_template = (template or "").strip()
	if resolved_template:
		conditions.append("template = %s")
		values.append(resolved_template)

	current_user = _current_user()
	resolved_user = (user or "").strip()
	if _is_system_manager():
		if resolved_user:
			conditions.append("printed_by = %s")
			values.append(resolved_user)
	else:
		conditions.append("printed_by = %s")
		values.append(current_user)

	if date_from:
		conditions.append("printed_at >= %s")
		values.append(get_datetime(date_from))
	if date_to:
		conditions.append("printed_at <= %s")
		values.append(get_datetime(date_to))

	where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
	resolved_start = _coerce_non_negative_int(start, default=0, maximum=100000)
	resolved_limit = _coerce_positive_int(limit, default=20, maximum=100)
	count_rows = frappe.db.sql(
		f"SELECT COUNT(*) AS total FROM `tabMyApp Print Job` {where_clause}",
		tuple(values),
		as_dict=True,
	)
	total = int(count_rows[0].get("total") or 0) if count_rows else 0
	rows = frappe.db.sql(
		f"""
		SELECT
			name, reference_doctype, reference_name, template, template_label, print_format,
			action, output, status, filename, file_url, printed_by, printed_at, error, metadata_json
		FROM `tabMyApp Print Job`
		{where_clause}
		ORDER BY printed_at DESC, creation DESC
		LIMIT %s OFFSET %s
		""",
		tuple([*values, resolved_limit, resolved_start]),
		as_dict=True,
	)
	jobs = [_serialize_print_job(row) for row in rows]
	return {
		"status": "success",
		"message": _("打印历史已获取。"),
		"data": {
			"jobs": jobs,
			"count": len(jobs),
			"total": total,
			"start": resolved_start,
			"limit": resolved_limit,
			"table_ready": True,
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


def build_print_batch_archive_download_v1(batch_id: str, filename: str | None = None):
	batch = get_print_batch_v1(batch_id)
	data = batch["data"]
	if not data.get("table_ready"):
		frappe.throw(_("打印批次表尚未创建。"))
	results = data.get("results") or []
	successful_results = [item for item in results if item.get("status") == "success" and item.get("file_url")]
	if not successful_results:
		frappe.throw(_("该打印批次没有可下载的成功文件。"))

	buffer = BytesIO()
	used_names = set()
	with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
		for item in successful_results:
			archive_name = _resolve_zip_entry_name(item, used_names)
			archive.writestr(archive_name, _read_file_url_bytes(item["file_url"]))

	resolved_filename = _normalize_zip_filename(filename) or f"{data['batch_id']}.zip"
	return {
		"filename": resolved_filename,
		"content": buffer.getvalue(),
		"batch_id": data["batch_id"],
		"file_count": len(successful_results),
		"mime_type": "application/zip",
	}


def build_print_batch_merged_pdf_v1(batch_id: str, filename: str | None = None):
	from pypdf import PdfReader, PdfWriter

	batch = get_print_batch_v1(batch_id)
	data = batch["data"]
	if not data.get("table_ready"):
		frappe.throw(_("打印批次表尚未创建。"))
	results = data.get("results") or []
	successful_results = [item for item in results if item.get("status") == "success" and item.get("file_url")]
	if not successful_results:
		frappe.throw(_("该打印批次没有可合并的成功文件。"))

	writer = PdfWriter()
	for item in successful_results:
		reader = PdfReader(BytesIO(_read_file_url_bytes(item["file_url"])))
		for page in reader.pages:
			writer.add_page(page)
	buffer = BytesIO()
	writer.write(buffer)
	resolved_filename = _normalize_pdf_filename(filename) or f"{data['batch_id']}-merged.pdf"
	return {
		"filename": resolved_filename,
		"content": buffer.getvalue(),
		"batch_id": data["batch_id"],
		"file_count": len(successful_results),
		"page_count": len(writer.pages),
		"mime_type": "application/pdf",
	}


def cleanup_expired_print_batches(
	retention_days: int = PRINT_BATCH_CLEANUP_RETENTION_DAYS,
	batch_size: int = PRINT_BATCH_CLEANUP_BATCH_SIZE,
	delete_archived_files: bool | int | str = True,
):
	if not _print_batch_table_exists():
		return {
			"status": "success",
			"data": {
				"deleted_count": 0,
				"deleted_file_count": 0,
				"table_ready": False,
			},
		}

	resolved_retention_days = _coerce_positive_int(
		retention_days,
		default=PRINT_BATCH_CLEANUP_RETENTION_DAYS,
		maximum=3650,
	)
	resolved_batch_size = _coerce_positive_int(
		batch_size,
		default=PRINT_BATCH_CLEANUP_BATCH_SIZE,
		maximum=500,
	)
	cutoff = add_days(now_datetime(), -resolved_retention_days)
	rows = frappe.db.sql(
		"""
		SELECT name, results_json
		FROM `tabMyApp Print Batch`
		WHERE status IN ('completed', 'partial_failed', 'failed', 'canceled')
			AND COALESCE(completed_at, modified, creation) < %s
		ORDER BY COALESCE(completed_at, modified, creation) ASC
		LIMIT %s
		""",
		(cutoff, resolved_batch_size),
		as_dict=True,
	)
	if not rows:
		return {
			"status": "success",
			"data": {
				"deleted_count": 0,
				"deleted_file_count": 0,
				"table_ready": True,
				"retention_days": resolved_retention_days,
				"batch_size": resolved_batch_size,
			},
		}

	deleted_file_count = 0
	if _coerce_bool_flag(delete_archived_files):
		deleted_file_count = _delete_print_batch_archived_files(rows)
	batch_names = [row.get("name") for row in rows if row.get("name")]
	frappe.db.sql(
		"""
		DELETE FROM `tabMyApp Print Batch`
		WHERE name IN %s
		""",
		(batch_names,),
	)
	frappe.db.commit()
	return {
		"status": "success",
		"data": {
			"deleted_count": len(batch_names),
			"deleted_file_count": deleted_file_count,
			"table_ready": True,
			"retention_days": resolved_retention_days,
			"batch_size": resolved_batch_size,
		},
	}


def _normalize_required_str(value: str | None, *, field_label: str):
	resolved = (value or "").strip()
	if not resolved:
		frappe.throw(_("{0} 不能为空。").format(field_label))
	return resolved


def _coerce_print_batch_items(documents, *, default_template: str | None):
	raw_items = _parse_documents_payload(documents)
	if not raw_items:
		frappe.throw(_("批量打印单据不能为空。"))
	if len(raw_items) > MAX_PRINT_BATCH_ITEMS:
		frappe.throw(_("单个批量打印任务最多支持 {0} 张单据。").format(MAX_PRINT_BATCH_ITEMS))

	items = []
	for index, item in enumerate(raw_items, start=1):
		if not isinstance(item, dict):
			frappe.throw(_("批量打印单据第 {0} 行格式不正确。").format(index))
		doctype = _normalize_required_str(item.get("doctype"), field_label=f"documents[{index}].doctype")
		docname = _normalize_required_str(
			item.get("docname") or item.get("name"),
			field_label=f"documents[{index}].docname",
		)
		template = _normalize_optional_str(item.get("template")) or _normalize_optional_str(default_template)
		template_info = resolve_print_template(doctype, template)
		items.append(
			{
				"idx": index,
				"doctype": doctype,
				"docname": docname,
				"template": template_info["key"],
				"template_label": template_info.get("label"),
				"print_format": template_info.get("print_format"),
				"filename": _normalize_optional_str(item.get("filename")),
			}
		)
	return items


def _parse_documents_payload(documents):
	if isinstance(documents, str):
		try:
			documents = json.loads(documents)
		except Exception:
			frappe.throw(_("批量打印单据参数不是有效 JSON。"))
	if isinstance(documents, dict):
		if isinstance(documents.get("documents"), list):
			return documents.get("documents")
		return [documents]
	if isinstance(documents, (list, tuple)):
		return list(documents)
	frappe.throw(_("批量打印单据参数格式不正确。"))


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


def _normalize_print_batch_request_id(value):
	resolved = _normalize_optional_str(value)
	if not resolved:
		return None
	if len(resolved) > 140:
		frappe.throw(_("request_id 长度不能超过 140 个字符。"))
	return resolved


def _coerce_positive_int(value, *, default: int, maximum: int):
	try:
		resolved = int(value)
	except Exception:
		return default
	if resolved <= 0:
		return default
	return min(resolved, maximum)


def _coerce_non_negative_int(value, *, default: int, maximum: int):
	try:
		resolved = int(value)
	except Exception:
		return default
	if resolved < 0:
		return default
	return min(resolved, maximum)


def _coerce_metadata_json(metadata):
	if metadata is None or metadata == "":
		return None
	if isinstance(metadata, str):
		return metadata
	return json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str)


def _insert_print_batch(*, items: list[dict], output: str, metadata, request_id: str | None = None):
	now = now_datetime()
	user = _current_user()
	batch_name = f"PRN-BATCH-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
	frappe.db.sql(
		"""
		INSERT INTO `tabMyApp Print Batch`
			(`name`, `creation`, `modified`, `modified_by`, `owner`, `docstatus`, `idx`,
			 `status`, `output`, `request_id`, `requested_by`, `requested_at`, `total_count`,
			 `success_count`, `failed_count`, `skipped_count`, `items_json`, `results_json`,
			 `metadata_json`)
		VALUES
			(%s, %s, %s, %s, %s, 0, 0,
			 'queued', %s, %s, %s, %s, %s,
			 0, 0, 0, %s, %s, %s)
		""",
		(
			batch_name,
			now,
			now,
			user,
			user,
			output,
			request_id,
			user,
			now,
			len(items),
			json.dumps(items, ensure_ascii=False, sort_keys=True, default=str),
			"[]",
			_coerce_metadata_json(metadata),
		),
	)
	frappe.db.commit()
	return batch_name


def _get_print_batch_by_request_id(requested_by: str, request_id: str):
	rows = frappe.db.sql(
		"""
		SELECT name
		FROM `tabMyApp Print Batch`
		WHERE requested_by = %s AND request_id = %s
		LIMIT 1
		""",
		(requested_by, request_id),
		as_dict=True,
	)
	return rows[0] if rows else None


def _enqueue_print_batch(batch_name: str):
	job = frappe.enqueue(
		"myapp.services.printing_service.process_print_batch_v1",
		queue="long",
		timeout=1800,
		job_name=f"myapp-print-batch-{batch_name}",
		batch_name=batch_name,
	)
	return getattr(job, "id", None) or getattr(job, "job_id", None) or str(job or "")


def _update_print_batch_enqueue_job_id(batch_name: str, enqueue_job_id: str | None):
	if not enqueue_job_id:
		return
	now = now_datetime()
	frappe.db.sql(
		"""
		UPDATE `tabMyApp Print Batch`
		SET enqueue_job_id = %s, modified = %s, modified_by = %s
		WHERE name = %s
		""",
		(enqueue_job_id, now, _current_user(), batch_name),
	)
	frappe.db.commit()


def _get_print_batch_row(batch_name: str):
	rows = frappe.db.sql(
		"""
		SELECT
			name, creation, modified, owner, status, output, request_id, requested_by, requested_at,
			started_at, completed_at, enqueue_job_id, total_count, success_count,
			failed_count, skipped_count, items_json, results_json, metadata_json, error
		FROM `tabMyApp Print Batch`
		WHERE name = %s
		LIMIT 1
		""",
		(batch_name,),
		as_dict=True,
	)
	return rows[0] if rows else None


def _update_print_batch_status(batch_name: str, status: str, *, started: bool = False):
	now = now_datetime()
	set_parts = ["status = %s", "modified = %s", "modified_by = %s"]
	values = [status, now, _current_user()]
	if started:
		set_parts.append("started_at = COALESCE(started_at, %s)")
		values.append(now)
	values.append(batch_name)
	frappe.db.sql(
		f"""
		UPDATE `tabMyApp Print Batch`
		SET {", ".join(set_parts)}
		WHERE name = %s
		""",
		tuple(values),
	)
	frappe.db.commit()


def _update_print_batch_results(
	batch_name: str,
	*,
	results: list[dict],
	success_count: int,
	failed_count: int,
	skipped_count: int,
	final_status: str,
	completed: bool = False,
):
	now = now_datetime()
	set_parts = [
		"status = %s",
		"success_count = %s",
		"failed_count = %s",
		"skipped_count = %s",
		"results_json = %s",
		"modified = %s",
		"modified_by = %s",
	]
	values = [
		final_status,
		success_count,
		failed_count,
		skipped_count,
		json.dumps(results, ensure_ascii=False, sort_keys=True, default=str),
		now,
		_current_user(),
	]
	if completed:
		set_parts.append("completed_at = %s")
		values.append(now)
	values.append(batch_name)
	frappe.db.sql(
		f"""
		UPDATE `tabMyApp Print Batch`
		SET {", ".join(set_parts)}
		WHERE name = %s
		""",
		tuple(values),
	)
	frappe.db.commit()


def _process_print_batch_item(batch_name: str, item: dict):
	doctype = item.get("doctype")
	docname = item.get("docname")
	template = item.get("template")
	try:
		file_result = get_print_file_v1(
			doctype=doctype,
			docname=docname,
			template=template,
			filename=item.get("filename"),
			archive=True,
		)
		file_data = file_result["data"]
		record_print_job_v1(
			doctype=doctype,
			docname=docname,
			template=template,
			action="archive",
			output=PRINT_OUTPUT_PDF,
			status="success",
			filename=file_data.get("filename"),
			file_url=file_data.get("file_url"),
			metadata={"batch_id": batch_name, "batch_idx": item.get("idx")},
		)
		return {
			"idx": item.get("idx"),
			"doctype": doctype,
			"docname": docname,
			"template": template,
			"status": "success",
			"filename": file_data.get("filename"),
			"file_url": file_data.get("file_url"),
			"file_size": file_data.get("file_size"),
		}
	except Exception as exc:
		error = str(exc)
		try:
			record_print_job_v1(
				doctype=doctype,
				docname=docname,
				template=template,
				action="archive",
				output=PRINT_OUTPUT_PDF,
				status="failed",
				error=error,
				metadata={"batch_id": batch_name, "batch_idx": item.get("idx")},
			)
		except Exception:
			pass
		return {
			"idx": item.get("idx"),
			"doctype": doctype,
			"docname": docname,
			"template": template,
			"status": "failed",
			"error": error,
		}


def _is_print_batch_cancel_requested(batch_name: str):
	row = _get_print_batch_row(batch_name)
	return bool(row and row.get("status") in {"cancel_requested", "canceled"})


def _build_skipped_print_batch_result(item: dict, *, reason: str):
	return {
		"idx": item.get("idx"),
		"doctype": item.get("doctype"),
		"docname": item.get("docname"),
		"template": item.get("template"),
		"status": "skipped",
		"reason": reason,
	}


def _merge_retry_metadata(metadata, *, retry_of: str):
	base = {}
	if isinstance(metadata, dict):
		base.update(metadata)
	elif metadata:
		base["source_metadata"] = metadata
	base["retry_of"] = retry_of
	return base


def _resolve_zip_entry_name(item: dict, used_names: set[str]):
	base_name = _safe_archive_filename(
		item.get("filename")
		or f"{item.get('doctype') or 'document'}-{item.get('docname') or item.get('idx') or 'print'}.pdf"
	)
	if not base_name.lower().endswith(".pdf"):
		base_name = f"{base_name}.pdf"
	name = base_name
	counter = 2
	while name in used_names:
		stem = base_name[:-4]
		name = f"{stem}-{counter}.pdf"
		counter += 1
	used_names.add(name)
	return name


def _safe_archive_filename(value):
	resolved = Path(str(value or "print.pdf")).name.strip()
	resolved = "".join(char if char.isalnum() or char in "._- " else "-" for char in resolved)
	resolved = resolved.strip(" .-")
	return resolved or "print.pdf"


def _normalize_zip_filename(value):
	if not value:
		return None
	resolved = _safe_archive_filename(value)
	if not resolved.lower().endswith(".zip"):
		resolved = f"{resolved}.zip"
	return resolved


def _normalize_pdf_filename(value):
	if not value:
		return None
	resolved = _safe_archive_filename(value)
	if not resolved.lower().endswith(".pdf"):
		resolved = f"{resolved}.pdf"
	return resolved


def _read_file_url_bytes(file_url: str):
	resolved_file_url = _normalize_required_str(file_url, field_label="file_url")
	file_rows = frappe.get_all("File", filters={"file_url": resolved_file_url}, fields=["name"], limit=1)
	if file_rows:
		try:
			content = frappe.get_doc("File", file_rows[0]["name"]).get_content()
			if isinstance(content, bytes):
				return content
			if isinstance(content, str):
				return content.encode()
		except Exception:
			pass
	relative_path = None
	if resolved_file_url.startswith("/private/files/"):
		relative_path = ("private", "files", Path(resolved_file_url).name)
	elif resolved_file_url.startswith("/files/"):
		relative_path = ("public", "files", Path(resolved_file_url).name)
	if not relative_path:
		frappe.throw(_("不支持的打印文件地址：{0}").format(resolved_file_url))
	path = Path(frappe.get_site_path(*relative_path))
	if not path.exists() or not path.is_file():
		frappe.throw(_("打印文件不存在：{0}").format(resolved_file_url))
	return path.read_bytes()


def _delete_print_batch_archived_files(rows):
	file_urls = []
	for row in rows:
		for result in _parse_json_list(row.get("results_json")):
			if result.get("status") == "success" and result.get("file_url"):
				file_urls.append(result["file_url"])
	if not file_urls:
		return 0

	deleted_count = 0
	seen = set()
	for file_url in file_urls:
		if file_url in seen:
			continue
		seen.add(file_url)
		try:
			file_rows = frappe.get_all("File", filters={"file_url": file_url}, fields=["name"], limit=1)
			if not file_rows:
				continue
			frappe.delete_doc("File", file_rows[0]["name"], ignore_permissions=True)
			deleted_count += 1
		except Exception:
			continue
	return deleted_count


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
	try:
		session = getattr(frappe, "session", None)
		user = getattr(session, "user", None)
	except Exception:
		user = None
	return user if isinstance(user, str) and user else "Administrator"


def _is_system_manager():
	try:
		return "System Manager" in set(frappe.get_roles() or [])
	except Exception:
		return False


def _require_print_batch_access(row):
	requested_by = (row.get("requested_by") or "").strip()
	if requested_by and requested_by == _current_user():
		return
	if _is_system_manager():
		return
	raise frappe.PermissionError(_("无权访问该打印批次。"))


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


def _print_batch_table_exists():
	try:
		return bool(frappe.db.table_exists(PRINT_BATCH_TABLE))
	except Exception:
		return False


def _print_setting_table_exists():
	try:
		return bool(frappe.db.table_exists(PRINT_SETTING_TABLE))
	except Exception:
		return False


def _get_print_settings():
	if not _print_setting_table_exists():
		return []
	rows = frappe.db.sql(
		"""
		SELECT name, reference_doctype, default_template, enabled, metadata_json, modified, modified_by
		FROM `tabMyApp Print Setting`
		ORDER BY reference_doctype ASC
		""",
		as_dict=True,
	)
	return [_serialize_print_setting(row) for row in rows]


def _serialize_print_setting(row):
	return {
		"name": row.get("name"),
		"doctype": row.get("reference_doctype"),
		"default_template": row.get("default_template"),
		"enabled": bool(row.get("enabled")),
		"metadata": _parse_json_value(row.get("metadata_json")),
		"modified": row.get("modified"),
		"modified_by": row.get("modified_by"),
	}


def _require_print_settings_manager():
	try:
		roles = set(frappe.get_roles() or [])
	except Exception:
		roles = set()
	if "System Manager" not in roles:
		raise frappe.PermissionError(_("只有 System Manager 可以维护打印设置。"))


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


def _serialize_print_batch(row):
	items = _parse_json_list(row.get("items_json"))
	results = _parse_json_list(row.get("results_json"))
	metadata = _parse_json_value(row.get("metadata_json"))
	total_count = int(row.get("total_count") or len(items) or 0)
	success_count = int(row.get("success_count") or 0)
	failed_count = int(row.get("failed_count") or 0)
	skipped_count = int(row.get("skipped_count") or 0)
	done_count = success_count + failed_count + skipped_count
	return {
		"batch_id": row.get("name"),
		"status": row.get("status"),
		"output": row.get("output"),
		"request_id": row.get("request_id"),
		"requested_by": row.get("requested_by"),
		"requested_at": row.get("requested_at"),
		"started_at": row.get("started_at"),
		"completed_at": row.get("completed_at"),
		"enqueue_job_id": row.get("enqueue_job_id"),
		"total_count": total_count,
		"success_count": success_count,
		"failed_count": failed_count,
		"skipped_count": skipped_count,
		"done_count": done_count,
		"progress": (done_count / total_count) if total_count else 0,
		"items": items,
		"results": results,
		"metadata": metadata,
		"error": row.get("error"),
		"table_ready": True,
	}


def _serialize_print_batch_summary(row):
	data = _serialize_print_batch(row)
	items = data.pop("items", [])
	data.pop("results", None)
	data["doctypes"] = list(dict.fromkeys(item.get("doctype") for item in items if item.get("doctype")))
	data["document_names"] = [item.get("docname") for item in items[:5] if item.get("docname")]
	return data


def _parse_json_list(value):
	parsed = _parse_json_value(value)
	return parsed if isinstance(parsed, list) else []


def _parse_json_value(value):
	if value is None or value == "":
		return None
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except Exception:
		return value


def _load_print_document(doctype: str, docname: str):
	if not frappe.db.exists(doctype, docname):
		raise frappe.DoesNotExistError(_("{0} {1} 不存在。").format(doctype, docname))

	document = frappe.get_doc(doctype, docname)
	if not frappe.has_permission(doctype, ptype="read", doc=document):
		raise frappe.PermissionError(_("你没有权限打印该单据。"))
	_attach_printing_derived_fields(document)
	return document


def _attach_printing_derived_fields(document):
	amount_value = None
	for fieldname in ("rounded_total", "grand_total", "received_amount", "paid_amount"):
		candidate = getattr(document, fieldname, None)
		if candidate is not None:
			amount_value = candidate
			break
	total_amount = _coerce_decimal_print_amount(amount_value)
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
				SUM(
					CASE
						WHEN status = 'success' AND action IN ('download', 'print', 'share', 'archive') THEN 1
						ELSE 0
					END
				) AS successful_count,
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
	_attach_print_template_fields(document, template_info)
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
	_attach_print_template_fields(document, template_info)
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


def _attach_print_template_fields(document, template_info: dict):
	document.myapp_print_template_key = template_info.get("key")
	document.myapp_print_template_label = template_info.get("label")
	document.myapp_print_template_category = template_info.get("category")
	document.myapp_print_format = template_info.get("print_format")


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
