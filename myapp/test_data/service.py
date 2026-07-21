from __future__ import annotations

import hashlib

import frappe
from frappe import _
from frappe.utils import cint, getdate, nowdate
from frappe.utils.background_jobs import get_redis_conn

from myapp.test_data.catalog import get_dataset, list_datasets, normalize_scale
from myapp.test_data.generator import resolve_master_defaults, validate_master_defaults
from myapp.test_data.registry import (
	count_runs,
	ensure_tables,
	find_latest_completed_run,
	find_open_run,
	get_run,
	insert_run,
	json_dumps,
	list_active_objects,
	list_runs,
	serialize_run,
)
from myapp.test_data.safety import (
	ALLOWED_ENVIRONMENTS,
	assert_confirmation,
	expected_confirmation,
	get_safety_snapshot,
	validate_mutation_environment,
)
from myapp.test_data.validator import validate_active_dataset


def _current_user() -> str:
	user = str(getattr(frappe.session, "user", "") or "").strip()
	if not user or user == "Guest":
		raise frappe.PermissionError(_("请先登录。"))
	return user


def require_test_data_manager() -> str:
	user = _current_user()
	if user != "Administrator" and "System Manager" not in set(frappe.get_roles(user) or []):
		raise frappe.PermissionError(_("只有系统管理员可以管理测试数据。"))
	return user


def _normalize_scenario_keys(dataset, value) -> tuple[list[str], list[str]]:
	if value in (None, ""):
		return [], []
	if isinstance(value, str):
		try:
			parsed = frappe.parse_json(value)
		except Exception:
			parsed = value.split(",")
		value = parsed
	if not isinstance(value, (list, tuple, set)):
		value = [value]
	requested = [str(item).strip() for item in value if str(item).strip()]
	available = {scenario.key for scenario in dataset.scenarios}
	unknown = sorted(set(requested) - available)
	selected = [scenario.key for scenario in dataset.scenarios if scenario.key in set(requested)]
	return selected, unknown


def _expected_counts(
	dataset,
	scenario_keys=None,
	*,
	include_master: bool = True,
	scenario_copies: int = 1,
) -> dict:
	counts = {}
	if include_master:
		counts = {
			"Customer": len(dataset.customers),
			"Supplier": len(dataset.suppliers),
			"Item": len(dataset.items),
			"Item Price": len(dataset.items),
			"Stock Entry": len(dataset.items),
		}
	selected = set(scenario_keys or [scenario.key for scenario in dataset.scenarios])
	for scenario in dataset.scenarios:
		if scenario.key not in selected:
			continue
		if scenario.domain == "sales":
			counts["Sales Order"] = counts.get("Sales Order", 0) + scenario_copies
			if scenario.state in {"partial_delivery", "complete"}:
				counts["Delivery Note"] = counts.get("Delivery Note", 0) + scenario_copies
			if scenario.state in {"unpaid_invoice", "paid_invoice", "complete"}:
				counts["Sales Invoice"] = counts.get("Sales Invoice", 0) + scenario_copies
			if scenario.state in {"paid_invoice", "complete"}:
				counts["Payment Entry"] = counts.get("Payment Entry", 0) + scenario_copies
		elif scenario.domain == "purchase":
			counts["Purchase Order"] = counts.get("Purchase Order", 0) + scenario_copies
			if scenario.state in {"received", "partial_paid"}:
				counts["Purchase Receipt"] = counts.get("Purchase Receipt", 0) + scenario_copies
			if scenario.state == "partial_paid":
				counts["Purchase Invoice"] = counts.get("Purchase Invoice", 0) + scenario_copies
				counts["Payment Entry"] = counts.get("Payment Entry", 0) + scenario_copies
	return dict(sorted(counts.items()))


def _catalog_conflicts(dataset) -> list[dict]:
	conflicts = []
	for item in dataset.items:
		if frappe.db.exists("Item", item.item_code):
			conflicts.append({"doctype": "Item", "name": item.item_code})
	for customer in dataset.customers:
		name = frappe.db.get_value("Customer", {"customer_name": customer.name}, "name")
		if name:
			conflicts.append({"doctype": "Customer", "name": name})
	for supplier in dataset.suppliers:
		name = frappe.db.get_value("Supplier", {"supplier_name": supplier.name}, "name")
		if name:
			conflicts.append({"doctype": "Supplier", "name": name})
	return conflicts


