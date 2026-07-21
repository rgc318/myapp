import frappe
from frappe.utils import cint

from myapp.test_data.company_reset import (
	get_company_transaction_reset as get_company_transaction_reset_service,
	preview_company_transaction_reset as preview_company_transaction_reset_service,
	request_company_transaction_reset as request_company_transaction_reset_service,
)
from myapp.test_data.service import (
	get_dataset_run as get_dataset_run_service,
	list_dataset_runs as list_dataset_runs_service,
	list_test_datasets as list_test_datasets_service,
	preview_dataset as preview_dataset_service,
	request_dataset_run as request_dataset_run_service,
	validate_latest_dataset as validate_latest_dataset_service,
)


@frappe.whitelist()
def list_test_datasets_v1():
	return list_test_datasets_service()


@frappe.whitelist()
def preview_test_dataset_v1(
	dataset_code: str,
	company: str,
	warehouse: str,
	action: str = "generate",
	base_date: str | None = None,
	seed: int = 1,
	scenario_keys=None,
	scale: str | None = None,
):
	return preview_dataset_service(
		dataset_code=dataset_code,
		company=company,
		warehouse=warehouse,
		action=action,
		base_date=base_date,
		seed=cint(seed) or 1,
		scenario_keys=scenario_keys,
		scale=scale,
	)


@frappe.whitelist(methods=["POST"])
def request_test_dataset_run_v1(
	dataset_code: str,
	company: str,
	warehouse: str,
	action: str,
	confirmation_text: str,
	base_date: str | None = None,
	seed: int = 1,
	scenario_keys=None,
	scale: str | None = None,
):
	return request_dataset_run_service(
		dataset_code=dataset_code,
		company=company,
		warehouse=warehouse,
		action=action,
		confirmation_text=confirmation_text,
		base_date=base_date,
		seed=cint(seed) or 1,
		scenario_keys=scenario_keys,
		scale=scale,
	)


@frappe.whitelist()
def get_test_dataset_run_v1(run_name: str):
	return get_dataset_run_service(run_name)


@frappe.whitelist()
def list_test_dataset_runs_v1(start: int = 0, limit: int = 20):
	return list_dataset_runs_service(start=cint(start), limit=cint(limit))


@frappe.whitelist(methods=["POST"])
def validate_test_dataset_v1(company: str, dataset_code: str):
	return validate_latest_dataset_service(company, dataset_code)


@frappe.whitelist()
def preview_company_transaction_reset_v1(company: str):
	return preview_company_transaction_reset_service(company=company)


@frappe.whitelist(methods=["POST"])
def request_company_transaction_reset_v1(
	company: str,
	confirmation_text: str,
	acknowledge_irreversible: int = 0,
):
	return request_company_transaction_reset_service(
		company=company,
		confirmation_text=confirmation_text,
		acknowledge_irreversible=cint(acknowledge_irreversible),
	)


@frappe.whitelist()
def get_company_transaction_reset_v1(record_name: str):
	return get_company_transaction_reset_service(record_name)
