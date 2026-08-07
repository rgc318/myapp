from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.purchase_service import (
	_check_doc_permission,
	_build_purchase_invoice_action_flags,
	_build_purchase_order_action_flags,
	_build_purchase_receipt_action_flags,
	_get_purchase_order_doc_for_update,
	_resolve_purchase_context_company,
	_collect_purchase_order_reference_names,
	_serialize_purchase_invoice_items,
	_serialize_purchase_order_items,
	_serialize_purchase_receipt_items,
	create_supplier_v2,
	create_purchase_invoice,
	create_purchase_invoice_from_receipt,
	create_purchase_order,
	disable_supplier_v2,
	get_purchase_company_context,
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
	update_purchase_order_v2,
)


class TestPurchaseService(TestCase):
	@patch("myapp.services.purchase_service.has_doctype_permission")
	def test_purchase_action_flags_hide_actions_without_target_permissions(self, mock_has_doctype_permission):
		permissions = {
			("Purchase Receipt", "create"): True,
			("Purchase Invoice", "create"): True,
			("Payment Entry", "create"): False,
			("Purchase Order", "cancel"): False,
		}
		mock_has_doctype_permission.side_effect = lambda doctype, ptype: permissions[(doctype, ptype)]

		result = _build_purchase_order_action_flags(
			{"is_fully_received": False},
			{"is_fully_billed": False},
			{"outstanding_amount": 100},
			invoice_names=[],
			receipt_names=[],
			docstatus=1,
		)

		self.assertTrue(result["can_receive_purchase_order"])
		self.assertTrue(result["can_create_purchase_invoice"])
		self.assertFalse(result["can_record_supplier_payment"])
		self.assertFalse(result["can_cancel_purchase_order"])
		self.assertIn("没有作废采购订单", result["cancel_purchase_order_hint"])

	@patch("myapp.services.purchase_service.has_doctype_permission", return_value=False)
	def test_purchase_document_action_flags_explain_missing_cancel_permission(self, _mock_permission):
		receipt_actions = _build_purchase_receipt_action_flags(
			docstatus=1,
			purchase_invoices=[],
		)
		invoice_actions = _build_purchase_invoice_action_flags(
			docstatus=1,
			latest_payment_entry=None,
			paid_amount=0,
		)

		self.assertFalse(receipt_actions["can_cancel_purchase_receipt"])
		self.assertFalse(receipt_actions["can_create_purchase_invoice"])
		self.assertIn("没有作废采购收货单", receipt_actions["cancel_purchase_receipt_hint"])
		self.assertFalse(invoice_actions["can_cancel_purchase_invoice"])
		self.assertIn("没有作废采购发票", invoice_actions["cancel_purchase_invoice_hint"])

	@patch("myapp.services.purchase_service.filter_permitted_user_default", return_value=None)
	@patch("myapp.services.purchase_service.frappe.defaults.get_user_default", return_value="Stale Company")
	def test_purchase_context_ignores_out_of_scope_saved_company(
		self,
		_mock_get_user_default,
		mock_filter_permitted_user_default,
	):
		result = _resolve_purchase_context_company(None)

		self.assertIsNone(result)
		mock_filter_permitted_user_default.assert_called_once_with(
			"Company",
			"Stale Company",
			applicable_for="Purchase Order",
		)

	@patch("myapp.services.purchase_service.ensure_user_permission_value")
	def test_purchase_context_rejects_explicit_out_of_scope_company(self, mock_ensure_user_permission_value):
		mock_ensure_user_permission_value.side_effect = frappe.PermissionError("denied")

		with self.assertRaises(frappe.PermissionError):
			_resolve_purchase_context_company("Forbidden Company")

	@patch("myapp.services.purchase_service.require_any_doctype_permission")
	def test_get_purchase_company_context_requires_purchase_order_access(
		self,
		mock_require_any_doctype_permission,
	):
		mock_require_any_doctype_permission.side_effect = frappe.PermissionError("denied")

		with self.assertRaises(frappe.PermissionError):
			get_purchase_company_context()

	def test_check_doc_permission_delegates_to_frappe_document(self):
		document = MagicMock()

		_check_doc_permission(document, "read")

		document.check_permission.assert_called_once_with("read")

	@patch("myapp.services.purchase_service.frappe.get_doc")
	def test_get_purchase_order_doc_for_update_checks_requested_permission(self, mock_get_doc):
		order = MagicMock()
		order.docstatus = 1
		mock_get_doc.return_value = order

		result = _get_purchase_order_doc_for_update("PO-SECURE-001", permission_type="cancel")

		self.assertIs(result, order)
		order.check_permission.assert_called_once_with("cancel")

	@patch("myapp.services.purchase_service.frappe.get_all")
	def test_collect_purchase_order_reference_names_excludes_return_documents(self, mock_get_all):
		mock_get_all.side_effect = [
			[frappe._dict({"parent": "PR-0001"}), frappe._dict({"parent": "PR-RETURN-0001"})],
			[frappe._dict({"name": "PR-0001"})],
			[frappe._dict({"parent": "PINV-0001"}), frappe._dict({"parent": "PINV-RETURN-0001"})],
			[frappe._dict({"name": "PINV-0001"})],
		]

		receipt_names, invoice_names = _collect_purchase_order_reference_names("PO-0001")

		self.assertEqual(receipt_names, ["PR-0001"])
		self.assertEqual(invoice_names, ["PINV-0001"])
		self.assertEqual(mock_get_all.call_count, 4)

	@patch("myapp.services.purchase_service._get_item_specification_field", return_value="custom_specification")
	@patch("myapp.services.purchase_service.frappe.get_all")
	@patch("myapp.services.purchase_service.build_uom_display_map", return_value={"Box": "箱"})
	def test_purchase_document_item_serializers_include_uom_display(
		self, mock_build_uom_display_map, mock_get_all, _mock_get_item_specification_field
	):
		mock_get_all.return_value = [frappe._dict({"name": "ITEM-001", "image": "/files/item-001.png", "custom_specification": "500ml"})]
		items = [
			frappe._dict(
				{
					"name": "ROW-001",
					"item_code": "ITEM-001",
					"item_name": "Item 1",
					"uom": "Box",
					"warehouse": "Stores - TC",
					"qty": 2,
					"rate": 10,
					"amount": 20,
				}
			)
		]

		order_rows = _serialize_purchase_order_items(items)
		receipt_rows = _serialize_purchase_receipt_items(items)
		invoice_rows = _serialize_purchase_invoice_items(items)

		self.assertEqual(order_rows[0]["uom_display"], "箱")
		self.assertEqual(receipt_rows[0]["uom_display"], "箱")
		self.assertEqual(invoice_rows[0]["uom_display"], "箱")
		self.assertEqual(order_rows[0]["image"], "/files/item-001.png")
		self.assertEqual(receipt_rows[0]["image"], "/files/item-001.png")
		self.assertEqual(invoice_rows[0]["image"], "/files/item-001.png")
		mock_build_uom_display_map.assert_any_call(["Box"])

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
	@patch("myapp.services.purchase_service._resolve_purchase_transaction_currency", return_value="CNY")
	@patch("myapp.services.purchase_service._get_purchase_order_remark_field", return_value="custom_order_remark")
	@patch("myapp.services.purchase_service.frappe.new_doc")
	@patch("myapp.services.purchase_service.nowdate", return_value="2026-03-26")
	@patch("myapp.services.purchase_service.frappe.defaults.get_user_default")
	def test_create_purchase_order_builds_and_submits_document(
		self,
		mock_get_user_default,
		mock_nowdate,
		mock_new_doc,
		_mock_get_remark_field,
		_mock_resolve_currency,
		mock_insert_and_submit,
		mock_build_purchase_order_item,
	):
		mock_get_user_default.return_value = "Test Company"
		po = MagicMock()
		po.name = "PO-0001"
		mock_new_doc.return_value = po
		mock_build_purchase_order_item.return_value = {"item_code": "ITEM-001", "qty": 2, "warehouse": "Stores - TC"}

		result = create_purchase_order(
			supplier="Test Supplier",
			items=[{"item_code": "ITEM-001", "qty": 2, "warehouse": "Stores - TC"}],
			remarks="采购备注",
		)

		mock_new_doc.assert_called_once_with("Purchase Order")
		self.assertEqual(result["purchase_order"], "PO-0001")
		mock_insert_and_submit.assert_called_once_with(po)
		po.append.assert_called_once()
		po.set.assert_any_call("custom_order_remark", "采购备注")

	@patch("myapp.services.purchase_service.run_idempotent", side_effect=lambda _key, _request_id, fn: fn())
	@patch("myapp.services.purchase_service._get_purchase_order_remark", return_value="更新备注")
	@patch("myapp.services.purchase_service._set_purchase_order_remark")
	@patch("myapp.services.purchase_service._get_purchase_order_remark_field", return_value="custom_order_remark")
	@patch("myapp.services.purchase_service._get_purchase_order_doc_for_update")
	def test_update_purchase_order_v2_updates_custom_remark_field(
		self,
		mock_get_order,
		mock_get_remark_field,
		mock_set_remark,
		mock_get_remark,
		_mock_run_idempotent,
	):
		po = MagicMock()
		po.name = "PO-0001"
		po.docstatus = 1
		po.get.side_effect = lambda key, default=None: {
			"transaction_date": "2026-03-26",
			"schedule_date": "2026-03-27",
			"supplier_ref": None,
			"custom_order_remark": "更新备注",
		}.get(key, default)
		po.meta.has_field.return_value = False
		mock_get_order.return_value = po

		result = update_purchase_order_v2("PO-0001", remarks="更新备注")

		mock_set_remark.assert_called_once_with(po, "更新备注")
		po.db_set.assert_any_call("custom_order_remark", "更新备注", update_modified=True)
		self.assertEqual(result["meta"]["remarks"], "更新备注")

	@patch("myapp.services.purchase_service.nowdate", return_value="2026-03-26")
	@patch("myapp.services.purchase_service._resolve_purchase_transaction_currency", return_value="CNY")
	@patch(
		"myapp.services.purchase_service.frappe.throw",
		side_effect=frappe.ValidationError("无法创建空采购订单，请至少选择一个商品。"),
	)
	def test_create_purchase_order_rejects_empty_items(self, mock_throw, _mock_resolve_currency, mock_nowdate):
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

	@patch("myapp.services.purchase_service.update_payment_status")
	def test_record_supplier_payment_uses_shared_settlement(self, mock_update_payment_status):
		mock_update_payment_status.return_value = {"status": "success", "payment_entry": "ACC-PAY-0001"}

		result = record_supplier_payment(
			"PINV-0001",
			100,
			mode_of_payment="Bank",
			settlement_mode="writeoff",
			writeoff_reason="采购差额核销",
		)

		self.assertEqual(result["payment_entry"], "ACC-PAY-0001")
		mock_update_payment_status.assert_called_once_with(
			"Purchase Invoice",
			"PINV-0001",
			100,
			mode_of_payment="Bank",
			reference_no="采购付款",
			reference_date=None,
			request_id=None,
			settlement_mode="writeoff",
			writeoff_reason="采购差额核销",
		)

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

	@patch("myapp.services.purchase_service.update_payment_status")
	def test_record_supplier_payment_passes_idempotency_key_to_shared_settlement(self, mock_update_payment_status):
		mock_update_payment_status.return_value = {"status": "success", "payment_entry": "ACC-PAY-0099"}

		with patch.object(frappe, "db", MagicMock(get_value=MagicMock(return_value=100))):
			result = record_supplier_payment("PINV-0001", 100, request_id="pay-001")

		self.assertEqual(result["payment_entry"], "ACC-PAY-0099")
		self.assertEqual(mock_update_payment_status.call_args.kwargs["request_id"], "pay-001")

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

	@patch("myapp.services.purchase_service.run_idempotent", side_effect=lambda namespace, request_id, callback, **kwargs: callback())
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
			request_id=None,
		)
		mock_run_idempotent.assert_called_once()
		self.assertIn("request_payload", mock_run_idempotent.call_args.kwargs)
		self.assertIn(frappe.ValidationError, mock_run_idempotent.call_args.kwargs["retryable_exceptions"])
		mock_get_purchase_order_detail.assert_not_called()

	@patch("myapp.services.purchase_service.run_idempotent", side_effect=lambda namespace, request_id, callback, **kwargs: callback())
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

	@patch("myapp.services.purchase_service._get_item_specification_field", return_value="custom_specification")
	@patch("myapp.services.purchase_service._get_latest_purchase_payment_entry_summary")
	@patch("myapp.services.purchase_service._load_purchase_invoice_rows")
	@patch("myapp.services.purchase_service._build_purchase_order_timeline", return_value=[])
	@patch("myapp.services.purchase_service._collect_purchase_order_reference_names")
	@patch("myapp.services.purchase_service._get_purchase_order_remark_field", return_value="custom_order_remark")
	@patch("myapp.services.purchase_service.frappe.get_all")
	@patch("myapp.services.purchase_service.frappe.get_doc")
	def test_get_purchase_order_detail_v2_returns_aggregated_data(
		self,
		mock_get_doc,
		mock_get_all,
		_mock_get_remark_field,
		mock_collect_refs,
		_mock_build_timeline,
		mock_load_invoices,
		mock_latest_payment,
		mock_get_item_specification_field,
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
				"custom_order_remark": "test",
				"items": [
					frappe._dict({"name": "POI-001", "item_code": "ITEM-001", "qty": 10, "received_qty": 4, "rate": 30, "amount": 300}),
				],
			}
		)
		po.check_permission = MagicMock()
		mock_get_doc.return_value = po
		mock_get_all.return_value = [frappe._dict({"name": "ITEM-001", "custom_specification": "500ml", "image": "/files/item-001.png"})]
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
		self.assertEqual(result["data"]["items"][0]["specification"], "500ml")
		self.assertEqual(result["data"]["items"][0]["image"], "/files/item-001.png")
		self.assertEqual(result["data"]["meta"]["remarks"], "test")

	@patch("myapp.services.purchase_service._get_item_specification_field", return_value="custom_specification")
	@patch("myapp.services.purchase_service._get_latest_purchase_payment_entry_summary")
	@patch("myapp.services.purchase_service._load_purchase_invoice_rows")
	@patch("myapp.services.purchase_service._build_purchase_order_timeline", return_value=[])
	@patch("myapp.services.purchase_service._collect_purchase_order_reference_names")
	@patch("myapp.services.purchase_service.frappe.get_all")
	@patch("myapp.services.purchase_service.frappe.get_doc")
	def test_get_purchase_order_detail_v2_actions_allow_cancel_without_downstream_docs(
		self,
		mock_get_doc,
		mock_get_all,
		mock_collect_refs,
		_mock_build_timeline,
		mock_load_invoices,
		mock_latest_payment,
		_mock_get_item_specification_field,
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
		po.check_permission = MagicMock()
		mock_get_doc.return_value = po
		mock_get_all.return_value = [frappe._dict({"name": "ITEM-001", "custom_specification": "500ml", "image": "/files/item-001.png"})]
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
		self.assertEqual(result["data"]["items"][0]["image"], "/files/item-001.png")

	@patch("myapp.services.purchase_service._get_item_specification_field", return_value="custom_specification")
	@patch("myapp.services.purchase_service._get_latest_purchase_payment_entry_summary")
	@patch("myapp.services.purchase_service._load_purchase_invoice_rows")
	@patch("myapp.services.purchase_service._build_purchase_order_timeline", return_value=[])
	@patch("myapp.services.purchase_service._collect_purchase_order_reference_names")
	@patch("myapp.services.purchase_service.frappe.get_all")
	@patch("myapp.services.purchase_service.frappe.get_doc")
	def test_get_purchase_order_detail_v2_disables_invoice_when_fully_billed(
		self,
		mock_get_doc,
		mock_get_all,
		mock_collect_refs,
		_mock_build_timeline,
		mock_load_invoices,
		mock_latest_payment,
		_mock_get_item_specification_field,
	):
		po = frappe._dict(
			{
				"name": "PO-0003",
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
					frappe._dict({"name": "POI-003", "item_code": "ITEM-001", "qty": 10, "received_qty": 10, "rate": 30, "amount": 300}),
				],
			}
		)
		po.check_permission = MagicMock()
		mock_get_doc.return_value = po
		mock_get_all.side_effect = [
			[frappe._dict({"po_detail": "POI-003", "qty": 10})],
			[],
			[frappe._dict({"name": "ITEM-001", "custom_specification": "500ml", "image": "/files/item-001.png"})],
			[frappe._dict({"po_detail": "POI-003", "qty": 10})],
		]
		mock_collect_refs.return_value = (["PR-0001"], ["PINV-0001"])
		mock_load_invoices.return_value = [frappe._dict({"name": "PINV-0001", "rounded_total": 300, "outstanding_amount": 300})]
		mock_latest_payment.return_value = {
			"payment_entry": None,
			"invoice_name": None,
			"unallocated_amount": 0,
			"writeoff_amount": 0,
			"actual_paid_amount": 0,
			"total_actual_paid_amount": 0,
			"total_writeoff_amount": 0,
		}

		result = get_purchase_order_detail_v2("PO-0003")

		self.assertEqual(result["status"], "success")
		self.assertFalse(result["data"]["actions"]["can_create_purchase_invoice"])
		self.assertEqual(result["data"]["billing"]["status"], "billed")
		self.assertEqual(result["data"]["items"][0]["billed_qty"], 10)
		self.assertEqual(result["data"]["items"][0]["pending_billing_qty"], 0)

	@patch("myapp.services.purchase_service._get_item_specification_field", return_value="custom_specification")
	@patch("myapp.services.purchase_service._build_purchase_receipt_references")
	@patch("myapp.services.purchase_service.frappe.get_all")
	@patch("myapp.services.purchase_service.frappe.get_doc")
	def test_get_purchase_receipt_detail_v2_returns_detail(
		self,
		mock_get_doc,
		mock_get_all,
		mock_build_references,
		mock_get_item_specification_field,
	):
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
		pr.check_permission = MagicMock()
		mock_get_doc.return_value = pr
		mock_get_all.return_value = [frappe._dict({"name": "ITEM-001", "custom_specification": "500ml", "image": "/files/item-001.png"})]
		mock_build_references.return_value = {"purchase_orders": ["PO-0001"], "purchase_invoices": ["PINV-0001"]}

		result = get_purchase_receipt_detail_v2("PR-0001")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["purchase_receipt_name"], "PR-0001")
		self.assertEqual(result["data"]["references"]["purchase_orders"], ["PO-0001"])
		self.assertEqual(result["data"]["items"][0]["specification"], "500ml")
		self.assertEqual(result["data"]["items"][0]["image"], "/files/item-001.png")

	@patch("myapp.services.purchase_service._get_item_specification_field", return_value="custom_specification")
	@patch("myapp.services.purchase_service._get_latest_purchase_payment_entry_summary")
	@patch("myapp.services.purchase_service.frappe.get_all")
	@patch("myapp.services.purchase_service.frappe.get_doc")
	def test_get_purchase_invoice_detail_v2_returns_detail(
		self,
		mock_get_doc,
		mock_get_all,
		mock_latest_payment,
		mock_get_item_specification_field,
	):
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
		pi.check_permission = MagicMock()
		mock_get_doc.return_value = pi
		mock_get_all.return_value = [frappe._dict({"name": "ITEM-001", "custom_specification": "500ml", "image": "/files/item-001.png"})]
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
		self.assertEqual(result["data"]["items"][0]["specification"], "500ml")
		self.assertEqual(result["data"]["items"][0]["image"], "/files/item-001.png")

	@patch("myapp.services.purchase_service._build_purchase_order_summary_rows")
	@patch("myapp.services.purchase_service.frappe.get_list")
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
	@patch("myapp.services.purchase_service.frappe.get_list")
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
	@patch("myapp.services.purchase_service.frappe.get_list")
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
	@patch("myapp.services.purchase_service.frappe.get_list")
	def test_search_purchase_orders_v2_supports_amount_asc_sort(self, mock_get_all, mock_build_summary_rows):
		mock_get_all.return_value = [
			frappe._dict(
				{
					"name": "PO-0001",
					"supplier": "SUP-001",
					"supplier_name": "MA Inc.",
					"transaction_date": "2026-03-25",
					"company": "Test Company",
					"docstatus": 1,
					"rounded_total": 200,
					"grand_total": 200,
					"modified": "2026-03-25 11:00:00",
				}
			),
			frappe._dict(
				{
					"name": "PO-0002",
					"supplier": "SUP-001",
					"supplier_name": "MA Inc.",
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
				"order_amount_estimate": 200,
				"transaction_date": "2026-03-25",
				"modified": "2026-03-25 11:00:00",
				"receiving": {"status": "pending", "is_fully_received": False},
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
			company="Test Company",
			status_filter="all",
			exclude_cancelled=False,
			sort_by="amount_asc",
			limit=10,
			start=0,
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["items"][0]["purchase_order_name"], "PO-0001")
		self.assertEqual(result["data"]["items"][1]["purchase_order_name"], "PO-0002")

	@patch("myapp.services.purchase_service._build_purchase_order_summary_rows")
	@patch("myapp.services.purchase_service.frappe.get_list")
	def test_search_purchase_orders_v2_supports_order_date_desc_sort(self, mock_get_all, mock_build_summary_rows):
		mock_get_all.return_value = [
			frappe._dict(
				{
					"name": "PO-NEW",
					"supplier": "SUP-001",
					"supplier_name": "MA Inc.",
					"transaction_date": "2026-03-26",
					"company": "Test Company",
					"docstatus": 1,
					"rounded_total": 500,
					"grand_total": 500,
					"modified": "2026-03-26 12:00:00",
				}
			),
			frappe._dict(
				{
					"name": "PO-OLD",
					"supplier": "SUP-001",
					"supplier_name": "MA Inc.",
					"transaction_date": "2026-03-24",
					"company": "Test Company",
					"docstatus": 1,
					"rounded_total": 200,
					"grand_total": 200,
					"modified": "2026-03-24 11:00:00",
				}
			),
		]
		mock_build_summary_rows.return_value = [
			{
				"purchase_order_name": "PO-NEW",
				"document_status": "submitted",
				"order_amount_estimate": 500,
				"transaction_date": "2026-03-26",
				"modified": "2026-03-26 12:00:00",
				"receiving": {"status": "pending", "is_fully_received": False},
				"payment": {"status": "unpaid"},
				"completion": {"status": "open"},
			},
			{
				"purchase_order_name": "PO-OLD",
				"document_status": "submitted",
				"order_amount_estimate": 200,
				"transaction_date": "2026-03-24",
				"modified": "2026-03-24 11:00:00",
				"receiving": {"status": "pending", "is_fully_received": False},
				"payment": {"status": "unpaid"},
				"completion": {"status": "open"},
			},
		]

		result = search_purchase_orders_v2(
			company="Test Company",
			status_filter="all",
			exclude_cancelled=False,
			sort_by="order_date_desc",
			limit=10,
			start=0,
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(mock_get_all.call_args.kwargs["order_by"], "transaction_date desc, modified desc")
		self.assertEqual(result["data"]["items"][0]["purchase_order_name"], "PO-NEW")
		self.assertEqual(result["data"]["meta"]["filters"]["sort_by"], "order_date_desc")

	@patch("myapp.services.purchase_service._build_purchase_order_summary_rows")
	@patch("myapp.services.purchase_service.frappe.get_list")
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
	@patch("myapp.services.purchase_service._resolve_purchase_transaction_currency", return_value="CNY")
	@patch("myapp.services.purchase_service.frappe.defaults.get_user_default")
	@patch("myapp.services.purchase_service.frappe.get_doc")
	def test_get_supplier_purchase_context_returns_defaults(
		self,
		mock_get_doc,
		mock_user_default,
		_mock_resolve_currency,
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
	@patch("myapp.services.purchase_service._safe_doc_field", return_value=True)
	@patch("myapp.services.purchase_service.frappe.get_list")
	def test_list_suppliers_v2_returns_summaries_with_meta(
		self,
		mock_get_list,
		_mock_safe_doc_field,
		mock_get_doc_if_exists,
		mock_serialize_contact_doc,
		mock_serialize_address_doc,
	):
		mock_get_list.side_effect = [
			[
				frappe._dict(
					{
						"name": "SUP-001",
						"supplier_name": "MA Inc.",
						"supplier_type": "Company",
						"supplier_group": "Raw",
						"default_currency": "CNY",
						"default_price_list": "Standard Buying",
						"payment_terms": "Net 15",
						"tax_id": "TAX-SUP-001",
						"tax_category": "Domestic",
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
		self.assertEqual(result["data"][0]["default_price_list"], "Standard Buying")
		self.assertEqual(result["data"][0]["payment_terms"], "Net 15")
		self.assertEqual(result["data"][0]["tax_id"], "TAX-SUP-001")
		self.assertEqual(result["data"][0]["tax_category"], "Domestic")
		self.assertEqual(result["meta"]["total"], 2)
		self.assertEqual(result["meta"]["total_count"], 2)
		self.assertEqual(result["pagination"]["total_count"], 2)
		self.assertEqual(result["pagination"]["page"], 1)
		self.assertEqual(result["pagination"]["page_size"], 20)
		self.assertTrue(result["pagination"]["has_more"])
		self.assertEqual(
			mock_get_list.call_args_list[0].kwargs["filters"]["creation"],
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
			default_price_list="Standard Buying",
			payment_terms="Net 15",
			tax_category="Domestic",
			tax_id="TAX-SUP-001",
			default_contact={"display_name": "张三", "phone": "13800000000"},
			default_address={"address_line1": "测试路 100 号", "city": "上海", "country": "China"},
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(supplier_doc.default_price_list, "Standard Buying")
		self.assertEqual(supplier_doc.payment_terms, "Net 15")
		self.assertEqual(supplier_doc.tax_category, "Domestic")
		self.assertEqual(supplier_doc.tax_id, "TAX-SUP-001")
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
			default_price_list="Standard Buying",
			payment_terms="Net 15",
			tax_category="Domestic",
			tax_id="TAX-SUP-001",
			default_contact={"name": "CONT-001", "display_name": "李四"},
			default_address={"name": "ADDR-001", "address_line1": "新地址", "city": "杭州", "country": "China"},
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(supplier_doc.supplier_name, "新供应商")
		self.assertEqual(supplier_doc.default_price_list, "Standard Buying")
		self.assertEqual(supplier_doc.payment_terms, "Net 15")
		self.assertEqual(supplier_doc.tax_category, "Domestic")
		self.assertEqual(supplier_doc.tax_id, "TAX-SUP-001")
		self.assertEqual(supplier_doc.save.call_count, 2)
		mock_upsert_contact.assert_called_once()
		mock_upsert_address.assert_called_once()

	@patch("myapp.services.purchase_service.run_idempotent")
	def test_disable_supplier_v2_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {"status": "success", "data": {"name": "SUP-001"}}

		result = disable_supplier_v2(supplier="SUP-001", request_id="sup-disable-001")

		self.assertEqual(result["status"], "success")
		mock_run_idempotent.assert_called_once()
