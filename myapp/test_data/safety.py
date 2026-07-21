from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint


ALLOWED_ENVIRONMENTS = {"development", "test", "testing", "demo"}


def parse_allowed_companies(value) -> tuple[str, ...]:
	if value in (None, ""):
		return ()
	if isinstance(value, str):
		text = value.strip()
		if not text:
			return ()
		if text.startswith("["):
			try:
				value = json.loads(text)
			except (TypeError, ValueError):
				value = text.split(",")
		else:
			value = text.split(",")
	if not isinstance(value, (list, tuple, set)):
		value = [value]
	return tuple(sorted({str(item).strip() for item in value if str(item).strip()}))


def get_environment_type() -> str:
	return str(
		frappe.conf.get("myapp_environment_type")
		or frappe.conf.get("environment_type")
		or ""
	).strip().lower()


def get_safety_snapshot() -> dict:
	return {
		"enabled": bool(cint(frappe.conf.get("myapp_test_data_enabled") or 0)),
		"environment_type": get_environment_type(),
		"allowed_companies": list(parse_allowed_companies(frappe.conf.get("myapp_test_data_allowed_companies"))),
		"developer_mode": bool(cint(frappe.conf.get("developer_mode") or 0)),
	}


def expected_confirmation(action: str, company: str) -> str:
	verb = {
		"generate": "GENERATE",
		"reset": "RESET",
		"supplement": "SUPPLEMENT",
	}.get(action, "GENERATE")
	return f"{verb} {company}"


def assert_confirmation(action: str, company: str, confirmation_text: str | None) -> None:
	expected = expected_confirmation(action, company)
	if (confirmation_text or "").strip() != expected:
		frappe.throw(_("确认文本不正确，请输入：{0}").format(expected))


def validate_mutation_environment(company: str, warehouse: str) -> dict:
	snapshot = get_safety_snapshot()
	if not snapshot["enabled"]:
		frappe.throw(_("测试数据管理未启用，请先配置 myapp_test_data_enabled。"))
	if snapshot["environment_type"] not in ALLOWED_ENVIRONMENTS:
		frappe.throw(_("当前环境不允许生成或重置测试数据。"))
	if company not in snapshot["allowed_companies"]:
		frappe.throw(_("公司 {0} 不在测试数据白名单中。").format(company))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("公司 {0} 不存在。").format(company))
	warehouse_company = frappe.db.get_value("Warehouse", warehouse, "company")
	if not warehouse_company:
		frappe.throw(_("仓库 {0} 不存在。").format(warehouse))
	if warehouse_company != company:
		frappe.throw(_("仓库 {0} 不属于公司 {1}。").format(warehouse, company))
	return snapshot
