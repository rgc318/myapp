import hmac
import os

import frappe

from .ai_api import archive_ai_conversation_v1 as archive_ai_conversation_v1_service
from .ai_api import chat_ai_v1 as chat_ai_v1_service
from .ai_api import cancel_ai_run_v1 as cancel_ai_run_v1_service
from .ai_api import cleanup_excluded_ai_product_vectors_v1 as cleanup_excluded_ai_product_vectors_v1_service
from .ai_api import create_ai_conversation_v1 as create_ai_conversation_v1_service
from .ai_api import discard_ai_draft_v1 as discard_ai_draft_v1_service
from .ai_api import execute_ai_draft_v1 as execute_ai_draft_v1_service
from .ai_api import generate_ai_inventory_adjustment_draft_v1 as generate_ai_inventory_adjustment_draft_v1_service
from .ai_api import generate_ai_purchase_order_draft_v1 as generate_ai_purchase_order_draft_v1_service
from .ai_api import generate_ai_product_setup_draft_v1 as generate_ai_product_setup_draft_v1_service
from .ai_api import generate_ai_sales_order_draft_v1 as generate_ai_sales_order_draft_v1_service
from .ai_api import get_ai_draft_v1 as get_ai_draft_v1_service
from .ai_api import get_ai_agent_approval_v1 as get_ai_agent_approval_v1_service
from .ai_api import get_ai_product_vector_status_v1 as get_ai_product_vector_status_v1_service
from .ai_api import get_ai_conversation_v1 as get_ai_conversation_v1_service
from .ai_api import list_ai_conversations_v1 as list_ai_conversations_v1_service
from .ai_api import list_ai_drafts_v1 as list_ai_drafts_v1_service
from .ai_api import list_ai_agent_approvals_v1 as list_ai_agent_approvals_v1_service
from .ai_api import list_ai_draft_versions_v1 as list_ai_draft_versions_v1_service
from .ai_api import rename_ai_conversation_v1 as rename_ai_conversation_v1_service
from .ai_api import reset_ai_conversation_context_v1 as reset_ai_conversation_context_v1_service
from .ai_api import resume_ai_run_v1 as resume_ai_run_v1_service
from .ai_api import resume_ai_agent_approval_v1 as resume_ai_agent_approval_v1_service
from .ai_api import review_ai_agent_approval_v1 as review_ai_agent_approval_v1_service
from .ai_api import stream_ai_run_resume_v1 as stream_ai_run_resume_v1_service
from .ai_api import stream_ai_message_v1 as stream_ai_message_v1_service
from .ai_api import submit_ai_feedback_v1 as submit_ai_feedback_v1_service
from .ai_api import prepare_ai_draft_handoff_v1 as prepare_ai_draft_handoff_v1_service
from .ai_api import refresh_ai_business_result_v1 as refresh_ai_business_result_v1_service
from .ai_api import restore_ai_draft_version_v1 as restore_ai_draft_version_v1_service
from .ai_api import resolve_ai_scenario_v1 as resolve_ai_scenario_v1_service
from .ai_api import rebuild_ai_product_vector_index_v1 as rebuild_ai_product_vector_index_v1_service
from .ai_api import update_ai_draft_v1 as update_ai_draft_v1_service
from .ai_api import approve_ai_model_policy_v1 as approve_ai_model_policy_v1_service
from .ai_api import get_ai_model_governance_overview_v1 as get_ai_model_governance_overview_v1_service
from .ai_api import get_ai_model_policy_v1 as get_ai_model_policy_v1_service
from .ai_api import get_ai_model_usage_summary_v1 as get_ai_model_usage_summary_v1_service
from .ai_api import list_ai_audit_events_v1 as list_ai_audit_events_v1_service
from .ai_api import list_ai_models_v1 as list_ai_models_v1_service
from .ai_api import list_ai_selectable_models_v1 as list_ai_selectable_models_v1_service
from .ai_api import list_ai_model_policies_v1 as list_ai_model_policies_v1_service
from .ai_api import publish_ai_model_policy_v1 as publish_ai_model_policy_v1_service
from .ai_api import rollback_ai_model_policy_v1 as rollback_ai_model_policy_v1_service
from .ai_api import save_ai_model_policy_draft_v1 as save_ai_model_policy_draft_v1_service
from .ai_api import sync_ai_model_registry_v1 as sync_ai_model_registry_v1_service
from .ai_api import check_ai_model_availability_v1 as check_ai_model_availability_v1_service
from .ai_api import update_ai_model_registry_v1 as update_ai_model_registry_v1_service
from .ai_api import upload_ai_image_attachment_v1 as upload_ai_image_attachment_v1_service
from .ai_api import discard_ai_attachment_v1 as discard_ai_attachment_v1_service
from .ai_api import validate_ai_model_policy_v1 as validate_ai_model_policy_v1_service
from .ai_api import approve_ai_vector_release_v1 as approve_ai_vector_release_v1_service
from .ai_api import create_ai_vector_release_v1 as create_ai_vector_release_v1_service
from .ai_api import get_ai_vector_release_v1 as get_ai_vector_release_v1_service
from .ai_api import list_ai_vector_releases_v1 as list_ai_vector_releases_v1_service
from .ai_api import publish_ai_vector_release_v1 as publish_ai_vector_release_v1_service
from .ai_api import retry_ai_vector_release_v1 as retry_ai_vector_release_v1_service
from .ai_api import rollback_ai_vector_release_v1 as rollback_ai_vector_release_v1_service
from .ai_api import validate_ai_vector_release_v1 as validate_ai_vector_release_v1_service
from .ai_api import analyze_ai_product_data_v1 as analyze_ai_product_data_v1_service
from .ai_api import create_ai_data_task_v1 as create_ai_data_task_v1_service
from .ai_api import execute_ai_data_task_v1 as execute_ai_data_task_v1_service
from .ai_api import get_ai_data_task_v1 as get_ai_data_task_v1_service
from .ai_api import list_ai_data_tasks_v1 as list_ai_data_tasks_v1_service
from .ai_api import review_ai_data_task_v1 as review_ai_data_task_v1_service
from .ai_api import rollback_ai_data_task_v1 as rollback_ai_data_task_v1_service
from myapp.services.ai_model_governance_service import get_published_ai_model_policies_for_runtime
from myapp.services.ai_agent_tool_service import execute_ai_agent_tool_v1 as execute_ai_agent_tool_v1_service
from myapp.services.ai_agent_tool_service import request_ai_agent_tool_approval_v1 as request_ai_agent_tool_approval_v1_service
from myapp.services.ai_repository import get_agent_checkpoint as get_agent_checkpoint_service
from myapp.services.ai_repository import get_agent_run_control as get_agent_run_control_service
from myapp.services.ai_repository import record_agent_runtime_event as record_agent_runtime_event_service

