import frappe
from frappe.utils import cint

from myapp.services.purchase_service import create_purchase_invoice as create_purchase_invoice_service
from myapp.services.purchase_service import (
	cancel_purchase_invoice_v2 as cancel_purchase_invoice_v2_service,
)
from myapp.services.purchase_service import (
	cancel_purchase_order_v2 as cancel_purchase_order_v2_service,
)
from myapp.services.purchase_service import (
	cancel_purchase_receipt_v2 as cancel_purchase_receipt_v2_service,
)
from myapp.services.purchase_service import cancel_supplier_payment as cancel_supplier_payment_service
from myapp.services.purchase_service import (
	create_purchase_invoice_from_receipt as create_purchase_invoice_from_receipt_service,
)
from myapp.services.purchase_service import create_purchase_order as create_purchase_order_service
from myapp.services.purchase_service import get_purchase_company_context as get_purchase_company_context_service
from myapp.services.purchase_service import get_purchase_invoice_detail_v2 as get_purchase_invoice_detail_v2_service
from myapp.services.purchase_service import get_purchase_order_detail_v2 as get_purchase_order_detail_v2_service
from myapp.services.purchase_service import (
	get_purchase_order_status_summary as get_purchase_order_status_summary_service,
)
from myapp.services.purchase_service import search_purchase_orders_v2 as search_purchase_orders_v2_service
from myapp.services.purchase_service import get_purchase_receipt_detail_v2 as get_purchase_receipt_detail_v2_service
from myapp.services.purchase_service import get_supplier_detail_v2 as get_supplier_detail_v2_service
from myapp.services.purchase_service import get_supplier_purchase_context as get_supplier_purchase_context_service
from myapp.services.purchase_service import list_suppliers_v2 as list_suppliers_v2_service
from myapp.services.purchase_service import process_purchase_return as process_purchase_return_service
from myapp.services.purchase_service import quick_cancel_purchase_order_v2 as quick_cancel_purchase_order_v2_service
from myapp.services.purchase_service import quick_create_purchase_order_v2 as quick_create_purchase_order_v2_service
from myapp.services.purchase_service import receive_purchase_order as receive_purchase_order_service
from myapp.services.purchase_service import record_supplier_payment as record_supplier_payment_service
from myapp.services.purchase_service import update_purchase_order_items_v2 as update_purchase_order_items_v2_service
from myapp.services.purchase_service import update_purchase_order_v2 as update_purchase_order_v2_service


def _merge_kwargs(kwargs, extra_kwargs):
	merged = dict(kwargs or {})
	merged.update(extra_kwargs)
	return merged


@frappe.whitelist()
def create_purchase_order(supplier: str, items, **kwargs):
	return create_purchase_order_service(supplier=supplier, items=items, **kwargs)


@frappe.whitelist()
def quick_create_purchase_order_v2(supplier: str, items, **kwargs):
	return quick_create_purchase_order_v2_service(supplier=supplier, items=items, **kwargs)


@frappe.whitelist()
def get_purchase_company_context(company: str | None = None):
	return get_purchase_company_context_service(company=company)


@frappe.whitelist()
def get_purchase_order_detail_v2(order_name: str):
	return get_purchase_order_detail_v2_service(order_name=order_name)


@frappe.whitelist()
def get_purchase_order_status_summary(supplier: str | None = None, company: str | None = None, limit: int = 20):
	return get_purchase_order_status_summary_service(supplier=supplier, company=company, limit=cint(limit))


@frappe.whitelist()
def search_purchase_orders_v2(
	search_key: str | None = None,
	supplier: str | None = None,
	company: str | None = None,
	status_filter: str | None = None,
	exclude_cancelled=None,
	sort_by: str | None = None,
	limit: int = 20,
	start: int = 0,
):
	return search_purchase_orders_v2_service(
		search_key=search_key,
		supplier=supplier,
		company=company,
		status_filter=status_filter,
		exclude_cancelled=exclude_cancelled,
		sort_by=sort_by,
		limit=cint(limit),
		start=cint(start),
	)


