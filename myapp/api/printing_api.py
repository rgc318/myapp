from myapp.services.printing_service import build_print_file_download_v1 as build_print_file_download_v1_service
from myapp.services.printing_service import get_print_file_v1 as get_print_file_v1_service
from myapp.services.printing_service import get_print_preview_v1 as get_print_preview_v1_service
from myapp.services.printing_service import get_print_templates_v1 as get_print_templates_v1_service
from myapp.services.printing_service import list_print_doctypes_v1 as list_print_doctypes_v1_service
from myapp.services.printing_service import list_print_jobs_v1 as list_print_jobs_v1_service
from myapp.services.printing_service import record_print_job_v1 as record_print_job_v1_service


def list_print_doctypes_v1():
	return list_print_doctypes_v1_service()


def get_print_templates_v1(doctype: str):
	return get_print_templates_v1_service(doctype=doctype)


def record_print_job_v1(
	doctype: str,
	docname: str,
	template: str | None = None,
	action: str = "print",
	output: str = "pdf",
	status: str = "success",
	filename: str | None = None,
	file_url: str | None = None,
	error: str | None = None,
	metadata: dict | str | None = None,
):
	return record_print_job_v1_service(
		doctype=doctype,
		docname=docname,
		template=template,
		action=action,
		output=output,
		status=status,
		filename=filename,
		file_url=file_url,
		error=error,
		metadata=metadata,
	)


def list_print_jobs_v1(
	doctype: str,
	docname: str,
	action: str | None = None,
	template: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	user: str | None = None,
	limit: int = 20,
):
	return list_print_jobs_v1_service(
		doctype=doctype,
		docname=docname,
		action=action,
		template=template,
		date_from=date_from,
		date_to=date_to,
		user=user,
		limit=limit,
	)


def get_print_preview_v1(
	doctype: str,
	docname: str,
	template: str | None = None,
	output: str = "html",
):
	return get_print_preview_v1_service(
		doctype=doctype,
		docname=docname,
		template=template,
		output=output,
	)


def get_print_file_v1(
	doctype: str,
	docname: str,
	template: str | None = None,
	filename: str | None = None,
	archive: bool | int | str = False,
):
	return get_print_file_v1_service(
		doctype=doctype,
		docname=docname,
		template=template,
		filename=filename,
		archive=archive,
	)


def build_print_file_download_v1(
	doctype: str,
	docname: str,
	template: str | None = None,
	filename: str | None = None,
):
	return build_print_file_download_v1_service(
		doctype=doctype,
		docname=docname,
		template=template,
		filename=filename,
	)
