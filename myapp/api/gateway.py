import frappe

from .orders_api import create_order as create_order_service
from .orders_api import create_order_v2 as create_order_v2_service
from .orders_api import create_sales_invoice as create_sales_invoice_service
from .orders_api import get_customer_sales_context as get_customer_sales_context_service
from .orders_api import get_sales_order_detail as get_sales_order_detail_service
from .orders_api import get_sales_order_status_summary as get_sales_order_status_summary_service
from .orders_api import submit_delivery as submit_delivery_service
from .orders_api import update_order_items_v2 as update_order_items_v2_service
from .orders_api import update_order_v2 as update_order_v2_service
from .purchase_api import create_purchase_invoice as create_purchase_invoice_service
from .purchase_api import (
	create_purchase_invoice_from_receipt as create_purchase_invoice_from_receipt_service,
)
from .purchase_api import create_purchase_order as create_purchase_order_service
from .purchase_api import process_purchase_return as process_purchase_return_service
from .purchase_api import receive_purchase_order as receive_purchase_order_service
from .purchase_api import record_supplier_payment as record_supplier_payment_service
from .settlement_api import confirm_pending_document as confirm_pending_document_service
from .settlement_api import process_sales_return as process_sales_return_service
from .settlement_api import update_payment_status as update_payment_status_service
from .wholesale_api import create_product_and_stock as create_product_and_stock_service
from .wholesale_api import search_product as search_product_service
from .wholesale_api import search_product_v2 as search_product_v2_service
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


@frappe.whitelist()
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


@frappe.whitelist()
def create_order(customer: str, items, immediate: bool = False, **kwargs):
	return _handle_gateway_call(
		lambda: create_order_service(customer=customer, items=items, immediate=immediate, **kwargs),
		success_code="ORDER_CREATED",
	)


@frappe.whitelist()
def create_order_v2(customer: str, items, immediate: bool = False, **kwargs):
	return _handle_gateway_call(
		lambda: create_order_v2_service(customer=customer, items=items, immediate=immediate, **kwargs),
		success_code="ORDER_V2_CREATED",
	)


@frappe.whitelist()
def get_customer_sales_context(customer: str):
	return _handle_gateway_call(
		lambda: get_customer_sales_context_service(customer=customer),
		success_code="CUSTOMER_SALES_CONTEXT_FETCHED",
	)


@frappe.whitelist()
def get_sales_order_detail(order_name: str):
	return _handle_gateway_call(
		lambda: get_sales_order_detail_service(order_name=order_name),
		success_code="ORDER_DETAIL_FETCHED",
	)


@frappe.whitelist()
def get_sales_order_status_summary(customer: str | None = None, company: str | None = None, limit: int = 20):
	return _handle_gateway_call(
		lambda: get_sales_order_status_summary_service(customer=customer, company=company, limit=limit),
		success_code="ORDER_SUMMARY_FETCHED",
	)


@frappe.whitelist()
def update_order_v2(order_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: update_order_v2_service(order_name=order_name, **kwargs),
		success_code="ORDER_V2_UPDATED",
	)


@frappe.whitelist()
def update_order_items_v2(order_name: str, items, **kwargs):
	return _handle_gateway_call(
		lambda: update_order_items_v2_service(order_name=order_name, items=items, **kwargs),
		success_code="ORDER_ITEMS_V2_UPDATED",
	)


@frappe.whitelist()
def create_purchase_order(supplier: str, items, **kwargs):
	return _handle_gateway_call(
		lambda: create_purchase_order_service(supplier=supplier, items=items, **kwargs),
		success_code="PURCHASE_ORDER_CREATED",
	)


@frappe.whitelist()
def submit_delivery(order_name: str, delivery_items=None, kwargs=None, **extra_kwargs):
	return _handle_gateway_call(
		lambda: submit_delivery_service(
			order_name=order_name,
			delivery_items=delivery_items,
			kwargs=_merge_kwargs(kwargs, extra_kwargs),
		),
		success_code="DELIVERY_SUBMITTED",
	)


