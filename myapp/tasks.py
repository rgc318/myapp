from __future__ import annotations

import frappe

from myapp.services.media_service import cleanup_expired_temporary_item_images
from myapp.services.printing_service import cleanup_expired_print_batches
from myapp.utils.idempotency import cleanup_expired_idempotency_records


def cleanup_temporary_item_images():
	result = cleanup_expired_temporary_item_images()
	if result["data"]["deleted_count"]:
		frappe.db.commit()
	return result


def cleanup_idempotency_records():
	result = cleanup_expired_idempotency_records()
	if result["data"]["deleted_count"]:
		frappe.db.commit()
	return result


def cleanup_print_batches():
	result = cleanup_expired_print_batches()
	if result["data"]["deleted_count"] or result["data"]["deleted_file_count"]:
		frappe.db.commit()
	return result
