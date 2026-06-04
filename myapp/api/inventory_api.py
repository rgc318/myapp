import frappe
from frappe.utils import cint

from myapp.services.inventory_service import list_stock_ledger_entries_v1 as list_stock_ledger_entries_v1_service


@frappe.whitelist()
def list_stock_ledger_entries_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	item_code: str | None = None,
	warehouse: str | None = None,
	voucher_type: str | None = None,
	voucher_no: str | None = None,
	page: int = 1,
	page_size: int = 20,
):
	return list_stock_ledger_entries_v1_service(
		company=company,
		date_from=date_from,
		date_to=date_to,
		item_code=item_code,
		warehouse=warehouse,
		voucher_type=voucher_type,
		voucher_no=voucher_no,
		page=cint(page),
		page_size=cint(page_size),
	)
