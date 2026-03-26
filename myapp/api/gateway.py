import frappe

from .customers_api import create_customer_v2 as create_customer_v2_service
from .customers_api import disable_customer_v2 as disable_customer_v2_service
from .customers_api import get_customer_detail_v2 as get_customer_detail_v2_service
from .customers_api import list_customers_v2 as list_customers_v2_service
from .uoms_api import create_uom_v2 as create_uom_v2_service
from .uoms_api import delete_uom_v2 as delete_uom_v2_service
from .uoms_api import disable_uom_v2 as disable_uom_v2_service
from .uoms_api import get_uom_detail_v2 as get_uom_detail_v2_service
from .uoms_api import list_uoms_v2 as list_uoms_v2_service
from .orders_api import create_order as create_order_service
from .orders_api import create_order_v2 as create_order_v2_service
from .orders_api import quick_create_order_v2 as quick_create_order_v2_service
from .orders_api import create_sales_invoice as create_sales_invoice_service
from .orders_api import cancel_delivery_note as cancel_delivery_note_service
from .orders_api import cancel_order_v2 as cancel_order_v2_service
from .orders_api import quick_cancel_order_v2 as quick_cancel_order_v2_service
from .orders_api import cancel_sales_invoice as cancel_sales_invoice_service
from .orders_api import get_delivery_note_detail as get_delivery_note_detail_service
from .orders_api import get_customer_sales_context as get_customer_sales_context_service
from .orders_api import get_sales_order_detail as get_sales_order_detail_service
from .orders_api import get_sales_invoice_detail as get_sales_invoice_detail_service
from .orders_api import get_sales_order_status_summary as get_sales_order_status_summary_service
from .orders_api import submit_delivery as submit_delivery_service
from .orders_api import update_order_items_v2 as update_order_items_v2_service
from .orders_api import update_order_v2 as update_order_v2_service
from .purchase_api import create_purchase_invoice as create_purchase_invoice_service
from .purchase_api import (
	cancel_purchase_invoice_v2 as cancel_purchase_invoice_v2_service,
)
from .purchase_api import (
	cancel_purchase_order_v2 as cancel_purchase_order_v2_service,
)
from .purchase_api import (
	cancel_purchase_receipt_v2 as cancel_purchase_receipt_v2_service,
)
from .purchase_api import cancel_supplier_payment as cancel_supplier_payment_service
from .purchase_api import (
	create_purchase_invoice_from_receipt as create_purchase_invoice_from_receipt_service,
)
from .purchase_api import create_purchase_order as create_purchase_order_service
from .purchase_api import get_purchase_invoice_detail_v2 as get_purchase_invoice_detail_v2_service
from .purchase_api import get_purchase_order_detail_v2 as get_purchase_order_detail_v2_service
from .purchase_api import get_purchase_order_status_summary as get_purchase_order_status_summary_service
from .purchase_api import get_purchase_receipt_detail_v2 as get_purchase_receipt_detail_v2_service
from .purchase_api import get_supplier_detail_v2 as get_supplier_detail_v2_service
from .purchase_api import get_supplier_purchase_context as get_supplier_purchase_context_service
from .purchase_api import list_suppliers_v2 as list_suppliers_v2_service
from .purchase_api import process_purchase_return as process_purchase_return_service
from .purchase_api import receive_purchase_order as receive_purchase_order_service
from .purchase_api import record_supplier_payment as record_supplier_payment_service
from .purchase_api import update_purchase_order_items_v2 as update_purchase_order_items_v2_service
from .purchase_api import update_purchase_order_v2 as update_purchase_order_v2_service
from .settlement_api import confirm_pending_document as confirm_pending_document_service
from .settlement_api import cancel_payment_entry as cancel_payment_entry_service
from .settlement_api import process_sales_return as process_sales_return_service
from .settlement_api import update_payment_status as update_payment_status_service
from .wholesale_api import create_product_and_stock as create_product_and_stock_service
from .wholesale_api import create_product_v2 as create_product_v2_service
from .wholesale_api import disable_product_v2 as disable_product_v2_service
from .wholesale_api import get_product_detail_v2 as get_product_detail_v2_service
from .wholesale_api import list_products_v2 as list_products_v2_service
from .wholesale_api import search_product as search_product_service
from .wholesale_api import search_product_v2 as search_product_v2_service
from .wholesale_api import update_product_v2 as update_product_v2_service
from .customers_api import update_customer_v2 as update_customer_v2_service
from .uoms_api import update_uom_v2 as update_uom_v2_service
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
def quick_create_order_v2(customer: str, items, **kwargs):
	return _handle_gateway_call(
		lambda: quick_create_order_v2_service(customer=customer, items=items, **kwargs),
		success_code="ORDER_V2_QUICK_CREATED",
	)


