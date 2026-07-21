from __future__ import annotations

import frappe
from frappe.utils import flt

from myapp.test_data.registry import list_active_objects


TRANSACTION_ITEM_DOCTYPES = {
	"Sales Order": "Sales Order Item",
	"Delivery Note": "Delivery Note Item",
	"Sales Invoice": "Sales Invoice Item",
	"Purchase Order": "Purchase Order Item",
	"Purchase Receipt": "Purchase Receipt Item",
	"Purchase Invoice": "Purchase Invoice Item",
}


def _check(name: str, passed: bool, details: dict | None = None) -> dict:
	return {"name": name, "passed": bool(passed), "details": details or {}}


def _validate_objects(objects) -> dict:
	checks = []
	missing = []
	for row in objects:
		if not frappe.db.exists(row.doctype_name, row.document_name):
			missing.append({"doctype": row.doctype_name, "name": row.document_name})
	checks.append(_check("registered_documents_exist", not missing, {"missing": missing, "count": len(objects)}))

	invalid_uom_rows = []
	for parent_doctype, child_doctype in TRANSACTION_ITEM_DOCTYPES.items():
		parent_names = [row.document_name for row in objects if row.doctype_name == parent_doctype]
		if not parent_names:
			continue
		rows = frappe.get_all(
			child_doctype,
			filters={"parent": ["in", parent_names]},
			fields=["parent", "item_code", "qty", "uom", "stock_uom", "conversion_factor", "stock_qty"],
			limit_page_length=0,
		)
		for row in rows:
			conversion_factor = flt(row.conversion_factor)
			expected_stock_qty = flt(row.qty) * conversion_factor
			if (
				not row.uom
				or not row.stock_uom
				or conversion_factor <= 0
				or abs(flt(row.stock_qty) - expected_stock_qty) > 0.001
			):
				invalid_uom_rows.append(
					{
						"parent": row.parent,
						"item_code": row.item_code,
						"qty": flt(row.qty),
						"uom": row.uom,
						"stock_uom": row.stock_uom,
						"conversion_factor": conversion_factor,
						"stock_qty": flt(row.stock_qty),
					}
				)
	checks.append(_check("uom_conversion_consistent", not invalid_uom_rows, {"invalid_rows": invalid_uom_rows}))

	item_codes = [row.document_name for row in objects if row.doctype_name == "Item"]
	negative_bins = []
	if item_codes:
		negative_bins = frappe.get_all(
			"Bin",
			filters={"item_code": ["in", item_codes], "actual_qty": ["<", 0]},
			fields=["item_code", "warehouse", "actual_qty"],
			limit_page_length=0,
		)
	checks.append(_check("generated_stock_non_negative", not negative_bins, {"negative_bins": negative_bins}))

	invalid_outstanding = []
	for doctype in ("Sales Invoice", "Purchase Invoice"):
		names = [row.document_name for row in objects if row.doctype_name == doctype]
		if not names:
			continue
		rows = frappe.get_all(
			doctype,
			filters={"name": ["in", names]},
			fields=["name", "grand_total", "outstanding_amount", "docstatus"],
			limit_page_length=0,
		)
		for row in rows:
			grand_total = abs(flt(row.grand_total))
			outstanding = flt(row.outstanding_amount)
			if row.docstatus != 1 or outstanding < -0.01 or outstanding - grand_total > 0.01:
				invalid_outstanding.append(
					{"doctype": doctype, "name": row.name, "grand_total": grand_total, "outstanding": outstanding}
				)
	checks.append(_check("invoice_outstanding_valid", not invalid_outstanding, {"invalid": invalid_outstanding}))

	vouchers = [
		(row.doctype_name, row.document_name)
		for row in objects
		if row.doctype_name in {
			"Stock Entry", "Delivery Note", "Sales Invoice", "Purchase Receipt", "Purchase Invoice", "Payment Entry"
		}
	]
	unbalanced = []
	for voucher_type, voucher_no in vouchers:
		balance = flt(
			frappe.db.sql(
				"SELECT COALESCE(SUM(debit - credit), 0) FROM `tabGL Entry` "
				"WHERE voucher_type = %s AND voucher_no = %s AND is_cancelled = 0",
				(voucher_type, voucher_no),
			)[0][0]
		)
		if abs(balance) > 0.01:
			unbalanced.append({"voucher_type": voucher_type, "voucher_no": voucher_no, "balance": balance})
	checks.append(_check("general_ledger_balanced", not unbalanced, {"unbalanced": unbalanced}))

	passed = all(check["passed"] for check in checks)
	return {"status": "passed" if passed else "failed", "passed": passed, "checks": checks}


def validate_run(run_name: str) -> dict:
	return _validate_objects(list_active_objects(run_name=run_name))


def validate_active_dataset(company: str, dataset_code: str) -> dict:
	return _validate_objects(list_active_objects(company=company, dataset_code=dataset_code))
