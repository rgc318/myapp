from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.inventory_service import (
	list_inventory_stock_summary_v1,
	list_stock_ledger_entries_v1,
)


class TestInventoryService(TestCase):
	@patch("myapp.services.inventory_service.frappe.db", new_callable=MagicMock)
	@patch("myapp.services.inventory_service.nowdate", return_value="2026-04-30")
	@patch("myapp.services.inventory_service.frappe.get_all")
	def test_list_stock_ledger_entries_v1_returns_paginated_rows(
		self,
		mock_get_all,
		mock_nowdate,
		mock_db,
	):
		mock_db.count.return_value = 11
		mock_get_all.side_effect = [
			[
				frappe._dict(
					{
						"name": "SLE-0002",
						"posting_date": "2026-04-02",
						"posting_time": "10:30:00",
						"company": "Test Company",
						"item_code": "ITEM-001",
						"warehouse": "Stores - TC",
						"actual_qty": -2,
						"qty_after_transaction": 8,
						"incoming_rate": 5,
						"stock_value_difference": -10,
						"voucher_type": "Delivery Note",
						"voucher_no": "DN-0001",
					}
				)
			],
			[frappe._dict({"name": "ITEM-001", "item_name": "Test Item"})],
		]

		result = list_stock_ledger_entries_v1(
			company="Test Company",
			date_from="2026-04-01",
			date_to="2026-04-30",
			item_code="ITEM-001",
			warehouse="Stores - TC",
			voucher_type="Delivery Note",
			voucher_no="DN-0001",
			page=2,
			page_size=5,
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["rows"][0]["item_name"], "Test Item")
		self.assertEqual(result["data"]["rows"][0]["actual_qty"], -2)
		self.assertEqual(result["data"]["pagination"]["page"], 2)
		self.assertEqual(result["data"]["pagination"]["page_size"], 5)
		self.assertEqual(result["data"]["pagination"]["total_count"], 11)
		self.assertTrue(result["data"]["pagination"]["has_more"])
		mock_db.count.assert_called_once_with(
			"Stock Ledger Entry",
			filters=[
				["posting_date", "between", ["2026-04-01", "2026-04-30"]],
				["company", "=", "Test Company"],
				["item_code", "=", "ITEM-001"],
				["warehouse", "=", "Stores - TC"],
				["voucher_type", "=", "Delivery Note"],
				["voucher_no", "=", "DN-0001"],
			],
		)
		mock_get_all.assert_any_call(
			"Stock Ledger Entry",
			filters=[
				["posting_date", "between", ["2026-04-01", "2026-04-30"]],
				["company", "=", "Test Company"],
				["item_code", "=", "ITEM-001"],
				["warehouse", "=", "Stores - TC"],
				["voucher_type", "=", "Delivery Note"],
				["voucher_no", "=", "DN-0001"],
			],
			fields=[
				"name",
				"posting_date",
				"posting_time",
				"company",
				"item_code",
				"warehouse",
				"actual_qty",
				"qty_after_transaction",
				"incoming_rate",
				"stock_value_difference",
				"voucher_type",
				"voucher_no",
			],
			order_by="posting_date desc, posting_time desc, creation desc",
			limit_start=5,
			limit_page_length=5,
		)

	@patch("myapp.services.inventory_service.frappe.db", new_callable=MagicMock)
	@patch("myapp.services.inventory_service.nowdate", return_value="2026-04-30")
	@patch("myapp.services.inventory_service.frappe.get_all")
	def test_list_stock_ledger_entries_v1_clamps_page_size(
		self,
		mock_get_all,
		mock_nowdate,
		mock_db,
	):
		mock_db.count.return_value = 0
		mock_get_all.return_value = []

		result = list_stock_ledger_entries_v1(page=1, page_size=1000)

		self.assertEqual(result["data"]["pagination"]["page_size"], 100)
		self.assertFalse(result["data"]["pagination"]["has_more"])
		stock_ledger_calls = [
			call for call in mock_get_all.call_args_list if call.args[0] == "Stock Ledger Entry"
		]
		self.assertEqual(len(stock_ledger_calls), 1)
		self.assertEqual(stock_ledger_calls[0].kwargs["limit_page_length"], 100)

	@patch("myapp.services.inventory_service.frappe.get_all")
	def test_list_inventory_stock_summary_v1_filters_low_stock_and_paginates(
		self,
		mock_get_all,
	):
		mock_get_all.side_effect = [
			[
				frappe._dict({"name": "Stores - TC", "company": "Test Company"}),
				frappe._dict({"name": "Overflow - TC", "company": "Test Company"}),
			],
			[
				frappe._dict(
					{
						"item_code": "ITEM-001",
						"warehouse": "Stores - TC",
						"actual_qty": 4,
						"reserved_qty": 1,
						"ordered_qty": 2,
						"indented_qty": 0,
						"projected_qty": 5,
						"valuation_rate": 8,
						"stock_value": 32,
					}
				),
				frappe._dict(
					{
						"item_code": "ITEM-002",
						"warehouse": "Overflow - TC",
						"actual_qty": 18,
						"reserved_qty": 0,
						"ordered_qty": 0,
						"indented_qty": 0,
						"projected_qty": 18,
						"valuation_rate": 3,
						"stock_value": 54,
					}
				),
			],
			[
				frappe._dict({"name": "ITEM-001", "item_name": "Low Stock Item", "stock_uom": "Nos", "disabled": 0}),
				frappe._dict({"name": "ITEM-002", "item_name": "Enough Stock Item", "stock_uom": "Nos", "disabled": 0}),
			],
			[
				frappe._dict({"name": "Overflow - TC", "company": "Test Company"}),
				frappe._dict({"name": "Stores - TC", "company": "Test Company"}),
			],
		]

		result = list_inventory_stock_summary_v1(
			company="Test Company",
			stock_status="low_stock",
			low_stock_threshold=5,
			page=1,
			page_size=20,
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["pagination"]["total_count"], 1)
		self.assertEqual(result["data"]["rows"][0]["item_code"], "ITEM-001")
		self.assertEqual(result["data"]["rows"][0]["item_name"], "Low Stock Item")
		self.assertEqual(result["data"]["rows"][0]["actual_qty"], 4)
		self.assertEqual(result["data"]["summary"]["actual_qty_total"], 4)
		self.assertFalse(result["data"]["pagination"]["has_more"])
		mock_get_all.assert_any_call(
			"Bin",
			filters={"warehouse": ["in", ["Stores - TC", "Overflow - TC"]]},
			fields=[
				"item_code",
				"warehouse",
				"actual_qty",
				"reserved_qty",
				"ordered_qty",
				"indented_qty",
				"projected_qty",
				"valuation_rate",
				"stock_value",
			],
			order_by="item_code asc, warehouse asc",
			limit_page_length=0,
		)

	@patch("myapp.services.inventory_service.frappe.get_all")
	def test_list_inventory_stock_summary_v1_searches_item_codes(self, mock_get_all):
		mock_get_all.side_effect = [
			[frappe._dict({"name": "ITEM-001"})],
			[
				frappe._dict(
					{
						"item_code": "ITEM-001",
						"warehouse": "Stores - TC",
						"actual_qty": -2,
						"reserved_qty": 0,
						"ordered_qty": 0,
						"indented_qty": 0,
						"projected_qty": -2,
						"valuation_rate": 5,
						"stock_value": -10,
					}
				)
			],
			[frappe._dict({"name": "ITEM-001", "item_name": "Negative Item", "stock_uom": "Nos", "disabled": 0})],
			[frappe._dict({"name": "Stores - TC", "company": "Test Company"})],
		]

		result = list_inventory_stock_summary_v1(search_key="ITEM", stock_status="negative")

		self.assertEqual(result["data"]["pagination"]["total_count"], 1)
		self.assertEqual(result["data"]["rows"][0]["item_code"], "ITEM-001")
		self.assertEqual(result["data"]["summary"]["negative_count"], 1)
		mock_get_all.assert_any_call(
			"Bin",
			filters={"item_code": ["in", ["ITEM-001"]]},
			fields=[
				"item_code",
				"warehouse",
				"actual_qty",
				"reserved_qty",
				"ordered_qty",
				"indented_qty",
				"projected_qty",
				"valuation_rate",
				"stock_value",
			],
			order_by="item_code asc, warehouse asc",
			limit_page_length=0,
		)
