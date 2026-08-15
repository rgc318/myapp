from myapp.services.ai_service import (
	archive_ai_conversation_v1 as archive_ai_conversation_v1_service,
	chat_ai_v1 as chat_ai_v1_service,
	cancel_ai_run_v1 as cancel_ai_run_v1_service,
	create_ai_conversation_v1 as create_ai_conversation_v1_service,
	discard_ai_draft_v1 as discard_ai_draft_v1_service,
	execute_ai_draft_v1 as execute_ai_draft_v1_service,
	generate_ai_inventory_adjustment_draft_v1 as generate_ai_inventory_adjustment_draft_v1_service,
	generate_ai_sales_order_draft_v1 as generate_ai_sales_order_draft_v1_service,
	generate_ai_purchase_order_draft_v1 as generate_ai_purchase_order_draft_v1_service,
	generate_ai_product_setup_draft_v1 as generate_ai_product_setup_draft_v1_service,
	get_ai_draft_v1 as get_ai_draft_v1_service,
	get_ai_agent_approval_v1 as get_ai_agent_approval_v1_service,
	get_ai_conversation_v1 as get_ai_conversation_v1_service,
	list_ai_conversations_v1 as list_ai_conversations_v1_service,
	list_ai_drafts_v1 as list_ai_drafts_v1_service,
	list_ai_agent_approvals_v1 as list_ai_agent_approvals_v1_service,
	list_ai_draft_versions_v1 as list_ai_draft_versions_v1_service,
	rename_ai_conversation_v1 as rename_ai_conversation_v1_service,
	reset_ai_conversation_context_v1 as reset_ai_conversation_context_v1_service,
	resume_ai_run_v1 as resume_ai_run_v1_service,
	resume_ai_agent_approval_v1 as resume_ai_agent_approval_v1_service,
	review_ai_agent_approval_v1 as review_ai_agent_approval_v1_service,
	stream_ai_run_resume_v1 as stream_ai_run_resume_v1_service,
	stream_ai_message_v1 as stream_ai_message_v1_service,
	submit_ai_feedback_v1 as submit_ai_feedback_v1_service,
	prepare_ai_draft_handoff_v1 as prepare_ai_draft_handoff_v1_service,
	refresh_ai_business_result_v1 as refresh_ai_business_result_v1_service,
	restore_ai_draft_version_v1 as restore_ai_draft_version_v1_service,
	resolve_ai_scenario_v1 as resolve_ai_scenario_v1_service,
	update_ai_draft_v1 as update_ai_draft_v1_service,
)
from myapp.services.ai_vector_service import (
	cleanup_excluded_product_vectors_v1 as cleanup_excluded_product_vectors_v1_service,
	get_product_vector_index_status_v1 as get_product_vector_index_status_v1_service,
	rebuild_product_vector_index_v1 as rebuild_product_vector_index_v1_service,
)
from myapp.services.ai_vector_governance_service import (
	approve_ai_vector_release_v1 as approve_ai_vector_release_v1_service,
	create_ai_vector_release_v1 as create_ai_vector_release_v1_service,
	get_ai_vector_release_v1 as get_ai_vector_release_v1_service,
	list_ai_vector_releases_v1 as list_ai_vector_releases_v1_service,
	publish_ai_vector_release_v1 as publish_ai_vector_release_v1_service,
	retry_ai_vector_release_v1 as retry_ai_vector_release_v1_service,
	rollback_ai_vector_release_v1 as rollback_ai_vector_release_v1_service,
	validate_ai_vector_release_v1 as validate_ai_vector_release_v1_service,
)
from myapp.services.ai_model_governance_service import (
	approve_ai_model_policy_v1 as approve_ai_model_policy_v1_service,
	check_ai_model_availability_v1 as check_ai_model_availability_v1_service,
	get_ai_model_governance_overview_v1 as get_ai_model_governance_overview_v1_service,
	get_ai_model_policy_v1 as get_ai_model_policy_v1_service,
	get_ai_model_usage_summary_v1 as get_ai_model_usage_summary_v1_service,
	list_ai_audit_events_v1 as list_ai_audit_events_v1_service,
	list_ai_models_v1 as list_ai_models_v1_service,
	list_ai_selectable_models_v1 as list_ai_selectable_models_v1_service,
	list_ai_model_policies_v1 as list_ai_model_policies_v1_service,
	publish_ai_model_policy_v1 as publish_ai_model_policy_v1_service,
	rollback_ai_model_policy_v1 as rollback_ai_model_policy_v1_service,
	save_ai_model_policy_draft_v1 as save_ai_model_policy_draft_v1_service,
	sync_ai_model_registry_v1 as sync_ai_model_registry_v1_service,
	update_ai_model_registry_v1 as update_ai_model_registry_v1_service,
	validate_ai_model_policy_v1 as validate_ai_model_policy_v1_service,
)
from myapp.services.ai_data_task_service import (
	analyze_ai_product_data_v1 as analyze_ai_product_data_v1_service,
	create_ai_data_task_v1 as create_ai_data_task_v1_service,
	execute_ai_data_task_v1 as execute_ai_data_task_v1_service,
	get_ai_data_task_v1 as get_ai_data_task_v1_service,
	list_ai_data_tasks_v1 as list_ai_data_tasks_v1_service,
	review_ai_data_task_v1 as review_ai_data_task_v1_service,
	rollback_ai_data_task_v1 as rollback_ai_data_task_v1_service,
)
from myapp.services.ai_attachment_service import (
	discard_ai_attachment as discard_ai_attachment_service,
	upload_ai_image_attachment as upload_ai_image_attachment_service,
)


