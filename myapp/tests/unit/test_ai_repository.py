import hashlib
from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.services import ai_repository
from myapp.services.ai_repository import (
	_nearest_rank_percentile,
	_normalize_agent_checkpoint,
	_normalize_conversation_state,
	cancel_agent_run,
	fail_run,
	get_agent_run_control,
	get_agent_checkpoint,
	get_agent_tool_result,
	get_conversation_state,
	get_conversation,
	_refresh_conversation_citations,
	list_conversations,
	list_drafts,
	load_model_messages,
	record_agent_runtime_event,
	prepare_agent_run_resume,
	prepare_reviewed_agent_approval_resume,
	request_agent_tool_approval,
	get_agent_tool_approval_decision,
	review_agent_approval,
	issue_agent_capability,
	mark_draft_executed,
	rename_conversation,
	reset_conversation_state,
	start_agent_tool_step,
	submit_feedback,
	update_draft,
	update_conversation_state,
)
from myapp.utils.ai_errors import AiDraftVersionConflictError, AiServiceError


class TestAiRepository(TestCase):
	@staticmethod
	def _agent_capability_row(token: str, now: datetime):
		return frappe._dict({
			"name": "AI-RUN-1", "requested_by": "user@example.com", "status": "running",
			"allowed_tools_json": '["search_products"]',
			"capability_token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
			"capability_expires_at": now + timedelta(minutes=5),
			"cancellation_requested": 0, "company_scope": "Demo Company",
		})

	@staticmethod
	def _waiting_approval_checkpoint():
		arguments = {"query": "莫", "limit": 8}
		return {
			"schema_version": "agent-state-v1", "run_id": "AI-RUN-1",
			"stage": "waiting_approval", "next_model_step": 2, "tool_count": 0,
			"runtime_messages": [], "agent_steps": [], "tool_calls": [],
			"pending_tool_calls": [{
				"id": "call-1", "type": "function",
				"function": {"name": "search_products", "arguments": '{"query":"莫","limit":8}'},
				"arguments": arguments,
			}],
			"pending_approval": {
				"approval_id": "AI-APPROVAL-1", "call_id": "call-1",
				"tool": "search_products", "risk_level": "L3_SENSITIVE",
			},
			"tool_results": [], "citations": [], "usage": {}, "model": "model",
			"model_alias": "erp-fast-chat", "prompt_version": "erp-readonly-v7",
			"trace_id": "trace", "agent_span_id": "span", "final_content": None,
		}

	def test_record_agent_runtime_event_updates_checkpoint_atomically(self):
		now = datetime(2026, 7, 27, 12, 0, 0)
		token = "capability-token-value"
		checkpoint = {
			"schema_version": "agent-state-v1", "run_id": "AI-RUN-1",
			"stage": "input_guardrail", "next_model_step": 1, "tool_count": 0,
			"runtime_messages": [], "agent_steps": [], "tool_calls": [],
			"pending_tool_calls": [], "tool_results": [], "citations": [],
			"usage": {}, "model": "model", "trace_id": "trace", "agent_span_id": "span",
			"final_content": None,
		}
		with patch.object(ai_repository, "frappe") as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value=now,
		):
			mock_frappe.PermissionError = frappe.PermissionError
			mock_frappe.as_json.side_effect = frappe.as_json
			mock_frappe.db.sql.side_effect = [
				[self._agent_capability_row(token, now)],
				[frappe._dict({"requested_by": "user@example.com", "status": "running", "last_step_no": 2})],
				[], None, None,
			]
			result = record_agent_runtime_event(
				run_id="AI-RUN-1", event_id="runtime:input_guardrail:1",
				step_type="input_guardrail", status="completed", data={"status": "passed"},
				checkpoint=checkpoint, capability_token=token,
			)

		self.assertFalse(result["replayed"])
		self.assertEqual(result["sequence_no"], 3)
		update_call = mock_frappe.db.sql.call_args_list[-1]
		self.assertIn("agent_state_json = COALESCE", update_call.args[0])
		self.assertIn('"schema_version": "agent-state-v1"', update_call.args[1][1])

	def test_record_agent_runtime_event_replays_same_event_id(self):
		now = datetime(2026, 7, 27, 12, 0, 0)
		token = "capability-token-value"
		with patch.object(ai_repository, "frappe") as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value=now,
		):
			mock_frappe.PermissionError = frappe.PermissionError
			mock_frappe.as_json.side_effect = frappe.as_json
			mock_frappe.db.sql.side_effect = [
				[self._agent_capability_row(token, now)],
				[frappe._dict({"requested_by": "user@example.com", "status": "running", "last_step_no": 2})],
				[frappe._dict({"name": "AI-STEP-1", "sequence_no": 2})],
			]
			result = record_agent_runtime_event(
				run_id="AI-RUN-1", event_id="runtime:model_decision:1",
				step_type="model_decision", status="completed", data={},
				capability_token=token,
			)

		self.assertTrue(result["replayed"])
		self.assertEqual(mock_frappe.db.sql.call_count, 3)

	def test_get_agent_checkpoint_requires_capability_and_returns_state(self):
		now = datetime(2026, 7, 27, 12, 0, 0)
		token = "capability-token-value"
		checkpoint = {"schema_version": "agent-state-v1", "run_id": "AI-RUN-1", "stage": "input_guardrail"}
		with patch.object(ai_repository, "frappe") as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value=now,
		):
			mock_frappe.PermissionError = frappe.PermissionError
			mock_frappe.db.sql.side_effect = [
				[self._agent_capability_row(token, now)],
				[frappe._dict({"status": "running", "agent_state_json": frappe.as_json(checkpoint), "last_step_no": 4})],
			]
			result = get_agent_checkpoint(run_id="AI-RUN-1", capability_token=token)

		self.assertEqual(result["checkpoint"], checkpoint)
		self.assertEqual(result["last_step_no"], 4)

	def test_agent_checkpoint_rejects_sensitive_fields(self):
		with patch.object(ai_repository, "frappe") as mock_frappe:
			mock_frappe.throw.side_effect = ValueError("invalid checkpoint")
			with self.assertRaises(ValueError):
				_normalize_agent_checkpoint({
					"schema_version": "agent-state-v1", "run_id": "AI-RUN-1",
					"stage": "input_guardrail", "capability_token": "secret",
				}, run_id="AI-RUN-1")

	def test_cancel_agent_run_revokes_capability_and_is_idempotent(self):
		with patch.object(ai_repository, "frappe") as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value="2026-07-27 12:00:00",
		):
			mock_frappe.db.sql.side_effect = [
				[frappe._dict({"status": "running"})],
				None,
				None,
			]
			result = cancel_agent_run(run_id="AI-RUN-1", user="user@example.com")

		self.assertEqual(result, {"run_id": "AI-RUN-1", "status": "cancelled", "cancelled": True})
		self.assertIn("capability_token_hash = NULL", mock_frappe.db.sql.call_args_list[1].args[0])

	def test_request_agent_tool_approval_atomically_binds_checkpoint_and_revokes_capability(self):
		now = datetime(2026, 7, 27, 12, 0, 0)
		token = "capability-token-value"
		arguments = {"query": "莫", "limit": 8}
		checkpoint = {
			"schema_version": "agent-state-v1", "run_id": "AI-RUN-1",
			"stage": "waiting_approval", "next_model_step": 2, "tool_count": 0,
			"runtime_messages": [], "agent_steps": [], "tool_calls": [],
			"pending_tool_calls": [{
				"id": "call-1", "type": "function",
				"function": {"name": "search_products", "arguments": '{"query":"莫","limit":8}'},
				"arguments": arguments,
			}],
			"pending_approval": {
				"call_id": "call-1", "tool": "search_products", "risk_level": "L3_SENSITIVE",
			},
			"tool_results": [], "citations": [], "usage": {}, "model": "model",
			"model_alias": "erp-fast-chat", "prompt_version": "erp-readonly-v7",
			"trace_id": "trace", "agent_span_id": "span", "final_content": None,
		}
		approval_row = frappe._dict({
			"name": "AI-APPROVAL-1", "run_id": "AI-RUN-1", "call_id": "call-1",
			"tool_name": "search_products", "risk_level": "L3_SENSITIVE",
			"arguments_summary_json": frappe.as_json(arguments), "status": "pending",
			"requested_by": "user@example.com", "requested_at": now,
			"reviewed_by": None, "reviewed_at": None, "decision_reason": None,
			"expires_at": now + timedelta(minutes=15), "executed_at": None, "version": 1,
		})
		with patch.object(ai_repository, "frappe") as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value=now,
		), patch("myapp.services.ai_repository._name", side_effect=["AI-APPROVAL-1", "AI-STEP-1"]):
			mock_frappe.PermissionError = frappe.PermissionError
			mock_frappe.as_json.side_effect = frappe.as_json
			mock_frappe.db.sql.side_effect = [
				[self._agent_capability_row(token, now)],
				[frappe._dict({"requested_by": "user@example.com", "status": "running", "last_step_no": 2})],
				[], None, None, None, [approval_row],
			]
			result = request_agent_tool_approval(
				run_id="AI-RUN-1", call_id="call-1", tool="search_products",
				arguments=arguments, risk_level="L3_SENSITIVE", checkpoint=checkpoint,
				capability_token=token,
			)

		self.assertEqual(result["status"], "pending")
		self.assertEqual(result["approval_id"], "AI-APPROVAL-1")
		pause_update = mock_frappe.db.sql.call_args_list[5]
		self.assertIn("status = 'waiting_approval'", pause_update.args[0])
		self.assertIn("capability_token_hash = NULL", pause_update.args[0])
		self.assertIn('"approval_id": "AI-APPROVAL-1"', pause_update.args[1][0])

	def test_request_agent_tool_approval_rejects_tool_outside_run_allowlist(self):
		now = datetime(2026, 7, 27, 12, 0, 0)
		token = "capability-token-value"
		arguments = {"report_type": "overview", "date_from": None, "date_to": None}
		checkpoint = {
			"schema_version": "agent-state-v1", "run_id": "AI-RUN-1",
			"stage": "waiting_approval", "next_model_step": 2, "tool_count": 0,
			"runtime_messages": [], "agent_steps": [], "tool_calls": [],
			"pending_tool_calls": [{
				"id": "call-1", "type": "function",
				"function": {"name": "get_business_report", "arguments": frappe.as_json(arguments)},
				"arguments": arguments,
			}],
			"pending_approval": {
				"call_id": "call-1", "tool": "get_business_report", "risk_level": "L3_SENSITIVE",
			},
			"tool_results": [], "citations": [], "usage": {}, "model": "model",
			"model_alias": "erp-fast-chat", "prompt_version": "erp-readonly-v7",
			"trace_id": "trace", "agent_span_id": "span", "final_content": None,
		}
		with patch.object(ai_repository, "frappe") as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value=now,
		):
			mock_frappe.PermissionError = frappe.PermissionError
			mock_frappe.db.sql.return_value = [self._agent_capability_row(token, now)]
			with self.assertRaises(frappe.PermissionError):
				request_agent_tool_approval(
					run_id="AI-RUN-1", call_id="call-1", tool="get_business_report",
					arguments=arguments, risk_level="L3_SENSITIVE", checkpoint=checkpoint,
					capability_token=token,
				)

		self.assertEqual(mock_frappe.db.sql.call_count, 1)

	def test_agent_approval_rejects_argument_substitution(self):
		now = datetime(2026, 7, 27, 12, 0, 0)
		original = '{"limit":8,"query":"莫"}'
		row = frappe._dict({
			"name": "AI-APPROVAL-1", "run_id": "AI-RUN-1", "call_id": "call-1",
			"tool_name": "search_products", "risk_level": "L3_SENSITIVE",
			"arguments_hash": hashlib.sha256(original.encode()).hexdigest(),
			"arguments_summary_json": "{}", "status": "approved",
			"requested_by": "user@example.com", "requested_at": now,
			"reviewed_by": "user@example.com", "reviewed_at": now,
			"decision_reason": None, "expires_at": now + timedelta(minutes=10),
			"executed_at": None, "version": 2,
		})
		with patch.object(ai_repository, "frappe") as mock_frappe:
			mock_frappe.PermissionError = frappe.PermissionError
			mock_frappe.db.sql.return_value = [row]
			with self.assertRaises(frappe.PermissionError):
				get_agent_tool_approval_decision(
					run_id="AI-RUN-1", call_id="call-1", tool="search_products",
					arguments={"query": "另一个商品", "limit": 8},
				)

	def test_reviewed_approval_reissues_capability_for_same_run(self):
		now = datetime(2026, 7, 27, 12, 0, 0)
		checkpoint = self._waiting_approval_checkpoint()
		arguments_hash = hashlib.sha256('{"limit":8,"query":"莫"}'.encode()).hexdigest()
		approval_row = frappe._dict({
			"name": "AI-APPROVAL-1", "run_id": "AI-RUN-1", "call_id": "call-1",
			"tool_name": "search_products", "risk_level": "L3_SENSITIVE",
			"arguments_hash": arguments_hash, "arguments_summary_json": "{}",
			"status": "approved", "requested_by": "user@example.com", "requested_at": now,
			"reviewed_by": "user@example.com", "reviewed_at": now,
			"decision_reason": None, "expires_at": now + timedelta(minutes=10),
			"executed_at": None, "version": 2, "conversation": "AI-CONV-1",
			"scenario": "general", "run_status": "waiting_approval", "model_alias": "erp-fast-chat",
			"allowed_tools_json": '["search_products"]',
			"agent_state_json": frappe.as_json(checkpoint), "company_scope": "Demo Company",
			"conversation_status": "active",
		})
		with patch.object(ai_repository, "frappe") as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value=now,
		), patch("myapp.services.ai_repository.secrets.token_urlsafe", return_value="new-token"):
			mock_frappe.PermissionError = frappe.PermissionError
			mock_frappe.as_json.side_effect = frappe.as_json
			mock_frappe.db.sql.side_effect = [
				[approval_row], None, [frappe._dict({"status": "running"})], None,
			]
			result = prepare_reviewed_agent_approval_resume(
				approval_id="AI-APPROVAL-1", user="user@example.com",
			)

		self.assertEqual(result["run_id"], "AI-RUN-1")
		self.assertEqual(result["capability_token"], "new-token")
		self.assertEqual(result["approval"]["status"], "approved")
		self.assertIn("status = 'running'", mock_frappe.db.sql.call_args_list[1].args[0])

	def test_rejected_approval_requires_a_reason(self):
		with patch.object(ai_repository, "frappe") as mock_frappe:
			mock_frappe.throw.side_effect = frappe.ValidationError("reason required")
			with self.assertRaises(frappe.ValidationError):
				review_agent_approval(
					approval_id="AI-APPROVAL-1", user="user@example.com",
					decision="rejected", expected_version=1, reason="",
				)
		mock_frappe.db.sql.assert_not_called()

	def test_agent_run_control_exposes_only_status_and_cancellation(self):
		with patch.object(ai_repository, "frappe") as mock_frappe:
			mock_frappe.db.sql.return_value = [frappe._dict({
				"status": "cancelled", "cancellation_requested": 1,
			})]
			result = get_agent_run_control(run_id="AI-RUN-1")

		self.assertEqual(result, {
			"run_id": "AI-RUN-1", "status": "cancelled", "cancelled": True,
				})

	def test_prepare_agent_run_resume_reopens_owned_failed_run_and_reissues_capability(self):
		now = datetime(2026, 7, 27, 12, 0, 0)
		checkpoint = {
			"schema_version": "agent-state-v1", "run_id": "AI-RUN-1",
			"stage": "tool_completed", "next_model_step": 2, "tool_count": 1,
			"runtime_messages": [], "agent_steps": [], "tool_calls": [],
			"pending_tool_calls": [], "tool_results": [], "citations": [],
			"usage": {}, "model": "provider-model", "model_alias": "erp-fast-chat",
			"prompt_version": "erp-readonly-v7", "trace_id": "trace", "agent_span_id": "span",
			"final_content": None,
		}
		with patch.object(ai_repository, "frappe") as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value=now,
		), patch("myapp.services.ai_repository.secrets.token_urlsafe", return_value="new-capability-token"):
			mock_frappe.PermissionError = frappe.PermissionError
			mock_frappe.as_json.side_effect = frappe.as_json
			mock_frappe.db.sql.side_effect = [
				[frappe._dict({
					"name": "AI-RUN-1", "conversation": "AI-CONV-1", "requested_by": "user@example.com",
					"scenario": "general", "status": "failed", "model_alias": "erp-fast-chat",
					"allowed_tools_json": '["search_products"]',
					"agent_state_json": frappe.as_json(checkpoint), "company_scope": "Demo Company",
					"conversation_status": "active",
				})],
				None,
				[frappe._dict({"status": "running"})],
				None,
			]
			result = prepare_agent_run_resume(run_id="AI-RUN-1", user="user@example.com")

		self.assertEqual(result["capability_token"], "new-capability-token")
		self.assertEqual(result["checkpoint_stage"], "tool_completed")
		self.assertEqual(mock_frappe.db.sql.call_count, 4)
		self.assertIn("status = 'running'", mock_frappe.db.sql.call_args_list[1].args[0])

	def test_issue_agent_capability_fails_when_run_is_not_running(self):
		with patch.object(ai_repository, "frappe") as mock_frappe:
			mock_frappe.db.sql.return_value = [frappe._dict({"status": "cancelled"})]
			mock_frappe.PermissionError = frappe.PermissionError
			with self.assertRaises(frappe.PermissionError):
				issue_agent_capability(
					run_id="AI-RUN-1", user="user@example.com", allowed_tools=["search_products"],
				)
		self.assertEqual(mock_frappe.db.sql.call_count, 1)

	def test_start_agent_tool_step_reuses_completed_call_inside_run_lock(self):
		cached_result = {"call_id": "call-1", "tool": "search_products", "status": "ok"}
		with patch.object(ai_repository, "frappe") as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value="2026-07-27 12:00:00",
		):
			mock_frappe.db.sql.side_effect = [
				[frappe._dict({"last_step_no": 2, "status": "running"})],
				[frappe._dict({
					"name": "AI-STEP-1", "status": "completed",
					"tool_name": "search_products", "arguments_json": frappe.as_json({"query": "莫"}),
					"result_json": frappe.as_json(cached_result),
				})],
			]
			claim = start_agent_tool_step(
				run_id="AI-RUN-1", user="user@example.com", call_id="call-1",
				tool="search_products", arguments={"query": "莫"},
			)

		self.assertEqual(claim["status"], "completed")
		self.assertEqual(claim["result"], cached_result)
		self.assertEqual(mock_frappe.db.sql.call_count, 2)

	def test_get_agent_tool_result_rejects_call_id_reused_with_different_arguments(self):
		row = frappe._dict({
			"tool_name": "search_products",
			"arguments_json": frappe.as_json({"query": "莫"}),
			"result_json": frappe.as_json({"call_id": "call-1", "status": "ok"}),
		})
		with patch.object(ai_repository, "frappe") as mock_frappe:
			mock_frappe.PermissionError = frappe.PermissionError
			mock_frappe.db.table_exists.return_value = True
			mock_frappe.db.sql.return_value = [row]
			with self.assertRaises(frappe.PermissionError):
				get_agent_tool_result(
					run_id="AI-RUN-1", call_id="call-1", tool="search_products",
					arguments={"query": "迪"},
				)

	def test_normalize_conversation_state_whitelists_and_bounds_working_fields(self):
		state = _normalize_conversation_state({
			"active_scenario": "order_query",
			"order": {
				"entities": ["sales_order", "invalid"], "date_preset": "last_month",
				"status": "unfinished", "sort": "amount_desc", "limit": 99,
			},
			"last_result_set": {"type": "business_documents", "id": "RESULT-1", "entity_ids": ["SO-1"],
				"scope": {"company": "Demo Company", "secret": "discarded"}},
		})

		self.assertEqual(state["schema_version"], "conversation-state-v1")
		self.assertEqual(state["order"]["entities"], ["sales_order"])
		self.assertEqual(state["order"]["limit"], 20)
		self.assertNotIn("secret", state["last_result_set"]["scope"])

	def test_get_conversation_state_is_owner_scoped_and_recovers_default_shape(self):
		conversation = frappe._dict({
			"name": "AI-CONV-1", "state_version": 3,
			"working_state_json": '{"active_scenario":"product_search","product":{"query":"Camera"}}',
			"state_updated_at": "2026-07-26 12:00:00",
		})
		with patch.object(ai_repository, "_get_owned_conversation", return_value=conversation) as mock_get:
			result = get_conversation_state(conversation_id="AI-CONV-1", user="user@example.com")

		self.assertEqual(result["version"], 3)
		self.assertEqual(result["state"]["product"]["query"], "Camera")
		mock_get.assert_called_once_with("AI-CONV-1", "user@example.com")

	def test_update_conversation_state_does_not_overwrite_stale_version(self):
		conversation = frappe._dict({"name": "AI-CONV-1", "state_version": 4})
		with patch.object(ai_repository, "_get_owned_conversation", return_value=conversation) as mock_get, patch.object(
			ai_repository, "frappe",
		) as mock_frappe:
			result = update_conversation_state(
				conversation_id="AI-CONV-1", user="user@example.com",
				state={"active_scenario": "order_query"}, expected_version=3,
			)

		self.assertFalse(result["updated"])
		self.assertEqual(result["reason"], "version_conflict")
		mock_get.assert_called_once_with("AI-CONV-1", "user@example.com", for_update=True)
		mock_frappe.db.sql.assert_not_called()

	def test_update_conversation_state_advances_version_with_owner_and_compare_guard(self):
		conversation = frappe._dict({"name": "AI-CONV-1", "state_version": 4})
		with patch.object(ai_repository, "_get_owned_conversation", return_value=conversation), patch.object(
			ai_repository, "frappe",
		) as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value="2026-07-26 12:00:00",
		):
			result = update_conversation_state(
				conversation_id="AI-CONV-1", user="user@example.com",
				state={"active_scenario": "order_query"}, expected_version=4,
			)

		self.assertTrue(result["updated"])
		self.assertEqual(result["version"], 5)
		query = mock_frappe.db.sql.call_args.args[0]
		self.assertIn("state_version = %s", query)
		self.assertEqual(mock_frappe.db.sql.call_args.args[1][-1], 4)

	def test_get_conversation_state_reports_expiry_without_mutating(self):
		conversation = frappe._dict({
			"name": "AI-CONV-1", "state_version": 3,
			"working_state_json": '{"active_scenario":"product_search","product":{"query":"Camera"}}',
			"state_updated_at": "2026-07-01 12:00:00", "context_start_sequence": 1,
		})
		with patch.object(ai_repository, "_get_owned_conversation", return_value=conversation), patch(
			"myapp.services.ai_repository.now_datetime", return_value="2026-07-26 12:00:00",
		), patch("myapp.services.ai_repository.frappe") as mock_frappe:
			result = get_conversation_state(conversation_id="AI-CONV-1", user="user@example.com")

		self.assertEqual(result["status"], "expired")
		self.assertEqual(result["reset_reason"], "expired")
		self.assertEqual(result["state"]["active_scenario"], "general")
		mock_frappe.db.sql.assert_not_called()

	def test_expired_context_is_reset_before_chat_and_starts_new_message_window(self):
		conversation = frappe._dict({
			"name": "AI-CONV-1", "state_version": 3, "message_count": 8,
			"working_state_json": '{"active_scenario":"order_query"}',
			"state_updated_at": "2026-07-01 12:00:00", "context_start_sequence": 1,
		})
		with patch.object(ai_repository, "_get_owned_conversation", return_value=conversation), patch(
			"myapp.services.ai_repository.now_datetime", return_value="2026-07-26 12:00:00",
		), patch("myapp.services.ai_repository.frappe") as mock_frappe:
			result = get_conversation_state(
				conversation_id="AI-CONV-1", user="user@example.com", expire_if_needed=True,
			)

		self.assertEqual(result["status"], "empty")
		self.assertEqual(result["reset_reason"], "expired")
		self.assertEqual(result["context_start_sequence"], 9)
		self.assertEqual(result["version"], 4)
		self.assertIn("context_start_sequence", mock_frappe.db.sql.call_args.args[0])

	def test_reset_context_keeps_messages_but_advances_context_boundary(self):
		conversation = frappe._dict({
			"name": "AI-CONV-1", "state_version": 4, "message_count": 6,
		})
		with patch.object(ai_repository, "_get_owned_conversation", return_value=conversation), patch(
			"myapp.services.ai_repository.now_datetime", return_value="2026-07-26 12:00:00",
		), patch("myapp.services.ai_repository.frappe") as mock_frappe:
			result = reset_conversation_state(conversation_id="AI-CONV-1", user="user@example.com")

		self.assertEqual(result["reset_reason"], "user_reset")
		self.assertEqual(result["context_start_sequence"], 7)
		self.assertEqual(result["version"], 5)
		self.assertIn('state_version = %s', mock_frappe.db.sql.call_args.args[0])

	def test_load_model_messages_only_reads_after_context_boundary(self):
		conversation = frappe._dict({"name": "AI-CONV-1", "context_start_sequence": 7})
		with patch.object(ai_repository, "_get_owned_conversation", return_value=conversation), patch.object(
			ai_repository, "frappe",
		) as mock_frappe:
			mock_frappe.db.sql.return_value = [frappe._dict({"role": "user", "content": "新问题"})]
			result = load_model_messages(
				conversation_id="AI-CONV-1", user="user@example.com", limit=20,
			)

		self.assertEqual(result, [{"role": "user", "content": "新问题"}])
		self.assertIn("sequence_no >= %s", mock_frappe.db.sql.call_args.args[0])
		self.assertEqual(mock_frappe.db.sql.call_args.args[1], ("AI-CONV-1", 7, 20))
	def test_refresh_conversation_citations_uses_latest_draft_state(self):
		with patch.object(
			ai_repository,
			"get_draft",
			return_value={
				"name": "AI-DRAFT-1",
				"title": "新增商品，迪莫",
				"status": "executed",
				"validation": {"ready_for_handoff": True, "errors": [], "warnings": []},
			},
		):
			result = _refresh_conversation_citations(
				[{
					"type": "ai_draft",
					"id": "AI-DRAFT-1",
					"label": "新增商品，迪莫",
					"data": {"status": "draft"},
				}],
				user="user@example.com",
			)

		self.assertEqual(result[0]["data"]["status"], "executed")

	def test_list_conversations_searches_owned_titles_and_messages_with_draft_counts(self):
		row = frappe._dict({
			"name": "AI-CONV-1", "title": "采购跟进", "status": "active",
			"company_scope": "Demo Company", "message_count": 4,
			"pending_draft_count": 2, "last_message_at": "2026-07-24 12:00:00",
			"creation": "2026-07-24 09:00:00", "modified": "2026-07-24 12:00:00",
		})
		with patch.object(ai_repository, "frappe") as mock_frappe:
			mock_frappe.db.table_exists.return_value = True
			mock_frappe.db.sql.side_effect = [
				[frappe._dict({"total": 1})],
				[frappe._dict({"total": 3})],
				[row],
			]
			result = list_conversations(
				user="user@example.com", status="active", search="  采购   跟进  ",
				start=0, limit=20,
			)

		self.assertEqual(result["items"][0]["pending_draft_count"], 2)
		self.assertEqual(result["pending_draft_total"], 3)
		count_query = mock_frappe.db.sql.call_args_list[0].args[0]
		self.assertIn("EXISTS", count_query)
		self.assertIn("LOCATE", count_query)
		self.assertEqual(
			mock_frappe.db.sql.call_args_list[0].args[1],
			("user@example.com", "active", "采购 跟进", "采购 跟进"),
		)
		rows_query = mock_frappe.db.sql.call_args_list[2].args[0]
		self.assertIn("pending_draft_count", rows_query)
		self.assertEqual(
			mock_frappe.db.sql.call_args_list[2].args[1],
			(
				"user@example.com", "user@example.com", "active",
				"采购 跟进", "采购 跟进", 20, 0,
			),
		)

	def test_rename_conversation_normalizes_title_and_preserves_owner_scope(self):
		conversation = frappe._dict({
			"name": "AI-CONV-1", "title": "旧名称", "status": "archived",
			"company_scope": "Demo Company", "message_count": 4,
			"last_message_at": "2026-07-24 12:00:00",
			"creation": "2026-07-24 09:00:00", "modified": "2026-07-24 12:00:00",
		})
		updated = frappe._dict({**conversation, "title": "采购 跟进"})
		with patch.object(ai_repository, "_get_owned_conversation", side_effect=[conversation, updated]) as mock_get, patch.object(
			ai_repository, "frappe",
		) as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value="2026-07-24 13:00:00",
		):
			result = rename_conversation(
				conversation_id="AI-CONV-1", user="user@example.com", title="  采购   跟进  ",
			)

		self.assertEqual(result["title"], "采购 跟进")
		self.assertTrue(mock_get.call_args_list[0].kwargs["for_update"])
		self.assertEqual(
			mock_frappe.db.sql.call_args.args[1],
			("采购 跟进", "2026-07-24 13:00:00", "user@example.com", "AI-CONV-1"),
		)

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
				include_advanced_diagnostics=True,
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

	def test_get_conversation_redacts_advanced_run_diagnostics(self):
		conversation = frappe._dict({
			"name": "AI-CONV-1", "title": "测试会话", "status": "active",
			"company_scope": "Demo Company", "message_count": 1,
			"last_message_at": "2026-07-24 10:00:00", "creation": "2026-07-24 09:00:00",
			"modified": "2026-07-24 10:00:00",
		})
		message = frappe._dict({
			"name": "AI-MSG-1", "sequence_no": 1, "role": "assistant", "content": "完成",
			"scenario": "general", "run_id": "AI-RUN-1", "citations_json": "[]",
			"prompt_version": "erp-readonly-v7", "creation": "2026-07-24 10:00:00",
			"run_status": "completed", "model_alias": "internal-alias", "model": "provider-model",
			"trace_id": "trace-secret", "prompt_tokens": 10, "completion_tokens": 2,
			"total_tokens": 12, "reasoning_tokens": 0, "latency_ms": 900,
			"first_token_ms": 240, "error_code": None, "error": None,
			"feedback_rating": None, "feedback_category": None, "feedback_comment": None,
		})
		with patch.object(ai_repository, "frappe") as mock_frappe, patch.object(
			ai_repository, "_get_owned_conversation", return_value=conversation,
		):
			mock_frappe.db.table_exists.return_value = True
			mock_frappe.db.sql.return_value = [message]
			result = get_conversation(
				conversation_id="AI-CONV-1", user="user@example.com", limit=40,
				include_advanced_diagnostics=False,
			)

		run = result["messages"][0]["run"]
		self.assertEqual(run["status"], "completed")
		self.assertEqual(run["latency_ms"], 900)
		self.assertNotIn("model_alias", run)
		self.assertNotIn("model", run)
		self.assertNotIn("trace_id", run)
		self.assertNotIn("usage", run)
		self.assertNotIn("first_token_ms", run)

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
