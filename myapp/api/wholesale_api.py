import frappe
from frappe.utils import cint

from myapp.services.wholesale_service import create_product_and_stock as create_product_and_stock_service
from myapp.services.wholesale_service import search_product as search_product_service
from myapp.services.wholesale_service import search_product_v2 as search_product_v2_service


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
	search_fields=None,
	sort_by: str = "relevance",
	sort_order: str = "asc",
	in_stock_only: bool = False,
):
	return search_product_v2_service(
		search_key=search_key,
		price_list=price_list,
		currency=currency,
		warehouse=warehouse,
		company=company,
		limit=cint(limit),
		search_fields=search_fields,
		sort_by=sort_by,
		sort_order=sort_order,
		in_stock_only=in_stock_only,
	)
