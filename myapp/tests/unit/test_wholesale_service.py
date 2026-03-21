from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.wholesale_service import (
	create_product_v2,
	create_product_and_stock,
	disable_product_v2,
	get_product_detail_v2,
	list_products_v2,
	search_product_v2,
	update_product_v2,
)


class TestWholesaleService(TestCase):
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
		mock_get_qty_map.return_value = {"ITEM-001": 9}
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

		result = list_products_v2(search_key="可乐")

		self.assertEqual(len(result["data"]), 1)
		self.assertEqual(result["data"][0]["item_code"], "ITEM-001")
		self.assertEqual(result["data"][0]["price_summary"]["wholesale_rate"], 12)
		self.assertEqual(result["data"][0]["price_summary"]["standard_buying_rate"], 6.2)
		self.assertEqual(result["data"][0]["wholesale_default_uom"], "Box")
		self.assertEqual(result["data"][0]["retail_default_uom"], "Bottle")
		self.assertEqual(result["data"][0]["valuation_rate"], 7.5)

	@patch("myapp.services.wholesale_service._get_primary_barcode")
	@patch("myapp.services.wholesale_service._get_uom_map")
	@patch("myapp.services.wholesale_service._get_multi_price_map")
	@patch("myapp.services.wholesale_service._get_price_map")
	@patch("myapp.services.wholesale_service._get_qty_map")
	@patch("myapp.services.wholesale_service._get_item_nickname_field")
	@patch("myapp.services.wholesale_service.frappe.get_doc")
	def test_get_product_detail_v2_returns_product_snapshot(
		self,
		mock_get_doc,
		mock_get_item_nickname_field,
		mock_get_qty_map,
		mock_get_price_map,
		mock_get_multi_price_map,
		mock_get_uom_map,
		mock_get_primary_barcode,
	):
		mock_get_item_nickname_field.return_value = "custom_nickname"
		mock_get_doc.return_value = frappe._dict(
			{
				"name": "ITEM-001",
				"item_name": "商品一",
				"item_group": "饮料",
				"stock_uom": "Nos",
				"image": "/files/a.png",
				"custom_nickname": "冰可乐",
				"custom_wholesale_default_uom": "Box",
				"custom_retail_default_uom": "Bottle",
				"description": "标准描述",
				"disabled": 0,
				"is_sales_item": 1,
				"creation": "2026-03-18 10:00:00",
				"modified": "2026-03-18 11:00:00",
			}
		)
		mock_get_qty_map.return_value = {"ITEM-001": 8}
		mock_get_price_map.return_value = {"ITEM-001": 15}
		mock_get_multi_price_map.side_effect = [
			{"ITEM-001": {"Wholesale": {"price_list": "Wholesale", "rate": 13, "currency": "CNY"}}},
			{"ITEM-001": {"Standard Buying": {"price_list": "Standard Buying", "rate": 8, "currency": "CNY"}}},
		]
		mock_get_uom_map.return_value = {"ITEM-001": [{"uom": "Box", "conversion_factor": 12}]}
		mock_get_primary_barcode.return_value = "BAR-001"

		result = get_product_detail_v2("ITEM-001", warehouse="Stores - RD")

		self.assertEqual(result["data"]["item_code"], "ITEM-001")
		self.assertEqual(result["data"]["nickname"], "冰可乐")
		self.assertEqual(result["data"]["image"], "/files/a.png")
		self.assertEqual(result["data"]["price"], 15)
		self.assertEqual(result["data"]["qty"], 8)
		self.assertEqual(result["data"]["barcode"], "BAR-001")
		self.assertEqual(result["data"]["price_summary"]["wholesale_rate"], 13)
		self.assertEqual(result["data"]["price_summary"]["standard_buying_rate"], 8)
		self.assertEqual(result["data"]["wholesale_default_uom"], "Box")
		self.assertEqual(result["data"]["retail_default_uom"], "Bottle")

	@patch("myapp.services.wholesale_service._get_qty_map")
	@patch("myapp.services.wholesale_service._get_multi_price_map")
	@patch("myapp.services.wholesale_service._get_uom_map")
	@patch("myapp.services.wholesale_service._get_price_map")
	@patch("myapp.services.wholesale_service._get_item_data_map")
	@patch("myapp.services.wholesale_service._search_item_codes")
	@patch("myapp.services.wholesale_service._get_item_nickname_field")
	def test_search_product_v2_filters_in_stock_and_sorts_by_price_desc(
		self,
		mock_get_item_nickname_field,
		mock_search_item_codes,
		mock_get_item_data_map,
		mock_get_price_map,
		mock_get_uom_map,
		mock_get_multi_price_map,
		mock_get_qty_map,
	):
		mock_get_item_nickname_field.return_value = "custom_nickname"
		mock_search_item_codes.return_value = ["ITEM-001", "ITEM-002"]
		mock_get_item_data_map.return_value = {
			"ITEM-001": frappe._dict(
				{
					"name": "ITEM-001",
					"item_name": "商品一",
					"stock_uom": "Nos",
					"image": None,
					"custom_nickname": "昵称一",
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
		mock_get_qty_map.return_value = {"ITEM-001": 0, "ITEM-002": 8}

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
		self.assertEqual(result["data"][0]["retail_default_uom"], "Pair")
		self.assertEqual(result["data"][0]["price_summary"]["wholesale_rate"], 22)
		self.assertEqual(result["filters"]["sort_by"], "price")
		self.assertTrue(result["filters"]["in_stock_only"])

	@patch("myapp.services.wholesale_service.frappe.db.exists")
	@patch("myapp.services.wholesale_service.frappe.defaults.get_user_default")
	def test_create_product_and_stock_requires_warehouse_when_no_default(
		self, mock_get_user_default, mock_exists
	):
		mock_get_user_default.return_value = None
		mock_exists.return_value = False

		with self.assertRaises(frappe.ValidationError):
			create_product_and_stock(item_name="测试商品")

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
	@patch("myapp.services.wholesale_service.frappe.new_doc")
	@patch("myapp.services.wholesale_service.frappe.db.get_value")
	@patch("myapp.services.wholesale_service.frappe.db.exists")
	def test_create_product_and_stock_builds_item_and_receipt(
		self,
		mock_exists,
		mock_get_value,
		mock_new_doc,
		mock_upsert_item_price,
		mock_get_item_nickname_field,
		mock_create_stock_entry,
	):
		def fake_exists(doctype, filters=None):
			if doctype == "Item":
				return False
			if doctype == "UOM":
				return True
			if doctype == "Item Group":
				return filters == "All Item Groups" or filters == {"barcode": "BAR-001"}
			if doctype == "Item Barcode":
				return False
			return False

		mock_exists.side_effect = fake_exists
		mock_get_value.return_value = "Test Company"
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
	@patch("myapp.services.wholesale_service._apply_item_price_updates")
	@patch("myapp.services.wholesale_service._build_item_code")
	@patch("myapp.services.wholesale_service._resolve_default_item_group")
	@patch("myapp.services.wholesale_service._get_item_mode_default_uom_field")
	@patch("myapp.services.wholesale_service._normalize_mode_default_uom")
	@patch("myapp.services.wholesale_service._resolve_default_uom")
	@patch("myapp.services.wholesale_service._get_item_nickname_field")
	@patch("myapp.services.wholesale_service.frappe.new_doc")
	def test_create_product_v2_creates_item_without_stock_entry(
		self,
		mock_new_doc,
		mock_get_item_nickname_field,
		mock_resolve_default_uom,
		mock_normalize_mode_default_uom,
		mock_get_item_mode_default_uom_field,
		mock_resolve_default_item_group,
		mock_build_item_code,
		mock_apply_item_price_updates,
		mock_build_product_detail_payload,
	):
		mock_get_item_nickname_field.return_value = "custom_nickname"
		mock_resolve_default_uom.return_value = "Nos"
		mock_normalize_mode_default_uom.side_effect = ["Box", "Bottle"]
		mock_get_item_mode_default_uom_field.side_effect = [
			"custom_wholesale_default_uom",
			"custom_retail_default_uom",
		]
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
			wholesale_default_uom="Box",
			retail_default_uom="Bottle",
			standard_rate=19,
			selling_prices=[{"price_list": "Wholesale", "rate": 16}],
		)

		mock_new_doc.assert_called_once_with("Item")
		self.assertEqual(item.custom_wholesale_default_uom, "Box")
		self.assertEqual(item.custom_retail_default_uom, "Bottle")
		item.insert.assert_called_once()
		mock_apply_item_price_updates.assert_called_once()
		self.assertEqual(result["data"]["item_code"], "ITEM-NEW")

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
	@patch("myapp.services.wholesale_service._get_item_mode_default_uom_field")
	@patch("myapp.services.wholesale_service._normalize_mode_default_uom")
	@patch("myapp.services.wholesale_service._get_item_nickname_field")
	@patch("myapp.services.wholesale_service.frappe.get_doc")
	def test_update_product_v2_updates_basic_fields(
		self,
		mock_get_doc,
		mock_get_item_nickname_field,
		mock_normalize_mode_default_uom,
		mock_get_item_mode_default_uom_field,
		mock_upsert_item_price,
		mock_build_product_detail_payload,
	):
		item = MagicMock()
		item.name = "ITEM-001"
		mock_get_doc.return_value = item
		mock_get_item_nickname_field.return_value = "custom_nickname"
		mock_normalize_mode_default_uom.side_effect = ["Case", "Piece"]
		mock_get_item_mode_default_uom_field.side_effect = [
			"custom_wholesale_default_uom",
			"custom_retail_default_uom",
		]
		mock_build_product_detail_payload.return_value = {"item_code": "ITEM-001", "nickname": "新昵称"}

		result = update_product_v2(
			item_code="ITEM-001",
			item_name="新名称",
			description="新描述",
			nickname="新昵称",
			image="/files/new.png",
			wholesale_default_uom="Case",
			retail_default_uom="Piece",
			standard_rate=18,
		)

		self.assertEqual(item.item_name, "新名称")
		self.assertEqual(item.description, "新描述")
		self.assertEqual(item.custom_nickname, "新昵称")
		self.assertEqual(item.image, "/files/new.png")
		self.assertEqual(item.custom_wholesale_default_uom, "Case")
		self.assertEqual(item.custom_retail_default_uom, "Piece")
		item.save.assert_called_once()
		item.reload.assert_called_once()
		mock_upsert_item_price.assert_called_once()
		self.assertEqual(result["data"]["nickname"], "新昵称")