def _missing_baseline_masters(dataset, owned: set[tuple[str, str]]) -> list[dict]:
	missing = []
	for item in dataset.items:
		if not frappe.db.exists("Item", item.item_code) or ("Item", item.item_code) not in owned:
			missing.append({"doctype": "Item", "name": item.item_code})
	for customer in dataset.customers:
		name = frappe.db.get_value("Customer", {"customer_name": customer.name}, "name")
		if not name or ("Customer", name) not in owned:
			missing.append({"doctype": "Customer", "name": name or customer.name})
	for supplier in dataset.suppliers:
		name = frappe.db.get_value("Supplier", {"supplier_name": supplier.name}, "name")
		if not name or ("Supplier", name) not in owned:
			missing.append({"doctype": "Supplier", "name": name or supplier.name})
	return missing


def list_test_datasets() -> dict:
	require_test_data_manager()
	return {"status": "success", "data": {"items": list_datasets()}}


def preview_dataset(
	*,
	dataset_code: str,
	company: str,
	warehouse: str,
	action: str = "generate",
	base_date=None,
	seed: int = 1,
	scenario_keys=None,
	scale: str | None = None,
) -> dict:
	require_test_data_manager()
	ensure_tables()
	dataset = get_dataset(dataset_code)
	try:
		scale_profile, scenario_copies = normalize_scale(scale, default=dataset.scale)
	except ValueError as exc:
		frappe.throw(str(exc))
	action = (action or "generate").strip().lower()
	if action not in {"generate", "reset", "supplement"}:
		frappe.throw(_("action 只支持 generate、reset 或 supplement。"))
	selected_scenario_keys, unknown_scenario_keys = _normalize_scenario_keys(dataset, scenario_keys)
	safety = get_safety_snapshot()
	blockers = []
	if not safety["enabled"]:
		blockers.append("myapp_test_data_enabled 未启用。")
	if safety["environment_type"] not in ALLOWED_ENVIRONMENTS:
		blockers.append("当前环境类型不允许修改测试数据。")
	if company not in safety["allowed_companies"]:
		blockers.append(f"公司 {company} 不在测试数据白名单中。")
	if not frappe.db.exists("Company", company):
		blockers.append(f"公司 {company} 不存在。")
	warehouse_company = frappe.db.get_value("Warehouse", warehouse, "company")
	if not warehouse_company:
		blockers.append(f"仓库 {warehouse} 不存在。")
	elif warehouse_company != company:
		blockers.append(f"仓库 {warehouse} 不属于公司 {company}。")
	if action != "supplement":
		blockers.extend(validate_master_defaults(resolve_master_defaults()))
	for uom in sorted({uom for item in dataset.items for uom, _factor in item.uom_conversions}):
		if not frappe.db.exists("UOM", uom):
			blockers.append(f"单位 {uom} 不存在。")

	conflicts = _catalog_conflicts(dataset)
	active_objects = list_active_objects(company=company, dataset_code=dataset.code)
	owned = {(row.doctype_name, row.document_name) for row in active_objects}
	unowned_conflicts = [row for row in conflicts if (row["doctype"], row["name"]) not in owned]
	missing_baseline_masters = _missing_baseline_masters(dataset, owned)
	if action == "generate" and conflicts:
		blockers.append("目标主数据已经存在，请改用 reset 或先处理冲突。")
	if action == "reset" and unowned_conflicts:
		blockers.append("检测到不属于测试数据登记表的同名主数据，拒绝覆盖。")
	if action == "supplement":
		if unknown_scenario_keys:
			blockers.append(f"存在未知场景：{', '.join(unknown_scenario_keys)}。")
		if not selected_scenario_keys:
			blockers.append("补充模式至少选择一个场景。")
		if missing_baseline_masters:
			blockers.append("标准主数据基线不完整，请先执行 reset。")
		if unowned_conflicts:
			blockers.append("标准主数据存在非系统登记的同名对象，拒绝补充场景。")

	return {
		"status": "success",
		"data": {
			"allowed": not blockers,
			"action": action,
			"dataset": dataset.serialize(),
			"company": company,
			"warehouse": warehouse,
			"base_date": str(getdate(base_date or nowdate())),
			"seed": cint(seed) or 1,
			"scale": scale_profile,
			"scenario_copies": scenario_copies,
			"scenario_instance_count": (
				len(selected_scenario_keys) if action == "supplement" else len(dataset.scenarios)
			) * scenario_copies,
			"selected_scenario_keys": selected_scenario_keys,
			"expected_counts": _expected_counts(
				dataset,
				selected_scenario_keys if action == "supplement" else None,
				include_master=action != "supplement",
				scenario_copies=scenario_copies,
			),
			"active_generated_object_count": len(active_objects),
			"conflicts": conflicts,
			"unowned_conflicts": unowned_conflicts,
			"missing_baseline_masters": missing_baseline_masters,
			"blockers": blockers,
			"safety": safety,
			"confirmation_text": expected_confirmation(action, company),
		},
	}


