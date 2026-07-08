import frappe
from frappe import _
from frappe.utils import cint


def get_transaction_warehouse_context(warehouse: str):
	row = frappe.db.get_value(
		"Warehouse",
		warehouse,
		["name", "company", "disabled", "is_group"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("仓库 {0} 不存在。").format(warehouse))
	if cint(row.get("disabled")):
		frappe.throw(_("仓库 {0} 已停用，不能用于交易。").format(warehouse))
	if cint(row.get("is_group")):
		frappe.throw(_("仓库 {0} 是父级/汇总仓，不能用于交易明细。请选择具体子仓库。").format(warehouse))
	if not row.get("company"):
		frappe.throw(_("仓库 {0} 未绑定公司，不能用于交易。").format(warehouse))
	return row


def validate_transaction_warehouse(warehouse: str, *, company: str | None = None):
	row = get_transaction_warehouse_context(warehouse)
	if company and row.company != company:
		frappe.throw(_("仓库 {0} 属于公司 {1}，与当前公司 {2} 不一致。").format(warehouse, row.company, company))
	return row
