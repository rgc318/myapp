import frappe
from frappe.utils import cint

from myapp.services.warehouse_service import create_warehouse_v2 as create_warehouse_v2_service
from myapp.services.warehouse_service import disable_warehouse_v2 as disable_warehouse_v2_service
from myapp.services.warehouse_service import get_warehouse_detail_v2 as get_warehouse_detail_v2_service
from myapp.services.warehouse_service import list_warehouses_v2 as list_warehouses_v2_service
from myapp.services.warehouse_service import update_warehouse_v2 as update_warehouse_v2_service


@frappe.whitelist()
def list_warehouses_v2(
	search_key: str | None = None,
	company: str | None = None,
	disabled=None,
	is_group=None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 20,
	start: int = 0,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	return list_warehouses_v2_service(
		search_key=search_key,
		company=company,
		disabled=disabled,
		is_group=is_group,
		date_from=date_from,
		date_to=date_to,
		limit=cint(limit),
		start=cint(start),
		sort_by=sort_by,
		sort_order=sort_order,
	)


@frappe.whitelist()
def get_warehouse_detail_v2(warehouse: str):
	return get_warehouse_detail_v2_service(warehouse=warehouse)


@frappe.whitelist()
def create_warehouse_v2(warehouse_name: str, company: str, **kwargs):
	return create_warehouse_v2_service(warehouse_name=warehouse_name, company=company, **kwargs)


@frappe.whitelist()
def update_warehouse_v2(warehouse: str, **kwargs):
	return update_warehouse_v2_service(warehouse=warehouse, **kwargs)


@frappe.whitelist()
def disable_warehouse_v2(warehouse: str, disabled: bool = True, **kwargs):
	return disable_warehouse_v2_service(warehouse=warehouse, disabled=disabled, **kwargs)
