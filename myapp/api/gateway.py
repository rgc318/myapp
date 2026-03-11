import frappe

from .orders_api import create_order as create_order_service
from .orders_api import create_sales_invoice as create_sales_invoice_service
from .orders_api import submit_delivery as submit_delivery_service
from .settlement_api import confirm_pending_document as confirm_pending_document_service
from .settlement_api import process_sales_return as process_sales_return_service
from .settlement_api import update_payment_status as update_payment_status_service
from .wholesale_api import search_product as search_product_service
from myapp.utils.api_response import (
	error_response,
	map_exception_to_error,
	normalize_service_response,
	success_response,
)


def _handle_gateway_call(callback, *, success_code: str):
	try:
		return normalize_service_response(callback(), code=success_code)
	except Exception as exc:
		code, http_status = map_exception_to_error(exc)
		frappe.local.response["http_status_code"] = http_status
		return error_response(message=str(exc), code=code)


def _merge_kwargs(kwargs, extra_kwargs):
	merged = dict(kwargs or {})
	merged.update(extra_kwargs)
	return merged


@frappe.whitelist(allow_guest=True)
def test_remote_debug():
	welcome_message = "太棒了！你的 VS Code 原生调试彻底打通了！"

	a = 10
	b = 24
	result = a + b

	print(f"=== 拦截成功！计算结果是: {result} ===")

	return success_response(
		message=welcome_message,
		data={"magic_number": result},
		code="REMOTE_DEBUG_OK",
	)


@frappe.whitelist(allow_guest=True)
def create_order(customer: str, items, immediate: bool = False, **kwargs):
	return _handle_gateway_call(
		lambda: create_order_service(customer=customer, items=items, immediate=immediate, **kwargs),
		success_code="ORDER_CREATED",
	)


@frappe.whitelist(allow_guest=True)
def submit_delivery(order_name: str, delivery_items=None, kwargs=None, **extra_kwargs):
	return _handle_gateway_call(
		lambda: submit_delivery_service(
			order_name=order_name,
			delivery_items=delivery_items,
			kwargs=_merge_kwargs(kwargs, extra_kwargs),
		),
		success_code="DELIVERY_SUBMITTED",
	)


@frappe.whitelist(allow_guest=True)
def create_sales_invoice(source_name: str, invoice_items=None, kwargs=None, **extra_kwargs):
	return _handle_gateway_call(
		lambda: create_sales_invoice_service(
			source_name=source_name,
			invoice_items=invoice_items,
			kwargs=_merge_kwargs(kwargs, extra_kwargs),
		),
		success_code="SALES_INVOICE_CREATED",
	)


@frappe.whitelist(allow_guest=True)
def search_product(
	search_key: str,
	price_list: str = "Standard Selling",
	currency: str | None = None,
	warehouse: str | None = None,
	company: str | None = None,
	limit: int = 20,
):
	return _handle_gateway_call(
		lambda: search_product_service(
			search_key=search_key,
			price_list=price_list,
			currency=currency,
			warehouse=warehouse,
			company=company,
			limit=limit,
		),
		success_code="PRODUCTS_FETCHED",
	)


@frappe.whitelist(allow_guest=True)
def confirm_pending_document(doctype: str, docname: str, **kwargs):
	return _handle_gateway_call(
		lambda: confirm_pending_document_service(doctype=doctype, docname=docname, **kwargs),
		success_code="DOCUMENT_CONFIRMED",
	)


@frappe.whitelist(allow_guest=True)
def update_payment_status(reference_doctype: str, reference_name: str, paid_amount: float, **kwargs):
	return _handle_gateway_call(
		lambda: update_payment_status_service(
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			paid_amount=paid_amount,
			**kwargs,
		),
		success_code="PAYMENT_RECORDED",
	)


@frappe.whitelist(allow_guest=True)
def process_sales_return(source_doctype: str, source_name: str, return_items=None, **kwargs):
	return _handle_gateway_call(
		lambda: process_sales_return_service(
			source_doctype=source_doctype,
			source_name=source_name,
			return_items=return_items,
			**kwargs,
		),
		success_code="SALES_RETURN_CREATED",
	)
