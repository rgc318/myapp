from unittest import TestCase
from unittest.mock import patch

import frappe
from myapp.api import gateway as gateway_module

from myapp.api.gateway import (
	add_product_barcode_v2,
	analyze_ai_product_data_v1,
	approve_ai_model_policy_v1,
	approve_ai_vector_release_v1,
	archive_ai_conversation_v1,
	batch_set_users_enabled_v1,
	chat_ai_v1,
	cleanup_excluded_ai_product_vectors_v1,
	generate_ai_inventory_adjustment_draft_v1,
	generate_ai_product_setup_draft_v1,
	cancel_delivery_note,
	cancel_payment_entry,
	cancel_print_batch_v1,
	cancel_purchase_invoice_v2,
	cancel_purchase_order_v2,
	cancel_purchase_receipt_v2,
	cancel_order_v2,
	cancel_sales_invoice,
	cancel_supplier_payment,
	create_customer_v2,
	create_ai_conversation_v1,
	create_ai_data_task_v1,
	create_ai_vector_release_v1,
	create_customer_refund,
	create_print_batch_v1,
	create_supplier_refund,
	create_product_v2,
	create_supplier_v2,
	create_purchase_invoice,
	create_purchase_invoice_from_receipt,
	download_print_batch_archive_v1,
	download_print_batch_merged_pdf_v1,
	download_print_file_v1,
	get_current_user_workspace_preferences_v1,
	get_ai_conversation_v1,
	get_ai_data_task_v1,
	get_ai_model_governance_overview_v1,
	get_ai_model_policy_v1,
	get_ai_product_vector_status_v1,
	get_ai_vector_release_v1,
	get_ai_runtime_policy_snapshot_v1,
	get_user_management_overview_v1,
	get_user_permission_snapshot_v1,
	get_user_security_v1,
	get_print_batch_v1,
	get_print_file_v1,
	get_print_preview_v1,
	get_print_settings_v1,
	get_print_templates_v1,
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
	search_link_options_v1,
	list_inventory_stock_summary_v1,
	list_ai_conversations_v1,
	list_ai_data_tasks_v1,
	list_ai_models_v1,
	list_ai_selectable_models_v1,
	list_ai_vector_releases_v1,
	list_ai_model_policies_v1,
	list_stock_ledger_entries_v1,
	reconcile_inventory_stock_v1,
	resolve_ai_scenario_v1,
	restore_ai_draft_version_v1,
	execute_ai_data_task_v1,
	execute_ai_draft_v1,
	submit_inventory_stock_count_v1,
	transfer_inventory_stock_v1,
	update_ai_draft_v1,
	list_cashflow_entries_v1,
	list_business_documents_v1,
	list_print_doctypes_v1,
	list_print_batches_v1,
	list_print_jobs_v1,
	list_print_jobs_v2,
	search_purchase_orders_v2,
	create_product_and_stock,
	create_sales_invoice,
	export_sales_orders_v2,
	create_uom_v2,
	create_warehouse_v2,
	create_order,
	create_purchase_order,
	quick_cancel_purchase_order_v2,
	quick_create_purchase_order_v2,
	delete_uom_v2,
	disable_customer_v2,
	disable_supplier_v2,
	disable_uom_v2,
	disable_warehouse_v2,
	get_customer_detail_v2,
	get_customer_refund_context_v1,
	get_supplier_refund_context_v1,
	get_payment_entry_detail_v1,
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
	get_warehouse_detail_v2,
	list_customers_v2,
	list_products_v2,
	list_suppliers_v2,
	list_uoms_v2,
	list_warehouses_v2,
	delete_item_image,
	delete_product_barcode_v2,
	replace_item_image,
	upload_item_image,
	process_purchase_return,
	process_sales_return,
	receive_purchase_order,
	search_product,
	search_product_v2,
	set_print_default_template_v1,
	set_primary_product_barcode_v2,
	stream_ai_message_v1,
	submit_ai_feedback_v1,
	review_ai_data_task_v1,
	test_remote_debug,
	update_payment_status,
	update_purchase_order_items_v2,
	update_purchase_order_v2,
	update_supplier_v2,
	update_ai_model_registry_v1,
	update_customer_v2,
	update_current_user_workspace_preferences_v1,
	update_product_v2,
	update_uom_v2,
	update_warehouse_v2,
	update_order_items_v2,
	update_order_v2,
	record_supplier_payment,
	submit_delivery,
	confirm_pending_document,
	record_print_job_v1,
	rebuild_ai_product_vector_index_v1,
	retry_ai_vector_release_v1,
	save_ai_model_policy_draft_v1,
	validate_ai_vector_release_v1,
	publish_ai_vector_release_v1,
	rollback_ai_vector_release_v1,
	rollback_ai_data_task_v1,
	retry_print_batch_failed_v1,
	revoke_user_sessions_v1,
	upload_current_user_avatar_v1,
)


