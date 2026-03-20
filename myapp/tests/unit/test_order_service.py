from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.order_service import (
	cancel_delivery_note,
	cancel_order_v2,
	cancel_sales_invoice,
	create_order,
	create_order_v2,
	create_sales_invoice,
	get_customer_sales_context,
	get_delivery_note_detail,
	get_sales_order_detail,
	get_sales_order_status_summary,
	get_sales_invoice_detail,
	submit_delivery,
	update_order_items_v2,
	update_order_v2,
)


class TestOrderService(TestCase):
	@patch("myapp.services.order_service.frappe.db.get_value")
	@patch("myapp.services.order_service.frappe.defaults.get_user_default")
	@patch("myapp.services.order_service.frappe.get_all")
	@patch("myapp.services.order_service.frappe.get_doc")
	def test_get_customer_sales_context_builds_customer_defaults_and_recent_addresses(
		self, mock_get_doc, mock_get_all, mock_get_user_default, mock_get_value
	):
		customer_doc = frappe._dict(
			{
				"name": "Test Customer",
				"customer_name": "测试客户",
				"customer_group": "Retail",
				"territory": "China",
				"default_currency": "CNY",
				"customer_primary_contact": "CONT-001",
				"customer_primary_address": "ADDR-001",
			}
		)
		contact_doc = frappe._dict(
			{
				"name": "CONT-001",
				"full_name": "张三",
				"mobile_no": "13800138000",
				"phone": "021-12345678",
				"email_id": "zhangsan@example.com",
			}
		)
		address_doc = frappe._dict(
			{
				"name": "ADDR-001",
				"address_title": "测试客户地址",
				"address_line1": "上海市浦东新区测试路 88 号",
				"city": "Shanghai",
				"state": "Shanghai",
				"country": "China",
				"pincode": "200120",
				"address_display": "上海市浦东新区测试路 88 号",
			}
		)

		def get_doc_side_effect(doctype, name):
			mapping = {
				("Customer", "Test Customer"): customer_doc,
				("Contact", "CONT-001"): contact_doc,
				("Address", "ADDR-001"): address_doc,
			}
			return mapping[(doctype, name)]

		mock_get_doc.side_effect = get_doc_side_effect
		mock_get_all.side_effect = [
			[frappe._dict({"parent": "CONT-001"})],
			[frappe._dict({"parent": "ADDR-001"})],
			[
				frappe._dict(
					{
						"shipping_address_name": "ADDR-001",
						"address_display": "上海市浦东新区测试路 88 号",
					}
				)
			],
		]
		mock_get_user_default.side_effect = ["Test Company", None]
		mock_get_value.return_value = "Stores - TC"

		result = get_customer_sales_context("Test Customer")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["customer"]["name"], "Test Customer")
		self.assertEqual(result["data"]["default_contact"]["name"], "CONT-001")
		self.assertEqual(result["data"]["default_address"]["name"], "ADDR-001")
		self.assertEqual(len(result["data"]["recent_addresses"]), 1)
		self.assertEqual(result["data"]["suggestions"]["company"], "Test Company")
		self.assertEqual(result["data"]["suggestions"]["warehouse"], "Stores - TC")

	def test_build_fulfillment_summary_returns_partial_when_some_items_delivered(self):
		from myapp.services.order_service import _build_fulfillment_summary

		items = [
			frappe._dict({"qty": 5, "delivered_qty": 2}),
			frappe._dict({"qty": 3, "delivered_qty": 3}),
		]

		result = _build_fulfillment_summary(items)

		self.assertEqual(result["status"], "partial")
		self.assertEqual(result["total_qty"], 8)
		self.assertEqual(result["delivered_qty"], 5)
		self.assertEqual(result["remaining_qty"], 3)
		self.assertFalse(result["is_fully_delivered"])

	def test_build_payment_summary_returns_paid_when_outstanding_is_zero(self):
		from myapp.services.order_service import _build_payment_summary

		invoices = [
			frappe._dict({"grand_total": 100, "outstanding_amount": 0}),
			frappe._dict({"grand_total": 50, "outstanding_amount": 0}),
		]

		result = _build_payment_summary(invoices)

		self.assertEqual(result["status"], "paid")
		self.assertEqual(result["receivable_amount"], 150)
		self.assertEqual(result["paid_amount"], 150)
		self.assertTrue(result["is_fully_paid"])

	@patch("myapp.services.order_service.frappe.get_all")
	def test_get_latest_payment_entry_summary_returns_actual_paid_and_writeoff(self, mock_get_all):
		from myapp.services.order_service import _get_latest_payment_entry_summary

		mock_get_all.side_effect = [
			[
				frappe._dict(
					{
						"parent": "ACC-PAY-0001",
						"reference_name": "ACC-SINV-0001",
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

		result = _get_latest_payment_entry_summary(["ACC-SINV-0001"])

		self.assertEqual(result["payment_entry"], "ACC-PAY-0001")
		self.assertEqual(result["invoice_name"], "ACC-SINV-0001")
		self.assertEqual(result["writeoff_amount"], 414)
		self.assertEqual(result["actual_paid_amount"], 9046)
		self.assertEqual(result["total_actual_paid_amount"], 9046)
		self.assertEqual(result["total_writeoff_amount"], 414)

	@patch("myapp.services.order_service._serialize_delivery_note_items")
	@patch("myapp.services.order_service._build_delivery_note_references")
	@patch("myapp.services.order_service.frappe.get_doc")
	def test_get_delivery_note_detail_returns_references_and_items(
		self,
		mock_get_doc,
		mock_build_delivery_note_references,
		mock_serialize_delivery_note_items,
	):
		delivery_note = frappe._dict(
			{
				"name": "MAT-DN-0001",
				"docstatus": 1,
				"customer": "Test Customer",
				"customer_name": "测试客户",
				"company": "rgc (Demo)",
				"currency": "CNY",
				"posting_date": "2026-03-20",
				"posting_time": "10:30:00",
				"remarks": "测试发货",
				"contact_person": "CONT-001",
				"contact_display": "张三",
				"contact_phone": "13800138000",
				"shipping_address_name": "ADDR-001",
				"address_display": "上海市浦东新区测试路 88 号",
				"items": [
					frappe._dict(
						{
							"name": "DNI-0001",
							"item_code": "SKU010",
							"item_name": "Camera",
							"uom": "Nos",
							"warehouse": "Stores - RD",
							"qty": 3,
							"rate": 900,
							"amount": 2700,
							"against_sales_order": "SO-0001",
							"so_detail": "SOI-0001",
						}
					)
				],
			}
		)
		mock_get_doc.return_value = delivery_note
		mock_build_delivery_note_references.return_value = {
			"sales_orders": ["SO-0001"],
			"sales_invoices": ["ACC-SINV-0001"],
		}
		mock_serialize_delivery_note_items.return_value = [
			{
				"item_code": "SKU010",
				"item_name": "Camera",
				"qty": 3,
				"rate": 900,
				"amount": 2700,
				"warehouse": "Stores - RD",
				"uom": "Nos",
				"image": "/files/test.png",
			}
		]

		result = get_delivery_note_detail("MAT-DN-0001")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["references"]["sales_orders"], ["SO-0001"])
		self.assertEqual(result["data"]["references"]["sales_invoices"], ["ACC-SINV-0001"])
		self.assertEqual(result["data"]["items"][0]["item_code"], "SKU010")
		self.assertEqual(result["data"]["customer"]["contact_display_name"], "张三")

	@patch("myapp.services.order_service.frappe.get_all")
	def test_build_delivery_note_references_falls_back_to_sales_order_invoices(self, mock_get_all):
		from myapp.services.order_service import _build_delivery_note_references

		delivery_items = [
			frappe._dict(
				{
					"name": "DNI-0001",
					"against_sales_order": "SO-0001",
				}
			)
		]

		mock_get_all.side_effect = [
			[],
			[frappe._dict({"parent": "ACC-SINV-0009"})],
		]

		result = _build_delivery_note_references(delivery_items)

		self.assertEqual(result["sales_orders"], ["SO-0001"])
		self.assertEqual(result["sales_invoices"], ["ACC-SINV-0009"])

	@patch("myapp.services.order_service._serialize_sales_invoice_items")
	@patch("myapp.services.order_service._build_sales_invoice_references")
	@patch("myapp.services.order_service._get_latest_payment_entry_summary")
	@patch("myapp.services.order_service.frappe.get_doc")
	def test_get_sales_invoice_detail_returns_payment_and_references(
		self,
		mock_get_doc,
		mock_get_latest_payment_entry_summary,
		mock_build_sales_invoice_references,
		mock_serialize_sales_invoice_items,
	):
		sales_invoice = frappe._dict(
			{
				"name": "ACC-SINV-0001",
				"docstatus": 1,
				"customer": "Test Customer",
				"customer_name": "测试客户",
				"company": "rgc (Demo)",
				"currency": "CNY",
				"posting_date": "2026-03-20",
				"due_date": "2026-03-27",
				"remarks": "测试开票",
				"rounded_total": 2700,
				"grand_total": 2700,
				"outstanding_amount": 0,
				"contact_person": "CONT-001",
				"contact_display": "张三",
				"contact_mobile": "13800138000",
				"customer_address": "ADDR-001",
				"address_display": "上海市浦东新区测试路 88 号",
				"items": [
					frappe._dict(
						{
							"name": "SII-0001",
							"item_code": "SKU010",
							"item_name": "Camera",
							"uom": "Nos",
							"warehouse": "Stores - RD",
							"qty": 3,
							"rate": 900,
							"amount": 2700,
							"sales_order": "SO-0001",
							"so_detail": "SOI-0001",
							"delivery_note": "MAT-DN-0001",
							"dn_detail": "DNI-0001",
						}
					)
				],
			}
		)
		mock_get_doc.return_value = sales_invoice
		mock_build_sales_invoice_references.return_value = {
			"sales_orders": ["SO-0001"],
			"delivery_notes": ["MAT-DN-0001"],
		}
		mock_serialize_sales_invoice_items.return_value = [
			{
				"item_code": "SKU010",
				"item_name": "Camera",
				"qty": 3,
				"rate": 900,
				"amount": 2700,
				"warehouse": "Stores - RD",
				"uom": "Nos",
				"image": "/files/test.png",
			}
		]
		mock_get_latest_payment_entry_summary.return_value = {
			"payment_entry": "ACC-PAY-0001",
			"invoice_name": "ACC-SINV-0001",
			"allocated_amount": 100,
			"unallocated_amount": 20,
			"writeoff_amount": 5,
			"actual_paid_amount": 95,
			"total_actual_paid_amount": 95,
			"total_writeoff_amount": 5,
		}

		result = get_sales_invoice_detail("ACC-SINV-0001")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["payment"]["actual_paid_amount"], 95)
		self.assertEqual(result["data"]["payment"]["total_writeoff_amount"], 5)
		self.assertEqual(result["data"]["references"]["sales_orders"], ["SO-0001"])
		self.assertEqual(result["data"]["references"]["delivery_notes"], ["MAT-DN-0001"])
		self.assertEqual(result["data"]["items"][0]["item_code"], "SKU010")

	@patch("myapp.services.order_service.frappe.get_all")
	def test_build_sales_invoice_references_falls_back_to_sales_order_delivery_notes(self, mock_get_all):
		from myapp.services.order_service import _build_sales_invoice_references

		invoice_items = [
			frappe._dict(
				{
					"sales_order": "SO-0001",
					"delivery_note": None,
				}
			)
		]

		mock_get_all.return_value = [frappe._dict({"parent": "MAT-DN-0009"})]

		result = _build_sales_invoice_references(invoice_items)

		self.assertEqual(result["sales_orders"], ["SO-0001"])
		self.assertEqual(result["delivery_notes"], ["MAT-DN-0009"])

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

	@patch("erpnext.selling.doctype.sales_order.sales_order.make_delivery_note")
	def test_submit_delivery_updates_qty_and_price(self, mock_make_delivery_note):
		item = frappe._dict({"item_code": "ITEM-001", "so_detail": "SOI-001", "qty": 1, "rate": 10})
		dn = frappe._dict({"items": [item], "name": "DN-0002"})
		dn.get = lambda key: dn[key]
		mock_make_delivery_note.return_value = dn

		with patch("myapp.services.order_service._validate_stock_for_immediate_delivery"), patch(
			"myapp.services.order_service._insert_and_submit"
		):
			result = submit_delivery(
				"SO-0001",
				delivery_items=[{"sales_order_item": "SOI-001", "qty": 3, "price": 16}],
			)

		self.assertEqual(item.qty, 3)
		self.assertEqual(item.rate, 16)
		self.assertEqual(result["delivery_note"], "DN-0002")

	@patch("erpnext.selling.doctype.sales_order.sales_order.make_delivery_note")
	def test_submit_delivery_force_delivery_skips_stock_precheck(self, mock_make_delivery_note):
		item = frappe._dict({"item_code": "ITEM-001", "warehouse": "Stores - RD", "qty": 2})
		dn = frappe._dict({"items": [item], "name": "DN-0004"})
		dn.get = lambda key: dn[key]
		mock_make_delivery_note.return_value = dn

		with patch("myapp.services.order_service._validate_stock_for_immediate_delivery") as mock_validate, patch(
			"myapp.services.order_service._insert_and_submit_with_temporary_negative_stock"
		) as mock_force_submit:
			result = submit_delivery("SO-0001", kwargs={"force_delivery": 1})

		mock_validate.assert_not_called()
		mock_force_submit.assert_called_once_with(dn)
		self.assertTrue(result["force_delivery"])
		self.assertEqual(result["delivery_note"], "DN-0004")

	@patch("erpnext.selling.doctype.sales_order.sales_order.make_delivery_note")
	def test_submit_delivery_cleans_up_draft_delivery_note_when_submit_fails(self, mock_make_delivery_note):
		item = frappe._dict({"item_code": "ITEM-001", "warehouse": "Stores - RD", "qty": 2})
		dn = frappe._dict({"items": [item], "name": "DN-0003"})
		dn.get = lambda key: dn[key]
		mock_make_delivery_note.return_value = dn

		with patch("myapp.services.order_service._validate_stock_for_immediate_delivery"), patch(
			"myapp.services.order_service._insert_and_submit",
			side_effect=frappe.ValidationError("库存不足"),
		), patch("myapp.services.order_service.frappe.db.exists", return_value=True), patch(
			"myapp.services.order_service.frappe.db.get_value", return_value=0
		), patch("myapp.services.order_service.frappe.delete_doc") as mock_delete_doc:
			with self.assertRaisesRegex(frappe.ValidationError, "库存不足"):
				submit_delivery("SO-0001")

		mock_delete_doc.assert_called_once_with("Delivery Note", "DN-0003", ignore_permissions=True, force=1)

	@patch("erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice")
	def test_create_sales_invoice_rejects_sales_order_without_billable_items(self, mock_make_sales_invoice):
		si = frappe._dict({"items": []})
		mock_make_sales_invoice.return_value = si

		with self.assertRaisesRegex(frappe.ValidationError, "没有可开票的商品明细"):
			create_sales_invoice("SO-0001")

	@patch("erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice")
	def test_create_sales_invoice_updates_qty_and_price(self, mock_make_sales_invoice):
		item = frappe._dict({"item_code": "ITEM-001", "so_detail": "SOI-001", "qty": 1, "rate": 10})
		si = frappe._dict({"items": [item], "name": "SINV-0002"})
		si.get = lambda key: si[key]
		mock_make_sales_invoice.return_value = si

		with patch("myapp.services.order_service._insert_and_submit"):
			result = create_sales_invoice(
				"SO-0001",
				invoice_items=[{"sales_order_item": "SOI-001", "qty": 2, "price": 18}],
			)

		self.assertEqual(item.qty, 2)
		self.assertEqual(item.rate, 18)
		self.assertEqual(result["sales_invoice"], "SINV-0002")

	@patch("myapp.services.order_service.run_idempotent")
	@patch("myapp.services.order_service.frappe.db.get_value")
	@patch("myapp.services.order_service.frappe.defaults.get_user_default")
	def test_create_order_returns_cached_result_for_same_request_id(
		self, mock_get_user_default, mock_get_value, mock_run_idempotent
	):
		mock_get_user_default.return_value = "Test Company"
		mock_get_value.return_value = "Test Company"
		mock_run_idempotent.return_value = {
			"status": "success",
			"order": "SO-0009",
		}

		result = create_order(
			customer="Test Customer",
			items=[{"item_code": "ITEM-001", "qty": 2, "warehouse": "Stores - TC"}],
			request_id="req-001",
		)

		self.assertEqual(result["order"], "SO-0009")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.order_service.run_idempotent")
	def test_cancel_order_v2_returns_cached_result_for_same_request_id(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {
			"status": "success",
			"order": "SO-0008",
			"document_status": "cancelled",
		}

		result = cancel_order_v2("SO-0008", request_id="cancel-001")

		self.assertEqual(result["document_status"], "cancelled")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.order_service.get_sales_order_detail")
	@patch("myapp.services.order_service._collect_sales_order_reference_names")
	@patch("myapp.services.order_service._get_sales_order_doc_for_update")
	def test_cancel_order_v2_cancels_submitted_order_without_downstream_documents(
		self,
		mock_get_sales_order_doc_for_update,
		mock_collect_sales_order_reference_names,
		mock_get_sales_order_detail,
	):
		so = MagicMock()
		so.name = "SO-0012"
		so.docstatus = 1
		mock_get_sales_order_doc_for_update.return_value = so
		mock_collect_sales_order_reference_names.return_value = ([], [])
		mock_get_sales_order_detail.return_value = {
			"data": {"order_name": "SO-0012", "document_status": "cancelled"}
		}

		result = cancel_order_v2("SO-0012")

		so.cancel.assert_called_once_with()
		self.assertEqual(result["order"], "SO-0012")
		self.assertEqual(result["document_status"], "cancelled")

	@patch("myapp.services.order_service._collect_sales_order_reference_names")
	def test_cancel_order_v2_rejects_order_with_downstream_documents(self, mock_collect_sales_order_reference_names):
		so = frappe._dict({"name": "SO-0013", "docstatus": 1})
		mock_collect_sales_order_reference_names.return_value = (["DN-0001"], [])

		from myapp.services.order_service import _ensure_sales_order_cancellable

		with self.assertRaises(frappe.ValidationError):
			_ensure_sales_order_cancellable(so)

	@patch("myapp.services.order_service.get_delivery_note_detail")
	@patch("myapp.services.order_service.frappe.get_doc")
	def test_cancel_delivery_note_cancels_submitted_note_without_invoice_links(
		self,
		mock_get_doc,
		mock_get_delivery_note_detail,
	):
		dn = MagicMock()
		dn.name = "DN-0001"
		dn.docstatus = 1
		dn.get.side_effect = lambda field, default=None: [] if field == "items" else default
		mock_get_doc.return_value = dn
		mock_get_delivery_note_detail.return_value = {
			"data": {"delivery_note_name": "DN-0001", "document_status": "cancelled"}
		}

		result = cancel_delivery_note("DN-0001")

		dn.cancel.assert_called_once_with()
		self.assertEqual(result["delivery_note"], "DN-0001")
		self.assertEqual(result["document_status"], "cancelled")

	@patch("myapp.services.order_service.frappe.get_doc")
	def test_cancel_delivery_note_rejects_linked_sales_invoice(self, mock_get_doc):
		dn = MagicMock()
		dn.name = "DN-0002"
		dn.docstatus = 1
		dn_item = frappe._dict({"name": "DNI-001", "against_sales_order": "SO-0001"})
		dn.get.side_effect = lambda field, default=None: [dn_item] if field == "items" else default
		mock_get_doc.return_value = dn

		with patch(
			"myapp.services.order_service.frappe.get_all",
			side_effect=[
				[frappe._dict({"parent": "SINV-0001"})],
				[frappe._dict({"parent": "SINV-0001"})],
			],
		):
			with self.assertRaises(frappe.ValidationError):
				cancel_delivery_note("DN-0002")

		dn.cancel.assert_not_called()

	@patch("myapp.services.order_service.get_sales_invoice_detail")
	@patch("myapp.services.order_service.frappe.get_doc")
	def test_cancel_sales_invoice_cancels_submitted_invoice(
		self,
		mock_get_doc,
		mock_get_sales_invoice_detail,
	):
		si = MagicMock()
		si.name = "SINV-0001"
		si.docstatus = 1
		si.get.side_effect = lambda field, default=None: [] if field == "items" else default
		mock_get_doc.return_value = si
		mock_get_sales_invoice_detail.return_value = {
			"data": {"sales_invoice_name": "SINV-0001", "document_status": "cancelled"}
		}

		result = cancel_sales_invoice("SINV-0001")

		si.cancel.assert_called_once_with()
		self.assertEqual(result["sales_invoice"], "SINV-0001")
		self.assertEqual(result["document_status"], "cancelled")

	@patch("myapp.services.order_service.frappe.get_doc")
	def test_cancel_sales_invoice_maps_linked_payment_error(self, mock_get_doc):
		si = MagicMock()
		si.name = "SINV-0002"
		si.docstatus = 1
		si.get.side_effect = lambda field, default=None: [] if field == "items" else default
		si.cancel.side_effect = frappe.LinkExistsError("linked payment")
		mock_get_doc.return_value = si

		with self.assertRaises(frappe.ValidationError):
			cancel_sales_invoice("SINV-0002")

	@patch("myapp.services.order_service.run_idempotent")
	@patch("myapp.services.order_service._commit_sales_order_context_update")
	@patch("myapp.services.order_service._get_sales_order_doc_for_update")
	def test_update_order_v2_updates_snapshot_and_meta(
		self, mock_get_order, mock_commit_order, mock_run_idempotent
	):
		so = frappe._dict(
			{
				"name": "SO-0002",
				"docstatus": 1,
				"company": "Test Company",
				"delivery_date": "2026-03-18",
				"transaction_date": "2026-03-18",
				"remarks": None,
				"contact_person": None,
				"contact_display": None,
				"contact_mobile": None,
				"contact_phone": None,
				"contact_email": None,
				"shipping_address_name": None,
				"customer_address": None,
				"address_display": None,
			}
		)
		so.meta = MagicMock()
		so.meta.has_field.return_value = True
		so.set = lambda field, value: so.__setitem__(field, value)
		so.get = lambda field, default=None: so[field] if field in so else default
		mock_get_order.return_value = so
		mock_commit_order.return_value = so
		mock_run_idempotent.side_effect = lambda _scope, _request_id, callback: callback()

		result = update_order_v2(
			order_name="SO-0002",
			delivery_date="2026-03-20",
			remarks="updated",
			customer_info={"contact_display_name": "张三", "contact_phone": "13800138000"},
			shipping_info={"receiver_name": "李四", "shipping_address_text": "上海市测试路 1 号"},
			request_id="upd-001",
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["order"], "SO-0002")
		self.assertEqual(result["snapshot"]["applied"]["contact_display"], "张三")
		self.assertEqual(result["snapshot"]["applied"]["shipping_address_text"], "上海市测试路 1 号")
		self.assertEqual(so.delivery_date, "2026-03-20")
		self.assertEqual(so.remarks, "updated")
		mock_commit_order.assert_called_once()

	@patch("myapp.services.order_service.run_idempotent")
	@patch("myapp.services.order_service._serialize_order_items")
	@patch("myapp.services.order_service._insert_and_submit")
	@patch("myapp.services.order_service._prepare_sales_order_for_item_replacement")
	@patch("myapp.services.order_service._build_sales_order_item")
	@patch("myapp.services.order_service._ensure_sales_order_items_editable")
	@patch("myapp.services.order_service._get_sales_order_doc_for_update")
	def test_update_order_items_v2_replaces_order_items(
		self,
		mock_get_order,
		mock_ensure_editable,
		mock_build_item,
		mock_prepare_replace,
		mock_insert_and_submit,
		mock_serialize_items,
		mock_run_idempotent,
	):
		so = MagicMock()
		so.name = "SO-0003"
		so.docstatus = 1
		so.company = "Test Company"
		so.delivery_date = "2026-03-18"
		items_holder = []
		so.get.side_effect = lambda field, default=None: items_holder if field == "items" else getattr(so, field, default)
		so.set.side_effect = lambda field, value: items_holder.clear() if field == "items" else None
		so.append.side_effect = lambda field, value: items_holder.append(frappe._dict(value))
		mock_get_order.return_value = so
		mock_prepare_replace.return_value = (so, "SO-0003")
		mock_build_item.side_effect = [
			{"item_code": "ITEM-001", "qty": 2, "warehouse": "Stores - TC", "delivery_date": "2026-03-18"},
			{"item_code": "ITEM-002", "qty": 1, "warehouse": "Stores - TC", "delivery_date": "2026-03-18"},
		]
		mock_serialize_items.return_value = [{"item_code": "ITEM-001"}, {"item_code": "ITEM-002"}]
		mock_run_idempotent.side_effect = lambda _scope, _request_id, callback: callback()

		result = update_order_items_v2(
			order_name="SO-0003",
			items=[
				{"item_code": "ITEM-001", "qty": 2, "warehouse": "Stores - TC"},
				{"item_code": "ITEM-002", "qty": 1, "warehouse": "Stores - TC"},
			],
			request_id="item-upd-001",
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["order"], "SO-0003")
		self.assertEqual(len(items_holder), 2)
		mock_ensure_editable.assert_called_once_with(so)
		mock_insert_and_submit.assert_called_once_with(so)

	@patch("myapp.services.order_service.run_idempotent")
	@patch("myapp.services.order_service._commit_sales_order_context_update")
	@patch("myapp.services.order_service._insert_and_submit")
	@patch("myapp.services.order_service._build_sales_order_item")
	@patch("myapp.services.order_service._validate_order_inputs")
	@patch("myapp.services.order_service.frappe.new_doc")
	@patch("myapp.services.order_service.frappe.defaults.get_user_default")
	def test_create_order_v2_commits_shipping_snapshot_after_insert(
		self,
		mock_get_user_default,
		mock_new_doc,
		mock_validate_inputs,
		mock_build_item,
		mock_insert_and_submit,
		mock_commit_context,
		mock_run_idempotent,
	):
		mock_get_user_default.return_value = "Test Company"
		so = frappe._dict({})
		so.meta = MagicMock()
		so.meta.has_field.return_value = True
		so.set = lambda field, value: so.__setitem__(field, value)
		so.get = lambda field, default=None: so[field] if field in so else default
		so.append = lambda field, value: so.setdefault(field, []).append(frappe._dict(value))
		so.name = "SO-NEW-001"
		so.docstatus = 1
		mock_new_doc.return_value = so
		mock_build_item.return_value = {"item_code": "ITEM-001", "qty": 1, "warehouse": "Stores - TC"}
		mock_commit_context.return_value = so
		mock_run_idempotent.side_effect = lambda _scope, _request_id, callback: callback()

		result = create_order_v2(
			customer="Test Customer",
			items=[{"item_code": "ITEM-001", "qty": 1, "warehouse": "Stores - TC"}],
			company="Test Company",
			shipping_info={"shipping_address_text": "北京市朝阳区测试路 100 号"},
			request_id="create-v2-001",
		)

		self.assertEqual(result["status"], "success")
		mock_insert_and_submit.assert_called_once_with(so)
		mock_commit_context.assert_called_once()
		self.assertIn("address_display", mock_commit_context.call_args.args[1])

	@patch("erpnext.selling.doctype.sales_order.sales_order.make_delivery_note")
	@patch("myapp.services.order_service.run_idempotent")
	@patch("myapp.services.order_service._apply_sales_order_context_to_target_doc")
	@patch("myapp.services.order_service._insert_and_submit")
	@patch("myapp.services.order_service._validate_stock_for_immediate_delivery")
	@patch("myapp.services.order_service.frappe.get_doc")
	def test_submit_delivery_applies_source_order_context(
		self,
		mock_get_doc,
		mock_validate_stock,
		mock_insert_and_submit,
		mock_apply_context,
		mock_run_idempotent,
		mock_make_delivery_note,
	):
		so = frappe._dict({"name": "SO-0001", "address_display": "北京市朝阳区测试路 100 号"})
		dn = frappe._dict({"name": "DN-0001", "items": [frappe._dict({"item_code": "ITEM-001", "warehouse": "Stores - TC", "qty": 1})]})
		mock_get_doc.return_value = so
		mock_make_delivery_note.return_value = dn
		mock_run_idempotent.side_effect = lambda _scope, _request_id, callback: callback()

		result = submit_delivery("SO-0001")

		self.assertEqual(result["delivery_note"], "DN-0001")
		mock_apply_context.assert_called_once_with(so, dn)
		mock_insert_and_submit.assert_called_once_with(dn)
		mock_validate_stock.assert_called_once()

	@patch("erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice")
	@patch("myapp.services.order_service.run_idempotent")
	@patch("myapp.services.order_service._apply_sales_order_context_to_target_doc")
	@patch("myapp.services.order_service._insert_and_submit")
	@patch("myapp.services.order_service.frappe.get_doc")
	def test_create_sales_invoice_applies_source_order_context(
		self,
		mock_get_doc,
		mock_insert_and_submit,
		mock_apply_context,
		mock_run_idempotent,
		mock_make_sales_invoice,
	):
		so = frappe._dict({"name": "SO-0001", "address_display": "北京市朝阳区测试路 100 号"})
		si = frappe._dict({"name": "SINV-0001", "items": [frappe._dict({"item_code": "ITEM-001"})]})
		mock_get_doc.return_value = so
		mock_make_sales_invoice.return_value = si
		mock_run_idempotent.side_effect = lambda _scope, _request_id, callback: callback()

		result = create_sales_invoice("SO-0001")

		self.assertEqual(result["sales_invoice"], "SINV-0001")
		mock_apply_context.assert_called_once_with(so, si)
		mock_insert_and_submit.assert_called_once_with(si)

	@patch("myapp.services.order_service.run_idempotent")
	@patch("myapp.services.order_service.frappe.db.get_value")
	@patch("myapp.services.order_service.frappe.defaults.get_user_default")
	def test_create_order_immediate_uses_same_idempotent_runner(
		self, mock_get_user_default, mock_get_value, mock_run_idempotent
	):
		mock_get_user_default.return_value = "Test Company"
		mock_get_value.return_value = "Test Company"
		mock_run_idempotent.return_value = {
			"status": "success",
			"order": "SO-0010",
			"delivery_note": "DN-0010",
			"sales_invoice": "SINV-0010",
		}

		result = create_order(
			customer="Test Customer",
			items=[{"item_code": "ITEM-001", "qty": 2, "warehouse": "Stores - TC"}],
			immediate=1,
			request_id="req-002",
		)

		self.assertEqual(result["delivery_note"], "DN-0010")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.order_service.run_idempotent")
	def test_submit_delivery_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {"status": "success", "delivery_note": "DN-0010"}

		result = submit_delivery("SO-0001", kwargs={"request_id": "dn-001"})

		self.assertEqual(result["delivery_note"], "DN-0010")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.order_service.run_idempotent")
	def test_create_sales_invoice_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {"status": "success", "sales_invoice": "SINV-0010"}

		result = create_sales_invoice("SO-0001", kwargs={"request_id": "si-001"})

		self.assertEqual(result["sales_invoice"], "SINV-0010")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.order_service.frappe.get_all")
	@patch("myapp.services.order_service.frappe.get_doc")
	def test_get_sales_order_detail_aggregates_statuses(self, mock_get_doc, mock_get_all):
		so = frappe._dict(
			{
				"name": "SO-0001",
				"docstatus": 1,
				"customer": "Test Customer",
				"customer_name": "测试客户",
				"company": "Test Company",
				"currency": "CNY",
				"transaction_date": "2026-03-17",
				"delivery_date": "2026-03-18",
				"rounded_total": 200,
				"remarks": "测试备注",
				"items": [
					frappe._dict(
						{
							"name": "SOI-001",
							"item_code": "ITEM-001",
							"item_name": "商品一",
							"qty": 10,
							"delivered_qty": 6,
							"rate": 20,
							"amount": 200,
							"warehouse": "Stores - TC",
						}
					)
				],
			}
		)
		so.get = lambda key, default=None: so[key] if key in so else default
		contact_doc = frappe._dict(
			{
				"full_name": "张三",
				"mobile_no": "13800000000",
				"email_id": "zhangsan@example.com",
			}
		)
		address_doc = frappe._dict(
			{
				"address_display": "测试市测试路 88 号",
				"address_line1": "测试路 88 号",
				"city": "测试市",
				"state": "测试省",
				"country": "China",
				"pincode": "200000",
			}
		)

		def fake_get_doc(doctype, name):
			if doctype == "Sales Order":
				return so
			if doctype == "Contact":
				return contact_doc
			if doctype == "Address":
				return address_doc
			raise AssertionError(f"Unexpected get_doc call: {doctype}, {name}")

		mock_get_doc.side_effect = fake_get_doc
		mock_get_all.side_effect = [
			[frappe._dict({"parent": "DN-0001"})],
			[frappe._dict({"parent": "SINV-0001"})],
			[
				frappe._dict(
					{
						"name": "SINV-0001",
						"grand_total": 200,
						"rounded_total": 200,
						"base_rounded_total": 200,
						"outstanding_amount": 50,
					}
				)
			],
			[
				frappe._dict(
					{
						"parent": "ACC-PAY-0001",
						"reference_name": "SINV-0001",
						"allocated_amount": 150,
						"modified": "2026-03-20 10:00:00",
					}
				)
			],
			[
				frappe._dict(
					{
						"name": "ACC-PAY-0001",
						"paid_amount": 120,
						"received_amount": 120,
						"unallocated_amount": 0,
						"difference_amount": 30,
						"modified": "2026-03-20 10:00:00",
					}
				)
			],
			[frappe._dict({"name": "ITEM-001", "image": "/files/item-001.png"})],
		]

		result = get_sales_order_detail("SO-0001")

		self.assertEqual(result["data"]["order_name"], "SO-0001")
		self.assertEqual(result["data"]["fulfillment"]["status"], "partial")
		self.assertEqual(result["data"]["delivery"]["status"], "partial")
		self.assertEqual(result["data"]["payment"]["status"], "partial")
		self.assertEqual(result["data"]["completion"]["status"], "open")
		self.assertTrue(result["data"]["actions"]["can_submit_delivery"])
		self.assertTrue(result["data"]["actions"]["can_record_payment"])
		self.assertFalse(result["data"]["actions"]["can_create_sales_invoice"])
		self.assertEqual(result["data"]["payment"]["actual_paid_amount"], 120)
		self.assertEqual(result["data"]["payment"]["total_writeoff_amount"], 30)
		self.assertEqual(result["data"]["customer"]["contact_display_name"], "张三")
		self.assertEqual(result["data"]["shipping"]["city"], "测试市")
		self.assertEqual(result["data"]["items"][0]["image"], "/files/item-001.png")

	@patch("myapp.services.order_service.get_sales_order_detail")
	@patch("myapp.services.order_service.frappe.get_all")
	def test_get_sales_order_status_summary_returns_list(self, mock_get_all, mock_get_sales_order_detail):
		mock_get_all.return_value = [
			frappe._dict(
				{
					"name": "SO-0001",
					"customer": "Test Customer",
					"customer_name": "测试客户",
					"transaction_date": "2026-03-17",
					"company": "Test Company",
					"docstatus": 1,
					"rounded_total": 200,
					"grand_total": 200,
					"modified": "2026-03-17 10:00:00",
				}
			)
		]
		mock_get_sales_order_detail.return_value = {
			"status": "success",
			"data": {
				"fulfillment": {"status": "partial"},
				"payment": {"status": "partial", "outstanding_amount": 50},
				"completion": {"status": "open"},
			},
		}

		result = get_sales_order_status_summary(customer="Test Customer", company="Test Company", limit=5)

		self.assertEqual(len(result["data"]), 1)
		self.assertEqual(result["data"][0]["order_name"], "SO-0001")
		self.assertEqual(result["data"][0]["payment"]["status"], "partial")
		self.assertEqual(result["meta"]["filters"]["customer"], "Test Customer")
