from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.api.gateway import (
	create_purchase_invoice,
	create_purchase_invoice_from_receipt,
	create_product_and_stock,
	create_sales_invoice,
	create_order,
	create_purchase_order,
	get_sales_order_detail,
	get_sales_order_status_summary,
	get_customer_sales_context,
	process_purchase_return,
	process_sales_return,
	receive_purchase_order,
	search_product,
	search_product_v2,
	test_remote_debug,
	update_payment_status,
	update_order_items_v2,
	update_order_v2,
	record_supplier_payment,
	submit_delivery,
	confirm_pending_document,
)


class TestGatewayWrappers(TestCase):
	def test_gateway_methods_are_not_exposed_to_guest(self):
		for method in (
			test_remote_debug,
			create_order,
			create_purchase_order,
			get_sales_order_detail,
			get_sales_order_status_summary,
			get_customer_sales_context,
			update_order_v2,
			update_order_items_v2,
			submit_delivery,
			create_sales_invoice,
			receive_purchase_order,
			create_purchase_invoice,
			create_purchase_invoice_from_receipt,
			search_product,
			search_product_v2,
			create_product_and_stock,
			confirm_pending_document,
			update_payment_status,
			record_supplier_payment,
			process_sales_return,
			process_purchase_return,
		):
			self.assertNotIn(method, frappe.guest_methods)

	@patch("myapp.api.gateway.submit_delivery_service")
	def test_submit_delivery_passes_top_level_request_id_to_service(self, mock_submit_delivery_service):
		mock_submit_delivery_service.return_value = {
			"status": "success",
			"delivery_note": "DN-0001",
		}

		submit_delivery("SO-0001", request_id="dn-001")

		mock_submit_delivery_service.assert_called_once_with(
			order_name="SO-0001",
			delivery_items=None,
			kwargs={"request_id": "dn-001"},
		)

	@patch("myapp.api.gateway.create_sales_invoice_service")
	def test_create_sales_invoice_passes_top_level_request_id_to_service(
		self, mock_create_sales_invoice_service
	):
		mock_create_sales_invoice_service.return_value = {
			"status": "success",
			"sales_invoice": "SINV-0001",
		}

		create_sales_invoice("SO-0001", request_id="si-001")

		mock_create_sales_invoice_service.assert_called_once_with(
			source_name="SO-0001",
			invoice_items=None,
			kwargs={"request_id": "si-001"},
		)

	@patch("myapp.api.gateway.receive_purchase_order_service")
	def test_receive_purchase_order_passes_top_level_request_id_to_service(
		self, mock_receive_purchase_order_service
	):
		mock_receive_purchase_order_service.return_value = {
			"status": "success",
			"purchase_receipt": "MAT-PRE-0001",
		}

		receive_purchase_order("PO-0001", request_id="pr-001")

		mock_receive_purchase_order_service.assert_called_once_with(
			order_name="PO-0001",
			receipt_items=None,
			kwargs={"request_id": "pr-001"},
		)

	@patch("myapp.api.gateway.create_purchase_invoice_service")
	def test_create_purchase_invoice_passes_top_level_request_id_to_service(
		self, mock_create_purchase_invoice_service
	):
		mock_create_purchase_invoice_service.return_value = {
			"status": "success",
			"purchase_invoice": "ACC-PINV-0001",
		}

		create_purchase_invoice("PO-0001", request_id="pi-001")

		mock_create_purchase_invoice_service.assert_called_once_with(
			source_name="PO-0001",
			invoice_items=None,
			kwargs={"request_id": "pi-001"},
		)

	@patch("myapp.api.gateway.create_purchase_invoice_from_receipt_service")
	def test_create_purchase_invoice_from_receipt_passes_top_level_request_id_to_service(
		self, mock_create_purchase_invoice_from_receipt_service
	):
		mock_create_purchase_invoice_from_receipt_service.return_value = {
			"status": "success",
			"purchase_invoice": "ACC-PINV-0002",
		}

		create_purchase_invoice_from_receipt("MAT-PRE-0001", request_id="pi-pr-001")

		mock_create_purchase_invoice_from_receipt_service.assert_called_once_with(
			receipt_name="MAT-PRE-0001",
			invoice_items=None,
			kwargs={"request_id": "pi-pr-001"},
		)

	@patch("myapp.api.gateway.record_supplier_payment_service")
	def test_record_supplier_payment_passes_request_id_to_service(self, mock_record_supplier_payment_service):
		mock_record_supplier_payment_service.return_value = {
			"status": "success",
			"payment_entry": "ACC-PAY-0001",
		}

		record_supplier_payment("PINV-0001", 100, request_id="pay-001")

		mock_record_supplier_payment_service.assert_called_once_with(
			reference_name="PINV-0001",
			paid_amount=100,
			request_id="pay-001",
		)

	@patch("myapp.api.gateway.process_purchase_return_service")
	def test_process_purchase_return_passes_request_id_to_service(self, mock_process_purchase_return_service):
		mock_process_purchase_return_service.return_value = {
			"status": "success",
			"return_document": "PINV-RET-0001",
		}

		process_purchase_return("Purchase Invoice", "PINV-0001", request_id="ret-001")

		mock_process_purchase_return_service.assert_called_once_with(
			source_doctype="Purchase Invoice",
			source_name="PINV-0001",
			return_items=None,
			request_id="ret-001",
		)

	@patch("myapp.api.gateway.create_product_and_stock_service")
	def test_create_product_and_stock_passes_fields_to_service(self, mock_create_product_and_stock_service):
		mock_create_product_and_stock_service.return_value = {
			"status": "success",
			"data": {"item_code": "NEW-ITEM"},
		}

		create_product_and_stock(
			item_name="临时矿泉水",
			opening_qty=6,
			default_warehouse="Stores - RD",
			standard_rate=12,
			request_id="product-001",
		)

		mock_create_product_and_stock_service.assert_called_once_with(
			item_name="临时矿泉水",
			warehouse=None,
			opening_qty=6,
			default_warehouse="Stores - RD",
			standard_rate=12,
			request_id="product-001",
		)

	@patch("myapp.api.gateway.get_sales_order_detail_service")
	def test_get_sales_order_detail_passes_order_name_to_service(self, mock_get_sales_order_detail_service):
		mock_get_sales_order_detail_service.return_value = {
			"status": "success",
			"data": {"order_name": "SO-0001"},
		}

		get_sales_order_detail("SO-0001")

		mock_get_sales_order_detail_service.assert_called_once_with(order_name="SO-0001")

	@patch("myapp.api.gateway.search_product_v2_service")
	def test_search_product_v2_passes_search_filters_to_service(self, mock_search_product_v2_service):
		mock_search_product_v2_service.return_value = {
			"status": "success",
			"data": [],
		}

		search_product_v2(
			"可乐",
			search_fields=["item_name", "nickname"],
			sort_by="price",
			sort_order="desc",
			in_stock_only=1,
		)

		mock_search_product_v2_service.assert_called_once_with(
			search_key="可乐",
			price_list="Standard Selling",
			currency=None,
			warehouse=None,
			company=None,
			limit=20,
			search_fields=["item_name", "nickname"],
			sort_by="price",
			sort_order="desc",
			in_stock_only=1,
		)

	@patch("myapp.api.gateway.get_sales_order_status_summary_service")
	def test_get_sales_order_status_summary_passes_filters_to_service(
		self, mock_get_sales_order_status_summary_service
	):
		mock_get_sales_order_status_summary_service.return_value = {
			"status": "success",
			"data": [],
		}

		get_sales_order_status_summary(customer="Test Customer", company="Test Company", limit=5)

		mock_get_sales_order_status_summary_service.assert_called_once_with(
			customer="Test Customer",
			company="Test Company",
			limit=5,
		)

	@patch("myapp.api.gateway.update_order_v2_service")
	def test_update_order_v2_passes_fields_to_service(self, mock_update_order_v2_service):
		mock_update_order_v2_service.return_value = {
			"status": "success",
			"order": "SO-0001",
		}

		update_order_v2(
			"SO-0001",
			delivery_date="2026-03-20",
			remarks="updated",
			customer_info={"contact_phone": "13800138000"},
		)

		mock_update_order_v2_service.assert_called_once_with(
			order_name="SO-0001",
			delivery_date="2026-03-20",
			remarks="updated",
			customer_info={"contact_phone": "13800138000"},
		)

	@patch("myapp.api.gateway.update_order_items_v2_service")
	def test_update_order_items_v2_passes_items_to_service(self, mock_update_order_items_v2_service):
		mock_update_order_items_v2_service.return_value = {
			"status": "success",
			"order": "SO-0001",
		}

		update_order_items_v2(
			"SO-0001",
			items=[{"item_code": "ITEM-001", "qty": 2, "warehouse": "Stores - TC"}],
			request_id="upd-items-001",
		)

		mock_update_order_items_v2_service.assert_called_once_with(
			order_name="SO-0001",
			items=[{"item_code": "ITEM-001", "qty": 2, "warehouse": "Stores - TC"}],
			request_id="upd-items-001",
		)

	@patch("myapp.api.gateway.get_customer_sales_context_service")
	def test_get_customer_sales_context_passes_customer_to_service(
		self, mock_get_customer_sales_context_service
	):
		mock_get_customer_sales_context_service.return_value = {
			"status": "success",
			"data": {"customer": {"name": "Test Customer"}},
		}

		get_customer_sales_context("Test Customer")

		mock_get_customer_sales_context_service.assert_called_once_with(customer="Test Customer")
