from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.services.return_service import get_return_source_context_v2


class TestReturnService(TestCase):
	@patch("myapp.services.return_service._get_detail_loader")
	def test_get_return_source_context_v2_maps_sales_invoice(self, mock_get_detail_loader):
		mock_get_detail_loader.return_value = lambda **kwargs: {
			"status": "success",
			"data": {
				"sales_invoice_name": "ACC-SINV-0001",
				"document_status": "submitted",
				"customer": {
					"name": "CUST-001",
					"display_name": "Test Customer",
					"contact_person": "CONT-001",
				},
				"amounts": {
					"invoice_amount_estimate": 120,
					"receivable_amount": 120,
					"paid_amount": 0,
					"outstanding_amount": 120,
				},
				"actions": {"can_cancel_sales_invoice": True},
				"references": {"sales_orders": ["SO-0001"]},
				"items": [
					{
						"sales_invoice_item": "SII-001",
						"item_code": "ITEM-001",
						"item_name": "Item 1",
						"uom": "Nos",
						"warehouse": "Stores - TC",
						"qty": 2,
						"rate": 60,
						"amount": 120,
					}
				],
				"meta": {"company": "Test Company", "currency": "CNY", "posting_date": "2026-04-01"},
			},
		}

		result = get_return_source_context_v2("Sales Invoice", "ACC-SINV-0001")

		mock_get_detail_loader.assert_called_once_with("myapp.services.order_service.get_sales_invoice_detail")
		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["business_type"], "sales")
		self.assertEqual(result["data"]["source_label"], "销售发票")
		self.assertEqual(result["data"]["party"]["party_type"], "Customer")
		self.assertEqual(result["data"]["actions"]["detail_submit_key"], "sales_invoice_item")
		self.assertEqual(result["data"]["items"][0]["detail_id"], "SII-001")
		self.assertEqual(result["data"]["items"][0]["max_returnable_qty"], 2.0)
		self.assertEqual(result["data"]["amounts"]["primary_amount"], 120.0)

	@patch("myapp.services.return_service._get_detail_loader")
	def test_get_return_source_context_v2_maps_purchase_receipt(self, mock_get_detail_loader):
		mock_get_detail_loader.return_value = lambda **kwargs: {
			"status": "success",
			"data": {
				"purchase_receipt_name": "MAT-PRE-0001",
				"document_status": "submitted",
				"supplier": {
					"name": "SUP-001",
					"display_name": "Test Supplier",
					"contact_person": "CONT-002",
				},
				"amounts": {"receipt_amount_estimate": 88},
				"actions": {"can_cancel_purchase_receipt": True},
				"references": {"purchase_orders": ["PO-0001"]},
				"items": [
					{
						"purchase_receipt_item": "PRI-001",
						"item_code": "ITEM-001",
						"item_name": "Item 1",
						"uom": "Nos",
						"warehouse": "Stores - TC",
						"qty": 4,
						"rate": 22,
						"amount": 88,
					}
				],
				"meta": {"company": "Test Company", "currency": "CNY", "posting_date": "2026-04-01"},
			},
		}

		result = get_return_source_context_v2("Purchase Receipt", "MAT-PRE-0001")

		mock_get_detail_loader.assert_called_once_with("myapp.services.purchase_service.get_purchase_receipt_detail_v2")
		self.assertEqual(result["data"]["business_type"], "purchase")
		self.assertEqual(result["data"]["source_label"], "采购收货单")
		self.assertEqual(result["data"]["party"]["party_type"], "Supplier")
		self.assertEqual(result["data"]["actions"]["detail_submit_key"], "purchase_receipt_item")
		self.assertEqual(result["data"]["items"][0]["detail_id"], "PRI-001")
		self.assertEqual(result["data"]["items"][0]["default_return_qty"], 4.0)

	@patch("myapp.services.return_service.frappe.throw")
	def test_get_return_source_context_v2_rejects_unsupported_source(self, mock_throw):
		mock_throw.side_effect = frappe.ValidationError("unsupported")

		with self.assertRaises(frappe.ValidationError):
			get_return_source_context_v2("Sales Order", "SO-0001")
