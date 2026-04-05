from myapp.services.printing_service import build_print_file_download_v1 as build_print_file_download_v1_service
from myapp.services.printing_service import get_print_file_v1 as get_print_file_v1_service
from myapp.services.printing_service import get_print_preview_v1 as get_print_preview_v1_service


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
):
	return get_print_file_v1_service(
		doctype=doctype,
		docname=docname,
		template=template,
		filename=filename,
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
