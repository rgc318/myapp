from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.order_service import (
	cancel_order_v2,
	create_order,
	create_order_v2,
	create_sales_invoice,
	get_customer_sales_context,
	get_sales_order_detail,
	get_sales_order_status_summary,
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
