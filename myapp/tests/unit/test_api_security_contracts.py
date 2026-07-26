from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.api import (
	customers_api,
	gateway,
	inventory_api,
	media_api,
	orders_api,
	purchase_api,
	settlement_api,
	uoms_api,
	user_management_api,
	user_preferences_api,
	warehouses_api,
	wholesale_api,
)
from myapp.scripts import backfill_item_nickname_and_specification


class TestApiSecurityContracts(TestCase):
	def assert_post_only(self, *functions):
		for function in functions:
			with self.subTest(function=function.__name__):
				self.assertEqual(
					frappe.allowed_http_methods_for_whitelisted_func.get(function),
					["POST"],
				)

	def test_sales_transaction_mutations_are_post_only(self):
		self.assert_post_only(
			gateway.create_order,
			gateway.create_order_v2,
			gateway.quick_create_order_v2,
			gateway.update_order_v2,
			gateway.update_order_items_v2,
			gateway.cancel_order_v2,
			gateway.quick_cancel_order_v2,
			gateway.submit_delivery,
			gateway.create_sales_invoice,
			gateway.cancel_delivery_note,
			gateway.cancel_sales_invoice,
			gateway.process_sales_return,
			orders_api.create_order,
			orders_api.create_order_v2,
			orders_api.quick_create_order_v2,
			orders_api.update_order_v2,
			orders_api.update_order_items_v2,
			orders_api.cancel_order_v2,
		)

	def test_purchase_transaction_mutations_are_post_only(self):
		self.assert_post_only(
			gateway.create_purchase_order,
			gateway.quick_create_purchase_order_v2,
			gateway.update_purchase_order_v2,
			gateway.update_purchase_order_items_v2,
			gateway.cancel_purchase_order_v2,
			gateway.quick_cancel_purchase_order_v2,
			gateway.receive_purchase_order,
			gateway.create_purchase_invoice,
			gateway.create_purchase_invoice_from_receipt,
			gateway.cancel_purchase_receipt_v2,
			gateway.cancel_purchase_invoice_v2,
			gateway.record_supplier_payment,
			gateway.cancel_supplier_payment,
			gateway.process_purchase_return,
			purchase_api.create_purchase_order,
			purchase_api.quick_create_purchase_order_v2,
			purchase_api.update_purchase_order_v2,
			purchase_api.update_purchase_order_items_v2,
			purchase_api.cancel_purchase_order_v2,
		)

	def test_inventory_and_master_data_mutations_are_post_only(self):
		self.assert_post_only(
			gateway.transfer_inventory_stock_v1,
			gateway.reconcile_inventory_stock_v1,
			gateway.submit_inventory_stock_count_v1,
			inventory_api.transfer_inventory_stock_v1,
			inventory_api.reconcile_inventory_stock_v1,
			inventory_api.submit_inventory_stock_count_v1,
			gateway.create_customer_v2,
			gateway.update_customer_v2,
			gateway.disable_customer_v2,
			customers_api.create_customer_v2,
			customers_api.update_customer_v2,
			customers_api.disable_customer_v2,
			gateway.create_uom_v2,
			gateway.update_uom_v2,
			gateway.disable_uom_v2,
			gateway.delete_uom_v2,
			uoms_api.create_uom_v2,
			uoms_api.update_uom_v2,
			uoms_api.disable_uom_v2,
			uoms_api.delete_uom_v2,
			gateway.create_warehouse_v2,
			gateway.update_warehouse_v2,
			gateway.disable_warehouse_v2,
			warehouses_api.create_warehouse_v2,
			warehouses_api.update_warehouse_v2,
			warehouses_api.disable_warehouse_v2,
			gateway.create_product_and_stock,
			gateway.create_product_v2,
			gateway.update_product_v2,
			gateway.disable_product_v2,
			gateway.add_product_barcode_v2,
			gateway.set_primary_product_barcode_v2,
			gateway.delete_product_barcode_v2,
			wholesale_api.create_product_and_stock,
			wholesale_api.create_product_v2,
			wholesale_api.update_product_v2,
			wholesale_api.disable_product_v2,
			wholesale_api.add_product_barcode_v2,
			wholesale_api.set_primary_product_barcode_v2,
			wholesale_api.delete_product_barcode_v2,
		)

	def test_identity_media_and_settlement_mutations_are_post_only(self):
		self.assert_post_only(
			gateway.update_current_user_profile_v1,
			gateway.upload_current_user_avatar_v1,
			gateway.change_current_user_password_v1,
			gateway.batch_set_users_enabled_v1,
			gateway.revoke_user_sessions_v1,
			gateway.create_user_v1,
			gateway.update_user_v1,
			gateway.set_user_enabled_v1,
			gateway.update_user_roles_v1,
			gateway.add_user_permission_v1,
			gateway.delete_user_permission_v1,
			gateway.update_current_user_workspace_preferences_v1,
			user_management_api.update_current_user_profile_v1,
			user_management_api.upload_current_user_avatar_v1,
			user_management_api.change_current_user_password_v1,
			user_management_api.batch_set_users_enabled_v1,
			user_management_api.revoke_user_sessions_v1,
			user_management_api.create_user_v1,
			user_management_api.update_user_v1,
			user_management_api.set_user_enabled_v1,
			user_management_api.update_user_roles_v1,
			user_management_api.add_user_permission_v1,
			user_management_api.delete_user_permission_v1,
			user_preferences_api.update_current_user_workspace_preferences_v1,
			gateway.upload_item_image,
			gateway.replace_item_image,
			gateway.delete_item_image,
			media_api.upload_item_image,
			media_api.replace_item_image,
			media_api.delete_item_image,
			settlement_api.confirm_pending_document,
			settlement_api.update_payment_status,
			settlement_api.cancel_payment_entry,
			settlement_api.create_customer_refund,
			settlement_api.create_supplier_refund,
			settlement_api.process_sales_return,
		)

	def test_ai_printing_and_debug_mutations_are_post_only(self):
		self.assert_post_only(
			gateway.test_remote_debug,
			gateway.create_ai_conversation_v1,
			gateway.archive_ai_conversation_v1,
			gateway.reset_ai_conversation_context_v1,
			gateway.chat_ai_v1,
			gateway.create_print_batch_v1,
			gateway.set_print_default_template_v1,
			gateway.cancel_print_batch_v1,
			gateway.retry_print_batch_failed_v1,
			gateway.record_print_job_v1,
		)

	@patch.object(gateway.frappe, "only_for")
	@patch("builtins.print")
	def test_remote_debug_requires_system_manager(self, _print, mock_only_for):
		gateway.test_remote_debug()

		mock_only_for.assert_called_once_with("System Manager")

	@patch.object(backfill_item_nickname_and_specification, "_run_backfill")
	@patch.object(backfill_item_nickname_and_specification.frappe, "only_for")
	def test_item_backfill_requires_system_manager(self, mock_only_for, mock_run_backfill):
		mock_run_backfill.return_value = {"scanned": 1}

		result = backfill_item_nickname_and_specification.run(commit=True)

		self.assertEqual(result, {"scanned": 1})
		mock_only_for.assert_called_once_with("System Manager")
		mock_run_backfill.assert_called_once_with(commit=True)
		self.assertEqual(
			frappe.allowed_http_methods_for_whitelisted_func.get(
				backfill_item_nickname_and_specification.run,
			),
			["POST"],
		)
