from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.purchase_service import (
	create_purchase_invoice,
	create_purchase_invoice_from_receipt,
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

	@patch("myapp.services.purchase_service.resolve_item_quantity_to_stock")
	@patch("myapp.services.purchase_service._validate_warehouse_company")
	def test_build_purchase_order_item_applies_conversion_context(self, mock_validate_warehouse, mock_resolve_qty):
		from myapp.services.purchase_service import _build_purchase_order_item

		mock_resolve_qty.return_value = {
			"uom": "Case",
			"stock_uom": "Bottle",
			"conversion_factor": 24,
			"stock_qty": 48,
		}

		row = _build_purchase_order_item(
			{"item_code": "ITEM-001", "qty": 2, "warehouse": "Stores - TC", "uom": "Case", "price": 18},
			"2026-03-11",
			None,
			"Test Company",
		)

		self.assertEqual(row["uom"], "Case")
		self.assertEqual(row["stock_uom"], "Bottle")
		self.assertEqual(row["conversion_factor"], 24)
		self.assertEqual(row["stock_qty"], 48)
		self.assertEqual(row["rate"], 18)
		mock_validate_warehouse.assert_called_once()

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

	@patch("erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt")
	def test_receive_purchase_order_updates_qty_and_price(self, mock_make_purchase_receipt):
		item = frappe._dict({"item_code": "ITEM-001", "purchase_order_item": "POI-001", "qty": 1, "rate": 10})
		pr = frappe._dict({"items": [item], "name": "MAT-PRE-0001"})
		pr.get = lambda key: pr[key]
		mock_make_purchase_receipt.return_value = pr

		with patch("myapp.services.purchase_service._insert_and_submit"):
			result = receive_purchase_order(
				"PO-0001",
				receipt_items=[{"purchase_order_item": "POI-001", "qty": 3, "price": 18}],
			)

		self.assertEqual(item.qty, 3)
		self.assertEqual(item.rate, 18)
		self.assertEqual(result["purchase_receipt"], "MAT-PRE-0001")

	@patch("myapp.services.purchase_service.frappe.db.get_single_value", return_value=1)
	def test_receive_purchase_order_rejects_price_override_when_maintain_same_rate_enabled(self, mock_get_single):
		with self.assertRaisesRegex(frappe.ValidationError, "maintain_same_rate"):
			receive_purchase_order(
				"PO-0001",
				receipt_items=[{"item_code": "ITEM-001", "qty": 1, "price": 18}],
			)

	@patch("erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_invoice")
	def test_create_purchase_invoice_rejects_order_without_billable_items(self, mock_make_purchase_invoice):
		pi = frappe._dict({"items": []})
		mock_make_purchase_invoice.return_value = pi

		with self.assertRaisesRegex(frappe.ValidationError, "没有可开票的商品明细"):
			create_purchase_invoice("PO-0001")

	@patch("erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice")
	def test_create_purchase_invoice_from_receipt_rejects_receipt_without_billable_items(
		self, mock_make_purchase_invoice
	):
		pi = frappe._dict({"items": []})
		mock_make_purchase_invoice.return_value = pi

		with self.assertRaisesRegex(frappe.ValidationError, "没有可开票的商品明细"):
			create_purchase_invoice_from_receipt("MAT-PRE-0001")

	@patch("erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice")
	def test_create_purchase_invoice_from_receipt_updates_qty_and_price(self, mock_make_purchase_invoice):
		item = frappe._dict({"item_code": "ITEM-001", "pr_detail": "PRI-001", "qty": 1, "rate": 10})
		pi = frappe._dict({"items": [item], "name": "PINV-0002"})
		pi.get = lambda key: pi[key]
		mock_make_purchase_invoice.return_value = pi

		with patch("myapp.services.purchase_service._insert_and_submit"):
			result = create_purchase_invoice_from_receipt(
				"MAT-PRE-0001",
				invoice_items=[{"purchase_receipt_item": "PRI-001", "qty": 2, "price": 16}],
			)

		self.assertEqual(item.qty, 2)
		self.assertEqual(item.rate, 16)
		self.assertEqual(result["purchase_invoice"], "PINV-0002")

	@patch("myapp.services.purchase_service.frappe.db.get_single_value", return_value=1)
	def test_create_purchase_invoice_from_receipt_rejects_price_override_when_maintain_same_rate_enabled(
		self, mock_get_single
	):
		with self.assertRaisesRegex(frappe.ValidationError, "maintain_same_rate"):
			create_purchase_invoice_from_receipt(
				"MAT-PRE-0001",
				invoice_items=[{"item_code": "ITEM-001", "qty": 1, "price": 16}],
			)

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

	@patch("erpnext.controllers.sales_and_purchase_return.make_return_doc")
	def test_process_purchase_return_updates_qty_by_receipt_detail(self, mock_make_return_doc):
		item = frappe._dict(
			{
				"item_code": "ITEM-001",
				"purchase_receipt_item": "PRI-001",
				"pr_detail": "PRI-001",
				"qty": -3,
			}
		)
		return_doc = frappe._dict({"items": [item], "name": "MAT-PRE-RET-0002", "doctype": "Purchase Receipt"})
		return_doc.get = lambda key: return_doc[key]
		return_doc.insert = MagicMock()
		return_doc.submit = MagicMock()
		mock_make_return_doc.return_value = return_doc

		result = process_purchase_return(
			"Purchase Receipt",
			"MAT-PRE-0001",
			return_items=[{"purchase_receipt_item": "PRI-001", "qty": 1}],
		)

		self.assertEqual(item.qty, -1)
		self.assertEqual(result["return_document"], "MAT-PRE-RET-0002")

	@patch("erpnext.controllers.sales_and_purchase_return.make_return_doc")
	def test_process_purchase_return_updates_qty_by_invoice_detail(self, mock_make_return_doc):
		item = frappe._dict(
			{
				"item_code": "ITEM-001",
				"purchase_invoice_item": "PII-001",
				"pi_detail": "PII-001",
				"qty": -3,
			}
		)
		return_doc = frappe._dict({"items": [item], "name": "ACC-PINV-RET-0002", "doctype": "Purchase Invoice"})
		return_doc.get = lambda key: return_doc[key]
		return_doc.insert = MagicMock()
		return_doc.submit = MagicMock()
		mock_make_return_doc.return_value = return_doc

		result = process_purchase_return(
			"Purchase Invoice",
			"ACC-PINV-0001",
			return_items=[{"purchase_invoice_item": "PII-001", "qty": 2}],
		)

		self.assertEqual(item.qty, -2)
		self.assertEqual(result["return_document"], "ACC-PINV-RET-0002")

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
	def test_create_purchase_invoice_from_receipt_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {"status": "success", "purchase_invoice": "PINV-0020"}

		result = create_purchase_invoice_from_receipt("MAT-PRE-0001", kwargs={"request_id": "pi-pr-001"})

		self.assertEqual(result["purchase_invoice"], "PINV-0020")
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