def upload_ai_image_attachment_v1(
	filename: str, file_content_base64: str, content_type: str,
):
	return upload_ai_image_attachment_service(
		filename=filename,
		file_content_base64=file_content_base64,
		content_type=content_type,
	)


def discard_ai_attachment_v1(attachment_id: str):
	return discard_ai_attachment_service(attachment_id=attachment_id)


def create_ai_conversation_v1(title: str | None = None, company: str | None = None):
	return create_ai_conversation_v1_service(title=title, company=company)


def list_ai_conversations_v1(
	status: str = "active", search: str | None = None,
	start: int = 0, limit: int = 20,
):
	return list_ai_conversations_v1_service(
		status=status, search=search, start=start, limit=limit,
	)


def rename_ai_conversation_v1(conversation_id: str, title: str):
	return rename_ai_conversation_v1_service(conversation_id=conversation_id, title=title)


def get_ai_conversation_v1(
	conversation_id: str,
	before_sequence: int | None = None,
	limit: int = 40,
):
	return get_ai_conversation_v1_service(
		conversation_id=conversation_id,
		before_sequence=before_sequence,
		limit=limit,
	)


def archive_ai_conversation_v1(conversation_id: str):
	return archive_ai_conversation_v1_service(conversation_id=conversation_id)


def reset_ai_conversation_context_v1(conversation_id: str):
	return reset_ai_conversation_context_v1_service(conversation_id=conversation_id)


def chat_ai_v1(
	messages=None,
	scenario: str | None = None,
	company: str | None = None,
	conversation_id: str | None = None,
	content: str | None = None,
	model_alias: str | None = None,
	attachment_ids=None,
):
	return chat_ai_v1_service(
		messages=messages,
		scenario=scenario,
		company=company,
		conversation_id=conversation_id,
		content=content,
		model_alias=model_alias,
		attachment_ids=attachment_ids,
	)


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


def cancel_ai_run_v1(run_id: str):
	return cancel_ai_run_v1_service(run_id=run_id)


def resume_ai_run_v1(run_id: str):
	return resume_ai_run_v1_service(run_id=run_id)


def get_ai_agent_approval_v1(approval_id: str):
	return get_ai_agent_approval_v1_service(approval_id=approval_id)


def list_ai_agent_approvals_v1(
	run_id: str | None = None, status: str | None = None, start: int = 0, limit: int = 20,
):
	return list_ai_agent_approvals_v1_service(
		run_id=run_id, status=status, start=start, limit=limit,
	)


def review_ai_agent_approval_v1(
	approval_id: str, decision: str, expected_version: int, reason: str | None = None,
):
	return review_ai_agent_approval_v1_service(
		approval_id=approval_id, decision=decision,
		expected_version=expected_version, reason=reason,
	)


def resume_ai_agent_approval_v1(approval_id: str):
	return resume_ai_agent_approval_v1_service(approval_id=approval_id)


def stream_ai_run_resume_v1(run_id: str):
	return stream_ai_run_resume_v1_service(run_id=run_id)


def resolve_ai_scenario_v1(
	content: str | None = None, attachment_ids=None, model_alias: str | None = None,
):
	return resolve_ai_scenario_v1_service(
		content=content, attachment_ids=attachment_ids, model_alias=model_alias,
	)


def refresh_ai_business_result_v1(result_set):
	return refresh_ai_business_result_v1_service(result_set=result_set)


def submit_ai_feedback_v1(
	run_id: str,
	rating: str,
	category: str | None = None,
	comment: str | None = None,
):
	return submit_ai_feedback_v1_service(
		run_id=run_id,
		rating=rating,
		category=category,
		comment=comment,
	)


def generate_ai_sales_order_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
	attachment_ids=None,
	retry_run_id: str | None = None,
):
	return generate_ai_sales_order_draft_v1_service(
		content=content, company=company, conversation_id=conversation_id,
		model_alias=model_alias, attachment_ids=attachment_ids, retry_run_id=retry_run_id,
	)


