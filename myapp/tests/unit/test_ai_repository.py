from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.services import ai_repository
from myapp.services.ai_repository import (
	_nearest_rank_percentile,
	fail_run,
	get_conversation,
	list_drafts,
	mark_draft_executed,
	submit_feedback,
	update_draft,
)
from myapp.utils.ai_errors import AiDraftVersionConflictError, AiServiceError


class TestAiRepository(TestCase):
	def test_fail_run_persists_stable_ai_error_code(self):
		with patch.object(ai_repository, "frappe") as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value="2026-07-23 23:30:00",
		):
			mock_frappe.db.table_exists.return_value = False
			fail_run(
				run_id="AI-RUN-1",
				user="user@example.com",
				error=AiServiceError(
					"AI 请求过于频繁，请稍后重试。",
					code="AI_REQUEST_RATE_LIMITED",
					http_status=429,
				),
				latency_ms=120,
			)

		parameters = mock_frappe.db.sql.call_args.args[1]
		self.assertEqual(parameters[3], "AI_REQUEST_RATE_LIMITED")

	def test_fail_run_hides_unknown_internal_error_details(self):
		with patch.object(ai_repository, "frappe") as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value="2026-07-23 23:30:00",
		):
			mock_frappe.PermissionError = frappe.PermissionError
			mock_frappe.AuthenticationError = frappe.AuthenticationError
			mock_frappe.ValidationError = frappe.ValidationError
			mock_frappe.db.table_exists.return_value = False
			fail_run(
				run_id="AI-RUN-2",
				user="user@example.com",
				error=RuntimeError("database password leaked"),
				latency_ms=120,
			)

		parameters = mock_frappe.db.sql.call_args.args[1]
		self.assertEqual(parameters[3], "AI_RUN_FAILED")
		self.assertNotIn("password", parameters[4])

	def test_update_draft_locks_and_advances_the_expected_version(self):
		updated = {"name": "AI-DRAFT-1", "status": "draft", "version": 3}
		with patch.object(ai_repository, "get_draft", return_value=updated), patch.object(
			ai_repository, "frappe",
		) as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value="2026-07-19 12:00:00",
		):
			mock_frappe.db.sql.side_effect = [
				[frappe._dict({"status": "draft", "version_no": 2})],
				None,
				None,
				None,
			]
			result = update_draft(
				draft_id="AI-DRAFT-1",
				user="user@example.com",
				payload={"remarks": "修改后"},
				validation={"ready_for_handoff": True},
				expected_version=2,
			)

		self.assertEqual(result["version"], 3)
		self.assertIn("FOR UPDATE", mock_frappe.db.sql.call_args_list[0].args[0])
		update_parameters = mock_frappe.db.sql.call_args_list[1].args[1]
		self.assertEqual(update_parameters[2], 3)

	def test_update_draft_rejects_a_stale_expected_version(self):
		with patch.object(ai_repository, "frappe") as mock_frappe:
			mock_frappe.db.sql.return_value = [
				frappe._dict({"status": "draft", "version_no": 3}),
			]

			with self.assertRaises(AiDraftVersionConflictError):
				update_draft(
					draft_id="AI-DRAFT-1",
					user="user@example.com",
					payload={},
					validation={},
					expected_version=2,
				)

	def test_mark_draft_executed_persists_business_receipt(self):
		draft = {
			"name": "AI-DRAFT-1", "status": "draft", "version": 2,
		}
		executed = {**draft, "status": "executed", "execution": {"target_name": "SO-001"}}
		with patch.object(ai_repository, "get_draft", side_effect=[draft, executed]), patch.object(
			ai_repository, "frappe",
		) as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value="2026-07-18 12:00:00",
		):
			result = mark_draft_executed(
				draft_id="AI-DRAFT-1", user="user@example.com", request_id="REQ-1",
				target_doctype="Sales Order", target_name="SO-001",
				result={"status": "success", "order": "SO-001"},
			)

		self.assertEqual(result["status"], "executed")
		parameters = mock_frappe.db.sql.call_args.args[1]
		self.assertEqual(parameters[2:8], ("REQ-1", "user@example.com", "2026-07-18 12:00:00", "Sales Order", "SO-001", mock_frappe.as_json.return_value))
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
			"first_token_ms": 240,
			"error_code": None, "error": None, "feedback_rating": "positive",
			"feedback_category": "helpful", "feedback_comment": None,
		})
		with patch.object(ai_repository, "frappe") as mock_frappe, patch.object(
			ai_repository, "_get_owned_conversation", return_value=conversation,
		):
			mock_frappe.db.table_exists.return_value = True
			mock_frappe.db.sql.return_value = [message]
			result = get_conversation(
				conversation_id="AI-CONV-1", user="user@example.com", limit=40,
			)

		self.assertEqual(result["messages"][0]["run"]["usage"]["total_tokens"], 12)
		self.assertEqual(result["messages"][0]["run"]["first_token_ms"], 240)
		self.assertEqual(result["messages"][0]["feedback"]["rating"], "positive")
		self.assertEqual(result["pagination"], {
			"before_sequence": None,
			"limit": 40,
			"total": 1,
			"returned_count": 1,
			"has_more": False,
			"next_before_sequence": None,
		})
		query_parameters = mock_frappe.db.sql.call_args.args[1]
		self.assertEqual(
			query_parameters,
			("user@example.com", "user@example.com", "AI-CONV-1", 41),
		)

	def test_get_conversation_pages_backwards_with_a_stable_sequence_cursor(self):
		conversation = frappe._dict({
			"name": "AI-CONV-1", "title": "长会话", "status": "active",
			"company_scope": "Demo Company", "message_count": 84,
			"last_message_at": "2026-07-24 10:00:00", "creation": "2026-07-20 09:00:00",
			"modified": "2026-07-24 10:00:00",
		})
		rows = [
			frappe._dict({
				"name": f"AI-MSG-{sequence}", "sequence_no": sequence,
				"role": "assistant" if sequence % 2 == 0 else "user",
				"content": f"消息 {sequence}", "scenario": "general", "run_id": None,
				"citations_json": "[]", "prompt_version": None,
				"creation": "2026-07-24 10:00:00",
			})
			for sequence in range(44, 2, -1)
		]
		with patch.object(ai_repository, "frappe") as mock_frappe, patch.object(
			ai_repository, "_get_owned_conversation", return_value=conversation,
		):
			mock_frappe.db.table_exists.return_value = True
			mock_frappe.db.sql.return_value = rows
			result = get_conversation(
				conversation_id="AI-CONV-1",
				user="user@example.com",
				before_sequence=45,
				limit=40,
			)

		self.assertEqual(result["messages"][0]["sequence"], 5)
		self.assertEqual(result["messages"][-1]["sequence"], 44)
		self.assertEqual(result["pagination"]["returned_count"], 40)
		self.assertTrue(result["pagination"]["has_more"])
		self.assertEqual(result["pagination"]["next_before_sequence"], 5)
		query = mock_frappe.db.sql.call_args.args[0]
		self.assertIn("m.sequence_no < %s", query)
		self.assertIn("ORDER BY m.sequence_no DESC", query)
		self.assertEqual(
			mock_frappe.db.sql.call_args.args[1],
			("user@example.com", "user@example.com", "AI-CONV-1", 45, 41),
		)
