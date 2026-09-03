from __future__ import annotations

import frappe


class OptimisticLockConflictError(frappe.ValidationError):
	"""A user-safe conflict raised when a document changed after it was loaded."""

	def __init__(
		self,
		message: str,
		*,
		doctype: str,
		name: str,
		expected_modified: str,
		current_modified: str,
	):
		super().__init__(message)
		self.public_data = {
			"conflict_type": "document_modified",
			"doctype": doctype,
			"name": name,
			"expected_modified": expected_modified,
			"current_modified": current_modified,
		}
