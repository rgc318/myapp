import frappe
from frappe.utils import cint

from myapp.services.inventory_service import list_inventory_stock_summary_v1 as list_inventory_stock_summary_v1_service
from myapp.services.inventory_service import list_stock_ledger_entries_v1 as list_stock_ledger_entries_v1_service
from myapp.services.inventory_service import reconcile_inventory_stock_v1 as reconcile_inventory_stock_v1_service
from myapp.services.inventory_service import submit_inventory_stock_count_v1 as submit_inventory_stock_count_v1_service
from myapp.services.inventory_service import transfer_inventory_stock_v1 as transfer_inventory_stock_v1_service


@frappe.whitelist()
def list_inventory_stock_summary_v1(
	company: str | None = None,
	warehouse: str | None = None,
	search_key: str | None = None,
	stock_status: str | None = "all",
	low_stock_threshold: float | int | str | None = 10,
	page: int = 1,
	page_size: int = 20,
):
	return list_inventory_stock_summary_v1_service(
		company=company,
		warehouse=warehouse,
		search_key=search_key,
		stock_status=stock_status,
		low_stock_threshold=low_stock_threshold,
		page=cint(page),
		page_size=cint(page_size),
	)


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


@frappe.whitelist()
def transfer_inventory_stock_v1(
	item_code: str,
	source_warehouse: str,
	target_warehouse: str,
	qty,
	uom: str | None = None,
	posting_date: str | None = None,
	remarks: str | None = None,
	request_id: str | None = None,
):
	return transfer_inventory_stock_v1_service(
		item_code=item_code,
		source_warehouse=source_warehouse,
		target_warehouse=target_warehouse,
		qty=qty,
		uom=uom,
		posting_date=posting_date,
		remarks=remarks,
		request_id=request_id,
	)


@frappe.whitelist()
def reconcile_inventory_stock_v1(
	item_code: str,
	warehouse: str,
	target_qty,
	uom: str | None = None,
	valuation_rate=None,
	posting_date: str | None = None,
	remarks: str | None = None,
	request_id: str | None = None,
):
	return reconcile_inventory_stock_v1_service(
		item_code=item_code,
		warehouse=warehouse,
		target_qty=target_qty,
		uom=uom,
		valuation_rate=valuation_rate,
		posting_date=posting_date,
		remarks=remarks,
		request_id=request_id,
	)


@frappe.whitelist()
def submit_inventory_stock_count_v1(
	items,
	company: str | None = None,
	posting_date: str | None = None,
	remarks: str | None = None,
	request_id: str | None = None,
):
	return submit_inventory_stock_count_v1_service(
		items=items,
		company=company,
		posting_date=posting_date,
		remarks=remarks,
		request_id=request_id,
	)
