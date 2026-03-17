import frappe

from myapp.services.order_service import create_order as create_order_service
from myapp.services.order_service import create_order_v2 as create_order_v2_service
from myapp.services.order_service import create_sales_invoice as create_sales_invoice_service
from myapp.services.order_service import get_customer_sales_context as get_customer_sales_context_service
from myapp.services.order_service import get_sales_order_detail as get_sales_order_detail_service
from myapp.services.order_service import get_sales_order_status_summary as get_sales_order_status_summary_service
from myapp.services.order_service import submit_delivery as submit_delivery_service


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
def get_sales_order_status_summary(customer: str | None = None, company: str | None = None, limit: int = 20):
	return get_sales_order_status_summary_service(customer=customer, company=company, limit=limit)
