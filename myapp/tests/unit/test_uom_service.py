from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.uom_service import (
	create_uom_v2,
	delete_uom_v2,
	disable_uom_v2,
	get_uom_detail_v2,
	list_uoms_v2,
	update_uom_v2,
)


class TestUOMService(TestCase):
	@patch("myapp.services.uom_service.frappe.get_all")
	def test_list_uoms_v2_returns_rows_with_meta(self, mock_get_all):
		mock_get_all.side_effect = [
			[
				frappe._dict(
					{
						"name": "Box",
						"uom_name": "Box",
						"symbol": "箱",
						"description": "整箱",
						"enabled": 1,
						"must_be_whole_number": 1,
						"modified": "2026-03-26 10:00:00",
						"creation": "2026-03-20 10:00:00",
					}
				)
			],
			["Box", "Case"],
		]

		result = list_uoms_v2(search_key="Bo", limit=20, start=0)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"][0]["uom_name"], "Box")
		self.assertEqual(result["meta"]["total"], 2)
		self.assertTrue(result["meta"]["has_more"])

	@patch("myapp.services.uom_service._collect_uom_references")
	@patch("myapp.services.uom_service.frappe.get_doc")
	def test_get_uom_detail_v2_includes_usage_summary(self, mock_get_doc, mock_collect_uom_references):
		mock_get_doc.return_value = frappe._dict(
			{
				"name": "Box",
				"uom_name": "Box",
				"enabled": 1,
				"must_be_whole_number": 1,
				"symbol": "箱",
				"description": "整箱",
			}
		)
		mock_collect_uom_references.return_value = {
			"total_references": 2,
			"doctypes": [{"doctype": "Item", "fieldname": "stock_uom", "count": 2, "examples": ["ITEM-001"]}],
		}

		result = get_uom_detail_v2("Box")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["usage_summary"]["total_references"], 2)

	@patch("myapp.services.uom_service.run_idempotent")
	def test_create_uom_v2_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {"status": "success", "data": {"name": "Box"}}

		result = create_uom_v2(uom_name="Box", request_id="uom-create-001")

		self.assertEqual(result["status"], "success")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.uom_service._new_doc")
	@patch("myapp.services.uom_service._uom_exists")
	def test_create_uom_v2_creates_uom(self, mock_exists, mock_new_doc):
		doc = MagicMock()
		doc.name = "Box"
		doc.uom_name = "Box"
		doc.enabled = 1
		doc.must_be_whole_number = 1
		doc.symbol = "箱"
		doc.description = "整箱"
		mock_new_doc.return_value = doc
		mock_exists.return_value = False

		result = create_uom_v2(
			uom_name="Box",
			symbol="箱",
			description="整箱",
			enabled=1,
			must_be_whole_number=1,
		)

		self.assertEqual(result["status"], "success")
		doc.insert.assert_called_once()

	@patch("myapp.services.uom_service.frappe.throw")
	@patch("myapp.services.uom_service.frappe.get_doc")
	def test_update_uom_v2_rejects_rename(self, mock_get_doc, mock_throw):
		mock_get_doc.return_value = frappe._dict(
			{
				"name": "Box",
				"uom_name": "Box",
				"enabled": 1,
				"must_be_whole_number": 1,
			}
		)
		mock_throw.side_effect = RuntimeError("rename blocked")

		with self.assertRaisesRegex(RuntimeError, "rename blocked"):
			update_uom_v2(uom="Box", uom_name="Case")

	@patch("myapp.services.uom_service._collect_uom_references")
	@patch("myapp.services.uom_service.frappe.throw")
	@patch("myapp.services.uom_service.frappe.get_doc")
	def test_update_uom_v2_rejects_whole_number_rule_change_when_referenced(
		self,
		mock_get_doc,
		mock_throw,
		mock_collect_uom_references,
	):
		doc = MagicMock()
		doc.name = "Piece"
		doc.uom_name = "Piece"
		doc.must_be_whole_number = 0
		doc.enabled = 1
		mock_get_doc.return_value = doc
		mock_collect_uom_references.return_value = {
			"total_references": 3,
			"doctypes": [{"doctype": "Item", "fieldname": "stock_uom", "count": 3, "examples": ["ITEM-001"]}],
		}
		mock_throw.side_effect = RuntimeError("whole number rule blocked")

		with self.assertRaisesRegex(RuntimeError, "whole number rule blocked"):
			update_uom_v2(uom="Piece", must_be_whole_number=1)

	@patch("myapp.services.uom_service._collect_uom_references")
	@patch("myapp.services.uom_service.frappe.get_doc")
	def test_update_uom_v2_updates_allowed_fields(self, mock_get_doc, mock_collect_uom_references):
		doc = MagicMock()
		doc.name = "Piece"
		doc.uom_name = "Piece"
		doc.enabled = 1
		doc.must_be_whole_number = 0
		mock_get_doc.return_value = doc
		mock_collect_uom_references.return_value = {"total_references": 0, "doctypes": []}

		result = update_uom_v2(
			uom="Piece",
			symbol="件",
			description="单件",
			enabled=0,
			must_be_whole_number=0,
		)

		self.assertEqual(result["status"], "success")
		doc.save.assert_called_once()
		self.assertEqual(doc.symbol, "件")
		self.assertEqual(doc.enabled, 0)

	@patch("myapp.services.uom_service.run_idempotent")
	def test_disable_uom_v2_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {"status": "success", "data": {"name": "Box"}}

		result = disable_uom_v2(uom="Box", request_id="uom-disable-001")

		self.assertEqual(result["status"], "success")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.uom_service._collect_uom_references")
	@patch("myapp.services.uom_service.frappe.throw")
	@patch("myapp.services.uom_service.frappe.get_doc")
	def test_delete_uom_v2_rejects_referenced_uom(self, mock_get_doc, mock_throw, mock_collect_uom_references):
		doc = MagicMock()
		doc.name = "Box"
		doc.uom_name = "Box"
		mock_get_doc.return_value = doc
		mock_collect_uom_references.return_value = {
			"total_references": 2,
			"doctypes": [{"doctype": "Item", "fieldname": "stock_uom", "count": 2, "examples": ["ITEM-001"]}],
		}
		mock_throw.side_effect = RuntimeError("delete blocked")

		with self.assertRaisesRegex(RuntimeError, "delete blocked"):
			delete_uom_v2(uom="Box")

	@patch("myapp.services.uom_service._collect_uom_references")
	@patch("myapp.services.uom_service.frappe.get_doc")
	def test_delete_uom_v2_deletes_unreferenced_uom(self, mock_get_doc, mock_collect_uom_references):
		doc = MagicMock()
		doc.name = "Loose"
		doc.uom_name = "Loose"
		mock_get_doc.return_value = doc
		mock_collect_uom_references.return_value = {"total_references": 0, "doctypes": []}

		result = delete_uom_v2(uom="Loose")

		self.assertEqual(result["status"], "success")
		doc.delete.assert_called_once()