def request_dataset_run(
	*,
	dataset_code: str,
	company: str,
	warehouse: str,
	action: str,
	confirmation_text: str,
	base_date=None,
	seed: int = 1,
	scenario_keys=None,
	scale: str | None = None,
	enqueue: bool = True,
) -> dict:
	actor = require_test_data_manager()
	ensure_tables()
	dataset = get_dataset(dataset_code)
	action = (action or "").strip().lower()
	if action not in {"generate", "reset", "supplement"}:
		frappe.throw(_("action 只支持 generate、reset 或 supplement。"))
	assert_confirmation(action, company, confirmation_text)
	safety = validate_mutation_environment(company, warehouse)
	preview = preview_dataset(
		dataset_code=dataset_code,
		company=company,
		warehouse=warehouse,
		action=action,
		base_date=base_date,
		seed=seed,
		scenario_keys=scenario_keys,
		scale=scale,
	)["data"]
	if not preview["allowed"]:
		frappe.throw(_("测试数据任务预检未通过：{0}").format("；".join(preview["blockers"])))

	request_lock = get_redis_conn().lock(
		f"myapp:test-data-request:{frappe.local.site}:{company}",
		timeout=30,
		blocking_timeout=2,
	)
	if not request_lock.acquire(blocking=True):
		frappe.throw(_("测试数据任务请求正在处理中，请稍后重试。"))
	try:
		if open_run := find_open_run(company):
			frappe.throw(_("公司 {0} 已有任务 {1} 正在执行。").format(company, open_run.name))
		previous = find_latest_completed_run(company, dataset.code)
		config_hash = hashlib.sha256(
			json_dumps(
				{
					"safety": safety,
					"scale": preview["scale"],
					"scenario_keys": preview["selected_scenario_keys"],
				}
			).encode("utf-8")
		).hexdigest()
		run_name = insert_run(
			{
				"status": "queued",
				"action": action,
				"dataset_code": dataset.code,
				"dataset_version": dataset.version,
				"scale": preview["scale"],
				"company": company,
				"warehouse": warehouse,
				"seed": cint(seed) or 1,
				"base_date": getdate(base_date or nowdate()),
				"requested_by": actor,
				"previous_run": previous.name if previous else None,
				"config_hash": config_hash,
				"scenario_keys": preview["selected_scenario_keys"],
			}
		)
		if enqueue:
			frappe.enqueue(
				"myapp.test_data.runner.execute_run",
				queue="long",
				job_id=f"myapp-test-data-{run_name}",
				enqueue_after_commit=True,
				run_name=run_name,
			)
		frappe.db.commit()
		return {
			"status": "success",
			"message": _("测试数据任务已创建。"),
			"data": {"run_name": run_name, "queued": bool(enqueue), "preview": preview},
		}
	finally:
		if request_lock.owned():
			request_lock.release()


def get_dataset_run(run_name: str) -> dict:
	require_test_data_manager()
	ensure_tables()
	row = get_run(run_name)
	if not row:
		raise frappe.DoesNotExistError(_("测试数据任务不存在。"))
	return {"status": "success", "data": serialize_run(row)}


def list_dataset_runs(start: int = 0, limit: int = 20) -> dict:
	require_test_data_manager()
	ensure_tables()
	return {
		"status": "success",
		"data": {
			"items": list_runs(start=max(cint(start), 0), limit=max(1, min(cint(limit) or 20, 100))),
			"total": count_runs(),
		},
	}


def validate_latest_dataset(company: str, dataset_code: str) -> dict:
	require_test_data_manager()
	ensure_tables()
	row = find_latest_completed_run(company, dataset_code)
	if not row:
		frappe.throw(_("没有可验证的已完成测试数据任务。"))
	return {
		"status": "success",
		"data": {
			"run": serialize_run(row),
			"validation": validate_active_dataset(company, dataset_code),
		},
	}
