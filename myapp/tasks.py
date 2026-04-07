from __future__ import annotations

import frappe

from myapp.services.media_service import cleanup_expired_temporary_item_images


def cleanup_temporary_item_images():
	result = cleanup_expired_temporary_item_images()
	if result["data"]["deleted_count"]:
		frappe.db.commit()
	return result
