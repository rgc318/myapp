import frappe

from myapp.services.purchase_service import create_purchase_invoice as create_purchase_invoice_service
from myapp.services.purchase_service import (
	create_purchase_invoice_from_receipt as create_purchase_invoice_from_receipt_service,
)
from myapp.services.purchase_service import create_purchase_order as create_purchase_order_service
from myapp.services.purchase_service import process_purchase_return as process_purchase_return_service
from myapp.services.purchase_service import receive_purchase_order as receive_purchase_order_service
from myapp.services.purchase_service import record_supplier_payment as record_supplier_payment_service


def _merge_kwargs(kwargs, extra_kwargs):
	merged = dict(kwargs or {})
	merged.update(extra_kwargs)
	return merged


@frappe.whitelist()
def create_purchase_order(supplier: str, items, **kwargs):
	return create_purchase_order_service(supplier=supplier, items=items, **kwargs)


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
