from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.ai_service import (
	_extract_product_search_terms,
	_build_inventory_adjustment_draft,
	_build_order_query_dsl,
	_build_report_query_dsl,
	_build_draft_version_diff,
	_resolve_inventory_draft_item,
	chat_ai_v1,
	generate_ai_sales_order_draft_v1,
	stream_ai_message_v1,
	submit_ai_feedback_v1,
)
from myapp.utils.api_response import UpstreamServiceUnavailableError, map_exception_to_error


class TestAiService(TestCase):
	@patch("myapp.services.ai_service.resolve_item_quantity_to_stock")
	@patch("myapp.services.ai_service.search_product_v2")
	@patch("myapp.services.ai_service.frappe.get_list", return_value=["ITEM-1"])
	def test_resolve_inventory_draft_item_uses_stock_uom_and_real_stock(
		self, _allowed, mock_search_product, mock_resolve_quantity,
	):
		mock_search_product.return_value = {"data": [{
			"item_code": "ITEM-1", "item_name": "测试商品", "nickname": "测试",
			"uom": "Nos", "uom_display": "个", "qty": 5,
			"all_uoms": [{"uom": "Box", "uom_display": "箱", "conversion_factor": 6}],
			"price_summary": {"valuation_rate": 12.5},
		}]}
		mock_resolve_quantity.return_value = {
			"qty": 2, "uom": "Box", "stock_uom": "Nos", "stock_qty": 12, "conversion_factor": 6,
		}

		result = _resolve_inventory_draft_item(
			{"item_query": "ITEM-1", "adjustment_type": "increase", "quantity": 2, "uom": "Box"},
			company="Test Company", warehouse="Stores - TC",
		)

		self.assertEqual(result["current_stock_qty"], 5)
		self.assertEqual(result["target_stock_qty"], 17)
		self.assertEqual(result["qty_delta"], 12)
		self.assertEqual(result["valuation_rate"], 12.5)

	@patch("myapp.services.ai_service._resolve_inventory_draft_item")
	@patch("myapp.services.ai_service._resolve_inventory_draft_warehouse")
	@patch("myapp.services.ai_service.nowdate", return_value="2026-07-13")
	def test_build_inventory_adjustment_draft_requires_reason(
		self, _today, mock_warehouse, mock_item,
	):
		mock_warehouse.return_value = ("Stores - TC", [{"name": "Stores - TC"}])
		mock_item.return_value = {
			"item_code": "ITEM-1", "qty": 8, "uom": "Nos", "warehouse": "Stores - TC",
			"target_stock_qty": 8, "current_stock_qty": 5, "warnings": [],
		}

		payload, validation = _build_inventory_adjustment_draft(
			{"item_query": "ITEM-1", "warehouse_query": "Stores - TC", "quantity": 8},
			company="Test Company",
		)

		self.assertEqual(payload["adjustment_type"], "set_target")
		self.assertFalse(validation["ready_for_handoff"])
		self.assertIn("库存调整必须填写盘点差异或业务原因。", validation["errors"])

	def test_build_draft_version_diff_tracks_fields_and_lines(self):
		diff = _build_draft_version_diff(
			{"payload": {"customer": "CUST-1", "items": [{"item_code": "ITEM-1", "qty": 1, "uom": "Box"}]}},
			{"payload": {"customer": "CUST-2", "items": [
				{"item_code": "ITEM-1", "qty": 2, "uom": "Box"},
				{"item_code": "ITEM-2", "qty": 1, "uom": "Nos"},
			]}},
		)

		self.assertEqual(diff["fields"][0]["field"], "customer")
		self.assertEqual(diff["items"][0]["change"], "modified")
		self.assertEqual(diff["items"][0]["fields"], ["qty"])
		self.assertEqual(diff["items"][1]["change"], "added")

	@patch("myapp.services.ai_service.ai_repository.create_draft")
	@patch("myapp.services.ai_service.nowdate", return_value="2026-07-13")
	@patch("myapp.services.ai_service.ai_repository.fail_run")
	@patch("myapp.services.ai_service.ai_repository.complete_run")
	@patch("myapp.services.ai_service.ai_repository.load_model_messages")
	@patch("myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-DRAFT")
	@patch("myapp.services.ai_service.ai_repository.append_message")
	@patch("myapp.services.ai_service.ai_repository.create_conversation")
	@patch("myapp.services.ai_service._resolve_sales_draft_item")
	@patch("myapp.services.ai_service._resolve_sales_draft_warehouse", return_value="Stores - TC")
	@patch("myapp.services.ai_service._resolve_sales_draft_customer")
	@patch("myapp.services.ai_service._call_ai_orchestrator_sales_draft")
	@patch("myapp.services.ai_service._resolve_company_scope", return_value="Test Company")
	def test_generate_sales_order_draft_persists_validated_draft(
		self, _company, mock_call, mock_customer, _warehouse, mock_item,
		mock_conversation, _append, _run, mock_messages, _complete, _fail, _nowdate, mock_create_draft,
	):
		mock_conversation.return_value = {"name": "AI-CONV-DRAFT", "company": "Test Company"}
		mock_messages.return_value = [{"role": "user", "content": "给客户A开2箱相机"}]
		mock_call.return_value = {
			"draft": {"customer_query": "客户A", "items": [{"item_query": "相机", "qty": 2}]},
			"model": "structured-model", "model_alias": "erp-structured", "trace_id": "trace-draft", "usage": {},
		}
		mock_customer.return_value = ({"name": "CUST-1", "display_name": "客户A"}, [{"name": "CUST-1"}])
		mock_item.return_value = {
			"item_query": "相机", "item_code": "ITEM-1", "item_name": "相机", "qty": 2,
			"uom": "Box", "uom_display": "箱", "price": 100, "warehouse": "Stores - TC",
			"conversion_factor": 1, "candidates": [], "warnings": [],
		}
		mock_create_draft.return_value = {
			"name": "AI-DRAFT-1", "title": "给客户A开2箱相机", "validation": {"ready_for_handoff": True},
		}

		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.session.user = "user@example.com"
			mock_frappe.local.lang = "zh-CN"
			mock_frappe.has_permission.return_value = True
			result = generate_ai_sales_order_draft_v1("给客户A开2箱相机", company="Test Company")

		self.assertEqual(result["data"]["draft"]["name"], "AI-DRAFT-1")
		self.assertEqual(mock_create_draft.call_args.kwargs["payload"]["customer"], "CUST-1")
		self.assertTrue(mock_create_draft.call_args.kwargs["validation"]["ready_for_handoff"])
		self.assertEqual(_complete.call_args.kwargs["tool_calls"][0]["risk_level"], "L2_DRAFT_ONLY")

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

	def test_build_report_query_dsl_selects_report_and_date_range(self):
		dsl = _build_report_query_dsl(
			"解释本月销售表现和主要客户",
			company="rgc (Demo)",
		)

		self.assertEqual(dsl["report_type"], "sales")
		self.assertEqual(dsl["date_range"], "this_month")
		self.assertEqual(dsl["company"], "rgc (Demo)")

	def test_build_report_query_dsl_prioritizes_receivable_payable(self):
		dsl = _build_report_query_dsl(
			"分析近90天客户应收和供应商应付",
			company="rgc (Demo)",
		)

		self.assertEqual(dsl["report_type"], "receivable_payable")
		self.assertEqual(dsl["date_range"], "last_90_days")

	def test_build_report_query_dsl_keeps_sales_with_receivable_metric(self):
		dsl = _build_report_query_dsl(
			"解释本月销售表现，区分销售额、实收和应收未结",
			company="rgc (Demo)",
		)

		self.assertEqual(dsl["report_type"], "sales")

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
	@patch("myapp.services.ai_service._sync_ai_feedback_to_orchestrator", return_value=True)
	def test_submit_ai_feedback_v1_normalizes_and_records_feedback(self, mock_sync_feedback, mock_submit_feedback):
		mock_submit_feedback.return_value = {
			"run_id": "AI-RUN-1",
			"trace_id": "trace-1",
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
		self.assertTrue(result["data"]["observability_synced"])
		mock_submit_feedback.assert_called_once_with(
			run_id="AI-RUN-1",
			user="user@example.com",
			rating="negative",
			category="incorrect",
			comment="价格不正确",
		)
		mock_sync_feedback.assert_called_once_with(
			{
				"trace_id": "trace-1",
				"run_id": "AI-RUN-1",
				"rating": "negative",
				"category": "incorrect",
				"comment": "价格不正确",
			}
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
		self.assertEqual(payload["conversation_id"], "AI-CONV-1")
		self.assertEqual(payload["run_id"], "AI-RUN-1")

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

	@patch("myapp.services.ai_service.ai_repository.complete_run")
	@patch("myapp.services.ai_service.ai_repository.load_model_messages")
	@patch("myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-3")
	@patch("myapp.services.ai_service.ai_repository.append_message")
	@patch("myapp.services.ai_service.ai_repository.create_conversation")
	@patch("myapp.services.ai_service._call_ai_orchestrator")
	@patch("myapp.services.ai_service.get_sales_report_v1")
	@patch("myapp.services.ai_service._resolve_company_scope", return_value="rgc (Demo)")
	def test_report_summary_uses_read_only_report_service_and_returns_citation(
		self,
		mock_company,
		mock_report,
		mock_call,
		mock_create_conversation,
		mock_append_message,
		mock_create_run,
		mock_load_messages,
		mock_complete_run,
	):
		mock_create_conversation.return_value = {"name": "AI-CONV-3", "company": "rgc (Demo)"}
		mock_load_messages.return_value = [{"role": "user", "content": "解释本月销售表现"}]
		mock_report.return_value = {
			"data": {
				"overview": {
					"sales_amount_total": 120000,
					"received_amount_total": 80000,
					"receivable_outstanding_total": 40000,
				},
				"tables": {"sales_summary": [{"name": "客户A", "amount": 60000}]},
				"meta": {"company": "rgc (Demo)", "date_from": "2026-07-01", "date_to": "2026-07-12"},
			}
		}
		mock_call.return_value = {
			"message": {"role": "assistant", "content": "本月销售额 12 万元。"},
			"model": "opencode-deepseek-v4-flash",
			"model_alias": "erp-fast-chat",
			"trace_id": "trace-3",
			"usage": {"reasoning_tokens": 0},
			"warnings": ["只读模式"],
		}

		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.session.user = "user@example.com"
			mock_frappe.local.lang = "zh-CN"
			mock_frappe.has_permission.return_value = True
			result = chat_ai_v1(
				content="解释本月销售表现",
				scenario="report_summary",
				company="rgc (Demo)",
			)

		citation = result["data"]["message"]["citations"][0]
		self.assertEqual(citation["type"], "business_report")
		self.assertEqual(citation["data"]["overview"]["sales_amount_total"], 120000)
		payload = mock_call.call_args.args[0]
		self.assertEqual(payload["context"]["tool"], "get_business_report")
		self.assertEqual(payload["context"]["dsl"]["report_type"], "sales")
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