def generate_ai_purchase_order_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
	attachment_ids=None,
	retry_run_id: str | None = None,
):
	return generate_ai_purchase_order_draft_v1_service(
		content=content, company=company, conversation_id=conversation_id,
		model_alias=model_alias, attachment_ids=attachment_ids, retry_run_id=retry_run_id,
	)


def generate_ai_inventory_adjustment_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
	attachment_ids=None,
	retry_run_id: str | None = None,
):
	return generate_ai_inventory_adjustment_draft_v1_service(
		content=content, company=company, conversation_id=conversation_id,
		model_alias=model_alias, attachment_ids=attachment_ids, retry_run_id=retry_run_id,
	)


def generate_ai_product_setup_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
	attachment_ids=None,
	retry_run_id: str | None = None,
):
	return generate_ai_product_setup_draft_v1_service(
		content=content, company=company, conversation_id=conversation_id,
		model_alias=model_alias, attachment_ids=attachment_ids, retry_run_id=retry_run_id,
	)


def list_ai_selectable_models_v1():
	return list_ai_selectable_models_v1_service()


def get_ai_draft_v1(draft_id: str):
	return get_ai_draft_v1_service(draft_id=draft_id)


def list_ai_drafts_v1(
	status: str = "draft", draft_type: str | None = None,
	start: int = 0, limit: int = 20,
):
	return list_ai_drafts_v1_service(
		status=status, draft_type=draft_type, start=start, limit=limit,
	)


def prepare_ai_draft_handoff_v1(draft_id: str):
	return prepare_ai_draft_handoff_v1_service(draft_id=draft_id)


def update_ai_draft_v1(
	draft_id: str, payload, expected_version: int, request_id: str | None = None,
):
	return update_ai_draft_v1_service(
		draft_id=draft_id, payload=payload,
		expected_version=expected_version, request_id=request_id,
	)


def discard_ai_draft_v1(draft_id: str):
	return discard_ai_draft_v1_service(draft_id=draft_id)


def execute_ai_draft_v1(
	draft_id: str, expected_version: int, confirmed: bool | int = False,
	request_id: str | None = None,
):
	return execute_ai_draft_v1_service(
		draft_id=draft_id, expected_version=expected_version,
		confirmed=confirmed, request_id=request_id,
	)


def list_ai_draft_versions_v1(draft_id: str):
	return list_ai_draft_versions_v1_service(draft_id=draft_id)


def restore_ai_draft_version_v1(
	draft_id: str, version: int, expected_version: int,
	request_id: str | None = None,
):
	return restore_ai_draft_version_v1_service(
		draft_id=draft_id, version=version,
		expected_version=expected_version, request_id=request_id,
	)


def get_ai_product_vector_status_v1(failure_limit: int = 20):
	return get_product_vector_index_status_v1_service(failure_limit=failure_limit)


def rebuild_ai_product_vector_index_v1(
	item_codes=None,
	failed_only: bool | int = False,
	limit: int = 100,
):
	return rebuild_product_vector_index_v1_service(
		item_codes=item_codes,
		failed_only=failed_only,
		limit=limit,
	)


def cleanup_excluded_ai_product_vectors_v1(
	dry_run: bool | int = True,
	limit: int = 5000,
	reason: str | None = None,
	request_id: str | None = None,
):
	return cleanup_excluded_product_vectors_v1_service(
		dry_run=dry_run,
		limit=limit,
		reason=reason,
		request_id=request_id,
	)


def analyze_ai_product_data_v1(item_codes=None, limit: int = 50, request_id: str | None = None):
	return analyze_ai_product_data_v1_service(item_codes=item_codes, limit=limit, request_id=request_id)


def create_ai_data_task_v1(payload, reason: str, request_id: str | None = None):
	return create_ai_data_task_v1_service(payload=payload, reason=reason, request_id=request_id)


def list_ai_data_tasks_v1(
	status: str | None = None, risk_level: str | None = None,
	task_type: str | None = None, start: int = 0, limit: int = 20,
):
	return list_ai_data_tasks_v1_service(
		status=status, risk_level=risk_level, task_type=task_type, start=start, limit=limit,
	)


def get_ai_data_task_v1(task_name: str):
	return get_ai_data_task_v1_service(task_name=task_name)


def review_ai_data_task_v1(
	task_name: str, action: str, reason: str, request_id: str | None = None,
):
	return review_ai_data_task_v1_service(
		task_name=task_name, action=action, reason=reason, request_id=request_id,
	)


def execute_ai_data_task_v1(task_name: str, request_id: str | None = None):
	return execute_ai_data_task_v1_service(task_name=task_name, request_id=request_id)


