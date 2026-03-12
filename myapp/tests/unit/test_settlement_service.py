from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.settlement_service import (
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
