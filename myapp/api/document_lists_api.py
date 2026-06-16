import frappe
from frappe.utils import cint

from myapp.services.document_list_service import list_business_documents_v1 as list_business_documents_v1_service


@frappe.whitelist()
def list_business_documents_v1(
	doctype: str,
	search_key: str | None = None,
	company: str | None = None,
	party: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	docstatus=None,
	sort_by: str | None = None,
	limit: int = 20,
	start: int = 0,
):
	return list_business_documents_v1_service(
		doctype=doctype,
		search_key=search_key,
		company=company,
		party=party,
		date_from=date_from,
		date_to=date_to,
		docstatus=docstatus,
		sort_by=sort_by,
		limit=cint(limit),
		start=cint(start),
	)
