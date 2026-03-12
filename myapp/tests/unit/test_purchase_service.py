from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.purchase_service import (
	create_purchase_invoice,
	create_purchase_order,
	process_purchase_return,
	receive_purchase_order,
	record_supplier_payment,
)


class TestPurchaseService(TestCase):
	@patch("myapp.services.purchase_service.frappe.db.get_value")
	def test_build_purchase_order_item_rejects_cross_company_warehouse(self, mock_get_value):
		from myapp.services.purchase_service import _build_purchase_order_item

		mock_get_value.return_value = "Other Company"

		with self.assertRaises(frappe.ValidationError):
			_build_purchase_order_item(
				{"item_code": "ITEM-001", "qty": 1, "warehouse": "Stores - OC"},
				"2026-03-11",
				None,
				"Test Company",
			)

	@patch("myapp.services.purchase_service._insert_and_submit")
	@patch("myapp.services.purchase_service.frappe.db.get_value")
	@patch("myapp.services.purchase_service.frappe.new_doc")
	@patch("myapp.services.purchase_service.frappe.defaults.get_user_default")
	def test_create_purchase_order_builds_and_submits_document(
		self, mock_get_user_default, mock_new_doc, mock_get_value, mock_insert_and_submit
	):
		mock_get_user_default.return_value = "Test Company"
		mock_get_value.return_value = "Test Company"
		po = MagicMock()
		po.name = "PO-0001"
		mock_new_doc.return_value = po

		result = create_purchase_order(
			supplier="Test Supplier",
			items=[{"item_code": "ITEM-001", "qty": 2, "warehouse": "Stores - TC"}],
		)

		mock_new_doc.assert_called_once_with("Purchase Order")
		self.assertEqual(result["purchase_order"], "PO-0001")
		mock_insert_and_submit.assert_called_once_with(po)
		po.append.assert_called_once()

	def test_create_purchase_order_rejects_empty_items(self):
		with self.assertRaises(frappe.ValidationError):
			create_purchase_order(supplier="Test Supplier", items=[], company="Test Company")

	@patch("erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt")
	def test_receive_purchase_order_rejects_order_without_receivable_items(self, mock_make_purchase_receipt):
		pr = frappe._dict({"items": []})
		mock_make_purchase_receipt.return_value = pr

		with self.assertRaisesRegex(frappe.ValidationError, "没有可收货的商品明细"):
			receive_purchase_order("PO-0001")

	@patch("erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_invoice")
	def test_create_purchase_invoice_rejects_order_without_billable_items(self, mock_make_purchase_invoice):
		pi = frappe._dict({"items": []})
		mock_make_purchase_invoice.return_value = pi

		with self.assertRaisesRegex(frappe.ValidationError, "没有可开票的商品明细"):
			create_purchase_invoice("PO-0001")

	@patch("erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry")
	def test_record_supplier_payment_creates_payment_entry(self, mock_get_payment_entry):
		pe = MagicMock()
		pe.name = "ACC-PAY-0001"
		pe.mode_of_payment = None
		mock_get_payment_entry.return_value = pe

		result = record_supplier_payment("PINV-0001", 100)

		mock_get_payment_entry.assert_called_once_with("Purchase Invoice", "PINV-0001", party_amount=100.0)
		pe.insert.assert_called_once()
		pe.submit.assert_called_once()
		self.assertEqual(result["payment_entry"], "ACC-PAY-0001")

	@patch("myapp.services.purchase_service.frappe.get_traceback", return_value="traceback")
	@patch("erpnext.controllers.sales_and_purchase_return.make_return_doc")
	def test_process_purchase_return_uses_return_factory(self, mock_make_return_doc, mock_traceback):
		return_doc = MagicMock()
		return_doc.name = "MAT-PRE-RET-0001"
		return_doc.doctype = "Purchase Receipt"
		return_doc.items = []
		mock_make_return_doc.return_value = return_doc

		result = process_purchase_return("Purchase Receipt", "MAT-PRE-0001")

		mock_make_return_doc.assert_called_once_with("Purchase Receipt", "MAT-PRE-0001")
		return_doc.insert.assert_called_once()
		return_doc.submit.assert_called_once()
		self.assertEqual(result["return_document"], "MAT-PRE-RET-0001")

	@patch("myapp.services.purchase_service.run_idempotent")
	def test_receive_purchase_order_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {"status": "success", "purchase_receipt": "MAT-PRE-0010"}

		result = receive_purchase_order("PO-0001", kwargs={"request_id": "pr-001"})

		self.assertEqual(result["purchase_receipt"], "MAT-PRE-0010")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.purchase_service.run_idempotent")
	def test_create_purchase_invoice_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {"status": "success", "purchase_invoice": "PINV-0010"}

		result = create_purchase_invoice("PO-0001", kwargs={"request_id": "pi-001"})

		self.assertEqual(result["purchase_invoice"], "PINV-0010")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.purchase_service.run_idempotent")
	def test_record_supplier_payment_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {"status": "success", "payment_entry": "ACC-PAY-0099"}

		result = record_supplier_payment("PINV-0001", 100, request_id="pay-001")

		self.assertEqual(result["payment_entry"], "ACC-PAY-0099")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.purchase_service.run_idempotent")
	def test_process_purchase_return_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {
			"status": "success",
			"return_document": "PINV-RET-0099",
			"return_doctype": "Purchase Invoice",
		}

		result = process_purchase_return("Purchase Invoice", "PINV-0001", request_id="ret-001")

		self.assertEqual(result["return_document"], "PINV-RET-0099")
		mock_run_idempotent.assert_called_once()
