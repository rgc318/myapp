import frappe

from myapp.services.return_service import get_return_source_context_v2 as get_return_source_context_v2_service


@frappe.whitelist()
def get_return_source_context_v2(source_doctype: str, source_name: str):
    return get_return_source_context_v2_service(source_doctype=source_doctype, source_name=source_name)
