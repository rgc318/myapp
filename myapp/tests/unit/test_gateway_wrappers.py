from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.api.gateway import (
	cancel_delivery_note,
	cancel_payment_entry,
	cancel_purchase_invoice_v2,
	cancel_purchase_order_v2,
	cancel_purchase_receipt_v2,
	cancel_order_v2,
	cancel_sales_invoice,
	cancel_supplier_payment,
	create_customer_v2,
	create_product_v2,
	create_supplier_v2,
	create_purchase_invoice,
	create_purchase_invoice_from_receipt,
	download_print_file_v1,
	get_print_file_v1,
	get_print_preview_v1,
	get_business_report_overview_v1,
	get_business_report_v1,
	get_cashflow_report_v1,
	get_purchase_report_v1,
	get_purchase_invoice_detail_v2,
	get_purchase_order_detail_v2,
	get_purchase_order_status_summary,
	get_purchase_receipt_detail_v2,
	get_receivable_payable_report_v1,
	get_return_source_context_v2,
	get_sales_report_v1,
	list_cashflow_entries_v1,
	search_purchase_orders_v2,
	create_product_and_stock,
	create_sales_invoice,
	create_uom_v2,
	create_order,
	create_purchase_order,
	quick_cancel_purchase_order_v2,
	quick_create_purchase_order_v2,
	delete_uom_v2,
	disable_customer_v2,
	disable_supplier_v2,
	disable_uom_v2,
	get_customer_detail_v2,
	get_delivery_note_detail_v2,
	get_product_detail_v2,
	get_sales_order_detail,
	get_sales_invoice_detail_v2,
	get_sales_order_status_summary,
	search_sales_orders_v2,
	get_customer_sales_context,
	get_supplier_detail_v2,
	get_supplier_purchase_context,
	get_uom_detail_v2,
	list_customers_v2,
	list_products_v2,
	list_suppliers_v2,
	list_uoms_v2,
	process_purchase_return,
	process_sales_return,
	receive_purchase_order,
	search_product,
	search_product_v2,
	test_remote_debug,
	update_payment_status,
	update_purchase_order_items_v2,
	update_purchase_order_v2,
	update_supplier_v2,
	update_customer_v2,
	update_product_v2,
	update_uom_v2,
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
			quick_create_purchase_order_v2,
			download_print_file_v1,
			get_print_file_v1,
			get_print_preview_v1,
			get_business_report_overview_v1,
			get_business_report_v1,
			get_cashflow_report_v1,
			get_sales_report_v1,
			get_purchase_report_v1,
			get_receivable_payable_report_v1,
			list_cashflow_entries_v1,
			get_purchase_order_detail_v2,
			get_purchase_order_status_summary,
			search_purchase_orders_v2,
			get_purchase_receipt_detail_v2,
			get_purchase_invoice_detail_v2,
			get_return_source_context_v2,
			get_sales_order_detail,
			get_sales_order_status_summary,
			search_sales_orders_v2,
			get_customer_sales_context,
			get_supplier_purchase_context,
			cancel_delivery_note,
			cancel_payment_entry,
			cancel_purchase_invoice_v2,
			cancel_purchase_order_v2,
			cancel_purchase_receipt_v2,
			quick_cancel_purchase_order_v2,
				cancel_order_v2,
				cancel_sales_invoice,
				cancel_supplier_payment,
				create_customer_v2,
				create_supplier_v2,
				create_uom_v2,
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
			get_product_detail_v2,
			get_customer_detail_v2,
			get_supplier_detail_v2,
			get_delivery_note_detail_v2,
			get_sales_invoice_detail_v2,
			update_product_v2,
			list_customers_v2,
				list_suppliers_v2,
				list_uoms_v2,
				disable_customer_v2,
				disable_supplier_v2,
				disable_uom_v2,
			delete_uom_v2,
			get_uom_detail_v2,
			confirm_pending_document,
				update_payment_status,
				update_purchase_order_v2,
				update_purchase_order_items_v2,
				update_supplier_v2,
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

	@patch("myapp.api.gateway.cancel_delivery_note_service")
	def test_cancel_delivery_note_passes_request_id_to_service(self, mock_cancel_delivery_note_service):
		mock_cancel_delivery_note_service.return_value = {
			"status": "success",
			"delivery_note": "DN-0001",
		}

		cancel_delivery_note("DN-0001", request_id="dn-cancel-001")

		mock_cancel_delivery_note_service.assert_called_once_with(
			delivery_note_name="DN-0001",
			request_id="dn-cancel-001",
		)

	@patch("myapp.api.gateway.cancel_sales_invoice_service")
	def test_cancel_sales_invoice_passes_request_id_to_service(self, mock_cancel_sales_invoice_service):
		mock_cancel_sales_invoice_service.return_value = {
			"status": "success",
			"sales_invoice": "SINV-0001",
		}

		cancel_sales_invoice("SINV-0001", request_id="si-cancel-001")

		mock_cancel_sales_invoice_service.assert_called_once_with(
			sales_invoice_name="SINV-0001",
			request_id="si-cancel-001",
		)

	@patch("myapp.api.gateway.cancel_payment_entry_service")
	def test_cancel_payment_entry_passes_request_id_to_service(self, mock_cancel_payment_entry_service):
		mock_cancel_payment_entry_service.return_value = {
			"status": "success",
			"payment_entry": "ACC-PAY-0001",
		}

		cancel_payment_entry("ACC-PAY-0001", request_id="pay-cancel-001")

		mock_cancel_payment_entry_service.assert_called_once_with(
			payment_entry_name="ACC-PAY-0001",
			request_id="pay-cancel-001",
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

	@patch("myapp.api.gateway.get_purchase_order_detail_v2_service")
	def test_get_purchase_order_detail_v2_passes_name_to_service(self, mock_get_purchase_order_detail_v2_service):
		mock_get_purchase_order_detail_v2_service.return_value = {
			"status": "success",
			"data": {"purchase_order_name": "PO-0001"},
		}

		get_purchase_order_detail_v2("PO-0001")

		mock_get_purchase_order_detail_v2_service.assert_called_once_with(order_name="PO-0001")

	@patch("myapp.api.gateway.get_purchase_order_status_summary_service")
	def test_get_purchase_order_status_summary_passes_filters_to_service(
		self, mock_get_purchase_order_status_summary_service
	):
		mock_get_purchase_order_status_summary_service.return_value = {"status": "success", "data": []}

		get_purchase_order_status_summary(
			supplier="SUP-001",
			company="Test Company",
			limit=5,
			date_from="2026-03-01",
			date_to="2026-03-31",
		)

		mock_get_purchase_order_status_summary_service.assert_called_once_with(
			supplier="SUP-001",
			company="Test Company",
			limit=5,
			date_from="2026-03-01",
			date_to="2026-03-31",
		)

	@patch("myapp.api.gateway.search_purchase_orders_v2_service")
	def test_search_purchase_orders_v2_passes_filters_to_service(self, mock_search_purchase_orders_v2_service):
		mock_search_purchase_orders_v2_service.return_value = {"status": "success", "data": {"items": []}}

		search_purchase_orders_v2(
			search_key="PO",
			supplier="SUP-001",
			company="Test Company",
			date_from="2026-03-01",
			date_to="2026-03-31",
			status_filter="unfinished",
			exclude_cancelled=True,
			sort_by="unfinished_first",
			limit=8,
			start=5,
		)

		mock_search_purchase_orders_v2_service.assert_called_once_with(
			search_key="PO",
			supplier="SUP-001",
			company="Test Company",
			date_from="2026-03-01",
			date_to="2026-03-31",
			status_filter="unfinished",
			exclude_cancelled=True,
			sort_by="unfinished_first",
			limit=8,
			start=5,
		)

	@patch("myapp.api.gateway.get_purchase_receipt_detail_v2_service")
	def test_get_purchase_receipt_detail_v2_passes_name_to_service(self, mock_get_purchase_receipt_detail_v2_service):
		mock_get_purchase_receipt_detail_v2_service.return_value = {
			"status": "success",
			"data": {"purchase_receipt_name": "PR-0001"},
		}

		get_purchase_receipt_detail_v2("PR-0001")

		mock_get_purchase_receipt_detail_v2_service.assert_called_once_with(receipt_name="PR-0001")

	@patch("myapp.api.gateway.get_purchase_invoice_detail_v2_service")
	def test_get_purchase_invoice_detail_v2_passes_name_to_service(self, mock_get_purchase_invoice_detail_v2_service):
		mock_get_purchase_invoice_detail_v2_service.return_value = {
			"status": "success",
			"data": {"purchase_invoice_name": "PINV-0001"},
		}

		get_purchase_invoice_detail_v2("PINV-0001")

		mock_get_purchase_invoice_detail_v2_service.assert_called_once_with(invoice_name="PINV-0001")

	@patch("myapp.api.gateway.get_return_source_context_v2_service")
	def test_get_return_source_context_v2_passes_args_to_service(self, mock_get_return_source_context_v2_service):
		mock_get_return_source_context_v2_service.return_value = {
			"status": "success",
			"data": {"source_name": "ACC-SINV-0001"},
		}

		get_return_source_context_v2("Sales Invoice", "ACC-SINV-0001")

		mock_get_return_source_context_v2_service.assert_called_once_with(
			source_doctype="Sales Invoice",
			source_name="ACC-SINV-0001",
		)

	@patch("myapp.api.gateway.get_supplier_purchase_context_service")
	def test_get_supplier_purchase_context_passes_supplier_to_service(self, mock_get_supplier_purchase_context_service):
		mock_get_supplier_purchase_context_service.return_value = {
			"status": "success",
			"data": {"supplier": {"name": "SUP-001"}},
		}

		get_supplier_purchase_context("SUP-001")

		mock_get_supplier_purchase_context_service.assert_called_once_with(supplier="SUP-001", company=None)

	@patch("myapp.api.gateway.list_suppliers_v2_service")
	def test_list_suppliers_v2_passes_filters_to_service(self, mock_list_suppliers_v2_service):
		mock_list_suppliers_v2_service.return_value = {"status": "success", "data": []}

		list_suppliers_v2(
			search_key="MA",
			supplier_group="Raw",
			disabled=0,
			date_from="2026-03-01",
			date_to="2026-03-31",
			limit=10,
			start=5,
		)

		mock_list_suppliers_v2_service.assert_called_once_with(
			search_key="MA",
			supplier_group="Raw",
			disabled=0,
			date_from="2026-03-01",
			date_to="2026-03-31",
			limit=10,
			start=5,
			sort_by="modified",
			sort_order="desc",
		)

	@patch("myapp.api.gateway.get_supplier_detail_v2_service")
	def test_get_supplier_detail_v2_passes_supplier_to_service(self, mock_get_supplier_detail_v2_service):
		mock_get_supplier_detail_v2_service.return_value = {
			"status": "success",
			"data": {"name": "SUP-001"},
		}

		get_supplier_detail_v2("SUP-001")

		mock_get_supplier_detail_v2_service.assert_called_once_with(supplier="SUP-001")

	@patch("myapp.api.gateway.update_purchase_order_v2_service")
	def test_update_purchase_order_v2_passes_payload_to_service(self, mock_update_purchase_order_v2_service):
		mock_update_purchase_order_v2_service.return_value = {"status": "success", "purchase_order": "PO-0001"}

		update_purchase_order_v2("PO-0001", schedule_date="2026-03-27", request_id="po-update-001")

		mock_update_purchase_order_v2_service.assert_called_once_with(
			order_name="PO-0001",
			schedule_date="2026-03-27",
			request_id="po-update-001",
		)

	@patch("myapp.api.gateway.update_purchase_order_items_v2_service")
	def test_update_purchase_order_items_v2_passes_payload_to_service(self, mock_update_purchase_order_items_v2_service):
		mock_update_purchase_order_items_v2_service.return_value = {"status": "success", "purchase_order": "PO-0002"}

		update_purchase_order_items_v2("PO-0001", items=[{"item_code": "ITEM-001", "qty": 2}], request_id="po-items-001")

		mock_update_purchase_order_items_v2_service.assert_called_once_with(
			order_name="PO-0001",
			items=[{"item_code": "ITEM-001", "qty": 2}],
			request_id="po-items-001",
		)

	@patch("myapp.api.gateway.cancel_purchase_order_v2_service")
	def test_cancel_purchase_order_v2_passes_request_id_to_service(self, mock_cancel_purchase_order_v2_service):
		mock_cancel_purchase_order_v2_service.return_value = {"status": "success", "purchase_order": "PO-0001"}

		cancel_purchase_order_v2("PO-0001", request_id="po-cancel-001")

		mock_cancel_purchase_order_v2_service.assert_called_once_with(order_name="PO-0001", request_id="po-cancel-001")

	@patch("myapp.api.gateway.get_business_report_v1_service")
	def test_get_business_report_v1_passes_filters_to_service(self, mock_get_business_report_v1_service):
		mock_get_business_report_v1_service.return_value = {"status": "success", "data": {"overview": {}, "tables": {}}}

		get_business_report_v1(company="Test Company", date_from="2026-03-01", date_to="2026-03-31", limit=8)

		mock_get_business_report_v1_service.assert_called_once_with(
			company="Test Company",
			date_from="2026-03-01",
			date_to="2026-03-31",
			limit=8,
		)

	@patch("myapp.api.gateway.get_business_report_overview_v1_service")
	def test_get_business_report_overview_v1_passes_filters_to_service(self, mock_get_business_report_overview_v1_service):
		mock_get_business_report_overview_v1_service.return_value = {"status": "success", "data": {"overview": {}}}

		get_business_report_overview_v1(company="Test Company", date_from="2026-03-01", date_to="2026-03-31")

		mock_get_business_report_overview_v1_service.assert_called_once_with(
			company="Test Company",
			date_from="2026-03-01",
			date_to="2026-03-31",
		)

	@patch("myapp.api.gateway.get_sales_report_v1_service")
	def test_get_sales_report_v1_passes_filters_to_service(self, mock_get_sales_report_v1_service):
		mock_get_sales_report_v1_service.return_value = {"status": "success", "data": {"overview": {}, "tables": {}}}

		get_sales_report_v1(company="Test Company", date_from="2026-03-01", date_to="2026-03-31", limit=6)

		mock_get_sales_report_v1_service.assert_called_once_with(
			company="Test Company",
			date_from="2026-03-01",
			date_to="2026-03-31",
			limit=6,
		)

	@patch("myapp.api.gateway.get_purchase_report_v1_service")
	def test_get_purchase_report_v1_passes_filters_to_service(self, mock_get_purchase_report_v1_service):
		mock_get_purchase_report_v1_service.return_value = {"status": "success", "data": {"overview": {}, "tables": {}}}

		get_purchase_report_v1(company="Test Company", date_from="2026-03-01", date_to="2026-03-31", limit=7)

		mock_get_purchase_report_v1_service.assert_called_once_with(
			company="Test Company",
			date_from="2026-03-01",
			date_to="2026-03-31",
			limit=7,
		)

	@patch("myapp.api.gateway.get_receivable_payable_report_v1_service")
	def test_get_receivable_payable_report_v1_passes_filters_to_service(self, mock_get_receivable_payable_report_v1_service):
		mock_get_receivable_payable_report_v1_service.return_value = {"status": "success", "data": {"overview": {}, "tables": {}}}

		get_receivable_payable_report_v1(company="Test Company", date_from="2026-03-01", date_to="2026-03-31", limit=5)

		mock_get_receivable_payable_report_v1_service.assert_called_once_with(
			company="Test Company",
			date_from="2026-03-01",
			date_to="2026-03-31",
			limit=5,
		)

	@patch("myapp.api.gateway.get_print_preview_v1_service")
	def test_get_print_preview_v1_passes_filters_to_service(self, mock_get_print_preview_v1_service):
		mock_get_print_preview_v1_service.return_value = {"status": "success", "data": {"html": "<html />"}}

		get_print_preview_v1(doctype="Sales Invoice", docname="SINV-0001", template="standard", output="html")

		mock_get_print_preview_v1_service.assert_called_once_with(
			doctype="Sales Invoice",
			docname="SINV-0001",
			template="standard",
			output="html",
		)

	@patch("myapp.api.gateway.get_print_file_v1_service")
	def test_get_print_file_v1_passes_filters_to_service(self, mock_get_print_file_v1_service):
		mock_get_print_file_v1_service.return_value = {"status": "success", "data": {"filename": "Sales Invoice-SINV-0001-standard.pdf"}}

		get_print_file_v1(doctype="Sales Invoice", docname="SINV-0001", template="standard", filename="invoice.pdf")

		mock_get_print_file_v1_service.assert_called_once_with(
			doctype="Sales Invoice",
			docname="SINV-0001",
			template="standard",
			filename="invoice.pdf",
		)

	@patch("myapp.api.gateway.build_print_file_download_v1_service")
	def test_download_print_file_v1_sets_download_response(self, mock_build_print_file_download_v1_service):
		mock_build_print_file_download_v1_service.return_value = {
			"filename": "invoice.pdf",
			"content": b"%PDF-download",
			"doctype": "Sales Invoice",
			"docname": "SINV-0001",
			"template": "standard",
		}

		response = frappe._dict()
		with patch("myapp.api.gateway.frappe.local", frappe._dict(response=response)):
			result = download_print_file_v1(
				doctype="Sales Invoice",
				docname="SINV-0001",
				template="standard",
				filename="invoice.pdf",
			)

		self.assertIsNone(result)
		self.assertEqual(response.filename, "invoice.pdf")
		self.assertEqual(response.filecontent, b"%PDF-download")
		self.assertEqual(response.type, "download")

	@patch("myapp.api.gateway.quick_create_purchase_order_v2_service")
	def test_quick_create_purchase_order_v2_passes_payload_to_service(
		self,
		mock_quick_create_purchase_order_v2_service,
	):
		mock_quick_create_purchase_order_v2_service.return_value = {"status": "success", "purchase_order": "PO-0001"}

		quick_create_purchase_order_v2(
			"SUP-001",
			items=[{"item_code": "ITEM-001", "qty": 2}],
			immediate_payment=1,
			request_id="quick-po-001",
		)

		mock_quick_create_purchase_order_v2_service.assert_called_once_with(
			supplier="SUP-001",
			items=[{"item_code": "ITEM-001", "qty": 2}],
			immediate_payment=1,
			request_id="quick-po-001",
		)

	@patch("myapp.api.gateway.quick_cancel_purchase_order_v2_service")
	def test_quick_cancel_purchase_order_v2_passes_request_id_to_service(
		self,
		mock_quick_cancel_purchase_order_v2_service,
	):
		mock_quick_cancel_purchase_order_v2_service.return_value = {"status": "success", "purchase_order": "PO-0001"}

		quick_cancel_purchase_order_v2("PO-0001", rollback_payment=False, request_id="quick-po-cancel-001")

		mock_quick_cancel_purchase_order_v2_service.assert_called_once_with(
			order_name="PO-0001",
			rollback_payment=False,
			request_id="quick-po-cancel-001",
		)

	@patch("myapp.api.gateway.cancel_purchase_receipt_v2_service")
	def test_cancel_purchase_receipt_v2_passes_request_id_to_service(self, mock_cancel_purchase_receipt_v2_service):
		mock_cancel_purchase_receipt_v2_service.return_value = {"status": "success", "purchase_receipt": "PR-0001"}

		cancel_purchase_receipt_v2("PR-0001", request_id="pr-cancel-001")

		mock_cancel_purchase_receipt_v2_service.assert_called_once_with(receipt_name="PR-0001", request_id="pr-cancel-001")

	@patch("myapp.api.gateway.cancel_purchase_invoice_v2_service")
	def test_cancel_purchase_invoice_v2_passes_request_id_to_service(self, mock_cancel_purchase_invoice_v2_service):
		mock_cancel_purchase_invoice_v2_service.return_value = {"status": "success", "purchase_invoice": "PINV-0001"}

		cancel_purchase_invoice_v2("PINV-0001", request_id="pi-cancel-001")

		mock_cancel_purchase_invoice_v2_service.assert_called_once_with(invoice_name="PINV-0001", request_id="pi-cancel-001")

	@patch("myapp.api.gateway.cancel_supplier_payment_service")
	def test_cancel_supplier_payment_passes_request_id_to_service(self, mock_cancel_supplier_payment_service):
		mock_cancel_supplier_payment_service.return_value = {"status": "success", "payment_entry": "PAY-0001"}

		cancel_supplier_payment("PAY-0001", request_id="pay-cancel-001")

		mock_cancel_supplier_payment_service.assert_called_once_with(
			payment_entry_name="PAY-0001",
			request_id="pay-cancel-001",
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

	@patch("myapp.api.gateway.create_product_v2_service")
	def test_create_product_v2_passes_stock_initialization_fields_to_service(self, mock_create_product_v2_service):
		mock_create_product_v2_service.return_value = {
			"status": "success",
			"data": {"item_code": "ITEM-NEW"},
		}

		create_product_v2(
			"新商品",
			stock_uom="Nos",
			warehouse="Stores - RD",
			warehouse_stock_qty=12,
			warehouse_stock_uom="Box",
			standard_rate=19,
		)

		mock_create_product_v2_service.assert_called_once_with(
			item_name="新商品",
			stock_uom="Nos",
			warehouse="Stores - RD",
			warehouse_stock_qty=12,
			warehouse_stock_uom="Box",
			standard_rate=19,
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

	@patch("myapp.api.gateway.get_product_detail_v2_service")
	def test_get_product_detail_v2_passes_filters_to_service(self, mock_get_product_detail_v2_service):
		mock_get_product_detail_v2_service.return_value = {
			"status": "success",
			"data": {"item_code": "ITEM-001"},
		}

		get_product_detail_v2("ITEM-001", warehouse="Stores - TC", price_list="Standard Selling")

		mock_get_product_detail_v2_service.assert_called_once_with(
			item_code="ITEM-001",
			warehouse="Stores - TC",
			company=None,
			price_list="Standard Selling",
			currency=None,
		)

	@patch("myapp.api.gateway.list_products_v2_service")
	def test_list_products_v2_passes_filters_to_service(self, mock_list_products_v2_service):
		mock_list_products_v2_service.return_value = {"status": "success", "data": []}

		list_products_v2(
			search_key="SKU",
			warehouse="Stores - TC",
			company="Test Company",
			date_from="2026-03-01",
			date_to="2026-03-31",
			limit=10,
			start=5,
		)

		mock_list_products_v2_service.assert_called_once_with(
			search_key="SKU",
			warehouse="Stores - TC",
			company="Test Company",
			date_from="2026-03-01",
			date_to="2026-03-31",
			limit=10,
			start=5,
			item_group=None,
			disabled=None,
			price_list="Standard Selling",
			currency=None,
			selling_price_lists=None,
			buying_price_lists=None,
			sort_by="modified",
			sort_order="desc",
		)

	@patch("myapp.api.gateway.list_customers_v2_service")
	def test_list_customers_v2_passes_filters_to_service(self, mock_list_customers_v2_service):
		mock_list_customers_v2_service.return_value = {"status": "success", "data": []}

		list_customers_v2(
			search_key="Palmer",
			customer_group="Retail",
			disabled=0,
			date_from="2026-03-01",
			date_to="2026-03-31",
			limit=10,
			start=5,
		)

		mock_list_customers_v2_service.assert_called_once_with(
			search_key="Palmer",
			customer_group="Retail",
			disabled=0,
			date_from="2026-03-01",
			date_to="2026-03-31",
			limit=10,
			start=5,
			sort_by="modified",
			sort_order="desc",
		)

	@patch("myapp.api.gateway.get_customer_detail_v2_service")
	def test_get_customer_detail_v2_passes_customer_to_service(self, mock_get_customer_detail_v2_service):
		mock_get_customer_detail_v2_service.return_value = {
			"status": "success",
			"data": {"name": "CUST-0001"},
		}

		get_customer_detail_v2("CUST-0001")

		mock_get_customer_detail_v2_service.assert_called_once_with(customer="CUST-0001")

	@patch("myapp.api.gateway.create_customer_v2_service")
	def test_create_customer_v2_passes_payload_to_service(self, mock_create_customer_v2_service):
		mock_create_customer_v2_service.return_value = {
			"status": "success",
			"data": {"name": "CUST-0001"},
		}

		create_customer_v2(
			customer_name="Palmer Productions Ltd.",
			default_contact={"display_name": "张三"},
			request_id="cust-create-001",
		)

		mock_create_customer_v2_service.assert_called_once_with(
			customer_name="Palmer Productions Ltd.",
			default_contact={"display_name": "张三"},
			request_id="cust-create-001",
		)

	@patch("myapp.api.gateway.update_customer_v2_service")
	def test_update_customer_v2_passes_payload_to_service(self, mock_update_customer_v2_service):
		mock_update_customer_v2_service.return_value = {
			"status": "success",
			"data": {"name": "CUST-0001"},
		}

		update_customer_v2("CUST-0001", customer_name="新客户", request_id="cust-update-001")

		mock_update_customer_v2_service.assert_called_once_with(
			customer="CUST-0001",
			customer_name="新客户",
			request_id="cust-update-001",
		)

	@patch("myapp.api.gateway.disable_customer_v2_service")
	def test_disable_customer_v2_passes_disabled_flag_to_service(self, mock_disable_customer_v2_service):
		mock_disable_customer_v2_service.return_value = {
			"status": "success",
			"data": {"name": "CUST-0001"},
		}

		disable_customer_v2("CUST-0001", disabled=True, request_id="cust-disable-001")

		mock_disable_customer_v2_service.assert_called_once_with(
			customer="CUST-0001",
			disabled=True,
			request_id="cust-disable-001",
		)

	@patch("myapp.api.gateway.create_supplier_v2_service")
	def test_create_supplier_v2_passes_payload_to_service(self, mock_create_supplier_v2_service):
		mock_create_supplier_v2_service.return_value = {
			"status": "success",
			"data": {"name": "SUP-0001"},
		}

		create_supplier_v2(
			supplier_name="MA Inc.",
			default_contact={"display_name": "张三"},
			request_id="sup-create-001",
		)

		mock_create_supplier_v2_service.assert_called_once_with(
			supplier_name="MA Inc.",
			default_contact={"display_name": "张三"},
			request_id="sup-create-001",
		)

	@patch("myapp.api.gateway.update_supplier_v2_service")
	def test_update_supplier_v2_passes_payload_to_service(self, mock_update_supplier_v2_service):
		mock_update_supplier_v2_service.return_value = {
			"status": "success",
			"data": {"name": "SUP-0001"},
		}

		update_supplier_v2("SUP-0001", supplier_name="新供应商", request_id="sup-update-001")

		mock_update_supplier_v2_service.assert_called_once_with(
			supplier="SUP-0001",
			supplier_name="新供应商",
			request_id="sup-update-001",
		)

	@patch("myapp.api.gateway.disable_supplier_v2_service")
	def test_disable_supplier_v2_passes_disabled_flag_to_service(self, mock_disable_supplier_v2_service):
		mock_disable_supplier_v2_service.return_value = {
			"status": "success",
			"data": {"name": "SUP-0001"},
		}

		disable_supplier_v2("SUP-0001", disabled=True, request_id="sup-disable-001")

		mock_disable_supplier_v2_service.assert_called_once_with(
			supplier="SUP-0001",
			disabled=True,
			request_id="sup-disable-001",
		)

	@patch("myapp.api.gateway.list_uoms_v2_service")
	def test_list_uoms_v2_passes_filters_to_service(self, mock_list_uoms_v2_service):
		mock_list_uoms_v2_service.return_value = {"status": "success", "data": []}

		list_uoms_v2(
			search_key="Box",
			enabled=1,
			must_be_whole_number=1,
			date_from="2026-03-01",
			date_to="2026-03-31",
			limit=10,
			start=5,
		)

		mock_list_uoms_v2_service.assert_called_once_with(
			search_key="Box",
			enabled=1,
			must_be_whole_number=1,
			date_from="2026-03-01",
			date_to="2026-03-31",
			limit=10,
			start=5,
			sort_by="modified",
			sort_order="desc",
		)

	@patch("myapp.api.gateway.get_uom_detail_v2_service")
	def test_get_uom_detail_v2_passes_uom_to_service(self, mock_get_uom_detail_v2_service):
		mock_get_uom_detail_v2_service.return_value = {"status": "success", "data": {"name": "Box"}}

		get_uom_detail_v2("Box")

		mock_get_uom_detail_v2_service.assert_called_once_with(uom="Box")

	@patch("myapp.api.gateway.create_uom_v2_service")
	def test_create_uom_v2_passes_payload_to_service(self, mock_create_uom_v2_service):
		mock_create_uom_v2_service.return_value = {"status": "success", "data": {"name": "Box"}}

		create_uom_v2(
			uom_name="Box",
			symbol="箱",
			must_be_whole_number=1,
			request_id="uom-create-001",
		)

		mock_create_uom_v2_service.assert_called_once_with(
			uom_name="Box",
			symbol="箱",
			must_be_whole_number=1,
			request_id="uom-create-001",
		)

	@patch("myapp.api.gateway.update_uom_v2_service")
	def test_update_uom_v2_passes_payload_to_service(self, mock_update_uom_v2_service):
		mock_update_uom_v2_service.return_value = {"status": "success", "data": {"name": "Box"}}

		update_uom_v2(
			"Box",
			description="整箱",
			enabled=0,
			request_id="uom-update-001",
		)

		mock_update_uom_v2_service.assert_called_once_with(
			uom="Box",
			description="整箱",
			enabled=0,
			request_id="uom-update-001",
		)

	@patch("myapp.api.gateway.disable_uom_v2_service")
	def test_disable_uom_v2_passes_disabled_flag_to_service(self, mock_disable_uom_v2_service):
		mock_disable_uom_v2_service.return_value = {"status": "success", "data": {"name": "Box"}}

		disable_uom_v2("Box", disabled=True, request_id="uom-disable-001")

		mock_disable_uom_v2_service.assert_called_once_with(
			uom="Box",
			disabled=True,
			request_id="uom-disable-001",
		)

	@patch("myapp.api.gateway.delete_uom_v2_service")
	def test_delete_uom_v2_passes_request_id_to_service(self, mock_delete_uom_v2_service):
		mock_delete_uom_v2_service.return_value = {"status": "success", "data": {"name": "Box"}}

		delete_uom_v2("Box", request_id="uom-delete-001")

		mock_delete_uom_v2_service.assert_called_once_with(
			uom="Box",
			request_id="uom-delete-001",
		)

	@patch("myapp.api.gateway.get_delivery_note_detail_service")
	def test_get_delivery_note_detail_v2_passes_name_to_service(self, mock_get_delivery_note_detail_service):
		mock_get_delivery_note_detail_service.return_value = {
			"status": "success",
			"data": {"delivery_note_name": "DN-0001"},
		}

		get_delivery_note_detail_v2("DN-0001")

		mock_get_delivery_note_detail_service.assert_called_once_with(delivery_note_name="DN-0001")

	@patch("myapp.api.gateway.get_sales_invoice_detail_service")
	def test_get_sales_invoice_detail_v2_passes_name_to_service(self, mock_get_sales_invoice_detail_service):
		mock_get_sales_invoice_detail_service.return_value = {
			"status": "success",
			"data": {"sales_invoice_name": "ACC-SINV-0001"},
		}

		get_sales_invoice_detail_v2("ACC-SINV-0001")

		mock_get_sales_invoice_detail_service.assert_called_once_with(
			sales_invoice_name="ACC-SINV-0001"
		)

	@patch("myapp.api.gateway.update_product_v2_service")
	def test_update_product_v2_passes_fields_to_service(self, mock_update_product_v2_service):
		mock_update_product_v2_service.return_value = {
			"status": "success",
			"data": {"item_code": "ITEM-001"},
		}

		update_product_v2(
			"ITEM-001",
			item_name="新名称",
			item_group="饮料",
			brand="可口可乐",
			barcode="BAR-001",
			stock_uom="Nos",
			uom_conversions=[{"uom": "Box", "conversion_factor": 12}],
			nickname="新昵称",
			description="新描述",
			image="/files/new.png",
			standard_rate=18,
			warehouse="Stores - RD",
			warehouse_stock_qty=25,
		)

		mock_update_product_v2_service.assert_called_once_with(
			item_code="ITEM-001",
			item_name="新名称",
			item_group="饮料",
			brand="可口可乐",
			barcode="BAR-001",
			stock_uom="Nos",
			uom_conversions=[{"uom": "Box", "conversion_factor": 12}],
			nickname="新昵称",
			description="新描述",
			image="/files/new.png",
			standard_rate=18,
			warehouse="Stores - RD",
			warehouse_stock_qty=25,
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

	@patch("myapp.api.gateway.search_sales_orders_v2_service")
	def test_search_sales_orders_v2_passes_filters_to_service(self, mock_search_sales_orders_v2_service):
		mock_search_sales_orders_v2_service.return_value = {"status": "success", "data": {"items": []}}

		search_sales_orders_v2(
			search_key="SO",
			customer="Test Customer",
			company="Test Company",
			date_from="2026-03-01",
			date_to="2026-03-31",
			status_filter="unfinished",
			exclude_cancelled=True,
			sort_by="unfinished_first",
			limit=8,
			start=5,
		)

		mock_search_sales_orders_v2_service.assert_called_once_with(
			search_key="SO",
			customer="Test Customer",
			company="Test Company",
			date_from="2026-03-01",
			date_to="2026-03-31",
			status_filter="unfinished",
			exclude_cancelled=True,
			sort_by="unfinished_first",
			limit=8,
			start=5,
		)

	@patch("myapp.api.gateway.get_sales_order_status_summary_service")
	def test_get_sales_order_status_summary_passes_filters_to_service(
		self, mock_get_sales_order_status_summary_service
	):
		mock_get_sales_order_status_summary_service.return_value = {"status": "success", "data": []}

		get_sales_order_status_summary(
			customer="Test Customer",
			company="Test Company",
			limit=5,
			date_from="2026-03-01",
			date_to="2026-03-31",
		)

		mock_get_sales_order_status_summary_service.assert_called_once_with(
			customer="Test Customer",
			company="Test Company",
			limit=5,
			date_from="2026-03-01",
			date_to="2026-03-31",
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

	@patch("myapp.api.gateway.cancel_order_v2_service")
	def test_cancel_order_v2_passes_order_name_to_service(self, mock_cancel_order_v2_service):
		mock_cancel_order_v2_service.return_value = {
			"status": "success",
			"order": "SO-0001",
			"document_status": "cancelled",
		}

		cancel_order_v2("SO-0001", request_id="cancel-001")

		mock_cancel_order_v2_service.assert_called_once_with(
			order_name="SO-0001",
			request_id="cancel-001",
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