class TestGatewayWrappers(TestCase):
	def test_api_aggregator_exports_print_center_methods(self):
		from myapp.api.api import download_print_file_v1 as aggregated_download
		from myapp.api.api import list_print_batches_v1 as aggregated_batches
		from myapp.api.api import list_print_jobs_v2 as aggregated_jobs

		self.assertIs(aggregated_download, download_print_file_v1)
		self.assertIs(aggregated_batches, list_print_batches_v1)
		self.assertIs(aggregated_jobs, list_print_jobs_v2)
		from myapp.api.api import get_ai_product_vector_status_v1 as aggregated_vector_status
		from myapp.api.api import cleanup_excluded_ai_product_vectors_v1 as aggregated_vector_cleanup
		from myapp.api.api import get_ai_model_governance_overview_v1 as aggregated_governance_overview
		from myapp.api.api import get_ai_model_policy_v1 as aggregated_policy_detail
		from myapp.api.api import list_ai_models_v1 as aggregated_model_list
		from myapp.api.api import list_ai_selectable_models_v1 as aggregated_selectable_models
		from myapp.api.api import update_ai_model_registry_v1 as aggregated_model_update
		from myapp.api.api import list_ai_vector_releases_v1 as aggregated_vector_releases
		from myapp.api.api import list_ai_data_tasks_v1 as aggregated_data_tasks

		self.assertIs(aggregated_vector_status, get_ai_product_vector_status_v1)
		self.assertIs(aggregated_vector_cleanup, cleanup_excluded_ai_product_vectors_v1)
		self.assertIs(aggregated_governance_overview, get_ai_model_governance_overview_v1)
		self.assertIs(aggregated_policy_detail, get_ai_model_policy_v1)
		self.assertIs(aggregated_model_list, list_ai_models_v1)
		self.assertIs(aggregated_selectable_models, list_ai_selectable_models_v1)
		self.assertIs(aggregated_model_update, update_ai_model_registry_v1)
		self.assertIs(aggregated_vector_releases, list_ai_vector_releases_v1)
		self.assertIs(aggregated_data_tasks, list_ai_data_tasks_v1)

	def test_gateway_methods_are_not_exposed_to_guest(self):
		for method in (
			archive_ai_conversation_v1,
			analyze_ai_product_data_v1,
			chat_ai_v1,
			cleanup_excluded_ai_product_vectors_v1,
			create_ai_conversation_v1,
			create_ai_data_task_v1,
			execute_ai_data_task_v1,
			get_ai_data_task_v1,
			get_ai_conversation_v1,
			get_ai_product_vector_status_v1,
			get_ai_model_governance_overview_v1,
			get_ai_model_policy_v1,
			list_ai_models_v1,
			list_ai_selectable_models_v1,
			list_ai_model_policies_v1,
			update_ai_model_registry_v1,
			list_ai_vector_releases_v1,
			get_ai_vector_release_v1,
			create_ai_vector_release_v1,
			retry_ai_vector_release_v1,
			validate_ai_vector_release_v1,
			approve_ai_vector_release_v1,
			publish_ai_vector_release_v1,
			rollback_ai_vector_release_v1,
			approve_ai_model_policy_v1,
			save_ai_model_policy_draft_v1,
			list_ai_conversations_v1,
			list_ai_data_tasks_v1,
			review_ai_data_task_v1,
			rollback_ai_data_task_v1,
			stream_ai_message_v1,
			submit_ai_feedback_v1,
			test_remote_debug,
			create_order,
			create_purchase_order,
			quick_create_purchase_order_v2,
			download_print_batch_archive_v1,
			download_print_batch_merged_pdf_v1,
			download_print_file_v1,
			get_current_user_workspace_preferences_v1,
			get_user_management_overview_v1,
			get_user_permission_snapshot_v1,
			get_user_security_v1,
			batch_set_users_enabled_v1,
			revoke_user_sessions_v1,
			upload_current_user_avatar_v1,
			get_print_file_v1,
			list_print_batches_v1,
			list_print_jobs_v2,
			get_print_preview_v1,
			get_print_settings_v1,
			get_print_templates_v1,
			create_print_batch_v1,
			get_print_batch_v1,
			get_business_report_overview_v1,
			get_business_report_v1,
			get_cashflow_report_v1,
			get_sales_report_v1,
			get_purchase_report_v1,
			get_receivable_payable_report_v1,
			search_link_options_v1,
			list_business_documents_v1,
			list_print_doctypes_v1,
			list_print_jobs_v1,
			list_cashflow_entries_v1,
			list_inventory_stock_summary_v1,
			list_stock_ledger_entries_v1,
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
			cancel_print_batch_v1,
			cancel_purchase_invoice_v2,
			cancel_purchase_order_v2,
			cancel_purchase_receipt_v2,
			quick_cancel_purchase_order_v2,
				cancel_order_v2,
				cancel_sales_invoice,
				cancel_supplier_payment,
				create_customer_v2,
				create_customer_refund,
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
			set_print_default_template_v1,
			search_product_v2,
			create_product_and_stock,
			get_product_detail_v2,
			get_customer_detail_v2,
			get_customer_refund_context_v1,
			get_supplier_detail_v2,
			get_delivery_note_detail_v2,
			get_sales_invoice_detail_v2,
			delete_item_image,
			replace_item_image,
			upload_item_image,
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
			record_print_job_v1,
			rebuild_ai_product_vector_index_v1,
			retry_print_batch_failed_v1,
			update_current_user_workspace_preferences_v1,
			process_sales_return,
			process_purchase_return,
		):
			self.assertNotIn(method, frappe.guest_methods)

	@patch("myapp.api.gateway.chat_ai_v1_service")
	def test_chat_ai_v1_passes_conversation_contract(self, mock_chat_service):
		mock_chat_service.return_value = {"status": "success", "data": {"conversation": "AI-CONV-1"}}

		chat_ai_v1(
			content="查找蓝色包装商品",
			conversation_id="AI-CONV-1",
			scenario="product_search",
			company="rgc (Demo)",
			model_alias="opencode-glm-5.2",
		)

		mock_chat_service.assert_called_once_with(
			messages=None,
			content="查找蓝色包装商品",
			conversation_id="AI-CONV-1",
			scenario="product_search",
			company="rgc (Demo)",
			model_alias="opencode-glm-5.2",
		)

	@patch("myapp.api.gateway.list_ai_selectable_models_v1_service")
	def test_list_ai_selectable_models_v1_uses_public_model_service(self, mock_model_service):
		mock_model_service.return_value = {"status": "success", "data": {"items": []}}

		list_ai_selectable_models_v1()

		mock_model_service.assert_called_once_with()

	@patch("myapp.api.gateway.generate_ai_inventory_adjustment_draft_v1_service")
	def test_generate_ai_inventory_adjustment_draft_passes_company_scope(self, mock_draft_service):
		mock_draft_service.return_value = {"status": "success", "data": {"draft": {"name": "AI-DRAFT-1"}}}

		generate_ai_inventory_adjustment_draft_v1(
			content="把相机库存调整到 8 个",
			company="rgc (Demo)",
			conversation_id="AI-CONV-1",
		)

		mock_draft_service.assert_called_once_with(
			content="把相机库存调整到 8 个",
			company="rgc (Demo)",
			conversation_id="AI-CONV-1",
			model_alias=None,
		)

	@patch("myapp.api.gateway.resolve_ai_scenario_v1_service")
	def test_resolve_ai_scenario_passes_content(self, mock_resolve_service):
		mock_resolve_service.return_value = {
			"status": "success", "data": {"scenario": "product_setup_draft"},
		}

		resolve_ai_scenario_v1(content="新增商品传承结晶")

		mock_resolve_service.assert_called_once_with(content="新增商品传承结晶")

	@patch("myapp.api.gateway.execute_ai_draft_v1_service")
	def test_execute_ai_draft_passes_confirmation_and_version(self, mock_execute_service):
		mock_execute_service.return_value = {"status": "success", "data": {"execution": {}}}

		execute_ai_draft_v1(
			draft_id="AI-DRAFT-1", expected_version=3, confirmed=True, request_id="REQ-1",
		)

		mock_execute_service.assert_called_once_with(
			draft_id="AI-DRAFT-1", expected_version=3, confirmed=True, request_id="REQ-1",
		)

	@patch("myapp.api.gateway.update_ai_draft_v1_service")
	def test_update_ai_draft_passes_expected_version_and_request_id(self, mock_update_service):
		mock_update_service.return_value = {"status": "success", "data": {"version": 3}}

		update_ai_draft_v1(
			draft_id="AI-DRAFT-1", payload={"remarks": "修改后"},
			expected_version=2, request_id="REQ-UPDATE-1",
		)

		mock_update_service.assert_called_once_with(
			draft_id="AI-DRAFT-1", payload={"remarks": "修改后"},
			expected_version=2, request_id="REQ-UPDATE-1",
		)

	@patch("myapp.api.gateway.restore_ai_draft_version_v1_service")
	def test_restore_ai_draft_passes_current_and_target_versions(self, mock_restore_service):
		mock_restore_service.return_value = {"status": "success", "data": {"version": 4}}

		restore_ai_draft_version_v1(
			draft_id="AI-DRAFT-1", version=1,
			expected_version=3, request_id="REQ-RESTORE-1",
		)

		mock_restore_service.assert_called_once_with(
			draft_id="AI-DRAFT-1", version=1,
			expected_version=3, request_id="REQ-RESTORE-1",
		)

	@patch("myapp.api.gateway.generate_ai_product_setup_draft_v1_service")
	def test_generate_ai_product_setup_draft_passes_company_scope(self, mock_draft_service):
		mock_draft_service.return_value = {
			"status": "success", "data": {"draft": {"name": "AI-DRAFT-PRODUCT"}},
		}

		generate_ai_product_setup_draft_v1(
			content="新增商品传承结晶",
			company="rgc (Demo)",
			conversation_id="AI-CONV-1",
		)

		mock_draft_service.assert_called_once_with(
			content="新增商品传承结晶",
			company="rgc (Demo)",
			conversation_id="AI-CONV-1",
			model_alias=None,
		)

	@patch("myapp.api.gateway.get_ai_product_vector_status_v1_service")
	def test_get_ai_product_vector_status_passes_failure_limit(self, mock_status_service):
		mock_status_service.return_value = {"status": "success", "data": {"enabled": False}}

		from myapp.api.gateway import get_ai_product_vector_status_v1

		get_ai_product_vector_status_v1(failure_limit=10)

		mock_status_service.assert_called_once_with(failure_limit=10)

	@patch("myapp.api.gateway.rebuild_ai_product_vector_index_v1_service")
	def test_rebuild_ai_product_vector_index_passes_governed_scope(self, mock_rebuild_service):
		mock_rebuild_service.return_value = {"status": "success", "data": {"queued_count": 1}}

		from myapp.api.gateway import rebuild_ai_product_vector_index_v1

		rebuild_ai_product_vector_index_v1(
			item_codes=["ITEM-001"], failed_only=True, limit=25,
		)

		mock_rebuild_service.assert_called_once_with(
			item_codes=["ITEM-001"], failed_only=True, limit=25,
		)

	@patch("myapp.api.gateway.cleanup_excluded_ai_product_vectors_v1_service")
	def test_cleanup_excluded_ai_product_vectors_passes_dry_run_and_audit_contract(self, mock_cleanup_service):
		mock_cleanup_service.return_value = {"status": "success", "data": {"removed_count": 0}}

		cleanup_excluded_ai_product_vectors_v1(
			dry_run=False,
			limit=500,
			reason="排除 HTTP 测试向量",
			request_id="cleanup-http-1",
		)

		mock_cleanup_service.assert_called_once_with(
			dry_run=False,
			limit=500,
			reason="排除 HTTP 测试向量",
			request_id="cleanup-http-1",
		)

	@patch("myapp.api.gateway.save_ai_model_policy_draft_v1_service")
	def test_save_ai_model_policy_draft_passes_governed_payload(self, mock_save_service):
		mock_save_service.return_value = {"status": "success", "data": {"version": 1}}

		save_ai_model_policy_draft_v1(
			payload={"policy_code": "general-default"},
			reason="建立默认策略",
			request_id="policy-draft-1",
		)

		mock_save_service.assert_called_once_with(
			payload={"policy_code": "general-default"},
			reason="建立默认策略",
			request_id="policy-draft-1",
		)

	@patch.dict("myapp.api.gateway.os.environ", {"MYAPP_AI_SERVICE_TOKEN": "service-token"})
	def test_runtime_policy_snapshot_rejects_invalid_service_token(self):
		with patch.object(gateway_module, "frappe") as mock_frappe:
			mock_frappe.get_request_header.return_value = "wrong-token"
			mock_frappe.local.response = {}
			result = get_ai_runtime_policy_snapshot_v1()

		self.assertEqual(result["code"], "AI_SERVICE_UNAUTHORIZED")
		self.assertEqual(mock_frappe.local.response["http_status_code"], 401)

	@patch.dict("myapp.api.gateway.os.environ", {"MYAPP_AI_SERVICE_TOKEN": "service-token"})
	@patch("myapp.api.gateway.get_published_ai_model_policies_for_runtime")
	def test_runtime_policy_snapshot_returns_only_published_governance_data(
		self, mock_snapshot,
	):
		mock_snapshot.return_value = {"policies": [{"policy_code": "general-prod"}]}

		with patch.object(gateway_module, "frappe") as mock_frappe:
			mock_frappe.get_request_header.return_value = "service-token"
			result = get_ai_runtime_policy_snapshot_v1()

		self.assertEqual(result, {"policies": [{"policy_code": "general-prod"}]})

	@patch("myapp.api.gateway.get_current_user_workspace_preferences_v1_service")
	def test_get_current_user_workspace_preferences_passes_through_service(
		self, mock_get_preferences_service
	):
		mock_get_preferences_service.return_value = {
			"status": "success",
			"data": {"default_company": "Test Company", "default_warehouse": "Stores - RD"},
		}

		get_current_user_workspace_preferences_v1()

		mock_get_preferences_service.assert_called_once_with()

	@patch("myapp.api.gateway.update_current_user_workspace_preferences_v1_service")
	def test_update_current_user_workspace_preferences_passes_through_service(
		self, mock_update_preferences_service
	):
		mock_update_preferences_service.return_value = {
			"status": "success",
			"data": {"default_company": "Test Company", "default_warehouse": "Stores - RD"},
		}

		update_current_user_workspace_preferences_v1(
			default_company="Test Company",
			default_warehouse="Stores - RD",
		)

		mock_update_preferences_service.assert_called_once_with(
			default_company="Test Company",
			default_warehouse="Stores - RD",
		)

	@patch("myapp.api.gateway.search_link_options_v1_service")
	def test_search_link_options_v1_passes_filters_to_service(self, mock_search_link_options_service):
		mock_search_link_options_service.return_value = {
			"status": "success",
			"data": [{"label": "Cash", "value": "Cash"}],
		}

		search_link_options_v1(
			doctype="Mode of Payment",
			query="Ca",
			extra_fields=["name"],
			filters={"enabled": 1},
			limit=5,
		)

		mock_search_link_options_service.assert_called_once_with(
			doctype="Mode of Payment",
			query="Ca",
			extra_fields=["name"],
			filters={"enabled": 1},
			limit=5,
		)

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

	@patch("myapp.api.gateway.create_customer_refund_service")
	def test_create_customer_refund_passes_request_id_to_service(self, mock_create_customer_refund_service):
		mock_create_customer_refund_service.return_value = {
			"status": "success",
			"payment_entry": "ACC-PAY-REF-0001",
		}

		create_customer_refund("SINV-RET-0001", 80, request_id="refund-001")

		mock_create_customer_refund_service.assert_called_once_with(
			return_invoice_name="SINV-RET-0001",
			refund_amount=80,
			request_id="refund-001",
		)

	@patch("myapp.api.gateway.get_customer_refund_context_v1_service")
	def test_get_customer_refund_context_v1_passes_return_invoice_to_service(
		self,
		mock_get_customer_refund_context_v1_service,
	):
		mock_get_customer_refund_context_v1_service.return_value = {
			"status": "success",
			"data": {"return_invoice": {"name": "SINV-RET-0001"}},
		}

		get_customer_refund_context_v1("SINV-RET-0001")

		mock_get_customer_refund_context_v1_service.assert_called_once_with(
			return_invoice_name="SINV-RET-0001",
		)

	@patch("myapp.api.gateway.create_supplier_refund_service")
	def test_create_supplier_refund_passes_request_id_to_service(self, mock_create_supplier_refund_service):
		mock_create_supplier_refund_service.return_value = {
			"status": "success",
			"payment_entry": "ACC-PAY-SUP-REF-0001",
		}

		create_supplier_refund("PINV-RET-0001", 80, request_id="supplier-refund-001")

		mock_create_supplier_refund_service.assert_called_once_with(
			return_invoice_name="PINV-RET-0001",
			refund_amount=80,
			request_id="supplier-refund-001",
		)

	@patch("myapp.api.gateway.get_supplier_refund_context_v1_service")
	def test_get_supplier_refund_context_v1_passes_return_invoice_to_service(
		self,
		mock_get_supplier_refund_context_v1_service,
	):
		mock_get_supplier_refund_context_v1_service.return_value = {
			"status": "success",
			"data": {"return_invoice": {"name": "PINV-RET-0001"}},
		}

		get_supplier_refund_context_v1("PINV-RET-0001")

		mock_get_supplier_refund_context_v1_service.assert_called_once_with(
			return_invoice_name="PINV-RET-0001",
		)

	@patch("myapp.api.gateway.get_payment_entry_detail_v1_service")
	def test_get_payment_entry_detail_v1_passes_name_to_service(
		self,
		mock_get_payment_entry_detail_v1_service,
	):
		mock_get_payment_entry_detail_v1_service.return_value = {
			"status": "success",
			"data": {"name": "ACC-PAY-0001"},
		}

		get_payment_entry_detail_v1("ACC-PAY-0001")

		mock_get_payment_entry_detail_v1_service.assert_called_once_with(
			payment_entry_name="ACC-PAY-0001",
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

	@patch("myapp.api.gateway.list_print_doctypes_v1_service")
	def test_list_print_doctypes_v1_passes_through_service(self, mock_list_print_doctypes_v1_service):
		mock_list_print_doctypes_v1_service.return_value = {"status": "success", "data": {"doctypes": []}}

		list_print_doctypes_v1()

		mock_list_print_doctypes_v1_service.assert_called_once_with()

	@patch("myapp.api.gateway.get_print_templates_v1_service")
	def test_get_print_templates_v1_passes_filters_to_service(self, mock_get_print_templates_v1_service):
		mock_get_print_templates_v1_service.return_value = {"status": "success", "data": {"templates": []}}

		get_print_templates_v1(doctype="Sales Invoice")

		mock_get_print_templates_v1_service.assert_called_once_with(doctype="Sales Invoice")

	@patch("myapp.api.gateway.create_print_batch_v1_service")
	def test_create_print_batch_v1_passes_payload_to_service(self, mock_create_print_batch_v1_service):
		mock_create_print_batch_v1_service.return_value = {"status": "success", "data": {"batch_id": "PRN-BATCH-001"}}
		documents = [{"doctype": "Sales Invoice", "docname": "SINV-0001"}]

		create_print_batch_v1(
			documents=documents,
			output="pdf",
			template="finance",
			run_async=1,
			metadata={"source": "web"},
			request_id="print-batch-001",
		)

		mock_create_print_batch_v1_service.assert_called_once_with(
			documents=documents,
			output="pdf",
			template="finance",
			run_async=1,
			metadata={"source": "web"},
			request_id="print-batch-001",
		)

	@patch("myapp.api.gateway.get_print_batch_v1_service")
	def test_get_print_batch_v1_passes_batch_id_to_service(self, mock_get_print_batch_v1_service):
		mock_get_print_batch_v1_service.return_value = {"status": "success", "data": {"batch_id": "PRN-BATCH-001"}}

		get_print_batch_v1(batch_id="PRN-BATCH-001")

		mock_get_print_batch_v1_service.assert_called_once_with(batch_id="PRN-BATCH-001")

	@patch("myapp.api.gateway.list_print_batches_v1_service")
	def test_list_print_batches_v1_passes_filters_to_service(self, mock_list_print_batches_v1_service):
		mock_list_print_batches_v1_service.return_value = {"status": "success", "data": {"batches": []}}

		list_print_batches_v1(
			status="completed",
			date_from="2026-07-01",
			date_to="2026-07-10",
			requested_by="test@example.com",
			start=20,
			limit=20,
		)

		mock_list_print_batches_v1_service.assert_called_once_with(
			status="completed",
			date_from="2026-07-01",
			date_to="2026-07-10",
			requested_by="test@example.com",
			start=20,
			limit=20,
		)

	@patch("myapp.api.gateway.get_print_settings_v1_service")
	def test_get_print_settings_v1_passes_through_service(self, mock_get_print_settings_v1_service):
		mock_get_print_settings_v1_service.return_value = {"status": "success", "data": {"settings": []}}

		get_print_settings_v1()

		mock_get_print_settings_v1_service.assert_called_once_with()

	@patch("myapp.api.gateway.set_print_default_template_v1_service")
	def test_set_print_default_template_v1_passes_payload_to_service(self, mock_set_print_default_template_v1_service):
		mock_set_print_default_template_v1_service.return_value = {"status": "success", "data": {"saved": True}}

		set_print_default_template_v1(
			doctype="Sales Invoice",
			template="finance",
			enabled=1,
			metadata={"source": "admin"},
		)

		mock_set_print_default_template_v1_service.assert_called_once_with(
			doctype="Sales Invoice",
			template="finance",
			enabled=1,
			metadata={"source": "admin"},
		)

	@patch("myapp.api.gateway.cancel_print_batch_v1_service")
	def test_cancel_print_batch_v1_passes_batch_id_to_service(self, mock_cancel_print_batch_v1_service):
		mock_cancel_print_batch_v1_service.return_value = {"status": "success", "data": {"batch_id": "PRN-BATCH-001"}}

		cancel_print_batch_v1(batch_id="PRN-BATCH-001")

		mock_cancel_print_batch_v1_service.assert_called_once_with(batch_id="PRN-BATCH-001")

	@patch("myapp.api.gateway.retry_print_batch_failed_v1_service")
	def test_retry_print_batch_failed_v1_passes_payload_to_service(self, mock_retry_print_batch_failed_v1_service):
		mock_retry_print_batch_failed_v1_service.return_value = {"status": "success", "data": {"batch_id": "PRN-BATCH-002"}}

		retry_print_batch_failed_v1(
			batch_id="PRN-BATCH-001",
			run_async=0,
			metadata={"source": "web"},
		)

		mock_retry_print_batch_failed_v1_service.assert_called_once_with(
			batch_id="PRN-BATCH-001",
			run_async=0,
			metadata={"source": "web"},
		)

	@patch("myapp.api.gateway.record_print_job_v1_service")
	def test_record_print_job_v1_passes_payload_to_service(self, mock_record_print_job_v1_service):
		mock_record_print_job_v1_service.return_value = {"status": "success", "data": {"recorded": True}}

		record_print_job_v1(
			doctype="Sales Invoice",
			docname="SINV-0001",
			template="standard",
			action="download",
			output="pdf",
			status="success",
			filename="invoice.pdf",
			file_url="/private/files/invoice.pdf",
			error=None,
			metadata={"source": "web"},
		)

		mock_record_print_job_v1_service.assert_called_once_with(
			doctype="Sales Invoice",
			docname="SINV-0001",
			template="standard",
			action="download",
			output="pdf",
			status="success",
			filename="invoice.pdf",
			file_url="/private/files/invoice.pdf",
			error=None,
			metadata={"source": "web"},
		)

	@patch("myapp.api.gateway.list_print_jobs_v1_service")
	def test_list_print_jobs_v1_passes_filters_to_service(self, mock_list_print_jobs_v1_service):
		mock_list_print_jobs_v1_service.return_value = {"status": "success", "data": {"jobs": []}}

		list_print_jobs_v1(
			doctype="Sales Invoice",
			docname="SINV-0001",
			action="download",
			template="standard",
			date_from="2026-07-01",
			date_to="2026-07-09",
			user="test@example.com",
			limit=5,
		)

		mock_list_print_jobs_v1_service.assert_called_once_with(
			doctype="Sales Invoice",
			docname="SINV-0001",
			action="download",
			template="standard",
			date_from="2026-07-01",
			date_to="2026-07-09",
			user="test@example.com",
			limit=5,
		)

	@patch("myapp.api.gateway.list_print_jobs_v2_service")
	def test_list_print_jobs_v2_passes_pagination_to_service(self, mock_list_print_jobs_v2_service):
		mock_list_print_jobs_v2_service.return_value = {"status": "success", "data": {"jobs": []}}

		list_print_jobs_v2(
			doctype="Sales Invoice",
			docname=None,
			action="download",
			status="success",
			template="standard",
			date_from="2026-07-01",
			date_to="2026-07-09",
			user="test@example.com",
			start=20,
			limit=20,
		)

		mock_list_print_jobs_v2_service.assert_called_once_with(
			doctype="Sales Invoice",
			docname=None,
			action="download",
			status="success",
			template="standard",
			date_from="2026-07-01",
			date_to="2026-07-09",
			user="test@example.com",
			start=20,
			limit=20,
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

		get_print_file_v1(
			doctype="Sales Invoice",
			docname="SINV-0001",
			template="standard",
			filename="invoice.pdf",
			archive=1,
		)

		mock_get_print_file_v1_service.assert_called_once_with(
			doctype="Sales Invoice",
			docname="SINV-0001",
			template="standard",
			filename="invoice.pdf",
			archive=1,
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

	@patch("myapp.api.gateway.build_print_batch_archive_download_v1_service")
	def test_download_print_batch_archive_v1_sets_download_response(
		self,
		mock_build_print_batch_archive_download_v1_service,
	):
		mock_build_print_batch_archive_download_v1_service.return_value = {
			"filename": "batch.zip",
			"content": b"PK-test",
			"mime_type": "application/zip",
		}

		response = frappe._dict()
		with patch("myapp.api.gateway.frappe.local", frappe._dict(response=response)):
			result = download_print_batch_archive_v1(batch_id="PRN-BATCH-001", filename="batch.zip")

		self.assertIsNone(result)
		self.assertEqual(response.filename, "batch.zip")
		self.assertEqual(response.filecontent, b"PK-test")
		self.assertEqual(response.type, "download")
		self.assertEqual(response.display_content_as, "attachment")
		self.assertEqual(response["content_type"], "application/zip")
		mock_build_print_batch_archive_download_v1_service.assert_called_once_with(
			batch_id="PRN-BATCH-001",
			filename="batch.zip",
		)

	@patch("myapp.api.gateway.build_print_batch_merged_pdf_v1_service")
	def test_download_print_batch_merged_pdf_v1_sets_download_response(
		self,
		mock_build_print_batch_merged_pdf_v1_service,
	):
		mock_build_print_batch_merged_pdf_v1_service.return_value = {
			"filename": "batch-merged.pdf",
			"content": b"%PDF-merged",
			"mime_type": "application/pdf",
		}

		response = frappe._dict()
		with patch("myapp.api.gateway.frappe.local", frappe._dict(response=response)):
			result = download_print_batch_merged_pdf_v1(
				batch_id="PRN-BATCH-001",
				filename="batch-merged.pdf",
			)

		self.assertIsNone(result)
		self.assertEqual(response.filename, "batch-merged.pdf")
		self.assertEqual(response.filecontent, b"%PDF-merged")
		self.assertEqual(response["content_type"], "application/pdf")

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
			item_context="purchase",
			item_group="饮料",
			brand="可口可乐",
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
			disabled=0,
			item_group="饮料",
			brand="可口可乐",
			search_fields=["item_name", "nickname"],
			sort_by="price",
			sort_order="desc",
			in_stock_only=1,
			item_context="purchase",
		)

	@patch("myapp.api.gateway.search_product_v2_service")
	def test_search_product_v2_defaults_empty_search_key(self, mock_search_product_v2_service):
		mock_search_product_v2_service.return_value = {
			"status": "success",
			"data": [],
		}

		search_product_v2(item_context="sales")

		mock_search_product_v2_service.assert_called_once()
		self.assertEqual(mock_search_product_v2_service.call_args.kwargs["search_key"], "")

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
			item_group="饮料",
			brand="可口可乐",
			in_stock_only=1,
		)

		mock_list_products_v2_service.assert_called_once_with(
			search_key="SKU",
			warehouse="Stores - TC",
			company="Test Company",
			date_from="2026-03-01",
			date_to="2026-03-31",
			limit=10,
			start=5,
			item_group="饮料",
			brand="可口可乐",
			disabled=None,
			in_stock_only=1,
			price_list="Standard Selling",
			currency=None,
			selling_price_lists=None,
			buying_price_lists=None,
			sort_by="modified",
			sort_order="desc",
		)

	@patch("myapp.api.gateway.list_stock_ledger_entries_v1_service")
	def test_list_stock_ledger_entries_v1_passes_filters_to_service(self, mock_list_stock_ledger_entries_v1_service):
		mock_list_stock_ledger_entries_v1_service.return_value = {"status": "success", "data": {"rows": []}}

		list_stock_ledger_entries_v1(
			company="Test Company",
			date_from="2026-04-01",
			date_to="2026-04-30",
			item_code="ITEM-001",
			warehouse="Stores - TC",
			voucher_type="Delivery Note",
			voucher_no="DN-0001",
			page=2,
			page_size=5,
		)

		mock_list_stock_ledger_entries_v1_service.assert_called_once_with(
			company="Test Company",
			date_from="2026-04-01",
			date_to="2026-04-30",
			item_code="ITEM-001",
			warehouse="Stores - TC",
			voucher_type="Delivery Note",
			voucher_no="DN-0001",
			page=2,
			page_size=5,
		)

	@patch("myapp.api.gateway.list_inventory_stock_summary_v1_service")
	def test_list_inventory_stock_summary_v1_passes_filters_to_service(self, mock_list_inventory_stock_summary_v1_service):
		mock_list_inventory_stock_summary_v1_service.return_value = {"status": "success", "data": {"rows": []}}

		list_inventory_stock_summary_v1(
			company="Test Company",
			warehouse="Stores - TC",
			search_key="ITEM",
			stock_status="low_stock",
			low_stock_threshold=5,
			page=2,
			page_size=10,
		)

		mock_list_inventory_stock_summary_v1_service.assert_called_once_with(
			company="Test Company",
			warehouse="Stores - TC",
			search_key="ITEM",
			stock_status="low_stock",
			low_stock_threshold=5,
			page=2,
			page_size=10,
		)

	@patch("myapp.api.gateway.transfer_inventory_stock_v1_service")
	def test_transfer_inventory_stock_v1_passes_payload_to_service(self, mock_transfer_inventory_stock_v1_service):
		mock_transfer_inventory_stock_v1_service.return_value = {"status": "success", "data": {"stock_entry": "STE-1"}}

		transfer_inventory_stock_v1(
			item_code="ITEM-001",
			source_warehouse="Stores - TC",
			target_warehouse="Transit - TC",
			qty=2,
			uom="Box",
			posting_date="2026-06-01",
			remarks="Move stock",
			request_id="transfer-001",
		)

		mock_transfer_inventory_stock_v1_service.assert_called_once_with(
			item_code="ITEM-001",
			source_warehouse="Stores - TC",
			target_warehouse="Transit - TC",
			qty=2,
			uom="Box",
			posting_date="2026-06-01",
			remarks="Move stock",
			request_id="transfer-001",
		)

	@patch("myapp.api.gateway.reconcile_inventory_stock_v1_service")
	def test_reconcile_inventory_stock_v1_passes_payload_to_service(self, mock_reconcile_inventory_stock_v1_service):
		mock_reconcile_inventory_stock_v1_service.return_value = {"status": "success", "data": {"stock_entry": "STE-2"}}

		reconcile_inventory_stock_v1(
			item_code="ITEM-001",
			warehouse="Stores - TC",
			target_qty=12,
			uom="Nos",
			valuation_rate=8,
			posting_date="2026-06-02",
			remarks="Cycle count",
			request_id="count-001",
		)

		mock_reconcile_inventory_stock_v1_service.assert_called_once_with(
			item_code="ITEM-001",
			warehouse="Stores - TC",
			target_qty=12,
			uom="Nos",
			valuation_rate=8,
			posting_date="2026-06-02",
			remarks="Cycle count",
			request_id="count-001",
		)

	@patch("myapp.api.gateway.submit_inventory_stock_count_v1_service")
	def test_submit_inventory_stock_count_v1_passes_payload_to_service(self, mock_submit_inventory_stock_count_v1_service):
		mock_submit_inventory_stock_count_v1_service.return_value = {
			"status": "success",
			"data": {"stock_reconciliation": "STK-REC-0001"},
		}
		items = [{"item_code": "ITEM-001", "warehouse": "Stores - TC", "counted_qty": 12}]

		submit_inventory_stock_count_v1(
			items=items,
			company="Test Company",
			posting_date="2026-06-03",
			remarks="Monthly count",
			request_id="stock-count-001",
		)

		mock_submit_inventory_stock_count_v1_service.assert_called_once_with(
			items=items,
			company="Test Company",
			posting_date="2026-06-03",
			remarks="Monthly count",
			request_id="stock-count-001",
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

	@patch("myapp.api.gateway.list_warehouses_v2_service")
	def test_list_warehouses_v2_passes_filters_to_service(self, mock_list_warehouses_v2_service):
		mock_list_warehouses_v2_service.return_value = {"status": "success", "data": []}

		list_warehouses_v2(
			search_key="Store",
			company="Test Company",
			disabled=0,
			is_group=0,
			date_from="2026-06-01",
			date_to="2026-06-30",
			limit=10,
			start=5,
		)

		mock_list_warehouses_v2_service.assert_called_once_with(
			search_key="Store",
			company="Test Company",
			disabled=0,
			is_group=0,
			date_from="2026-06-01",
			date_to="2026-06-30",
			limit=10,
			start=5,
			sort_by="modified",
			sort_order="desc",
		)

	@patch("myapp.api.gateway.get_warehouse_detail_v2_service")
	def test_get_warehouse_detail_v2_passes_warehouse_to_service(self, mock_get_warehouse_detail_v2_service):
		mock_get_warehouse_detail_v2_service.return_value = {"status": "success", "data": {"name": "Stores - TC"}}

		get_warehouse_detail_v2("Stores - TC")

		mock_get_warehouse_detail_v2_service.assert_called_once_with(warehouse="Stores - TC")

	@patch("myapp.api.gateway.create_warehouse_v2_service")
	def test_create_warehouse_v2_passes_payload_to_service(self, mock_create_warehouse_v2_service):
		mock_create_warehouse_v2_service.return_value = {"status": "success", "data": {"name": "Stores - TC"}}

		create_warehouse_v2(
			warehouse_name="Stores",
			company="Test Company",
			parent_warehouse="All Warehouses - TC",
			request_id="wh-create-001",
		)

		mock_create_warehouse_v2_service.assert_called_once_with(
			warehouse_name="Stores",
			company="Test Company",
			parent_warehouse="All Warehouses - TC",
			request_id="wh-create-001",
		)

	@patch("myapp.api.gateway.update_warehouse_v2_service")
	def test_update_warehouse_v2_passes_payload_to_service(self, mock_update_warehouse_v2_service):
		mock_update_warehouse_v2_service.return_value = {"status": "success", "data": {"name": "Stores - TC"}}

		update_warehouse_v2(
			"Stores - TC",
			warehouse_name="Main Stores",
			disabled=0,
			request_id="wh-update-001",
		)

		mock_update_warehouse_v2_service.assert_called_once_with(
			warehouse="Stores - TC",
			warehouse_name="Main Stores",
			disabled=0,
			request_id="wh-update-001",
		)

	@patch("myapp.api.gateway.disable_warehouse_v2_service")
	def test_disable_warehouse_v2_passes_disabled_flag_to_service(self, mock_disable_warehouse_v2_service):
		mock_disable_warehouse_v2_service.return_value = {"status": "success", "data": {"name": "Stores - TC"}}

		disable_warehouse_v2("Stores - TC", disabled=True, request_id="wh-disable-001")

		mock_disable_warehouse_v2_service.assert_called_once_with(
			warehouse="Stores - TC",
			disabled=True,
			request_id="wh-disable-001",
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

	@patch("myapp.api.gateway.add_product_barcode_v2_service")
	def test_add_product_barcode_v2_passes_fields_to_service(self, mock_add_product_barcode_v2_service):
		mock_add_product_barcode_v2_service.return_value = {
			"status": "success",
			"data": {"item_code": "ITEM-001"},
		}

		add_product_barcode_v2(
			"ITEM-001",
			"BAR-002",
			set_primary=True,
			request_id="barcode-add-001",
		)

		mock_add_product_barcode_v2_service.assert_called_once_with(
			item_code="ITEM-001",
			barcode="BAR-002",
			set_primary=True,
			request_id="barcode-add-001",
		)

	@patch("myapp.api.gateway.set_primary_product_barcode_v2_service")
	def test_set_primary_product_barcode_v2_passes_fields_to_service(
		self,
		mock_set_primary_product_barcode_v2_service,
	):
		mock_set_primary_product_barcode_v2_service.return_value = {
			"status": "success",
			"data": {"item_code": "ITEM-001"},
		}

		set_primary_product_barcode_v2("ITEM-001", "BAR-002")

		mock_set_primary_product_barcode_v2_service.assert_called_once_with(
			item_code="ITEM-001",
			barcode="BAR-002",
		)

	@patch("myapp.api.gateway.delete_product_barcode_v2_service")
	def test_delete_product_barcode_v2_passes_fields_to_service(self, mock_delete_product_barcode_v2_service):
		mock_delete_product_barcode_v2_service.return_value = {
			"status": "success",
			"data": {"item_code": "ITEM-001"},
		}

		delete_product_barcode_v2("ITEM-001", "BAR-002")

		mock_delete_product_barcode_v2_service.assert_called_once_with(
			item_code="ITEM-001",
			barcode="BAR-002",
		)

	@patch("myapp.api.gateway.upload_item_image_service")
	def test_upload_item_image_passes_fields_to_service(self, mock_upload_item_image_service):
		mock_upload_item_image_service.return_value = {
			"status": "success",
			"data": {"file_url": "/files/item.png"},
		}

		upload_item_image(
			filename="item.png",
			file_content_base64="ZmFrZS1pbWFnZQ==",
			content_type="image/png",
			item_code="ITEM-001",
		)

		mock_upload_item_image_service.assert_called_once_with(
			filename="item.png",
			file_content_base64="ZmFrZS1pbWFnZQ==",
			content_type="image/png",
			item_code="ITEM-001",
			is_private=False,
		)

	@patch("myapp.api.gateway.replace_item_image_service")
	def test_replace_item_image_passes_fields_to_service(self, mock_replace_item_image_service):
		mock_replace_item_image_service.return_value = {
			"status": "success",
			"data": {"file_url": "/files/item-new.png"},
		}

		replace_item_image(
			item_code="ITEM-001",
			filename="item-new.png",
			file_content_base64="ZmFrZS1pbWFnZQ==",
			content_type="image/png",
		)

		mock_replace_item_image_service.assert_called_once_with(
			item_code="ITEM-001",
			filename="item-new.png",
			file_content_base64="ZmFrZS1pbWFnZQ==",
			content_type="image/png",
			is_private=False,
		)

	@patch("myapp.api.gateway.delete_item_image_service")
	def test_delete_item_image_passes_fields_to_service(self, mock_delete_item_image_service):
		mock_delete_item_image_service.return_value = {
			"status": "success",
			"data": {"deleted": True},
		}

		delete_item_image(item_code="ITEM-001")

		mock_delete_item_image_service.assert_called_once_with(item_code="ITEM-001")

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
			risk_filter=None,
			sort_by="unfinished_first",
			limit=8,
			start=5,
		)

	@patch("myapp.api.gateway.export_sales_orders_v2_service")
	def test_export_sales_orders_v2_passes_filters_to_service(self, mock_export_sales_orders_v2_service):
		mock_export_sales_orders_v2_service.return_value = {"status": "success", "data": {"content": ""}}

		export_sales_orders_v2(
			search_key="SO",
			customer="Test Customer",
			company="Test Company",
			date_from="2026-03-01",
			date_to="2026-03-31",
			status_filter="paying",
			exclude_cancelled=True,
			risk_filter="payment_overdue",
			sort_by="latest",
			limit=500,
		)

		mock_export_sales_orders_v2_service.assert_called_once_with(
			search_key="SO",
			customer="Test Customer",
			company="Test Company",
			date_from="2026-03-01",
			date_to="2026-03-31",
			status_filter="paying",
			exclude_cancelled=True,
			risk_filter="payment_overdue",
			sort_by="latest",
			limit=500,
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