@frappe.whitelist()
def get_customer_sales_context(customer: str):
	return _handle_gateway_call(
		lambda: get_customer_sales_context_service(customer=customer),
		success_code="CUSTOMER_SALES_CONTEXT_FETCHED",
	)


@frappe.whitelist()
def list_customers_v2(
	search_key: str | None = None,
	customer_group: str | None = None,
	disabled: int | None = None,
	limit: int = 20,
	start: int = 0,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	return _handle_gateway_call(
		lambda: list_customers_v2_service(
			search_key=search_key,
			customer_group=customer_group,
			disabled=disabled,
			limit=limit,
			start=start,
			sort_by=sort_by,
			sort_order=sort_order,
		),
		success_code="CUSTOMER_LIST_FETCHED",
	)


@frappe.whitelist()
def get_customer_detail_v2(customer: str):
	return _handle_gateway_call(
		lambda: get_customer_detail_v2_service(customer=customer),
		success_code="CUSTOMER_DETAIL_FETCHED",
	)


@frappe.whitelist()
def create_customer_v2(customer_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: create_customer_v2_service(customer_name=customer_name, **kwargs),
		success_code="CUSTOMER_CREATED",
	)


@frappe.whitelist()
def update_customer_v2(customer: str, **kwargs):
	return _handle_gateway_call(
		lambda: update_customer_v2_service(customer=customer, **kwargs),
		success_code="CUSTOMER_UPDATED",
	)


@frappe.whitelist()
def disable_customer_v2(customer: str, disabled: bool = True, **kwargs):
	return _handle_gateway_call(
		lambda: disable_customer_v2_service(customer=customer, disabled=disabled, **kwargs),
		success_code="CUSTOMER_DISABLED",
	)


@frappe.whitelist()
def list_uoms_v2(
	search_key: str | None = None,
	enabled: int | None = None,
	must_be_whole_number: int | None = None,
	limit: int = 20,
	start: int = 0,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	return _handle_gateway_call(
		lambda: list_uoms_v2_service(
			search_key=search_key,
			enabled=enabled,
			must_be_whole_number=must_be_whole_number,
			limit=limit,
			start=start,
			sort_by=sort_by,
			sort_order=sort_order,
		),
		success_code="UOM_LIST_FETCHED",
	)


@frappe.whitelist()
def get_uom_detail_v2(uom: str):
	return _handle_gateway_call(
		lambda: get_uom_detail_v2_service(uom=uom),
		success_code="UOM_DETAIL_FETCHED",
	)


@frappe.whitelist()
def create_uom_v2(uom_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: create_uom_v2_service(uom_name=uom_name, **kwargs),
		success_code="UOM_CREATED",
	)


@frappe.whitelist()
def update_uom_v2(uom: str, **kwargs):
	return _handle_gateway_call(
		lambda: update_uom_v2_service(uom=uom, **kwargs),
		success_code="UOM_UPDATED",
	)


@frappe.whitelist()
def disable_uom_v2(uom: str, disabled: bool = True, **kwargs):
	return _handle_gateway_call(
		lambda: disable_uom_v2_service(uom=uom, disabled=disabled, **kwargs),
		success_code="UOM_DISABLED",
	)


@frappe.whitelist()
def delete_uom_v2(uom: str, **kwargs):
	return _handle_gateway_call(
		lambda: delete_uom_v2_service(uom=uom, **kwargs),
		success_code="UOM_DELETED",
	)


@frappe.whitelist()
def get_sales_order_detail(order_name: str):
	return _handle_gateway_call(
		lambda: get_sales_order_detail_service(order_name=order_name),
		success_code="ORDER_DETAIL_FETCHED",
	)


@frappe.whitelist()
def get_delivery_note_detail_v2(delivery_note_name: str):
	return _handle_gateway_call(
		lambda: get_delivery_note_detail_service(delivery_note_name=delivery_note_name),
		success_code="DELIVERY_NOTE_DETAIL_FETCHED",
	)


@frappe.whitelist()
def get_sales_invoice_detail_v2(sales_invoice_name: str):
	return _handle_gateway_call(
		lambda: get_sales_invoice_detail_service(sales_invoice_name=sales_invoice_name),
		success_code="SALES_INVOICE_DETAIL_FETCHED",
	)


@frappe.whitelist()
def get_sales_order_status_summary(customer: str | None = None, company: str | None = None, limit: int = 20):
	return _handle_gateway_call(
		lambda: get_sales_order_status_summary_service(customer=customer, company=company, limit=limit),
		success_code="ORDER_SUMMARY_FETCHED",
	)


@frappe.whitelist()
def cancel_order_v2(order_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: cancel_order_v2_service(order_name=order_name, **kwargs),
		success_code="ORDER_V2_CANCELLED",
	)


@frappe.whitelist()
def quick_cancel_order_v2(order_name: str, rollback_payment: bool = True, **kwargs):
	return _handle_gateway_call(
		lambda: quick_cancel_order_v2_service(
			order_name=order_name,
			rollback_payment=rollback_payment,
			**kwargs,
		),
		success_code="ORDER_V2_QUICK_CANCELLED",
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
def get_purchase_order_detail_v2(order_name: str):
	return _handle_gateway_call(
		lambda: get_purchase_order_detail_v2_service(order_name=order_name),
		success_code="PURCHASE_ORDER_DETAIL_FETCHED",
	)


@frappe.whitelist()
def get_purchase_order_status_summary(supplier: str | None = None, company: str | None = None, limit: int = 20):
	return _handle_gateway_call(
		lambda: get_purchase_order_status_summary_service(supplier=supplier, company=company, limit=limit),
		success_code="PURCHASE_ORDER_STATUS_SUMMARY_FETCHED",
	)


@frappe.whitelist()
def get_purchase_receipt_detail_v2(receipt_name: str):
	return _handle_gateway_call(
		lambda: get_purchase_receipt_detail_v2_service(receipt_name=receipt_name),
		success_code="PURCHASE_RECEIPT_DETAIL_FETCHED",
	)


@frappe.whitelist()
def get_purchase_invoice_detail_v2(invoice_name: str):
	return _handle_gateway_call(
		lambda: get_purchase_invoice_detail_v2_service(invoice_name=invoice_name),
		success_code="PURCHASE_INVOICE_DETAIL_FETCHED",
	)


@frappe.whitelist()
def get_supplier_purchase_context(supplier: str):
	return _handle_gateway_call(
		lambda: get_supplier_purchase_context_service(supplier=supplier),
		success_code="SUPPLIER_PURCHASE_CONTEXT_FETCHED",
	)


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
	return _handle_gateway_call(
		lambda: list_suppliers_v2_service(
			search_key=search_key,
			supplier_group=supplier_group,
			disabled=disabled,
			limit=limit,
			start=start,
			sort_by=sort_by,
			sort_order=sort_order,
		),
		success_code="SUPPLIER_LIST_FETCHED",
	)


@frappe.whitelist()
def get_supplier_detail_v2(supplier: str):
	return _handle_gateway_call(
		lambda: get_supplier_detail_v2_service(supplier=supplier),
		success_code="SUPPLIER_DETAIL_FETCHED",
	)


@frappe.whitelist()
def update_purchase_order_v2(order_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: update_purchase_order_v2_service(order_name=order_name, **kwargs),
		success_code="PURCHASE_ORDER_UPDATED",
	)


@frappe.whitelist()
def update_purchase_order_items_v2(order_name: str, items, **kwargs):
	return _handle_gateway_call(
		lambda: update_purchase_order_items_v2_service(order_name=order_name, items=items, **kwargs),
		success_code="PURCHASE_ORDER_ITEMS_UPDATED",
	)


@frappe.whitelist()
def cancel_purchase_order_v2(order_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: cancel_purchase_order_v2_service(order_name=order_name, **kwargs),
		success_code="PURCHASE_ORDER_CANCELLED",
	)


@frappe.whitelist()
def cancel_purchase_receipt_v2(receipt_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: cancel_purchase_receipt_v2_service(receipt_name=receipt_name, **kwargs),
		success_code="PURCHASE_RECEIPT_CANCELLED",
	)


@frappe.whitelist()
def cancel_purchase_invoice_v2(invoice_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: cancel_purchase_invoice_v2_service(invoice_name=invoice_name, **kwargs),
		success_code="PURCHASE_INVOICE_CANCELLED",
	)


@frappe.whitelist()
def cancel_supplier_payment(payment_entry_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: cancel_supplier_payment_service(payment_entry_name=payment_entry_name, **kwargs),
		success_code="SUPPLIER_PAYMENT_CANCELLED",
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
def cancel_delivery_note(delivery_note_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: cancel_delivery_note_service(delivery_note_name=delivery_note_name, **kwargs),
		success_code="DELIVERY_NOTE_CANCELLED",
	)


@frappe.whitelist()
def cancel_sales_invoice(sales_invoice_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: cancel_sales_invoice_service(sales_invoice_name=sales_invoice_name, **kwargs),
		success_code="SALES_INVOICE_CANCELLED",
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
def create_product_v2(item_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: create_product_v2_service(item_name=item_name, **kwargs),
		success_code="PRODUCT_CREATED",
	)


@frappe.whitelist()
def list_products_v2(
	search_key: str | None = None,
	warehouse: str | None = None,
	company: str | None = None,
	limit: int = 20,
	start: int = 0,
	item_group: str | None = None,
	disabled: int | None = None,
	price_list: str = "Standard Selling",
	currency: str | None = None,
	selling_price_lists=None,
	buying_price_lists=None,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	return _handle_gateway_call(
		lambda: list_products_v2_service(
			search_key=search_key,
			warehouse=warehouse,
			company=company,
			limit=limit,
			start=start,
			item_group=item_group,
			disabled=disabled,
			price_list=price_list,
			currency=currency,
			selling_price_lists=selling_price_lists,
			buying_price_lists=buying_price_lists,
			sort_by=sort_by,
			sort_order=sort_order,
		),
		success_code="PRODUCTS_FETCHED",
	)


@frappe.whitelist()
def get_product_detail_v2(
	item_code: str,
	warehouse: str | None = None,
	company: str | None = None,
	price_list: str = "Standard Selling",
	currency: str | None = None,
):
	return _handle_gateway_call(
		lambda: get_product_detail_v2_service(
			item_code=item_code,
			warehouse=warehouse,
			company=company,
			price_list=price_list,
			currency=currency,
		),
		success_code="PRODUCT_DETAIL_FETCHED",
	)


@frappe.whitelist()
def update_product_v2(item_code: str, **kwargs):
	return _handle_gateway_call(
		lambda: update_product_v2_service(item_code=item_code, **kwargs),
		success_code="PRODUCT_UPDATED",
	)


@frappe.whitelist()
def disable_product_v2(item_code: str, disabled: bool = True, **kwargs):
	return _handle_gateway_call(
		lambda: disable_product_v2_service(item_code=item_code, disabled=disabled, **kwargs),
		success_code="PRODUCT_UPDATED",
	)


@frappe.whitelist()
def confirm_pending_document(doctype: str, docname: str, **kwargs):
	return _handle_gateway_call(
		lambda: confirm_pending_document_service(doctype=doctype, docname=docname, **kwargs),
		success_code="DOCUMENT_CONFIRMED",
	)


@frappe.whitelist()
def cancel_payment_entry(payment_entry_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: cancel_payment_entry_service(payment_entry_name=payment_entry_name, **kwargs),
		success_code="PAYMENT_ENTRY_CANCELLED",
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
