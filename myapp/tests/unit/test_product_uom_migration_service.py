from unittest import TestCase
from unittest.mock import MagicMock, call, patch

import frappe

from myapp.services import wholesale_service
from myapp.services.wholesale_service import (
	_normalize_product_uom_migration_mappings,
	assess_product_uom_migration_v1,
	execute_product_uom_migration_v1,
)


class TestProductUomMigrationService(TestCase):
	@patch("myapp.services.wholesale_service.current_user", return_value="user@example.com")
	@patch("myapp.services.wholesale_service.frappe.get_roles", return_value=["Stock Manager"])
	def test_assessment_requires_system_manager(self, _mock_roles, _mock_current_user):
		with self.assertRaises(frappe.PermissionError):
			assess_product_uom_migration_v1("ITEM-001")

	@patch("myapp.services.wholesale_service._get_uom_map", return_value={"ITEM-001": []})
	@patch("myapp.services.wholesale_service._get_product_uom_migration_alternatives", return_value=[])
	@patch("myapp.services.wholesale_service._get_product_uom_migration_prices", return_value=[])
	@patch(
		"myapp.services.wholesale_service._get_product_uom_migration_open_transactions",
		return_value={"sales_order_count": 1, "purchase_order_count": 0},
	)
	@patch(
		"myapp.services.wholesale_service._get_product_uom_migration_bins",
		return_value=[
			{
				"warehouse": "Stores - TC",
				"actual_qty": 4,
				"reserved_qty": 2,
			},
		],
	)
	@patch("myapp.services.wholesale_service.require_document_permission")
	@patch("myapp.services.wholesale_service._require_product_uom_migration_manager")
	def test_assessment_reports_stock_commitments_and_open_orders_as_blockers(
		self,
		_mock_require_manager,
		mock_require_document,
		_mock_bins,
		_mock_open_transactions,
		_mock_prices,
		_mock_alternatives,
		_mock_uom_map,
	):
		item = frappe._dict(
			name="ITEM-001",
			item_name="测试商品",
			modified="2026-08-31 12:00:00",
			disabled=0,
			stock_uom="Nos",
			barcodes=[],
			has_variants=0,
			variant_of=None,
			is_fixed_asset=0,
		)
		mock_require_document.return_value = item
		fake_db = MagicMock()
		fake_db.count.return_value = 2
		with (
			patch.object(wholesale_service.frappe, "db", fake_db),
			patch("myapp.services.wholesale_service.frappe.get_all", return_value=[]),
		):
			result = assess_product_uom_migration_v1("ITEM-001")

		blocker_codes = {row["code"] for row in result["data"]["blockers"]}
		self.assertEqual(
			blocker_codes,
			{"NON_ZERO_STOCK", "COMMITTED_STOCK_EXISTS", "OPEN_SALES_ORDERS"},
		)
		self.assertFalse(result["data"]["can_execute"])
		self.assertEqual(result["data"]["history"]["stock_ledger_entry_count"], 2)

	def test_mapping_requires_explicit_decision_for_every_source_row(self):
		with (
			patch(
				"myapp.services.wholesale_service.frappe.throw",
				side_effect=frappe.ValidationError,
			),
			self.assertRaises(frappe.ValidationError),
		):
			_normalize_product_uom_migration_mappings(
				[{"source_name": "PRICE-1", "action": "copy", "target_uom": "Box"}],
				source_rows=[{"name": "PRICE-1"}, {"name": "PRICE-2"}],
				mapping_kind="price",
			)

	@patch(
		"myapp.services.wholesale_service._build_product_detail_payload",
		return_value={"item_code": "ITEM-NEW"},
	)
	@patch("myapp.services.wholesale_service._get_item_specification_field", return_value=None)
	@patch("myapp.services.wholesale_service._get_item_nickname_field", return_value=None)
	@patch("myapp.services.wholesale_service._get_item_mode_default_uom_field", return_value=None)
	@patch("myapp.services.wholesale_service._apply_item_uom_updates")
	@patch("myapp.services.wholesale_service._upsert_item_price")
	@patch(
		"myapp.services.wholesale_service._validate_business_uom_conversion_map",
		return_value=("Nos", {"Nos": 1.0, "Box": 24.0}),
	)
	@patch("myapp.services.wholesale_service._build_product_uom_migration_assessment")
	@patch("myapp.services.wholesale_service.require_document_permission")
	@patch("myapp.services.wholesale_service.require_doctype_permission")
	@patch("myapp.services.wholesale_service._require_product_uom_migration_manager")
	@patch("myapp.services.wholesale_service.run_idempotent")
	def test_execute_creates_replacement_moves_barcode_and_disables_source(
		self,
		mock_run_idempotent,
		_mock_require_manager,
		mock_require_doctype,
		mock_require_document,
		mock_build_assessment,
		_mock_validate_uoms,
		mock_upsert_price,
		mock_apply_uoms,
		_mock_mode_field,
		_mock_nickname_field,
		_mock_specification_field,
		_mock_build_detail,
	):
		mock_run_idempotent.side_effect = lambda _namespace, _request_id, callback: callback()
		barcode_child = MagicMock()
		barcode_child.name = "BAR-ROW-1"
		source = MagicMock()
		source.name = "ITEM-OLD"
		source.item_name = "测试商品"
		source.modified = "2026-08-31 12:00:00"
		source.item_group = "Products"
		source.brand = "Brand A"
		source.description = "desc"
		source.image = None
		source.is_stock_item = 1
		source.is_sales_item = 1
		source.is_purchase_item = 1
		source.include_item_in_manufacturing = 0
		source.has_batch_no = 0
		source.has_serial_no = 0
		source.barcodes = [barcode_child]
		mock_require_document.return_value = source
		mock_build_assessment.return_value = {
			"blockers": [],
			"prices": [
				{
					"name": "PRICE-1",
					"price_list": "Wholesale",
					"currency": "CNY",
					"rate": 99,
					"uom": "Wrong UOM",
				},
			],
			"barcodes": [
				{
					"name": "BAR-ROW-1",
					"barcode": "690000000001",
					"uom": "Wrong UOM",
				},
			],
		}
		new_item = MagicMock()
		new_item.name = "ITEM-NEW"
		alternative = MagicMock()
		alternative.name = "ALT-1"
		mock_upsert_price.return_value = frappe._dict(name="PRICE-NEW")

		def new_doc(doctype):
			return {"Item": new_item, "Item Alternative": alternative}[doctype]

		fake_db = MagicMock()
		fake_db.exists.return_value = False
		with (
			patch.object(wholesale_service.frappe, "db", fake_db),
			patch("myapp.services.wholesale_service.frappe.new_doc", side_effect=new_doc),
		):
			result = execute_product_uom_migration_v1(
				"ITEM-OLD",
				source_modified="2026-08-31 12:00:00",
				new_item_code="ITEM-NEW",
				new_item_name="测试商品（新）",
				stock_uom="Nos",
				uom_conversions=[
					{"uom": "Nos", "conversion_factor": 1},
					{"uom": "Box", "conversion_factor": 24},
				],
				price_mappings=[
					{"source_name": "PRICE-1", "action": "copy", "target_uom": "Box"},
				],
				barcode_mappings=[
					{"source_name": "BAR-ROW-1", "action": "move", "target_uom": "Nos"},
				],
				confirm_disable_source=1,
				confirm_history_preserved=1,
				request_id="migration-001",
			)

		self.assertTrue(source.disabled)
		self.assertEqual(source.allow_alternative_item, 1)
		source.remove.assert_called_once_with(barcode_child)
		source.save.assert_called_once()
		mock_apply_uoms.assert_called_once()
		new_item.append.assert_called_once_with(
			"barcodes",
			{"barcode": "690000000001", "uom": "Nos"},
		)
		new_item.insert.assert_called_once()
		mock_upsert_price.assert_called_once_with(
			item_code="ITEM-NEW",
			rate=99,
			price_list="Wholesale",
			currency="CNY",
			uom="Box",
		)
		alternative.insert.assert_called_once()
		self.assertEqual(result["data"]["new_item"]["item_code"], "ITEM-NEW")
		self.assertEqual(
			mock_require_doctype.call_args_list,
			[
				call("Item", "create"),
				call("Item Alternative", "create"),
				call("Item Price", "create"),
			],
		)
