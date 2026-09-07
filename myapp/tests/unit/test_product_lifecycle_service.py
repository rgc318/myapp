from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services import product_lifecycle_service as service


class TestProductLifecycleService(TestCase):
	def setUp(self):
		self.item = frappe._dict(name="ITEM-1", item_name="商品", modified="2026-09-07", disabled=0)
		self.permissions = self._patch("require_document_permission", return_value=self.item)
		self.exists = self._patch("frappe.db", new=MagicMock()).exists
		self.exists.return_value = False
		self.static_links = self._patch("check_if_doc_is_linked")
		self.dynamic_links = self._patch("check_if_doc_is_dynamically_linked")
		self._patch("frappe.clear_last_message")
		self.delete = self._patch("frappe.delete_doc")

	def _patch(self, name, **kwargs):
		patcher = patch(f"myapp.services.product_lifecycle_service.{name}", **kwargs)
		self.addCleanup(patcher.stop)
		return patcher.start()

	def test_valid_preview_is_not_execution_authority(self):
		result = service.preview_product_lifecycle("delete", ["ITEM-1"], "重复建档")
		self.assertTrue(result["preflight_passed"])
		self.assertFalse(result["execution_available"])
		self.assertEqual(result["scope"], "shared_item_master")
		self.assertEqual(result["targets"][0]["item_modified"], "2026-09-07")
		self.delete.assert_not_called()

	def test_invalid_requests_are_rejected_before_reading(self):
		for operation, codes, reason in [
			("merge", ["ITEM-1"], "原因"), ("delete", [], "原因"),
			("delete", ["ITEM-1", " ITEM-1 "], "原因"),
			("delete", [None], "原因"), ("delete", "ITEM-1", "原因"),
			("delete", [str(i) for i in range(21)], "原因"),
			("delete", ["ITEM-1"], " "), ("delete", ["ITEM-1"], "字" * 501),
		]:
			with self.subTest(operation=operation, codes=codes):
				with self.assertRaises(frappe.ValidationError):
					service.preview_product_lifecycle(operation, codes, reason)
		self.permissions.assert_not_called()

	def test_all_targets_authorized_before_reference_queries(self):
		self.permissions.side_effect = [self.item, self.item, frappe.PermissionError("denied")]
		with self.assertRaises(frappe.PermissionError):
			service.preview_product_lifecycle("delete", ["ITEM-1", "ITEM-2"], "原因")
		self.exists.assert_not_called()
		self.delete.assert_not_called()

	def test_each_cascade_or_history_dependency_blocks_delete(self):
		for doctype, expected in [
			("Stock Ledger Entry", "PRODUCT_HAS_STOCK_HISTORY"),
			("Bin", "PRODUCT_HAS_STOCK_RECORD"),
			("Item Price", "PRODUCT_HAS_PRICES"),
			("Item", "PRODUCT_HAS_VARIANTS"),
			("File", "PRODUCT_HAS_ATTACHMENTS"),
		]:
			with self.subTest(doctype=doctype):
				self.exists.side_effect = lambda dt, filters: dt == doctype
				result = service.preview_product_lifecycle("delete", ["ITEM-1"], "原因")
				self.assertFalse(result["preflight_passed"])
				self.assertEqual(result["targets"][0]["blockers"][0]["code"], expected)

	def test_image_reference_blocks_native_file_cleanup(self):
		self.item.image = "/private/files/product.png"
		result = service.preview_product_lifecycle("delete", ["ITEM-1"], "原因")
		self.assertFalse(result["preflight_passed"])
		self.assertEqual(result["targets"][0]["blockers"][0]["code"], "PRODUCT_HAS_IMAGE")

	def test_static_and_dynamic_reference_errors_are_redacted(self):
		for checker in [self.static_links, self.dynamic_links]:
			with self.subTest(checker=checker):
				checker.side_effect = frappe.LinkExistsError("SECRET-COMPANY-INVOICE")
				result = service.preview_product_lifecycle("delete", ["ITEM-1"], "原因")
				self.assertFalse(result["preflight_passed"])
				self.assertNotIn("SECRET", str(result))
				checker.side_effect = None

	def test_unexpected_reference_failure_does_not_become_pass(self):
		self.static_links.side_effect = RuntimeError("database unavailable")
		with self.assertRaises(RuntimeError):
			service.preview_product_lifecycle("delete", ["ITEM-1"], "原因")

	def test_enable_disable_use_write_permission_without_deletion_probes(self):
		for operation in ["enable", "disable"]:
			result = service.preview_product_lifecycle(operation, ["ITEM-1"], "原因")
			self.permissions.assert_called_with("Item", "ITEM-1", "write")
			self.assertEqual(result["targets"][0]["already_in_requested_state"], operation == "enable")
			self.assertFalse(result["execution_available"])
		self.exists.assert_not_called()
		self.static_links.assert_not_called()
		self.delete.assert_not_called()

	def test_preview_never_calls_document_mutations(self):
		item = MagicMock(name="item")
		item.name = "ITEM-1"
		item.modified = "version"
		item.get.side_effect = lambda key: {"disabled": 0, "item_name": "商品"}.get(key)
		self.permissions.return_value = item
		for operation in ["enable", "disable", "delete"]:
			service.preview_product_lifecycle(operation, ["ITEM-1"], "原因")
		item.save.assert_not_called()
		item.delete.assert_not_called()
		item.run_method.assert_not_called()
