import frappe

from myapp.services.settlement_service import confirm_pending_document as confirm_pending_document_service
from myapp.services.settlement_service import process_sales_return as process_sales_return_service
from myapp.services.settlement_service import update_payment_status as update_payment_status_service


@frappe.whitelist()
def confirm_pending_document(doctype: str, docname: str, **kwargs):
	return confirm_pending_document_service(doctype=doctype, docname=docname, **kwargs)


@frappe.whitelist()
def update_payment_status(reference_doctype: str, reference_name: str, paid_amount: float, **kwargs):
	return update_payment_status_service(
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		paid_amount=paid_amount,
		**kwargs,
	)


@frappe.whitelist()
def process_sales_return(source_doctype: str, source_name: str, return_items=None, **kwargs):
	return process_sales_return_service(
		source_doctype=source_doctype,
		source_name=source_name,
		return_items=return_items,
		**kwargs,
	)
