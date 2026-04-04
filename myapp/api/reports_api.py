from frappe.utils import cint

from myapp.services.report_service import get_business_report_v1 as get_business_report_v1_service
from myapp.services.report_service import get_cashflow_report_v1 as get_cashflow_report_v1_service
from myapp.services.report_service import get_purchase_report_v1 as get_purchase_report_v1_service
from myapp.services.report_service import get_sales_report_v1 as get_sales_report_v1_service
from myapp.services.report_service import list_cashflow_entries_v1 as list_cashflow_entries_v1_service


def get_business_report_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 10,
):
	return get_business_report_v1_service(
		company=company,
		date_from=date_from,
		date_to=date_to,
		limit=cint(limit),
	)


def get_cashflow_report_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
):
	return get_cashflow_report_v1_service(
		company=company,
		date_from=date_from,
		date_to=date_to,
	)


def get_sales_report_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 10,
):
	return get_sales_report_v1_service(
		company=company,
		date_from=date_from,
		date_to=date_to,
		limit=cint(limit),
	)


def get_purchase_report_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 10,
):
	return get_purchase_report_v1_service(
		company=company,
		date_from=date_from,
		date_to=date_to,
		limit=cint(limit),
	)


def list_cashflow_entries_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	page: int = 1,
	page_size: int = 20,
):
	return list_cashflow_entries_v1_service(
		company=company,
		date_from=date_from,
		date_to=date_to,
		page=cint(page),
		page_size=cint(page_size),
	)