from .media_api import delete_item_image as delete_item_image_service
from .media_api import upload_item_image as upload_item_image_service
from .media_api import replace_item_image as replace_item_image_service
from .customers_api import create_customer_v2 as create_customer_v2_service
from .customers_api import disable_customer_v2 as disable_customer_v2_service
from .customers_api import get_customer_detail_v2 as get_customer_detail_v2_service
from .customers_api import list_customers_v2 as list_customers_v2_service
from .document_lists_api import list_business_documents_v1 as list_business_documents_v1_service
from .uoms_api import create_uom_v2 as create_uom_v2_service
from .uoms_api import delete_uom_v2 as delete_uom_v2_service
from .uoms_api import disable_uom_v2 as disable_uom_v2_service
from .uoms_api import get_uom_detail_v2 as get_uom_detail_v2_service
from .uoms_api import list_uoms_v2 as list_uoms_v2_service
from .warehouses_api import create_warehouse_v2 as create_warehouse_v2_service
from .warehouses_api import disable_warehouse_v2 as disable_warehouse_v2_service
from .warehouses_api import get_warehouse_detail_v2 as get_warehouse_detail_v2_service
from .warehouses_api import list_warehouses_v2 as list_warehouses_v2_service
from .warehouses_api import update_warehouse_v2 as update_warehouse_v2_service
from .orders_api import create_order as create_order_service
from .orders_api import create_order_v2 as create_order_v2_service
from .orders_api import quick_create_order_v2 as quick_create_order_v2_service
from .orders_api import create_sales_invoice as create_sales_invoice_service
from .orders_api import cancel_delivery_note as cancel_delivery_note_service
from .orders_api import cancel_order_v2 as cancel_order_v2_service
from .orders_api import quick_cancel_order_v2 as quick_cancel_order_v2_service
from .orders_api import cancel_sales_invoice as cancel_sales_invoice_service
from .orders_api import get_delivery_note_detail as get_delivery_note_detail_service
from .orders_api import get_customer_sales_context as get_customer_sales_context_service
from .orders_api import get_sales_order_detail as get_sales_order_detail_service
from .orders_api import get_sales_invoice_detail as get_sales_invoice_detail_service
from .orders_api import get_sales_order_status_summary as get_sales_order_status_summary_service
from .orders_api import search_sales_orders_v2 as search_sales_orders_v2_service
from .orders_api import export_sales_orders_v2 as export_sales_orders_v2_service
from .orders_api import submit_delivery as submit_delivery_service
from .orders_api import update_order_items_v2 as update_order_items_v2_service
from .orders_api import update_order_v2 as update_order_v2_service
from .purchase_api import create_purchase_invoice as create_purchase_invoice_service
from .purchase_api import (
	cancel_purchase_invoice_v2 as cancel_purchase_invoice_v2_service,
)
from .purchase_api import (
	cancel_purchase_order_v2 as cancel_purchase_order_v2_service,
)
from .purchase_api import (
	cancel_purchase_receipt_v2 as cancel_purchase_receipt_v2_service,
)
from .purchase_api import cancel_supplier_payment as cancel_supplier_payment_service
from .purchase_api import create_supplier_v2 as create_supplier_v2_service
from .purchase_api import (
	create_purchase_invoice_from_receipt as create_purchase_invoice_from_receipt_service,
)
from .purchase_api import create_purchase_order as create_purchase_order_service
from .purchase_api import quick_cancel_purchase_order_v2 as quick_cancel_purchase_order_v2_service
from .purchase_api import quick_create_purchase_order_v2 as quick_create_purchase_order_v2_service
from .purchase_api import get_purchase_company_context as get_purchase_company_context_service
from .purchase_api import get_purchase_invoice_detail_v2 as get_purchase_invoice_detail_v2_service
from .purchase_api import get_purchase_order_detail_v2 as get_purchase_order_detail_v2_service
from .purchase_api import get_purchase_order_status_summary as get_purchase_order_status_summary_service
from .purchase_api import search_purchase_orders_v2 as search_purchase_orders_v2_service
from .purchase_api import get_purchase_receipt_detail_v2 as get_purchase_receipt_detail_v2_service
from .purchase_api import get_supplier_detail_v2 as get_supplier_detail_v2_service
from .purchase_api import get_supplier_purchase_context as get_supplier_purchase_context_service
from .purchase_api import list_suppliers_v2 as list_suppliers_v2_service
from .purchase_api import process_purchase_return as process_purchase_return_service
from .purchase_api import receive_purchase_order as receive_purchase_order_service
from .purchase_api import record_supplier_payment as record_supplier_payment_service
from .purchase_api import disable_supplier_v2 as disable_supplier_v2_service
from .purchase_api import update_supplier_v2 as update_supplier_v2_service
from .purchase_api import update_purchase_order_items_v2 as update_purchase_order_items_v2_service
from .purchase_api import update_purchase_order_v2 as update_purchase_order_v2_service
from .printing_api import build_print_file_download_v1 as build_print_file_download_v1_service
from .printing_api import build_print_batch_archive_download_v1 as build_print_batch_archive_download_v1_service
from .printing_api import build_print_batch_merged_pdf_v1 as build_print_batch_merged_pdf_v1_service
from .printing_api import cancel_print_batch_v1 as cancel_print_batch_v1_service
from .printing_api import create_print_batch_v1 as create_print_batch_v1_service
from .printing_api import get_print_file_v1 as get_print_file_v1_service
from .printing_api import get_print_batch_v1 as get_print_batch_v1_service
from .printing_api import get_print_preview_v1 as get_print_preview_v1_service
from .printing_api import get_print_settings_v1 as get_print_settings_v1_service
from .printing_api import get_print_templates_v1 as get_print_templates_v1_service
from .printing_api import list_print_doctypes_v1 as list_print_doctypes_v1_service
from .printing_api import list_print_batches_v1 as list_print_batches_v1_service
from .printing_api import list_print_jobs_v1 as list_print_jobs_v1_service
from .printing_api import list_print_jobs_v2 as list_print_jobs_v2_service
from .printing_api import record_print_job_v1 as record_print_job_v1_service
from .printing_api import retry_print_batch_failed_v1 as retry_print_batch_failed_v1_service
from .printing_api import set_print_default_template_v1 as set_print_default_template_v1_service
from .reports_api import get_business_report_overview_v1 as get_business_report_overview_v1_service
from .reports_api import get_business_report_v1 as get_business_report_v1_service
from .reports_api import get_cashflow_report_v1 as get_cashflow_report_v1_service
from .reports_api import get_purchase_report_v1 as get_purchase_report_v1_service
from .reports_api import get_receivable_payable_report_v1 as get_receivable_payable_report_v1_service
from .reports_api import get_sales_report_v1 as get_sales_report_v1_service
from .reports_api import list_cashflow_entries_v1 as list_cashflow_entries_v1_service
from .inventory_api import list_inventory_stock_summary_v1 as list_inventory_stock_summary_v1_service
from .inventory_api import list_stock_ledger_entries_v1 as list_stock_ledger_entries_v1_service
from .inventory_api import reconcile_inventory_stock_v1 as reconcile_inventory_stock_v1_service
from .inventory_api import submit_inventory_stock_count_v1 as submit_inventory_stock_count_v1_service
from .inventory_api import transfer_inventory_stock_v1 as transfer_inventory_stock_v1_service
from myapp.services.link_options_service import search_link_options_v1 as search_link_options_v1_service
from .returns_api import get_return_source_context_v2 as get_return_source_context_v2_service
from .settlement_api import confirm_pending_document as confirm_pending_document_service
from .settlement_api import cancel_payment_entry as cancel_payment_entry_service
from .settlement_api import create_customer_refund as create_customer_refund_service
from .settlement_api import create_supplier_refund as create_supplier_refund_service
from .settlement_api import get_customer_refund_context_v1 as get_customer_refund_context_v1_service
from .settlement_api import get_payment_entry_detail_v1 as get_payment_entry_detail_v1_service
from .settlement_api import get_supplier_refund_context_v1 as get_supplier_refund_context_v1_service
from .settlement_api import process_sales_return as process_sales_return_service
from .settlement_api import update_payment_status as update_payment_status_service
from .wholesale_api import add_product_barcode_v2 as add_product_barcode_v2_service
from .wholesale_api import create_product_and_stock as create_product_and_stock_service
from .wholesale_api import create_product_v2 as create_product_v2_service
from .wholesale_api import delete_product_barcode_v2 as delete_product_barcode_v2_service
from .wholesale_api import disable_product_v2 as disable_product_v2_service
from .wholesale_api import get_product_detail_v2 as get_product_detail_v2_service
from .wholesale_api import list_products_v2 as list_products_v2_service
from .wholesale_api import search_product as search_product_service
from .wholesale_api import search_product_v2 as search_product_v2_service
from .wholesale_api import set_primary_product_barcode_v2 as set_primary_product_barcode_v2_service
from .wholesale_api import update_product_v2 as update_product_v2_service
from .customers_api import update_customer_v2 as update_customer_v2_service
from .uoms_api import update_uom_v2 as update_uom_v2_service
from .user_preferences_api import (
	get_current_user_workspace_preferences_v1 as get_current_user_workspace_preferences_v1_service,
)
from .user_preferences_api import (
	update_current_user_workspace_preferences_v1 as update_current_user_workspace_preferences_v1_service,
)
from .user_management_api import add_user_permission_v1 as add_user_permission_v1_service
from .user_management_api import batch_set_users_enabled_v1 as batch_set_users_enabled_v1_service
from .user_management_api import change_current_user_password_v1 as change_current_user_password_v1_service
from .user_management_api import create_user_v1 as create_user_v1_service
from .user_management_api import delete_user_permission_v1 as delete_user_permission_v1_service
from .user_management_api import get_current_user_profile_v1 as get_current_user_profile_v1_service
from .user_management_api import get_user_management_overview_v1 as get_user_management_overview_v1_service
from .user_management_api import get_user_permission_snapshot_v1 as get_user_permission_snapshot_v1_service
from .user_management_api import get_user_security_v1 as get_user_security_v1_service
from .user_management_api import get_user_detail_v1 as get_user_detail_v1_service
from .user_management_api import list_roles_v1 as list_roles_v1_service
from .user_management_api import list_users_v1 as list_users_v1_service
from .user_management_api import set_user_enabled_v1 as set_user_enabled_v1_service
from .user_management_api import revoke_user_sessions_v1 as revoke_user_sessions_v1_service
from .user_management_api import update_current_user_profile_v1 as update_current_user_profile_v1_service
from .user_management_api import update_user_roles_v1 as update_user_roles_v1_service
from .user_management_api import update_user_v1 as update_user_v1_service
from .user_management_api import upload_current_user_avatar_v1 as upload_current_user_avatar_v1_service
from myapp.services.mobile_release_service import get_mobile_release_info as get_mobile_release_info_service
from myapp.utils.api_response import (
	error_response,
	map_exception_to_error,
	normalize_service_response,
	success_response,
)


def _handle_gateway_call(callback, *, success_code: str):
	try:
		return normalize_service_response(callback(), code=success_code)
	except Exception as exc:
		code, http_status = map_exception_to_error(exc)
		frappe.local.response["http_status_code"] = http_status
		message = str(exc)
		if http_status >= 500:
			frappe.log_error(frappe.get_traceback(), "Gateway 请求处理失败")
			if not bool(getattr(exc, "user_safe", False)):
				message = (
					"上游服务暂不可用，请稍后重试。"
					if http_status == 503
					else "系统内部错误，请稍后重试。"
				)
		return error_response(
			message=message,
			code=code,
			data=getattr(exc, "public_data", None),
		)


def _merge_kwargs(kwargs, extra_kwargs):
	merged = dict(kwargs or {})
	merged.update(extra_kwargs)
	return merged


@frappe.whitelist(methods=["POST"])
def test_remote_debug():
	frappe.only_for("System Manager")
	welcome_message = "太棒了！你的 VS Code 原生调试彻底打通了！"

	a = 10
	b = 24
	result = a + b
	print(f"=== 拦截成功！计算结果是: {result} ===")

	return success_response(
		message=welcome_message,
		data={"magic_number": result},
		code="REMOTE_DEBUG_OK",
	)


@frappe.whitelist(methods=["POST"])
def create_ai_conversation_v1(title: str | None = None, company: str | None = None):
	return _handle_gateway_call(
		lambda: create_ai_conversation_v1_service(title=title, company=company),
		success_code="AI_CONVERSATION_CREATED",
	)


