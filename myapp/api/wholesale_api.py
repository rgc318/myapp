import frappe
from frappe.utils import cint

from myapp.services.wholesale_service import create_product_and_stock as create_product_and_stock_service
from myapp.services.wholesale_service import add_product_barcode_v2 as add_product_barcode_v2_service
from myapp.services.wholesale_service import create_product_v2 as create_product_v2_service
from myapp.services.wholesale_service import delete_product_barcode_v2 as delete_product_barcode_v2_service
from myapp.services.wholesale_service import disable_product_v2 as disable_product_v2_service
from myapp.services.wholesale_service import get_product_detail_v2 as get_product_detail_v2_service
from myapp.services.wholesale_service import list_products_v2 as list_products_v2_service
from myapp.services.wholesale_service import search_product as search_product_service
from myapp.services.wholesale_service import search_product_v2 as search_product_v2_service
from myapp.services.wholesale_service import set_primary_product_barcode_v2 as set_primary_product_barcode_v2_service
from myapp.services.wholesale_service import update_product_v2 as update_product_v2_service


@frappe.whitelist()
def search_product(
	search_key: str,
	price_list: str = "Standard Selling",
	currency: str | None = None,
	warehouse: str | None = None,
	company: str | None = None,
	limit: int = 20,
):
	return search_product_service(
		search_key=search_key,
		price_list=price_list,
		currency=currency,
		warehouse=warehouse,
		company=company,
		limit=cint(limit),
	)


@frappe.whitelist()
def create_product_and_stock(item_name: str, warehouse: str | None = None, opening_qty: float = 0, **kwargs):
	return create_product_and_stock_service(
		item_name=item_name,
		warehouse=warehouse,
		opening_qty=opening_qty,
		**kwargs,
	)


@frappe.whitelist()
def search_product_v2(
	search_key: str,
	price_list: str = "Standard Selling",
	currency: str | None = None,
	warehouse: str | None = None,
	company: str | None = None,
	limit: int = 20,
	disabled: int | None = 0,
	item_group: str | None = None,
	brand: str | None = None,
	search_fields=None,
	sort_by: str = "relevance",
	sort_order: str = "asc",
	in_stock_only: bool = False,
	item_context: str | None = "sales",
):
	return search_product_v2_service(
		search_key=search_key,
		price_list=price_list,
		currency=currency,
		warehouse=warehouse,
		company=company,
		limit=cint(limit),
		disabled=disabled,
		item_group=item_group,
		brand=brand,
		search_fields=search_fields,
		sort_by=sort_by,
		sort_order=sort_order,
		in_stock_only=in_stock_only,
		item_context=item_context,
	)


@frappe.whitelist()
def list_products_v2(
	search_key: str | None = None,
	warehouse: str | None = None,
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 20,
	start: int = 0,
	item_group: str | None = None,
	brand: str | None = None,
	disabled: int | None = None,
	in_stock_only: bool = False,
	price_list: str = "Standard Selling",
	currency: str | None = None,
	selling_price_lists=None,
	buying_price_lists=None,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	return list_products_v2_service(
		search_key=search_key,
		warehouse=warehouse,
		company=company,
		date_from=date_from,
		date_to=date_to,
		limit=cint(limit),
		start=cint(start),
		item_group=item_group,
		brand=brand,
		disabled=disabled,
		in_stock_only=in_stock_only,
		price_list=price_list,
		currency=currency,
		selling_price_lists=selling_price_lists,
		buying_price_lists=buying_price_lists,
		sort_by=sort_by,
		sort_order=sort_order,
	)


@frappe.whitelist()
def get_product_detail_v2(
	item_code: str,
	warehouse: str | None = None,
	company: str | None = None,
	price_list: str = "Standard Selling",
	currency: str | None = None,
):
	return get_product_detail_v2_service(
		item_code=item_code,
		warehouse=warehouse,
		company=company,
		price_list=price_list,
		currency=currency,
	)


@frappe.whitelist()
def create_product_v2(item_name: str, **kwargs):
	return create_product_v2_service(item_name=item_name, **kwargs)


@frappe.whitelist()
def update_product_v2(item_code: str, **kwargs):
	return update_product_v2_service(item_code=item_code, **kwargs)


@frappe.whitelist()
def disable_product_v2(item_code: str, disabled: bool = True, **kwargs):
	return disable_product_v2_service(item_code=item_code, disabled=disabled, **kwargs)


@frappe.whitelist()
def add_product_barcode_v2(item_code: str, barcode: str, set_primary: bool = False, **kwargs):
	return add_product_barcode_v2_service(
		item_code=item_code,
		barcode=barcode,
		set_primary=set_primary,
		**kwargs,
	)


@frappe.whitelist()
def set_primary_product_barcode_v2(item_code: str, barcode: str, **kwargs):
	return set_primary_product_barcode_v2_service(item_code=item_code, barcode=barcode, **kwargs)


@frappe.whitelist()
def delete_product_barcode_v2(item_code: str, barcode: str, **kwargs):
	return delete_product_barcode_v2_service(item_code=item_code, barcode=barcode, **kwargs)
