from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.services.inventory_service import list_stock_ledger_entries_v1


class TestInventoryService(TestCase):
	@patch("myapp.services.inventory_service.nowdate", return_value="2026-04-30")
	@patch("myapp.services.inventory_service.frappe.get_all")
	@patch("myapp.services.inventory_service.frappe.db.count")
	def test_list_stock_ledger_entries_v1_returns_paginated_rows(
		self,
		mock_count,
		mock_get_all,
		mock_nowdate,
	):
		mock_count.return_value = 11
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
		mock_count.assert_called_once_with(
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

	@patch("myapp.services.inventory_service.nowdate", return_value="2026-04-30")
	@patch("myapp.services.inventory_service.frappe.get_all")
	@patch("myapp.services.inventory_service.frappe.db.count")
	def test_list_stock_ledger_entries_v1_clamps_page_size(
		self,
		mock_count,
		mock_get_all,
		mock_nowdate,
	):
		mock_count.return_value = 0
		mock_get_all.return_value = []

		result = list_stock_ledger_entries_v1(page=1, page_size=1000)

		self.assertEqual(result["data"]["pagination"]["page_size"], 100)
		self.assertFalse(result["data"]["pagination"]["has_more"])
		stock_ledger_calls = [
			call for call in mock_get_all.call_args_list if call.args[0] == "Stock Ledger Entry"
		]
		self.assertEqual(len(stock_ledger_calls), 1)
		self.assertEqual(stock_ledger_calls[0].kwargs["limit_page_length"], 100)
