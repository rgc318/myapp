from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.wholesale_service import create_product_and_stock, search_product_v2


class TestWholesaleService(TestCase):
	@patch("myapp.services.wholesale_service._get_qty_map")
	@patch("myapp.services.wholesale_service._get_uom_map")
	@patch("myapp.services.wholesale_service._get_price_map")
	@patch("myapp.services.wholesale_service._get_item_data_map")
	@patch("myapp.services.wholesale_service._search_item_codes")
	def test_search_product_v2_filters_in_stock_and_sorts_by_price_desc(
		self,
		mock_search_item_codes,
		mock_get_item_data_map,
		mock_get_price_map,
		mock_get_uom_map,
		mock_get_qty_map,
	):
		mock_search_item_codes.return_value = ["ITEM-001", "ITEM-002"]
		mock_get_item_data_map.return_value = {
			"ITEM-001": frappe._dict(
				{
					"name": "ITEM-001",
					"item_name": "商品一",
					"stock_uom": "Nos",
					"image": None,
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
					"description": "别名二",
					"creation": "2026-03-15 10:00:00",
					"modified": "2026-03-17 09:00:00",
				}
			),
		}
		mock_get_price_map.return_value = {"ITEM-001": 10, "ITEM-002": 25}
		mock_get_uom_map.return_value = {"ITEM-001": [], "ITEM-002": []}
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
		)

		mock_new_doc.assert_called_once_with("Item")
		item.insert.assert_called_once()
		item.append.assert_called_once_with("barcodes", {"barcode": "BAR-001X"})
		mock_upsert_item_price.assert_called_once()
		mock_create_stock_entry.assert_called_once()
		self.assertEqual(result["data"]["item_code"], "TEST-COLA")
		self.assertEqual(result["data"]["warehouse"], "Stores - RD")
		self.assertEqual(result["data"]["qty"], 8)