@frappe.whitelist()
def list_ai_conversations_v1(
	status: str = "active", search: str | None = None,
	start: int = 0, limit: int = 20,
):
	return _handle_gateway_call(
		lambda: list_ai_conversations_v1_service(
			status=status, search=search, start=start, limit=limit,
		),
		success_code="AI_CONVERSATIONS_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def rename_ai_conversation_v1(conversation_id: str, title: str):
	return _handle_gateway_call(
		lambda: rename_ai_conversation_v1_service(
			conversation_id=conversation_id, title=title,
		),
		success_code="AI_CONVERSATION_RENAMED",
	)


@frappe.whitelist()
def get_ai_conversation_v1(
	conversation_id: str,
	before_sequence: int | None = None,
	limit: int = 40,
):
	return _handle_gateway_call(
		lambda: get_ai_conversation_v1_service(
			conversation_id=conversation_id,
			before_sequence=before_sequence,
			limit=limit,
		),
		success_code="AI_CONVERSATION_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def archive_ai_conversation_v1(conversation_id: str):
	return _handle_gateway_call(
		lambda: archive_ai_conversation_v1_service(conversation_id=conversation_id),
		success_code="AI_CONVERSATION_ARCHIVED",
	)


@frappe.whitelist(methods=["POST"])
def reset_ai_conversation_context_v1(conversation_id: str):
	return _handle_gateway_call(
		lambda: reset_ai_conversation_context_v1_service(conversation_id=conversation_id),
		success_code="AI_CONVERSATION_CONTEXT_RESET",
	)


@frappe.whitelist(methods=["POST"])
def upload_ai_image_attachment_v1(
	filename: str, file_content_base64: str, content_type: str,
):
	return _handle_gateway_call(
		lambda: upload_ai_image_attachment_v1_service(
			filename=filename,
			file_content_base64=file_content_base64,
			content_type=content_type,
		),
		success_code="AI_ATTACHMENT_UPLOADED",
	)


@frappe.whitelist(methods=["POST"])
def discard_ai_attachment_v1(attachment_id: str):
	return _handle_gateway_call(
		lambda: discard_ai_attachment_v1_service(attachment_id=attachment_id),
		success_code="AI_ATTACHMENT_DISCARDED",
	)


@frappe.whitelist(methods=["POST"])
def chat_ai_v1(
	messages=None,
	scenario: str | None = None,
	company: str | None = None,
	conversation_id: str | None = None,
	content: str | None = None,
	model_alias: str | None = None,
	attachment_ids=None,
):
	return _handle_gateway_call(
		lambda: chat_ai_v1_service(
			messages=messages,
			scenario=scenario,
			company=company,
			conversation_id=conversation_id,
			content=content,
			model_alias=model_alias,
			attachment_ids=attachment_ids,
		),
		success_code="AI_CHAT_COMPLETED",
	)


@frappe.whitelist(methods=["POST"])
def stream_ai_message_v1(
	content: str,
	scenario: str | None = None,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
	retry_run_id: str | None = None,
	attachment_ids=None,
):
	return stream_ai_message_v1_service(
		content=content,
		scenario=scenario,
		company=company,
		conversation_id=conversation_id,
		model_alias=model_alias,
		retry_run_id=retry_run_id,
		attachment_ids=attachment_ids,
	)


@frappe.whitelist(methods=["POST"])
def resume_ai_run_v1(run_id: str):
	return _handle_gateway_call(
		lambda: resume_ai_run_v1_service(run_id=run_id),
		success_code="AI_RUN_RESUMED",
	)


@frappe.whitelist(methods=["POST"])
def stream_ai_run_resume_v1(run_id: str):
	return stream_ai_run_resume_v1_service(run_id=run_id)


@frappe.whitelist()
def list_ai_selectable_models_v1():
	return _handle_gateway_call(
		list_ai_selectable_models_v1_service,
		success_code="AI_SELECTABLE_MODELS_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def submit_ai_feedback_v1(
	run_id: str,
	rating: str,
	category: str | None = None,
	comment: str | None = None,
):
	return _handle_gateway_call(
		lambda: submit_ai_feedback_v1_service(
			run_id=run_id,
			rating=rating,
			category=category,
			comment=comment,
		),
		success_code="AI_FEEDBACK_RECORDED",
	)


@frappe.whitelist(methods=["POST"])
def resolve_ai_scenario_v1(
	content: str | None = None, attachment_ids=None, model_alias: str | None = None,
):
	return _handle_gateway_call(
		lambda: resolve_ai_scenario_v1_service(
			content=content, attachment_ids=attachment_ids, model_alias=model_alias,
		),
		success_code="AI_SCENARIO_RESOLVED",
	)


@frappe.whitelist(methods=["POST"])
def refresh_ai_business_result_v1(result_set):
	return _handle_gateway_call(
		lambda: refresh_ai_business_result_v1_service(result_set=result_set),
		success_code="AI_BUSINESS_RESULT_REFRESHED",
	)


@frappe.whitelist(methods=["POST"])
def generate_ai_sales_order_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
	attachment_ids=None,
	retry_run_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: generate_ai_sales_order_draft_v1_service(
			content=content, company=company, conversation_id=conversation_id,
			model_alias=model_alias, attachment_ids=attachment_ids, retry_run_id=retry_run_id,
		),
		success_code="AI_SALES_ORDER_DRAFT_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def generate_ai_purchase_order_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
	attachment_ids=None,
	retry_run_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: generate_ai_purchase_order_draft_v1_service(
			content=content, company=company, conversation_id=conversation_id,
			model_alias=model_alias, attachment_ids=attachment_ids, retry_run_id=retry_run_id,
		),
		success_code="AI_PURCHASE_ORDER_DRAFT_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def generate_ai_inventory_adjustment_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
	attachment_ids=None,
	retry_run_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: generate_ai_inventory_adjustment_draft_v1_service(
			content=content, company=company, conversation_id=conversation_id,
			model_alias=model_alias, attachment_ids=attachment_ids, retry_run_id=retry_run_id,
		),
		success_code="AI_INVENTORY_ADJUSTMENT_DRAFT_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def generate_ai_product_setup_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
	attachment_ids=None,
	retry_run_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: generate_ai_product_setup_draft_v1_service(
			content=content, company=company, conversation_id=conversation_id,
			model_alias=model_alias, attachment_ids=attachment_ids, retry_run_id=retry_run_id,
		),
		success_code="AI_PRODUCT_SETUP_DRAFT_CREATED",
	)


@frappe.whitelist()
def get_ai_draft_v1(draft_id: str):
	return _handle_gateway_call(
		lambda: get_ai_draft_v1_service(draft_id=draft_id),
		success_code="AI_DRAFT_FETCHED",
	)


@frappe.whitelist()
def list_ai_drafts_v1(
	status: str = "draft", draft_type: str | None = None,
	start: int = 0, limit: int = 20,
):
	return _handle_gateway_call(
		lambda: list_ai_drafts_v1_service(
			status=status, draft_type=draft_type, start=start, limit=limit,
		),
		success_code="AI_DRAFTS_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def prepare_ai_draft_handoff_v1(draft_id: str):
	return _handle_gateway_call(
		lambda: prepare_ai_draft_handoff_v1_service(draft_id=draft_id),
		success_code="AI_DRAFT_HANDOFF_PREPARED",
	)


@frappe.whitelist(methods=["POST"])
def update_ai_draft_v1(
	draft_id: str, payload, expected_version: int,
	request_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: update_ai_draft_v1_service(
			draft_id=draft_id, payload=payload,
			expected_version=expected_version, request_id=request_id,
		),
		success_code="AI_DRAFT_UPDATED",
	)


@frappe.whitelist(methods=["POST"])
def discard_ai_draft_v1(draft_id: str):
	return _handle_gateway_call(
		lambda: discard_ai_draft_v1_service(draft_id=draft_id),
		success_code="AI_DRAFT_DISCARDED",
	)


@frappe.whitelist(methods=["POST"])
def execute_ai_draft_v1(
	draft_id: str, expected_version: int, confirmed: bool | int = False,
	request_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: execute_ai_draft_v1_service(
			draft_id=draft_id, expected_version=expected_version,
			confirmed=confirmed, request_id=request_id,
		),
		success_code="AI_DRAFT_EXECUTED",
	)


@frappe.whitelist()
def list_ai_draft_versions_v1(draft_id: str):
	return _handle_gateway_call(
		lambda: list_ai_draft_versions_v1_service(draft_id=draft_id),
		success_code="AI_DRAFT_VERSIONS_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def restore_ai_draft_version_v1(
	draft_id: str, version: int, expected_version: int,
	request_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: restore_ai_draft_version_v1_service(
			draft_id=draft_id, version=version,
			expected_version=expected_version, request_id=request_id,
		),
		success_code="AI_DRAFT_VERSION_RESTORED",
	)


@frappe.whitelist()
def get_ai_product_vector_status_v1(failure_limit: int = 20):
	return _handle_gateway_call(
		lambda: get_ai_product_vector_status_v1_service(failure_limit=failure_limit),
		success_code="AI_PRODUCT_VECTOR_STATUS_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def rebuild_ai_product_vector_index_v1(
	item_codes=None,
	failed_only: bool | int = False,
	limit: int = 100,
):
	return _handle_gateway_call(
		lambda: rebuild_ai_product_vector_index_v1_service(
			item_codes=item_codes,
			failed_only=failed_only,
			limit=limit,
		),
		success_code="AI_PRODUCT_VECTOR_REBUILD_QUEUED",
	)


@frappe.whitelist(methods=["POST"])
def cleanup_excluded_ai_product_vectors_v1(
	dry_run: bool | int = True,
	limit: int = 5000,
	reason: str | None = None,
	request_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: cleanup_excluded_ai_product_vectors_v1_service(
			dry_run=dry_run,
			limit=limit,
			reason=reason,
			request_id=request_id,
		),
		success_code="AI_PRODUCT_VECTOR_EXCLUSIONS_CLEANED",
	)


@frappe.whitelist(methods=["POST"])
def analyze_ai_product_data_v1(item_codes=None, limit: int = 50, request_id: str | None = None):
	return _handle_gateway_call(
		lambda: analyze_ai_product_data_v1_service(item_codes=item_codes, limit=limit, request_id=request_id),
		success_code="AI_DATA_ANALYSIS_COMPLETED",
	)


@frappe.whitelist(methods=["POST"])
def create_ai_data_task_v1(payload, reason: str, request_id: str | None = None):
	return _handle_gateway_call(
		lambda: create_ai_data_task_v1_service(payload=payload, reason=reason, request_id=request_id),
		success_code="AI_DATA_TASK_CREATED",
	)


@frappe.whitelist()
def list_ai_data_tasks_v1(
	status: str | None = None, risk_level: str | None = None,
	task_type: str | None = None, start: int = 0, limit: int = 20,
):
	return _handle_gateway_call(
		lambda: list_ai_data_tasks_v1_service(
			status=status, risk_level=risk_level, task_type=task_type, start=start, limit=limit,
		),
		success_code="AI_DATA_TASKS_FETCHED",
	)


@frappe.whitelist()
def get_ai_data_task_v1(task_name: str):
	return _handle_gateway_call(
		lambda: get_ai_data_task_v1_service(task_name=task_name),
		success_code="AI_DATA_TASK_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def review_ai_data_task_v1(
	task_name: str, action: str, reason: str, request_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: review_ai_data_task_v1_service(
			task_name=task_name, action=action, reason=reason, request_id=request_id,
		),
		success_code="AI_DATA_TASK_REVIEWED",
	)


@frappe.whitelist(methods=["POST"])
def execute_ai_data_task_v1(task_name: str, request_id: str | None = None):
	return _handle_gateway_call(
		lambda: execute_ai_data_task_v1_service(task_name=task_name, request_id=request_id),
		success_code="AI_DATA_TASK_EXECUTED",
	)


@frappe.whitelist(methods=["POST"])
def rollback_ai_data_task_v1(task_name: str, reason: str, request_id: str | None = None):
	return _handle_gateway_call(
		lambda: rollback_ai_data_task_v1_service(
			task_name=task_name, reason=reason, request_id=request_id,
		),
		success_code="AI_DATA_TASK_ROLLED_BACK",
	)


@frappe.whitelist()
def list_ai_vector_releases_v1(start: int = 0, limit: int = 20):
	return _handle_gateway_call(
		lambda: list_ai_vector_releases_v1_service(start=start, limit=limit),
		success_code="AI_VECTOR_RELEASES_FETCHED",
	)


@frappe.whitelist()
def get_ai_vector_release_v1(release_code: str, failure_limit: int = 50):
	return _handle_gateway_call(
		lambda: get_ai_vector_release_v1_service(release_code=release_code, failure_limit=failure_limit),
		success_code="AI_VECTOR_RELEASE_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def create_ai_vector_release_v1(payload, reason: str, request_id: str | None = None):
	return _handle_gateway_call(
		lambda: create_ai_vector_release_v1_service(payload=payload, reason=reason, request_id=request_id),
		success_code="AI_VECTOR_RELEASE_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def retry_ai_vector_release_v1(release_code: str, request_id: str | None = None):
	return _handle_gateway_call(
		lambda: retry_ai_vector_release_v1_service(release_code=release_code, request_id=request_id),
		success_code="AI_VECTOR_RELEASE_RETRY_QUEUED",
	)


@frappe.whitelist(methods=["POST"])
def validate_ai_vector_release_v1(release_code: str, request_id: str | None = None):
	return _handle_gateway_call(
		lambda: validate_ai_vector_release_v1_service(release_code=release_code, request_id=request_id),
		success_code="AI_VECTOR_RELEASE_VALIDATED",
	)


@frappe.whitelist(methods=["POST"])
def approve_ai_vector_release_v1(release_code: str, reason: str, request_id: str | None = None):
	return _handle_gateway_call(
		lambda: approve_ai_vector_release_v1_service(release_code=release_code, reason=reason, request_id=request_id),
		success_code="AI_VECTOR_RELEASE_APPROVED",
	)


@frappe.whitelist(methods=["POST"])
def publish_ai_vector_release_v1(release_code: str, reason: str, request_id: str | None = None):
	return _handle_gateway_call(
		lambda: publish_ai_vector_release_v1_service(release_code=release_code, reason=reason, request_id=request_id),
		success_code="AI_VECTOR_RELEASE_PUBLISHED",
	)


@frappe.whitelist(methods=["POST"])
def rollback_ai_vector_release_v1(
	target_release_code: str, reason: str, request_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: rollback_ai_vector_release_v1_service(
			target_release_code=target_release_code, reason=reason, request_id=request_id,
		),
		success_code="AI_VECTOR_RELEASE_ROLLED_BACK",
	)


@frappe.whitelist()
def get_ai_model_governance_overview_v1():
	return _handle_gateway_call(
		get_ai_model_governance_overview_v1_service,
		success_code="AI_MODEL_GOVERNANCE_OVERVIEW_FETCHED",
	)


@frappe.whitelist()
def list_ai_audit_events_v1(
	search: str | None = None, action: str | None = None,
	object_type: str | None = None, priority: str | None = None,
	date_from: str | None = None, date_to: str | None = None,
	start: int = 0, limit: int = 20,
):
	return _handle_gateway_call(
		lambda: list_ai_audit_events_v1_service(
			search=search, action=action, object_type=object_type, priority=priority,
			date_from=date_from, date_to=date_to, start=start, limit=limit,
		),
		success_code="AI_AUDIT_EVENTS_FETCHED",
	)


@frappe.whitelist()
def get_ai_model_policy_v1(policy_code: str):
	return _handle_gateway_call(
		lambda: get_ai_model_policy_v1_service(policy_code=policy_code),
		success_code="AI_MODEL_POLICY_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def sync_ai_model_registry_v1(request_id: str | None = None):
	return _handle_gateway_call(
		lambda: sync_ai_model_registry_v1_service(request_id=request_id),
		success_code="AI_MODEL_REGISTRY_SYNCED",
	)


@frappe.whitelist(methods=["POST"])
def check_ai_model_availability_v1(model_aliases=None, request_id: str | None = None):
	return _handle_gateway_call(
		lambda: check_ai_model_availability_v1_service(
			model_aliases=model_aliases,
			request_id=request_id,
		),
		success_code="AI_MODEL_AVAILABILITY_CHECKED",
	)


@frappe.whitelist()
def list_ai_models_v1(
	search: str | None = None,
	capability: str | None = None,
	status: str | None = None,
	start: int = 0,
	limit: int = 20,
):
	return _handle_gateway_call(
		lambda: list_ai_models_v1_service(
			search=search, capability=capability, status=status, start=start, limit=limit,
		),
		success_code="AI_MODELS_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def update_ai_model_registry_v1(
	model_alias: str, payload, reason: str, request_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: update_ai_model_registry_v1_service(
			model_alias=model_alias, payload=payload, reason=reason, request_id=request_id,
		),
		success_code="AI_MODEL_REGISTRY_UPDATED",
	)


@frappe.whitelist()
def list_ai_model_policies_v1(
	search: str | None = None,
	status: str | None = None,
	start: int = 0,
	limit: int = 20,
):
	return _handle_gateway_call(
		lambda: list_ai_model_policies_v1_service(
			search=search,
			status=status,
			start=start,
			limit=limit,
		),
		success_code="AI_MODEL_POLICIES_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def save_ai_model_policy_draft_v1(payload, reason: str, request_id: str | None = None):
	return _handle_gateway_call(
		lambda: save_ai_model_policy_draft_v1_service(
			payload=payload,
			reason=reason,
			request_id=request_id,
		),
		success_code="AI_MODEL_POLICY_DRAFT_SAVED",
	)


@frappe.whitelist(methods=["POST"])
def validate_ai_model_policy_v1(policy_code: str, request_id: str | None = None):
	return _handle_gateway_call(
		lambda: validate_ai_model_policy_v1_service(
			policy_code=policy_code,
			request_id=request_id,
		),
		success_code="AI_MODEL_POLICY_VALIDATED",
	)


@frappe.whitelist(methods=["POST"])
def approve_ai_model_policy_v1(
	policy_code: str,
	reason: str,
	request_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: approve_ai_model_policy_v1_service(
			policy_code=policy_code,
			reason=reason,
			request_id=request_id,
		),
		success_code="AI_MODEL_POLICY_APPROVED",
	)


@frappe.whitelist(methods=["POST"])
def publish_ai_model_policy_v1(
	policy_code: str,
	reason: str,
	request_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: publish_ai_model_policy_v1_service(
			policy_code=policy_code,
			reason=reason,
			request_id=request_id,
		),
		success_code="AI_MODEL_POLICY_PUBLISHED",
	)


@frappe.whitelist(methods=["POST"])
def rollback_ai_model_policy_v1(
	policy_code: str,
	target_version: int,
	reason: str,
	request_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: rollback_ai_model_policy_v1_service(
			policy_code=policy_code,
			target_version=target_version,
			reason=reason,
			request_id=request_id,
		),
		success_code="AI_MODEL_POLICY_ROLLED_BACK",
	)


@frappe.whitelist()
def get_ai_model_usage_summary_v1(
	date_from: str | None = None,
	date_to: str | None = None,
	environment: str | None = None,
	company: str | None = None,
):
	return _handle_gateway_call(
		lambda: get_ai_model_usage_summary_v1_service(
			date_from=date_from,
			date_to=date_to,
			environment=environment,
			company=company,
		),
		success_code="AI_MODEL_USAGE_FETCHED",
	)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_ai_runtime_policy_snapshot_v1():
	"""Narrow internal endpoint for Orchestrator policy refresh; returns no ERP business data."""
	expected_token = os.environ.get("MYAPP_AI_SERVICE_TOKEN", "").strip()
	provided_token = str(frappe.get_request_header("X-MyApp-AI-Service-Token") or "")
	if not expected_token or not hmac.compare_digest(provided_token, expected_token):
		frappe.local.response["http_status_code"] = 401
		return error_response(message=frappe._("AI 服务认证失败。"), code="AI_SERVICE_UNAUTHORIZED")
	return get_published_ai_model_policies_for_runtime()


@frappe.whitelist(methods=["POST"])
def cancel_ai_run_v1(run_id: str):
	return _handle_gateway_call(
		lambda: cancel_ai_run_v1_service(run_id=run_id),
		success_code="AI_RUN_CANCELLED",
	)


@frappe.whitelist()
def get_ai_agent_approval_v1(approval_id: str):
	return _handle_gateway_call(
		lambda: get_ai_agent_approval_v1_service(approval_id=approval_id),
		success_code="AI_AGENT_APPROVAL_FETCHED",
	)


@frappe.whitelist()
def list_ai_agent_approvals_v1(
	run_id: str | None = None, status: str | None = None, start: int = 0, limit: int = 20,
):
	return _handle_gateway_call(
		lambda: list_ai_agent_approvals_v1_service(
			run_id=run_id, status=status, start=start, limit=limit,
		),
		success_code="AI_AGENT_APPROVALS_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def review_ai_agent_approval_v1(
	approval_id: str, decision: str, expected_version: int, reason: str | None = None,
):
	return _handle_gateway_call(
		lambda: review_ai_agent_approval_v1_service(
			approval_id=approval_id, decision=decision,
			expected_version=expected_version, reason=reason,
		),
		success_code="AI_AGENT_APPROVAL_REVIEWED",
	)


@frappe.whitelist(methods=["POST"])
def resume_ai_agent_approval_v1(approval_id: str):
	return _handle_gateway_call(
		lambda: resume_ai_agent_approval_v1_service(approval_id=approval_id),
		success_code="AI_AGENT_APPROVAL_RESUMED",
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def execute_ai_agent_tool_v1(
	run_id: str, call_id: str, tool: str, arguments=None, capability_token: str | None = None,
):
	"""Internal capability-scoped Agent tool executor; never exposed to Web/Mobile."""
	expected_token = os.environ.get("MYAPP_AI_SERVICE_TOKEN", "").strip()
	provided_token = str(frappe.get_request_header("X-MyApp-AI-Service-Token") or "")
	if not expected_token or not hmac.compare_digest(provided_token, expected_token):
		frappe.local.response["http_status_code"] = 401
		return error_response(message=frappe._("AI 服务认证失败。"), code="AI_SERVICE_UNAUTHORIZED")
	return execute_ai_agent_tool_v1_service(
		run_id=run_id,
		call_id=call_id,
		tool=tool,
		arguments=arguments or {},
		capability_token=str(capability_token or ""),
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def request_ai_agent_tool_approval_v1(
	run_id: str, call_id: str, tool: str, arguments=None, risk_level: str | None = None,
	checkpoint=None, capability_token: str | None = None,
):
	"""Internal atomic approval request and waiting-approval transition."""
	expected_token = os.environ.get("MYAPP_AI_SERVICE_TOKEN", "").strip()
	provided_token = str(frappe.get_request_header("X-MyApp-AI-Service-Token") or "")
	if not expected_token or not hmac.compare_digest(provided_token, expected_token):
		frappe.local.response["http_status_code"] = 401
		return error_response(message=frappe._("AI 服务认证失败。"), code="AI_SERVICE_UNAUTHORIZED")
	return request_ai_agent_tool_approval_v1_service(
		run_id=run_id, call_id=call_id, tool=tool, arguments=arguments or {},
		risk_level=str(risk_level or ""), checkpoint=checkpoint or {},
		capability_token=str(capability_token or ""),
	)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_ai_agent_run_control_v1(run_id: str):
	"""Internal minimal run state used to abort in-flight model requests."""
	expected_token = os.environ.get("MYAPP_AI_SERVICE_TOKEN", "").strip()
	provided_token = str(frappe.get_request_header("X-MyApp-AI-Service-Token") or "")
	if not expected_token or not hmac.compare_digest(provided_token, expected_token):
		frappe.local.response["http_status_code"] = 401
		return error_response(message=frappe._("AI 服务认证失败。"), code="AI_SERVICE_UNAUTHORIZED")
	return get_agent_run_control_service(run_id=str(run_id or "").strip())


@frappe.whitelist(allow_guest=True, methods=["POST"])
def record_ai_agent_runtime_event_v1(
	run_id: str, event_id: str, step_type: str, status: str,
	data=None, checkpoint=None, span_id: str | None = None, error_code: str | None = None,
	capability_token: str | None = None,
):
	"""Internal durable Agent event/checkpoint writer."""
	expected_token = os.environ.get("MYAPP_AI_SERVICE_TOKEN", "").strip()
	provided_token = str(frappe.get_request_header("X-MyApp-AI-Service-Token") or "")
	if not expected_token or not hmac.compare_digest(provided_token, expected_token):
		frappe.local.response["http_status_code"] = 401
		return error_response(message=frappe._("AI 服务认证失败。"), code="AI_SERVICE_UNAUTHORIZED")
	result = record_agent_runtime_event_service(
		run_id=str(run_id or "").strip(),
		event_id=str(event_id or "").strip(),
		step_type=str(step_type or "").strip(),
		status=str(status or "").strip(),
		data=data or {}, checkpoint=checkpoint,
		span_id=span_id, error_code=error_code,
		capability_token=str(capability_token or ""),
	)
	frappe.db.commit()
	return result


@frappe.whitelist(allow_guest=True, methods=["POST"])
def get_ai_agent_checkpoint_v1(run_id: str, capability_token: str | None = None):
	"""Internal durable checkpoint reader for same-Run recovery."""
	expected_token = os.environ.get("MYAPP_AI_SERVICE_TOKEN", "").strip()
	provided_token = str(frappe.get_request_header("X-MyApp-AI-Service-Token") or "")
	if not expected_token or not hmac.compare_digest(provided_token, expected_token):
		frappe.local.response["http_status_code"] = 401
		return error_response(message=frappe._("AI 服务认证失败。"), code="AI_SERVICE_UNAUTHORIZED")
	return get_agent_checkpoint_service(
		run_id=str(run_id or "").strip(), capability_token=str(capability_token or ""),
	)


@frappe.whitelist(methods=["POST"])
def create_order(customer: str, items, immediate: bool = False, **kwargs):
	return _handle_gateway_call(
		lambda: create_order_service(customer=customer, items=items, immediate=immediate, **kwargs),
		success_code="ORDER_CREATED",
	)


@frappe.whitelist()
def get_business_report_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 10,
):
	return _handle_gateway_call(
		lambda: get_business_report_v1_service(
			company=company,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
		),
		success_code="BUSINESS_REPORT_FETCHED",
	)


@frappe.whitelist()
def list_print_doctypes_v1():
	return _handle_gateway_call(
		lambda: list_print_doctypes_v1_service(),
		success_code="PRINT_DOCTYPES_FETCHED",
	)


@frappe.whitelist()
def get_print_templates_v1(doctype: str):
	return _handle_gateway_call(
		lambda: get_print_templates_v1_service(doctype=doctype),
		success_code="PRINT_TEMPLATES_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def create_print_batch_v1(
	documents,
	output: str = "pdf",
	template: str | None = None,
	run_async: bool | int | str = True,
	metadata: dict | str | None = None,
	request_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: create_print_batch_v1_service(
			documents=documents,
			output=output,
			template=template,
			run_async=run_async,
			metadata=metadata,
			request_id=request_id,
		),
		success_code="PRINT_BATCH_CREATED",
	)


@frappe.whitelist()
def get_print_batch_v1(batch_id: str):
	return _handle_gateway_call(
		lambda: get_print_batch_v1_service(batch_id=batch_id),
		success_code="PRINT_BATCH_FETCHED",
	)


@frappe.whitelist()
def list_print_batches_v1(
	status: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	requested_by: str | None = None,
	start: int = 0,
	limit: int = 20,
):
	return _handle_gateway_call(
		lambda: list_print_batches_v1_service(
			status=status,
			date_from=date_from,
			date_to=date_to,
			requested_by=requested_by,
			start=start,
			limit=limit,
		),
		success_code="PRINT_BATCHES_FETCHED",
	)


@frappe.whitelist()
def get_print_settings_v1():
	return _handle_gateway_call(
		lambda: get_print_settings_v1_service(),
		success_code="PRINT_SETTINGS_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def set_print_default_template_v1(
	doctype: str,
	template: str,
	enabled: bool | int | str = True,
	metadata: dict | str | None = None,
):
	return _handle_gateway_call(
		lambda: set_print_default_template_v1_service(
			doctype=doctype,
			template=template,
			enabled=enabled,
			metadata=metadata,
		),
		success_code="PRINT_DEFAULT_TEMPLATE_SET",
	)


@frappe.whitelist(methods=["POST"])
def cancel_print_batch_v1(batch_id: str):
	return _handle_gateway_call(
		lambda: cancel_print_batch_v1_service(batch_id=batch_id),
		success_code="PRINT_BATCH_CANCELED",
	)


@frappe.whitelist(methods=["POST"])
def retry_print_batch_failed_v1(
	batch_id: str,
	run_async: bool | int | str = True,
	metadata: dict | str | None = None,
):
	return _handle_gateway_call(
		lambda: retry_print_batch_failed_v1_service(
			batch_id=batch_id,
			run_async=run_async,
			metadata=metadata,
		),
		success_code="PRINT_BATCH_RETRY_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def record_print_job_v1(
	doctype: str,
	docname: str,
	template: str | None = None,
	action: str = "print",
	output: str = "pdf",
	status: str = "success",
	filename: str | None = None,
	file_url: str | None = None,
	error: str | None = None,
	metadata: dict | str | None = None,
):
	return _handle_gateway_call(
		lambda: record_print_job_v1_service(
			doctype=doctype,
			docname=docname,
			template=template,
			action=action,
			output=output,
			status=status,
			filename=filename,
			file_url=file_url,
			error=error,
			metadata=metadata,
		),
		success_code="PRINT_JOB_RECORDED",
	)


@frappe.whitelist()
def list_print_jobs_v1(
	doctype: str,
	docname: str,
	action: str | None = None,
	template: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	user: str | None = None,
	limit: int = 20,
):
	return _handle_gateway_call(
		lambda: list_print_jobs_v1_service(
			doctype=doctype,
			docname=docname,
			action=action,
			template=template,
			date_from=date_from,
			date_to=date_to,
			user=user,
			limit=limit,
		),
		success_code="PRINT_JOBS_FETCHED",
	)


@frappe.whitelist()
def list_print_jobs_v2(
	doctype: str | None = None,
	docname: str | None = None,
	action: str | None = None,
	status: str | None = None,
	template: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	user: str | None = None,
	start: int = 0,
	limit: int = 20,
):
	return _handle_gateway_call(
		lambda: list_print_jobs_v2_service(
			doctype=doctype,
			docname=docname,
			action=action,
			status=status,
			template=template,
			date_from=date_from,
			date_to=date_to,
			user=user,
			start=start,
			limit=limit,
		),
		success_code="PRINT_JOBS_FETCHED",
	)


@frappe.whitelist()
def get_print_preview_v1(
	doctype: str,
	docname: str,
	template: str | None = None,
	output: str = "html",
):
	return _handle_gateway_call(
		lambda: get_print_preview_v1_service(
			doctype=doctype,
			docname=docname,
			template=template,
			output=output,
		),
		success_code="PRINT_PREVIEW_FETCHED",
	)


@frappe.whitelist()
def get_print_file_v1(
	doctype: str,
	docname: str,
	template: str | None = None,
	filename: str | None = None,
	archive: bool | int | str = False,
):
	return _handle_gateway_call(
		lambda: get_print_file_v1_service(
			doctype=doctype,
			docname=docname,
			template=template,
			filename=filename,
			archive=archive,
		),
		success_code="PRINT_FILE_FETCHED",
	)


@frappe.whitelist()
def download_print_file_v1(
	doctype: str,
	docname: str,
	template: str | None = None,
	filename: str | None = None,
):
	payload = build_print_file_download_v1_service(
		doctype=doctype,
		docname=docname,
		template=template,
		filename=filename,
	)
	frappe.local.response.filename = payload["filename"]
	frappe.local.response.filecontent = payload["content"]
	frappe.local.response.type = "download"
	frappe.local.response.display_content_as = "attachment"
	frappe.local.response["content_type"] = "application/pdf"
	return None


@frappe.whitelist()
def download_print_batch_archive_v1(batch_id: str, filename: str | None = None):
	payload = build_print_batch_archive_download_v1_service(
		batch_id=batch_id,
		filename=filename,
	)
	frappe.local.response.filename = payload["filename"]
	frappe.local.response.filecontent = payload["content"]
	frappe.local.response.type = "download"
	frappe.local.response.display_content_as = "attachment"
	frappe.local.response["content_type"] = payload.get("mime_type") or "application/zip"
	return None


@frappe.whitelist()
def download_print_batch_merged_pdf_v1(batch_id: str, filename: str | None = None):
	payload = build_print_batch_merged_pdf_v1_service(batch_id=batch_id, filename=filename)
	frappe.local.response.filename = payload["filename"]
	frappe.local.response.filecontent = payload["content"]
	frappe.local.response.type = "download"
	frappe.local.response.display_content_as = "attachment"
	frappe.local.response["content_type"] = "application/pdf"
	return None


@frappe.whitelist()
def get_current_user_workspace_preferences_v1():
	return _handle_gateway_call(
		lambda: get_current_user_workspace_preferences_v1_service(),
		success_code="USER_WORKSPACE_PREFERENCES_FETCHED",
	)


@frappe.whitelist()
def get_current_user_profile_v1():
	return _handle_gateway_call(lambda: get_current_user_profile_v1_service(), success_code="CURRENT_USER_PROFILE_FETCHED")


@frappe.whitelist(methods=["POST"])
def update_current_user_profile_v1(**kwargs):
	return _handle_gateway_call(lambda: update_current_user_profile_v1_service(**kwargs), success_code="CURRENT_USER_PROFILE_UPDATED")


@frappe.whitelist(methods=["POST"])
def upload_current_user_avatar_v1(filename: str, file_content_base64: str, content_type=None):
	return _handle_gateway_call(
		lambda: upload_current_user_avatar_v1_service(filename=filename, file_content_base64=file_content_base64, content_type=content_type),
		success_code="CURRENT_USER_AVATAR_UPDATED",
	)


@frappe.whitelist(methods=["POST"])
def change_current_user_password_v1(old_password: str, new_password: str, logout_all_sessions=1):
	return _handle_gateway_call(
		lambda: change_current_user_password_v1_service(old_password=old_password, new_password=new_password, logout_all_sessions=logout_all_sessions),
		success_code="CURRENT_USER_PASSWORD_CHANGED",
	)


@frappe.whitelist()
def list_users_v1(search=None, enabled=None, role=None, user_type=None, page=1, page_size=20):
	return _handle_gateway_call(
		lambda: list_users_v1_service(search=search, enabled=enabled, role=role, user_type=user_type, page=page, page_size=page_size),
		success_code="USERS_FETCHED",
	)


@frappe.whitelist()
def get_user_management_overview_v1():
	return _handle_gateway_call(
		lambda: get_user_management_overview_v1_service(),
		success_code="USER_MANAGEMENT_OVERVIEW_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def batch_set_users_enabled_v1(users=None, enabled=1):
	return _handle_gateway_call(
		lambda: batch_set_users_enabled_v1_service(users=users, enabled=enabled),
		success_code="USER_STATUS_BATCH_UPDATED",
	)


@frappe.whitelist()
def get_user_detail_v1(user: str):
	return _handle_gateway_call(lambda: get_user_detail_v1_service(user=user), success_code="USER_DETAIL_FETCHED")


@frappe.whitelist()
def get_user_security_v1(user: str | None = None):
	return _handle_gateway_call(lambda: get_user_security_v1_service(user=user), success_code="USER_SECURITY_FETCHED")


@frappe.whitelist(methods=["POST"])
def revoke_user_sessions_v1(user: str | None = None):
	return _handle_gateway_call(lambda: revoke_user_sessions_v1_service(user=user), success_code="USER_SESSIONS_REVOKED")


@frappe.whitelist()
def get_user_permission_snapshot_v1(user: str):
	return _handle_gateway_call(
		lambda: get_user_permission_snapshot_v1_service(user=user),
		success_code="USER_PERMISSION_SNAPSHOT_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def create_user_v1(email: str, first_name: str, roles=None, password=None, send_welcome_email=0, enabled=1, **kwargs):
	return _handle_gateway_call(
		lambda: create_user_v1_service(email=email, first_name=first_name, roles=roles, password=password, send_welcome_email=send_welcome_email, enabled=enabled, **kwargs),
		success_code="USER_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def update_user_v1(user: str, **kwargs):
	return _handle_gateway_call(lambda: update_user_v1_service(user=user, **kwargs), success_code="USER_UPDATED")


@frappe.whitelist(methods=["POST"])
def set_user_enabled_v1(user: str, enabled=1):
	return _handle_gateway_call(lambda: set_user_enabled_v1_service(user=user, enabled=enabled), success_code="USER_STATUS_UPDATED")


@frappe.whitelist(methods=["POST"])
def update_user_roles_v1(user: str, roles=None):
	return _handle_gateway_call(lambda: update_user_roles_v1_service(user=user, roles=roles), success_code="USER_ROLES_UPDATED")


@frappe.whitelist()
def list_roles_v1(search=None):
	return _handle_gateway_call(lambda: list_roles_v1_service(search=search), success_code="ROLES_FETCHED")


@frappe.whitelist(methods=["POST"])
def add_user_permission_v1(user: str, allow: str, for_value: str, is_default=0, apply_to_all_doctypes=1, applicable_for=None, hide_descendants=0):
	return _handle_gateway_call(
		lambda: add_user_permission_v1_service(user=user, allow=allow, for_value=for_value, is_default=is_default, apply_to_all_doctypes=apply_to_all_doctypes, applicable_for=applicable_for, hide_descendants=hide_descendants),
		success_code="USER_PERMISSION_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def delete_user_permission_v1(user: str, permission_name: str):
	return _handle_gateway_call(
		lambda: delete_user_permission_v1_service(user=user, permission_name=permission_name),
		success_code="USER_PERMISSION_DELETED",
	)


@frappe.whitelist()
def search_link_options_v1(
	doctype: str,
	query: str | None = None,
	extra_fields=None,
	filters=None,
	limit: int = 8,
):
	return _handle_gateway_call(
		lambda: search_link_options_v1_service(
			doctype=doctype,
			query=query,
			extra_fields=extra_fields,
			filters=filters,
			limit=limit,
		),
		success_code="LINK_OPTIONS_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def update_current_user_workspace_preferences_v1(
	default_company: str | None = None,
	default_warehouse: str | None = None,
):
	return _handle_gateway_call(
		lambda: update_current_user_workspace_preferences_v1_service(
			default_company=default_company,
			default_warehouse=default_warehouse,
		),
		success_code="USER_WORKSPACE_PREFERENCES_UPDATED",
	)


@frappe.whitelist()
def get_mobile_release_info_v1(
	current_version: str | None = None,
	current_build_number: int | str | None = None,
):
	return _handle_gateway_call(
		lambda: get_mobile_release_info_service(
			current_version=current_version,
			current_build_number=current_build_number,
		),
		success_code="MOBILE_RELEASE_INFO_FETCHED",
	)


@frappe.whitelist()
def get_business_report_overview_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
):
	return _handle_gateway_call(
		lambda: get_business_report_overview_v1_service(
			company=company,
			date_from=date_from,
			date_to=date_to,
		),
		success_code="BUSINESS_REPORT_OVERVIEW_FETCHED",
	)


@frappe.whitelist()
def get_cashflow_report_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
):
	return _handle_gateway_call(
		lambda: get_cashflow_report_v1_service(
			company=company,
			date_from=date_from,
			date_to=date_to,
		),
		success_code="CASHFLOW_REPORT_FETCHED",
	)


@frappe.whitelist()
def get_receivable_payable_report_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 10,
):
	return _handle_gateway_call(
		lambda: get_receivable_payable_report_v1_service(
			company=company,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
		),
		success_code="RECEIVABLE_PAYABLE_REPORT_FETCHED",
	)


@frappe.whitelist()
def get_sales_report_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 10,
):
	return _handle_gateway_call(
		lambda: get_sales_report_v1_service(
			company=company,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
		),
		success_code="SALES_REPORT_FETCHED",
	)


@frappe.whitelist()
def get_purchase_report_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 10,
):
	return _handle_gateway_call(
		lambda: get_purchase_report_v1_service(
			company=company,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
		),
		success_code="PURCHASE_REPORT_FETCHED",
	)


@frappe.whitelist()
def list_cashflow_entries_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	search_key: str | None = None,
	payment_type: str | None = None,
	mode_of_payment: str | None = None,
	party: str | None = None,
	party_type: str | None = None,
	page: int = 1,
	page_size: int = 20,
):
	return _handle_gateway_call(
		lambda: list_cashflow_entries_v1_service(
			company=company,
			date_from=date_from,
			date_to=date_to,
			search_key=search_key,
			payment_type=payment_type,
			mode_of_payment=mode_of_payment,
			party=party,
			party_type=party_type,
			page=page,
			page_size=page_size,
		),
		success_code="CASHFLOW_ENTRIES_FETCHED",
	)


@frappe.whitelist()
def list_inventory_stock_summary_v1(
	company: str | None = None,
	warehouse: str | None = None,
	search_key: str | None = None,
	stock_status: str | None = "all",
	low_stock_threshold: float | int | str | None = 10,
	page: int = 1,
	page_size: int = 20,
):
	return _handle_gateway_call(
		lambda: list_inventory_stock_summary_v1_service(
			company=company,
			warehouse=warehouse,
			search_key=search_key,
			stock_status=stock_status,
			low_stock_threshold=low_stock_threshold,
			page=page,
			page_size=page_size,
		),
		success_code="INVENTORY_STOCK_SUMMARY_FETCHED",
	)


@frappe.whitelist()
def list_stock_ledger_entries_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	item_code: str | None = None,
	warehouse: str | None = None,
	voucher_type: str | None = None,
	voucher_no: str | None = None,
	page: int = 1,
	page_size: int = 20,
):
	return _handle_gateway_call(
		lambda: list_stock_ledger_entries_v1_service(
			company=company,
			date_from=date_from,
			date_to=date_to,
			item_code=item_code,
			warehouse=warehouse,
			voucher_type=voucher_type,
			voucher_no=voucher_no,
			page=page,
			page_size=page_size,
		),
		success_code="STOCK_LEDGER_ENTRIES_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def transfer_inventory_stock_v1(
	item_code: str,
	source_warehouse: str,
	target_warehouse: str,
	qty,
	uom: str | None = None,
	posting_date: str | None = None,
	remarks: str | None = None,
	request_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: transfer_inventory_stock_v1_service(
			item_code=item_code,
			source_warehouse=source_warehouse,
			target_warehouse=target_warehouse,
			qty=qty,
			uom=uom,
			posting_date=posting_date,
			remarks=remarks,
			request_id=request_id,
		),
		success_code="INVENTORY_STOCK_TRANSFERRED",
	)


@frappe.whitelist(methods=["POST"])
def reconcile_inventory_stock_v1(
	item_code: str,
	warehouse: str,
	target_qty,
	uom: str | None = None,
	valuation_rate=None,
	posting_date: str | None = None,
	remarks: str | None = None,
	request_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: reconcile_inventory_stock_v1_service(
			item_code=item_code,
			warehouse=warehouse,
			target_qty=target_qty,
			uom=uom,
			valuation_rate=valuation_rate,
			posting_date=posting_date,
			remarks=remarks,
			request_id=request_id,
		),
		success_code="INVENTORY_STOCK_RECONCILED",
	)


@frappe.whitelist(methods=["POST"])
def submit_inventory_stock_count_v1(
	items,
	company: str | None = None,
	posting_date: str | None = None,
	remarks: str | None = None,
	request_id: str | None = None,
):
	return _handle_gateway_call(
		lambda: submit_inventory_stock_count_v1_service(
			items=items,
			company=company,
			posting_date=posting_date,
			remarks=remarks,
			request_id=request_id,
		),
		success_code="INVENTORY_STOCK_COUNT_SUBMITTED",
	)


@frappe.whitelist(methods=["POST"])
def create_order_v2(customer: str, items, immediate: bool = False, **kwargs):
	return _handle_gateway_call(
		lambda: create_order_v2_service(customer=customer, items=items, immediate=immediate, **kwargs),
		success_code="ORDER_V2_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def quick_create_order_v2(customer: str, items, **kwargs):
	return _handle_gateway_call(
		lambda: quick_create_order_v2_service(customer=customer, items=items, **kwargs),
		success_code="ORDER_V2_QUICK_CREATED",
	)


@frappe.whitelist()
def get_customer_sales_context(customer: str):
	return _handle_gateway_call(
		lambda: get_customer_sales_context_service(customer=customer),
		success_code="CUSTOMER_SALES_CONTEXT_FETCHED",
	)


@frappe.whitelist()
def list_customers_v2(
	search_key: str | None = None,
	customer_group: str | None = None,
	disabled: int | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 20,
	start: int = 0,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	return _handle_gateway_call(
		lambda: list_customers_v2_service(
			search_key=search_key,
			customer_group=customer_group,
			disabled=disabled,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
			start=start,
			sort_by=sort_by,
			sort_order=sort_order,
		),
		success_code="CUSTOMER_LIST_FETCHED",
	)


@frappe.whitelist()
def get_customer_detail_v2(customer: str):
	return _handle_gateway_call(
		lambda: get_customer_detail_v2_service(customer=customer),
		success_code="CUSTOMER_DETAIL_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def create_customer_v2(customer_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: create_customer_v2_service(customer_name=customer_name, **kwargs),
		success_code="CUSTOMER_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def update_customer_v2(customer: str, **kwargs):
	return _handle_gateway_call(
		lambda: update_customer_v2_service(customer=customer, **kwargs),
		success_code="CUSTOMER_UPDATED",
	)


@frappe.whitelist(methods=["POST"])
def disable_customer_v2(customer: str, disabled: bool = True, **kwargs):
	return _handle_gateway_call(
		lambda: disable_customer_v2_service(customer=customer, disabled=disabled, **kwargs),
		success_code="CUSTOMER_DISABLED",
	)


@frappe.whitelist()
def list_uoms_v2(
	search_key: str | None = None,
	enabled: int | None = None,
	must_be_whole_number: int | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 20,
	start: int = 0,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	return _handle_gateway_call(
		lambda: list_uoms_v2_service(
			search_key=search_key,
			enabled=enabled,
			must_be_whole_number=must_be_whole_number,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
			start=start,
			sort_by=sort_by,
			sort_order=sort_order,
		),
		success_code="UOM_LIST_FETCHED",
	)


@frappe.whitelist()
def get_uom_detail_v2(uom: str):
	return _handle_gateway_call(
		lambda: get_uom_detail_v2_service(uom=uom),
		success_code="UOM_DETAIL_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def create_uom_v2(uom_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: create_uom_v2_service(uom_name=uom_name, **kwargs),
		success_code="UOM_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def update_uom_v2(uom: str, **kwargs):
	return _handle_gateway_call(
		lambda: update_uom_v2_service(uom=uom, **kwargs),
		success_code="UOM_UPDATED",
	)


@frappe.whitelist(methods=["POST"])
def disable_uom_v2(uom: str, disabled: bool = True, **kwargs):
	return _handle_gateway_call(
		lambda: disable_uom_v2_service(uom=uom, disabled=disabled, **kwargs),
		success_code="UOM_DISABLED",
	)


@frappe.whitelist(methods=["POST"])
def delete_uom_v2(uom: str, **kwargs):
	return _handle_gateway_call(
		lambda: delete_uom_v2_service(uom=uom, **kwargs),
		success_code="UOM_DELETED",
	)


@frappe.whitelist()
def list_warehouses_v2(
	search_key: str | None = None,
	company: str | None = None,
	disabled=None,
	is_group=None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 20,
	start: int = 0,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	return _handle_gateway_call(
		lambda: list_warehouses_v2_service(
			search_key=search_key,
			company=company,
			disabled=disabled,
			is_group=is_group,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
			start=start,
			sort_by=sort_by,
			sort_order=sort_order,
		),
		success_code="WAREHOUSE_LIST_FETCHED",
	)


@frappe.whitelist()
def get_warehouse_detail_v2(warehouse: str):
	return _handle_gateway_call(
		lambda: get_warehouse_detail_v2_service(warehouse=warehouse),
		success_code="WAREHOUSE_DETAIL_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def create_warehouse_v2(warehouse_name: str, company: str, **kwargs):
	return _handle_gateway_call(
		lambda: create_warehouse_v2_service(warehouse_name=warehouse_name, company=company, **kwargs),
		success_code="WAREHOUSE_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def update_warehouse_v2(warehouse: str, **kwargs):
	return _handle_gateway_call(
		lambda: update_warehouse_v2_service(warehouse=warehouse, **kwargs),
		success_code="WAREHOUSE_UPDATED",
	)


@frappe.whitelist(methods=["POST"])
def disable_warehouse_v2(warehouse: str, disabled: bool = True, **kwargs):
	return _handle_gateway_call(
		lambda: disable_warehouse_v2_service(warehouse=warehouse, disabled=disabled, **kwargs),
		success_code="WAREHOUSE_DISABLED",
	)


@frappe.whitelist()
def get_sales_order_detail(order_name: str):
	return _handle_gateway_call(
		lambda: get_sales_order_detail_service(order_name=order_name),
		success_code="ORDER_DETAIL_FETCHED",
	)


@frappe.whitelist()
def get_delivery_note_detail_v2(delivery_note_name: str):
	return _handle_gateway_call(
		lambda: get_delivery_note_detail_service(delivery_note_name=delivery_note_name),
		success_code="DELIVERY_NOTE_DETAIL_FETCHED",
	)


@frappe.whitelist()
def get_sales_invoice_detail_v2(sales_invoice_name: str):
	return _handle_gateway_call(
		lambda: get_sales_invoice_detail_service(sales_invoice_name=sales_invoice_name),
		success_code="SALES_INVOICE_DETAIL_FETCHED",
	)


@frappe.whitelist()
def list_business_documents_v1(
	doctype: str,
	search_key: str | None = None,
	company: str | None = None,
	party: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	docstatus=None,
	sort_by: str | None = None,
	limit: int = 20,
	start: int = 0,
):
	return _handle_gateway_call(
		lambda: list_business_documents_v1_service(
			doctype=doctype,
			search_key=search_key,
			company=company,
			party=party,
			date_from=date_from,
			date_to=date_to,
			docstatus=docstatus,
			sort_by=sort_by,
			limit=limit,
			start=start,
		),
		success_code="BUSINESS_DOCUMENTS_LISTED",
	)


@frappe.whitelist()
def get_sales_order_status_summary(
	customer: str | None = None,
	company: str | None = None,
	limit: int = 20,
	date_from: str | None = None,
	date_to: str | None = None,
):
	return _handle_gateway_call(
		lambda: get_sales_order_status_summary_service(
			customer=customer,
			company=company,
			limit=limit,
			date_from=date_from,
			date_to=date_to,
		),
		success_code="ORDER_SUMMARY_FETCHED",
	)


@frappe.whitelist()
def search_sales_orders_v2(
	search_key: str | None = None,
	customer: str | None = None,
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	status_filter: str | None = None,
	exclude_cancelled=None,
	risk_filter: str | None = None,
	sort_by: str | None = None,
	limit: int = 20,
	start: int = 0,
):
	return _handle_gateway_call(
		lambda: search_sales_orders_v2_service(
			search_key=search_key,
			customer=customer,
			company=company,
			date_from=date_from,
			date_to=date_to,
				status_filter=status_filter,
				exclude_cancelled=exclude_cancelled,
				risk_filter=risk_filter,
				sort_by=sort_by,
			limit=limit,
			start=start,
		),
		success_code="SALES_ORDER_SEARCHED",
	)


@frappe.whitelist()
def export_sales_orders_v2(
	search_key: str | None = None,
	customer: str | None = None,
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	status_filter: str | None = None,
	exclude_cancelled=None,
	risk_filter: str | None = None,
	sort_by: str | None = None,
	limit: int | None = None,
):
	return _handle_gateway_call(
		lambda: export_sales_orders_v2_service(
			search_key=search_key,
			customer=customer,
			company=company,
			date_from=date_from,
			date_to=date_to,
			status_filter=status_filter,
			exclude_cancelled=exclude_cancelled,
			risk_filter=risk_filter,
			sort_by=sort_by,
			limit=limit,
		),
		success_code="SALES_ORDER_EXPORTED",
	)


@frappe.whitelist(methods=["POST"])
def cancel_order_v2(order_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: cancel_order_v2_service(order_name=order_name, **kwargs),
		success_code="ORDER_V2_CANCELLED",
	)


@frappe.whitelist(methods=["POST"])
def quick_cancel_order_v2(order_name: str, rollback_payment: bool = True, **kwargs):
	return _handle_gateway_call(
		lambda: quick_cancel_order_v2_service(
			order_name=order_name,
			rollback_payment=rollback_payment,
			**kwargs,
		),
		success_code="ORDER_V2_QUICK_CANCELLED",
	)


@frappe.whitelist(methods=["POST"])
def update_order_v2(order_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: update_order_v2_service(order_name=order_name, **kwargs),
		success_code="ORDER_V2_UPDATED",
	)


@frappe.whitelist(methods=["POST"])
def update_order_items_v2(order_name: str, items, **kwargs):
	return _handle_gateway_call(
		lambda: update_order_items_v2_service(order_name=order_name, items=items, **kwargs),
		success_code="ORDER_ITEMS_V2_UPDATED",
	)


@frappe.whitelist(methods=["POST"])
def create_purchase_order(supplier: str, items, **kwargs):
	return _handle_gateway_call(
		lambda: create_purchase_order_service(supplier=supplier, items=items, **kwargs),
		success_code="PURCHASE_ORDER_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def quick_create_purchase_order_v2(supplier: str, items, **kwargs):
	return _handle_gateway_call(
		lambda: quick_create_purchase_order_v2_service(supplier=supplier, items=items, **kwargs),
		success_code="PURCHASE_ORDER_QUICK_CREATED",
	)


@frappe.whitelist()
def get_purchase_company_context(company: str | None = None):
	return _handle_gateway_call(
		lambda: get_purchase_company_context_service(company=company),
		success_code="PURCHASE_COMPANY_CONTEXT_FETCHED",
	)


@frappe.whitelist()
def get_purchase_order_detail_v2(order_name: str):
	return _handle_gateway_call(
		lambda: get_purchase_order_detail_v2_service(order_name=order_name),
		success_code="PURCHASE_ORDER_DETAIL_FETCHED",
	)


@frappe.whitelist()
def get_purchase_order_status_summary(
	supplier: str | None = None,
	company: str | None = None,
	limit: int = 20,
	date_from: str | None = None,
	date_to: str | None = None,
):
	return _handle_gateway_call(
		lambda: get_purchase_order_status_summary_service(
			supplier=supplier,
			company=company,
			limit=limit,
			date_from=date_from,
			date_to=date_to,
		),
		success_code="PURCHASE_ORDER_STATUS_SUMMARY_FETCHED",
	)


@frappe.whitelist()
def search_purchase_orders_v2(
	search_key: str | None = None,
	supplier: str | None = None,
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	status_filter: str | None = None,
	exclude_cancelled=None,
	sort_by: str | None = None,
	limit: int = 20,
	start: int = 0,
):
	return _handle_gateway_call(
		lambda: search_purchase_orders_v2_service(
			search_key=search_key,
			supplier=supplier,
			company=company,
			date_from=date_from,
			date_to=date_to,
			status_filter=status_filter,
			exclude_cancelled=exclude_cancelled,
			sort_by=sort_by,
			limit=limit,
			start=start,
		),
		success_code="PURCHASE_ORDER_SEARCHED",
	)


@frappe.whitelist()
def get_purchase_receipt_detail_v2(receipt_name: str):
	return _handle_gateway_call(
		lambda: get_purchase_receipt_detail_v2_service(receipt_name=receipt_name),
		success_code="PURCHASE_RECEIPT_DETAIL_FETCHED",
	)


@frappe.whitelist()
def get_purchase_invoice_detail_v2(invoice_name: str):
	return _handle_gateway_call(
		lambda: get_purchase_invoice_detail_v2_service(invoice_name=invoice_name),
		success_code="PURCHASE_INVOICE_DETAIL_FETCHED",
	)


@frappe.whitelist()
def get_return_source_context_v2(source_doctype: str, source_name: str):
	return _handle_gateway_call(
		lambda: get_return_source_context_v2_service(source_doctype=source_doctype, source_name=source_name),
		success_code="RETURN_SOURCE_CONTEXT_FETCHED",
	)


@frappe.whitelist()
def get_supplier_purchase_context(supplier: str, company: str | None = None):
	return _handle_gateway_call(
		lambda: get_supplier_purchase_context_service(supplier=supplier, company=company),
		success_code="SUPPLIER_PURCHASE_CONTEXT_FETCHED",
	)


@frappe.whitelist()
def list_suppliers_v2(
	search_key: str | None = None,
	supplier_group: str | None = None,
	disabled: int | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 20,
	start: int = 0,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	return _handle_gateway_call(
		lambda: list_suppliers_v2_service(
			search_key=search_key,
			supplier_group=supplier_group,
			disabled=disabled,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
			start=start,
			sort_by=sort_by,
			sort_order=sort_order,
		),
		success_code="SUPPLIER_LIST_FETCHED",
	)


@frappe.whitelist()
def get_supplier_detail_v2(supplier: str):
	return _handle_gateway_call(
		lambda: get_supplier_detail_v2_service(supplier=supplier),
		success_code="SUPPLIER_DETAIL_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def create_supplier_v2(supplier_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: create_supplier_v2_service(supplier_name=supplier_name, **kwargs),
		success_code="SUPPLIER_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def update_supplier_v2(supplier: str, **kwargs):
	return _handle_gateway_call(
		lambda: update_supplier_v2_service(supplier=supplier, **kwargs),
		success_code="SUPPLIER_UPDATED",
	)


@frappe.whitelist(methods=["POST"])
def disable_supplier_v2(supplier: str, disabled: bool = True, **kwargs):
	return _handle_gateway_call(
		lambda: disable_supplier_v2_service(supplier=supplier, disabled=disabled, **kwargs),
		success_code="SUPPLIER_DISABLED" if bool(disabled) else "SUPPLIER_ENABLED",
	)


@frappe.whitelist(methods=["POST"])
def update_purchase_order_v2(order_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: update_purchase_order_v2_service(order_name=order_name, **kwargs),
		success_code="PURCHASE_ORDER_UPDATED",
	)


@frappe.whitelist(methods=["POST"])
def update_purchase_order_items_v2(order_name: str, items, **kwargs):
	return _handle_gateway_call(
		lambda: update_purchase_order_items_v2_service(order_name=order_name, items=items, **kwargs),
		success_code="PURCHASE_ORDER_ITEMS_UPDATED",
	)


@frappe.whitelist(methods=["POST"])
def cancel_purchase_order_v2(order_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: cancel_purchase_order_v2_service(order_name=order_name, **kwargs),
		success_code="PURCHASE_ORDER_CANCELLED",
	)


@frappe.whitelist(methods=["POST"])
def quick_cancel_purchase_order_v2(order_name: str, rollback_payment: bool = True, **kwargs):
	return _handle_gateway_call(
		lambda: quick_cancel_purchase_order_v2_service(
			order_name=order_name,
			rollback_payment=rollback_payment,
			**kwargs,
		),
		success_code="PURCHASE_ORDER_QUICK_CANCELLED",
	)


@frappe.whitelist(methods=["POST"])
def cancel_purchase_receipt_v2(receipt_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: cancel_purchase_receipt_v2_service(receipt_name=receipt_name, **kwargs),
		success_code="PURCHASE_RECEIPT_CANCELLED",
	)


@frappe.whitelist(methods=["POST"])
def cancel_purchase_invoice_v2(invoice_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: cancel_purchase_invoice_v2_service(invoice_name=invoice_name, **kwargs),
		success_code="PURCHASE_INVOICE_CANCELLED",
	)


@frappe.whitelist(methods=["POST"])
def cancel_supplier_payment(payment_entry_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: cancel_supplier_payment_service(payment_entry_name=payment_entry_name, **kwargs),
		success_code="SUPPLIER_PAYMENT_CANCELLED",
	)


@frappe.whitelist(methods=["POST"])
def submit_delivery(order_name: str, delivery_items=None, kwargs=None, **extra_kwargs):
	return _handle_gateway_call(
		lambda: submit_delivery_service(
			order_name=order_name,
			delivery_items=delivery_items,
			kwargs=_merge_kwargs(kwargs, extra_kwargs),
		),
		success_code="DELIVERY_SUBMITTED",
	)


@frappe.whitelist(methods=["POST"])
def create_sales_invoice(source_name: str, invoice_items=None, kwargs=None, **extra_kwargs):
	return _handle_gateway_call(
		lambda: create_sales_invoice_service(
			source_name=source_name,
			invoice_items=invoice_items,
			kwargs=_merge_kwargs(kwargs, extra_kwargs),
		),
		success_code="SALES_INVOICE_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def cancel_delivery_note(delivery_note_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: cancel_delivery_note_service(delivery_note_name=delivery_note_name, **kwargs),
		success_code="DELIVERY_NOTE_CANCELLED",
	)


@frappe.whitelist(methods=["POST"])
def cancel_sales_invoice(sales_invoice_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: cancel_sales_invoice_service(sales_invoice_name=sales_invoice_name, **kwargs),
		success_code="SALES_INVOICE_CANCELLED",
	)


@frappe.whitelist(methods=["POST"])
def receive_purchase_order(order_name: str, receipt_items=None, kwargs=None, **extra_kwargs):
	return _handle_gateway_call(
		lambda: receive_purchase_order_service(
			order_name=order_name,
			receipt_items=receipt_items,
			kwargs=_merge_kwargs(kwargs, extra_kwargs),
		),
		success_code="PURCHASE_RECEIPT_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def create_purchase_invoice(source_name: str, invoice_items=None, kwargs=None, **extra_kwargs):
	return _handle_gateway_call(
		lambda: create_purchase_invoice_service(
			source_name=source_name,
			invoice_items=invoice_items,
			kwargs=_merge_kwargs(kwargs, extra_kwargs),
		),
		success_code="PURCHASE_INVOICE_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def create_purchase_invoice_from_receipt(receipt_name: str, invoice_items=None, kwargs=None, **extra_kwargs):
	return _handle_gateway_call(
		lambda: create_purchase_invoice_from_receipt_service(
			receipt_name=receipt_name,
			invoice_items=invoice_items,
			kwargs=_merge_kwargs(kwargs, extra_kwargs),
		),
		success_code="PURCHASE_INVOICE_CREATED",
	)


@frappe.whitelist()
def search_product(
	search_key: str,
	price_list: str = "Standard Selling",
	currency: str | None = None,
	warehouse: str | None = None,
	company: str | None = None,
	limit: int = 20,
):
	return _handle_gateway_call(
		lambda: search_product_service(
			search_key=search_key,
			price_list=price_list,
			currency=currency,
			warehouse=warehouse,
			company=company,
			limit=limit,
		),
		success_code="PRODUCTS_FETCHED",
	)


@frappe.whitelist()
def search_product_v2(
	search_key: str = "",
	price_list: str = "Standard Selling",
	currency: str | None = None,
	warehouse: str | None = None,
	company: str | None = None,
	limit: int = 20,
	disabled: int | None = 0,
	item_group: str | None = None,
	brand: str | None = None,
	search_fields=None,
	sort_by: str = "relevance",
	sort_order: str = "asc",
	in_stock_only: bool = False,
	item_context: str | None = "sales",
):
	return _handle_gateway_call(
		lambda: search_product_v2_service(
			search_key=search_key,
			price_list=price_list,
			currency=currency,
			warehouse=warehouse,
			company=company,
			limit=limit,
			disabled=disabled,
			item_group=item_group,
			brand=brand,
			search_fields=search_fields,
			sort_by=sort_by,
			sort_order=sort_order,
			in_stock_only=in_stock_only,
			item_context=item_context,
		),
		success_code="PRODUCTS_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def create_product_and_stock(item_name: str, warehouse: str | None = None, opening_qty: float = 0, **kwargs):
	return _handle_gateway_call(
		lambda: create_product_and_stock_service(
			item_name=item_name,
			warehouse=warehouse,
			opening_qty=opening_qty,
			**kwargs,
		),
		success_code="PRODUCT_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def create_product_v2(item_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: create_product_v2_service(item_name=item_name, **kwargs),
		success_code="PRODUCT_CREATED",
	)


@frappe.whitelist()
def list_products_v2(
	search_key: str | None = None,
	warehouse: str | None = None,
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 20,
	start: int = 0,
	item_group: str | None = None,
	brand: str | None = None,
	disabled: int | None = None,
	in_stock_only: bool = False,
	price_list: str = "Standard Selling",
	currency: str | None = None,
	selling_price_lists=None,
	buying_price_lists=None,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	return _handle_gateway_call(
		lambda: list_products_v2_service(
			search_key=search_key,
			warehouse=warehouse,
			company=company,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
			start=start,
			item_group=item_group,
			brand=brand,
			disabled=disabled,
			in_stock_only=in_stock_only,
			price_list=price_list,
			currency=currency,
			selling_price_lists=selling_price_lists,
			buying_price_lists=buying_price_lists,
			sort_by=sort_by,
			sort_order=sort_order,
		),
		success_code="PRODUCTS_FETCHED",
	)


@frappe.whitelist()
def get_product_detail_v2(
	item_code: str,
	warehouse: str | None = None,
	company: str | None = None,
	price_list: str = "Standard Selling",
	currency: str | None = None,
):
	return _handle_gateway_call(
		lambda: get_product_detail_v2_service(
			item_code=item_code,
			warehouse=warehouse,
			company=company,
			price_list=price_list,
			currency=currency,
		),
		success_code="PRODUCT_DETAIL_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def update_product_v2(item_code: str, **kwargs):
	return _handle_gateway_call(
		lambda: update_product_v2_service(item_code=item_code, **kwargs),
		success_code="PRODUCT_UPDATED",
	)


@frappe.whitelist(methods=["POST"])
def disable_product_v2(item_code: str, disabled: bool = True, **kwargs):
	return _handle_gateway_call(
		lambda: disable_product_v2_service(item_code=item_code, disabled=disabled, **kwargs),
		success_code="PRODUCT_UPDATED",
	)


@frappe.whitelist(methods=["POST"])
def add_product_barcode_v2(item_code: str, barcode: str, set_primary: bool = False, **kwargs):
	return _handle_gateway_call(
		lambda: add_product_barcode_v2_service(
			item_code=item_code,
			barcode=barcode,
			set_primary=set_primary,
			**kwargs,
		),
		success_code="PRODUCT_BARCODE_ADDED",
	)


@frappe.whitelist(methods=["POST"])
def set_primary_product_barcode_v2(item_code: str, barcode: str, **kwargs):
	return _handle_gateway_call(
		lambda: set_primary_product_barcode_v2_service(item_code=item_code, barcode=barcode, **kwargs),
		success_code="PRODUCT_BARCODE_UPDATED",
	)


@frappe.whitelist(methods=["POST"])
def delete_product_barcode_v2(item_code: str, barcode: str, **kwargs):
	return _handle_gateway_call(
		lambda: delete_product_barcode_v2_service(item_code=item_code, barcode=barcode, **kwargs),
		success_code="PRODUCT_BARCODE_DELETED",
	)


@frappe.whitelist(methods=["POST"])
def upload_item_image(
	filename: str,
	file_content_base64: str,
	content_type: str | None = None,
	item_code: str | None = None,
	is_private: bool = False,
):
	return _handle_gateway_call(
		lambda: upload_item_image_service(
			filename=filename,
			file_content_base64=file_content_base64,
			content_type=content_type,
			item_code=item_code,
			is_private=is_private,
		),
		success_code="ITEM_IMAGE_UPLOADED",
	)


@frappe.whitelist(methods=["POST"])
def replace_item_image(
	item_code: str,
	filename: str,
	file_content_base64: str,
	content_type: str | None = None,
	is_private: bool = False,
):
	return _handle_gateway_call(
		lambda: replace_item_image_service(
			item_code=item_code,
			filename=filename,
			file_content_base64=file_content_base64,
			content_type=content_type,
			is_private=is_private,
		),
		success_code="ITEM_IMAGE_REPLACED",
	)


@frappe.whitelist(methods=["POST"])
def delete_item_image(item_code: str):
	return _handle_gateway_call(
		lambda: delete_item_image_service(item_code=item_code),
		success_code="ITEM_IMAGE_DELETED",
	)


@frappe.whitelist(methods=["POST"])
def confirm_pending_document(doctype: str, docname: str, **kwargs):
	return _handle_gateway_call(
		lambda: confirm_pending_document_service(doctype=doctype, docname=docname, **kwargs),
		success_code="DOCUMENT_CONFIRMED",
	)


@frappe.whitelist(methods=["POST"])
def cancel_payment_entry(payment_entry_name: str, **kwargs):
	return _handle_gateway_call(
		lambda: cancel_payment_entry_service(payment_entry_name=payment_entry_name, **kwargs),
		success_code="PAYMENT_ENTRY_CANCELLED",
	)


@frappe.whitelist(methods=["POST"])
def update_payment_status(reference_doctype: str, reference_name: str, paid_amount: float, **kwargs):
	return _handle_gateway_call(
		lambda: update_payment_status_service(
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			paid_amount=paid_amount,
			**kwargs,
		),
		success_code="PAYMENT_RECORDED",
	)


@frappe.whitelist(methods=["POST"])
def create_customer_refund(return_invoice_name: str, refund_amount: float, **kwargs):
	return _handle_gateway_call(
		lambda: create_customer_refund_service(
			return_invoice_name=return_invoice_name,
			refund_amount=refund_amount,
			**kwargs,
		),
		success_code="CUSTOMER_REFUND_CREATED",
	)


@frappe.whitelist()
def get_customer_refund_context_v1(return_invoice_name: str):
	return _handle_gateway_call(
		lambda: get_customer_refund_context_v1_service(return_invoice_name=return_invoice_name),
		success_code="CUSTOMER_REFUND_CONTEXT_LOADED",
	)


@frappe.whitelist(methods=["POST"])
def create_supplier_refund(return_invoice_name: str, refund_amount: float, **kwargs):
	return _handle_gateway_call(
		lambda: create_supplier_refund_service(
			return_invoice_name=return_invoice_name,
			refund_amount=refund_amount,
			**kwargs,
		),
		success_code="SUPPLIER_REFUND_CREATED",
	)


@frappe.whitelist()
def get_supplier_refund_context_v1(return_invoice_name: str):
	return _handle_gateway_call(
		lambda: get_supplier_refund_context_v1_service(return_invoice_name=return_invoice_name),
		success_code="SUPPLIER_REFUND_CONTEXT_LOADED",
	)


@frappe.whitelist()
def get_payment_entry_detail_v1(payment_entry_name: str):
	return _handle_gateway_call(
		lambda: get_payment_entry_detail_v1_service(payment_entry_name=payment_entry_name),
		success_code="PAYMENT_ENTRY_DETAIL_FETCHED",
	)


@frappe.whitelist(methods=["POST"])
def record_supplier_payment(reference_name: str, paid_amount: float, **kwargs):
	return _handle_gateway_call(
		lambda: record_supplier_payment_service(
			reference_name=reference_name,
			paid_amount=paid_amount,
			**kwargs,
		),
		success_code="SUPPLIER_PAYMENT_RECORDED",
	)


@frappe.whitelist(methods=["POST"])
def process_sales_return(source_doctype: str, source_name: str, return_items=None, **kwargs):
	return _handle_gateway_call(
		lambda: process_sales_return_service(
			source_doctype=source_doctype,
			source_name=source_name,
			return_items=return_items,
			**kwargs,
		),
		success_code="SALES_RETURN_CREATED",
	)


@frappe.whitelist(methods=["POST"])
def process_purchase_return(source_doctype: str, source_name: str, return_items=None, **kwargs):
	return _handle_gateway_call(
		lambda: process_purchase_return_service(
			source_doctype=source_doctype,
			source_name=source_name,
			return_items=return_items,
			**kwargs,
		),
		success_code="PURCHASE_RETURN_CREATED",
	)
