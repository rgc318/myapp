from unittest import TestCase
from unittest.mock import MagicMock, call, patch

import frappe

from myapp.services import wholesale_service
from myapp.services.wholesale_service import (
	_build_product_uom_migration_price_plan,
	_create_product_uom_repack_entries,
	_execute_in_place_product_uom_correction,
	_normalize_product_uom_inventory_mappings,
	_normalize_product_uom_migration_mappings,
	_normalize_product_uom_migration_new_prices,
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
			{
				"warehouse": "Returns - TC",
				"actual_qty": -4,
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
		fake_db.exists.return_value = False
		with (
			patch.object(wholesale_service.frappe, "db", fake_db),
			patch("myapp.services.wholesale_service.frappe.get_all", return_value=[]),
		):
			result = assess_product_uom_migration_v1("ITEM-001")

		blocker_codes = {row["code"] for row in result["data"]["blockers"]}
		self.assertEqual(
			blocker_codes,
			{"NON_ZERO_STOCK", "NEGATIVE_STOCK", "COMMITTED_STOCK_EXISTS", "OPEN_SALES_ORDERS"},
		)
		self.assertFalse(result["data"]["can_execute"])
		self.assertFalse(result["data"]["can_execute_with_inventory_conversion"])
		self.assertEqual(result["data"]["history"]["stock_ledger_entry_count"], 2)
		self.assertTrue(result["data"]["suggested_new_item_code"])

	def _assess_strategy(self, stock_ledger_entry_count):
		item = frappe._dict(
			name="ITEM-001",
			item_name="测试商品",
			modified="2026-08-31 12:00:00",
			disabled=0,
			stock_uom="Wrong UOM",
			barcodes=[],
			has_variants=0,
			variant_of=None,
			is_fixed_asset=0,
		)
		fake_db = MagicMock()
		fake_db.count.return_value = stock_ledger_entry_count
		fake_db.exists.return_value = False
		with (
			patch("myapp.services.wholesale_service._require_product_uom_migration_manager"),
			patch(
				"myapp.services.wholesale_service.require_document_permission",
				return_value=item,
			),
			patch("myapp.services.wholesale_service._get_product_uom_migration_bins", return_value=[]),
			patch(
				"myapp.services.wholesale_service._get_product_uom_migration_open_transactions",
				return_value={"sales_order_count": 0, "purchase_order_count": 0},
			),
			patch("myapp.services.wholesale_service._get_product_uom_migration_prices", return_value=[]),
			patch("myapp.services.wholesale_service._get_product_uom_migration_alternatives", return_value=[]),
			patch("myapp.services.wholesale_service._get_uom_map", return_value={"ITEM-001": []}),
			patch.object(wholesale_service.frappe, "db", fake_db),
			patch("myapp.services.wholesale_service.frappe.get_all", return_value=[]),
		):
			return assess_product_uom_migration_v1("ITEM-001")["data"]

	def test_assessment_recommends_in_place_only_without_stock_history(self):
		result = self._assess_strategy(stock_ledger_entry_count=0)

		self.assertEqual(result["recommended_strategy"], "in_place")
		self.assertTrue(result["strategies"]["in_place"]["available"])

	def test_assessment_recommends_replacement_when_stock_history_exists(self):
		result = self._assess_strategy(stock_ledger_entry_count=2)

		self.assertEqual(result["recommended_strategy"], "replacement")
		self.assertFalse(result["strategies"]["in_place"]["available"])
		self.assertTrue(result["strategies"]["replacement"]["available"])

	def test_assessment_allows_replacement_with_explicit_inventory_conversion(self):
		item = frappe._dict(
			name="ITEM-001",
			item_name="测试商品",
			modified="2026-08-31 12:00:00",
			disabled=0,
			stock_uom="Wrong UOM",
			barcodes=[],
			has_variants=0,
			variant_of=None,
			is_fixed_asset=0,
		)
		fake_db = MagicMock()
		fake_db.count.return_value = 2
		fake_db.exists.return_value = False
		with (
			patch("myapp.services.wholesale_service._get_product_uom_migration_bins", return_value=[
				{
					"warehouse": "Stores - TC",
					"company": "Test Company",
					"actual_qty": 24,
					"projected_qty": 24,
				}
			]),
			patch(
				"myapp.services.wholesale_service._get_product_uom_migration_open_transactions",
				return_value={"sales_order_count": 0, "purchase_order_count": 0},
			),
			patch("myapp.services.wholesale_service._get_product_uom_migration_prices", return_value=[]),
			patch("myapp.services.wholesale_service._get_product_uom_migration_alternatives", return_value=[]),
			patch("myapp.services.wholesale_service._get_uom_map", return_value={"ITEM-001": []}),
			patch.object(wholesale_service.frappe, "db", fake_db),
			patch("myapp.services.wholesale_service.frappe.get_all", return_value=[]),
		):
			result = wholesale_service._build_product_uom_migration_assessment(item)

		self.assertFalse(result["can_execute"])
		self.assertTrue(result["can_execute_with_inventory_conversion"])
		self.assertTrue(result["strategies"]["replacement"]["available"])
		self.assertEqual({row["code"] for row in result["blockers"]}, {"NON_ZERO_STOCK"})

	def test_inventory_mapping_requires_every_positive_bin_and_explicit_target_qty(self):
		assessment = {
			"inventory": {
				"bins": [
					{
						"warehouse": "Stores - TC",
						"company": "Test Company",
						"actual_qty": 24,
						"valuation_rate": 2,
						"stock_value": 48,
					}
				]
			}
		}
		with (
			patch("myapp.services.wholesale_service.ensure_warehouse_access", return_value="Stores - TC"),
			patch("myapp.services.wholesale_service.validate_transaction_warehouse"),
		):
			result = _normalize_product_uom_inventory_mappings(
				[{"warehouse": "Stores - TC", "source_qty": 24, "target_qty": 576}],
				assessment=assessment,
			)
		self.assertEqual(result[0]["target_qty"], 576)
		self.assertEqual(result[0]["source_valuation_rate"], 2)
		self.assertEqual(result[0]["source_stock_value"], 48)

		with (
			patch("myapp.services.wholesale_service.frappe.throw", side_effect=frappe.ValidationError),
			self.assertRaises(frappe.ValidationError),
		):
			_normalize_product_uom_inventory_mappings([], assessment=assessment)

		for invalid_target_qty in (None, 0, -1, "NaN", "Infinity"):
			with (
				patch("myapp.services.wholesale_service.ensure_warehouse_access", return_value="Stores - TC"),
				patch("myapp.services.wholesale_service.validate_transaction_warehouse"),
				patch("myapp.services.wholesale_service.frappe.throw", side_effect=frappe.ValidationError),
				self.assertRaises(frappe.ValidationError),
			):
				_normalize_product_uom_inventory_mappings(
					[{"warehouse": "Stores - TC", "source_qty": 24, "target_qty": invalid_target_qty}],
					assessment=assessment,
				)

	def test_repack_entry_consumes_source_and_receives_target_in_same_warehouse(self):
		stock_entry = MagicMock()
		stock_entry.name = "MAT-STE-0001"
		with patch("myapp.services.wholesale_service.frappe.new_doc", return_value=stock_entry):
			result = _create_product_uom_repack_entries(
				source_item=frappe._dict(name="ITEM-OLD"),
				target_item=frappe._dict(name="ITEM-NEW"),
				inventory_mappings=[
					{
						"company": "Test Company",
						"warehouse": "Stores - TC",
						"source_qty": 24,
						"target_qty": 576,
						"source_valuation_rate": 2,
						"source_stock_value": 48,
					}
				],
				reason="纠正错误单位",
			)

		self.assertEqual(stock_entry.stock_entry_type, "Repack")
		self.assertEqual(stock_entry.purpose, "Repack")
		self.assertEqual(
			stock_entry.append.call_args_list,
			[
				call(
					"items",
					{
						"item_code": "ITEM-OLD",
						"qty": 24,
						"s_warehouse": "Stores - TC",
						"allow_zero_valuation_rate": 1,
					},
				),
				call(
					"items",
					{
						"item_code": "ITEM-NEW",
						"qty": 576,
						"t_warehouse": "Stores - TC",
						"is_finished_item": 1,
					},
				),
			],
		)
		stock_entry.insert.assert_called_once()
		stock_entry.submit.assert_called_once()
		self.assertEqual(result[0]["name"], "MAT-STE-0001")
		self.assertFalse(result[0]["allowed_zero_target_valuation"])

	def test_repack_entry_allows_zero_valuation_only_when_source_stock_value_is_zero(self):
		stock_entry = MagicMock()
		stock_entry.name = "MAT-STE-0002"
		with patch("myapp.services.wholesale_service.frappe.new_doc", return_value=stock_entry):
			result = _create_product_uom_repack_entries(
				source_item=frappe._dict(name="ITEM-OLD"),
				target_item=frappe._dict(name="ITEM-NEW"),
				inventory_mappings=[
					{
						"company": "Test Company",
						"warehouse": "Stores - TC",
						"source_qty": 24,
						"target_qty": 576,
						"source_valuation_rate": 0,
						"source_stock_value": 0,
					}
				],
				reason="纠正零价值库存单位",
			)

		self.assertEqual(
			stock_entry.append.call_args_list[1],
			call(
				"items",
				{
					"item_code": "ITEM-NEW",
					"qty": 576,
					"t_warehouse": "Stores - TC",
					"is_finished_item": 1,
					"allow_zero_valuation_rate": 1,
				},
			),
		)
		self.assertTrue(result[0]["allowed_zero_target_valuation"])

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

	def test_manual_and_new_prices_require_explicit_nonnegative_rates(self):
		manual = _normalize_product_uom_migration_mappings(
			[
				{
					"source_name": "PRICE-1",
					"action": "manual",
					"target_uom": "Bottle",
					"target_rate": "25.50",
				}
			],
			source_rows=[{"name": "PRICE-1"}],
			mapping_kind="price",
		)
		self.assertEqual(manual["PRICE-1"]["target_rate"], 25.5)
		self.assertEqual(
			_normalize_product_uom_migration_new_prices(
				[
					{
						"price_list": "Retail",
						"currency": "CNY",
						"rate": 9.9,
						"target_uom": "Bottle",
					}
				]
			)[0]["rate"],
			9.9,
		)
		for invalid_rate in (None, "", -1, "NaN", "Infinity"):
			with (
				patch(
					"myapp.services.wholesale_service.frappe.throw",
					side_effect=frappe.ValidationError,
				),
				self.assertRaises(frappe.ValidationError),
			):
				_normalize_product_uom_migration_new_prices(
					[
						{
							"price_list": "Retail",
							"currency": "CNY",
							"rate": invalid_rate,
							"target_uom": "Bottle",
						}
					]
				)

	def test_price_plan_rejects_duplicate_price_list_currency_and_uom(self):
		fake_db = MagicMock()
		fake_db.exists.return_value = True
		with (
			patch.object(wholesale_service.frappe, "db", fake_db),
			patch(
				"myapp.services.wholesale_service.frappe.throw",
				side_effect=frappe.ValidationError,
			),
			self.assertRaises(frappe.ValidationError),
		):
			_build_product_uom_migration_price_plan(
				source_prices=[
					{
						"name": "PRICE-1",
						"price_list": "Retail",
						"currency": "CNY",
						"rate": 10,
					}
				],
				price_mappings={
					"PRICE-1": {
						"action": "copy",
						"target_rate": None,
						"target_uom": "Bottle",
					}
				},
				new_prices=[
					{
						"price_list": "Retail",
						"currency": "CNY",
						"rate": 12,
						"target_uom": "Bottle",
					}
				],
			)

	@patch("myapp.services.wholesale_service.record_product_correction", return_value="CORR-1")
	@patch("myapp.services.wholesale_service.nowdate", return_value="2026-09-01")
	@patch(
		"myapp.services.wholesale_service._build_product_detail_payload",
		return_value={"item_code": "ITEM-OLD", "stock_uom": "Nos"},
	)
	@patch("myapp.services.wholesale_service._upsert_item_price")
	@patch("myapp.services.wholesale_service._apply_item_uom_updates")
	@patch(
		"myapp.services.wholesale_service._get_item_mode_default_uom_field",
		side_effect=lambda mode: f"custom_{mode}_uom",
	)
	@patch("myapp.services.wholesale_service.require_document_permission")
	@patch("myapp.services.wholesale_service.require_doctype_permission")
	def test_in_place_correction_updates_item_barcode_prices_and_audit(
		self,
		mock_require_doctype,
		mock_require_document,
		_mock_mode_field,
		mock_apply_uoms,
		mock_upsert_price,
		_mock_build_detail,
		_mock_nowdate,
		mock_record_correction,
	):
		barcode = MagicMock(name="barcode")
		barcode.name = "BAR-ROW-1"
		barcode.uom = "Wrong UOM"
		source = MagicMock(name="source")
		source.name = "ITEM-OLD"
		source.modified = "2026-08-31 12:00:00"
		source.disabled = 0
		source.barcodes = [barcode]
		updated_price = MagicMock(name="updated_price")
		updated_price.name = "PRICE-1"
		expired_price = MagicMock(name="expired_price")
		expired_price.name = "PRICE-2"
		mock_require_document.side_effect = lambda _doctype, name, _ptype: {
			"PRICE-1": updated_price,
			"PRICE-2": expired_price,
		}[name]
		mock_upsert_price.return_value = frappe._dict(name="PRICE-NEW")

		result = _execute_in_place_product_uom_correction(
			source=source,
			assessment={
				"strategies": {"in_place": {"available": True}},
				"prices": [
					{"name": "PRICE-1", "price_list": "Retail"},
					{"name": "PRICE-2", "price_list": "Wholesale"},
				],
				"barcodes": [
					{"name": "BAR-ROW-1", "barcode": "690000000001", "uom": "Wrong UOM"},
				],
			},
			resolved_stock_uom="Nos",
			conversion_map={"Nos": 1.0, "Box": 24.0},
			wholesale_default_uom="Box",
			retail_default_uom="Nos",
			price_mappings={
				"PRICE-1": {"action": "manual", "target_uom": "Nos", "target_rate": 3},
				"PRICE-2": {"action": "skip", "target_uom": None, "target_rate": None},
			},
			planned_prices=[
				{
					"source_name": "PRICE-1",
					"price_list": "Retail",
					"currency": "CNY",
					"rate": 3,
					"target_uom": "Nos",
				},
				{
					"source_name": None,
					"price_list": "Wholesale",
					"currency": "CNY",
					"rate": 70,
					"target_uom": "Box",
				},
			],
			barcode_mappings={
				"BAR-ROW-1": {"action": "move", "target_uom": "Nos"},
			},
			request_id="REQ-1",
			reason="纠正建档单位",
			before_snapshot={"stock_uom": "Wrong UOM"},
		)

		self.assertEqual(source.stock_uom, "Nos")
		self.assertEqual(source.custom_wholesale_uom, "Box")
		self.assertEqual(source.custom_retail_uom, "Nos")
		self.assertEqual(barcode.uom, "Nos")
		mock_apply_uoms.assert_called_once()
		source.save.assert_called_once()
		self.assertEqual(updated_price.price_list_rate, 3)
		self.assertEqual(updated_price.uom, "Nos")
		self.assertEqual(updated_price.currency, "CNY")
		updated_price.save.assert_called_once()
		self.assertIsNotNone(expired_price.valid_upto)
		expired_price.save.assert_called_once()
		mock_upsert_price.assert_called_once_with(
			item_code="ITEM-OLD",
			rate=70,
			price_list="Wholesale",
			currency="CNY",
			uom="Box",
		)
		mock_require_doctype.assert_called_once_with("Item Price", "write")
		mock_record_correction.assert_called_once()
		self.assertEqual(result["data"]["strategy"], "in_place")
		self.assertFalse(result["data"]["source_disabled"])
		self.assertEqual(result["data"]["correction_name"], "CORR-1")

	@patch("myapp.services.wholesale_service.record_product_correction", return_value="CORR-2")
	@patch(
		"myapp.services.wholesale_service._build_product_detail_payload",
		return_value={"item_code": "ITEM-OLD", "stock_uom": "Nos"},
	)
	@patch("myapp.services.wholesale_service._apply_item_uom_updates")
	@patch("myapp.services.wholesale_service._get_item_mode_default_uom_field", return_value=None)
	@patch("myapp.services.wholesale_service.require_doctype_permission")
	def test_in_place_correction_without_prices_does_not_require_price_write_permission(
		self,
		mock_require_doctype,
		_mock_mode_field,
		_mock_apply_uoms,
		_mock_build_detail,
		_mock_record_correction,
	):
		source = MagicMock()
		source.name = "ITEM-OLD"
		source.modified = "2026-08-31 12:00:00"
		source.disabled = 0
		source.barcodes = []

		_execute_in_place_product_uom_correction(
			source=source,
			assessment={
				"strategies": {"in_place": {"available": True}},
				"prices": [],
				"barcodes": [],
			},
			resolved_stock_uom="Nos",
			conversion_map={"Nos": 1.0},
			wholesale_default_uom=None,
			retail_default_uom=None,
			price_mappings={},
			planned_prices=[],
			barcode_mappings={},
			request_id="REQ-2",
			reason="纠正建档单位",
			before_snapshot={"stock_uom": "Wrong UOM"},
		)

		mock_require_doctype.assert_not_called()

	@patch("myapp.services.wholesale_service.record_product_correction", return_value="CORR-REPLACEMENT")
	@patch("myapp.services.wholesale_service._build_item_code", return_value="ITEM-NEW")
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
		mock_build_item_code,
		mock_record_correction,
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
			"blockers": [{"code": "NON_ZERO_STOCK", "message": "仍有库存"}],
			"can_execute_with_inventory_conversion": True,
			"inventory": {
				"bins": [
					{
						"warehouse": "Stores - TC",
						"company": "Test Company",
						"actual_qty": 24,
					}
				]
			},
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
		mock_upsert_price.side_effect = [
			frappe._dict(name="PRICE-COPIED"),
			frappe._dict(name="PRICE-CREATED"),
		]

		def new_doc(doctype):
			return {"Item": new_item, "Item Alternative": alternative}[doctype]

		fake_db = MagicMock()
		fake_db.exists.side_effect = lambda doctype, _name: doctype == "Price List"
		with (
			patch.object(wholesale_service.frappe, "db", fake_db),
			patch("myapp.services.wholesale_service.frappe.new_doc", side_effect=new_doc),
			patch(
				"myapp.services.wholesale_service._normalize_product_uom_inventory_mappings",
				return_value=[
					{
						"warehouse": "Stores - TC",
						"company": "Test Company",
						"source_qty": 24,
						"target_qty": 576,
					}
				],
			),
			patch(
				"myapp.services.wholesale_service._create_product_uom_repack_entries",
				return_value=[{"name": "MAT-STE-0001"}],
			) as mock_repack,
			patch(
				"myapp.services.wholesale_service._get_product_uom_migration_bins",
				return_value=[{"warehouse": "Stores - TC", "actual_qty": 0}],
			),
		):
			result = execute_product_uom_migration_v1(
				"ITEM-OLD",
				source_modified="2026-08-31 12:00:00",
				new_item_name="测试商品（新）",
				stock_uom="Nos",
				uom_conversions=[
					{"uom": "Nos", "conversion_factor": 1},
					{"uom": "Box", "conversion_factor": 24},
				],
				price_mappings=[
					{"source_name": "PRICE-1", "action": "copy", "target_uom": "Box"},
				],
				new_prices=[
					{
						"price_list": "Retail",
						"currency": "CNY",
						"rate": 9.9,
						"target_uom": "Nos",
					},
				],
				barcode_mappings=[
					{"source_name": "BAR-ROW-1", "action": "move", "target_uom": "Nos"},
				],
				confirm_disable_source=1,
				confirm_history_preserved=1,
				confirm_inventory_conversion=1,
				inventory_mappings=[
					{"warehouse": "Stores - TC", "source_qty": 24, "target_qty": 576},
				],
				request_id="migration-001",
			)

		self.assertTrue(source.disabled)
		mock_build_item_code.assert_called_once_with("测试商品（新）", None)
		self.assertEqual(source.allow_alternative_item, 1)
		source.remove.assert_called_once_with(barcode_child)
		self.assertEqual(source.save.call_count, 2)
		mock_apply_uoms.assert_called_once()
		new_item.append.assert_called_once_with(
			"barcodes",
			{"barcode": "690000000001", "uom": "Nos"},
		)
		new_item.insert.assert_called_once()
		mock_repack.assert_called_once()
		self.assertEqual(result["data"]["repack_entries"], [{"name": "MAT-STE-0001"}])
		self.assertEqual(
			mock_upsert_price.call_args_list,
			[
				call(
					item_code="ITEM-NEW",
					rate=99,
					price_list="Wholesale",
					currency="CNY",
					uom="Box",
				),
				call(
					item_code="ITEM-NEW",
					rate=9.9,
					price_list="Retail",
					currency="CNY",
					uom="Nos",
				),
			],
		)
		alternative.insert.assert_called_once()
		self.assertEqual(result["data"]["new_item"]["item_code"], "ITEM-NEW")
		self.assertEqual(result["data"]["correction_name"], "CORR-REPLACEMENT")
		mock_record_correction.assert_called_once()
		self.assertEqual(
			mock_require_doctype.call_args_list,
			[
				call("Item", "create"),
				call("Item Alternative", "create"),
				call("Stock Entry", "create"),
				call("Item Price", "create"),
			],
		)
