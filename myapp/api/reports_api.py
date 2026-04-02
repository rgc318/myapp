from frappe.utils import cint

from myapp.services.report_service import get_business_report_v1 as get_business_report_v1_service


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
