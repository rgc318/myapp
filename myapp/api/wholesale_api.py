import frappe
from frappe.utils import cint

from myapp.services.wholesale_service import search_product as search_product_service


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
