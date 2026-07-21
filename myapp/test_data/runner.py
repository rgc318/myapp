from __future__ import annotations

import traceback

import frappe
from frappe.utils import now_datetime
from frappe.utils.background_jobs import get_redis_conn

from myapp.test_data.catalog import get_dataset, normalize_scale
from myapp.test_data.generator import generate_dataset
from myapp.test_data.registry import (
	clear_run_progress,
	get_run,
	get_run_progress,
	json_dumps,
	json_loads,
	list_active_objects,
	mark_object_deleted,
	set_run_progress,
	update_run,
)
from myapp.test_data.validator import validate_active_dataset


LOCK_TIMEOUT_SECONDS = 60 * 60


def _progress_total(dataset, *, action: str, selected_scenario_count: int, scenario_copies: int) -> int:
	master_step_count = 0 if action == "supplement" else (
		len(dataset.customers) + len(dataset.suppliers) + len(dataset.items)
	)
	return master_step_count + (selected_scenario_count * scenario_copies) + 1 + (1 if action == "reset" else 0)


def _delete_registered_objects(*, company: str, dataset_code: str) -> dict:
	objects = list_active_objects(company=company, dataset_code=dataset_code)
	deleted_counts = {}
	for row in reversed(objects):
		if frappe.db.exists(row.doctype_name, row.document_name):
			doc = frappe.get_doc(row.doctype_name, row.document_name)
			doc.flags.ignore_permissions = True
			if getattr(doc, "docstatus", 0) == 1:
				doc.cancel()
			frappe.delete_doc(row.doctype_name, row.document_name, ignore_permissions=True, force=True)
			deleted_counts[row.doctype_name] = deleted_counts.get(row.doctype_name, 0) + 1
		mark_object_deleted(row.name)
	return {"object_count": len(objects), "counts": dict(sorted(deleted_counts.items()))}


def _acquire_lock(company: str):
	lock = get_redis_conn().lock(
		f"myapp:test-data:{frappe.local.site}:{company}",
		timeout=LOCK_TIMEOUT_SECONDS,
		blocking_timeout=1,
	)
	if not lock.acquire(blocking=True):
		frappe.throw("同一公司已有测试数据任务正在执行。")
	return lock


def execute_run(run_name: str) -> dict:
	run = get_run(run_name)
	if not run:
		raise frappe.DoesNotExistError(f"测试数据任务不存在：{run_name}")
	if run.status not in {"queued", "failed"}:
		return {"status": run.status, "run_name": run_name}

	frappe.set_user(run.requested_by)
	lock = _acquire_lock(run.company)
	progress_current = 0
	progress_total = 0
	progress_message = "准备执行测试数据任务"
	try:
		dataset = get_dataset(run.dataset_code)
		scale_profile, scenario_copies = normalize_scale(run.scale, default=dataset.scale)
		scenario_keys = json_loads(getattr(run, "scenario_keys_json", None), [])
		selected_scenario_count = (
			len(scenario_keys) if run.action == "supplement" else len(dataset.scenarios)
		)
		progress_total = _progress_total(
			dataset,
			action=run.action,
			selected_scenario_count=selected_scenario_count,
			scenario_copies=scenario_copies,
		)
		set_run_progress(
			run_name,
			current=progress_current,
			total=progress_total,
			message=progress_message,
		)
		update_run(
			run_name,
			status="running",
			started_at=now_datetime(),
			error_text=None,
			progress_current=progress_current,
			progress_total=progress_total,
			progress_message=progress_message,
		)
		frappe.db.commit()

		def advance(message: str) -> None:
			nonlocal progress_current, progress_message
			progress_current += 1
			progress_message = message
			set_run_progress(
				run_name,
				current=progress_current,
				total=progress_total,
				message=progress_message,
			)

		cleanup_result = None
		if run.action == "reset":
			cleanup_result = _delete_registered_objects(company=run.company, dataset_code=run.dataset_code)
			advance(f"已清理 {cleanup_result['object_count']} 个旧模板对象")

		generation_result = generate_dataset(
			run_name=run_name,
			company=run.company,
			warehouse=run.warehouse,
			base_date=run.base_date,
			dataset=dataset,
			create_masters=run.action != "supplement",
			scenario_keys=scenario_keys if run.action == "supplement" else None,
			scale=scale_profile,
			scenario_copies=scenario_copies,
			progress_callback=advance,
		)
		progress_message = "正在验证活动测试数据集"
		set_run_progress(
			run_name,
			current=progress_current,
			total=progress_total,
			message=progress_message,
		)
		validation = validate_active_dataset(run.company, run.dataset_code)
		if not validation["passed"]:
			frappe.throw("生成后的数据完整性验证失败。")
		advance("测试数据完整性验证通过")
		result = {
			"cleanup": cleanup_result,
			"generation": generation_result,
			"validation": validation,
		}
		clear_run_progress(run_name)
		update_run(
			run_name,
			status="completed",
			completed_at=now_datetime(),
			result_json=json_dumps(result),
			error_text=None,
			progress_current=progress_current,
			progress_total=progress_total,
			progress_message=progress_message,
		)
		frappe.db.commit()
		return result
	except Exception as exc:
		frappe.db.rollback()
		progress = get_run_progress(
			run_name,
			fallback={"current": progress_current, "total": progress_total, "message": progress_message},
		)
		error_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-12000:]
		clear_run_progress(run_name)
		update_run(
			run_name,
			status="failed",
			completed_at=now_datetime(),
			error_text=error_text,
			progress_current=progress["current"],
			progress_total=progress["total"],
			progress_message=progress["message"],
		)
		frappe.db.commit()
		frappe.log_error(error_text, "MyApp Test Dataset Run Failed")
		raise
	finally:
		clear_run_progress(run_name)
		try:
			if lock.owned():
				lock.release()
		except Exception:
			frappe.log_error(frappe.get_traceback(), "MyApp Test Dataset Lock Release Failed")
