from myapp.services.printing_service import build_print_file_download_v1 as build_print_file_download_v1_service
from myapp.services.printing_service import build_print_batch_archive_download_v1 as build_print_batch_archive_download_v1_service
from myapp.services.printing_service import build_print_batch_merged_pdf_v1 as build_print_batch_merged_pdf_v1_service
from myapp.services.printing_service import cancel_print_batch_v1 as cancel_print_batch_v1_service
from myapp.services.printing_service import create_print_batch_v1 as create_print_batch_v1_service
from myapp.services.printing_service import get_print_file_v1 as get_print_file_v1_service
from myapp.services.printing_service import get_print_batch_v1 as get_print_batch_v1_service
from myapp.services.printing_service import get_print_preview_v1 as get_print_preview_v1_service
from myapp.services.printing_service import get_print_settings_v1 as get_print_settings_v1_service
from myapp.services.printing_service import get_print_templates_v1 as get_print_templates_v1_service
from myapp.services.printing_service import list_print_doctypes_v1 as list_print_doctypes_v1_service
from myapp.services.printing_service import list_print_batches_v1 as list_print_batches_v1_service
from myapp.services.printing_service import list_print_jobs_v1 as list_print_jobs_v1_service
from myapp.services.printing_service import list_print_jobs_v2 as list_print_jobs_v2_service
from myapp.services.printing_service import record_print_job_v1 as record_print_job_v1_service
from myapp.services.printing_service import retry_print_batch_failed_v1 as retry_print_batch_failed_v1_service
from myapp.services.printing_service import set_print_default_template_v1 as set_print_default_template_v1_service


def list_print_doctypes_v1():
	return list_print_doctypes_v1_service()


def get_print_templates_v1(doctype: str):
	return get_print_templates_v1_service(doctype=doctype)


def create_print_batch_v1(
	documents,
	output: str = "pdf",
	template: str | None = None,
	run_async: bool | int | str = True,
	metadata: dict | str | None = None,
	request_id: str | None = None,
):
	return create_print_batch_v1_service(
		documents=documents,
		output=output,
		template=template,
		run_async=run_async,
		metadata=metadata,
		request_id=request_id,
	)


def get_print_batch_v1(batch_id: str):
	return get_print_batch_v1_service(batch_id=batch_id)


def list_print_batches_v1(
	status: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	requested_by: str | None = None,
	start: int = 0,
	limit: int = 20,
):
	return list_print_batches_v1_service(
		status=status,
		date_from=date_from,
		date_to=date_to,
		requested_by=requested_by,
		start=start,
		limit=limit,
	)


def get_print_settings_v1():
	return get_print_settings_v1_service()


def set_print_default_template_v1(
	doctype: str,
	template: str,
	enabled: bool | int | str = True,
	metadata: dict | str | None = None,
):
	return set_print_default_template_v1_service(
		doctype=doctype,
		template=template,
		enabled=enabled,
		metadata=metadata,
	)


def cancel_print_batch_v1(batch_id: str):
	return cancel_print_batch_v1_service(batch_id=batch_id)


def retry_print_batch_failed_v1(
	batch_id: str,
	run_async: bool | int | str = True,
	metadata: dict | str | None = None,
):
	return retry_print_batch_failed_v1_service(
		batch_id=batch_id,
		run_async=run_async,
		metadata=metadata,
	)


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


def list_print_jobs_v2(
	doctype: str | None = None,
	docname: str | None = None,
	action: str | None = None,
	status: str | None = None,
	template: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	user: str | None = None,
	start: int = 0,
	limit: int = 20,
):
	return list_print_jobs_v2_service(
		doctype=doctype,
		docname=docname,
		action=action,
		status=status,
		template=template,
		date_from=date_from,
		date_to=date_to,
		user=user,
		start=start,
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


def build_print_batch_archive_download_v1(batch_id: str, filename: str | None = None):
	return build_print_batch_archive_download_v1_service(batch_id=batch_id, filename=filename)


def build_print_batch_merged_pdf_v1(batch_id: str, filename: str | None = None):
	return build_print_batch_merged_pdf_v1_service(batch_id=batch_id, filename=filename)