@frappe.whitelist()
def get_purchase_receipt_detail_v2(receipt_name: str):
	return get_purchase_receipt_detail_v2_service(receipt_name=receipt_name)


@frappe.whitelist()
def get_purchase_invoice_detail_v2(invoice_name: str):
	return get_purchase_invoice_detail_v2_service(invoice_name=invoice_name)


@frappe.whitelist()
def get_supplier_purchase_context(supplier: str, company: str | None = None):
	return get_supplier_purchase_context_service(supplier=supplier, company=company)


@frappe.whitelist()
def list_suppliers_v2(
	search_key: str | None = None,
	supplier_group: str | None = None,
	disabled: int | None = None,
	limit: int = 20,
	start: int = 0,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	return list_suppliers_v2_service(
		search_key=search_key,
		supplier_group=supplier_group,
		disabled=disabled,
		limit=cint(limit),
		start=cint(start),
		sort_by=sort_by,
		sort_order=sort_order,
	)


@frappe.whitelist()
def get_supplier_detail_v2(supplier: str):
	return get_supplier_detail_v2_service(supplier=supplier)


@frappe.whitelist()
def update_purchase_order_v2(order_name: str, **kwargs):
	return update_purchase_order_v2_service(order_name=order_name, **kwargs)


@frappe.whitelist()
def update_purchase_order_items_v2(order_name: str, items, **kwargs):
	return update_purchase_order_items_v2_service(order_name=order_name, items=items, **kwargs)


@frappe.whitelist()
def cancel_purchase_order_v2(order_name: str, **kwargs):
	return cancel_purchase_order_v2_service(order_name=order_name, **kwargs)


@frappe.whitelist()
def quick_cancel_purchase_order_v2(order_name: str, rollback_payment: bool = True, **kwargs):
	return quick_cancel_purchase_order_v2_service(
		order_name=order_name,
		rollback_payment=rollback_payment,
		**kwargs,
	)


@frappe.whitelist()
def cancel_purchase_receipt_v2(receipt_name: str, **kwargs):
	return cancel_purchase_receipt_v2_service(receipt_name=receipt_name, **kwargs)


@frappe.whitelist()
def cancel_purchase_invoice_v2(invoice_name: str, **kwargs):
	return cancel_purchase_invoice_v2_service(invoice_name=invoice_name, **kwargs)


@frappe.whitelist()
def cancel_supplier_payment(payment_entry_name: str, **kwargs):
	return cancel_supplier_payment_service(payment_entry_name=payment_entry_name, **kwargs)


@frappe.whitelist()
def receive_purchase_order(order_name: str, receipt_items=None, kwargs=None, **extra_kwargs):
	return receive_purchase_order_service(
		order_name=order_name,
		receipt_items=receipt_items,
		kwargs=_merge_kwargs(kwargs, extra_kwargs),
	)


@frappe.whitelist()
def create_purchase_invoice(source_name: str, invoice_items=None, kwargs=None, **extra_kwargs):
	return create_purchase_invoice_service(
		source_name=source_name,
		invoice_items=invoice_items,
		kwargs=_merge_kwargs(kwargs, extra_kwargs),
	)


@frappe.whitelist()
def create_purchase_invoice_from_receipt(receipt_name: str, invoice_items=None, kwargs=None, **extra_kwargs):
	return create_purchase_invoice_from_receipt_service(
		receipt_name=receipt_name,
		invoice_items=invoice_items,
		kwargs=_merge_kwargs(kwargs, extra_kwargs),
	)


@frappe.whitelist()
def record_supplier_payment(reference_name: str, paid_amount: float, **kwargs):
	return record_supplier_payment_service(reference_name=reference_name, paid_amount=paid_amount, **kwargs)


@frappe.whitelist()
def process_purchase_return(source_doctype: str, source_name: str, return_items=None, **kwargs):
	return process_purchase_return_service(
		source_doctype=source_doctype,
		source_name=source_name,
		return_items=return_items,
		**kwargs,
	)
