from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.purchase_service import (
	create_supplier_v2,
	create_purchase_invoice,
	create_purchase_invoice_from_receipt,
	create_purchase_order,
	disable_supplier_v2,
	get_supplier_detail_v2,
	get_supplier_purchase_context,
	get_purchase_invoice_detail_v2,
	get_purchase_order_detail_v2,
	get_purchase_order_status_summary,
	get_purchase_receipt_detail_v2,
	list_suppliers_v2,
	process_purchase_return,
	quick_cancel_purchase_order_v2,
	quick_create_purchase_order_v2,
	receive_purchase_order,
	record_supplier_payment,
	search_purchase_orders_v2,
	update_supplier_v2,
)


class TestPurchaseService(TestCase):
	@patch("myapp.services.purchase_service.frappe.get_all")
	def test_get_latest_purchase_payment_entry_summary_returns_actual_paid_and_writeoff(self, mock_get_all):
		from myapp.services.purchase_service import _get_latest_purchase_payment_entry_summary

		mock_get_all.side_effect = [
			[
				frappe._dict(
					{
						"parent": "ACC-PAY-0001",
						"reference_name": "ACC-PINV-0001",
						"allocated_amount": 9460,
						"modified": "2026-03-20 10:00:00",
					}
				)
			],
			[
				frappe._dict(
					{
						"name": "ACC-PAY-0001",
						"paid_amount": 9046,
						"received_amount": 9046,
						"unallocated_amount": 0,
						"difference_amount": 414,
						"modified": "2026-03-20 10:00:00",
					}
				)
			],
		]

		result = _get_latest_purchase_payment_entry_summary(["ACC-PINV-0001"])

		self.assertEqual(result["payment_entry"], "ACC-PAY-0001")
		self.assertEqual(result["invoice_name"], "ACC-PINV-0001")
		self.assertEqual(result["writeoff_amount"], 414)
		self.assertEqual(result["actual_paid_amount"], 9046)
		self.assertEqual(result["total_actual_paid_amount"], 9046)
		self.assertEqual(result["total_writeoff_amount"], 414)

	@patch(
		"myapp.services.purchase_service._validate_warehouse_company",
		side_effect=frappe.ValidationError("cross-company"),
	)
	def test_build_purchase_order_item_rejects_cross_company_warehouse(self, mock_validate_warehouse):
		from myapp.services.purchase_service import _build_purchase_order_item

		with self.assertRaises(frappe.ValidationError):
			_build_purchase_order_item(
				{"item_code": "ITEM-001", "qty": 1, "warehouse": "Stores - OC"},
				"2026-03-11",
				None,
				"Test Company",
			)
		mock_validate_warehouse.assert_called_once_with("Stores - OC", "Test Company", "ITEM-001")

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

	@patch("myapp.services.purchase_service._build_purchase_order_item")
	@patch("myapp.services.purchase_service._insert_and_submit")
	@patch("myapp.services.purchase_service.frappe.new_doc")
	@patch("myapp.services.purchase_service.nowdate", return_value="2026-03-26")
	@patch("myapp.services.purchase_service.frappe.defaults.get_user_default")
	def test_create_purchase_order_builds_and_submits_document(
		self, mock_get_user_default, mock_nowdate, mock_new_doc, mock_insert_and_submit, mock_build_purchase_order_item
	):
		mock_get_user_default.return_value = "Test Company"
		po = MagicMock()
		po.name = "PO-0001"
		mock_new_doc.return_value = po
		mock_build_purchase_order_item.return_value = {"item_code": "ITEM-001", "qty": 2, "warehouse": "Stores - TC"}

		result = create_purchase_order(
			supplier="Test Supplier",
			items=[{"item_code": "ITEM-001", "qty": 2, "warehouse": "Stores - TC"}],
		)

		mock_new_doc.assert_called_once_with("Purchase Order")
		self.assertEqual(result["purchase_order"], "PO-0001")
		mock_insert_and_submit.assert_called_once_with(po)
		po.append.assert_called_once()

	@patch("myapp.services.purchase_service.nowdate", return_value="2026-03-26")
	@patch(
		"myapp.services.purchase_service.frappe.throw",
		side_effect=frappe.ValidationError("无法创建空采购订单，请至少选择一个商品。"),
	)
	def test_create_purchase_order_rejects_empty_items(self, mock_throw, mock_nowdate):
		with self.assertRaises(frappe.ValidationError):
			create_purchase_order(supplier="Test Supplier", items=[], company="Test Company")
		mock_throw.assert_called_once()

	@patch(
		"myapp.services.purchase_service.frappe.throw",
		side_effect=frappe.ValidationError("采购订单 PO-0001 当前没有可收货的商品明细。"),
	)
	@patch("erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt")
	def test_receive_purchase_order_rejects_order_without_receivable_items(self, mock_make_purchase_receipt, mock_throw):
		pr = SimpleNamespace(items=[], get=lambda key, default=None: [] if key == "items" else default)
		mock_make_purchase_receipt.return_value = pr

		with self.assertRaisesRegex(frappe.ValidationError, "没有可收货的商品明细"):
			receive_purchase_order("PO-0001")

	@patch("myapp.services.purchase_service._validate_purchase_rate_override_allowed")
	@patch("erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt")
	def test_receive_purchase_order_updates_qty_and_price(self, mock_make_purchase_receipt, mock_validate_rate_override):
		item = SimpleNamespace(item_code="ITEM-001", purchase_order_item="POI-001", qty=1, rate=10)
		pr = SimpleNamespace(
			items=[item],
			name="MAT-PRE-0001",
			get=lambda key, default=None: [item] if key == "items" else getattr(pr, key, default),
		)
		mock_make_purchase_receipt.return_value = pr

		with patch("myapp.services.purchase_service._insert_and_submit"):
			result = receive_purchase_order(
				"PO-0001",
				receipt_items=[{"purchase_order_item": "POI-001", "qty": 3, "price": 18}],
			)

		self.assertEqual(item.qty, 3)
		self.assertEqual(item.rate, 18)
		self.assertEqual(result["purchase_receipt"], "MAT-PRE-0001")

	@patch(
		"myapp.services.purchase_service._validate_purchase_rate_override_allowed",
		side_effect=frappe.ValidationError("maintain_same_rate"),
	)
	@patch("erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt")
	def test_receive_purchase_order_rejects_price_override_when_maintain_same_rate_enabled(
		self, mock_make_purchase_receipt, mock_validate_rate_override
	):
		item = SimpleNamespace(item_code="ITEM-001", purchase_order_item="POI-001", qty=1, rate=10)
		pr = SimpleNamespace(
			items=[item],
			name="MAT-PRE-0001",
			get=lambda key, default=None: [item] if key == "items" else getattr(pr, key, default),
		)
		mock_make_purchase_receipt.return_value = pr

		with self.assertRaisesRegex(frappe.ValidationError, "maintain_same_rate"):
			receive_purchase_order(
				"PO-0001",
				receipt_items=[{"item_code": "ITEM-001", "qty": 1, "price": 18}],
			)

	@patch(
		"myapp.services.purchase_service.frappe.throw",
		side_effect=frappe.ValidationError("采购订单 PO-0001 当前没有可开票的商品明细。"),
	)
	@patch("erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_invoice")
	def test_create_purchase_invoice_rejects_order_without_billable_items(self, mock_make_purchase_invoice, mock_throw):
		pi = SimpleNamespace(items=[], get=lambda key, default=None: [] if key == "items" else default)
		mock_make_purchase_invoice.return_value = pi

		with self.assertRaisesRegex(frappe.ValidationError, "没有可开票的商品明细"):
			create_purchase_invoice("PO-0001")

	@patch(
		"myapp.services.purchase_service.frappe.throw",
		side_effect=frappe.ValidationError("采购收货单 MAT-PRE-0001 当前没有可开票的商品明细。"),
	)
	@patch("erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice")
	def test_create_purchase_invoice_from_receipt_rejects_receipt_without_billable_items(
		self, mock_make_purchase_invoice, mock_throw
	):
		pi = SimpleNamespace(items=[], get=lambda key, default=None: [] if key == "items" else default)
		mock_make_purchase_invoice.return_value = pi

		with self.assertRaisesRegex(frappe.ValidationError, "没有可开票的商品明细"):
			create_purchase_invoice_from_receipt("MAT-PRE-0001")

	@patch("myapp.services.purchase_service._validate_purchase_rate_override_allowed")
	@patch("erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice")
	def test_create_purchase_invoice_from_receipt_updates_qty_and_price(
		self, mock_make_purchase_invoice, mock_validate_rate_override
	):
		item = SimpleNamespace(item_code="ITEM-001", pr_detail="PRI-001", qty=1, rate=10)
		pi = SimpleNamespace(
			items=[item],
			name="PINV-0002",
			get=lambda key, default=None: [item] if key == "items" else getattr(pi, key, default),
		)
		mock_make_purchase_invoice.return_value = pi

		with patch("myapp.services.purchase_service._insert_and_submit"):
			result = create_purchase_invoice_from_receipt(
				"MAT-PRE-0001",
				invoice_items=[{"purchase_receipt_item": "PRI-001", "qty": 2, "price": 16}],
			)

		self.assertEqual(item.qty, 2)
		self.assertEqual(item.rate, 16)
		self.assertEqual(result["purchase_invoice"], "PINV-0002")

	@patch(
		"myapp.services.purchase_service._validate_purchase_rate_override_allowed",
		side_effect=frappe.ValidationError("maintain_same_rate"),
	)
	@patch("erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice")
	def test_create_purchase_invoice_from_receipt_rejects_price_override_when_maintain_same_rate_enabled(
		self, mock_make_purchase_invoice, mock_validate_rate_override
	):
		item = SimpleNamespace(item_code="ITEM-001", pr_detail="PRI-001", qty=1, rate=10)
		pi = SimpleNamespace(
			items=[item],
			name="PINV-0002",
			get=lambda key, default=None: [item] if key == "items" else getattr(pi, key, default),
		)
		mock_make_purchase_invoice.return_value = pi

		with self.assertRaisesRegex(frappe.ValidationError, "maintain_same_rate"):
			create_purchase_invoice_from_receipt(
				"MAT-PRE-0001",
				invoice_items=[{"item_code": "ITEM-001", "qty": 1, "price": 16}],
			)

	@patch("myapp.services.purchase_service.nowdate", return_value="2026-03-26")
	@patch("erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry")
	def test_record_supplier_payment_creates_payment_entry(self, mock_get_payment_entry, mock_nowdate):
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
		self.assertEqual(result["source_doctype"], "Purchase Receipt")
		self.assertEqual(result["source_name"], "MAT-PRE-0001")
		self.assertEqual(result["business_type"], "purchase")
		self.assertEqual(result["next_actions"]["suggested_next_action"], "view_return_document")

	@patch("erpnext.controllers.sales_and_purchase_return.make_return_doc")
	def test_process_purchase_return_updates_qty_by_receipt_detail(self, mock_make_return_doc):
		item = SimpleNamespace(item_code="ITEM-001", purchase_receipt_item="PRI-001", pr_detail="PRI-001", qty=-3)
		return_doc = SimpleNamespace(
			items=[item],
			name="MAT-PRE-RET-0002",
			doctype="Purchase Receipt",
			insert=MagicMock(),
			submit=MagicMock(),
		)
		return_doc.get = lambda key, default=None: getattr(return_doc, key, default)
		mock_make_return_doc.return_value = return_doc

		result = process_purchase_return(
			"Purchase Receipt",
			"MAT-PRE-0001",
			return_items=[{"purchase_receipt_item": "PRI-001", "qty": 1}],
		)

		self.assertEqual(item.qty, -1)
		self.assertEqual(result["return_document"], "MAT-PRE-RET-0002")
		self.assertTrue(result["summary"]["is_partial_return"])

	@patch("erpnext.controllers.sales_and_purchase_return.make_return_doc")
	def test_process_purchase_return_updates_qty_by_invoice_detail(self, mock_make_return_doc):
		item = SimpleNamespace(item_code="ITEM-001", purchase_invoice_item="PII-001", pi_detail="PII-001", qty=-3)
		return_doc = SimpleNamespace(
			items=[item],
			name="ACC-PINV-RET-0002",
			doctype="Purchase Invoice",
			insert=MagicMock(),
			submit=MagicMock(),
		)
		return_doc.get = lambda key, default=None: getattr(return_doc, key, default)
		mock_make_return_doc.return_value = return_doc

		result = process_purchase_return(
			"Purchase Invoice",
			"ACC-PINV-0001",
			return_items=[{"purchase_invoice_item": "PII-001", "qty": 2}],
		)

		self.assertEqual(item.qty, -2)
		self.assertEqual(result["return_document"], "ACC-PINV-RET-0002")
		self.assertEqual(result["next_actions"]["suggested_next_action"], "review_supplier_refund")

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

	@patch("myapp.services.purchase_service.run_idempotent", side_effect=lambda namespace, request_id, callback: callback())
	@patch("myapp.services.purchase_service.get_purchase_order_detail_v2")
	@patch("myapp.services.purchase_service.record_supplier_payment")
	@patch("myapp.services.purchase_service.create_purchase_invoice_from_receipt")
	@patch("myapp.services.purchase_service.receive_purchase_order")
	@patch("myapp.services.purchase_service.create_purchase_order")
	def test_quick_create_purchase_order_v2_runs_full_chain(
		self,
		mock_create_purchase_order,
		mock_receive_purchase_order,
		mock_create_purchase_invoice_from_receipt,
		mock_record_supplier_payment,
		mock_get_purchase_order_detail,
		mock_run_idempotent,
	):
		mock_create_purchase_order.return_value = {"status": "success", "purchase_order": "PO-0001"}
		mock_receive_purchase_order.return_value = {"status": "success", "purchase_receipt": "PR-0001"}
		mock_create_purchase_invoice_from_receipt.return_value = {
			"status": "success",
			"purchase_invoice": "PINV-0001",
		}
		mock_record_supplier_payment.return_value = {"status": "success", "payment_entry": "PAY-0001"}
		mock_get_purchase_order_detail.return_value = {"status": "success", "data": {"purchase_order_name": "PO-0001"}}

		result = quick_create_purchase_order_v2(
			supplier="SUP-001",
			items=[{"item_code": "ITEM-001", "qty": 2, "warehouse": "Stores - TC"}],
			immediate_payment=1,
			paid_amount=200,
			mode_of_payment="微信支付",
			reference_date="2026-04-01",
			request_id="quick-po-001",
		)

		self.assertEqual(result["purchase_order"], "PO-0001")
		self.assertEqual(result["purchase_receipt"], "PR-0001")
		self.assertEqual(result["purchase_invoice"], "PINV-0001")
		self.assertEqual(result["payment_entry"], "PAY-0001")
		self.assertEqual(
			result["completed_steps"],
			["purchase_order", "purchase_receipt", "purchase_invoice", "payment_entry"],
		)
		self.assertFalse(result["detail_included"])
		self.assertIsNone(result["detail"])
		mock_receive_purchase_order.assert_called_once()
		mock_create_purchase_invoice_from_receipt.assert_called_once()
		mock_record_supplier_payment.assert_called_once_with(
			"PINV-0001",
			paid_amount=200,
			mode_of_payment="微信支付",
			reference_no=None,
			reference_date="2026-04-01",
			request_id="quick-po-001",
		)
		mock_run_idempotent.assert_called_once()
		mock_get_purchase_order_detail.assert_not_called()

	@patch("myapp.services.purchase_service.run_idempotent", side_effect=lambda namespace, request_id, callback: callback())
	@patch("myapp.services.purchase_service.get_purchase_order_detail_v2")
	@patch("myapp.services.purchase_service.record_supplier_payment")
	@patch("myapp.services.purchase_service.create_purchase_invoice_from_receipt")
	@patch("myapp.services.purchase_service.receive_purchase_order")
	@patch("myapp.services.purchase_service.create_purchase_order")
	def test_quick_create_purchase_order_v2_can_include_detail_when_requested(
		self,
		mock_create_purchase_order,
		mock_receive_purchase_order,
		mock_create_purchase_invoice_from_receipt,
		mock_record_supplier_payment,
		mock_get_purchase_order_detail,
		mock_run_idempotent,
	):
		mock_create_purchase_order.return_value = {"status": "success", "purchase_order": "PO-0002"}
		mock_receive_purchase_order.return_value = {"status": "success", "purchase_receipt": "PR-0002"}
		mock_create_purchase_invoice_from_receipt.return_value = {
			"status": "success",
			"purchase_invoice": "PINV-0002",
		}
		mock_record_supplier_payment.return_value = {"status": "success", "payment_entry": "PAY-0002"}
		mock_get_purchase_order_detail.return_value = {"status": "success", "data": {"purchase_order_name": "PO-0002"}}

		result = quick_create_purchase_order_v2(
			supplier="SUP-001",
			items=[{"item_code": "ITEM-001", "qty": 2, "warehouse": "Stores - TC"}],
			immediate_payment=1,
			paid_amount=200,
			include_detail=1,
		)

		self.assertTrue(result["detail_included"])
		self.assertEqual(result["detail"]["purchase_order_name"], "PO-0002")
		mock_get_purchase_order_detail.assert_called_once_with("PO-0002")

	@patch("myapp.services.purchase_service.run_idempotent", side_effect=lambda namespace, request_id, callback: callback())
	@patch("myapp.services.purchase_service.get_purchase_order_detail_v2")
	@patch("myapp.services.purchase_service.cancel_purchase_receipt_v2")
	@patch("myapp.services.purchase_service.cancel_purchase_invoice_v2")
	@patch("myapp.services.purchase_service.cancel_supplier_payment")
	@patch("myapp.services.purchase_service._collect_submitted_supplier_payment_entry_summaries")
	@patch("myapp.services.purchase_service._collect_purchase_order_reference_names")
	@patch("myapp.services.purchase_service._get_purchase_order_doc_for_update")
	def test_quick_cancel_purchase_order_v2_runs_reverse_chain(
		self,
		mock_get_purchase_order_doc_for_update,
		mock_collect_purchase_refs,
		mock_collect_payments,
		mock_cancel_supplier_payment,
		mock_cancel_purchase_invoice,
		mock_cancel_purchase_receipt,
		mock_get_purchase_order_detail,
		mock_run_idempotent,
	):
		mock_get_purchase_order_doc_for_update.return_value = frappe._dict({"name": "PO-0001"})
		mock_collect_purchase_refs.return_value = (["PR-0001"], ["PINV-0001"])
		mock_collect_payments.return_value = [
			{
				"payment_entry": "PAY-0001",
				"references": [
					{
						"reference_doctype": "Purchase Invoice",
						"reference_name": "PINV-0001",
						"allocated_amount": 200,
					}
				],
			}
		]
		mock_cancel_supplier_payment.return_value = {"status": "success", "payment_entry": "PAY-0001"}
		mock_cancel_purchase_invoice.return_value = {"status": "success", "purchase_invoice": "PINV-0001"}
		mock_cancel_purchase_receipt.return_value = {"status": "success", "purchase_receipt": "PR-0001"}
		mock_get_purchase_order_detail.return_value = {"status": "success", "data": {"purchase_order_name": "PO-0001"}}

		result = quick_cancel_purchase_order_v2("PO-0001", request_id="quick-cancel-001")

		self.assertEqual(result["purchase_order"], "PO-0001")
		self.assertEqual(result["cancelled_payment_entries"], ["PAY-0001"])
		self.assertEqual(result["cancelled_purchase_invoice"], "PINV-0001")
		self.assertEqual(result["cancelled_purchase_receipt"], "PR-0001")
		self.assertEqual(
			result["completed_steps"],
			["payment_entry", "purchase_invoice", "purchase_receipt"],
		)
		self.assertFalse(result["detail_included"])
		self.assertIsNone(result["detail"])
		mock_get_purchase_order_detail.assert_not_called()
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.purchase_service.run_idempotent", side_effect=lambda namespace, request_id, callback: callback())
	@patch(
		"myapp.services.purchase_service._collect_submitted_supplier_payment_entry_summaries",
		return_value=[{"payment_entry": "PAY-0001", "references": []}],
	)
	@patch(
		"myapp.services.purchase_service._collect_purchase_order_reference_names",
		return_value=(["PR-0001"], ["PINV-0001"]),
	)
	@patch("myapp.services.purchase_service._get_purchase_order_doc_for_update")
	def test_quick_cancel_purchase_order_v2_rejects_when_payment_rollback_disabled(
		self,
		mock_get_purchase_order_doc_for_update,
		mock_collect_purchase_refs,
		mock_collect_payments,
		mock_run_idempotent,
	):
		mock_get_purchase_order_doc_for_update.return_value = frappe._dict({"name": "PO-0001"})

		with patch(
			"myapp.services.purchase_service.frappe.throw",
			side_effect=frappe.ValidationError("采购订单 PO-0001 当前存在有效付款，快捷作废要求先回退付款。"),
		):
			with self.assertRaisesRegex(frappe.ValidationError, "先回退付款"):
				quick_cancel_purchase_order_v2("PO-0001", rollback_payment=False)

		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.purchase_service.run_idempotent", side_effect=lambda namespace, request_id, callback: callback())
	@patch("myapp.services.purchase_service.get_purchase_order_detail_v2")
	@patch("myapp.services.purchase_service.cancel_purchase_receipt_v2")
	@patch("myapp.services.purchase_service.cancel_purchase_invoice_v2")
	@patch("myapp.services.purchase_service.cancel_supplier_payment")
	@patch("myapp.services.purchase_service._collect_submitted_supplier_payment_entry_summaries")
	@patch("myapp.services.purchase_service._collect_purchase_order_reference_names")
	@patch("myapp.services.purchase_service._get_purchase_order_doc_for_update")
	def test_quick_cancel_purchase_order_v2_recovers_after_invoice_cancel_failure(
		self,
		mock_get_purchase_order_doc_for_update,
		mock_collect_purchase_refs,
		mock_collect_payments,
		mock_cancel_supplier_payment,
		mock_cancel_purchase_invoice,
		mock_cancel_purchase_receipt,
		mock_get_purchase_order_detail,
		mock_run_idempotent,
	):
		mock_get_purchase_order_doc_for_update.return_value = frappe._dict({"name": "PO-0001"})
		mock_collect_purchase_refs.return_value = (["PR-0001"], ["PINV-0001"])
		mock_collect_payments.side_effect = [
			[
				{
					"payment_entry": "PAY-0001",
					"references": [
						{
							"reference_doctype": "Purchase Invoice",
							"reference_name": "PINV-0001",
						}
					],
				}
			],
			[],
		]
		mock_cancel_supplier_payment.return_value = {"status": "success", "payment_entry": "PAY-0001"}
		mock_cancel_purchase_invoice.side_effect = [
			frappe.ValidationError("invoice-cancel-failed"),
			{"status": "success", "purchase_invoice": "PINV-0001"},
		]
		mock_cancel_purchase_receipt.return_value = {"status": "success", "purchase_receipt": "PR-0001"}
		mock_get_purchase_order_detail.return_value = {"status": "success", "data": {"purchase_order_name": "PO-0001"}}

		with self.assertRaisesRegex(frappe.ValidationError, "invoice-cancel-failed"):
			quick_cancel_purchase_order_v2("PO-0001", request_id="quick-cancel-recovery-a")

		result = quick_cancel_purchase_order_v2("PO-0001", request_id="quick-cancel-recovery-b")

		self.assertEqual(result["cancelled_payment_entries"], [])
		self.assertEqual(result["cancelled_purchase_invoice"], "PINV-0001")
		self.assertEqual(result["cancelled_purchase_receipt"], "PR-0001")
		self.assertEqual(result["completed_steps"], ["purchase_invoice", "purchase_receipt"])
		self.assertFalse(result["detail_included"])
		self.assertIsNone(result["detail"])
		mock_cancel_supplier_payment.assert_called_once_with("PAY-0001")
		self.assertEqual(mock_cancel_purchase_invoice.call_count, 2)
		mock_cancel_purchase_receipt.assert_called_once_with("PR-0001", request_id="quick-cancel-recovery-b")
		self.assertEqual(mock_run_idempotent.call_count, 2)
		mock_get_purchase_order_detail.assert_not_called()

	@patch("myapp.services.purchase_service.run_idempotent", side_effect=lambda namespace, request_id, callback: callback())
	@patch("myapp.services.purchase_service.get_purchase_order_detail_v2")
	@patch("myapp.services.purchase_service.cancel_purchase_receipt_v2")
	@patch("myapp.services.purchase_service.cancel_purchase_invoice_v2")
	@patch("myapp.services.purchase_service.cancel_supplier_payment")
	@patch("myapp.services.purchase_service._collect_submitted_supplier_payment_entry_summaries")
	@patch("myapp.services.purchase_service._collect_purchase_order_reference_names")
	@patch("myapp.services.purchase_service._get_purchase_order_doc_for_update")
	def test_quick_cancel_purchase_order_v2_recovers_after_receipt_cancel_failure(
		self,
		mock_get_purchase_order_doc_for_update,
		mock_collect_purchase_refs,
		mock_collect_payments,
		mock_cancel_supplier_payment,
		mock_cancel_purchase_invoice,
		mock_cancel_purchase_receipt,
		mock_get_purchase_order_detail,
		mock_run_idempotent,
	):
		mock_get_purchase_order_doc_for_update.return_value = frappe._dict({"name": "PO-0001"})
		mock_collect_purchase_refs.side_effect = [
			(["PR-0001"], ["PINV-0001"]),
			(["PR-0001"], []),
		]
		mock_collect_payments.side_effect = [
			[
				{
					"payment_entry": "PAY-0001",
					"references": [
						{
							"reference_doctype": "Purchase Invoice",
							"reference_name": "PINV-0001",
						}
					],
				}
			],
			[],
		]
		mock_cancel_supplier_payment.return_value = {"status": "success", "payment_entry": "PAY-0001"}
		mock_cancel_purchase_invoice.return_value = {"status": "success", "purchase_invoice": "PINV-0001"}
		mock_cancel_purchase_receipt.side_effect = [
			frappe.ValidationError("receipt-cancel-failed"),
			{"status": "success", "purchase_receipt": "PR-0001"},
		]
		mock_get_purchase_order_detail.return_value = {"status": "success", "data": {"purchase_order_name": "PO-0001"}}

		with self.assertRaisesRegex(frappe.ValidationError, "receipt-cancel-failed"):
			quick_cancel_purchase_order_v2("PO-0001", request_id="quick-cancel-recovery-c")

		result = quick_cancel_purchase_order_v2("PO-0001", request_id="quick-cancel-recovery-d")

		self.assertEqual(result["cancelled_payment_entries"], [])
		self.assertIsNone(result["cancelled_purchase_invoice"])
		self.assertEqual(result["cancelled_purchase_receipt"], "PR-0001")
		self.assertEqual(result["completed_steps"], ["purchase_receipt"])
		self.assertFalse(result["detail_included"])
		self.assertIsNone(result["detail"])
		mock_cancel_supplier_payment.assert_called_once_with("PAY-0001")
		mock_cancel_purchase_invoice.assert_called_once_with("PINV-0001", request_id="quick-cancel-recovery-c")
		self.assertEqual(mock_cancel_purchase_receipt.call_count, 2)
		mock_cancel_purchase_receipt.assert_called_with("PR-0001", request_id="quick-cancel-recovery-d")
		self.assertEqual(mock_run_idempotent.call_count, 2)
		mock_get_purchase_order_detail.assert_not_called()

	@patch("myapp.services.purchase_service._get_latest_purchase_payment_entry_summary")
	@patch("myapp.services.purchase_service._load_purchase_invoice_rows")
	@patch("myapp.services.purchase_service._collect_purchase_order_reference_names")
	@patch("myapp.services.purchase_service.frappe.get_doc")
	def test_get_purchase_order_detail_v2_returns_aggregated_data(
		self,
		mock_get_doc,
		mock_collect_refs,
		mock_load_invoices,
		mock_latest_payment,
	):
		po = frappe._dict(
			{
				"name": "PO-0001",
				"docstatus": 1,
				"supplier": "SUP-001",
				"supplier_name": "MA Inc.",
				"company": "Test Company",
				"currency": "CNY",
				"transaction_date": "2026-03-26",
				"schedule_date": "2026-03-27",
				"rounded_total": 300,
				"grand_total": 300,
				"remarks": "test",
				"items": [
					frappe._dict({"name": "POI-001", "item_code": "ITEM-001", "qty": 10, "received_qty": 4, "rate": 30, "amount": 300}),
				],
			}
		)
		mock_get_doc.return_value = po
		mock_collect_refs.return_value = (["PR-0001"], ["PINV-0001"])
		mock_load_invoices.return_value = [frappe._dict({"name": "PINV-0001", "rounded_total": 300, "outstanding_amount": 120})]
		mock_latest_payment.return_value = {
			"payment_entry": "PAY-0001",
			"invoice_name": "PINV-0001",
			"unallocated_amount": 0,
			"writeoff_amount": 0,
			"actual_paid_amount": 180,
			"total_actual_paid_amount": 180,
			"total_writeoff_amount": 0,
		}

		result = get_purchase_order_detail_v2("PO-0001")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["purchase_order_name"], "PO-0001")
		self.assertEqual(result["data"]["receiving"]["status"], "partial")
		self.assertEqual(result["data"]["references"]["purchase_receipts"], ["PR-0001"])
		self.assertFalse(result["data"]["actions"]["can_cancel_purchase_order"])
		self.assertIn("收货或开票记录", result["data"]["actions"]["cancel_purchase_order_hint"])

	@patch("myapp.services.purchase_service._get_latest_purchase_payment_entry_summary")
	@patch("myapp.services.purchase_service._load_purchase_invoice_rows")
	@patch("myapp.services.purchase_service._collect_purchase_order_reference_names")
	@patch("myapp.services.purchase_service.frappe.get_doc")
	def test_get_purchase_order_detail_v2_actions_allow_cancel_without_downstream_docs(
		self,
		mock_get_doc,
		mock_collect_refs,
		mock_load_invoices,
		mock_latest_payment,
	):
		po = frappe._dict(
			{
				"name": "PO-0002",
				"docstatus": 1,
				"supplier": "SUP-001",
				"supplier_name": "MA Inc.",
				"company": "Test Company",
				"currency": "CNY",
				"transaction_date": "2026-03-26",
				"schedule_date": "2026-03-27",
				"rounded_total": 300,
				"grand_total": 300,
				"items": [
					frappe._dict({"name": "POI-002", "item_code": "ITEM-001", "qty": 10, "received_qty": 0, "rate": 30, "amount": 300}),
				],
			}
		)
		mock_get_doc.return_value = po
		mock_collect_refs.return_value = ([], [])
		mock_load_invoices.return_value = []
		mock_latest_payment.return_value = {
			"payment_entry": None,
			"invoice_name": None,
			"unallocated_amount": 0,
			"writeoff_amount": 0,
			"actual_paid_amount": 0,
			"total_actual_paid_amount": 0,
			"total_writeoff_amount": 0,
		}

		result = get_purchase_order_detail_v2("PO-0002")

		self.assertEqual(result["status"], "success")
		self.assertTrue(result["data"]["actions"]["can_cancel_purchase_order"])
		self.assertIsNone(result["data"]["actions"]["cancel_purchase_order_hint"])

	@patch("myapp.services.purchase_service._build_purchase_receipt_references")
	@patch("myapp.services.purchase_service.frappe.get_doc")
	def test_get_purchase_receipt_detail_v2_returns_detail(self, mock_get_doc, mock_build_references):
		pr = frappe._dict(
			{
				"name": "PR-0001",
				"docstatus": 1,
				"supplier": "SUP-001",
				"supplier_name": "MA Inc.",
				"company": "Test Company",
				"currency": "CNY",
				"posting_date": "2026-03-26",
				"posting_time": "10:00:00",
				"grand_total": 200,
				"items": [frappe._dict({"name": "PRI-001", "item_code": "ITEM-001", "qty": 2, "rate": 100, "amount": 200})],
			}
		)
		mock_get_doc.return_value = pr
		mock_build_references.return_value = {"purchase_orders": ["PO-0001"], "purchase_invoices": ["PINV-0001"]}

		result = get_purchase_receipt_detail_v2("PR-0001")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["purchase_receipt_name"], "PR-0001")
		self.assertEqual(result["data"]["references"]["purchase_orders"], ["PO-0001"])

	@patch("myapp.services.purchase_service._get_latest_purchase_payment_entry_summary")
	@patch("myapp.services.purchase_service.frappe.get_doc")
	def test_get_purchase_invoice_detail_v2_returns_detail(self, mock_get_doc, mock_latest_payment):
		pi = frappe._dict(
			{
				"name": "PINV-0001",
				"docstatus": 1,
				"supplier": "SUP-001",
				"supplier_name": "MA Inc.",
				"company": "Test Company",
				"currency": "CNY",
				"posting_date": "2026-03-26",
				"due_date": "2026-03-30",
				"rounded_total": 200,
				"outstanding_amount": 50,
				"items": [frappe._dict({"name": "PII-001", "item_code": "ITEM-001", "qty": 2, "rate": 100, "amount": 200})],
			}
		)
		mock_get_doc.return_value = pi
		mock_latest_payment.return_value = {
			"payment_entry": "PAY-0001",
			"invoice_name": "PINV-0001",
			"unallocated_amount": 0,
			"writeoff_amount": 0,
			"actual_paid_amount": 150,
			"total_actual_paid_amount": 150,
			"total_writeoff_amount": 0,
		}

		result = get_purchase_invoice_detail_v2("PINV-0001")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["purchase_invoice_name"], "PINV-0001")
		self.assertEqual(result["data"]["payment"]["outstanding_amount"], 50)

	@patch("myapp.services.purchase_service._build_purchase_order_summary_rows")
	@patch("myapp.services.purchase_service.frappe.get_all")
	def test_get_purchase_order_status_summary_uses_summary_rows(self, mock_get_all, mock_build_summary_rows):
		mock_get_all.return_value = [
			frappe._dict(
				{
					"name": "PO-0001",
					"supplier": "SUP-001",
					"supplier_name": "MA Inc.",
					"transaction_date": "2026-03-26",
					"company": "Test Company",
					"docstatus": 1,
					"rounded_total": 300,
					"grand_total": 300,
					"modified": "2026-03-26 10:00:00",
				}
			)
		]
		mock_build_summary_rows.return_value = [
			{
				"purchase_order_name": "PO-0001",
				"receiving": {"status": "partial"},
				"payment": {"outstanding_amount": 120},
				"completion": {"status": "open"},
			}
		]

		result = get_purchase_order_status_summary(supplier="SUP-001", company="Test Company", limit=5)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"][0]["purchase_order_name"], "PO-0001")
		self.assertEqual(result["data"][0]["receiving"]["status"], "partial")

	@patch("myapp.services.purchase_service._build_purchase_order_summary_rows")
	@patch("myapp.services.purchase_service.frappe.get_all")
	def test_search_purchase_orders_v2_filters_out_cancelled_by_default(self, mock_get_all, mock_build_summary_rows):
		mock_get_all.return_value = [
			frappe._dict(
				{
					"name": "PO-OPEN-001",
					"supplier": "SUP-001",
					"supplier_name": "MA Inc.",
					"transaction_date": "2026-03-26",
					"company": "Test Company",
					"docstatus": 1,
					"rounded_total": 300,
					"grand_total": 300,
					"modified": "2026-03-26 10:00:00",
				}
			),
			frappe._dict(
				{
					"name": "PO-CAN-001",
					"supplier": "SUP-001",
					"supplier_name": "MA Inc.",
					"transaction_date": "2026-03-25",
					"company": "Test Company",
					"docstatus": 2,
					"rounded_total": 80,
					"grand_total": 80,
					"modified": "2026-03-25 09:00:00",
				}
			),
		]
		mock_build_summary_rows.return_value = [
			{
				"purchase_order_name": "PO-OPEN-001",
				"document_status": "submitted",
				"receiving": {"status": "pending", "is_fully_received": False},
				"payment": {"status": "unpaid"},
				"completion": {"status": "open"},
			},
			{
				"purchase_order_name": "PO-CAN-001",
				"document_status": "cancelled",
				"receiving": {"status": "pending", "is_fully_received": False},
				"payment": {"status": "unpaid"},
				"completion": {"status": "open"},
			},
		]

		result = search_purchase_orders_v2(company="Test Company", status_filter="unfinished", exclude_cancelled=True, limit=20)

		self.assertEqual(result["status"], "success")
		self.assertEqual(len(result["data"]["items"]), 1)
		self.assertEqual(result["data"]["items"][0]["purchase_order_name"], "PO-OPEN-001")
		self.assertEqual(result["data"]["summary"]["cancelled_count"], 1)

	@patch("myapp.services.purchase_service._build_purchase_order_summary_rows")
	@patch("myapp.services.purchase_service.frappe.get_all")
	def test_search_purchase_orders_v2_passes_search_filters_and_sorts(self, mock_get_all, mock_build_summary_rows):
		mock_get_all.return_value = [
			frappe._dict(
				{
					"name": "PO-0001",
					"supplier": "SUP-001",
					"supplier_name": "MA Inc.",
					"transaction_date": "2026-03-24",
					"company": "Test Company",
					"docstatus": 1,
					"rounded_total": 50,
					"grand_total": 50,
					"modified": "2026-03-24 09:00:00",
				}
			),
			frappe._dict(
				{
					"name": "PO-0002",
					"supplier": "SUP-002",
					"supplier_name": "NB Inc.",
					"transaction_date": "2026-03-26",
					"company": "Test Company",
					"docstatus": 1,
					"rounded_total": 500,
					"grand_total": 500,
					"modified": "2026-03-26 12:00:00",
				}
			),
		]
		mock_build_summary_rows.return_value = [
			{
				"purchase_order_name": "PO-0001",
				"document_status": "submitted",
				"order_amount_estimate": 50,
				"transaction_date": "2026-03-24",
				"modified": "2026-03-24 09:00:00",
				"receiving": {"status": "received", "is_fully_received": True},
				"payment": {"status": "unpaid"},
				"completion": {"status": "open"},
			},
			{
				"purchase_order_name": "PO-0002",
				"document_status": "submitted",
				"order_amount_estimate": 500,
				"transaction_date": "2026-03-26",
				"modified": "2026-03-26 12:00:00",
				"receiving": {"status": "pending", "is_fully_received": False},
				"payment": {"status": "unpaid"},
				"completion": {"status": "open"},
			},
		]

		result = search_purchase_orders_v2(
			search_key="MA",
			company="Test Company",
			date_from="2026-03-01",
			date_to="2026-03-31",
			status_filter="all",
			exclude_cancelled=False,
			sort_by="amount_desc",
			limit=10,
			start=0,
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["summary"]["total_count"], 2)
		self.assertEqual(result["data"]["items"][0]["purchase_order_name"], "PO-0002")
		self.assertEqual(mock_get_all.call_args.kwargs["filters"]["company"], "Test Company")
		self.assertEqual(
			mock_get_all.call_args.kwargs["filters"]["transaction_date"],
			["between", ["2026-03-01", "2026-03-31"]],
		)
		self.assertEqual(len(mock_get_all.call_args.kwargs["or_filters"]), 5)
		self.assertEqual(result["data"]["meta"]["filters"]["date_from"], "2026-03-01")
		self.assertEqual(result["data"]["meta"]["filters"]["date_to"], "2026-03-31")

	@patch("myapp.services.purchase_service._build_purchase_order_summary_rows")
	@patch("myapp.services.purchase_service.frappe.get_all")
	def test_get_purchase_order_status_summary_supports_date_range_filters(self, mock_get_all, mock_build_summary_rows):
		mock_get_all.return_value = [
			frappe._dict(
				{
					"name": "PO-0003",
					"supplier": "SUP-001",
					"supplier_name": "MA Inc.",
					"transaction_date": "2026-03-15",
					"company": "Test Company",
					"docstatus": 1,
					"rounded_total": 300,
					"grand_total": 300,
					"modified": "2026-03-15 10:00:00",
				}
			)
		]
		mock_build_summary_rows.return_value = [
			{
				"purchase_order_name": "PO-0003",
				"document_status": "submitted",
				"receiving": {"status": "pending", "is_fully_received": False},
				"payment": {"status": "unpaid"},
				"completion": {"status": "open"},
			}
		]

		result = get_purchase_order_status_summary(
			supplier="SUP-001",
			company="Test Company",
			limit=5,
			date_from="2026-03-01",
			date_to="2026-03-31",
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["meta"]["filters"]["date_from"], "2026-03-01")
		self.assertEqual(result["meta"]["filters"]["date_to"], "2026-03-31")
		self.assertEqual(
			mock_get_all.call_args.kwargs["filters"]["transaction_date"],
			["between", ["2026-03-01", "2026-03-31"]],
		)

	@patch("myapp.services.purchase_service._get_recent_purchase_order_addresses")
	@patch("myapp.services.purchase_service._serialize_address_doc")
	@patch("myapp.services.purchase_service._serialize_contact_doc")
	@patch("myapp.services.purchase_service._get_doc_if_exists")
	@patch("myapp.services.purchase_service.frappe.get_doc")
	def test_get_supplier_detail_v2_includes_recent_addresses(
		self,
		mock_get_doc,
		mock_get_doc_if_exists,
		mock_serialize_contact_doc,
		mock_serialize_address_doc,
		mock_recent_addresses,
	):
		mock_get_doc.return_value = frappe._dict(
			{
				"name": "SUP-001",
				"supplier_name": "MA Inc.",
				"supplier_type": "Company",
				"supplier_group": "Raw",
				"default_currency": "CNY",
				"disabled": 0,
				"supplier_primary_contact": "CONT-001",
				"supplier_primary_address": "ADDR-001",
			}
		)
		mock_get_doc_if_exists.side_effect = [
			frappe._dict({"name": "CONT-001"}),
			frappe._dict({"name": "ADDR-001"}),
		]
		mock_serialize_contact_doc.return_value = {"name": "CONT-001", "display_name": "张三"}
		mock_serialize_address_doc.return_value = {"name": "ADDR-001", "address_line1": "测试路 100 号"}
		mock_recent_addresses.return_value = [{"name": "ADDR-001", "address_display": "测试地址"}]

		result = get_supplier_detail_v2("SUP-001")

		self.assertEqual(result["data"]["name"], "SUP-001")
		self.assertEqual(result["data"]["recent_addresses"][0]["name"], "ADDR-001")

	@patch("myapp.services.purchase_service._get_recent_purchase_order_addresses")
	@patch("myapp.services.purchase_service._serialize_address_doc")
	@patch("myapp.services.purchase_service._serialize_contact_doc")
	@patch("myapp.services.purchase_service._get_linked_parent_names")
	@patch("myapp.services.purchase_service._get_doc_if_exists")
	@patch("myapp.services.purchase_service._get_purchase_default_warehouse_for_company")
	@patch("myapp.services.purchase_service.frappe.defaults.get_user_default")
	@patch("myapp.services.purchase_service.frappe.get_doc")
	def test_get_supplier_purchase_context_returns_defaults(
		self,
		mock_get_doc,
		mock_user_default,
		mock_default_warehouse,
		mock_get_doc_if_exists,
		mock_get_linked_parent_names,
		mock_serialize_contact_doc,
		mock_serialize_address_doc,
		mock_recent_addresses,
	):
		mock_get_doc.return_value = frappe._dict(
			{
				"name": "SUP-001",
				"supplier_name": "MA Inc.",
				"supplier_group": "Raw",
				"supplier_type": "Company",
				"default_currency": "CNY",
				"supplier_primary_contact": "CONT-001",
				"supplier_primary_address": "ADDR-001",
			}
		)
		mock_user_default.return_value = "Test Company"
		mock_default_warehouse.return_value = "Stores - TC"
		mock_get_linked_parent_names.return_value = []
		mock_get_doc_if_exists.side_effect = [frappe._dict({"name": "CONT-001"}), frappe._dict({"name": "ADDR-001"})]
		mock_serialize_contact_doc.return_value = {"name": "CONT-001", "display_name": "张三"}
		mock_serialize_address_doc.return_value = {"name": "ADDR-001", "address_line1": "测试路 100 号"}
		mock_recent_addresses.return_value = []

		result = get_supplier_purchase_context("SUP-001")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["suggestions"]["warehouse"], "Stores - TC")
		self.assertEqual(result["data"]["supplier"]["name"], "SUP-001")

	@patch("myapp.services.purchase_service._serialize_address_doc")
	@patch("myapp.services.purchase_service._serialize_contact_doc")
	@patch("myapp.services.purchase_service._get_doc_if_exists")
	@patch("myapp.services.purchase_service.frappe.get_all")
	def test_list_suppliers_v2_returns_summaries_with_meta(
		self,
		mock_get_all,
		mock_get_doc_if_exists,
		mock_serialize_contact_doc,
		mock_serialize_address_doc,
	):
		mock_get_all.side_effect = [
			[
				frappe._dict(
					{
						"name": "SUP-001",
						"supplier_name": "MA Inc.",
						"supplier_type": "Company",
						"supplier_group": "Raw",
						"default_currency": "CNY",
						"disabled": 0,
						"modified": "2026-03-26 10:00:00",
						"creation": "2026-03-20 10:00:00",
						"supplier_primary_contact": "CONT-001",
						"supplier_primary_address": "ADDR-001",
					}
				)
			],
			["SUP-001", "SUP-002"],
		]
		mock_get_doc_if_exists.side_effect = [frappe._dict({"name": "CONT-001"}), frappe._dict({"name": "ADDR-001"})]
		mock_serialize_contact_doc.return_value = {"name": "CONT-001", "display_name": "张三"}
		mock_serialize_address_doc.return_value = {"name": "ADDR-001", "address_line1": "测试路 100 号"}

		result = list_suppliers_v2(
			search_key="MA",
			date_from="2026-03-01",
			date_to="2026-03-31",
			limit=20,
			start=0,
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(len(result["data"]), 1)
		self.assertEqual(result["data"][0]["name"], "SUP-001")
		self.assertEqual(result["meta"]["total"], 2)
		self.assertEqual(
			mock_get_all.call_args_list[0].kwargs["filters"]["creation"],
			["between", ["2026-03-01 00:00:00", "2026-03-31 23:59:59"]],
		)
		self.assertEqual(result["meta"]["filters"]["date_from"], "2026-03-01")
		self.assertEqual(result["meta"]["filters"]["date_to"], "2026-03-31")

	@patch("myapp.services.purchase_service.run_idempotent")
	def test_create_supplier_v2_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {"status": "success", "data": {"name": "SUP-001"}}

		result = create_supplier_v2(supplier_name="MA Inc.", request_id="sup-create-001")

		self.assertEqual(result["status"], "success")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.purchase_service._build_supplier_payload")
	@patch("myapp.services.purchase_service._upsert_supplier_primary_address")
	@patch("myapp.services.purchase_service._upsert_supplier_primary_contact")
	@patch("myapp.services.purchase_service._supplier_name_exists")
	@patch("myapp.services.purchase_service._safe_doc_field", return_value=True)
	@patch("myapp.services.purchase_service._new_doc")
	def test_create_supplier_v2_creates_supplier_contact_and_address(
		self,
		mock_new_doc,
		_mock_safe_doc_field,
		mock_exists,
		mock_upsert_contact,
		mock_upsert_address,
		mock_build_payload,
	):
		supplier_doc = MagicMock()
		supplier_doc.name = "SUP-001"
		supplier_doc.supplier_name = "MA Inc."
		supplier_doc.disabled = 0
		mock_new_doc.return_value = supplier_doc
		mock_exists.return_value = False
		mock_upsert_contact.return_value = frappe._dict({"name": "CONT-001"})
		mock_upsert_address.return_value = frappe._dict({"name": "ADDR-001"})
		mock_build_payload.return_value = {"name": "SUP-001"}

		result = create_supplier_v2(
			supplier_name="MA Inc.",
			supplier_group="Raw",
			default_contact={"display_name": "张三", "phone": "13800000000"},
			default_address={"address_line1": "测试路 100 号", "city": "上海", "country": "China"},
		)

		self.assertEqual(result["status"], "success")
		supplier_doc.insert.assert_called_once()
		supplier_doc.save.assert_called_once()
		mock_upsert_contact.assert_called_once()
		mock_upsert_address.assert_called_once()
		self.assertEqual(result["meta"]["created_contact"], "CONT-001")
		self.assertEqual(result["meta"]["created_address"], "ADDR-001")

	@patch("myapp.services.purchase_service._build_supplier_payload")
	@patch("myapp.services.purchase_service._upsert_supplier_primary_address")
	@patch("myapp.services.purchase_service._upsert_supplier_primary_contact")
	@patch("myapp.services.purchase_service._safe_doc_field", return_value=True)
	@patch("myapp.services.purchase_service.frappe.get_doc")
	def test_update_supplier_v2_updates_supplier_and_primary_links(
		self,
		mock_get_doc,
		_mock_safe_doc_field,
		mock_upsert_contact,
		mock_upsert_address,
		mock_build_payload,
	):
		supplier_doc = MagicMock()
		supplier_doc.name = "SUP-001"
		supplier_doc.supplier_name = "旧供应商"
		supplier_doc.supplier_primary_contact = "CONT-001"
		supplier_doc.supplier_primary_address = "ADDR-001"
		supplier_doc.meta.has_field.return_value = True
		mock_get_doc.return_value = supplier_doc
		mock_upsert_contact.return_value = frappe._dict({"name": "CONT-001"})
		mock_upsert_address.return_value = frappe._dict({"name": "ADDR-001"})
		mock_build_payload.return_value = {"name": "SUP-001"}

		result = update_supplier_v2(
			supplier="SUP-001",
			supplier_name="新供应商",
			default_contact={"name": "CONT-001", "display_name": "李四"},
			default_address={"name": "ADDR-001", "address_line1": "新地址", "city": "杭州", "country": "China"},
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(supplier_doc.supplier_name, "新供应商")
		self.assertEqual(supplier_doc.save.call_count, 2)
		mock_upsert_contact.assert_called_once()
		mock_upsert_address.assert_called_once()

	@patch("myapp.services.purchase_service.run_idempotent")
	def test_disable_supplier_v2_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {"status": "success", "data": {"name": "SUP-001"}}

		result = disable_supplier_v2(supplier="SUP-001", request_id="sup-disable-001")

		self.assertEqual(result["status"], "success")
		mock_run_idempotent.assert_called_once()
