import frappe
from frappe.utils import cint

from myapp.services.uom_service import create_uom_v2 as create_uom_v2_service
from myapp.services.uom_service import delete_uom_v2 as delete_uom_v2_service
from myapp.services.uom_service import disable_uom_v2 as disable_uom_v2_service
from myapp.services.uom_service import get_uom_detail_v2 as get_uom_detail_v2_service
from myapp.services.uom_service import list_uoms_v2 as list_uoms_v2_service
from myapp.services.uom_service import update_uom_v2 as update_uom_v2_service


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
	return list_uoms_v2_service(
		search_key=search_key,
		enabled=enabled,
		must_be_whole_number=must_be_whole_number,
		limit=cint(limit),
		start=cint(start),
		sort_by=sort_by,
		sort_order=sort_order,
	)


@frappe.whitelist()
def get_uom_detail_v2(uom: str):
	return get_uom_detail_v2_service(uom=uom)


@frappe.whitelist()
def create_uom_v2(uom_name: str, **kwargs):
	return create_uom_v2_service(uom_name=uom_name, **kwargs)


@frappe.whitelist()
def update_uom_v2(uom: str, **kwargs):
	return update_uom_v2_service(uom=uom, **kwargs)


@frappe.whitelist()
def disable_uom_v2(uom: str, disabled: bool = True, **kwargs):
	return disable_uom_v2_service(uom=uom, disabled=disabled, **kwargs)


@frappe.whitelist()
def delete_uom_v2(uom: str, **kwargs):
	return delete_uom_v2_service(uom=uom, **kwargs)
