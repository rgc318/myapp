from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.services.report_service import (
	get_business_report_v1,
	get_cashflow_report_v1,
	get_purchase_report_v1,
	get_sales_report_v1,
	list_cashflow_entries_v1,
)


class TestReportService(TestCase):
	@patch("myapp.services.report_service._build_sales_report_v1_data")
	def test_get_sales_report_v1_returns_sales_tables_and_meta(self, mock_build_sales_report_v1_data):
		mock_build_sales_report_v1_data.return_value = {
			"overview": {
				"sales_amount_total": 1200,
				"received_amount_total": 800,
				"receivable_outstanding_total": 400,
			},
			"tables": {
				"sales_summary": [{"name": "Customer A", "count": 2, "amount": 1200}],
				"sales_trend": [{"trend_date": "2026-04-01", "count": 2, "amount": 1200}],
				"sales_trend_hourly": [{"trend_hour": 9, "count": 2, "amount": 1200}],
				"sales_product_summary": [{"item_key": "SKU-1", "item_name": "Item A", "qty": 3, "amount": 1200}],
			},
		}

		result = get_sales_report_v1(company="Test Company", date_from="2026-04-01", date_to="2026-04-02", limit=8)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["overview"]["sales_amount_total"], 1200)
		self.assertEqual(result["data"]["tables"]["sales_summary"][0]["name"], "Customer A")
		self.assertEqual(result["data"]["meta"]["limit"], 8)
		mock_build_sales_report_v1_data.assert_called_once_with(
			company="Test Company",
			date_from="2026-04-01",
			date_to="2026-04-02",
			limit=8,
		)

	@patch("myapp.services.report_service._build_purchase_report_v1_data")
	def test_get_purchase_report_v1_returns_purchase_tables_and_meta(self, mock_build_purchase_report_v1_data):
		mock_build_purchase_report_v1_data.return_value = {
			"overview": {
				"purchase_amount_total": 900,
				"paid_amount_total": 300,
				"payable_outstanding_total": 600,
			},
			"tables": {
				"purchase_summary": [{"name": "Supplier A", "count": 2, "amount": 900}],
				"purchase_trend": [{"trend_date": "2026-04-01", "count": 2, "amount": 900}],
				"purchase_trend_hourly": [{"trend_hour": 10, "count": 2, "amount": 900}],
				"purchase_product_summary": [{"item_key": "MAT-1", "item_name": "Material A", "qty": 6, "amount": 900}],
			},
		}

		result = get_purchase_report_v1(company="Test Company", date_from="2026-04-01", date_to="2026-04-02", limit=6)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["overview"]["purchase_amount_total"], 900)
		self.assertEqual(result["data"]["tables"]["purchase_summary"][0]["name"], "Supplier A")
		self.assertEqual(result["data"]["meta"]["limit"], 6)
		mock_build_purchase_report_v1_data.assert_called_once_with(
			company="Test Company",
			date_from="2026-04-01",
			date_to="2026-04-02",
			limit=6,
		)

	@patch("myapp.services.report_service.nowdate", return_value="2026-04-02")
	@patch("myapp.services.report_service._make_payment_type_totals")
	@patch("myapp.services.report_service._make_cashflow_trend_rows")
	def test_get_cashflow_report_v1_returns_overview_and_trend(
		self,
		mock_make_cashflow_trend_rows,
		mock_make_payment_type_totals,
		mock_nowdate,
	):
		mock_make_payment_type_totals.return_value = [
			frappe._dict({"payment_type": "Receive", "total_received_amount": 900, "total_paid_amount": 900}),
			frappe._dict({"payment_type": "Pay", "total_received_amount": 250, "total_paid_amount": 250}),
		]
		mock_make_cashflow_trend_rows.return_value = [
			frappe._dict({"trend_date": "2026-04-01", "count": 1, "in_amount": 500, "out_amount": 0}),
			frappe._dict({"trend_date": "2026-04-02", "count": 2, "in_amount": 400, "out_amount": 250}),
		]

		result = get_cashflow_report_v1(company="Test Company")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["overview"]["received_amount_total"], 900)
		self.assertEqual(result["data"]["overview"]["paid_amount_total"], 250)
		self.assertEqual(result["data"]["overview"]["net_cashflow_total"], 650)
		self.assertEqual(result["data"]["trend"][0]["trend_date"], "2026-04-01")
		self.assertEqual(result["data"]["meta"]["company"], "Test Company")
		mock_make_payment_type_totals.assert_called_once_with(
			company="Test Company",
			date_from="2026-03-04",
			date_to="2026-04-02",
		)

	@patch("myapp.services.report_service.nowdate", return_value="2026-04-02")
	@patch("myapp.services.report_service._count_cashflow_entries")
	@patch("myapp.services.report_service._make_cashflow_entry_rows")
	def test_list_cashflow_entries_v1_returns_paginated_rows(
		self,
		mock_make_cashflow_entry_rows,
		mock_count_cashflow_entries,
		mock_nowdate,
	):
		mock_count_cashflow_entries.return_value = 45
		mock_make_cashflow_entry_rows.return_value = [
			frappe._dict(
				{
					"name": "PE-0002",
					"posting_date": "2026-04-02",
					"payment_type": "Pay",
					"party_type": "Supplier",
					"party": "Supplier A",
					"mode_of_payment": "Bank",
					"paid_amount": 200,
					"received_amount": 0,
					"reference_no": "PV-001",
				}
			),
			frappe._dict(
				{
					"name": "PE-0001",
					"posting_date": "2026-04-01",
					"payment_type": "Receive",
					"party_type": "Customer",
					"party": "Customer A",
					"mode_of_payment": "Cash",
					"paid_amount": 0,
					"received_amount": 300,
					"reference_no": "RC-001",
				}
			),
		]

		result = list_cashflow_entries_v1(company="Test Company", page=2, page_size=2)

		self.assertEqual(result["status"], "success")
		self.assertEqual(len(result["data"]["rows"]), 2)
		self.assertEqual(result["data"]["rows"][0]["direction"], "out")
		self.assertEqual(result["data"]["rows"][1]["direction"], "in")
		self.assertEqual(result["data"]["pagination"]["page"], 2)
		self.assertEqual(result["data"]["pagination"]["page_size"], 2)
		self.assertEqual(result["data"]["pagination"]["total_count"], 45)
		self.assertTrue(result["data"]["pagination"]["has_more"])
		mock_count_cashflow_entries.assert_called_once_with(
			company="Test Company",
			date_from="2026-03-04",
			date_to="2026-04-02",
		)
		mock_make_cashflow_entry_rows.assert_called_once_with(
			company="Test Company",
			date_from="2026-03-04",
			date_to="2026-04-02",
			limit=2,
			offset=2,
		)

	@patch("myapp.services.report_service.nowdate", return_value="2026-04-02")
	@patch("myapp.services.report_service._count_cashflow_entries")
	@patch("myapp.services.report_service._make_cashflow_entry_rows")
	def test_list_cashflow_entries_v1_clamps_page_size(
		self,
		mock_make_cashflow_entry_rows,
		mock_count_cashflow_entries,
		mock_nowdate,
	):
		mock_count_cashflow_entries.return_value = 0
		mock_make_cashflow_entry_rows.return_value = []

		result = list_cashflow_entries_v1(page=1, page_size=1000)

		self.assertEqual(result["data"]["pagination"]["page_size"], 100)
		self.assertFalse(result["data"]["pagination"]["has_more"])
		mock_make_cashflow_entry_rows.assert_called_once_with(
			company=None,
			date_from="2026-03-04",
			date_to="2026-04-02",
			limit=100,
			offset=0,
		)

	@patch("myapp.services.report_service.nowdate", return_value="2026-04-02")
	@patch("myapp.services.report_service._make_purchase_hourly_rows")
	@patch("myapp.services.report_service._make_sales_hourly_rows")
	@patch("myapp.services.report_service._make_cashflow_trend_rows")
	@patch("myapp.services.report_service._make_purchase_product_rows")
	@patch("myapp.services.report_service._make_purchase_trend_rows")
	@patch("myapp.services.report_service._make_sales_product_rows")
	@patch("myapp.services.report_service._make_sales_trend_rows")
	@patch("myapp.services.report_service._make_payment_type_totals")
	@patch("myapp.services.report_service._make_scalar_aggregate")
	@patch("myapp.services.report_service._make_recent_cashflow_rows")
	@patch("myapp.services.report_service._make_invoice_grouped_rows")
	@patch("myapp.services.report_service._make_grouped_rows")
	def test_get_business_report_v1_returns_overview_and_tables(
		self,
		mock_make_grouped_rows,
		mock_make_invoice_grouped_rows,
		mock_make_recent_cashflow_rows,
		mock_make_scalar_aggregate,
		mock_make_payment_type_totals,
		mock_make_sales_trend_rows,
		mock_make_sales_product_rows,
		mock_make_purchase_trend_rows,
		mock_make_purchase_product_rows,
		mock_make_cashflow_trend_rows,
		mock_make_sales_hourly_rows,
		mock_make_purchase_hourly_rows,
		mock_nowdate,
	):
		mock_make_grouped_rows.side_effect = [
			[
				frappe._dict({"name": "Customer A", "count": 2, "amount": 2000}),
				frappe._dict({"name": "Customer B", "count": 1, "amount": 500}),
			],
			[
				frappe._dict({"name": "Supplier A", "count": 1, "amount": 600}),
				frappe._dict({"name": "Supplier B", "count": 1, "amount": 300}),
			],
		]
		mock_make_invoice_grouped_rows.side_effect = [
			[
				frappe._dict({"name": "Customer B", "count": 1, "total_amount": 500, "paid_amount": 0, "outstanding_amount": 500}),
				frappe._dict({"name": "Customer A", "count": 1, "total_amount": 1000, "paid_amount": 800, "outstanding_amount": 200}),
			],
			[
				frappe._dict({"name": "Supplier A", "count": 1, "total_amount": 700, "paid_amount": 600, "outstanding_amount": 100}),
			],
		]
		mock_make_recent_cashflow_rows.return_value = [
			frappe._dict(
				{
					"name": "PE-0001",
					"posting_date": "2026-04-02",
					"payment_type": "Receive",
					"party_type": "Customer",
					"party": "Customer A",
					"mode_of_payment": "Cash",
					"received_amount": 800,
					"paid_amount": 800,
					"reference_no": "RC-001",
				}
			),
			frappe._dict(
				{
					"name": "PE-0002",
					"posting_date": "2026-04-01",
					"payment_type": "Pay",
					"party_type": "Supplier",
					"party": "Supplier A",
					"mode_of_payment": "Bank",
					"received_amount": 400,
					"paid_amount": 400,
					"reference_no": "PV-001",
				}
			),
		]
		mock_make_scalar_aggregate.side_effect = [9999, 5555, 777, 333]
		mock_make_payment_type_totals.return_value = [
			frappe._dict({"payment_type": "Receive", "total_received_amount": 2500, "total_paid_amount": 2500}),
			frappe._dict({"payment_type": "Pay", "total_received_amount": 1200, "total_paid_amount": 1200}),
		]
		mock_make_sales_trend_rows.return_value = [
			frappe._dict({"trend_date": "2026-04-01", "count": 2, "amount": 1000}),
			frappe._dict({"trend_date": "2026-04-02", "count": 1, "amount": 500}),
		]
		mock_make_sales_product_rows.return_value = [
			frappe._dict({"item_key": "SKU-1", "item_name": "Product A", "qty": 5, "amount": 900}),
		]
		mock_make_purchase_trend_rows.return_value = [
			frappe._dict({"trend_date": "2026-04-01", "count": 1, "amount": 600}),
			frappe._dict({"trend_date": "2026-04-02", "count": 2, "amount": 1200}),
		]
		mock_make_purchase_product_rows.return_value = [
			frappe._dict({"item_key": "MAT-1", "item_name": "Material A", "qty": 8, "amount": 700}),
		]
		mock_make_sales_hourly_rows.return_value = [
			frappe._dict({"trend_hour": 10, "count": 1, "amount": 100}),
		]
		mock_make_purchase_hourly_rows.return_value = [
			frappe._dict({"trend_hour": 11, "count": 1, "amount": 200}),
		]
		mock_make_cashflow_trend_rows.return_value = [
			frappe._dict({"trend_date": "2026-04-01", "count": 1, "in_amount": 500, "out_amount": 0}),
			frappe._dict({"trend_date": "2026-04-02", "count": 2, "in_amount": 800, "out_amount": 400}),
		]

		result = get_business_report_v1(company="Test Company", limit=10)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["overview"]["sales_amount_total"], 9999)
		self.assertEqual(result["data"]["overview"]["purchase_amount_total"], 5555)
		self.assertEqual(result["data"]["overview"]["received_amount_total"], 2500)
		self.assertEqual(result["data"]["overview"]["paid_amount_total"], 1200)
		self.assertEqual(result["data"]["overview"]["net_cashflow_total"], 1300)
		self.assertEqual(result["data"]["overview"]["receivable_outstanding_total"], 777)
		self.assertEqual(result["data"]["overview"]["payable_outstanding_total"], 333)
		self.assertEqual(result["data"]["tables"]["sales_summary"][0]["name"], "Customer A")
		self.assertEqual(result["data"]["tables"]["sales_trend"][0]["trend_date"], "2026-04-01")
		self.assertEqual(result["data"]["tables"]["sales_trend_hourly"][0]["trend_hour"], 10)
		self.assertEqual(result["data"]["tables"]["sales_product_summary"][0]["item_key"], "SKU-1")
		self.assertEqual(result["data"]["tables"]["purchase_trend"][0]["trend_date"], "2026-04-01")
		self.assertEqual(result["data"]["tables"]["purchase_trend_hourly"][0]["trend_hour"], 11)
		self.assertEqual(result["data"]["tables"]["purchase_product_summary"][0]["item_key"], "MAT-1")
		self.assertEqual(result["data"]["tables"]["receivable_summary"][0]["name"], "Customer B")
		self.assertEqual(result["data"]["tables"]["cashflow_summary"][0]["direction"], "in")
		self.assertEqual(result["data"]["tables"]["cashflow_trend"][0]["trend_date"], "2026-04-01")
		self.assertEqual(result["data"]["tables"]["cashflow_trend"][1]["in_amount"], 800)

		first_group_args = mock_make_grouped_rows.call_args_list[0].args
		first_group_kwargs = mock_make_grouped_rows.call_args_list[0].kwargs
		self.assertEqual(first_group_args[0], "tabSales Order")
		self.assertEqual(first_group_kwargs["party_field"], "customer")
		self.assertEqual(first_group_kwargs["date_from"], "2026-03-04")
		self.assertEqual(first_group_kwargs["date_to"], "2026-04-02")
		self.assertEqual(first_group_kwargs["company"], "Test Company")

	@patch("myapp.services.report_service.frappe.throw", side_effect=frappe.ValidationError("报表时间范围不能超过 366 天。"))
	def test_get_business_report_v1_rejects_too_large_date_range(self, mock_throw):
		with self.assertRaisesRegex(frappe.ValidationError, "报表时间范围不能超过 366 天"):
			get_business_report_v1(date_from="2024-01-01", date_to="2026-04-02")

	@patch("myapp.services.report_service.frappe.throw", side_effect=frappe.ValidationError("date_from 不能晚于 date_to。"))
	def test_get_business_report_v1_rejects_invalid_date_range(self, mock_throw):
		with self.assertRaisesRegex(frappe.ValidationError, "date_from 不能晚于 date_to"):
			get_business_report_v1(date_from="2026-04-03", date_to="2026-04-02")