def rollback_ai_data_task_v1(task_name: str, reason: str, request_id: str | None = None):
	return rollback_ai_data_task_v1_service(
		task_name=task_name, reason=reason, request_id=request_id,
	)


def list_ai_vector_releases_v1(start: int = 0, limit: int = 20):
	return list_ai_vector_releases_v1_service(start=start, limit=limit)


def get_ai_vector_release_v1(release_code: str, failure_limit: int = 50):
	return get_ai_vector_release_v1_service(release_code=release_code, failure_limit=failure_limit)


def create_ai_vector_release_v1(payload, reason: str, request_id: str | None = None):
	return create_ai_vector_release_v1_service(payload=payload, reason=reason, request_id=request_id)


def retry_ai_vector_release_v1(release_code: str, request_id: str | None = None):
	return retry_ai_vector_release_v1_service(release_code=release_code, request_id=request_id)


def validate_ai_vector_release_v1(release_code: str, request_id: str | None = None):
	return validate_ai_vector_release_v1_service(release_code=release_code, request_id=request_id)


def approve_ai_vector_release_v1(release_code: str, reason: str, request_id: str | None = None):
	return approve_ai_vector_release_v1_service(release_code=release_code, reason=reason, request_id=request_id)


def publish_ai_vector_release_v1(release_code: str, reason: str, request_id: str | None = None):
	return publish_ai_vector_release_v1_service(release_code=release_code, reason=reason, request_id=request_id)


def rollback_ai_vector_release_v1(
	target_release_code: str, reason: str, request_id: str | None = None,
):
	return rollback_ai_vector_release_v1_service(
		target_release_code=target_release_code, reason=reason, request_id=request_id,
	)


def get_ai_model_governance_overview_v1():
	return get_ai_model_governance_overview_v1_service()


def list_ai_audit_events_v1(
	search: str | None = None, action: str | None = None,
	object_type: str | None = None, priority: str | None = None,
	date_from: str | None = None, date_to: str | None = None,
	start: int = 0, limit: int = 20,
):
	return list_ai_audit_events_v1_service(
		search=search, action=action, object_type=object_type, priority=priority,
		date_from=date_from, date_to=date_to, start=start, limit=limit,
	)


def get_ai_model_policy_v1(policy_code: str):
	return get_ai_model_policy_v1_service(policy_code=policy_code)


def sync_ai_model_registry_v1(request_id: str | None = None):
	return sync_ai_model_registry_v1_service(request_id=request_id)


def check_ai_model_availability_v1(model_aliases=None, request_id: str | None = None):
	return check_ai_model_availability_v1_service(
		model_aliases=model_aliases,
		request_id=request_id,
	)


def list_ai_models_v1(
	search: str | None = None,
	capability: str | None = None,
	status: str | None = None,
	start: int = 0,
	limit: int = 20,
):
	return list_ai_models_v1_service(
		search=search, capability=capability, status=status, start=start, limit=limit,
	)


def update_ai_model_registry_v1(
	model_alias: str, payload, reason: str, request_id: str | None = None,
):
	return update_ai_model_registry_v1_service(
		model_alias=model_alias, payload=payload, reason=reason, request_id=request_id,
	)


def list_ai_model_policies_v1(
	search: str | None = None,
	status: str | None = None,
	start: int = 0,
	limit: int = 20,
):
	return list_ai_model_policies_v1_service(search=search, status=status, start=start, limit=limit)


def save_ai_model_policy_draft_v1(payload, reason: str, request_id: str | None = None):
	return save_ai_model_policy_draft_v1_service(payload=payload, reason=reason, request_id=request_id)


def validate_ai_model_policy_v1(policy_code: str, request_id: str | None = None):
	return validate_ai_model_policy_v1_service(policy_code=policy_code, request_id=request_id)


def approve_ai_model_policy_v1(
	policy_code: str,
	reason: str,
	request_id: str | None = None,
):
	return approve_ai_model_policy_v1_service(
		policy_code=policy_code,
		reason=reason,
		request_id=request_id,
	)


def publish_ai_model_policy_v1(
	policy_code: str,
	reason: str,
	request_id: str | None = None,
):
	return publish_ai_model_policy_v1_service(
		policy_code=policy_code,
		reason=reason,
		request_id=request_id,
	)


def rollback_ai_model_policy_v1(
	policy_code: str,
	target_version: int,
	reason: str,
	request_id: str | None = None,
):
	return rollback_ai_model_policy_v1_service(
		policy_code=policy_code,
		target_version=target_version,
		reason=reason,
		request_id=request_id,
	)


def get_ai_model_usage_summary_v1(
	date_from: str | None = None,
	date_to: str | None = None,
	environment: str | None = None,
	company: str | None = None,
):
	return get_ai_model_usage_summary_v1_service(
		date_from=date_from,
		date_to=date_to,
		environment=environment,
		company=company,
	)
