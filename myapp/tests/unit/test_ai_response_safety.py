import json
from contextlib import ExitStack
from unittest import TestCase
from unittest.mock import patch

from myapp.services import ai_service as service
from myapp.services.ai_response_safety import (
	check_readonly_chat_output,
	require_readonly_chat_intent,
	require_reliable_intent,
)
from myapp.utils.ai_errors import AiServiceError


class TestAiResponseSafety(TestCase):
	def test_uncertain_intents_fail_closed_without_lexical_assumptions(self):
		for confidence in (None, 0.2, True, "0.9", float("nan"), float("inf"), -1, 2):
			with self.subTest(confidence=confidence), self.assertRaises(AiServiceError):
				require_reliable_intent({"intent": "general", "confidence": confidence})
		for intent in ({}, None, {"intent": "unknown", "confidence": 0.9}, {"intent": [], "confidence": 0.9}):
			with self.subTest(intent=intent), self.assertRaises(AiServiceError):
				require_reliable_intent(intent)

	def test_readonly_queries_remain_available(self):
		for scenario in ("general", "product_search", "order_query", "report_summary"):
			require_readonly_chat_intent({"intent": scenario, "confidence": 0.9})

	def test_all_write_scenarios_and_disguised_actions_require_workflow(self):
		for scenario in (*service.AI_DRAFT_SCENARIOS, "product_lifecycle_plan"):
			with self.subTest(scenario=scenario), self.assertRaises(AiServiceError):
				require_readonly_chat_intent({"intent": scenario, "confidence": 0.9})
		for operation in ("update", "delete", "cancel", "pay", "refund", "inventory_adjust"):
			with self.subTest(operation=operation), self.assertRaises(AiServiceError):
				require_readonly_chat_intent({"intent": "general", "confidence": 0.9,
					"action_contract": {"operations": [operation]}})

	def test_public_chat_and_stream_reject_writes_before_any_run_or_answer(self):
		for endpoint in (service.chat_ai_v1, service.stream_ai_message_v1):
			for scenario in ("auto", "general", "product_search", "order_query", "report_summary"):
				for agent in ("0", "1"):
					with self.subTest(endpoint=endpoint.__name__, scenario=scenario, agent=agent), ExitStack() as stack:
						stack.enter_context(patch.dict(service.os.environ, {"MYAPP_AI_AGENT_RUNTIME_ENABLED": agent}))
						stack.enter_context(patch.object(service, "_current_user", return_value="u"))
						stack.enter_context(patch.object(service, "resolve_ai_selected_model_alias", return_value="model"))
						stack.enter_context(patch.object(service, "resolve_ai_attachments", return_value=([], [])))
						stack.enter_context(patch.object(service, "_resolve_company_scope", return_value="c"))
						stack.enter_context(patch.object(service, "_take_ai_scenario_resolution", return_value=None))
						stack.enter_context(patch.object(service, "_call_ai_intent_orchestrator", return_value={
							"intent": "product_setup_draft", "confidence": 0.95}))
						repository = stack.enter_context(patch.object(service, "ai_repository"))
						answer = stack.enter_context(patch.object(service, "_call_ai_orchestrator"))
						if endpoint is service.stream_ai_message_v1:
							response = endpoint(content="那把这张图改成百事可乐的封面", scenario=scenario, company="c")
							self.assertIn('"code":"AI_CHAT_ACTION_REQUIRES_WORKFLOW"', response.get_data(as_text=True))
						else:
							with self.assertRaises(AiServiceError):
								endpoint(content="那把这张图改成百事可乐的封面", scenario=scenario, company="c")
						repository.create_run.assert_not_called()
						repository.issue_agent_capability.assert_not_called()
						answer.assert_not_called()

	def test_image_intent_timeout_is_not_empty_general_fallback(self):
		with patch.object(service, "_get_ai_orchestrator_settings", return_value=("http://ai", "test")), patch.object(
			service.urllib.request, "urlopen", side_effect=TimeoutError("timed out"),
		), patch.object(service, "frappe") as mock_frappe:
			mock_frappe.local.lang = "zh-CN"
			with self.assertRaises(AiServiceError) as caught:
				service._call_ai_intent_orchestrator(content="那把这张图改成百事可乐的封面", user="u", company="c",
					attachments=[{"attachment_id": "ATT", "data_base64": "test"}])
		self.assertEqual(caught.exception.code, "AI_INTENT_PARSE_FAILED")
		self.assertIsInstance(caught.exception.__cause__, TimeoutError)

	def test_success_claims_are_not_execution_receipts(self):
		for content in (
			"已按‘百事可乐’主题改成商品封面风格。", "已替换商品图片。",
			"已删除两个商品。", "我已经提交销售订单。", "已取消采购订单。",
			"已扣减库存。", "已付款。", "已退款。", "I have updated the image.",
		):
			with self.subTest(content=content), self.assertRaises(AiServiceError) as caught:
				check_readonly_chat_output(content)
			self.assertEqual(caught.exception.code, "AI_UNVERIFIED_ACTION_CLAIM")

	def test_image_timeout_stops_public_entry_without_creating_run(self):
		for endpoint in (service.chat_ai_v1, service.stream_ai_message_v1, service.resolve_ai_scenario_v1):
			with self.subTest(endpoint=endpoint.__name__), ExitStack() as stack:
				stack.enter_context(patch.object(service, "_current_user", return_value="u"))
				stack.enter_context(patch.object(service, "resolve_ai_selected_model_alias", return_value="model"))
				stack.enter_context(patch.object(service, "resolve_ai_attachments", return_value=(
					[{"attachment_id": "ATT"}], [{"attachment_id": "ATT", "data_base64": "test"}],
				)))
				stack.enter_context(patch.object(service, "_resolve_company_scope", return_value="c"))
				stack.enter_context(patch.object(service, "_take_ai_scenario_resolution", return_value=None))
				stack.enter_context(patch.object(service, "_get_ai_orchestrator_settings", return_value=("http://ai", "test")))
				stack.enter_context(patch.object(service.urllib.request, "urlopen", side_effect=TimeoutError("timed out")))
				frappe_mock = stack.enter_context(patch.object(service, "frappe"))
				frappe_mock.local.lang = "zh-CN"
				repository = stack.enter_context(patch.object(service, "ai_repository"))
				answer = stack.enter_context(patch.object(service, "_call_ai_orchestrator"))
				if endpoint is service.stream_ai_message_v1:
					response = endpoint(content="那把这张图改成百事可乐的封面", company="c", attachment_ids=["ATT"])
					self.assertIn('"code":"AI_INTENT_PARSE_FAILED"', response.get_data(as_text=True))
					self.assertNotIn("run_started", response.get_data(as_text=True))
				else:
					with self.assertRaises(AiServiceError) as caught:
						endpoint(content="那把这张图改成百事可乐的封面", company="c", attachment_ids=["ATT"])
					self.assertEqual(caught.exception.code, "AI_INTENT_PARSE_FAILED")
				repository.create_run.assert_not_called()
				answer.assert_not_called()

	def test_queries_history_instructions_and_negation_are_not_success_claims(self):
		for content in ("找到 3 个商品。", "订单状态为已取消。", "该订单已付款。",
			"请确认后再修改图片。", "未执行任何修改。", "没有替换图片。", "已生成待确认草稿，尚未写入商品。",
			"没有替换成功。", "删除失败，未成功。", "点击删除，成功后刷新。", "已查询到三个已取消订单。"):
			with self.subTest(content=content):
				check_readonly_chat_output(content)

	def _stream(self, chunks, final, *, resume=False):
		prepared = {"conversation_id": "conv", "run_id": "run", "started": 1,
			"tool_calls": [], "citations": [], "payload": {}}
		events = [{"type": "message_delta", "delta": chunk} for chunk in chunks]
		events.append({"type": "completed", "message": {"content": final}})
		with patch.object(service, "_stream_ai_orchestrator", return_value=iter(events)), patch.object(
			service, "_validate_runtime_result", return_value={},
		), patch.object(service, "_complete_chat_run", return_value={}) as complete, patch.object(
			service, "_fail_chat_run",
		) as fail, patch.object(service, "_public_ai_result_details", return_value={}):
			response = service._stream_prepared_ai_run(prepared, resume=resume)
			body = b"".join(response.iter_encoded()).decode()
			return [json.loads(row[6:]) for row in body.splitlines() if row.startswith("data: ")], complete, fail

	def test_stream_does_not_leak_claim_at_any_chunk_boundary_including_resume(self):
		claim = "已按百事可乐主题改成商品封面风格。"
		for split in range(1, len(claim)):
			for resume in (False, True):
				with self.subTest(split=split, resume=resume):
					events, complete, fail = self._stream([claim[:split], claim[split:]], claim, resume=resume)
					self.assertFalse(any(event["type"] in {"message_delta", "completed"} for event in events))
					self.assertEqual(events[-1]["code"], "AI_UNVERIFIED_ACTION_CLAIM")
					complete.assert_not_called()
					fail.assert_called_once()

	def test_stream_rejects_different_final_content(self):
		events, complete, _fail = self._stream(["找到一个商品。"], "已替换图片。")
		self.assertEqual(events[-1]["code"], "AI_STREAM_CONTENT_MISMATCH")
		self.assertFalse(any(event["type"] == "message_delta" for event in events))
		complete.assert_not_called()

	def test_stream_enforces_response_memory_limit_before_publishing(self):
		with patch.object(service, "MAX_CHAT_RESPONSE_CHARS", 4):
			events, complete, _fail = self._stream(["123", "456"], "123456")
		self.assertEqual(events[-1]["code"], "AI_OUTPUT_TOO_LARGE")
		self.assertFalse(any(event["type"] == "message_delta" for event in events))
		complete.assert_not_called()

	def test_safe_stream_preserves_output_and_supports_final_only_providers(self):
		for chunks in (["找到", "商品。"], []):
			events, complete, fail = self._stream(chunks, "找到商品。")
			self.assertEqual("".join(event["delta"] for event in events if event["type"] == "message_delta"), "找到商品。")
			self.assertEqual(events[-1]["message"]["content"], "找到商品。")
			complete.assert_called_once()
			fail.assert_not_called()

	def test_sync_chat_rejects_model_claim_before_persistence(self):
		with patch.object(service, "_prepare_chat_run", return_value={"payload": {}}), patch.object(
			service, "_call_ai_orchestrator", return_value={"message": {"content": "已替换图片。"}, "execution_receipt": "fake"},
		), patch.object(service, "_complete_chat_run") as complete, patch.object(service, "_fail_chat_run") as fail:
			with self.assertRaises(AiServiceError):
				service.chat_ai_v1(content="替换图片")
			complete.assert_not_called()
			fail.assert_called_once()
