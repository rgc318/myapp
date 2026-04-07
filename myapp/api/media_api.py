import frappe

from myapp.services.media_service import delete_item_image as delete_item_image_service
from myapp.services.media_service import replace_item_image as replace_item_image_service
from myapp.services.media_service import upload_item_image as upload_item_image_service


@frappe.whitelist()
def upload_item_image(
	filename: str,
	file_content_base64: str,
	content_type: str | None = None,
	item_code: str | None = None,
	is_private: bool = False,
):
	return upload_item_image_service(
		filename=filename,
		file_content_base64=file_content_base64,
		content_type=content_type,
		item_code=item_code,
		is_private=is_private,
	)


@frappe.whitelist()
def replace_item_image(
	item_code: str,
	filename: str,
	file_content_base64: str,
	content_type: str | None = None,
	is_private: bool = False,
):
	return replace_item_image_service(
		item_code=item_code,
		filename=filename,
		file_content_base64=file_content_base64,
		content_type=content_type,
		is_private=is_private,
	)


@frappe.whitelist()
def delete_item_image(item_code: str):
	return delete_item_image_service(item_code=item_code)
