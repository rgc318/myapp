from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services import product_correction_service
from myapp.services.product_correction_service import (
	_legacy_replacement,
	resolve_active_product_reference,
)


class TestProductCorrectionService(TestCase):
	@patch("myapp.services.product_correction_service.require_document_permission")
	@patch("myapp.services.product_correction_service._legacy_replacement", return_value=None)
	@patch("myapp.services.product_correction_service._latest_recorded_replacement")
	def test_resolves_formal_replacement_chain(
		self,
		mock_latest_replacement,
		_mock_legacy_replacement,
		mock_require_document,
	):
		mock_latest_replacement.side_effect = lambda item_code: {
			"ITEM-A": {"name": "CORR-A", "target_item": "ITEM-B"},
			"ITEM-B": {"name": "CORR-B", "target_item": "ITEM-C"},
		}.get(item_code)
		fake_db = MagicMock()
		fake_db.get_value.return_value = 0

		with patch.object(product_correction_service.frappe, "db", fake_db):
			result = resolve_active_product_reference("ITEM-A")

		self.assertEqual(result["active_item_code"], "ITEM-C")
		self.assertTrue(result["changed"])
		self.assertEqual(result["resolution_source"], "correction_record")
		self.assertTrue(result["requires_confirmation"])
		self.assertEqual(
			result["chain"],
			[
				{
					"source_item": "ITEM-A",
					"target_item": "ITEM-B",
					"source": "correction_record",
				},
				{
					"source_item": "ITEM-B",
					"target_item": "ITEM-C",
					"source": "correction_record",
				},
			],
		)
		self.assertEqual(
			[mock_call.args[:3] for mock_call in mock_require_document.call_args_list],
			[("Item", "ITEM-A", "read"), ("Item", "ITEM-C", "read")],
		)

	def test_legacy_single_active_one_way_alternative_is_resolved(self):
		fake_db = MagicMock()
		fake_db.get_value.side_effect = lambda _doctype, name, _field: {
			"ITEM-OLD": 1,
			"ITEM-NEW": 0,
		}[name]
		fake_db.exists.return_value = True
		with (
			patch.object(product_correction_service.frappe, "db", fake_db),
			patch(
				"myapp.services.product_correction_service.frappe.get_list",
				return_value=[
					frappe._dict(
						name="ALT-1",
						alternative_item_code="ITEM-NEW",
					),
				],
			),
		):
			result = _legacy_replacement("ITEM-OLD")

		self.assertEqual(result, {"name": "ALT-1", "target_item": "ITEM-NEW"})

	def test_legacy_multiple_active_alternatives_are_not_auto_selected(self):
		fake_db = MagicMock()
		fake_db.get_value.side_effect = lambda _doctype, name, _field: 1 if name == "ITEM-OLD" else 0
		fake_db.exists.return_value = True
		with (
			patch.object(product_correction_service.frappe, "db", fake_db),
			patch(
				"myapp.services.product_correction_service.frappe.get_list",
				return_value=[
					frappe._dict(name="ALT-1", alternative_item_code="ITEM-A"),
					frappe._dict(name="ALT-2", alternative_item_code="ITEM-B"),
				],
			),
		):
			self.assertIsNone(_legacy_replacement("ITEM-OLD"))

	@patch("myapp.services.product_correction_service.require_document_permission")
	@patch("myapp.services.product_correction_service._legacy_replacement", return_value=None)
	@patch("myapp.services.product_correction_service._latest_recorded_replacement")
	def test_replacement_cycle_is_rejected(
		self,
		mock_latest_replacement,
		_mock_legacy_replacement,
		_mock_require_document,
	):
		mock_latest_replacement.side_effect = lambda item_code: {
			"ITEM-A": {"name": "CORR-A", "target_item": "ITEM-B"},
			"ITEM-B": {"name": "CORR-B", "target_item": "ITEM-A"},
		}[item_code]

		with (
			patch(
				"myapp.services.product_correction_service.frappe.throw",
				side_effect=frappe.ValidationError,
			),
			self.assertRaises(frappe.ValidationError),
		):
			resolve_active_product_reference("ITEM-A")

	@patch("myapp.services.product_correction_service.require_document_permission")
	@patch("myapp.services.product_correction_service._legacy_replacement", return_value=None)
	@patch("myapp.services.product_correction_service._table_exists", return_value=False)
	def test_missing_correction_table_keeps_current_item_available(
		self,
		_mock_table_exists,
		_mock_legacy_replacement,
		_mock_require_document,
	):
		fake_db = MagicMock()
		fake_db.get_value.return_value = 0
		with patch.object(product_correction_service.frappe, "db", fake_db):
			result = resolve_active_product_reference("ITEM-001")

		self.assertFalse(result["changed"])
		self.assertEqual(result["active_item_code"], "ITEM-001")
		self.assertEqual(result["chain"], [])
