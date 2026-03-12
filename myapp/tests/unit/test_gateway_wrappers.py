from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.api.gateway import (
	create_purchase_invoice,
	create_sales_invoice,
	create_order,
	create_purchase_order,
	process_purchase_return,
	process_sales_return,
	receive_purchase_order,
	search_product,
	test_remote_debug,
	update_payment_status,
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
			submit_delivery,
			create_sales_invoice,
			receive_purchase_order,
			create_purchase_invoice,
			search_product,
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