@frappe.whitelist()
def create_sales_invoice(source_name: str, invoice_items=None, kwargs=None, **extra_kwargs):
	return _handle_gateway_call(
		lambda: create_sales_invoice_service(
			source_name=source_name,
			invoice_items=invoice_items,
			kwargs=_merge_kwargs(kwargs, extra_kwargs),
		),
		success_code="SALES_INVOICE_CREATED",
	)


@frappe.whitelist()
def receive_purchase_order(order_name: str, receipt_items=None, kwargs=None, **extra_kwargs):
	return _handle_gateway_call(
		lambda: receive_purchase_order_service(
			order_name=order_name,
			receipt_items=receipt_items,
			kwargs=_merge_kwargs(kwargs, extra_kwargs),
		),
		success_code="PURCHASE_RECEIPT_CREATED",
	)


@frappe.whitelist()
def create_purchase_invoice(source_name: str, invoice_items=None, kwargs=None, **extra_kwargs):
	return _handle_gateway_call(
		lambda: create_purchase_invoice_service(
			source_name=source_name,
			invoice_items=invoice_items,
			kwargs=_merge_kwargs(kwargs, extra_kwargs),
		),
		success_code="PURCHASE_INVOICE_CREATED",
	)


@frappe.whitelist()
def create_purchase_invoice_from_receipt(receipt_name: str, invoice_items=None, kwargs=None, **extra_kwargs):
	return _handle_gateway_call(
		lambda: create_purchase_invoice_from_receipt_service(
			receipt_name=receipt_name,
			invoice_items=invoice_items,
			kwargs=_merge_kwargs(kwargs, extra_kwargs),
		),
		success_code="PURCHASE_INVOICE_CREATED",
	)


@frappe.whitelist()
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


@frappe.whitelist()
def search_product_v2(
	search_key: str,
	price_list: str = "Standard Selling",
	currency: str | None = None,
	warehouse: str | None = None,
	company: str | None = None,
	limit: int = 20,
	search_fields=None,
	sort_by: str = "relevance",
	sort_order: str = "asc",
	in_stock_only: bool = False,
):
	return _handle_gateway_call(
		lambda: search_product_v2_service(
			search_key=search_key,
			price_list=price_list,
			currency=currency,
			warehouse=warehouse,
			company=company,
			limit=limit,
			search_fields=search_fields,
			sort_by=sort_by,
			sort_order=sort_order,
			in_stock_only=in_stock_only,
		),
		success_code="PRODUCTS_FETCHED",
	)


@frappe.whitelist()
def create_product_and_stock(item_name: str, warehouse: str | None = None, opening_qty: float = 0, **kwargs):
	return _handle_gateway_call(
		lambda: create_product_and_stock_service(
			item_name=item_name,
			warehouse=warehouse,
			opening_qty=opening_qty,
			**kwargs,
		),
		success_code="PRODUCT_CREATED",
	)


@frappe.whitelist()
def confirm_pending_document(doctype: str, docname: str, **kwargs):
	return _handle_gateway_call(
		lambda: confirm_pending_document_service(doctype=doctype, docname=docname, **kwargs),
		success_code="DOCUMENT_CONFIRMED",
	)


@frappe.whitelist()
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


@frappe.whitelist()
def record_supplier_payment(reference_name: str, paid_amount: float, **kwargs):
	return _handle_gateway_call(
		lambda: record_supplier_payment_service(
			reference_name=reference_name,
			paid_amount=paid_amount,
			**kwargs,
		),
		success_code="SUPPLIER_PAYMENT_RECORDED",
	)


@frappe.whitelist()
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


@frappe.whitelist()
def process_purchase_return(source_doctype: str, source_name: str, return_items=None, **kwargs):
	return _handle_gateway_call(
		lambda: process_purchase_return_service(
			source_doctype=source_doctype,
			source_name=source_name,
			return_items=return_items,
			**kwargs,
		),
		success_code="PURCHASE_RETURN_CREATED",
	)
