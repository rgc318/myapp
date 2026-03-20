import sys
from types import ModuleType
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.settlement_service import (
	cancel_payment_entry,
	confirm_pending_document,
	process_sales_return,
	update_payment_status,
)


class TestSettlementService(TestCase):
	@patch("myapp.services.settlement_service.frappe.get_doc")
	@patch("myapp.services.settlement_service.frappe.get_traceback", return_value="traceback")
	def test_confirm_pending_document_submits_draft(self, mock_traceback, mock_get_doc):
		doc = MagicMock()
		doc.doctype = "Sales Order"
		doc.name = "SO-0001"
		doc.docstatus = 0
		doc.get.return_value = None
		doc.submit.side_effect = lambda: setattr(doc, "docstatus", 1)
		mock_get_doc.return_value = doc

		result = confirm_pending_document("Sales Order", "SO-0001")

		doc.submit.assert_called_once()
		self.assertEqual(result["docstatus"], 1)
		self.assertEqual(result["docname"], "SO-0001")

	@patch("myapp.services.settlement_service.frappe.get_traceback", return_value="traceback")
	@patch("myapp.services.settlement_service.frappe.get_doc")
	@patch("frappe.model.workflow.apply_workflow")
	def test_confirm_pending_document_uses_workflow_action(
		self, mock_apply_workflow, mock_get_doc, mock_traceback
	):
		doc = MagicMock()
		doc.doctype = "ToDo"
		doc.name = "TD-0001"
		doc.docstatus = 0
		mock_get_doc.return_value = doc

		confirmed_doc = MagicMock()
		confirmed_doc.doctype = "ToDo"
		confirmed_doc.name = "TD-0001"
		confirmed_doc.docstatus = 1
		confirmed_doc.get.return_value = "Approved"
		mock_apply_workflow.return_value = confirmed_doc

		result = confirm_pending_document("ToDo", "TD-0001", action="Approve")

		mock_apply_workflow.assert_called_once_with(doc, "Approve")
		self.assertEqual(result["workflow_state"], "Approved")
		self.assertEqual(result["docstatus"], 1)

	@patch("myapp.services.settlement_service.frappe.get_traceback", return_value="traceback")
	@patch("myapp.services.settlement_service.frappe.get_attr")
	def test_process_sales_return_uses_erpnext_return_factory(self, mock_get_attr, mock_traceback):
		return_doc = MagicMock()
		return_doc.name = "SINV-RET-0001"
		return_doc.doctype = "Sales Invoice"
		return_doc.items = []
		mock_get_attr.return_value = MagicMock(return_value=return_doc)

		result = process_sales_return("Sales Invoice", "SINV-0001")

		mock_get_attr.assert_called_once_with(
			"erpnext.accounts.doctype.sales_invoice.sales_invoice.make_sales_return"
		)
		return_doc.insert.assert_called_once()
		return_doc.submit.assert_called_once()
		self.assertEqual(result["return_document"], "SINV-RET-0001")

	@patch("myapp.services.settlement_service.frappe.get_attr")
	def test_process_sales_return_updates_qty_by_invoice_detail(self, mock_get_attr):
		return_doc = frappe._dict(
			{
				"items": [
					frappe._dict(
						{
							"item_code": "ITEM-001",
							"sales_invoice_item": "SII-001",
							"si_detail": "SII-001",
							"qty": -3,
						}
					)
				],
				"name": "SINV-RET-0002",
				"doctype": "Sales Invoice",
			}
		)
		return_doc.insert = MagicMock()
		return_doc.submit = MagicMock()
		mock_get_attr.return_value = MagicMock(return_value=return_doc)

		result = process_sales_return(
			"Sales Invoice",
			"SINV-0001",
			return_items=[{"sales_invoice_item": "SII-001", "qty": 1}],
		)

		self.assertEqual(return_doc.items[0].qty, -1)
		self.assertEqual(result["return_document"], "SINV-RET-0002")

	@patch("myapp.services.settlement_service.frappe.get_attr")
	def test_process_sales_return_updates_qty_by_delivery_detail(self, mock_get_attr):
		return_doc = frappe._dict(
			{
				"items": [
					frappe._dict(
						{
							"item_code": "ITEM-001",
							"delivery_note_item": "DNI-001",
							"dn_detail": "DNI-001",
							"qty": -2,
						}
					)
				],
				"name": "DN-RET-0002",
				"doctype": "Delivery Note",
			}
		)
		return_doc.insert = MagicMock()
		return_doc.submit = MagicMock()
		mock_get_attr.return_value = MagicMock(return_value=return_doc)

		result = process_sales_return(
			"Delivery Note",
			"DN-0001",
			return_items=[{"delivery_note_item": "DNI-001", "qty": 1}],
		)

		self.assertEqual(return_doc.items[0].qty, -1)
		self.assertEqual(result["return_document"], "DN-RET-0002")

	@patch("myapp.services.settlement_service.frappe.get_traceback", return_value="traceback")
	@patch("erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry")
	def test_update_payment_status_creates_payment_entry(self, mock_get_payment_entry, mock_traceback):
		pe = MagicMock()
		pe.name = "ACC-PAY-0001"
		pe.mode_of_payment = None
		mock_get_payment_entry.return_value = pe

		result = update_payment_status("Sales Invoice", "SINV-0001", 120)

		mock_get_payment_entry.assert_called_once_with("Sales Invoice", "SINV-0001", party_amount=120.0)
		pe.insert.assert_called_once()
		pe.submit.assert_called_once()
		self.assertEqual(result["payment_entry"], "ACC-PAY-0001")

	def test_update_payment_status_supports_writeoff_settlement(self):
		pe = MagicMock()
		pe.name = "ACC-PAY-0002"
		pe.mode_of_payment = None
		pe.company = "rgc (Demo)"
		pe.difference_amount = 100

		fake_payment_entry_module = ModuleType("payment_entry")
		fake_get_payment_entry = MagicMock(return_value=pe)
		fake_payment_entry_module.get_payment_entry = fake_get_payment_entry

		with patch.dict(
			sys.modules,
			{"erpnext.accounts.doctype.payment_entry.payment_entry": fake_payment_entry_module},
		), patch.object(
			frappe,
			"db",
			MagicMock(get_value=MagicMock(return_value=1000)),
		), patch.object(
			frappe,
			"get_cached_value",
			return_value={
				"write_off_account": "Write Off - RD",
				"cost_center": "Main - RD",
			},
		):
			result = update_payment_status(
				"Sales Invoice",
				"SINV-0002",
				900,
				settlement_mode="writeoff",
				writeoff_reason="临时优惠结清",
				reference_date="2026-03-19",
			)

		fake_get_payment_entry.assert_called_once_with("Sales Invoice", "SINV-0002", party_amount=1000)
		pe.set_amounts.assert_called_once()
		pe.set_gain_or_loss.assert_called_once()
		self.assertEqual(result["payment_entry"], "ACC-PAY-0002")
		self.assertEqual(result["settlement_mode"], "writeoff")
		self.assertEqual(result["writeoff_amount"], 100)

	def test_update_payment_status_supports_unallocated_overpayment(self):
		pe = MagicMock()
		pe.name = "ACC-PAY-0003"
		pe.mode_of_payment = None
		pe.company = "rgc (Demo)"
		pe.unallocated_amount = 100

		fake_payment_entry_module = ModuleType("payment_entry")
		fake_get_payment_entry = MagicMock(return_value=pe)
		fake_payment_entry_module.get_payment_entry = fake_get_payment_entry

		with patch.dict(
			sys.modules,
			{"erpnext.accounts.doctype.payment_entry.payment_entry": fake_payment_entry_module},
		), patch.object(
			frappe,
			"db",
			MagicMock(get_value=MagicMock(return_value=1000)),
		):
			result = update_payment_status(
				"Sales Invoice",
				"SINV-0003",
				1100,
				reference_date="2026-03-19",
			)

		fake_get_payment_entry.assert_called_once_with("Sales Invoice", "SINV-0003", party_amount=1000)
		pe.set_amounts.assert_called_once()
		self.assertEqual(result["payment_entry"], "ACC-PAY-0003")
		self.assertEqual(result["unallocated_amount"], 100)

	@patch("myapp.services.settlement_service.run_idempotent")
	def test_update_payment_status_returns_cached_result_for_same_request_id(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {
			"status": "success",
			"payment_entry": "ACC-PAY-0099",
			"message": "cached",
		}

		result = update_payment_status("Sales Invoice", "SINV-0001", 120, request_id="pay-001")

		self.assertEqual(result["payment_entry"], "ACC-PAY-0099")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.settlement_service.run_idempotent")
	def test_process_sales_return_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {
			"status": "success",
			"return_document": "SINV-RET-0099",
			"return_doctype": "Sales Invoice",
		}

		result = process_sales_return("Sales Invoice", "SINV-0001", request_id="ret-001")

		self.assertEqual(result["return_document"], "SINV-RET-0099")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.settlement_service.frappe.get_doc")
	def test_cancel_payment_entry_cancels_submitted_payment(self, mock_get_doc):
		pe = MagicMock()
		pe.name = "ACC-PAY-0001"
		pe.docstatus = 1
		pe.get.return_value = [
			frappe._dict(
				{
					"reference_doctype": "Sales Invoice",
					"reference_name": "SINV-0001",
					"allocated_amount": 120,
				}
			)
		]
		mock_get_doc.return_value = pe

		result = cancel_payment_entry("ACC-PAY-0001")

		pe.cancel.assert_called_once()
		self.assertEqual(result["payment_entry"], "ACC-PAY-0001")
		self.assertEqual(result["document_status"], "cancelled")
		self.assertEqual(result["references"][0]["reference_name"], "SINV-0001")

	@patch("myapp.services.settlement_service.frappe.get_doc")
	def test_cancel_payment_entry_returns_idempotent_success_for_cancelled_doc(self, mock_get_doc):
		pe = MagicMock()
		pe.name = "ACC-PAY-0002"
		pe.docstatus = 2
		pe.get.return_value = []
		mock_get_doc.return_value = pe

		result = cancel_payment_entry("ACC-PAY-0002")

		pe.cancel.assert_not_called()
		self.assertEqual(result["document_status"], "cancelled")

	@patch("myapp.services.settlement_service.run_idempotent")
	def test_cancel_payment_entry_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {
			"status": "success",
			"payment_entry": "ACC-PAY-0099",
			"document_status": "cancelled",
		}

		result = cancel_payment_entry("ACC-PAY-0099", request_id="pay-cancel-001")

		self.assertEqual(result["payment_entry"], "ACC-PAY-0099")
		mock_run_idempotent.assert_called_once()
