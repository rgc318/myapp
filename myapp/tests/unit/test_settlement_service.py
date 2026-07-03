import sys
from types import ModuleType
from unittest import TestCase
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.settlement_service import (
	cancel_payment_entry,
	confirm_pending_document,
	create_customer_refund,
	create_supplier_refund,
	get_customer_refund_context,
	get_payment_entry_detail,
	get_supplier_refund_context,
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
		self.assertEqual(result["source_doctype"], "Sales Invoice")
		self.assertEqual(result["source_name"], "SINV-0001")
		self.assertEqual(result["business_type"], "sales")
		self.assertEqual(result["next_actions"]["suggested_next_action"], "review_refund")

	@patch("myapp.services.settlement_service.frappe.get_attr")
	def test_process_sales_return_updates_qty_by_invoice_detail(self, mock_get_attr):
		item = SimpleNamespace(
			item_code="ITEM-001",
			sales_invoice_item="SII-001",
			si_detail="SII-001",
			qty=-3,
		)
		return_doc = SimpleNamespace(
			items=[item],
			name="SINV-RET-0002",
			doctype="Sales Invoice",
			insert=MagicMock(),
			submit=MagicMock(),
		)
		mock_get_attr.return_value = MagicMock(return_value=return_doc)

		result = process_sales_return(
			"Sales Invoice",
			"SINV-0001",
			return_items=[{"sales_invoice_item": "SII-001", "qty": 1}],
		)

		self.assertEqual(item.qty, -1)
		self.assertEqual(result["return_document"], "SINV-RET-0002")
		self.assertTrue(result["summary"]["is_partial_return"])

	@patch("myapp.services.settlement_service.frappe.get_attr")
	def test_process_sales_return_updates_qty_by_delivery_detail(self, mock_get_attr):
		item = SimpleNamespace(
			item_code="ITEM-001",
			delivery_note_item="DNI-001",
			dn_detail="DNI-001",
			qty=-2,
		)
		return_doc = SimpleNamespace(
			items=[item],
			name="DN-RET-0002",
			doctype="Delivery Note",
			insert=MagicMock(),
			submit=MagicMock(),
		)
		mock_get_attr.return_value = MagicMock(return_value=return_doc)

		result = process_sales_return(
			"Delivery Note",
			"DN-0001",
			return_items=[{"delivery_note_item": "DNI-001", "qty": 1}],
		)

		self.assertEqual(item.qty, -1)
		self.assertEqual(result["return_document"], "DN-RET-0002")
		self.assertEqual(result["next_actions"]["suggested_next_action"], "view_return_document")

	@patch("myapp.services.settlement_service.frappe.get_traceback", return_value="traceback")
	@patch("myapp.services.settlement_service.nowdate", return_value="2026-03-26")
	@patch("myapp.services.settlement_service.frappe.log_error")
	@patch("erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry")
	def test_update_payment_status_creates_payment_entry(
		self, mock_get_payment_entry, _mock_log_error, _mock_nowdate, mock_traceback
	):
		pe = MagicMock()
		pe.name = "ACC-PAY-0001"
		pe.mode_of_payment = None
		mock_get_payment_entry.return_value = pe

		with patch.object(
			frappe,
			"db",
			MagicMock(get_value=MagicMock(return_value=120)),
		):
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

	def test_update_payment_status_caps_allocation_after_partial_return(self):
		pe = MagicMock()
		pe.name = "ACC-PAY-0004"
		pe.mode_of_payment = None
		pe.company = "rgc (Demo)"
		pe.unallocated_amount = 300

		fake_payment_entry_module = ModuleType("payment_entry")
		fake_get_payment_entry = MagicMock(return_value=pe)
		fake_payment_entry_module.get_payment_entry = fake_get_payment_entry
		invoice = frappe._dict(
			{
				"name": "SINV-0004",
				"is_return": 0,
				"docstatus": 1,
				"rounded_total": 1000,
				"grand_total": 1000,
				"outstanding_amount": 400,
			}
		)

		with patch.dict(
			sys.modules,
			{"erpnext.accounts.doctype.payment_entry.payment_entry": fake_payment_entry_module},
		), patch.object(
			frappe,
			"db",
			MagicMock(get_value=MagicMock(return_value=invoice)),
		), patch(
			"myapp.services.settlement_service.frappe.get_all",
			return_value=[
				frappe._dict(
					{
						"name": "SINV-RET-0004",
						"rounded_total": -300,
						"grand_total": -300,
					}
				)
			],
		):
			result = update_payment_status(
				"Sales Invoice",
				"SINV-0004",
				400,
				reference_date="2026-03-19",
			)

		fake_get_payment_entry.assert_called_once_with("Sales Invoice", "SINV-0004", party_amount=100.0)
		pe.set_amounts.assert_called_once()
		self.assertEqual(result["payment_entry"], "ACC-PAY-0004")
		self.assertEqual(result["unallocated_amount"], 300)

	@patch("myapp.services.settlement_service.frappe.throw")
	@patch("myapp.services.settlement_service.frappe.get_all")
	def test_update_payment_status_rejects_after_partial_return_when_net_outstanding_is_zero(
		self,
		mock_get_all,
		mock_throw,
	):
		mock_throw.side_effect = frappe.ValidationError
		mock_get_all.return_value = [
			frappe._dict(
				{
					"name": "SINV-RET-0005",
					"rounded_total": -300,
					"grand_total": -300,
				}
			)
		]
		invoice = frappe._dict(
			{
				"name": "SINV-0005",
				"is_return": 0,
				"docstatus": 1,
				"rounded_total": 1000,
				"grand_total": 1000,
				"outstanding_amount": 300,
			}
		)

		with patch.object(
			frappe,
			"db",
			MagicMock(get_value=MagicMock(return_value=invoice)),
		):
			with self.assertRaises(frappe.ValidationError):
				update_payment_status("Sales Invoice", "SINV-0005", 100)

		self.assertIn("当前没有可核销的未收金额", str(mock_throw.call_args[0][0]))

	@patch("myapp.services.settlement_service.frappe.throw")
	@patch("myapp.services.settlement_service.frappe.get_all")
	def test_update_payment_status_rejects_fully_returned_source_invoice(
		self,
		mock_get_all,
		mock_throw,
	):
		mock_throw.side_effect = frappe.ValidationError
		mock_get_all.return_value = [
			frappe._dict(
				{
					"name": "SINV-RET-0001",
					"rounded_total": -1000,
					"grand_total": -1000,
				}
			)
		]

		with patch.object(
			frappe,
			"db",
			MagicMock(
				get_value=MagicMock(
					return_value=frappe._dict(
						{
							"name": "SINV-0001",
							"is_return": 0,
							"docstatus": 1,
							"rounded_total": 1000,
							"grand_total": 1000,
						}
					)
				)
			),
		):
			with self.assertRaises(frappe.ValidationError):
				update_payment_status("Sales Invoice", "SINV-0001", 100)

		self.assertIn("全额冲回", str(mock_throw.call_args[0][0]))

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

	@patch("myapp.services.settlement_service._ensure_customer_receipt_cancel_allowed")
	@patch("myapp.services.settlement_service._get_invoice_reference_meta")
	@patch("myapp.services.settlement_service.frappe.get_doc")
	def test_cancel_payment_entry_cancels_submitted_payment(
		self,
		mock_get_doc,
		mock_get_invoice_reference_meta,
		mock_ensure_cancel_allowed,
	):
		mock_get_invoice_reference_meta.return_value = {"is_return": False, "return_against": None}
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

		mock_ensure_cancel_allowed.assert_called_once()
		pe.cancel.assert_called_once()
		self.assertEqual(result["payment_entry"], "ACC-PAY-0001")
		self.assertEqual(result["document_status"], "cancelled")
		self.assertEqual(result["references"][0]["reference_name"], "SINV-0001")
		self.assertFalse(result["references"][0]["is_return"])

	@patch("myapp.services.settlement_service.frappe.throw", side_effect=frappe.ValidationError)
	@patch(
		"myapp.services.settlement_service._get_customer_refund_entries_for_source_invoice",
		return_value=[{"payment_entry": "ACC-PAY-REF-0001", "allocated_amount": -100}],
	)
	def test_ensure_customer_receipt_cancel_rejects_when_refund_exists(
		self,
		_mock_refund_entries,
		mock_throw,
	):
		with self.assertRaises(frappe.ValidationError):
			from myapp.services.settlement_service import _ensure_customer_receipt_cancel_allowed

			_ensure_customer_receipt_cancel_allowed(
				MagicMock(name="ACC-PAY-0001"),
				[
					{
						"reference_doctype": "Sales Invoice",
						"reference_name": "SINV-0001",
						"is_return": False,
					}
				],
			)

		self.assertIn("已存在客户退款", str(mock_throw.call_args[0][0]))

	@patch("myapp.services.settlement_service._get_customer_refund_entries_for_source_invoice")
	def test_ensure_customer_receipt_cancel_allows_return_invoice_refund_cancellation(
		self,
		mock_refund_entries,
	):
		from myapp.services.settlement_service import _ensure_customer_receipt_cancel_allowed

		_ensure_customer_receipt_cancel_allowed(
			MagicMock(name="ACC-PAY-REF-0001"),
			[
				{
					"reference_doctype": "Sales Invoice",
					"reference_name": "SINV-RET-0001",
					"is_return": True,
					"return_against": "SINV-0001",
				}
			],
		)

		mock_refund_entries.assert_not_called()

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

	@patch("myapp.services.settlement_service.frappe.get_doc")
	def test_get_payment_entry_detail_returns_references_and_links(self, mock_get_doc):
		payment_entry = frappe._dict(
			{
				"name": "ACC-PAY-0001",
				"company": "Test Company",
				"posting_date": "2026-06-25",
				"docstatus": 1,
				"payment_type": "Receive",
				"party_type": "Customer",
				"party": "CUST-0001",
				"party_name": "Test Customer",
				"mode_of_payment": "Bank",
				"paid_to_account_currency": "CNY",
				"paid_amount": 120,
				"received_amount": 120,
				"unallocated_amount": 20,
				"difference_amount": 0,
				"reference_no": "BANK-001",
				"reference_date": "2026-06-25",
				"remarks": "客户收款",
				"references": [
					frappe._dict(
						{
							"reference_doctype": "Sales Invoice",
							"reference_name": "SINV-0001",
							"total_amount": 100,
							"outstanding_amount": 0,
							"allocated_amount": 100,
							"exchange_rate": 1,
							"due_date": "2026-06-30",
							"account": "Debtors - TC",
						}
					)
				],
				"deductions": [
					frappe._dict(
						{
							"account": "Write Off - TC",
							"cost_center": "Main - TC",
							"amount": 5,
							"description": "抹零",
						}
					)
				],
			}
		)
		mock_get_doc.return_value = payment_entry

		with patch.object(
			frappe,
			"db",
			MagicMock(
				get_value=MagicMock(
					return_value={
						"is_return": 0,
						"return_against": None,
					}
				)
			),
		):
			result = get_payment_entry_detail("ACC-PAY-0001")

		data = result["data"]
		self.assertEqual(data["name"], "ACC-PAY-0001")
		self.assertEqual(data["direction"], "in")
		self.assertEqual(data["business_type"], "customer_receipt")
		self.assertEqual(data["currency"], "CNY")
		self.assertEqual(data["amount"], 120)
		self.assertTrue(data["actions"]["can_cancel"])
		self.assertEqual(data["references"][0]["reference_name"], "SINV-0001")
		self.assertEqual(data["deductions"][0]["amount"], 5)
		self.assertEqual(data["links"]["sales_invoices"], ["SINV-0001"])

	@patch("myapp.services.settlement_service.frappe.get_doc")
	def test_get_payment_entry_detail_detects_return_invoice_refund(self, mock_get_doc):
		payment_entry = frappe._dict(
			{
				"name": "ACC-PAY-REF-0001",
				"docstatus": 1,
				"payment_type": "Receive",
				"party_type": "Customer",
				"party": "CUST-0001",
				"received_amount": 40,
				"references": [
					frappe._dict(
						{
							"reference_doctype": "Sales Invoice",
							"reference_name": "SINV-RET-0001",
							"allocated_amount": 40,
						}
					)
				],
				"deductions": [],
			}
		)
		mock_get_doc.return_value = payment_entry

		with patch.object(
			frappe,
			"db",
			MagicMock(
				get_value=MagicMock(
					return_value={
						"is_return": 1,
						"return_against": "SINV-0001",
					}
				)
			),
		):
			result = get_payment_entry_detail("ACC-PAY-REF-0001")

		data = result["data"]
		self.assertEqual(data["business_type"], "customer_refund")
		self.assertEqual(data["links"]["return_invoices"], ["SINV-RET-0001"])
		self.assertEqual(data["links"]["sales_invoices"], ["SINV-0001"])

	@patch("myapp.services.settlement_service.frappe.get_doc")
	def test_get_payment_entry_detail_marks_cancelled_as_not_cancelable(self, mock_get_doc):
		payment_entry = frappe._dict(
			{
				"name": "ACC-PAY-0002",
				"docstatus": 2,
				"payment_type": "Pay",
				"party_type": "Supplier",
				"party": "SUP-0001",
				"paid_amount": 50,
				"references": [],
				"deductions": [],
			}
		)
		mock_get_doc.return_value = payment_entry

		result = get_payment_entry_detail("ACC-PAY-0002")

		self.assertEqual(result["data"]["document_status"], "cancelled")
		self.assertFalse(result["data"]["actions"]["can_cancel"])
		self.assertTrue(result["data"]["actions"]["cancel_hint"])

	@patch("myapp.services.settlement_service._get_customer_refundable_amount", return_value=100)
	@patch("myapp.services.settlement_service.frappe.get_doc")
	def test_create_customer_refund_creates_payment_entry_for_return_invoice(self, mock_get_doc, _mock_refundable):
		return_invoice = frappe._dict(
			{
				"name": "SINV-RET-0001",
				"docstatus": 1,
				"is_return": 1,
				"grand_total": -100,
				"outstanding_amount": -100,
				"return_against": "SINV-0001",
			}
		)
		mock_get_doc.return_value = return_invoice

		pe = MagicMock()
		pe.name = "ACC-PAY-REF-0001"
		pe.mode_of_payment = None
		pe.references = [
			frappe._dict(
				{
					"reference_doctype": "Sales Invoice",
					"reference_name": "SINV-RET-0001",
					"total_amount": 100,
					"outstanding_amount": 100,
					"allocated_amount": 80,
				}
			)
		]

		fake_payment_entry_module = ModuleType("payment_entry")
		fake_get_payment_entry = MagicMock(return_value=pe)
		fake_payment_entry_module.get_payment_entry = fake_get_payment_entry

		with patch.dict(
			sys.modules,
			{"erpnext.accounts.doctype.payment_entry.payment_entry": fake_payment_entry_module},
		), patch("myapp.services.settlement_service.nowdate", return_value="2026-04-01"):
			result = create_customer_refund(
				"SINV-RET-0001",
				80,
				mode_of_payment="Bank",
				reference_no="REF-001",
				remarks="客户退货退款",
			)

		fake_get_payment_entry.assert_called_once_with(
			"Sales Invoice",
			"SINV-RET-0001",
			party_amount=80.0,
		)
		pe.insert.assert_called_once()
		pe.submit.assert_called_once()
		self.assertEqual(pe.mode_of_payment, "Bank")
		self.assertEqual(pe.reference_no, "REF-001")
		self.assertEqual(pe.reference_date, "2026-04-01")
		self.assertEqual(pe.remarks, "客户退货退款")
		self.assertEqual(pe.references[0].total_amount, -100)
		self.assertEqual(pe.references[0].outstanding_amount, -100)
		self.assertEqual(pe.references[0].allocated_amount, -80)
		self.assertEqual(result["payment_entry"], "ACC-PAY-REF-0001")
		self.assertEqual(result["refund_amount"], 80.0)
		self.assertEqual(result["return_invoice"], "SINV-RET-0001")
		self.assertEqual(result["source_invoice"], "SINV-0001")

	@patch("myapp.services.settlement_service.frappe.throw", side_effect=frappe.ValidationError)
	@patch("myapp.services.settlement_service.frappe.get_doc")
	def test_create_customer_refund_rejects_normal_sales_invoice(self, mock_get_doc, _mock_throw):
		mock_get_doc.return_value = frappe._dict(
			{
				"name": "SINV-0001",
				"docstatus": 1,
				"is_return": 0,
				"outstanding_amount": 100,
			}
		)

		with self.assertRaises(frappe.ValidationError):
			create_customer_refund("SINV-0001", 10)

	@patch("myapp.services.settlement_service._get_customer_refundable_amount", return_value=50)
	@patch("myapp.services.settlement_service.frappe.throw", side_effect=frappe.ValidationError)
	@patch("myapp.services.settlement_service.frappe.get_doc")
	def test_create_customer_refund_rejects_over_refund(self, mock_get_doc, _mock_throw, _mock_refundable):
		mock_get_doc.return_value = frappe._dict(
			{
				"name": "SINV-RET-0002",
				"docstatus": 1,
				"is_return": 1,
				"outstanding_amount": -50,
			}
		)

		with self.assertRaises(frappe.ValidationError):
			create_customer_refund("SINV-RET-0002", 60)

	@patch("myapp.services.settlement_service.run_idempotent")
	def test_create_customer_refund_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {
			"status": "success",
			"payment_entry": "ACC-PAY-REF-0099",
		}

		result = create_customer_refund("SINV-RET-0099", 20, request_id="refund-001")

		self.assertEqual(result["payment_entry"], "ACC-PAY-REF-0099")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.order_service._collect_sales_invoice_payment_entries")
	@patch("myapp.services.settlement_service.frappe.get_all")
	@patch("myapp.services.settlement_service.frappe.get_doc")
	def test_get_customer_refund_context_returns_refundable_amount_and_history(
		self,
		mock_get_doc,
		mock_get_all,
		mock_collect_payment_entries,
	):
		return_invoice = frappe._dict(
			{
				"name": "SINV-RET-0001",
				"docstatus": 1,
				"is_return": 1,
				"return_against": "SINV-0001",
				"customer": "CUST-0001",
				"customer_name": "Test Customer",
				"company": "Test Company",
				"currency": "CNY",
				"posting_date": "2026-06-22",
				"grand_total": -100,
				"outstanding_amount": -40,
			}
		)
		source_invoice = frappe._dict(
			{
				"name": "SINV-0001",
				"docstatus": 1,
				"is_return": 0,
				"customer": "CUST-0001",
				"customer_name": "Test Customer",
				"company": "Test Company",
				"currency": "CNY",
				"posting_date": "2026-06-20",
				"grand_total": 100,
				"outstanding_amount": 0,
			}
		)
		mock_get_doc.side_effect = [return_invoice, source_invoice]
		mock_get_all.return_value = [frappe._dict({"name": "SINV-RET-0001"})]

		def fake_collect_entries(invoice_names):
			if invoice_names == ["SINV-RET-0001"]:
				return [
					{
						"payment_entry": "ACC-PAY-REF-0001",
						"allocated_amount": 60,
						"posting_date": "2026-06-22",
					}
				]
			if invoice_names == ["SINV-0001"]:
				return [{"payment_entry": "ACC-PAY-0001", "allocated_amount": 100, "actual_paid_amount": 100}]
			return []

		mock_collect_payment_entries.side_effect = fake_collect_entries

		result = get_customer_refund_context("SINV-RET-0001")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["return_invoice"]["name"], "SINV-RET-0001")
		self.assertEqual(result["data"]["source_invoice"]["name"], "SINV-0001")
		self.assertEqual(result["data"]["refund"]["return_amount"], 100)
		self.assertEqual(result["data"]["refund"]["refunded_amount"], 60)
		self.assertEqual(result["data"]["refund"]["refundable_amount"], 40)
		self.assertEqual(result["data"]["refund"]["suggested_refund_amount"], 40)
		self.assertEqual(result["data"]["refund"]["status"], "partial_refunded")
		self.assertTrue(result["data"]["actions"]["can_create_refund"])
		self.assertEqual(result["data"]["entries"][0]["payment_entry"], "ACC-PAY-REF-0001")

	@patch("myapp.services.order_service._collect_sales_invoice_payment_entries")
	@patch("myapp.services.settlement_service.frappe.get_all")
	@patch("myapp.services.settlement_service.frappe.get_doc")
	def test_get_customer_refund_context_caps_refund_to_actual_source_receipt(
		self,
		mock_get_doc,
		mock_get_all,
		mock_collect_payment_entries,
	):
		return_invoice = frappe._dict(
			{
				"name": "SINV-RET-0002",
				"docstatus": 1,
				"is_return": 1,
				"return_against": "SINV-0002",
				"customer": "CUST-0001",
				"company": "Test Company",
				"currency": "CNY",
				"grand_total": -5012,
				"outstanding_amount": -5012,
			}
		)
		source_invoice = frappe._dict(
			{
				"name": "SINV-0002",
				"docstatus": 1,
				"is_return": 0,
				"customer": "CUST-0001",
				"company": "Test Company",
				"currency": "CNY",
				"grand_total": 5012,
				"outstanding_amount": 2012,
			}
		)
		mock_get_doc.side_effect = [return_invoice, source_invoice]
		mock_get_all.return_value = [frappe._dict({"name": "SINV-RET-0002"})]

		def fake_collect_entries(invoice_names):
			if invoice_names == ["SINV-0002"]:
				return [
					{"payment_entry": "ACC-PAY-0001", "allocated_amount": 1000, "actual_paid_amount": 1000},
					{"payment_entry": "ACC-PAY-0002", "allocated_amount": 2000, "actual_paid_amount": 2000},
				]
			return []

		mock_collect_payment_entries.side_effect = fake_collect_entries

		result = get_customer_refund_context("SINV-RET-0002")

		self.assertEqual(result["data"]["refund"]["return_amount"], 5012)
		self.assertEqual(result["data"]["refund"]["refundable_amount"], 3000)
		self.assertEqual(result["data"]["refund"]["suggested_refund_amount"], 3000)
		self.assertTrue(result["data"]["actions"]["can_create_refund"])

	@patch("myapp.services.order_service._collect_sales_invoice_payment_entries")
	@patch("myapp.services.settlement_service.frappe.get_all")
	@patch("myapp.services.settlement_service.frappe.get_doc")
	def test_get_customer_refund_context_blocks_refund_after_source_receipt_cancelled(
		self,
		mock_get_doc,
		mock_get_all,
		mock_collect_payment_entries,
	):
		return_invoice = frappe._dict(
			{
				"name": "SINV-RET-0003",
				"docstatus": 1,
				"is_return": 1,
				"return_against": "SINV-0003",
				"customer": "CUST-0001",
				"company": "Test Company",
				"currency": "CNY",
				"grand_total": -500,
				"outstanding_amount": -500,
			}
		)
		source_invoice = frappe._dict(
			{
				"name": "SINV-0003",
				"docstatus": 1,
				"is_return": 0,
				"customer": "CUST-0001",
				"company": "Test Company",
				"currency": "CNY",
				"grand_total": 500,
				"outstanding_amount": 500,
			}
		)
		mock_get_doc.side_effect = [return_invoice, source_invoice]
		mock_get_all.return_value = [frappe._dict({"name": "SINV-RET-0003"})]
		mock_collect_payment_entries.return_value = []

		result = get_customer_refund_context("SINV-RET-0003")

		self.assertEqual(result["data"]["refund"]["refundable_amount"], 0)
		self.assertEqual(result["data"]["refund"]["suggested_refund_amount"], 0)
		self.assertFalse(result["data"]["actions"]["can_create_refund"])
		self.assertIn("没有可退金额", result["data"]["actions"]["create_refund_hint"])

	@patch("myapp.services.order_service._collect_sales_invoice_payment_entries")
	@patch("myapp.services.settlement_service.frappe.get_all")
	def test_customer_refundable_amount_supports_partial_receipts_and_partial_refunds(
		self,
		mock_get_all,
		mock_collect_payment_entries,
	):
		from myapp.services.settlement_service import _get_customer_refundable_amount

		return_invoice = frappe._dict(
			{
				"name": "SINV-RET-0004",
				"return_against": "SINV-0004",
				"grand_total": -800,
				"outstanding_amount": -500,
			}
		)
		mock_get_all.return_value = [frappe._dict({"name": "SINV-RET-0004"})]

		def fake_collect_entries(invoice_names):
			if invoice_names == ["SINV-0004"]:
				return [
					{"payment_entry": "ACC-PAY-0001", "allocated_amount": 300, "actual_paid_amount": 300},
					{"payment_entry": "ACC-PAY-0002", "allocated_amount": 300, "actual_paid_amount": 300},
				]
			if invoice_names == ["SINV-RET-0004"]:
				return [{"payment_entry": "ACC-PAY-REF-0001", "allocated_amount": -300}]
			return []

		mock_collect_payment_entries.side_effect = fake_collect_entries

		self.assertEqual(_get_customer_refundable_amount(return_invoice), 300)

	@patch("myapp.services.order_service._collect_sales_invoice_payment_entries")
	@patch("myapp.services.settlement_service.frappe.get_all")
	def test_customer_refundable_amount_caps_across_multiple_return_invoices(
		self,
		mock_get_all,
		mock_collect_payment_entries,
	):
		from myapp.services.settlement_service import _get_customer_refundable_amount

		current_return_invoice = frappe._dict(
			{
				"name": "SINV-RET-0005-B",
				"return_against": "SINV-0005",
				"grand_total": -600,
				"outstanding_amount": -600,
			}
		)
		mock_get_all.return_value = [
			frappe._dict({"name": "SINV-RET-0005-A"}),
			frappe._dict({"name": "SINV-RET-0005-B"}),
		]

		def fake_collect_entries(invoice_names):
			if invoice_names == ["SINV-0005"]:
				return [{"payment_entry": "ACC-PAY-0001", "allocated_amount": 1000, "actual_paid_amount": 1000}]
			if invoice_names == ["SINV-RET-0005-B"]:
				return []
			if invoice_names == ["SINV-RET-0005-A", "SINV-RET-0005-B"]:
				return [{"payment_entry": "ACC-PAY-REF-0001", "allocated_amount": -700}]
			return []

		mock_collect_payment_entries.side_effect = fake_collect_entries

		self.assertEqual(_get_customer_refundable_amount(current_return_invoice), 300)

	@patch("myapp.services.order_service._collect_sales_invoice_payment_entries", return_value=[])
	@patch("myapp.services.settlement_service.frappe.get_doc")
	def test_get_customer_refund_context_rejects_normal_invoice(self, mock_get_doc, _mock_collect_entries):
		mock_get_doc.return_value = frappe._dict(
			{
				"name": "SINV-0001",
				"docstatus": 1,
				"is_return": 0,
				"grand_total": 100,
				"outstanding_amount": 100,
			}
		)

		result = get_customer_refund_context("SINV-0001")

		self.assertFalse(result["data"]["actions"]["can_create_refund"])
		self.assertEqual(result["data"]["refund"]["status"], "unavailable")

	@patch("myapp.services.settlement_service._get_supplier_refundable_amount", return_value=100)
	@patch("myapp.services.settlement_service.frappe.get_doc")
	def test_create_supplier_refund_creates_payment_entry_for_return_invoice(self, mock_get_doc, _mock_refundable):
		return_invoice = frappe._dict(
			{
				"name": "PINV-RET-0001",
				"docstatus": 1,
				"is_return": 1,
				"grand_total": -100,
				"outstanding_amount": -100,
				"return_against": "PINV-0001",
			}
		)
		mock_get_doc.return_value = return_invoice

		pe = MagicMock()
		pe.name = "ACC-PAY-SUP-REF-0001"
		pe.mode_of_payment = None
		pe.references = [
			frappe._dict(
				{
					"reference_doctype": "Purchase Invoice",
					"reference_name": "PINV-RET-0001",
					"total_amount": 100,
					"outstanding_amount": 100,
					"allocated_amount": 70,
				}
			)
		]

		fake_payment_entry_module = ModuleType("payment_entry")
		fake_get_payment_entry = MagicMock(return_value=pe)
		fake_payment_entry_module.get_payment_entry = fake_get_payment_entry

		with patch.dict(
			sys.modules,
			{"erpnext.accounts.doctype.payment_entry.payment_entry": fake_payment_entry_module},
		), patch("myapp.services.settlement_service.nowdate", return_value="2026-04-02"):
			result = create_supplier_refund(
				"PINV-RET-0001",
				70,
				mode_of_payment="Bank",
				reference_no="SUP-REF-001",
				remarks="供应商退货退款",
			)

		fake_get_payment_entry.assert_called_once_with(
			"Purchase Invoice",
			"PINV-RET-0001",
			party_amount=70.0,
		)
		pe.insert.assert_called_once()
		pe.submit.assert_called_once()
		self.assertEqual(pe.mode_of_payment, "Bank")
		self.assertEqual(pe.reference_no, "SUP-REF-001")
		self.assertEqual(pe.reference_date, "2026-04-02")
		self.assertEqual(pe.remarks, "供应商退货退款")
		self.assertEqual(pe.references[0].total_amount, -100)
		self.assertEqual(pe.references[0].outstanding_amount, -100)
		self.assertEqual(pe.references[0].allocated_amount, -70)
		self.assertEqual(result["payment_entry"], "ACC-PAY-SUP-REF-0001")
		self.assertEqual(result["refund_amount"], 70.0)
		self.assertEqual(result["return_invoice"], "PINV-RET-0001")
		self.assertEqual(result["source_invoice"], "PINV-0001")

	@patch("myapp.services.settlement_service.frappe.throw", side_effect=frappe.ValidationError)
	@patch("myapp.services.settlement_service.frappe.get_doc")
	def test_create_supplier_refund_rejects_normal_purchase_invoice(self, mock_get_doc, _mock_throw):
		mock_get_doc.return_value = frappe._dict(
			{
				"name": "PINV-0001",
				"docstatus": 1,
				"is_return": 0,
				"outstanding_amount": 100,
			}
		)

		with self.assertRaises(frappe.ValidationError):
			create_supplier_refund("PINV-0001", 10)

	@patch("myapp.services.settlement_service.run_idempotent")
	def test_create_supplier_refund_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {
			"status": "success",
			"payment_entry": "ACC-PAY-SUP-REF-0099",
		}

		result = create_supplier_refund("PINV-RET-0099", 20, request_id="supplier-refund-001")

		self.assertEqual(result["payment_entry"], "ACC-PAY-SUP-REF-0099")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.settlement_service._collect_purchase_invoice_payment_entries")
	@patch("myapp.services.settlement_service.frappe.get_all")
	@patch("myapp.services.settlement_service.frappe.get_doc")
	def test_get_supplier_refund_context_returns_refundable_amount_and_history(
		self,
		mock_get_doc,
		mock_get_all,
		mock_collect_payment_entries,
	):
		return_invoice = frappe._dict(
			{
				"name": "PINV-RET-0001",
				"docstatus": 1,
				"is_return": 1,
				"return_against": "PINV-0001",
				"supplier": "SUP-0001",
				"supplier_name": "Test Supplier",
				"company": "Test Company",
				"currency": "CNY",
				"posting_date": "2026-06-22",
				"grand_total": -100,
				"outstanding_amount": -40,
			}
		)
		source_invoice = frappe._dict(
			{
				"name": "PINV-0001",
				"docstatus": 1,
				"is_return": 0,
				"supplier": "SUP-0001",
				"supplier_name": "Test Supplier",
				"company": "Test Company",
				"currency": "CNY",
				"posting_date": "2026-06-20",
				"grand_total": 100,
				"outstanding_amount": 0,
			}
		)
		mock_get_doc.side_effect = [return_invoice, source_invoice]
		mock_get_all.return_value = [frappe._dict({"name": "PINV-RET-0001"})]

		def fake_collect_entries(invoice_names):
			if invoice_names == ["PINV-RET-0001"]:
				return [
					{
						"payment_entry": "ACC-PAY-SUP-REF-0001",
						"allocated_amount": 60,
						"posting_date": "2026-06-22",
					}
				]
			if invoice_names == ["PINV-0001"]:
				return [{"payment_entry": "ACC-PAY-SUP-0001", "allocated_amount": 100}]
			return []

		mock_collect_payment_entries.side_effect = fake_collect_entries

		result = get_supplier_refund_context("PINV-RET-0001")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["return_invoice"]["name"], "PINV-RET-0001")
		self.assertEqual(result["data"]["source_invoice"]["name"], "PINV-0001")
		self.assertEqual(result["data"]["refund"]["return_amount"], 100)
		self.assertEqual(result["data"]["refund"]["refunded_amount"], 60)
		self.assertEqual(result["data"]["refund"]["refundable_amount"], 40)
		self.assertEqual(result["data"]["refund"]["suggested_refund_amount"], 40)
		self.assertEqual(result["data"]["refund"]["status"], "partial_refunded")
		self.assertTrue(result["data"]["actions"]["can_create_refund"])
		self.assertEqual(result["data"]["entries"][0]["payment_entry"], "ACC-PAY-SUP-REF-0001")
