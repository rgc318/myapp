from unittest import TestCase
from unittest.mock import patch

from myapp.services.ai_agent_tool_service import (
	TOOL_POLICIES,
	_build_grounding_contract,
	_execute_business_documents,
	execute_ai_agent_tool_v1,
	request_ai_agent_tool_approval_v1,
)


class TestAiAgentToolService(TestCase):
	@patch("myapp.services.ai_service._build_order_query_context")
	def test_business_document_tool_reports_ok_when_any_group_has_results(self, build_context):
		build_context.return_value = (
			{
				"tool": "query_business_documents",
				"result_set": {"groups": [
					{"entity": "sales_order", "returned_count": 0},
					{"entity": "sales_invoice", "returned_count": 2},
				]},
			},
			[{"type": "sales_invoice", "id": "SINV-001"}],
			[],
		)

		_context, _citations, status = _execute_business_documents(
			{
				"entities": ["sales_order", "sales_invoice"],
				"date_from": None, "date_to": None, "status": "all",
				"sort": "latest", "min_amount": None, "limit": 10,
			},
			company="Demo Company",
		)

		self.assertEqual(status, "ok")

	@patch("myapp.services.ai_service._build_order_query_context")
	def test_business_document_tool_reports_not_found_when_all_groups_are_empty(self, build_context):
		build_context.return_value = (
			{
				"tool": "query_business_documents",
				"result_set": {"groups": [
					{"entity": "sales_order", "returned_count": 0},
					{"entity": "sales_invoice", "returned_count": 0},
				]},
			},
			[{"type": "business_result_set", "id": "snapshot-1"}],
			[],
		)

		_context, _citations, status = _execute_business_documents(
			{
				"entities": ["sales_order", "sales_invoice"],
				"date_from": None, "date_to": None, "status": "all",
				"sort": "latest", "min_amount": None, "limit": 10,
			},
			company="Demo Company",
		)

		self.assertEqual(status, "not_found")

	def test_grounding_contract_preserves_result_completeness_semantics(self):
		contract = _build_grounding_contract(
			context={
				"tool": "query_business_documents",
				"result_set": {"groups": [
					{"entity": "sales_order", "truncated": False, "returned_count": 2, "available_count": 2},
					{"entity": "sales_invoice", "truncated": True, "returned_count": 2, "available_count": 5},
					{"entity": "purchase_order", "truncated": None, "returned_count": 1, "available_count": None},
				]},
			},
			citations=[{"type": "sales_order", "id": "SO-001"}],
			company="Demo Company",
		)

		self.assertEqual(contract["schema_version"], "agent-grounding-v1")
		self.assertEqual(
			[result["complete"] for result in contract["result_sets"]],
			[True, False, None],
		)
		self.assertEqual(contract["citation_refs"], [{"type": "sales_order", "id": "SO-001"}])

	def test_sensitive_tool_approval_request_uses_server_policy(self):
		with patch.dict(
			TOOL_POLICIES["search_products"],
			{"risk_level": "L3_SENSITIVE", "approval_required": True}, clear=True,
		), patch(
			"myapp.services.ai_agent_tool_service.ai_repository.request_agent_tool_approval",
			return_value={
				"approval_id": "AI-APPROVAL-1", "run_id": "AI-RUN-1", "call_id": "call-1",
				"tool": "search_products", "risk_level": "L3_SENSITIVE", "status": "pending",
			},
		) as request_approval, patch("myapp.services.ai_agent_tool_service.frappe") as mock_frappe:
			result = request_ai_agent_tool_approval_v1(
				run_id="AI-RUN-1", call_id="call-1", tool="search_products",
				arguments={
					"query": "莫", "match_mode": "contains",
					"search_fields": ["item_name"], "limit": 8,
				}, risk_level="L3_SENSITIVE",
				checkpoint={"schema_version": "agent-state-v1"}, capability_token="token",
			)

		self.assertEqual(result["status"], "pending")
		request_approval.assert_called_once()
		self.assertEqual(request_approval.call_args.kwargs["risk_level"], "L3_SENSITIVE")
		mock_frappe.db.commit.assert_called_once()

	def test_rejected_sensitive_tool_returns_denied_without_business_execution(self):
		capability = {
			"run_id": "AI-RUN-1", "user": "user@example.com",
			"company": "Demo Company", "allowed_tools": ["search_products"],
		}
		with patch.dict(
			TOOL_POLICIES["search_products"],
			{"risk_level": "L3_SENSITIVE", "approval_required": True}, clear=True,
		), patch(
			"myapp.services.ai_agent_tool_service.ai_repository.validate_agent_capability",
			return_value=capability,
		), patch(
			"myapp.services.ai_agent_tool_service.ai_repository.get_agent_tool_result",
			return_value=None,
		), patch(
			"myapp.services.ai_agent_tool_service.ai_repository.get_agent_tool_approval_decision",
			return_value={"approval_id": "AI-APPROVAL-1", "status": "rejected"},
		), patch(
			"myapp.services.ai_agent_tool_service.ai_repository.start_agent_tool_step",
			return_value={"status": "claimed", "step_id": "AI-STEP-1", "result": None},
		), patch(
			"myapp.services.ai_agent_tool_service.ai_repository.complete_agent_tool_step",
		) as complete_step, patch(
			"myapp.services.ai_agent_tool_service._execute_search_products",
		) as execute_search, patch(
			"myapp.services.ai_agent_tool_service._switch_user",
		), patch(
			"myapp.services.ai_agent_tool_service._commit_agent_tool_result",
		):
			result = execute_ai_agent_tool_v1(
				run_id="AI-RUN-1", call_id="call-1", tool="search_products",
				arguments={
					"query": "莫", "match_mode": "contains",
					"search_fields": ["item_name"], "limit": 8,
				}, capability_token="token",
			)

		self.assertEqual(result["status"], "denied")
		self.assertEqual(result["error"]["code"], "AI_AGENT_TOOL_REJECTED")
		execute_search.assert_not_called()
		complete_step.assert_called_once()
	@patch("myapp.services.ai_agent_tool_service._commit_agent_tool_result")
	@patch("myapp.services.ai_agent_tool_service._switch_user")
	@patch("myapp.services.ai_agent_tool_service.ai_repository.complete_agent_tool_step")
	@patch(
		"myapp.services.ai_agent_tool_service.ai_repository.start_agent_tool_step",
		return_value={"status": "claimed", "step_id": "AI-STEP-1", "result": None},
	)
	@patch("myapp.services.ai_agent_tool_service.ai_repository.get_agent_tool_result", return_value=None)
	@patch("myapp.services.ai_agent_tool_service.ai_repository.validate_agent_capability")
	@patch("myapp.services.ai_agent_tool_service._execute_search_products")
	def test_executes_capability_scoped_tool_and_persists_result(
		self, execute_search, validate, _cached, start_step, complete_step,
		set_user, _commit,
	):
		validate.return_value = {
			"run_id": "AI-RUN-1", "user": "user@example.com",
			"company": "Demo Company", "allowed_tools": ["search_products"],
		}
		execute_search.return_value = (
			{"tool": "search_products", "products": [{"item_code": "SKU-MO"}]},
			[{"type": "product", "id": "SKU-MO"}],
			"resolved",
		)

		result = execute_ai_agent_tool_v1(
			run_id="AI-RUN-1", call_id="call-1", tool="search_products",
			arguments={
				"query": "莫", "match_mode": "contains",
				"search_fields": ["item_name"], "limit": 8,
			}, capability_token="token",
		)

		self.assertEqual(result["status"], "resolved")
		self.assertEqual(result["citations"][0]["id"], "SKU-MO")
		self.assertEqual(result["grounding"]["schema_version"], "agent-grounding-v1")
		self.assertEqual(result["grounding"]["company"], "Demo Company")
		self.assertEqual(result["grounding"]["citation_refs"], [{
			"type": "product", "id": "SKU-MO",
		}])
		validate.assert_called_once_with(
			run_id="AI-RUN-1", capability_token="token", tool="search_products",
		)
		start_step.assert_called_once()
		complete_step.assert_called_once()
		set_user.assert_any_call("user@example.com")

	@patch("myapp.services.ai_agent_tool_service.ai_repository.validate_agent_capability")
	@patch("myapp.services.ai_agent_tool_service.ai_repository.get_agent_tool_result")
	def test_replayed_call_returns_persisted_result_without_reexecution(self, cached, validate):
		validate.return_value = {
			"run_id": "AI-RUN-1", "user": "user@example.com",
			"company": "Demo Company", "allowed_tools": ["search_products"],
		}
		cached.return_value = {
			"call_id": "call-1", "tool": "search_products", "status": "resolved",
			"data": {"result_count": 1}, "model_context": {}, "citations": [],
			"error": None, "retryable": False,
		}

		result = execute_ai_agent_tool_v1(
			run_id="AI-RUN-1", call_id="call-1", tool="search_products",
			arguments={
				"query": "莫", "match_mode": "contains",
				"search_fields": ["item_name"], "limit": 8,
			}, capability_token="token",
		)

		self.assertEqual(result, cached.return_value)

	@patch("myapp.services.ai_agent_tool_service._commit_agent_tool_result")
	@patch("myapp.services.ai_agent_tool_service._execute_search_products")
	@patch("myapp.services.ai_agent_tool_service.ai_repository.get_agent_tool_result", return_value=None)
	@patch("myapp.services.ai_agent_tool_service.ai_repository.validate_agent_capability")
	@patch("myapp.services.ai_agent_tool_service.ai_repository.start_agent_tool_step")
	def test_concurrent_replay_reuses_result_found_inside_claim_lock(
		self, start_step, validate, _cached, execute_search, commit,
	):
		validate.return_value = {
			"run_id": "AI-RUN-1", "user": "user@example.com",
			"company": "Demo Company", "allowed_tools": ["search_products"],
		}
		persisted = {
			"call_id": "call-1", "tool": "search_products", "status": "resolved",
			"data": {"result_count": 1}, "model_context": {}, "citations": [],
			"error": None, "retryable": False,
		}
		start_step.return_value = {
			"status": "completed", "step_id": "AI-STEP-1", "result": persisted,
		}

		result = execute_ai_agent_tool_v1(
			run_id="AI-RUN-1", call_id="call-1", tool="search_products",
			arguments={
				"query": "莫", "match_mode": "contains",
				"search_fields": ["item_name"], "limit": 8,
			}, capability_token="token",
		)

		self.assertEqual(result, persisted)
		execute_search.assert_not_called()
		commit.assert_called_once_with()

	def test_rejects_invalid_tool_argument_types_at_frappe_boundary(self):
		with patch(
			"myapp.services.ai_agent_tool_service.ai_repository.validate_agent_capability",
			return_value={"run_id": "AI-RUN-1", "user": "user@example.com", "company": "Demo Company"},
		), patch("myapp.services.ai_agent_tool_service.frappe.throw", side_effect=ValueError("invalid")):
			with self.assertRaises(ValueError):
				execute_ai_agent_tool_v1(
					run_id="AI-RUN-1", call_id="call-1", tool="search_products",
					arguments={
						"query": ["SKU001"], "match_mode": "auto",
						"search_fields": [], "limit": 8,
					}, capability_token="token",
				)
