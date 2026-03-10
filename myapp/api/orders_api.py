import frappe

from myapp.services.order_service import create_order as create_order_service
from myapp.services.order_service import create_sales_invoice as create_sales_invoice_service
from myapp.services.order_service import submit_delivery as submit_delivery_service


@frappe.whitelist()
def create_order(customer: str, items, immediate: bool = False, **kwargs):
	return create_order_service(customer=customer, items=items, immediate=immediate, **kwargs)


@frappe.whitelist()
def submit_delivery(order_name: str, delivery_items=None, kwargs=None):
	return submit_delivery_service(order_name=order_name, delivery_items=delivery_items, kwargs=kwargs)


@frappe.whitelist()
def create_sales_invoice(source_name: str, invoice_items=None, kwargs=None):
	return create_sales_invoice_service(source_name=source_name, invoice_items=invoice_items, kwargs=kwargs)
