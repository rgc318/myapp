from myapp.services.ai_service import (
	archive_ai_conversation_v1 as archive_ai_conversation_v1_service,
	chat_ai_v1 as chat_ai_v1_service,
	create_ai_conversation_v1 as create_ai_conversation_v1_service,
	discard_ai_draft_v1 as discard_ai_draft_v1_service,
	generate_ai_inventory_adjustment_draft_v1 as generate_ai_inventory_adjustment_draft_v1_service,
	generate_ai_sales_order_draft_v1 as generate_ai_sales_order_draft_v1_service,
	generate_ai_purchase_order_draft_v1 as generate_ai_purchase_order_draft_v1_service,
	get_ai_draft_v1 as get_ai_draft_v1_service,
	get_ai_conversation_v1 as get_ai_conversation_v1_service,
	list_ai_conversations_v1 as list_ai_conversations_v1_service,
	list_ai_draft_versions_v1 as list_ai_draft_versions_v1_service,
	stream_ai_message_v1 as stream_ai_message_v1_service,
	submit_ai_feedback_v1 as submit_ai_feedback_v1_service,
	prepare_ai_draft_handoff_v1 as prepare_ai_draft_handoff_v1_service,
	restore_ai_draft_version_v1 as restore_ai_draft_version_v1_service,
	update_ai_draft_v1 as update_ai_draft_v1_service,
)


def create_ai_conversation_v1(title: str | None = None, company: str | None = None):
	return create_ai_conversation_v1_service(title=title, company=company)


def list_ai_conversations_v1(status: str = "active", start: int = 0, limit: int = 20):
	return list_ai_conversations_v1_service(status=status, start=start, limit=limit)


def get_ai_conversation_v1(conversation_id: str):
	return get_ai_conversation_v1_service(conversation_id=conversation_id)


def archive_ai_conversation_v1(conversation_id: str):
	return archive_ai_conversation_v1_service(conversation_id=conversation_id)


def chat_ai_v1(
	messages=None,
	scenario: str | None = None,
	company: str | None = None,
	conversation_id: str | None = None,
	content: str | None = None,
):
	return chat_ai_v1_service(
		messages=messages,
		scenario=scenario,
		company=company,
		conversation_id=conversation_id,
		content=content,
	)


def stream_ai_message_v1(
	content: str,
	scenario: str | None = None,
	company: str | None = None,
	conversation_id: str | None = None,
):
	return stream_ai_message_v1_service(
		content=content,
		scenario=scenario,
		company=company,
		conversation_id=conversation_id,
	)


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
):
	return generate_ai_sales_order_draft_v1_service(
		content=content, company=company, conversation_id=conversation_id,
	)


def generate_ai_purchase_order_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
):
	return generate_ai_purchase_order_draft_v1_service(
		content=content, company=company, conversation_id=conversation_id,
	)


def generate_ai_inventory_adjustment_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
):
	return generate_ai_inventory_adjustment_draft_v1_service(
		content=content, company=company, conversation_id=conversation_id,
	)


def get_ai_draft_v1(draft_id: str):
	return get_ai_draft_v1_service(draft_id=draft_id)


def prepare_ai_draft_handoff_v1(draft_id: str):
	return prepare_ai_draft_handoff_v1_service(draft_id=draft_id)


def update_ai_draft_v1(draft_id: str, payload):
	return update_ai_draft_v1_service(draft_id=draft_id, payload=payload)


def discard_ai_draft_v1(draft_id: str):
	return discard_ai_draft_v1_service(draft_id=draft_id)


def list_ai_draft_versions_v1(draft_id: str):
	return list_ai_draft_versions_v1_service(draft_id=draft_id)


def restore_ai_draft_version_v1(draft_id: str, version: int):
	return restore_ai_draft_version_v1_service(draft_id=draft_id, version=version)
