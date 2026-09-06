"""Persistent, bounded model checks. One site-wide worker prevents probe storms."""
import json
import uuid
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime
from myapp.utils.idempotency import run_idempotent

from myapp.services.ai_model_governance_service import (
	_check_ai_model_availability,
	_require_manager,
	_resolve_healthcheck_model_aliases,
)

TABLE = "tabMyApp AI Model Check Job"
ACTIVE = {"queued", "running"}


def _read(job_id):
	rows = frappe.db.sql(f"SELECT * FROM `{TABLE}` WHERE name=%s", (job_id,), as_dict=True)
	if not rows:
		frappe.throw(_("检测任务不存在。"), frappe.DoesNotExistError)
	return rows[0]


def _view(row):
	aliases = json.loads(row.aliases_json)
	items = json.loads(row.results_json)
	status = row.status
	if status in ACTIVE and get_datetime(row.modified) < now_datetime() - timedelta(minutes=30):
		status = "interrupted"
	return {
		"job_id": row.name, "status": status, "mode": row.mode,
		"total": len(aliases), "completed": len(items), "items": items, "model_aliases": aliases,
		"cancel_requested": bool(row.cancel_requested),
		"creation": str(row.creation), "modified": str(row.modified),
	}


def _expire():
	# A worker killed before its final write must not monopolize the active slot.
	frappe.db.sql(f"""UPDATE `{TABLE}` SET status='interrupted', active_key=NULL
		WHERE active_key='model-check' AND modified < %s""", (now_datetime() - timedelta(minutes=30),))


def start_ai_model_check_v1(model_aliases=None, mode="full", request_id=None):
	_require_manager()
	return run_idempotent(
		"start_ai_model_check_v1", request_id,
		lambda: _start(model_aliases, mode),
		request_payload={"model_aliases": model_aliases, "mode": mode},
	)


def _start(model_aliases=None, mode="full"):
	actor = _require_manager()
	if mode not in {"basic", "full"}:
		frappe.throw(_("检测模式必须是 basic 或 full。"))
	if isinstance(model_aliases, str) and model_aliases:
		model_aliases = frappe.parse_json(model_aliases)
	if model_aliases is not None and not isinstance(model_aliases, (list, tuple)):
		frappe.throw(_("模型列表必须为数组。"))
	if model_aliases is not None and len(model_aliases) > 100:
		frappe.throw(_("单次最多检测 100 个模型，请分批选择。"))
	aliases = _resolve_healthcheck_model_aliases(model_aliases)
	if len(aliases) > 100:
		frappe.throw(_("单次最多检测 100 个模型，请分批选择。"))
	_expire()
	active = frappe.db.sql(f"SELECT * FROM `{TABLE}` WHERE active_key='model-check'", as_dict=True)
	if active:
		if active[0].mode == mode and set(aliases).issubset(json.loads(active[0].aliases_json)):
			return {"status": "success", "data": _view(active[0])}
		frappe.throw(_("已有模型检测任务执行中，请等待完成或取消当前任务。"))
	job_id = f"AI-CHECK-{uuid.uuid4().hex}"
	now = now_datetime()
	try:
		frappe.db.sql(f"""INSERT INTO `{TABLE}`
			(name,owner,creation,modified,status,active_key,mode,aliases_json,results_json)
			VALUES (%s,%s,%s,%s,'queued','model-check',%s,%s,'[]')""",
			(job_id, actor, now, now, mode, json.dumps(aliases)))
	except Exception as exc:
		if not frappe.db.is_duplicate_entry(exc):
			raise
		frappe.throw(_("另一个检测任务刚刚启动，请刷新任务进度。"))
	frappe.enqueue(
		"myapp.services.ai_model_check_service.run_model_check_job",
		queue="long", timeout=21600, job_id=job_id, check_job_id=job_id,
		enqueue_after_commit=True,
	)
	return {"status": "success", "data": _view(_read(job_id))}


def get_ai_model_check_v1(job_id=None):
	_require_manager()
	if not job_id:
		rows = frappe.db.sql(f"SELECT * FROM `{TABLE}` ORDER BY creation DESC LIMIT 1", as_dict=True)
		return {"status": "success", "data": _view(rows[0]) if rows else None}
	return {"status": "success", "data": _view(_read(job_id))}


def cancel_ai_model_check_v1(job_id):
	_require_manager()
	frappe.db.sql(f"UPDATE `{TABLE}` SET status='cancelled',active_key=NULL,cancel_requested=1 WHERE name=%s AND status='queued'", (job_id,))
	frappe.db.sql(f"UPDATE `{TABLE}` SET cancel_requested=1 WHERE name=%s AND status IN ('queued','running')", (job_id,))
	return {"status": "success", "data": _view(_read(job_id))}


def run_model_check_job(check_job_id):
	row = _read(check_job_id)
	if row.status not in ACTIVE:
		return
	# Claim once, including when RQ redelivers a job.
	frappe.db.sql(f"UPDATE `{TABLE}` SET status='running',modified=%s WHERE name=%s AND status='queued'", (now_datetime(), check_job_id))
	if not frappe.db._cursor.rowcount:
		return
	frappe.db.commit()
	items = json.loads(row.results_json)
	status = "completed"
	previous_user = frappe.session.user
	try:
		frappe.set_user(row.owner)
		_require_manager()
		for alias in json.loads(row.aliases_json):
			frappe.db.commit()
			current = _read(check_job_id)
			if current.status != "running":
				return
			if current.cancel_requested:
				status = "cancelled"
				break
			if (get_datetime(now_datetime()) - get_datetime(row.creation)).total_seconds() > 18000:
				status = "interrupted"
				break
			try:
				_require_manager()
				result = _check_ai_model_availability(model_aliases=[alias], actor=row.owner,
					trigger="background", mode=row.mode)
				results = result["data"]["items"]
				if len(results) != 1:
					raise ValueError("missing probe result")
				items.append({**results[0], "check_status": "completed"})
			except Exception:
				frappe.db.rollback()
				items.append({"model_alias": alias, "check_status": "error", "error_code": "MODEL_CHECK_EXECUTION_FAILED"})
				frappe.log_error(frappe.get_traceback(), "AI model background check failed")
			frappe.db.sql(f"UPDATE `{TABLE}` SET results_json=%s,modified=%s WHERE name=%s AND status='running'",
				(json.dumps(items), now_datetime(), check_job_id))
			frappe.db.commit()
		if status == "completed" and any(item["check_status"] == "error" for item in items):
			status = "partial"
	except Exception:
		frappe.db.rollback()
		status = "interrupted"
		frappe.log_error(frappe.get_traceback(), "AI model check job interrupted")
	finally:
		frappe.db.sql(f"UPDATE `{TABLE}` SET status=%s,active_key=NULL,modified=%s WHERE name=%s AND status='running'",
			(status, now_datetime(), check_job_id))
		frappe.db.commit()
		frappe.set_user(previous_user)
