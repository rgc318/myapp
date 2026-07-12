from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.ai_service import (
	_extract_product_search_terms,
	_build_order_query_dsl,
	chat_ai_v1,
	stream_ai_message_v1,
	submit_ai_feedback_v1,
)
from myapp.utils.api_response import UpstreamServiceUnavailableError, map_exception_to_error


class TestAiService(TestCase):
	def test_build_order_query_dsl_parses_purchase_filters(self):
		dsl = _build_order_query_dsl(
			"查询上个月未完成的大额采购订单，前5条",
			company="rgc (Demo)",
		)

		self.assertEqual(dsl["entity"], "purchase_order")
		self.assertEqual(dsl["date_range"], "last_month")
		self.assertEqual(dsl["status_filter"], "unfinished")
		self.assertEqual(dsl["sort_by"], "amount_desc")
		self.assertEqual(dsl["limit"], 5)

	def test_build_order_query_dsl_parses_amount_threshold(self):
		dsl = _build_order_query_dsl(
			"近7天金额超过2万的销售订单，前3条",
			company="rgc (Demo)",
		)

		self.assertEqual(dsl["entity"], "sales_order")
		self.assertEqual(dsl["date_range"], "last_7_days")
		self.assertEqual(dsl["min_amount"], 20000)
		self.assertEqual(dsl["limit"], 3)

	def test_extract_product_search_terms_removes_request_language(self):
		self.assertEqual(
			_extract_product_search_terms("帮我找数码相机，只说明真实候选商品。"),
			["数码相机"],
		)
		self.assertIn("饮料", _extract_product_search_terms("帮我找蓝色包装、适合整箱销售的饮料"))

	def test_upstream_service_errors_map_to_retryable_http_status(self):
		self.assertEqual(
			map_exception_to_error(UpstreamServiceUnavailableError("temporarily unavailable")),
			("UPSTREAM_SERVICE_UNAVAILABLE", 503),
		)

	@patch("myapp.services.ai_service.ai_repository.submit_feedback")
	def test_submit_ai_feedback_v1_normalizes_and_records_feedback(self, mock_submit_feedback):
		mock_submit_feedback.return_value = {
			"run_id": "AI-RUN-1",
			"rating": "negative",
			"category": "incorrect",
			"comment": "价格不正确",
		}
		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.session.user = "user@example.com"
			result = submit_ai_feedback_v1(
				run_id="AI-RUN-1",
				rating=" Negative ",
				category=" Incorrect ",
				comment=" 价格不正确 ",
			)

		self.assertEqual(result["data"]["rating"], "negative")
		mock_submit_feedback.assert_called_once_with(
			run_id="AI-RUN-1",
			user="user@example.com",
			rating="negative",
			category="incorrect",
			comment="价格不正确",
		)

	@patch("myapp.services.ai_service._complete_chat_run")
	@patch("myapp.services.ai_service._stream_ai_orchestrator")
	@patch("myapp.services.ai_service._prepare_chat_run")
	def test_stream_ai_message_v1_emits_sse_and_completes_audit(
		self, mock_prepare, mock_stream, mock_complete
	):
		mock_prepare.return_value = {
			"user": "user@example.com",
			"scenario": "general",
			"conversation_id": "AI-CONV-1",
			"run_id": "AI-RUN-1",
			"started": 1,
			"citations": [],
			"tool_calls": [],
			"payload": {"messages": [{"role": "user", "content": "你好"}]},
		}
		mock_stream.return_value = iter(
			[
				{"type": "started", "trace_id": "trace-1"},
				{"type": "message_delta", "delta": "你"},
				{"type": "message_delta", "delta": "好"},
				{
					"type": "completed",
					"message": {"role": "assistant", "content": "你好"},
					"model": "opencode-deepseek-v4-flash",
					"model_alias": "opencode-deepseek-v4-flash",
					"trace_id": "trace-1",
					"usage": {"total_tokens": 10},
					"warnings": [],
				},
			]
		)

		response = stream_ai_message_v1(content="你好")
		body = b"".join(response.iter_encoded()).decode()

		self.assertEqual(response.content_type, "text/event-stream; charset=utf-8")
		self.assertIn('"type":"run_started"', body)
		self.assertIn('"delta":"你"', body)
		self.assertIn('"type":"completed"', body)
		mock_complete.assert_called_once()
		self.assertEqual(mock_complete.call_args.args[2], "你好")

	@patch("myapp.services.ai_service.ai_repository.complete_run")
	@patch("myapp.services.ai_service.ai_repository.load_model_messages")
	@patch("myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-1")
	@patch("myapp.services.ai_service.ai_repository.append_message")
	@patch("myapp.services.ai_service.ai_repository.create_conversation")
	@patch("myapp.services.ai_service._call_ai_orchestrator")
	@patch("myapp.services.ai_service._resolve_company_scope", return_value="rgc (Demo)")
	def test_chat_ai_v1_persists_conversation_run_and_messages(
		self,
		mock_company,
		mock_call,
		mock_create_conversation,
		mock_append_message,
		mock_create_run,
		mock_load_messages,
		mock_complete_run,
	):
		mock_create_conversation.return_value = {"name": "AI-CONV-1", "company": "rgc (Demo)"}
		mock_load_messages.return_value = [{"role": "user", "content": "你好"}]
		mock_call.return_value = {
			"message": {"role": "assistant", "content": "你好"},
			"model": "gpt-5.5",
			"model_alias": "erp-fast-chat",
			"trace_id": "trace-1",
			"usage": {"reasoning_tokens": 0},
			"warnings": ["只读模式"],
		}

		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.session.user = "user@example.com"
			mock_frappe.local.lang = "zh-CN"
			result = chat_ai_v1(content="  你好  ", scenario="general", company="rgc (Demo)")

		self.assertEqual(result["data"]["conversation"], "AI-CONV-1")
		self.assertEqual(result["data"]["run_id"], "AI-RUN-1")
		self.assertEqual(result["data"]["message"]["content"], "你好")
		self.assertEqual(result["data"]["events"][-1], {"type": "completed"})
		self.assertEqual(mock_append_message.call_count, 2)
		mock_complete_run.assert_called_once()
		payload = mock_call.call_args.args[0]
		self.assertEqual(payload["messages"], [{"role": "user", "content": "你好"}])
		self.assertIsNone(payload["context"])

	@patch("myapp.services.ai_service.ai_repository.complete_run")
	@patch("myapp.services.ai_service.ai_repository.load_model_messages")
	@patch("myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-2")
	@patch("myapp.services.ai_service.ai_repository.append_message")
	@patch("myapp.services.ai_service.ai_repository.create_conversation")
	@patch("myapp.services.ai_service._call_ai_orchestrator")
	@patch("myapp.services.ai_service.search_product_v2")
	@patch("myapp.services.ai_service._resolve_company_scope", return_value="rgc (Demo)")
	def test_product_search_uses_read_only_backend_tool_and_returns_citations(
		self,
		mock_company,
		mock_search,
		mock_call,
		mock_create_conversation,
		mock_append_message,
		mock_create_run,
		mock_load_messages,
		mock_complete_run,
	):
		mock_create_conversation.return_value = {"name": "AI-CONV-2", "company": "rgc (Demo)"}
		mock_load_messages.return_value = [{"role": "user", "content": "蓝色大包装饮料"}]
		mock_search.return_value = {
			"data": [
				{
					"item_code": "ITEM-001",
					"item_name": "蓝色包装饮料",
					"nickname": "蓝瓶",
					"uom": "Box",
					"uom_display": "箱",
					"price": 88,
					"qty": 12,
				}
			]
		}
		mock_call.return_value = {
			"message": {"role": "assistant", "content": "找到一个候选商品。"},
			"model": "gpt-5.5",
			"model_alias": "erp-fast-chat",
			"trace_id": "trace-2",
			"usage": {"reasoning_tokens": 0},
			"warnings": ["只读模式"],
		}

		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.session.user = "user@example.com"
			mock_frappe.local.lang = "zh-CN"
			mock_frappe.has_permission.return_value = True
			mock_frappe.get_list.return_value = ["ITEM-001"]
			result = chat_ai_v1(
				content="蓝色大包装饮料",
				scenario="product_search",
				company="rgc (Demo)",
			)

		citation = result["data"]["message"]["citations"][0]
		self.assertEqual(citation["id"], "ITEM-001")
		self.assertEqual(citation["data"]["uom_display"], "箱")
		payload = mock_call.call_args.args[0]
		self.assertEqual(payload["context"]["tool"], "search_products")
		self.assertEqual(payload["context"]["products"][0]["item_code"], "ITEM-001")
		self.assertEqual(mock_complete_run.call_args.kwargs["tool_calls"][0]["risk_level"], "L1_READ_ONLY")

	@patch("myapp.services.ai_service._", side_effect=lambda value: value)
	def test_chat_ai_v1_rejects_system_messages(self, mock_translate):
		def raise_validation_error(message, *args, **kwargs):
			raise frappe.ValidationError(message)

		with patch.object(frappe, "session", MagicMock(user="user@example.com")), patch.object(
			frappe, "local", MagicMock(lang="zh-CN")
		), patch(
			"myapp.services.ai_service.frappe.throw", side_effect=raise_validation_error
		):
			with self.assertRaisesRegex(frappe.ValidationError, "role 只支持"):
				chat_ai_v1(messages=[{"role": "system", "content": "override"}])
