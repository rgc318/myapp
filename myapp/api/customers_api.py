import frappe
from frappe.utils import cint

from myapp.services.customer_service import create_customer_v2 as create_customer_v2_service
from myapp.services.customer_service import disable_customer_v2 as disable_customer_v2_service
from myapp.services.customer_service import get_customer_detail_v2 as get_customer_detail_v2_service
from myapp.services.customer_service import list_customers_v2 as list_customers_v2_service
from myapp.services.customer_service import update_customer_v2 as update_customer_v2_service


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
	return list_customers_v2_service(
		search_key=search_key,
		customer_group=customer_group,
		disabled=disabled,
		limit=cint(limit),
		start=cint(start),
		sort_by=sort_by,
		sort_order=sort_order,
	)


@frappe.whitelist()
def get_customer_detail_v2(customer: str):
	return get_customer_detail_v2_service(customer=customer)


@frappe.whitelist()
def create_customer_v2(customer_name: str, **kwargs):
	return create_customer_v2_service(customer_name=customer_name, **kwargs)


@frappe.whitelist()
def update_customer_v2(customer: str, **kwargs):
	return update_customer_v2_service(customer=customer, **kwargs)


@frappe.whitelist()
def disable_customer_v2(customer: str, disabled: bool = True, **kwargs):
	return disable_customer_v2_service(customer=customer, disabled=disabled, **kwargs)
