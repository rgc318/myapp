from unittest import TestCase
from unittest.mock import MagicMock, call, patch

import frappe

from myapp.services.wholesale_service import (
	_apply_item_uom_updates,
	_validate_mode_default_uoms_against_stock_uom,
	create_product_v2,
	create_product_and_stock,
	disable_product_v2,
	get_product_detail_v2,
	list_products_v2,
	search_product,
	search_product_v2,
	update_product_v2,
)


class TestWholesaleService(TestCase):
	@patch("myapp.services.wholesale_service._resolve_default_uom")
	@patch("myapp.services.wholesale_service.frappe.throw", side_effect=frappe.ValidationError)
	def test_validate_mode_default_uoms_requires_conversion_mapping(self, _mock_throw, mock_resolve_default_uom):
		mock_resolve_default_uom.side_effect = lambda value=None: (value or "Nos").strip()
		item = frappe._dict(
			{
				"stock_uom": "Nos",
				"custom_wholesale_default_uom": "Box",
				"custom_retail_default_uom": "Nos",
				"uoms": [{"uom": "Nos", "conversion_factor": 1}],
			}
		)

		with self.assertRaises(frappe.ValidationError):
			_validate_mode_default_uoms_against_stock_uom(item=item)

	@patch("myapp.services.wholesale_service._resolve_default_uom")
	def test_apply_item_uom_updates_rebuilds_conversion_rows(self, mock_resolve_default_uom):
		mock_resolve_default_uom.side_effect = lambda value=None: (value or "Nos").strip()
		item = MagicMock()
		item.stock_uom = "Nos"

		_apply_item_uom_updates(
			item=item,
			stock_uom="Nos",
			uom_conversions=[
				{"uom": "Box", "conversion_factor": 12},
				{"uom": "Nos", "conversion_factor": 1},
			],
		)

		item.set.assert_called_once_with("uoms", [])
		self.assertEqual(item.append.call_args_list, [
			call("uoms", {"uom": "Nos", "conversion_factor": 1}),
			call("uoms", {"uom": "Box", "conversion_factor": 12.0}),
		])

	@patch("myapp.services.wholesale_service._get_warehouse_stock_detail_map")
	@patch("myapp.services.wholesale_service._get_multi_price_map")
	@patch("myapp.services.wholesale_service._get_price_map")
	@patch("myapp.services.wholesale_service._get_qty_map")
	@patch("myapp.services.wholesale_service._get_item_rows")
	def test_list_products_v2_returns_price_summary(
		self,
		mock_get_item_rows,
		mock_get_qty_map,
		mock_get_price_map,
		mock_get_multi_price_map,
		mock_get_warehouse_stock_detail_map,
	):
		mock_get_item_rows.return_value = [
			frappe._dict(
				{
					"name": "ITEM-001",
					"item_name": "商品一",
					"item_group": "饮料",
					"stock_uom": "Nos",
					"image": "/files/a.png",
					"description": "标准描述",
					"custom_nickname": "冰可乐",
					"custom_wholesale_default_uom": "Box",
					"custom_retail_default_uom": "Bottle",
					"disabled": 0,
					"is_sales_item": 1,
					"is_purchase_item": 1,
					"valuation_rate": 7.5,
					"standard_rate": 15,
					"creation": "2026-03-20 09:00:00",
					"modified": "2026-03-20 10:00:00",
				}
			)
		]
		mock_get_qty_map.side_effect = [
			{"ITEM-001": 9},
			{"ITEM-001": 42},
			{"ITEM-001": 42},
		]
		mock_get_warehouse_stock_detail_map.return_value = {
			"ITEM-001": [
				{"warehouse": "Stores - RD", "company": "Test Company", "qty": 9},
				{"warehouse": "Stores - TC", "company": "Test Company", "qty": 33},
			]
		}
		mock_get_price_map.return_value = {"ITEM-001": 15}
		mock_get_multi_price_map.side_effect = [
			{
				"ITEM-001": {
					"Standard Selling": {"price_list": "Standard Selling", "rate": 15, "currency": "CNY"},
					"Wholesale": {"price_list": "Wholesale", "rate": 12, "currency": "CNY"},
					"Retail": {"price_list": "Retail", "rate": 18, "currency": "CNY"},
				}
			},
			{
				"ITEM-001": {
					"Standard Buying": {"price_list": "Standard Buying", "rate": 6.2, "currency": "CNY"}
				}
			},
		]

		result = list_products_v2(search_key="可乐", date_from="2026-03-01", date_to="2026-03-31")

		self.assertEqual(len(result["data"]), 1)
		self.assertEqual(result["data"][0]["item_code"], "ITEM-001")
		self.assertEqual(result["data"][0]["price_summary"]["wholesale_rate"], 12)
		self.assertEqual(result["data"][0]["price_summary"]["standard_buying_rate"], 6.2)
		self.assertEqual(result["data"][0]["wholesale_default_uom"], "Box")
		self.assertEqual(result["data"][0]["retail_default_uom"], "Bottle")
		self.assertEqual(result["data"][0]["valuation_rate"], 7.5)
		self.assertEqual(result["data"][0]["total_qty"], 42)
		self.assertEqual(len(result["data"][0]["warehouse_stock_details"]), 2)
		self.assertEqual(mock_get_item_rows.call_args.kwargs["date_from"], "2026-03-01")
		self.assertEqual(mock_get_item_rows.call_args.kwargs["date_to"], "2026-03-31")
		self.assertEqual(result["filters"]["date_from"], "2026-03-01")
		self.assertEqual(result["filters"]["date_to"], "2026-03-31")

	@patch("myapp.services.wholesale_service._get_warehouse_stock_detail_map")
	@patch("myapp.services.wholesale_service._get_primary_barcode")
	@patch("myapp.services.wholesale_service._get_uom_map")
	@patch("myapp.services.wholesale_service._get_multi_price_map")
	@patch("myapp.services.wholesale_service._get_price_map")
	@patch("myapp.services.wholesale_service._get_item_specification_field")
	@patch("myapp.services.wholesale_service._get_qty_map")
	@patch("myapp.services.wholesale_service._get_item_nickname_field")
	@patch("myapp.services.wholesale_service.frappe.get_doc")
	def test_get_product_detail_v2_returns_product_snapshot(
		self,
		mock_get_doc,
		mock_get_item_nickname_field,
		mock_get_qty_map,
		mock_get_item_specification_field,
		mock_get_price_map,
		mock_get_multi_price_map,
		mock_get_uom_map,
		mock_get_primary_barcode,
		mock_get_warehouse_stock_detail_map,
	):
		mock_get_item_nickname_field.return_value = "custom_nickname"
		mock_get_item_specification_field.return_value = "custom_specification"
		mock_get_doc.return_value = frappe._dict(
			{
				"name": "ITEM-001",
				"item_name": "商品一",
				"item_group": "饮料",
				"stock_uom": "Nos",
				"image": "/files/a.png",
				"custom_nickname": "冰可乐",
				"custom_specification": "500ml",
				"custom_wholesale_default_uom": "Box",
				"custom_retail_default_uom": "Bottle",
				"description": "标准描述",
				"disabled": 0,
				"is_sales_item": 1,
				"creation": "2026-03-18 10:00:00",
				"modified": "2026-03-18 11:00:00",
			}
		)
		mock_get_qty_map.side_effect = [
			{"ITEM-001": 8},
			{"ITEM-001": 21},
			{"ITEM-001": 21},
		]
		mock_get_warehouse_stock_detail_map.return_value = {
			"ITEM-001": [
				{"warehouse": "Stores - RD", "company": "Test Company", "qty": 8},
				{"warehouse": "Stores - TC", "company": "Test Company", "qty": 13},
			]
		}
		mock_get_price_map.return_value = {"ITEM-001": 15}
		mock_get_multi_price_map.side_effect = [
			{"ITEM-001": {"Wholesale": {"price_list": "Wholesale", "rate": 13, "currency": "CNY"}}},
			{"ITEM-001": {"Standard Buying": {"price_list": "Standard Buying", "rate": 8, "currency": "CNY"}}},
		]
		mock_get_uom_map.return_value = {"ITEM-001": [{"uom": "Box", "conversion_factor": 12}]}
		mock_get_primary_barcode.return_value = "BAR-001"

		result = get_product_detail_v2("ITEM-001", warehouse="Stores - RD", company="Test Company")

		self.assertEqual(result["data"]["item_code"], "ITEM-001")
		self.assertEqual(result["data"]["nickname"], "冰可乐")
		self.assertEqual(result["data"]["specification"], "500ml")
		self.assertEqual(result["data"]["image"], "/files/a.png")
		self.assertEqual(result["data"]["price"], 15)
		self.assertEqual(result["data"]["qty"], 8)
		self.assertEqual(result["data"]["barcode"], "BAR-001")
		self.assertEqual(result["data"]["price_summary"]["wholesale_rate"], 13)
		self.assertEqual(result["data"]["price_summary"]["standard_buying_rate"], 8)
		self.assertEqual(result["data"]["wholesale_default_uom"], "Box")
		self.assertEqual(result["data"]["retail_default_uom"], "Bottle")
		self.assertEqual(result["data"]["total_qty"], 21)
		self.assertEqual(len(result["data"]["warehouse_stock_details"]), 2)

	@patch("myapp.services.wholesale_service._get_warehouse_stock_detail_map")
	@patch("myapp.services.wholesale_service._get_qty_map")
	@patch("myapp.services.wholesale_service._get_multi_price_map")
	@patch("myapp.services.wholesale_service._get_uom_map")
	@patch("myapp.services.wholesale_service._get_price_map")
	@patch("myapp.services.wholesale_service._get_item_data_map")
	@patch("myapp.services.wholesale_service._search_item_codes")
	@patch("myapp.services.wholesale_service._get_item_specification_field")
	@patch("myapp.services.wholesale_service._get_item_nickname_field")
	def test_search_product_v2_filters_in_stock_and_sorts_by_price_desc(
		self,
		mock_get_item_nickname_field,
		mock_get_item_specification_field,
		mock_search_item_codes,
		mock_get_item_data_map,
		mock_get_price_map,
		mock_get_uom_map,
		mock_get_multi_price_map,
		mock_get_qty_map,
		mock_get_warehouse_stock_detail_map,
	):
		mock_get_item_nickname_field.return_value = "custom_nickname"
		mock_get_item_specification_field.return_value = "custom_specification"
		mock_search_item_codes.return_value = ["ITEM-001", "ITEM-002"]
		mock_get_item_data_map.return_value = {
			"ITEM-001": frappe._dict(
				{
					"name": "ITEM-001",
					"item_name": "商品一",
					"stock_uom": "Nos",
					"image": None,
					"custom_nickname": "昵称一",
					"custom_specification": "500ml",
					"custom_wholesale_default_uom": "Box",
					"custom_retail_default_uom": "Bottle",
					"description": "别名一",
					"creation": "2026-03-16 10:00:00",
					"modified": "2026-03-17 10:00:00",
				}
			),
			"ITEM-002": frappe._dict(
				{
					"name": "ITEM-002",
					"item_name": "商品二",
					"stock_uom": "Nos",
					"image": None,
					"custom_nickname": "昵称二",
					"custom_specification": "1000ml",
					"custom_wholesale_default_uom": "Case",
					"custom_retail_default_uom": "Pair",
					"description": "别名二",
					"creation": "2026-03-15 10:00:00",
					"modified": "2026-03-17 09:00:00",
				}
			),
		}
		mock_get_price_map.return_value = {"ITEM-001": 10, "ITEM-002": 25}
		mock_get_uom_map.return_value = {"ITEM-001": [], "ITEM-002": []}
		mock_get_multi_price_map.side_effect = [
			{
				"ITEM-001": {"Wholesale": {"price_list": "Wholesale", "rate": 9, "currency": "CNY"}},
				"ITEM-002": {"Wholesale": {"price_list": "Wholesale", "rate": 22, "currency": "CNY"}},
			},
			{
				"ITEM-001": {"Standard Buying": {"price_list": "Standard Buying", "rate": 6, "currency": "CNY"}},
				"ITEM-002": {"Standard Buying": {"price_list": "Standard Buying", "rate": 18, "currency": "CNY"}},
			},
		]
		mock_get_qty_map.side_effect = [
			{"ITEM-001": 0, "ITEM-002": 8},
			{"ITEM-001": 5, "ITEM-002": 12},
			{"ITEM-001": 5, "ITEM-002": 12},
		]
		mock_get_warehouse_stock_detail_map.return_value = {
			"ITEM-002": [
				{"warehouse": "Stores - TC", "company": "Test Company", "qty": 8},
				{"warehouse": "Stores - RD", "company": "Test Company", "qty": 4},
			]
		}

		result = search_product_v2(
			search_key="商品",
			search_fields=["item_name", "nickname"],
			in_stock_only=1,
			sort_by="price",
			sort_order="desc",
		)

		self.assertEqual(len(result["data"]), 1)
		self.assertEqual(result["data"][0]["item_code"], "ITEM-002")
		self.assertEqual(result["data"][0]["nickname"], "昵称二")
		self.assertEqual(result["data"][0]["specification"], "1000ml")
		self.assertEqual(result["data"][0]["retail_default_uom"], "Pair")
		self.assertEqual(result["data"][0]["price_summary"]["wholesale_rate"], 22)
		self.assertEqual(result["data"][0]["total_qty"], 12)
		self.assertEqual(len(result["data"][0]["warehouse_stock_details"]), 2)
		self.assertEqual(result["filters"]["sort_by"], "price")
		self.assertTrue(result["filters"]["in_stock_only"])

	@patch("myapp.services.wholesale_service._get_multi_price_map")
	@patch("myapp.services.wholesale_service._get_qty_map")
	@patch("myapp.services.wholesale_service._get_uom_map")
	@patch("myapp.services.wholesale_service._get_price_map")
	@patch("myapp.services.wholesale_service._get_item_data_map")
	@patch("myapp.services.wholesale_service._search_item_codes")
	def test_search_product_calls_price_summary_maps_once(self, mock_search_item_codes, mock_get_item_data_map, mock_get_price_map, mock_get_uom_map, mock_get_qty_map, mock_get_multi_price_map):
		mock_search_item_codes.return_value = ["ITEM-001"]
		mock_get_item_data_map.return_value = {
			"ITEM-001": frappe._dict(
				{
					"name": "ITEM-001",
					"item_name": "商品一",
					"stock_uom": "Nos",
					"image": None,
				}
			)
		}
		mock_get_price_map.return_value = {"ITEM-001": 10}
		mock_get_uom_map.return_value = {"ITEM-001": []}
		mock_get_qty_map.return_value = {"ITEM-001": 5}
		mock_get_multi_price_map.side_effect = [
			{"ITEM-001": {"Wholesale": {"price_list": "Wholesale", "rate": 9, "currency": "CNY"}}},
			{"ITEM-001": {"Standard Buying": {"price_list": "Standard Buying", "rate": 6, "currency": "CNY"}}},
		]

		result = search_product("商品", company="Test Company")

		self.assertEqual(len(result["data"]), 1)
		self.assertEqual(mock_get_multi_price_map.call_count, 2)

	@patch(
		"myapp.services.wholesale_service.frappe.throw",
		side_effect=frappe.ValidationError("请先选择仓库，或在当前用户默认值中配置 warehouse。"),
	)
	@patch(
		"myapp.services.wholesale_service._resolve_default_warehouse",
		side_effect=frappe.ValidationError("请先选择仓库，或在当前用户默认值中配置 warehouse。"),
	)
	def test_create_product_and_stock_requires_warehouse_when_no_default(
		self, mock_resolve_default_warehouse, _mock_throw
	):
		with self.assertRaises(frappe.ValidationError):
			create_product_and_stock(item_name="测试商品")
		mock_resolve_default_warehouse.assert_called_once()

	@patch("myapp.services.wholesale_service.run_idempotent")
	def test_create_product_and_stock_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {
			"status": "success",
			"data": {"item_code": "TEST-ITEM"},
		}

		result = create_product_and_stock(
			item_name="测试商品",
			warehouse="Stores - RD",
			request_id="create-product-001",
		)

		self.assertEqual(result["data"]["item_code"], "TEST-ITEM")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.wholesale_service._create_stock_entry")
	@patch("myapp.services.wholesale_service._get_item_nickname_field")
	@patch("myapp.services.wholesale_service._upsert_item_price")
	@patch("myapp.services.wholesale_service.resolve_item_quantity_to_stock")
	@patch("myapp.services.wholesale_service.frappe.new_doc")
	@patch("myapp.services.wholesale_service._build_item_code")
	@patch("myapp.services.wholesale_service._resolve_default_item_group")
	@patch("myapp.services.wholesale_service._resolve_default_uom")
	@patch("myapp.services.wholesale_service._resolve_company_from_warehouse")
	@patch("myapp.services.wholesale_service.frappe.defaults.get_user_default")
	def test_create_product_and_stock_builds_item_and_receipt(
		self,
		mock_get_user_default,
		mock_resolve_company_from_warehouse,
		mock_resolve_default_uom,
		mock_resolve_default_item_group,
		mock_build_item_code,
		mock_new_doc,
		mock_resolve_qty,
		mock_upsert_item_price,
		mock_get_item_nickname_field,
		mock_create_stock_entry,
	):
		mock_get_user_default.return_value = "CNY"
		mock_resolve_company_from_warehouse.return_value = "Test Company"
		mock_resolve_default_uom.return_value = "Nos"
		mock_resolve_default_item_group.return_value = "All Item Groups"
		mock_build_item_code.return_value = "TEST-COLA"
		mock_resolve_qty.return_value = {"qty": 8, "uom": "Nos", "stock_qty": 8}
		mock_get_item_nickname_field.return_value = "custom_nickname"

		item = MagicMock()
		item.item_code = "TEST-COLA"
		item.item_name = "测试可乐"
		item.stock_uom = "Nos"
		item.image = "/files/cola.png"
		mock_new_doc.return_value = item

		stock_entry = MagicMock()
		stock_entry.name = "MAT-STE-0001"
		mock_create_stock_entry.return_value = stock_entry

		from myapp.services import wholesale_service

		fake_db = MagicMock()
		fake_db.exists.return_value = False

		with patch.object(wholesale_service.frappe, "db", fake_db):
			result = create_product_and_stock(
				item_name="测试可乐",
				warehouse="Stores - RD",
				opening_qty=8,
				standard_rate=5.5,
				image="/files/cola.png",
				barcode="BAR-001X",
				nickname="冰可乐",
			)

		mock_new_doc.assert_called_once_with("Item")
		self.assertEqual(item.custom_nickname, "冰可乐")
		item.insert.assert_called_once()
		item.append.assert_called_once_with("barcodes", {"barcode": "BAR-001X"})
		mock_upsert_item_price.assert_called_once()
		mock_create_stock_entry.assert_called_once()
		self.assertEqual(result["data"]["item_code"], "TEST-COLA")
		self.assertEqual(result["data"]["warehouse"], "Stores - RD")
		self.assertEqual(result["data"]["qty"], 8)
		self.assertEqual(result["data"]["nickname"], "冰可乐")

	@patch("myapp.services.wholesale_service.run_idempotent")
	def test_update_product_v2_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {
			"status": "success",
			"data": {"item_code": "ITEM-001"},
		}

		result = update_product_v2(item_code="ITEM-001", nickname="新昵称", request_id="update-product-001")

		self.assertEqual(result["data"]["item_code"], "ITEM-001")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.wholesale_service.run_idempotent")
	def test_create_product_v2_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {
			"status": "success",
			"data": {"item_code": "ITEM-NEW"},
		}

		result = create_product_v2(item_name="新商品", request_id="create-product-v2-001")

		self.assertEqual(result["data"]["item_code"], "ITEM-NEW")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.wholesale_service._build_product_detail_payload")
	@patch("myapp.services.wholesale_service._create_stock_adjustment_entry")
	@patch("myapp.services.wholesale_service._resolve_company_from_warehouse")
	@patch("myapp.services.wholesale_service._resolve_default_warehouse")
	@patch("myapp.services.wholesale_service.resolve_item_quantity_to_stock")
	@patch("myapp.services.wholesale_service._apply_item_price_updates")
	@patch("myapp.services.wholesale_service._build_item_code")
	@patch("myapp.services.wholesale_service._resolve_default_item_group")
	@patch(
		"myapp.services.wholesale_service._get_item_mode_default_uom_field",
		side_effect=lambda mode: {
			"wholesale": "custom_wholesale_default_uom",
			"retail": "custom_retail_default_uom",
		}.get(mode),
	)
	@patch("myapp.services.wholesale_service._normalize_mode_default_uom")
	@patch("myapp.services.wholesale_service._validate_mode_default_uoms_against_stock_uom")
	@patch("myapp.services.wholesale_service._resolve_default_uom")
	@patch("myapp.services.wholesale_service._get_item_specification_field")
	@patch("myapp.services.wholesale_service._get_item_nickname_field")
	@patch("myapp.services.wholesale_service.frappe.new_doc")
	def test_create_product_v2_creates_item_without_stock_entry(
		self,
		mock_new_doc,
		mock_get_item_nickname_field,
		mock_get_item_specification_field,
		mock_resolve_default_uom,
		mock_validate_mode_default_uoms_against_stock_uom,
		mock_normalize_mode_default_uom,
		mock_get_item_mode_default_uom_field,
		mock_resolve_default_item_group,
		mock_build_item_code,
		mock_apply_item_price_updates,
		mock_resolve_item_quantity_to_stock,
		mock_resolve_default_warehouse,
		mock_resolve_company_from_warehouse,
		mock_create_stock_adjustment_entry,
		mock_build_product_detail_payload,
	):
		mock_get_item_nickname_field.return_value = "custom_nickname"
		mock_get_item_specification_field.return_value = "custom_specification"
		mock_resolve_default_uom.return_value = "Nos"
		mock_resolve_item_quantity_to_stock.return_value = {"qty": 0, "uom": "Nos", "stock_qty": 0}
		mock_resolve_default_warehouse.return_value = "Stores - RD"
		mock_resolve_company_from_warehouse.return_value = "rgc (Demo)"
		mock_normalize_mode_default_uom.side_effect = ["Box", "Bottle"]
		mock_resolve_default_item_group.return_value = "All Item Groups"
		mock_build_item_code.return_value = "ITEM-NEW"
		item = MagicMock()
		item.item_code = "ITEM-NEW"
		item.item_name = "新商品"
		mock_new_doc.return_value = item
		mock_build_product_detail_payload.return_value = {"item_code": "ITEM-NEW", "nickname": "新品"}

		result = create_product_v2(
			item_name="新商品",
			nickname="新品",
			specification="500ml",
			wholesale_default_uom="Box",
			retail_default_uom="Bottle",
			standard_rate=19,
			selling_prices=[{"price_list": "Wholesale", "rate": 16}],
		)

		mock_new_doc.assert_called_once_with("Item")
		self.assertEqual(item.custom_specification, "500ml")
		self.assertEqual(item.custom_wholesale_default_uom, "Box")
		self.assertEqual(item.custom_retail_default_uom, "Bottle")
		mock_validate_mode_default_uoms_against_stock_uom.assert_called_once()
		item.insert.assert_called_once()
		mock_apply_item_price_updates.assert_called_once()
		mock_create_stock_adjustment_entry.assert_not_called()
		self.assertEqual(result["data"]["item_code"], "ITEM-NEW")

	@patch("myapp.services.wholesale_service._build_product_detail_payload")
	@patch("myapp.services.wholesale_service._create_stock_adjustment_entry")
	@patch("myapp.services.wholesale_service._resolve_company_from_warehouse")
	@patch("myapp.services.wholesale_service._resolve_default_warehouse")
	@patch("myapp.services.wholesale_service.resolve_item_quantity_to_stock")
	@patch("myapp.services.wholesale_service._apply_item_price_updates")
	@patch("myapp.services.wholesale_service._build_item_code")
	@patch("myapp.services.wholesale_service._resolve_default_item_group")
	@patch(
		"myapp.services.wholesale_service._get_item_mode_default_uom_field",
		side_effect=lambda mode: {
			"wholesale": "custom_wholesale_default_uom",
			"retail": "custom_retail_default_uom",
		}.get(mode),
	)
	@patch("myapp.services.wholesale_service._normalize_mode_default_uom")
	@patch("myapp.services.wholesale_service._validate_mode_default_uoms_against_stock_uom")
	@patch("myapp.services.wholesale_service._resolve_default_uom")
	@patch("myapp.services.wholesale_service._get_item_specification_field")
	@patch("myapp.services.wholesale_service._get_item_nickname_field")
	@patch("myapp.services.wholesale_service.frappe.new_doc")
	def test_create_product_v2_can_initialize_stock_atomically(
		self,
		mock_new_doc,
		mock_get_item_nickname_field,
		mock_get_item_specification_field,
		mock_resolve_default_uom,
		mock_validate_mode_default_uoms_against_stock_uom,
		mock_normalize_mode_default_uom,
		mock_get_item_mode_default_uom_field,
		mock_resolve_default_item_group,
		mock_build_item_code,
		mock_apply_item_price_updates,
		mock_resolve_item_quantity_to_stock,
		mock_resolve_default_warehouse,
		mock_resolve_company_from_warehouse,
		mock_create_stock_adjustment_entry,
		mock_build_product_detail_payload,
	):
		mock_get_item_nickname_field.return_value = "custom_nickname"
		mock_get_item_specification_field.return_value = "custom_specification"
		mock_resolve_default_uom.return_value = "Nos"
		mock_normalize_mode_default_uom.side_effect = ["Box", "Bottle"]
		mock_resolve_default_item_group.return_value = "All Item Groups"
		mock_build_item_code.return_value = "ITEM-NEW"
		mock_resolve_item_quantity_to_stock.return_value = {"qty": 12, "uom": "Box", "stock_qty": 24}
		mock_resolve_default_warehouse.return_value = "Stores - RD"
		mock_resolve_company_from_warehouse.return_value = "rgc (Demo)"
		item = MagicMock()
		item.item_code = "ITEM-NEW"
		item.item_name = "新商品"
		item.name = "ITEM-NEW"
		item.valuation_rate = 0
		item.standard_rate = 0
		mock_new_doc.return_value = item
		mock_build_product_detail_payload.return_value = {"item_code": "ITEM-NEW", "warehouse": "Stores - RD"}

		result = create_product_v2(
			item_name="新商品",
			stock_uom="Nos",
			warehouse="Stores - RD",
			warehouse_stock_qty=12,
			warehouse_stock_uom="Box",
			standard_rate=19,
		)

		mock_resolve_default_warehouse.assert_called_once_with("Stores - RD", None)
		mock_resolve_item_quantity_to_stock.assert_called_once_with(
			item_code="ITEM-NEW",
			qty=12,
			uom="Box",
		)
		mock_create_stock_adjustment_entry.assert_called_once_with(
			item_code="ITEM-NEW",
			warehouse="Stores - RD",
			qty_delta=24.0,
			company="rgc (Demo)",
			valuation_rate=19.0,
			posting_date=None,
		)
		mock_build_product_detail_payload.assert_called_once_with(
			item,
			warehouse="Stores - RD",
			company=None,
			price_list="Standard Selling",
			currency=None,
		)
		self.assertEqual(result["data"]["item_code"], "ITEM-NEW")

	@patch("myapp.services.wholesale_service._build_item_code")
	@patch("myapp.services.wholesale_service._resolve_default_item_group")
	@patch(
		"myapp.services.wholesale_service._get_item_mode_default_uom_field",
		side_effect=lambda mode: {
			"wholesale": "custom_wholesale_default_uom",
			"retail": "custom_retail_default_uom",
		}.get(mode),
	)
	@patch("myapp.services.wholesale_service._normalize_mode_default_uom")
	@patch("myapp.services.wholesale_service._resolve_default_uom")
	@patch("myapp.services.wholesale_service._get_item_nickname_field")
	@patch("myapp.services.wholesale_service.frappe.new_doc")
	@patch("myapp.services.wholesale_service.frappe.throw", side_effect=frappe.ValidationError)
	def test_create_product_v2_rejects_mode_default_uom_without_conversion(
		self,
		_mock_throw,
		mock_new_doc,
		mock_get_item_nickname_field,
		mock_resolve_default_uom,
		mock_normalize_mode_default_uom,
		mock_get_item_mode_default_uom_field,
		mock_resolve_default_item_group,
		mock_build_item_code,
	):
		mock_get_item_nickname_field.return_value = "custom_nickname"
		mock_resolve_default_uom.side_effect = lambda value=None: (value or "Nos").strip()
		mock_normalize_mode_default_uom.side_effect = ["Box", "Nos"]
		mock_resolve_default_item_group.return_value = "All Item Groups"
		mock_build_item_code.return_value = "ITEM-NEW"
		item = MagicMock()
		item.item_code = "ITEM-NEW"
		item.item_name = "新商品"
		mock_new_doc.return_value = item

		with self.assertRaises(frappe.ValidationError):
			create_product_v2(
				item_name="新商品",
				wholesale_default_uom="Box",
				retail_default_uom="Nos",
				uom_conversions=[{"uom": "Nos", "conversion_factor": 1}],
				stock_uom="Nos",
			)

	@patch("myapp.services.wholesale_service.run_idempotent")
	def test_disable_product_v2_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {
			"status": "success",
			"data": {"item_code": "ITEM-001", "disabled": True},
		}

		result = disable_product_v2(item_code="ITEM-001", request_id="disable-product-001")

		self.assertEqual(result["data"]["item_code"], "ITEM-001")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.wholesale_service._build_product_detail_payload")
	@patch("myapp.services.wholesale_service._upsert_item_price")
	@patch("myapp.services.wholesale_service._create_stock_adjustment_entry")
	@patch("myapp.services.wholesale_service.resolve_item_quantity_to_stock")
	@patch("myapp.services.wholesale_service._get_qty_map")
	@patch("myapp.services.wholesale_service._resolve_company_from_warehouse")
	@patch("myapp.services.wholesale_service._apply_item_uom_updates")
	@patch("myapp.services.wholesale_service._validate_mode_default_uoms_against_stock_uom")
	@patch("myapp.services.wholesale_service._update_primary_barcode")
	@patch("myapp.services.wholesale_service._resolve_default_item_group")
	@patch(
		"myapp.services.wholesale_service._get_item_mode_default_uom_field",
		side_effect=lambda mode: {
			"wholesale": "custom_wholesale_default_uom",
			"retail": "custom_retail_default_uom",
		}.get(mode),
	)
	@patch("myapp.services.wholesale_service._normalize_mode_default_uom")
	@patch("myapp.services.wholesale_service._get_item_specification_field")
	@patch("myapp.services.wholesale_service._get_item_nickname_field")
	@patch("myapp.services.wholesale_service.frappe.get_doc")
	def test_update_product_v2_updates_basic_fields(
		self,
		mock_get_doc,
		mock_get_item_nickname_field,
		mock_get_item_specification_field,
		mock_normalize_mode_default_uom,
		mock_get_item_mode_default_uom_field,
		mock_resolve_default_item_group,
		mock_update_primary_barcode,
		mock_validate_mode_default_uoms_against_stock_uom,
		mock_apply_item_uom_updates,
		mock_resolve_company_from_warehouse,
		mock_get_qty_map,
		mock_resolve_item_quantity_to_stock,
		mock_create_stock_adjustment_entry,
		mock_upsert_item_price,
		mock_build_product_detail_payload,
	 ):
		item = MagicMock()
		item.name = "ITEM-001"
		item.standard_rate = 18
		item.valuation_rate = 9
		mock_get_doc.return_value = item
		mock_get_item_nickname_field.return_value = "custom_nickname"
		mock_get_item_specification_field.return_value = "custom_specification"
		mock_resolve_default_item_group.return_value = "饮料"
		mock_normalize_mode_default_uom.side_effect = ["Case", "Piece"]
		mock_resolve_company_from_warehouse.return_value = "rgc (Demo)"
		mock_get_qty_map.return_value = {"ITEM-001": 5}
		mock_resolve_item_quantity_to_stock.return_value = {"stock_qty": 24}
		mock_build_product_detail_payload.return_value = {"item_code": "ITEM-001", "nickname": "新昵称"}

		result = update_product_v2(
			item_code="ITEM-001",
			item_name="新名称",
			item_group="饮料",
			brand="可口可乐",
			barcode="BAR-NEW",
			description="新描述",
			nickname="新昵称",
			specification="1000ml",
			image="/files/new.png",
			wholesale_default_uom="Case",
			retail_default_uom="Piece",
			standard_rate=18,
			warehouse="Stores - RD",
			warehouse_stock_qty=12,
			warehouse_stock_uom="Case",
		)

		self.assertEqual(item.item_name, "新名称")
		self.assertEqual(item.item_group, "饮料")
		self.assertEqual(item.brand, "可口可乐")
		self.assertEqual(item.description, "新描述")
		self.assertEqual(item.custom_nickname, "新昵称")
		self.assertEqual(item.custom_specification, "1000ml")
		self.assertEqual(item.image, "/files/new.png")
		mock_apply_item_uom_updates.assert_called_once()
		mock_validate_mode_default_uoms_against_stock_uom.assert_called_once()
		self.assertEqual(item.custom_wholesale_default_uom, "Case")
		self.assertEqual(item.custom_retail_default_uom, "Piece")
		mock_update_primary_barcode.assert_called_once_with(item, "BAR-NEW")
		item.save.assert_called_once()
		item.reload.assert_called_once()
		mock_upsert_item_price.assert_called_once()
		mock_create_stock_adjustment_entry.assert_called_once_with(
			item_code="ITEM-001",
			warehouse="Stores - RD",
			qty_delta=19.0,
			company="rgc (Demo)",
			valuation_rate=18.0,
			posting_date=None,
		)
		self.assertEqual(result["data"]["nickname"], "新昵称")

	@patch("myapp.services.wholesale_service._build_product_detail_payload")
	@patch("myapp.services.wholesale_service._update_primary_barcode")
	@patch("myapp.services.wholesale_service._resolve_default_item_group")
	@patch("myapp.services.wholesale_service._get_item_mode_default_uom_field")
	@patch("myapp.services.wholesale_service._normalize_mode_default_uom")
	@patch("myapp.services.wholesale_service._apply_item_uom_updates")
	@patch("myapp.services.wholesale_service._resolve_default_uom")
	@patch("myapp.services.wholesale_service.frappe.get_doc")
	@patch("myapp.services.wholesale_service.frappe.throw", side_effect=frappe.ValidationError)
	def test_update_product_v2_rejects_mode_default_uom_without_conversion(
		self,
		_mock_throw,
		mock_get_doc,
		mock_resolve_default_uom,
		mock_apply_item_uom_updates,
		mock_normalize_mode_default_uom,
		mock_get_item_mode_default_uom_field,
		_mock_resolve_default_item_group,
		_mock_update_primary_barcode,
		_mock_build_product_detail_payload,
	):
		mock_resolve_default_uom.side_effect = lambda value=None: (value or "Nos").strip()
		item = frappe._dict(
			{
				"name": "ITEM-001",
				"stock_uom": "Nos",
				"uoms": [{"uom": "Nos", "conversion_factor": 1}],
			}
		)
		item.save = MagicMock()
		mock_get_doc.return_value = item
		mock_normalize_mode_default_uom.return_value = "Box"
		mock_get_item_mode_default_uom_field.return_value = "custom_wholesale_default_uom"

		with self.assertRaises(frappe.ValidationError):
			update_product_v2(item_code="ITEM-001", wholesale_default_uom="Box")

		mock_apply_item_uom_updates.assert_called_once()
		item.save.assert_not_called()

	@patch("myapp.services.wholesale_service._create_stock_entry")
	@patch("myapp.services.wholesale_service.resolve_item_quantity_to_stock")
	@patch("myapp.services.wholesale_service._upsert_item_price")
	@patch("myapp.services.wholesale_service._apply_item_uom_updates")
	@patch("myapp.services.wholesale_service._build_item_code")
	@patch("myapp.services.wholesale_service._resolve_default_item_group")
	@patch("myapp.services.wholesale_service._resolve_default_uom")
	@patch("myapp.services.wholesale_service._resolve_company_from_warehouse")
	@patch("myapp.services.wholesale_service._resolve_default_warehouse")
	@patch("myapp.services.wholesale_service.frappe.defaults.get_user_default", return_value="CNY")
	@patch("myapp.services.wholesale_service.frappe.new_doc")
	def test_create_product_and_stock_converts_opening_qty_by_input_uom(
		self,
		mock_new_doc,
		_mock_get_user_default,
		mock_resolve_default_warehouse,
		mock_resolve_company_from_warehouse,
		mock_resolve_default_uom,
		mock_resolve_default_item_group,
		mock_build_item_code,
		mock_apply_item_uom_updates,
		mock_upsert_item_price,
		mock_resolve_item_quantity_to_stock,
		mock_create_stock_entry,
	):
		item = MagicMock()
		item.item_code = "ITEM-001"
		item.item_name = "测试可乐"
		item.stock_uom = "Bottle"
		item.image = None
		item.description = None
		item.insert = MagicMock()
		mock_new_doc.return_value = item
		mock_resolve_default_warehouse.return_value = "Stores - RD"
		mock_resolve_company_from_warehouse.return_value = "rgc (Demo)"
		mock_resolve_default_uom.return_value = "Bottle"
		mock_resolve_default_item_group.return_value = "饮料"
		mock_build_item_code.return_value = "ITEM-001"
		mock_resolve_item_quantity_to_stock.return_value = {
			"qty": 10,
			"uom": "Case",
			"stock_qty": 240,
		}
		stock_entry = MagicMock()
		stock_entry.name = "MAT-STE-0002"
		mock_create_stock_entry.return_value = stock_entry

		result = create_product_and_stock(
			item_name="测试可乐",
			warehouse="Stores - RD",
			opening_qty=10,
			opening_uom="Case",
			stock_uom="Bottle",
		)

		mock_create_stock_entry.assert_called_once_with(
			item_code="ITEM-001",
			warehouse="Stores - RD",
			qty=240,
			company="rgc (Demo)",
			valuation_rate=0.0,
			posting_date=None,
		)
		self.assertEqual(result["data"]["qty"], 240)
		self.assertEqual(result["data"]["input_qty"], 10)
		self.assertEqual(result["data"]["input_uom"], "Case")
