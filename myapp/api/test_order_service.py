from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.order_service import create_order, create_sales_invoice, submit_delivery


class TestOrderService(TestCase):
	@patch("myapp.services.order_service.frappe.get_all")
	def test_validate_stock_for_immediate_delivery_rejects_insufficient_stock(self, mock_get_all):
		from myapp.services.order_service import _validate_stock_for_immediate_delivery

		mock_get_all.return_value = [{"actual_qty": -1, "reserved_qty": 1}]

		with self.assertRaises(frappe.ValidationError):
			_validate_stock_for_immediate_delivery(
				[{"item_code": "ITEM-001", "qty": 1, "warehouse": "Stores - TC"}]
			)

	@patch("myapp.services.order_service.frappe.get_all")
	def test_validate_stock_for_immediate_delivery_rejects_missing_bin(self, mock_get_all):
		from myapp.services.order_service import _validate_stock_for_immediate_delivery

		mock_get_all.return_value = []

		with self.assertRaises(frappe.ValidationError):
			_validate_stock_for_immediate_delivery(
				[{"item_code": "ITEM-001", "qty": 1, "warehouse": "Stores - TC"}]
			)

	@patch("myapp.services.order_service.frappe.db.get_value")
	def test_build_sales_order_item_rejects_cross_company_warehouse(self, mock_get_value):
		from myapp.services.order_service import _build_sales_order_item

		mock_get_value.return_value = "Other Company"

		with self.assertRaises(frappe.ValidationError):
			_build_sales_order_item(
				{"item_code": "ITEM-001", "qty": 1, "warehouse": "Stores - OC"},
				"2026-03-10",
				None,
				"Test Company",
			)

	@patch("myapp.services.order_service._insert_and_submit")
	@patch("myapp.services.order_service.frappe.db.get_value")
	@patch("myapp.services.order_service.frappe.new_doc")
	@patch("myapp.services.order_service.frappe.defaults.get_user_default")
	def test_create_order_builds_and_submits_sales_order(
		self, mock_get_user_default, mock_new_doc, mock_get_value, mock_insert_and_submit
	):
		mock_get_user_default.return_value = "Test Company"
		mock_get_value.return_value = "Test Company"
		so = MagicMock()
		so.name = "SO-0001"
		so.docstatus = 1
		mock_new_doc.return_value = so

		result = create_order(
			customer="Test Customer",
			items=[{"item_code": "ITEM-001", "qty": 2, "warehouse": "Stores - TC"}],
		)

		mock_new_doc.assert_called_once_with("Sales Order")
		self.assertEqual(result["status"], "success")
		self.assertEqual(result["order"], "SO-0001")
		mock_insert_and_submit.assert_called_once_with(so)
		so.append.assert_called_once()

	def test_create_order_rejects_empty_items(self):
		with self.assertRaises(frappe.ValidationError):
			create_order(customer="Test Customer", items=[], company="Test Company")

	@patch("erpnext.selling.doctype.sales_order.sales_order.make_delivery_note")
	def test_submit_delivery_rejects_sales_order_without_deliverable_items(self, mock_make_delivery_note):
		dn = frappe._dict({"items": []})
		mock_make_delivery_note.return_value = dn

		with self.assertRaisesRegex(frappe.ValidationError, "没有可发货的商品明细"):
			submit_delivery("SO-0001")

	@patch("erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice")
	def test_create_sales_invoice_rejects_sales_order_without_billable_items(self, mock_make_sales_invoice):
		si = frappe._dict({"items": []})
		mock_make_sales_invoice.return_value = si

		with self.assertRaisesRegex(frappe.ValidationError, "没有可开票的商品明细"):
			create_sales_invoice("SO-0001")

	@patch("myapp.services.order_service.get_idempotent_result")
	@patch("myapp.services.order_service.frappe.db.get_value")
	@patch("myapp.services.order_service.frappe.defaults.get_user_default")
	def test_create_order_immediate_returns_cached_result_for_same_request_id(
		self, mock_get_user_default, mock_get_value, mock_get_idempotent_result
	):
		mock_get_user_default.return_value = "Test Company"
		mock_get_value.return_value = "Test Company"
		mock_get_idempotent_result.return_value = {
			"status": "success",
			"order": "SO-0009",
			"delivery_note": "DN-0009",
			"sales_invoice": "SINV-0009",
		}

		result = create_order(
			customer="Test Customer",
			items=[{"item_code": "ITEM-001", "qty": 2, "warehouse": "Stores - TC"}],
			immediate=1,
			request_id="req-001",
		)

		self.assertEqual(result["order"], "SO-0009")
		self.assertEqual(result["delivery_note"], "DN-0009")
		mock_get_idempotent_result.assert_called_once_with("create_order_immediate", "req-001")
