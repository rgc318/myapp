from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.services import ai_repository
from myapp.services.ai_repository import (
	_nearest_rank_percentile,
	get_conversation,
	list_drafts,
	submit_feedback,
)


class TestAiRepository(TestCase):
	def test_nearest_rank_percentile_uses_sorted_observations(self):
		values = [900, 100, 500, 300, 700]

		self.assertEqual(_nearest_rank_percentile(values, 0.50), 500)
		self.assertEqual(_nearest_rank_percentile(values, 0.95), 900)

	def test_nearest_rank_percentile_handles_empty_samples(self):
		self.assertIsNone(_nearest_rank_percentile([], 0.50))

	def test_feedback_rating_change_applies_daily_counter_deltas(self):
		run = frappe._dict({
			"name": "AI-RUN-1", "conversation": "AI-CONV-1", "status": "completed",
			"trace_id": "trace-1", "scenario": "general", "environment": "production",
			"company": "Demo Company", "policy_code": "general-prod", "policy_version": 2,
			"model_alias": "erp-fast-chat", "usage_date": "2026-07-15",
			"previous_rating": "negative",
		})
		with patch.object(ai_repository, "frappe") as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value="2026-07-15 10:00:00",
		):
			mock_frappe.db.table_exists.return_value = True
			mock_frappe.db.sql.side_effect = [[run], None, None]
			result = submit_feedback(
				run_id="AI-RUN-1", user="user@example.com", rating="positive",
				category="helpful", comment=None,
			)

		self.assertEqual(result["rating"], "positive")
		daily_params = mock_frappe.db.sql.call_args_list[2].args[1]
		self.assertEqual(daily_params[-2:], (1, -1))

	def test_list_drafts_is_owner_scoped_and_paginated(self):
		row = frappe._dict({
			"name": "AI-DRAFT-1", "conversation": "AI-CONV-1", "source_run": "AI-RUN-1",
			"draft_type": "sales_order", "status": "draft", "company": "Demo Company",
			"title": "销售订单草稿", "version_no": 2, "payload_json": "{}",
			"validation_json": '{"ready_for_handoff": true}', "creation": "2026-07-16 09:00:00",
			"modified": "2026-07-16 10:00:00",
		})
		with patch.object(ai_repository, "frappe") as mock_frappe:
			mock_frappe.db.table_exists.return_value = True
			mock_frappe.db.sql.side_effect = [[frappe._dict({"total": 1})], [row]]
			result = list_drafts(
				user="user@example.com", status="draft", draft_type="sales_order",
				start=20, limit=10,
			)

		self.assertEqual(result["pagination"], {"start": 20, "limit": 10, "total": 1})
		self.assertTrue(result["items"][0]["validation"]["ready_for_handoff"])
		count_parameters = mock_frappe.db.sql.call_args_list[0].args[1]
		self.assertEqual(count_parameters, ("user@example.com", "draft", "sales_order"))

	def test_get_conversation_includes_owned_run_and_persisted_feedback(self):
		conversation = frappe._dict({
			"name": "AI-CONV-1", "title": "测试会话", "status": "active",
			"company_scope": "Demo Company", "message_count": 1,
			"last_message_at": "2026-07-16 10:00:00", "creation": "2026-07-16 09:00:00",
			"modified": "2026-07-16 10:00:00",
		})
		message = frappe._dict({
			"name": "AI-MSG-1", "sequence_no": 1, "role": "assistant", "content": "完成",
			"scenario": "general", "run_id": "AI-RUN-1", "citations_json": "[]",
			"prompt_version": "erp-readonly-v5", "creation": "2026-07-16 10:00:00",
			"run_status": "completed", "model_alias": "erp-fast-chat", "model": "provider-model",
			"trace_id": "trace-1", "prompt_tokens": 10, "completion_tokens": 2,
			"total_tokens": 12, "reasoning_tokens": 0, "latency_ms": 900,
			"error_code": None, "error": None, "feedback_rating": "positive",
			"feedback_category": "helpful", "feedback_comment": None,
		})
		with patch.object(ai_repository, "frappe") as mock_frappe, patch.object(
			ai_repository, "_get_owned_conversation", return_value=conversation,
		):
			mock_frappe.db.table_exists.return_value = True
			mock_frappe.db.sql.return_value = [message]
			result = get_conversation(conversation_id="AI-CONV-1", user="user@example.com")

		self.assertEqual(result["messages"][0]["run"]["usage"]["total_tokens"], 12)
		self.assertEqual(result["messages"][0]["feedback"]["rating"], "positive")
		query_parameters = mock_frappe.db.sql.call_args.args[1]
		self.assertEqual(query_parameters, ("user@example.com", "user@example.com", "AI-CONV-1"))
