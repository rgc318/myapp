import frappe

from myapp.services.order_service import create_order as create_order_service
from myapp.services.order_service import create_order_v2 as create_order_v2_service
from myapp.services.order_service import create_sales_invoice as create_sales_invoice_service
from myapp.services.order_service import cancel_order_v2 as cancel_order_v2_service
from myapp.services.order_service import get_delivery_note_detail as get_delivery_note_detail_service
from myapp.services.order_service import get_customer_sales_context as get_customer_sales_context_service
from myapp.services.order_service import get_sales_order_detail as get_sales_order_detail_service
from myapp.services.order_service import get_sales_invoice_detail as get_sales_invoice_detail_service
from myapp.services.order_service import get_sales_order_status_summary as get_sales_order_status_summary_service
from myapp.services.order_service import submit_delivery as submit_delivery_service
from myapp.services.order_service import update_order_items_v2 as update_order_items_v2_service
from myapp.services.order_service import update_order_v2 as update_order_v2_service


def _merge_kwargs(kwargs, extra_kwargs):
	merged = dict(kwargs or {})
	merged.update(extra_kwargs)
	return merged


@frappe.whitelist()
def create_order(customer: str, items, immediate: bool = False, **kwargs):
	return create_order_service(customer=customer, items=items, immediate=immediate, **kwargs)


@frappe.whitelist()
def create_order_v2(customer: str, items, immediate: bool = False, **kwargs):
	return create_order_v2_service(customer=customer, items=items, immediate=immediate, **kwargs)


@frappe.whitelist()
def get_customer_sales_context(customer: str):
	return get_customer_sales_context_service(customer=customer)


@frappe.whitelist()
def submit_delivery(order_name: str, delivery_items=None, kwargs=None, **extra_kwargs):
	return submit_delivery_service(
		order_name=order_name,
		delivery_items=delivery_items,
		kwargs=_merge_kwargs(kwargs, extra_kwargs),
	)


@frappe.whitelist()
def create_sales_invoice(source_name: str, invoice_items=None, kwargs=None, **extra_kwargs):
	return create_sales_invoice_service(
		source_name=source_name,
		invoice_items=invoice_items,
		kwargs=_merge_kwargs(kwargs, extra_kwargs),
	)


@frappe.whitelist()
def get_sales_order_detail(order_name: str):
	return get_sales_order_detail_service(order_name=order_name)


@frappe.whitelist()
def get_delivery_note_detail(delivery_note_name: str):
	return get_delivery_note_detail_service(delivery_note_name=delivery_note_name)


@frappe.whitelist()
def get_sales_invoice_detail(sales_invoice_name: str):
	return get_sales_invoice_detail_service(sales_invoice_name=sales_invoice_name)


@frappe.whitelist()
def get_sales_order_status_summary(customer: str | None = None, company: str | None = None, limit: int = 20):
	return get_sales_order_status_summary_service(customer=customer, company=company, limit=limit)


@frappe.whitelist()
def cancel_order_v2(order_name: str, **kwargs):
	return cancel_order_v2_service(order_name=order_name, **kwargs)


@frappe.whitelist()
def update_order_v2(order_name: str, **kwargs):
	return update_order_v2_service(order_name=order_name, **kwargs)


@frappe.whitelist()
def update_order_items_v2(order_name: str, items, **kwargs):
	return update_order_items_v2_service(order_name=order_name, items=items, **kwargs)
