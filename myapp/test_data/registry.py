from __future__ import annotations

import json
import uuid

import frappe
from frappe.utils import now_datetime

from myapp.test_data.catalog import normalize_scale


RUN_TABLE = "tabMyApp Test Dataset Run"
OBJECT_TABLE = "tabMyApp Test Dataset Object"
PROGRESS_CACHE_TTL = 4 * 60 * 60


def ensure_tables() -> None:
	if not frappe.db.table_exists("MyApp Test Dataset Run") or not frappe.db.table_exists("MyApp Test Dataset Object"):
		frappe.throw("测试数据管理表尚未初始化，请先执行 bench migrate。")


def json_dumps(value) -> str:
	return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def json_loads(value, default):
	if value in (None, ""):
		return default
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return default


def insert_run(values: dict) -> str:
	now = now_datetime()
	name = values.get("name") or f"TDM-RUN-{uuid.uuid4().hex}"
	actor = values["requested_by"]
	frappe.db.sql(
		f"""
		INSERT INTO `{RUN_TABLE}`
		(name, creation, modified, modified_by, owner, status, action, dataset_code, dataset_version,
		 scale, company, warehouse, seed, base_date, requested_by, previous_run, config_hash,
		 scenario_keys_json, progress_current, progress_total, progress_message)
		VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 0, NULL)
		""",
		(
			name, now, now, actor, actor, values["status"], values["action"], values["dataset_code"],
			values["dataset_version"], values["scale"], values["company"], values["warehouse"],
			values["seed"], values["base_date"], actor, values.get("previous_run"), values.get("config_hash"),
			json_dumps(values.get("scenario_keys") or []),
		),
	)
	return name


def update_run(run_name: str, **values) -> None:
	if not values:
		return
	allowed = {
		"status", "started_at", "completed_at", "result_json", "error_text", "previous_run",
		"progress_current", "progress_total", "progress_message",
	}
	unknown = set(values) - allowed
	if unknown:
		raise ValueError(f"不允许更新运行字段：{', '.join(sorted(unknown))}")
	values["modified"] = now_datetime()
	values["modified_by"] = str(getattr(frappe.session, "user", "") or "Administrator")
	assignments = ", ".join(f"`{field}` = %s" for field in values)
	frappe.db.sql(
		f"UPDATE `{RUN_TABLE}` SET {assignments} WHERE name = %s",
		(*values.values(), run_name),
	)


def get_run(run_name: str):
	rows = frappe.db.sql(f"SELECT * FROM `{RUN_TABLE}` WHERE name = %s", (run_name,), as_dict=True)
	return rows[0] if rows else None


def serialize_run(row) -> dict:
	_scale_profile, scenario_copies = normalize_scale(row.scale)
	progress = get_run_progress(
		row.name,
		fallback={
			"current": int(getattr(row, "progress_current", 0) or 0),
			"total": int(getattr(row, "progress_total", 0) or 0),
			"message": getattr(row, "progress_message", None),
		},
	)
	return {
		"name": row.name,
		"status": row.status,
		"action": row.action,
		"dataset_code": row.dataset_code,
		"dataset_version": row.dataset_version,
		"scale": row.scale,
		"scenario_copies": scenario_copies,
		"company": row.company,
		"warehouse": row.warehouse,
		"seed": row.seed,
		"base_date": row.base_date,
		"requested_by": row.requested_by,
		"started_at": row.started_at,
		"completed_at": row.completed_at,
		"previous_run": row.previous_run,
		"scenario_keys": json_loads(getattr(row, "scenario_keys_json", None), []),
		"progress": progress,
		"result": json_loads(row.result_json, None),
		"error": row.error_text,
		"creation": row.creation,
		"modified": row.modified,
	}


def _progress_cache_key(run_name: str) -> str:
	return f"myapp:test-data-progress:{run_name}"


def set_run_progress(run_name: str, *, current: int, total: int, message: str | None) -> dict:
	progress = {"current": int(current), "total": int(total), "message": message}
	frappe.cache.set_value(
		_progress_cache_key(run_name),
		progress,
		expires_in_sec=PROGRESS_CACHE_TTL,
	)
	return progress


def get_run_progress(run_name: str, *, fallback: dict | None = None) -> dict:
	progress = frappe.cache.get_value(_progress_cache_key(run_name), use_local_cache=False)
	return progress if isinstance(progress, dict) else (fallback or {"current": 0, "total": 0, "message": None})


def clear_run_progress(run_name: str) -> None:
	frappe.cache.delete_value(_progress_cache_key(run_name))


def list_runs(*, start: int = 0, limit: int = 20) -> list[dict]:
	rows = frappe.db.sql(
		f"SELECT * FROM `{RUN_TABLE}` ORDER BY creation DESC LIMIT %s OFFSET %s",
		(limit, start),
		as_dict=True,
	)
	return [serialize_run(row) for row in rows]


def count_runs() -> int:
	return int(frappe.db.sql(f"SELECT COUNT(*) FROM `{RUN_TABLE}`")[0][0] or 0)


def find_open_run(company: str):
	rows = frappe.db.sql(
		f"SELECT * FROM `{RUN_TABLE}` WHERE company = %s AND status IN ('queued','running','validating') "
		"ORDER BY creation DESC LIMIT 1",
		(company,),
		as_dict=True,
	)
	return rows[0] if rows else None


def find_latest_completed_run(company: str, dataset_code: str):
	rows = frappe.db.sql(
		f"SELECT * FROM `{RUN_TABLE}` WHERE company = %s AND dataset_code = %s AND status = 'completed' "
		"ORDER BY creation DESC LIMIT 1",
		(company, dataset_code),
		as_dict=True,
	)
	return rows[0] if rows else None


def register_object(
	*,
	run_name: str,
	scenario_key: str,
	doctype_name: str,
	document_name: str,
	document_order: int,
	metadata: dict | None = None,
) -> None:
	now = now_datetime()
	actor = str(getattr(frappe.session, "user", "") or "Administrator")
	frappe.db.sql(
		f"""
		INSERT INTO `{OBJECT_TABLE}`
		(name, creation, modified, modified_by, owner, run_name, scenario_key, doctype_name,
		 document_name, document_order, metadata_json, deleted)
		VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
		""",
		(
			f"TDM-OBJ-{uuid.uuid4().hex}", now, now, actor, actor, run_name, scenario_key, doctype_name,
			document_name, document_order, json_dumps(metadata or {}),
		),
	)


def list_active_objects(*, run_name: str | None = None, company: str | None = None, dataset_code: str | None = None):
	conditions = ["obj.deleted = 0"]
	params = []
	if run_name:
		conditions.append("obj.run_name = %s")
		params.append(run_name)
	if company:
		conditions.append("run.company = %s")
		params.append(company)
	if dataset_code:
		conditions.append("run.dataset_code = %s")
		params.append(dataset_code)
	return frappe.db.sql(
		f"""
		SELECT obj.*, run.company, run.dataset_code, run.creation AS run_creation
		FROM `{OBJECT_TABLE}` obj
		INNER JOIN `{RUN_TABLE}` run ON run.name = obj.run_name
		WHERE {' AND '.join(conditions)}
		ORDER BY run.creation ASC, obj.document_order ASC, obj.creation ASC
		""",
		tuple(params),
		as_dict=True,
	)


def mark_object_deleted(object_name: str) -> None:
	now = now_datetime()
	frappe.db.sql(
		f"UPDATE `{OBJECT_TABLE}` SET deleted = 1, deleted_at = %s, modified = %s WHERE name = %s",
		(now, now, object_name),
	)
