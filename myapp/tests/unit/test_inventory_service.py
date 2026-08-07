from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.inventory_service import (
	list_inventory_stock_summary_v1,
	list_stock_ledger_entries_v1,
	reconcile_inventory_stock_v1,
	submit_inventory_stock_count_v1,
	transfer_inventory_stock_v1,
)


class TestInventoryService(TestCase):
	@patch("myapp.services.inventory_service.frappe.db", new_callable=MagicMock)
	@patch("myapp.services.inventory_service.nowdate", return_value="2026-04-30")
	@patch("myapp.services.inventory_service.frappe.get_list")
	def test_list_stock_ledger_entries_v1_returns_paginated_rows(
		self,
		mock_get_list,
		mock_nowdate,
		mock_db,
	):
		mock_get_list.side_effect = [
			[f"SLE-{index:04d}" for index in range(11)],
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
		mock_get_list.assert_any_call(
			"Stock Ledger Entry",
			filters=[
				["posting_date", "between", ["2026-04-01", "2026-04-30"]],
				["company", "=", "Test Company"],
				["item_code", "=", "ITEM-001"],
				["warehouse", "=", "Stores - TC"],
				["voucher_type", "=", "Delivery Note"],
				["voucher_no", "=", "DN-0001"],
			],
			pluck="name",
			limit_page_length=0,
		)
		mock_get_list.assert_any_call(
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
	@patch("myapp.services.inventory_service.frappe.get_list")
	def test_list_stock_ledger_entries_v1_clamps_page_size(
		self,
		mock_get_list,
		mock_nowdate,
		mock_db,
	):
		mock_get_list.return_value = []

		result = list_stock_ledger_entries_v1(page=1, page_size=1000)

		self.assertEqual(result["data"]["pagination"]["page_size"], 100)
		self.assertFalse(result["data"]["pagination"]["has_more"])
		stock_ledger_calls = [
			call for call in mock_get_list.call_args_list if call.args[0] == "Stock Ledger Entry"
		]
		self.assertEqual(len(stock_ledger_calls), 2)
		self.assertEqual(stock_ledger_calls[1].kwargs["limit_page_length"], 100)

	@patch("myapp.services.inventory_service.get_permitted_warehouse_names", return_value=["Stores - TC", "Overflow - TC"])
	@patch("myapp.services.inventory_service.frappe.get_list")
	def test_list_inventory_stock_summary_v1_filters_low_stock_and_paginates(
		self,
		mock_get_list,
		_mock_get_permitted_warehouse_names,
	):
		mock_get_list.side_effect = [
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
		mock_get_list.assert_any_call(
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

	@patch("myapp.services.inventory_service.get_permitted_warehouse_names", return_value=["Stores - TC"])
	@patch("myapp.services.inventory_service.frappe.get_list")
	def test_list_inventory_stock_summary_v1_searches_item_codes(
		self, mock_get_list, _mock_get_permitted_warehouse_names
	):
		mock_get_list.side_effect = [
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
		mock_get_list.assert_any_call(
			"Bin",
			filters={
				"warehouse": ["in", ["Stores - TC"]],
				"item_code": ["in", ["ITEM-001"]],
			},
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

	@patch("myapp.services.inventory_service.run_idempotent")
	@patch("myapp.services.inventory_service.resolve_item_quantity_to_stock")
	@patch("myapp.services.inventory_service.frappe.new_doc")
	@patch("myapp.services.inventory_service.frappe.db", new_callable=MagicMock)
	def test_transfer_inventory_stock_v1_creates_material_transfer(
		self,
		mock_db,
		mock_new_doc,
		mock_resolve_item_quantity_to_stock,
		mock_run_idempotent,
	):
		mock_run_idempotent.side_effect = lambda _scope, _request_id, callback: callback()
		mock_db.get_value.side_effect = [
			frappe._dict(
				{
					"name": "ITEM-001",
					"item_name": "Transfer Item",
					"stock_uom": "Nos",
					"disabled": 0,
					"is_stock_item": 1,
				}
			),
				frappe._dict({"name": "Stores - TC", "company": "Test Company", "disabled": 0, "is_group": 0}),
				frappe._dict({"name": "Transit - TC", "company": "Test Company", "disabled": 0, "is_group": 0}),
				12,
		]
		mock_resolve_item_quantity_to_stock.return_value = {
			"uom": "Box",
			"stock_uom": "Nos",
			"conversion_factor": 6,
			"qty": 1,
			"stock_qty": 6,
		}
		stock_entry = MagicMock()
		stock_entry.name = "MAT-STE-0001"
		mock_new_doc.return_value = stock_entry

		result = transfer_inventory_stock_v1(
			item_code="ITEM-001",
			source_warehouse="Stores - TC",
			target_warehouse="Transit - TC",
			qty=1,
			uom="Box",
			posting_date="2026-06-01",
			remarks="Move to transit",
			request_id="transfer-001",
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["stock_entry"], "MAT-STE-0001")
		self.assertEqual(result["data"]["stock_qty"], 6)
		self.assertEqual(result["data"]["source_qty_after"], 6)
		self.assertEqual(stock_entry.stock_entry_type, "Material Transfer")
		self.assertEqual(stock_entry.purpose, "Material Transfer")
		self.assertEqual(stock_entry.company, "Test Company")
		self.assertEqual(stock_entry.posting_date, "2026-06-01")
		self.assertEqual(stock_entry.remarks, "Move to transit")
		stock_entry.append.assert_called_once_with(
			"items",
			{
				"item_code": "ITEM-001",
				"qty": 6,
				"s_warehouse": "Stores - TC",
				"t_warehouse": "Transit - TC",
				"allow_zero_valuation_rate": 1,
			},
		)
		stock_entry.insert.assert_called_once()
		stock_entry.submit.assert_called_once()

	@patch("myapp.services.inventory_service.run_idempotent")
	@patch("myapp.services.inventory_service.resolve_item_quantity_to_stock")
	@patch("myapp.services.inventory_service.frappe.new_doc")
	@patch("myapp.services.inventory_service.frappe.db", new_callable=MagicMock)
	def test_reconcile_inventory_stock_v1_creates_delta_adjustment(
		self,
		mock_db,
		mock_new_doc,
		mock_resolve_item_quantity_to_stock,
		mock_run_idempotent,
	):
		mock_run_idempotent.side_effect = lambda _scope, _request_id, callback: callback()
		mock_db.get_value.side_effect = [
			frappe._dict(
				{
					"name": "ITEM-001",
					"item_name": "Counted Item",
					"stock_uom": "Nos",
					"disabled": 0,
					"is_stock_item": 1,
				}
			),
				frappe._dict({"name": "Stores - TC", "company": "Test Company", "disabled": 0, "is_group": 0}),
				3,
		]
		mock_resolve_item_quantity_to_stock.return_value = {
			"uom": "Box",
			"stock_uom": "Nos",
			"conversion_factor": 6,
			"qty": 2,
			"stock_qty": 12,
		}
		stock_entry = MagicMock()
		stock_entry.name = "MAT-STE-0002"
		mock_new_doc.return_value = stock_entry

		result = reconcile_inventory_stock_v1(
			item_code="ITEM-001",
			warehouse="Stores - TC",
			target_qty=2,
			uom="Box",
			valuation_rate=8,
			posting_date="2026-06-02",
			remarks="Cycle count",
			request_id="count-001",
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["stock_entry"], "MAT-STE-0002")
		self.assertEqual(result["data"]["target_stock_qty"], 12)
		self.assertEqual(result["data"]["qty_delta"], 9)
		self.assertEqual(stock_entry.stock_entry_type, "Material Receipt")
		stock_entry.append.assert_called_once_with(
			"items",
			{
				"item_code": "ITEM-001",
				"qty": 9,
				"basic_rate": 8,
				"valuation_rate": 8,
				"allow_zero_valuation_rate": 1,
				"t_warehouse": "Stores - TC",
			},
		)
		stock_entry.insert.assert_called_once()
		stock_entry.submit.assert_called_once()

	@patch("myapp.services.inventory_service.run_idempotent")
	@patch("myapp.services.inventory_service.resolve_item_quantity_to_stock")
	@patch("myapp.services.inventory_service.frappe.new_doc")
	@patch("myapp.services.inventory_service.frappe.db", new_callable=MagicMock)
	def test_submit_inventory_stock_count_v1_creates_stock_reconciliation(
		self,
		mock_db,
		mock_new_doc,
		mock_resolve_item_quantity_to_stock,
		mock_run_idempotent,
	):
		mock_run_idempotent.side_effect = lambda _scope, _request_id, callback: callback()
		mock_db.get_value.side_effect = [
			frappe._dict(
				{
					"name": "ITEM-001",
					"item_name": "Counted Item",
					"stock_uom": "Nos",
					"disabled": 0,
					"is_stock_item": 1,
				}
			),
				frappe._dict({"name": "Stores - TC", "company": "Test Company", "disabled": 0, "is_group": 0}),
				3,
			frappe._dict(
				{
					"name": "ITEM-002",
					"item_name": "Second Item",
					"stock_uom": "Nos",
					"disabled": 0,
					"is_stock_item": 1,
				}
			),
				frappe._dict({"name": "Stores - TC", "company": "Test Company", "disabled": 0, "is_group": 0}),
				5,
		]
		mock_resolve_item_quantity_to_stock.side_effect = [
			{
				"uom": "Box",
				"stock_uom": "Nos",
				"conversion_factor": 6,
				"qty": 2,
				"stock_qty": 12,
			},
			{
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"qty": 5,
				"stock_qty": 5,
			},
		]
		reconciliation = MagicMock()
		reconciliation.name = "STK-REC-0001"
		mock_new_doc.return_value = reconciliation

		result = submit_inventory_stock_count_v1(
			items=[
				{"item_code": "ITEM-001", "warehouse": "Stores - TC", "counted_qty": 2, "uom": "Box", "valuation_rate": 8},
				{"item_code": "ITEM-002", "warehouse": "Stores - TC", "counted_qty": 5, "uom": "Nos", "valuation_rate": 3},
			],
			company="Test Company",
			posting_date="2026-06-03",
			remarks="Monthly count",
			request_id="stock-count-001",
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["stock_reconciliation"], "STK-REC-0001")
		self.assertEqual(result["data"]["difference_count"], 1)
		self.assertEqual(result["data"]["rows"][0]["counted_stock_qty"], 12)
		self.assertEqual(result["data"]["rows"][0]["qty_delta"], 9)
		self.assertFalse(result["data"]["rows"][1]["has_difference"])
		self.assertEqual(reconciliation.company, "Test Company")
		self.assertEqual(reconciliation.purpose, "Stock Reconciliation")
		self.assertEqual(reconciliation.posting_date, "2026-06-03")
		self.assertEqual(reconciliation.remarks, "Monthly count")
		reconciliation.append.assert_called_once_with(
			"items",
			{
				"item_code": "ITEM-001",
				"warehouse": "Stores - TC",
				"qty": 12,
				"valuation_rate": 8,
			},
		)
		reconciliation.insert.assert_called_once()
		reconciliation.submit.assert_called_once()

	@patch("myapp.services.inventory_service.run_idempotent")
	@patch("myapp.services.inventory_service.resolve_item_quantity_to_stock")
	@patch("myapp.services.inventory_service.frappe.new_doc")
	@patch("myapp.services.inventory_service.frappe.db", new_callable=MagicMock)
	def test_submit_inventory_stock_count_v1_skips_document_when_no_difference(
		self,
		mock_db,
		mock_new_doc,
		mock_resolve_item_quantity_to_stock,
		mock_run_idempotent,
	):
		mock_run_idempotent.side_effect = lambda _scope, _request_id, callback: callback()
		mock_db.get_value.side_effect = [
			frappe._dict(
				{
					"name": "ITEM-001",
					"item_name": "Counted Item",
					"stock_uom": "Nos",
					"disabled": 0,
					"is_stock_item": 1,
				}
			),
				frappe._dict({"name": "Stores - TC", "company": "Test Company", "disabled": 0, "is_group": 0}),
				12,
		]
		mock_resolve_item_quantity_to_stock.return_value = {
			"uom": "Nos",
			"stock_uom": "Nos",
			"conversion_factor": 1,
			"qty": 12,
			"stock_qty": 12,
		}

		result = submit_inventory_stock_count_v1(
			items=[{"item_code": "ITEM-001", "warehouse": "Stores - TC", "counted_qty": 12, "uom": "Nos"}],
			company="Test Company",
			request_id="stock-count-no-diff",
		)

		self.assertEqual(result["status"], "success")
		self.assertIsNone(result["data"]["stock_reconciliation"])
		self.assertEqual(result["data"]["difference_count"], 0)
		mock_new_doc.assert_not_called()
