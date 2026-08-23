import io
import json
import os
import urllib.error
from contextlib import nullcontext
from datetime import date
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from frappe.exceptions import QueryDeadlockError

from myapp.services.ai_service import (
	_build_draft_version_diff,
	_build_inventory_adjustment_draft,
	_build_order_query_context,
	_build_order_query_dsl,
	_build_next_conversation_state,
	_build_product_setup_draft,
	_candidate_requests_product_image_application,
	_rebuild_order_draft_before_execution,
	_authoritative_reference_price,
	_refresh_ai_draft_before_execution,
	_resolve_line_price_intent,
	_execute_ai_draft_payload,
	_fail_draft_generation_run,
	_build_report_query_dsl,
	_call_ai_orchestrator,
	_call_ai_orchestrator_product_setup_draft,
	_call_ai_intent_orchestrator,
	_normalize_ai_business_result_refresh,
	_update_ai_draft_once,
	_hybrid_rerank_product_rows,
	_extract_product_search_terms,
	_normalize_product_entity_text,
	_merge_intent_with_conversation_state,
	_resolve_item_candidates,
	_infer_ai_scenario,
	_infer_ai_action_scenario,
	_prepare_chat_run,
	_prepare_product_setup_image_binding,
	_resolve_draft_retry_request,
	_start_draft_generation_run,
	_prepare_agent_resume,
	_query_business_document_entity,
	_resolve_inventory_draft_item,
	_resolve_purchase_draft_item,
	_resolve_product_setup_source_attachments,
	_resolve_prompt_version,
	_resolve_order_update_source,
	_resolve_sales_draft_item,
	_requests_product_image_application,
	_complete_chat_run,
	_stream_ai_orchestrator,
	chat_ai_v1,
	execute_ai_draft_v1,
	generate_ai_inventory_adjustment_draft_v1,
	generate_ai_purchase_order_draft_v1,
	generate_ai_sales_order_draft_v1,
	get_ai_conversation_v1,
	list_ai_conversations_v1,
	list_ai_drafts_v1,
	rename_ai_conversation_v1,
	reset_ai_conversation_context_v1,
	refresh_ai_business_result_v1,
	resume_ai_run_v1,
	stream_ai_message_v1,
	stream_ai_run_resume_v1,
	submit_ai_feedback_v1,
	update_ai_draft_v1,
)
from myapp.utils.ai_errors import AiDraftVersionConflictError, AiServiceError
from myapp.utils.api_response import UpstreamServiceUnavailableError, map_exception_to_error


class TestAiService(TestCase):
	def setUp(self):
		# Existing tests exercise the compatibility chat path. Agent Runtime has
		# dedicated contract tests and is enabled explicitly there.
		self._agent_runtime_env = patch.dict(
			os.environ, {"MYAPP_AI_AGENT_RUNTIME_ENABLED": "0"}, clear=False,
		)
		self._agent_runtime_env.start()

	def tearDown(self):
		self._agent_runtime_env.stop()

	@patch("myapp.services.ai_service.ai_repository.prepare_failed_run_retry")
	def test_draft_retry_recovers_original_attachment_ids(self, mock_prepare):
		mock_prepare.return_value = {
			"content": "按照照片新增商品",
			"company": "Demo Company",
			"conversation_id": "AI-CONV-1",
			"attachment_ids": ["AI-ATT-1"],
			"failed_message_id": "AI-MSG-FAILED",
			"scenario": "product_setup_draft",
			"source_run_id": "AI-RUN-FAILED",
		}

		content, company, conversation_id, attachment_ids, retry_context = _resolve_draft_retry_request(
			scenario="product_setup_draft", user="user@example.com", content="重试",
			company="Other", conversation_id=None, attachment_ids=[], retry_run_id="AI-RUN-FAILED",
		)

		self.assertEqual(content, "按照照片新增商品")
		self.assertEqual(company, "Demo Company")
		self.assertEqual(conversation_id, "AI-CONV-1")
		self.assertEqual(attachment_ids, ["AI-ATT-1"])
		self.assertEqual(retry_context["source_run_id"], "AI-RUN-FAILED")

	def test_product_image_application_requires_explicit_non_negated_intent(self):
		self.assertTrue(_requests_product_image_application("图片就使用我给你发的图片"))
		self.assertTrue(_requests_product_image_application("把刚才那张图设为商品主图"))
		self.assertFalse(_requests_product_image_application("根据刚才图片完善商品资料"))
		self.assertFalse(_requests_product_image_application("不要使用之前图片，保留现有主图"))

	def test_product_image_evidence_declares_explicit_application(self):
		self.assertTrue(_candidate_requests_product_image_application({
			"evidence": [{
				"field": "image", "value": "use_as_product_image",
				"attachment_id": "AI-ATT-1", "confidence": 1,
			}],
		}))
		self.assertFalse(_candidate_requests_product_image_application({
			"evidence": [{
				"field": "item_name", "value": "相机",
				"attachment_id": "AI-ATT-1", "confidence": 0.9,
			}],
		}))

	def test_product_source_attachment_prefers_valid_image_evidence(self):
		messages = [
			{"role": "user", "content": "第一张", "attachments": [{
				"attachment_id": "AI-ATT-1", "mime_type": "image/webp", "data_base64": "first",
			}]},
			{"role": "assistant", "content": "已看到"},
			{"role": "user", "content": "第二张", "attachments": [{
				"attachment_id": "AI-ATT-2", "mime_type": "image/webp", "data_base64": "second",
			}]},
		]
		result = _resolve_product_setup_source_attachments(
			candidate={"evidence": [{
				"field": "image", "value": "use_as_product_image",
				"attachment_id": "AI-ATT-1", "confidence": 1,
			}]},
			model_messages=messages,
			current_attachment_refs=[],
			content="把第一张图片设为商品主图",
		)

		self.assertEqual([row["attachment_id"] for row in result], ["AI-ATT-1"])
		self.assertNotIn("data_base64", result[0])

	def test_product_source_attachment_falls_back_only_for_explicit_history_reference(self):
		messages = [
			{"role": "user", "content": "订单截图", "attachments": [{"attachment_id": "AI-ATT-ORDER"}]},
			{"role": "assistant", "content": "已看到"},
			{"role": "user", "content": "商品照片", "attachments": [{"attachment_id": "AI-ATT-PRODUCT"}]},
			{"role": "user", "content": "完善商品"},
		]
		selected = _resolve_product_setup_source_attachments(
			candidate={}, model_messages=messages, current_attachment_refs=[],
			content="完善商品，图片使用我刚才发的图片",
		)
		ignored = _resolve_product_setup_source_attachments(
			candidate={}, model_messages=messages, current_attachment_refs=[],
			content="完善这个商品的说明",
		)

		self.assertEqual([row["attachment_id"] for row in selected], ["AI-ATT-PRODUCT"])
		self.assertEqual(ignored, [])

	@patch("myapp.services.ai_service.stage_attachment_as_item_image", return_value="/files/history.webp")
	def test_product_image_binding_stages_explicit_history_image_for_update(self, mock_stage):
		candidate, sources, image_url, should_stage, apply_image = _prepare_product_setup_image_binding(
			candidate={"operation": "update", "item_code": "ITEM-1"},
			model_messages=[
				{"role": "user", "content": "商品照片", "attachments": [{
					"attachment_id": "AI-ATT-HISTORY", "mime_type": "image/webp",
				}]},
				{"role": "user", "content": "完善商品，图片使用我发的图片"},
			],
			current_attachment_refs=[],
			content="完善商品，图片使用我发的图片",
			user="user@example.com",
			resolved_operation="update",
			requested_operation="update",
			existing_matches=[{"name": "ITEM-1"}],
		)

		self.assertTrue(should_stage)
		self.assertTrue(apply_image)
		self.assertEqual(image_url, "/files/history.webp")
		self.assertEqual(candidate["image"], "/files/history.webp")
		self.assertEqual([row["attachment_id"] for row in sources], ["AI-ATT-HISTORY"])
		mock_stage.assert_called_once_with(
			attachment_id="AI-ATT-HISTORY", user="user@example.com",
		)

	@patch("myapp.services.ai_service.resolve_ai_attachments")
	@patch("myapp.services.ai_service.ai_repository.rebind_failed_run_message_for_retry")
	@patch("myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-RETRY")
	@patch("myapp.services.ai_service.ai_repository.append_message")
	def test_draft_retry_rebinds_failed_assistant_without_duplicate_user_message(
		self, mock_append, mock_create_run, mock_rebind, mock_resolve,
	):
		retry_context = {
			"failed_message_id": "AI-MSG-FAILED",
			"source_run_id": "AI-RUN-FAILED",
		}
		run_id = _start_draft_generation_run(
			scenario="product_setup_draft", prompt_version="product-setup-draft-v6",
			user="user@example.com", content="按照照片新增商品", conversation_id="AI-CONV-1",
			model_alias="vision-model", attachment_ids=["AI-ATT-1"],
			attachment_refs=[{"attachment_id": "AI-ATT-1"}],
			attachment_payloads=[{"attachment_id": "AI-ATT-1"}], retry_context=retry_context,
		)

		self.assertEqual(run_id, "AI-RUN-RETRY")
		mock_append.assert_not_called()
		mock_resolve.assert_not_called()
		mock_create_run.assert_called_once_with(
			conversation_id="AI-CONV-1", user="user@example.com", scenario="product_setup_draft",
			model_alias="vision-model", retry_of_run_id="AI-RUN-FAILED",
		)
		mock_rebind.assert_called_once()

	@patch("myapp.services.ai_service.time.perf_counter", return_value=10.25)
	@patch("myapp.services.ai_service.ai_repository.append_failed_run_message")
	@patch("myapp.services.ai_service.ai_repository.fail_run")
	@patch("myapp.services.ai_service.frappe")
	def test_failed_draft_generation_persists_retryable_assistant_placeholder(
		self, mock_frappe, mock_fail_run, mock_append_failed, _perf_counter,
	):
		error = AiServiceError("vision unavailable", code="AI_SELECTED_MODEL_NO_VISION")

		_fail_draft_generation_run(
			run_id="AI-RUN-FAILED", user="user@example.com", error=error, started=10,
		)

		mock_frappe.db.rollback.assert_called_once_with()
		mock_fail_run.assert_called_once_with(
			run_id="AI-RUN-FAILED", user="user@example.com", error=error, latency_ms=250,
		)
		mock_append_failed.assert_called_once_with(
			run_id="AI-RUN-FAILED", user="user@example.com",
		)
		mock_frappe.db.commit.assert_called_once_with()

	@patch("myapp.services.ai_service._can_view_advanced_diagnostics", return_value=True)
	@patch("myapp.services.ai_service._current_user", return_value="manager@example.com")
	@patch("myapp.services.ai_service._resolve_ai_model_display", return_value="DeepSeek V4 Flash")
	@patch("myapp.services.ai_service._get_ai_orchestrator_settings", return_value=("http://ai", "token"))
	@patch("myapp.services.ai_service.urllib.request.urlopen")
	def test_structured_draft_provider_error_preserves_model_diagnostics(
		self, mock_urlopen, _settings, _display, _user, _advanced,
	):
		body = json.dumps({
			"detail": {
				"code": "MODEL_PROVIDER_REJECTED",
				"message": "模型供应商拒绝了请求。",
				"model_alias": "opencode-deepseek-v4-flash",
				"provider_error_code": "PROVIDER_HTTP_403",
			},
		}).encode()
		mock_urlopen.side_effect = urllib.error.HTTPError(
			"http://ai/internal/v1/drafts/product-setup", 502, "Bad Gateway", {}, io.BytesIO(body),
		)

		with self.assertRaises(AiServiceError) as raised:
			_call_ai_orchestrator_product_setup_draft({
				"messages": [{"role": "user", "content": "完善迪莫商品资料"}],
				"model_alias": None,
			})

		self.assertEqual(raised.exception.code, "MODEL_PROVIDER_REJECTED")
		self.assertEqual(raised.exception.model_alias, "opencode-deepseek-v4-flash")
		self.assertEqual(raised.exception.public_data, {
			"model_display": "DeepSeek V4 Flash",
			"model_alias": "opencode-deepseek-v4-flash",
			"provider_error_code": "PROVIDER_HTTP_403",
			"retryable": True,
		})
		self.assertIn("DeepSeek V4 Flash", str(raised.exception))

	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	@patch("myapp.services.ai_service.ai_repository.list_conversations")
	def test_list_ai_conversations_forwards_search(self, mock_list, _current_user):
		mock_list.return_value = {"items": [], "pagination": {"total": 0}}

		list_ai_conversations_v1(status="archived", search="采购", start=20, limit=10)

		mock_list.assert_called_once_with(
			user="user@example.com", status="archived", search="采购", start=20, limit=10,
		)

	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	@patch("myapp.services.ai_service.ai_repository.rename_conversation")
	def test_rename_ai_conversation_uses_current_user_scope(self, mock_rename, _current_user):
		mock_rename.return_value = {"name": "AI-CONV-1", "title": "采购跟进"}

		rename_ai_conversation_v1(conversation_id="AI-CONV-1", title="采购跟进")

		mock_rename.assert_called_once_with(
			conversation_id="AI-CONV-1", user="user@example.com", title="采购跟进",
		)

	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	@patch("myapp.services.ai_service._can_view_advanced_diagnostics", return_value=False)
	@patch("myapp.services.ai_service.ai_repository.get_conversation")
	def test_get_ai_conversation_forwards_message_cursor(
		self, mock_get_conversation, _diagnostics, _current_user,
	):
		mock_get_conversation.return_value = {
			"conversation": {"name": "AI-CONV-1"},
			"messages": [],
			"pagination": {"has_more": False},
		}

		get_ai_conversation_v1(
			conversation_id="AI-CONV-1", before_sequence=81, limit=40,
		)

		mock_get_conversation.assert_called_once_with(
			conversation_id="AI-CONV-1",
			user="user@example.com",
			before_sequence=81,
			limit=40,
			include_advanced_diagnostics=False,
		)

	@patch("myapp.services.ai_service._get_ai_orchestrator_settings", return_value=("http://ai", "token"))
	@patch("myapp.services.ai_service.urllib.request.urlopen")
	def test_stream_orchestrator_preserves_runtime_limit_code(self, mock_urlopen, _settings):
		mock_urlopen.side_effect = urllib.error.HTTPError(
			url="http://ai/internal/v1/chat/stream",
			code=429,
			msg="Too Many Requests",
			hdrs=None,
			fp=io.BytesIO(
				b'{"detail":{"code":"AI_DAILY_BUDGET_EXCEEDED","message":"budget exceeded"}}'
			),
		)

		with self.assertRaises(AiServiceError) as caught:
			list(_stream_ai_orchestrator({"messages": []}))

		self.assertEqual(caught.exception.code, "AI_DAILY_BUDGET_EXCEEDED")
		self.assertEqual(caught.exception.http_status, 429)

	@patch("myapp.services.ai_service.search_product_v2")
	@patch("myapp.services.ai_service.frappe.get_list")
	def test_user_edited_order_prices_override_reference_prices_but_model_prices_do_not(
		self, mock_allowed, mock_search,
	):
		mock_allowed.return_value = ["ITEM-001"]
		base = {
			"item_code": "ITEM-001", "item_name": "煌星", "uom": "Unit",
			"uom_display": "个", "all_uoms": [{"uom": "Unit", "conversion_factor": 1}],
			"price": 100, "price_summary": {
				"standard_buying_rate": 60,
				"selling_prices": [{"price_list": "Standard Selling", "rate": 100}],
				"buying_prices": [{"price_list": "Standard Buying", "rate": 60}],
			},
		}
		mock_search.return_value = {"data": [base]}
		candidate = {
			"item_query": "ITEM-001", "qty": 2, "uom": "Unit", "price": 88,
			"warehouse_query": "Stores - DC",
		}

		model_sales = _resolve_sales_draft_item(
			candidate, company="Demo Company", default_warehouse="Stores - DC",
		)
		user_sales = _resolve_sales_draft_item(
			candidate, company="Demo Company", default_warehouse="Stores - DC",
			allow_user_price=True,
		)
		user_purchase = _resolve_purchase_draft_item(
			candidate, company="Demo Company", default_warehouse="Stores - DC",
			allow_user_price=True,
		)

		self.assertEqual(model_sales["price"], 100)
		self.assertEqual(user_sales["price"], 88)
		self.assertEqual(user_purchase["price"], 88)

	def test_reference_price_distinguishes_missing_from_explicit_zero(self):
		missing, missing_source = _authoritative_reference_price(
			{"price_list": "Standard Selling", "price_summary": {"selling_prices": []}},
			buying=False,
		)
		explicit_zero, zero_source = _authoritative_reference_price(
			{
				"price_list": "Standard Selling",
				"price_summary": {
					"selling_prices": [
						{"price_list": "Standard Selling", "rate": 0},
					],
				},
			},
			buying=False,
		)

		self.assertIsNone(missing)
		self.assertEqual(explicit_zero, 0)
		self.assertEqual(missing_source, zero_source)

	def test_system_price_refreshes_while_user_override_remains_intentional(self):
		system_price, system_patch = _resolve_line_price_intent(
			{
				"price": 100,
				"_state": {
					"schema_version": "ai-draft-state-v1",
					"patch": {},
					"effective": {"price": 100},
				},
			},
			reference_price=120,
			allow_user_price=True,
		)
		user_price, user_patch = _resolve_line_price_intent(
			{
				"price": 88,
				"_state": {
					"schema_version": "ai-draft-state-v1",
					"patch": {"price": 88},
					"effective": {"price": 88},
				},
			},
			reference_price=120,
			allow_user_price=True,
		)

		self.assertEqual(system_price, 120)
		self.assertEqual(system_patch, {})
		self.assertEqual(user_price, 88)
		self.assertEqual(user_patch, {"price": 88})
	@patch("myapp.services.ai_service.create_product_v2")
	def test_execute_product_setup_draft_reuses_product_domain_service(self, mock_create):
		mock_create.return_value = {"status": "success", "data": {"item_code": "ITEM-001"}}
		result = _execute_ai_draft_payload({
			"draft_type": "product_setup",
			"payload": {
				"item_name": "煌星", "item_code": "ITEM-001", "company": "Demo Company",
				"item_group": "Products", "brand": "Brand A", "stock_uom": "Unit",
				"standard_selling_rate": 10000, "wholesale_rate": 8800,
				"retail_rate": 10800, "standard_buying_rate": 5000,
				"currency": "CNY", "warehouse": "Stores - DC", "opening_qty": 5,
				"opening_uom": "Unit", "description": "测试商品",
				"image": "/files/huangxing.png",
			},
		}, request_id="REQ-1")

		self.assertEqual(result["target_doctype"], "Item")
		self.assertEqual(result["target_name"], "ITEM-001")
		mock_create.assert_called_once_with(
			item_name="煌星", item_code="ITEM-001", image="/files/huangxing.png",
			item_group="Products", brand="Brand A",
			stock_uom="Unit", standard_rate=10000, valuation_rate=5000, currency="CNY",
			selling_prices=[
				{"price_list": "Wholesale", "rate": 8800, "currency": "CNY"},
				{"price_list": "Retail", "rate": 10800, "currency": "CNY"},
			],
			buying_prices=[{"price_list": "Standard Buying", "rate": 5000, "currency": "CNY"}],
			description="测试商品", company="Demo Company", warehouse="Stores - DC",
			warehouse_stock_qty=5, warehouse_stock_uom="Unit", request_id="REQ-1",
		)

	@patch("myapp.services.ai_service.update_product_v2")
	def test_execute_product_update_only_sends_user_patch(self, mock_update):
		mock_update.return_value = {"status": "success", "data": {"item_code": "ITEM-001"}}

		result = _execute_ai_draft_payload({
			"draft_type": "product_setup",
			"payload": {
				"operation": "update",
				"company": "Demo Company",
				"item_code": "ITEM-001",
				"currency": "CNY",
				"_state": {
					"operation": "update",
					"entity": {"doctype": "Item", "name": "ITEM-001"},
					"patch": {
						"standard_selling_rate": 5,
						"description": "新说明",
						"image": "/files/item-new.png",
					},
				},
			},
		}, request_id="REQ-UPDATE")

		self.assertEqual(result["target_name"], "ITEM-001")
		mock_update.assert_called_once_with(
			item_code="ITEM-001",
			company="Demo Company",
			request_id="REQ-UPDATE",
			description="新说明",
			image="/files/item-new.png",
			standard_rate=5,
		)

	@patch("myapp.services.ai_service.create_order_v2")
	@patch("myapp.services.ai_service.create_purchase_order")
	@patch("myapp.services.ai_service.reconcile_inventory_stock_v1")
	def test_execute_transaction_drafts_reuse_existing_domain_services(
		self, mock_inventory, mock_purchase, mock_sales,
	):
		mock_sales.return_value = {"status": "success", "order": "SO-001"}
		mock_purchase.return_value = {"status": "success", "purchase_order": "PO-001"}
		mock_inventory.return_value = {"status": "success", "data": {"stock_entry": "STE-001"}}
		line = {"item_code": "ITEM-001", "qty": 2, "uom": "Unit", "price": 10, "warehouse": "Stores - DC"}

		sales = _execute_ai_draft_payload({
			"draft_type": "sales_order", "payload": {
				"customer": "CUST-1", "company": "Demo Company", "transaction_date": "2026-07-18",
				"delivery_date": "2026-07-20", "warehouse": "Stores - DC",
				"default_sales_mode": "wholesale", "remarks": "AI 草稿", "items": [line],
			},
		}, request_id="REQ-S")
		purchase = _execute_ai_draft_payload({
			"draft_type": "purchase_order", "payload": {
				"supplier": "SUP-1", "company": "Demo Company", "transaction_date": "2026-07-18",
				"schedule_date": "2026-07-20", "warehouse": "Stores - DC", "currency": "CNY",
				"supplier_ref": "REF-1", "remarks": "AI 草稿", "items": [line],
			},
		}, request_id="REQ-P")
		inventory = _execute_ai_draft_payload({
			"draft_type": "inventory_adjustment", "payload": {
				"warehouse": "Stores - DC", "posting_date": "2026-07-18", "reason": "盘点差异",
				"items": [{"item_code": "ITEM-001", "target_stock_qty": 8, "stock_uom": "Unit", "valuation_rate": 5}],
			},
		}, request_id="REQ-I")

		self.assertEqual(sales["target_name"], "SO-001")
		self.assertEqual(purchase["target_name"], "PO-001")
		self.assertEqual(inventory["target_name"], "STE-001")
		mock_sales.assert_called_once()
		mock_purchase.assert_called_once()
		mock_inventory.assert_called_once()

	@patch("myapp.services.ai_service.create_order_v2")
	@patch("myapp.services.ai_service.create_purchase_order")
	@patch("myapp.services.ai_service.update_order_items_v2")
	@patch("myapp.services.ai_service.update_order_v2")
	@patch("myapp.services.ai_service.update_purchase_order_items_v2")
	@patch("myapp.services.ai_service.update_purchase_order_v2")
	def test_execute_order_update_drafts_never_fall_back_to_create(
		self, mock_update_purchase, mock_update_purchase_items,
		mock_update_sales, mock_update_sales_items, mock_create_purchase, mock_create_sales,
	):
		mock_update_sales.return_value = {
			"status": "success", "order": "SO-001", "meta": {"modified": "2026-08-14 10:01:00"},
		}
		mock_update_sales_items.return_value = {"status": "success", "order": "SO-001"}
		mock_update_purchase.return_value = {
			"status": "success", "purchase_order": "PO-001",
			"meta": {"modified": "2026-08-14 10:02:00"},
		}
		line = {
			"item_code": "ITEM-001", "qty": 2, "uom": "Unit",
			"price": 10, "warehouse": "Stores - DC",
		}

		sales = _execute_ai_draft_payload({
			"draft_type": "sales_order", "payload": {
				"operation": "update", "order_number": "SO-001",
				"source_order_modified": "2026-08-14 10:00:00",
				"update_items_explicit": True, "company": "Demo Company",
				"transaction_date": "2026-07-18", "delivery_date": "2026-07-20",
				"warehouse": "Stores - DC", "default_sales_mode": "wholesale",
				"remarks": "更新销售订单", "items": [line],
			},
		}, request_id="REQ-SU")
		purchase = _execute_ai_draft_payload({
			"draft_type": "purchase_order", "payload": {
				"operation": "update", "order_number": "PO-001",
				"source_order_modified": "2026-08-14 10:00:00",
				"update_items_explicit": False, "company": "Demo Company",
				"transaction_date": "2026-07-18", "schedule_date": "2026-07-20",
				"warehouse": "Stores - DC", "supplier_ref": "REF-2",
				"remarks": "仅更新采购订单表头", "items": [line],
			},
		}, request_id="REQ-PU")

		self.assertEqual(sales["target_name"], "SO-001")
		self.assertEqual(purchase["target_name"], "PO-001")
		mock_update_sales.assert_called_once_with(
			order_name="SO-001", transaction_date="2026-07-18",
			delivery_date="2026-07-20", default_sales_mode="wholesale",
			remarks="更新销售订单", request_id="REQ-SU",
			expected_modified="2026-08-14 10:00:00",
		)
		self.assertEqual(
			mock_update_sales_items.call_args.kwargs["expected_modified"],
			"2026-08-14 10:01:00",
		)
		mock_update_purchase.assert_called_once_with(
			order_name="PO-001", transaction_date="2026-07-18",
			schedule_date="2026-07-20", supplier_ref="REF-2",
			remarks="仅更新采购订单表头", request_id="REQ-PU",
			expected_modified="2026-08-14 10:00:00",
		)
		mock_update_purchase_items.assert_not_called()
		mock_create_sales.assert_not_called()
		mock_create_purchase.assert_not_called()

	@patch("myapp.services.ai_service.get_sales_order_detail")
	@patch("myapp.services.ai_service._resolve_sales_draft_customer")
	@patch("myapp.services.ai_service._resolve_sales_draft_warehouse", return_value="Stores - DC")
	@patch("myapp.services.ai_service._resolve_sales_draft_item")
	def test_order_execution_refresh_rejects_concurrent_source_order_change(
		self, mock_item, _warehouse, mock_customer, mock_detail,
	):
		mock_detail.return_value = {"data": {"meta": {
			"company": "Demo Company", "modified": "2026-08-14 11:00:00",
		}}}
		mock_customer.return_value = ({"name": "CUST-1", "display_name": "客户A"}, [])
		mock_item.return_value = {
			"item_code": "ITEM-001", "qty": 1, "uom": "Unit", "price": 10,
			"warehouse": "Stores - DC", "warnings": [],
		}
		next_payload, validation = _rebuild_order_draft_before_execution({
			"draft_type": "sales_order",
			"company": "Demo Company",
			"payload": {
				"operation": "update", "order_number": "SO-001",
				"source_order_modified": "2026-08-14 10:00:00",
				"customer": "CUST-1", "warehouse": "Stores - DC",
				"items": [{"item_code": "ITEM-001", "qty": 1}],
			},
		})

		self.assertFalse(validation["ready_for_handoff"])
		self.assertTrue(any("其他用户修改" in error for error in validation["errors"]))
		self.assertEqual(next_payload["source_order_modified"], "2026-08-14 10:00:00")

	@patch("myapp.services.ai_service.get_sales_order_detail")
	def test_missing_system_order_stays_an_invalid_update(self, mock_get_detail):
		mock_get_detail.side_effect = frappe.DoesNotExistError

		operation, order_number, detail, errors = _resolve_order_update_source(
			{
				"operation": "auto", "order_number": "SO-MISSING",
				"source_document_type": "our_system_order",
			},
			draft_type="sales_order", company="Demo Company",
		)

		self.assertEqual(operation, "update")
		self.assertEqual(order_number, "SO-MISSING")
		self.assertIsNone(detail)
		self.assertTrue(errors)

	@patch("myapp.services.ai_service.run_idempotent", side_effect=lambda _namespace, _request_id, callback, **_kwargs: callback())
	@patch("myapp.services.ai_service.filelock", side_effect=lambda *_args, **_kwargs: nullcontext())
	@patch("myapp.services.ai_service._record_ai_draft_execution_audit")
	@patch("myapp.services.ai_service._execute_ai_draft_payload")
	@patch("myapp.services.ai_service._refresh_ai_draft_before_execution", side_effect=lambda draft, user: draft)
	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	def test_execute_ai_draft_checks_version_and_persists_receipt(
		self, _user, _refresh, mock_execute, _audit, _lock, _idempotent,
	):
		draft = {
			"name": "AI-DRAFT-1", "draft_type": "sales_order", "status": "draft", "version": 3,
			"payload": {}, "validation": {"ready_for_handoff": True}, "execution": None,
		}
		mock_execute.return_value = {
			"target_doctype": "Sales Order", "target_name": "SO-001",
			"result": {"status": "success", "order": "SO-001"},
		}
		executed = {**draft, "status": "executed", "execution": {"target_name": "SO-001"}}
		with patch("myapp.services.ai_service.ai_repository.get_draft", return_value=draft), patch(
			"myapp.services.ai_service.ai_repository.mark_draft_executed", return_value=executed,
		) as mock_mark, patch("myapp.services.ai_service.frappe") as mock_frappe:
			result = execute_ai_draft_v1(
				draft_id="AI-DRAFT-1", expected_version=3, confirmed=True, request_id="REQ-1",
			)

		self.assertEqual(result["data"]["execution"]["target_name"], "SO-001")
		mock_mark.assert_called_once_with(
			draft_id="AI-DRAFT-1", user="user@example.com", request_id="REQ-1",
			target_doctype="Sales Order", target_name="SO-001",
			result={"status": "success", "order": "SO-001"},
		)
		mock_frappe.db.commit.assert_not_called()

	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	def test_execute_ai_draft_rejects_a_stale_version_with_domain_conflict(self, _user):
		draft = {
			"name": "AI-DRAFT-1", "draft_type": "sales_order", "status": "draft", "version": 4,
			"payload": {}, "validation": {"ready_for_handoff": True}, "execution": None,
		}
		with patch(
			"myapp.services.ai_service.ai_repository.get_draft", return_value=draft,
		), patch(
			"myapp.services.ai_service.filelock", side_effect=lambda *_args, **_kwargs: nullcontext(),
		), patch(
			"myapp.services.ai_service.run_idempotent",
			side_effect=lambda _namespace, _request_id, callback, **_kwargs: callback(),
		):
			with self.assertRaises(AiDraftVersionConflictError):
				execute_ai_draft_v1(
					draft_id="AI-DRAFT-1", expected_version=3, confirmed=True, request_id="REQ-STALE",
				)

	@patch("myapp.services.ai_service._update_ai_draft_once")
	@patch(
		"myapp.services.ai_service.run_idempotent",
		side_effect=lambda _namespace, _request_id, callback, **_kwargs: callback(),
	)
	@patch("myapp.services.ai_service.get_current_request_id", return_value="REQ-UPDATE-1")
	def test_update_ai_draft_uses_expected_version_and_idempotency(
		self, _request_id, mock_idempotent, mock_update_once,
	):
		mock_update_once.return_value = {"status": "success", "data": {"version": 3}}

		result = update_ai_draft_v1(
			draft_id="AI-DRAFT-1",
			payload={"remarks": "修改后"},
			expected_version=2,
			request_id="REQ-UPDATE-1",
		)

		self.assertEqual(result["data"]["version"], 3)
		mock_update_once.assert_called_once_with(
			draft_id="AI-DRAFT-1",
			payload={"remarks": "修改后"},
			expected_version=2,
			change_source="user_edit",
		)
		self.assertEqual(mock_idempotent.call_args.args[:2], ("update_ai_draft_v1", "REQ-UPDATE-1"))

	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	def test_update_sales_draft_preserves_edited_item_fields_and_version(self, _user):
		draft = {"draft_type": "sales_order", "company": "Demo Company"}
		resolved_item = {
			"item_code": "ITEM-001", "item_name": "相机", "qty": 5,
			"uom": "Unit", "price": 120, "warehouse": "Stores - DC", "warnings": [],
		}
		updated = {"name": "AI-DRAFT-1", "version": 3}
		with patch("myapp.services.ai_service.ai_repository.get_draft", return_value=draft), patch(
			"myapp.services.ai_service._resolve_sales_draft_customer",
			return_value=({"name": "CUST-1", "display_name": "客户A"}, []),
		), patch(
			"myapp.services.ai_service._resolve_sales_draft_warehouse", return_value="Stores - DC",
		), patch(
			"myapp.services.ai_service._resolve_sales_draft_item", return_value=resolved_item,
		), patch(
			"myapp.services.ai_service.ai_repository.update_draft", return_value=updated,
		) as mock_update, patch("myapp.services.ai_service.frappe"):
			result = _update_ai_draft_once(
				draft_id="AI-DRAFT-1",
				payload={
					"customer": "CUST-1", "warehouse": "Stores - DC",
					"transaction_date": "2026-07-19", "delivery_date": "2026-07-20",
					"items": [{"item_code": "ITEM-001", "qty": 5, "price": 120}],
				},
				expected_version=2,
			)

		self.assertEqual(result["data"]["version"], 3)
		call = mock_update.call_args.kwargs
		self.assertEqual(call["expected_version"], 2)
		self.assertEqual(call["payload"]["items"][0]["qty"], 5)
		self.assertEqual(call["payload"]["items"][0]["price"], 120)

	@patch("myapp.services.ai_service._resolve_sales_draft_warehouse", return_value=None)
	@patch("myapp.services.ai_service._resolve_item_candidates")
	def test_unresolved_order_lines_preserve_item_and_warehouse_queries(
		self, mock_candidates, _warehouse,
	):
		mock_candidates.return_value = {"candidates": [], "selected": None}
		for resolver in (_resolve_sales_draft_item, _resolve_purchase_draft_item):
			with self.subTest(resolver=resolver.__name__):
				row = resolver(
					{
						"item_query": "圣晶石",
						"qty": 2,
						"warehouse_query": "临时仓",
					},
					company="Demo Company",
					default_warehouse=None,
				)

				self.assertIsNone(row["item_code"])
				self.assertEqual(row["item_query"], "圣晶石")
				self.assertIsNone(row["warehouse"])
				self.assertEqual(row["warehouse_query"], "临时仓")

	@patch("myapp.services.ai_service.ai_repository.update_draft")
	@patch("myapp.services.ai_service._build_product_setup_draft")
	def test_execution_refresh_persists_new_version_when_business_facts_drift(
		self, mock_build, mock_update,
	):
		draft = {
			"name": "AI-DRAFT-1",
			"company": "Demo Company",
			"draft_type": "product_setup",
			"version": 3,
			"payload": {"_state": {"schema_version": "ai-draft-state-v1", "source_hash": "old"}},
		}
		mock_build.return_value = (
			{"_state": {"schema_version": "ai-draft-state-v1", "source_hash": "new"}},
			{"ready_for_handoff": True, "errors": [], "warnings": []},
		)
		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			with self.assertRaises(AiDraftVersionConflictError):
				_refresh_ai_draft_before_execution(draft=draft, user="user@example.com")

		mock_update.assert_called_once_with(
			draft_id="AI-DRAFT-1",
			user="user@example.com",
			payload={"_state": {"schema_version": "ai-draft-state-v1", "source_hash": "new"}},
			validation={"ready_for_handoff": True, "errors": [], "warnings": []},
			expected_version=3,
			change_source="system_refresh_before_execute",
		)
		mock_frappe.db.commit.assert_called_once()

	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	def test_update_purchase_draft_preserves_currency_reference_and_version(self, _user):
		draft = {"draft_type": "purchase_order", "company": "Demo Company"}
		resolved_item = {
			"item_code": "ITEM-001", "item_name": "相机", "qty": 3,
			"uom": "Unit", "price": 80, "warehouse": "Stores - DC", "warnings": [],
		}
		updated = {"name": "AI-DRAFT-1", "version": 3}
		with patch("myapp.services.ai_service.ai_repository.get_draft", return_value=draft), patch(
			"myapp.services.ai_service._resolve_purchase_draft_supplier",
			return_value=({"name": "SUP-1", "display_name": "供应商A"}, []),
		), patch(
			"myapp.services.ai_service._resolve_sales_draft_warehouse", return_value="Stores - DC",
		), patch(
			"myapp.services.ai_service._resolve_purchase_draft_item", return_value=resolved_item,
		), patch(
			"myapp.services.ai_service.ai_repository.update_draft", return_value=updated,
		) as mock_update, patch("myapp.services.ai_service.frappe"):
			result = _update_ai_draft_once(
				draft_id="AI-DRAFT-1",
				payload={
					"supplier": "SUP-1", "warehouse": "Stores - DC", "currency": "USD",
					"supplier_ref": "SUP-REF-001", "transaction_date": "2026-07-19",
					"schedule_date": "2026-07-22", "items": [{"item_code": "ITEM-001", "qty": 3}],
				},
				expected_version=2,
			)

		self.assertEqual(result["data"]["version"], 3)
		call = mock_update.call_args.kwargs
		self.assertEqual(call["expected_version"], 2)
		self.assertEqual(call["payload"]["currency"], "USD")
		self.assertEqual(call["payload"]["supplier_ref"], "SUP-REF-001")

	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	def test_update_inventory_and_product_drafts_pass_expected_version(self, _user):
		for draft_type, builder_name in (
			("inventory_adjustment", "_build_inventory_adjustment_draft"),
			("product_setup", "_build_product_setup_draft"),
		):
			with self.subTest(draft_type=draft_type), patch(
				"myapp.services.ai_service.ai_repository.get_draft",
				return_value={"draft_type": draft_type, "company": "Demo Company"},
			), patch(
				f"myapp.services.ai_service.{builder_name}",
				return_value=({"company": "Demo Company"}, {"ready_for_handoff": True}),
			), patch(
				"myapp.services.ai_service.ai_repository.update_draft",
				return_value={"name": "AI-DRAFT-1", "version": 3},
			) as mock_update, patch("myapp.services.ai_service.frappe"):
				_update_ai_draft_once(
					draft_id="AI-DRAFT-1", payload={}, expected_version=2,
				)
				self.assertEqual(mock_update.call_args.kwargs["expected_version"], 2)
	@patch("myapp.services.ai_service._call_ai_intent_orchestrator", return_value={
		"intent": "product_search", "confidence": 0.96, "product_query": "莫",
		"entities": [], "report_type": None, "date_preset": "all",
		"date_from": None, "date_to": None, "status": "all", "sort": "latest",
		"min_amount": None, "limit": 10,
	})
	@patch("myapp.services.ai_service._resolve_company_scope", side_effect=lambda company, required=False: company)
	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	@patch("myapp.services.ai_service.resolve_ai_selected_model_alias", return_value="erp-fast-chat")
	@patch("myapp.services.ai_service.resolve_ai_agent_runtime_readiness")
	def test_agent_runtime_uses_compatibility_query_when_policy_is_not_ready(
		self, mock_readiness, _resolve_model, _current_user, _resolve_company, mock_intent,
	):
		mock_readiness.return_value = {
			"ready": False, "reason": "no_published_policy", "policy_code": None,
		}
		with patch.dict(os.environ, {
			"MYAPP_AI_AGENT_RUNTIME_ENABLED": "1", "MYAPP_AI_ENVIRONMENT": "staging",
		}, clear=False), patch(
			"myapp.services.ai_service.ai_repository.create_conversation",
			return_value={"name": "AI-CONV-1", "company": "Demo Company"},
		), patch("myapp.services.ai_service.ai_repository.append_message"), patch(
			"myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-1",
		), patch("myapp.services.ai_service.ai_repository.load_model_messages", return_value=[]), patch(
			"myapp.services.ai_service._build_product_search_context",
			return_value=({"tool": "search_products", "products": []}, [], []),
		) as build_context, patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.local.lang = "zh-CN"
			mock_frappe.get_roles.return_value = []
			prepared = _prepare_chat_run(
				content="查询一下有没有带莫字的商品", scenario="auto", company="Demo Company",
			)

		self.assertFalse(prepared["agent_mode"])
		self.assertEqual(prepared["scenario"], "product_search")
		self.assertEqual(prepared["payload"]["context"]["tool"], "search_products")
		self.assertNotIn("policy_code", prepared["payload"])
		self.assertNotIn("policy_version", prepared["payload"])
		self.assertTrue(prepared["warnings"])
		self.assertEqual(prepared["tool_calls"][0]["tool"], "agent_runtime_readiness")
		self.assertEqual(prepared["tool_calls"][0]["reason"], "no_published_policy")
		mock_readiness.assert_called_once()
		mock_intent.assert_called_once()
		self.assertEqual(
			build_context.call_args.kwargs["structured_intent"]["product_query"], "莫",
		)

	@patch("myapp.services.ai_service._call_ai_intent_orchestrator", return_value={
		"intent": "product_search", "confidence": 0.97, "product_query": "迪莫",
		"entities": [], "report_type": None, "date_preset": "all",
		"date_from": None, "date_to": None, "status": "all", "sort": "latest",
		"min_amount": None, "limit": 10,
	})
	@patch("myapp.services.ai_service._resolve_company_scope", side_effect=lambda company, required=False: company)
	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	@patch("myapp.services.ai_service.resolve_ai_selected_model_alias", return_value="erp-fast-chat")
	def test_auto_compatibility_mode_uses_ai_semantics_without_a_local_keyword_hit(
		self, _resolve_model, _current_user, _resolve_company, mock_intent,
	):
		with patch.dict(os.environ, {"MYAPP_AI_AGENT_RUNTIME_ENABLED": "0"}, clear=False), patch(
			"myapp.services.ai_service.ai_repository.create_conversation",
			return_value={"name": "AI-CONV-1", "company": "Demo Company"},
		), patch("myapp.services.ai_service.ai_repository.append_message"), patch(
			"myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-1",
		), patch("myapp.services.ai_service.ai_repository.load_model_messages", return_value=[]), patch(
			"myapp.services.ai_service._build_product_search_context",
			return_value=({"tool": "search_products", "products": []}, [], []),
		) as build_context, patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.local.lang = "zh-CN"
			mock_frappe.get_roles.return_value = []
			prepared = _prepare_chat_run(
				content="仓里还剩迪莫吗", scenario="auto", company="Demo Company",
			)

		self.assertEqual(_infer_ai_scenario("仓里还剩迪莫吗"), "general")
		self.assertEqual(prepared["scenario"], "product_search")
		self.assertEqual(prepared["tool_calls"][0]["tool"], "parse_ai_intent")
		self.assertEqual(prepared["tool_calls"][0]["mode"], "structured_intent")
		self.assertEqual(
			build_context.call_args.kwargs["structured_intent"]["product_query"], "迪莫",
		)
		self.assertEqual(mock_intent.call_args.kwargs["model_alias"], "erp-fast-chat")

	@patch("myapp.services.ai_service._call_ai_intent_orchestrator", return_value={
		"intent": "order_query", "confidence": 0.99, "product_query": None,
		"entities": ["sales_order"], "report_type": None, "date_preset": "all",
		"date_from": None, "date_to": None, "status": "all", "sort": "latest",
		"min_amount": None, "limit": 10,
	})
	@patch("myapp.services.ai_service._resolve_company_scope", side_effect=lambda company, required=False: company)
	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	@patch("myapp.services.ai_service.resolve_ai_selected_model_alias", return_value="erp-fast-chat")
	def test_explicit_readonly_scenario_cannot_be_rewritten_by_intent_parser(
		self, _resolve_model, _current_user, _resolve_company, _mock_intent,
	):
		with patch.dict(os.environ, {"MYAPP_AI_AGENT_RUNTIME_ENABLED": "0"}, clear=False), patch(
			"myapp.services.ai_service.ai_repository.create_conversation",
			return_value={"name": "AI-CONV-1", "company": "Demo Company"},
		), patch("myapp.services.ai_service.ai_repository.append_message"), patch(
			"myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-1",
		), patch("myapp.services.ai_service.ai_repository.load_model_messages", return_value=[]), patch(
			"myapp.services.ai_service._build_product_search_context",
			return_value=({"tool": "search_products", "products": []}, [], []),
		) as build_context, patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.local.lang = "zh-CN"
			mock_frappe.get_roles.return_value = []
			prepared = _prepare_chat_run(
				content="仓里还有迪莫吗", scenario="product_search", company="Demo Company",
			)

		self.assertEqual(prepared["scenario"], "product_search")
		self.assertEqual(prepared["tool_calls"][0]["tool"], "parse_ai_intent")
		self.assertEqual(prepared["tool_calls"][0]["mode"], "structured_intent_fallback")
		self.assertIsNone(build_context.call_args.kwargs["structured_intent"])

	@patch("myapp.services.ai_service._resolve_company_scope", side_effect=lambda company, required=False: company)
	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	@patch("myapp.services.ai_service.resolve_ai_selected_model_alias", return_value="erp-fast-chat")
	@patch("myapp.services.ai_service.resolve_ai_agent_runtime_readiness", return_value={
		"ready": True, "reason": "ready", "policy_code": "general-staging", "policy_version": 4,
	})
	def test_agent_runtime_is_enabled_only_when_policy_is_ready(
		self, _readiness, _resolve_model, _current_user, _resolve_company,
	):
		with patch.dict(os.environ, {"MYAPP_AI_AGENT_RUNTIME_ENABLED": "1"}, clear=False), patch(
			"myapp.services.ai_service.ai_repository.create_conversation",
			return_value={"name": "AI-CONV-1", "company": "Demo Company"},
		), patch("myapp.services.ai_service.ai_repository.append_message"), patch(
			"myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-1",
		), patch("myapp.services.ai_service.ai_repository.load_model_messages", return_value=[]), patch(
			"myapp.services.ai_service.ai_repository.issue_agent_capability",
			return_value="capability-token",
		) as issue_capability, patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.local.lang = "zh-CN"
			mock_frappe.get_roles.return_value = []
			mock_frappe.has_permission.return_value = True
			prepared = _prepare_chat_run(
				content="查一下最近的订单", scenario="general", company="Demo Company",
			)

		self.assertTrue(prepared["agent_mode"])
		self.assertEqual(prepared["payload"]["capability_token"], "capability-token")
		self.assertEqual(prepared["payload"]["policy_code"], "general-staging")
		self.assertEqual(prepared["payload"]["policy_version"], 4)
		self.assertEqual(prepared["warnings"], [])
		issue_capability.assert_called_once()

	@patch("myapp.services.ai_service._resolve_company_scope", side_effect=lambda company, required=False: company)
	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	def test_existing_conversation_uses_its_persisted_company_when_request_omits_company(
		self, _current_user, mock_resolve_company,
	):
		with patch("myapp.services.ai_service.ai_repository.get_conversation") as mock_get, patch(
			"myapp.services.ai_service.ai_repository.get_conversation_state",
			return_value={"version": 0, "state": {"active_scenario": "general"}},
		), patch(
			"myapp.services.ai_service.ai_repository.append_message",
		), patch(
			"myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-1",
		), patch(
			"myapp.services.ai_service.ai_repository.load_model_messages", return_value=[],
		), patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_get.return_value = {
				"conversation": {"name": "AI-CONV-1", "company": "Original Company"},
			}
			mock_frappe.local.lang = "zh-CN"
			prepared = _prepare_chat_run(
				content="继续查询", scenario="general", conversation_id="AI-CONV-1",
			)

		self.assertEqual(prepared["company"], "Original Company")
		self.assertEqual(prepared["payload"]["company"], "Original Company")
		mock_resolve_company.assert_called_once_with("Original Company", required=False)
		self.assertEqual(prepared["tool_calls"][-1]["tool"], "load_conversation_context")
		self.assertFalse(prepared["tool_calls"][-1]["event_visible"])

	@patch("myapp.services.ai_service._call_ai_intent_orchestrator", return_value={
		"intent": "general", "confidence": 0.99, "product_query": None,
		"entities": [], "report_type": None, "date_preset": "all",
		"date_from": None, "date_to": None, "status": "all", "sort": "latest",
		"min_amount": None, "limit": 10,
	})
	@patch("myapp.services.ai_service._resolve_company_scope", side_effect=lambda company, required=False: company)
	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	@patch("myapp.services.ai_service.resolve_ai_selected_model_alias", return_value="gpt-5.6-luna")
	def test_failed_run_retry_reuses_message_and_current_selected_model(
		self, _resolve_model, _current_user, _resolve_company, _intent,
	):
		with patch.dict(
			os.environ, {"MYAPP_AI_AGENT_RUNTIME_ENABLED": "0"}, clear=False,
		), patch(
			"myapp.services.ai_service.ai_repository.prepare_failed_run_retry",
			return_value={
				"conversation_id": "AI-CONV-1",
				"company": "Demo Company",
				"content": "查询库存",
				"failed_message_id": "AI-MSG-2",
				"scenario": "general",
				"source_run_id": "AI-RUN-FAILED",
			},
		), patch(
			"myapp.services.ai_service.ai_repository.get_conversation",
			return_value={
				"conversation": {
					"name": "AI-CONV-1", "status": "active", "company": "Demo Company",
				},
			},
		), patch(
			"myapp.services.ai_service.ai_repository.get_conversation_state",
			return_value={"version": 0, "state": {"active_scenario": "general"}},
		), patch(
			"myapp.services.ai_service.ai_repository.append_message",
		) as append_message, patch(
			"myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-RETRY",
		) as create_run_mock, patch(
			"myapp.services.ai_service.ai_repository.rebind_failed_run_message_for_retry",
		) as rebind, patch(
			"myapp.services.ai_service.ai_repository.load_model_messages",
			return_value=[{"role": "user", "content": "查询库存"}],
		), patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.local.lang = "zh-CN"
			mock_frappe.get_roles.return_value = []
			prepared = _prepare_chat_run(
				content="ignored",
				scenario="auto",
				model_alias="gpt-5.6-luna",
				retry_run_id="AI-RUN-FAILED",
			)

		append_message.assert_not_called()
		create_run_mock.assert_called_once_with(
			conversation_id="AI-CONV-1",
			user="user@example.com",
			scenario="general",
			model_alias="gpt-5.6-luna",
			retry_of_run_id="AI-RUN-FAILED",
		)
		rebind.assert_called_once_with(
			message_id="AI-MSG-2",
			source_run_id="AI-RUN-FAILED",
			retry_run_id="AI-RUN-RETRY",
			user="user@example.com",
			scenario="general",
			prompt_version=prepared["prompt_version"],
		)
		self.assertEqual(prepared["payload"]["model_alias"], "gpt-5.6-luna")
		self.assertEqual(prepared["retry_of_run_id"], "AI-RUN-FAILED")

	@patch("myapp.services.ai_service._resolve_company_scope", side_effect=lambda company, required=False: company)
	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	def test_readonly_agent_does_not_capture_existing_product_setup_draft_flow(
		self, _current_user, _resolve_company,
	):
		with patch.dict(
			os.environ, {"MYAPP_AI_AGENT_RUNTIME_ENABLED": "1"}, clear=False,
		), patch(
			"myapp.services.ai_service.ai_repository.create_conversation",
			return_value={"name": "AI-CONV-1"},
		), patch(
			"myapp.services.ai_service.ai_repository.append_message",
		), patch(
			"myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-1",
		), patch(
			"myapp.services.ai_service.ai_repository.load_model_messages", return_value=[],
		), patch(
			"myapp.services.ai_service.ai_repository.issue_agent_capability",
		) as issue_capability, patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.local.lang = "zh-CN"
			prepared = _prepare_chat_run(
				content="新增一个商品叫传承结晶，库存单位是件",
				scenario="auto",
				company="Demo Company",
			)

		self.assertFalse(prepared["agent_mode"])
		self.assertEqual(prepared["scenario"], "product_setup_draft")
		self.assertNotIn("capability_token", prepared["payload"])
		issue_capability.assert_not_called()

	@patch("myapp.services.ai_service._resolve_company_scope", return_value="Demo Company")
	@patch("myapp.services.ai_service.resolve_ai_selected_model_alias", return_value="erp-fast-chat")
	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	def test_prepare_agent_resume_reuses_owned_run_checkpoint_contract(
		self, _current_user, _resolve_model, _resolve_company,
	):
		with patch(
			"myapp.services.ai_service.ai_repository.prepare_agent_run_resume",
			return_value={
				"run_id": "AI-RUN-1", "conversation_id": "AI-CONV-1", "scenario": "general",
				"company": "Demo Company", "model_alias": "erp-fast-chat",
				"prompt_version": "erp-readonly-v8", "allowed_tools": ["search_products"],
				"capability_token": "new-capability-token", "checkpoint_stage": "tool_completed",
			},
		), patch(
			"myapp.services.ai_service.ai_repository.get_conversation",
			return_value={"conversation": {"name": "AI-CONV-1", "status": "active"}},
		), patch(
			"myapp.services.ai_service.ai_repository.get_conversation_state",
			return_value={"version": 2, "state": {"schema_version": "conversation-state-v1"}},
		), patch(
			"myapp.services.ai_service.ai_repository.load_model_messages",
			return_value=[{"role": "user", "content": "查询商品"}],
		), patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.local.lang = "zh-CN"
			mock_frappe.get_roles.return_value = ["Sales User"]
			prepared = _prepare_agent_resume("AI-RUN-1")

		self.assertEqual(prepared["run_id"], "AI-RUN-1")
		self.assertEqual(prepared["payload"]["capability_token"], "new-capability-token")
		self.assertEqual(prepared["payload"]["model_alias"], "erp-fast-chat")
		self.assertEqual(prepared["payload"]["prompt_version"], "erp-readonly-v8")
		mock_frappe.db.commit.assert_called_once()

	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	@patch("myapp.services.ai_service.ai_repository.reset_conversation_state")
	def test_reset_conversation_context_keeps_owner_scope(self, mock_reset, _current_user):
		mock_reset.return_value = {
			"version": 4, "status": "empty", "reset_reason": "user_reset",
		}

		result = reset_ai_conversation_context_v1("AI-CONV-1")

		self.assertEqual(result["data"]["reset_reason"], "user_reset")
		mock_reset.assert_called_once_with(
			conversation_id="AI-CONV-1", user="user@example.com",
		)

	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	@patch("myapp.services.ai_service.ai_repository.list_drafts")
	def test_list_ai_drafts_uses_current_user_scope(self, mock_list, _current_user):
		mock_list.return_value = {"items": [], "pagination": {"total": 0}}

		result = list_ai_drafts_v1(
			status="handed_off", draft_type="purchase_order", start=20, limit=10,
		)

		self.assertEqual(result["data"]["pagination"]["total"], 0)
		mock_list.assert_called_once_with(
			user="user@example.com", status="handed_off", draft_type="purchase_order",
			start=20, limit=10,
		)

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
			{"payload": {"customer": "CUST-1", "image": "/files/old.png", "items": [{"item_code": "ITEM-1", "qty": 1, "uom": "Box"}]}},
			{"payload": {"customer": "CUST-2", "image": "/files/new.png", "items": [
				{"item_code": "ITEM-1", "qty": 2, "uom": "Box"},
				{"item_code": "ITEM-2", "qty": 1, "uom": "Nos"},
			]}},
		)

		self.assertEqual(diff["fields"][0]["field"], "customer")
		self.assertIn("image", [row["field"] for row in diff["fields"]])
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
			"draft": {
				"customer_query": "客户A", "warehouse_query": "Stores - TC",
				"items": [{"item_query": "相机", "qty": 2}],
			},
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
		self.assertEqual(result["data"]["run"]["status"], "completed")
		self.assertGreaterEqual(result["data"]["run"]["latency_ms"], 0)
		self.assertEqual(mock_create_draft.call_args.kwargs["payload"]["customer"], "CUST-1")
		self.assertEqual(
			mock_create_draft.call_args.kwargs["payload"]["warehouse_query"],
			"Stores - TC",
		)
		self.assertTrue(mock_create_draft.call_args.kwargs["validation"]["ready_for_handoff"])
		mock_item.assert_called_once_with(
			{"item_query": "相机", "qty": 2}, company="Test Company",
			default_warehouse="Stores - TC", allow_user_price=True,
		)
		self.assertEqual(_complete.call_args.kwargs["tool_calls"][0]["risk_level"], "L2_DRAFT_ONLY")
		expected_prompt_version = _resolve_prompt_version("sales_order_draft")
		self.assertEqual(mock_call.call_args.args[0]["prompt_version"], expected_prompt_version)
		self.assertEqual(
			{call.kwargs["prompt_version"] for call in _append.call_args_list},
			{expected_prompt_version},
		)

	@patch("myapp.services.ai_service.ai_repository.create_draft")
	@patch("myapp.services.ai_service.nowdate", return_value="2026-07-13")
	@patch("myapp.services.ai_service.ai_repository.fail_run")
	@patch("myapp.services.ai_service.ai_repository.complete_run")
	@patch("myapp.services.ai_service.ai_repository.load_model_messages")
	@patch("myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-SALES-UPDATE")
	@patch("myapp.services.ai_service.ai_repository.append_message")
	@patch("myapp.services.ai_service.ai_repository.create_conversation")
	@patch("myapp.services.ai_service._resolve_sales_draft_warehouse", return_value="Stores - TC")
	@patch("myapp.services.ai_service._resolve_sales_draft_customer", return_value=(None, []))
	@patch("myapp.services.ai_service.get_sales_order_detail")
	@patch("myapp.services.ai_service._call_ai_orchestrator_sales_draft")
	@patch("myapp.services.ai_service._resolve_company_scope", return_value="Test Company")
	def test_sales_order_update_uses_system_order_as_baseline(
		self, _company, mock_call, mock_detail, _customer, _warehouse,
		mock_conversation, _append, _run, mock_messages, _complete, _fail,
		_nowdate, mock_create_draft,
	):
		mock_conversation.return_value = {"name": "AI-CONV-SALES-UPDATE", "company": "Test Company"}
		mock_messages.return_value = [{"role": "user", "content": "修改图片里的销售订单"}]
		mock_call.return_value = {
			"draft": {
				"operation": "auto", "order_number": "SO-001",
				"source_document_type": "our_system_order", "items": [],
			},
			"model": "vision-model", "model_alias": "erp-vision",
			"trace_id": "trace-sales-update", "usage": {},
		}
		mock_detail.return_value = {"data": {
			"meta": {
				"company": "Test Company", "transaction_date": "2026-07-01",
				"delivery_date": "2026-07-05", "default_sales_mode": "retail",
				"remarks": "原销售备注",
			},
			"customer": {"name": "CUST-1", "display_name": "客户A"},
			"items": [{
				"item_code": "ITEM-1", "item_name": "相机", "qty": 2,
				"uom": "Box", "uom_display": "箱", "rate": 100,
				"warehouse": "Stores - TC", "conversion_factor": 6,
			}],
		}}
		mock_create_draft.return_value = {
			"name": "AI-DRAFT-SALES-UPDATE", "title": "修改图片里的销售订单",
			"validation": {"ready_for_handoff": True},
		}

		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.session.user = "user@example.com"
			mock_frappe.local.lang = "zh-CN"
			mock_frappe.has_permission.return_value = True
			generate_ai_sales_order_draft_v1("修改图片里的销售订单", company="Test Company")

		payload = mock_create_draft.call_args.kwargs["payload"]
		self.assertEqual(payload["operation"], "update")
		self.assertEqual(payload["order_number"], "SO-001")
		self.assertFalse(payload["update_items_explicit"])
		self.assertEqual(payload["customer"], "CUST-1")
		self.assertEqual(payload["transaction_date"], "2026-07-01")
		self.assertEqual(payload["delivery_date"], "2026-07-05")
		self.assertEqual(payload["remarks"], "原销售备注")
		self.assertEqual(payload["items"][0]["conversion_factor"], 6)
		self.assertTrue(mock_create_draft.call_args.kwargs["validation"]["ready_for_handoff"])

	def test_prompt_versions_are_mapped_by_scenario(self):
		self.assertEqual(_resolve_prompt_version("general"), "erp-readonly-v8")
		draft_versions = {
			"sales_order_draft": "sales-order-draft-v3",
			"purchase_order_draft": "purchase-order-draft-v3",
			"inventory_adjustment_draft": "inventory-adjustment-draft-v2",
			"product_setup_draft": "product-setup-draft-v6",
		}
		for scenario, expected in draft_versions.items():
			with self.subTest(scenario=scenario):
				self.assertEqual(_resolve_prompt_version(scenario), expected)
				self.assertNotEqual(expected, "erp-readonly-v8")

	@patch("myapp.services.ai_service.ai_repository.create_draft")
	@patch("myapp.services.ai_service.ai_repository.fail_run")
	@patch("myapp.services.ai_service.ai_repository.complete_run")
	@patch("myapp.services.ai_service.ai_repository.load_model_messages")
	@patch("myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-PURCHASE-DRAFT")
	@patch("myapp.services.ai_service.ai_repository.append_message")
	@patch("myapp.services.ai_service.ai_repository.create_conversation")
	@patch("myapp.services.ai_service._resolve_purchase_draft_item")
	@patch("myapp.services.ai_service._resolve_sales_draft_warehouse", return_value="Stores - TC")
	@patch("myapp.services.ai_service._resolve_purchase_draft_supplier")
	@patch("myapp.services.ai_service._call_ai_orchestrator_purchase_draft")
	@patch("myapp.services.ai_service._resolve_company_scope", return_value="Test Company")
	def test_purchase_draft_uses_purchase_prompt_version_for_request_and_audit(
		self, _company, mock_call, mock_supplier, _warehouse, mock_item,
		mock_conversation, mock_append, mock_run, mock_messages, _complete, _fail, mock_create_draft,
	):
		mock_conversation.return_value = {"name": "AI-CONV-PURCHASE", "company": "Test Company"}
		mock_messages.return_value = [{"role": "user", "content": "向供应商A采购2箱相机"}]
		mock_call.return_value = {
			"draft": {
				"supplier_query": "供应商A",
				"warehouse_query": "Stores - TC",
				"transaction_date": "2026-07-13",
				"schedule_date": "2026-07-14",
				"currency": "CNY",
				"items": [{"item_query": "相机", "qty": 2}],
			},
			"model": "structured-model", "model_alias": "erp-structured",
			"trace_id": "trace-purchase", "usage": {},
		}
		mock_supplier.return_value = (
			{"name": "SUP-1", "display_name": "供应商A"},
			[{"name": "SUP-1"}],
		)
		mock_item.return_value = {
			"item_query": "相机", "item_code": "ITEM-1", "item_name": "相机", "qty": 2,
			"uom": "Box", "uom_display": "箱", "price": 80, "warehouse": "Stores - TC",
			"conversion_factor": 1, "candidates": [], "warnings": [],
		}
		mock_create_draft.return_value = {
			"name": "AI-DRAFT-PURCHASE", "title": "向供应商A采购2箱相机",
			"validation": {"ready_for_handoff": True},
		}

		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.session.user = "user@example.com"
			mock_frappe.local.lang = "zh-CN"
			mock_frappe.has_permission.return_value = True
			generate_ai_purchase_order_draft_v1(
				"向供应商A采购2箱相机",
				company="Test Company",
			)

		expected_prompt_version = _resolve_prompt_version("purchase_order_draft")
		self.assertEqual(mock_call.call_args.args[0]["prompt_version"], expected_prompt_version)
		self.assertEqual(
			{call.kwargs["prompt_version"] for call in mock_append.call_args_list},
			{expected_prompt_version},
		)
		self.assertEqual(mock_run.call_args.kwargs["scenario"], "purchase_order_draft")
		mock_item.assert_called_once_with(
			{"item_query": "相机", "qty": 2}, company="Test Company",
			default_warehouse="Stores - TC", allow_user_price=True,
		)
		self.assertEqual(
			mock_create_draft.call_args.kwargs["payload"]["warehouse_query"],
			"Stores - TC",
		)

	@patch("myapp.services.ai_service.ai_repository.create_draft")
	@patch("myapp.services.ai_service.ai_repository.fail_run")
	@patch("myapp.services.ai_service.ai_repository.complete_run")
	@patch("myapp.services.ai_service.ai_repository.load_model_messages")
	@patch("myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-PURCHASE-UPDATE")
	@patch("myapp.services.ai_service.ai_repository.append_message")
	@patch("myapp.services.ai_service.ai_repository.create_conversation")
	@patch("myapp.services.ai_service._resolve_sales_draft_warehouse", return_value="Stores - TC")
	@patch("myapp.services.ai_service._resolve_purchase_draft_supplier", return_value=(None, []))
	@patch("myapp.services.ai_service.get_purchase_order_detail_v2")
	@patch("myapp.services.ai_service._call_ai_orchestrator_purchase_draft")
	@patch("myapp.services.ai_service._resolve_company_scope", return_value="Test Company")
	def test_purchase_order_update_uses_system_order_as_baseline(
		self, _company, mock_call, mock_detail, _supplier, _warehouse,
		mock_conversation, _append, _run, mock_messages, _complete, _fail, mock_create_draft,
	):
		mock_conversation.return_value = {"name": "AI-CONV-PURCHASE-UPDATE", "company": "Test Company"}
		mock_messages.return_value = [{"role": "user", "content": "修改图片里的采购订单"}]
		mock_call.return_value = {
			"draft": {
				"operation": "update", "order_number": "PO-001",
				"source_document_type": "our_system_order", "currency": "CNY",
				"remarks": "新采购备注", "items": [],
			},
			"model": "vision-model", "model_alias": "erp-vision",
			"trace_id": "trace-purchase-update", "usage": {},
		}
		mock_detail.return_value = {"data": {
			"meta": {
				"company": "Test Company", "transaction_date": "2026-07-02",
				"schedule_date": "2026-07-06", "supplier_ref": "REF-OLD",
				"remarks": "原采购备注",
			},
			"supplier": {"name": "SUP-1", "display_name": "供应商A"},
			"items": [{
				"item_code": "ITEM-2", "item_name": "镜头", "qty": 3,
				"uom": "Nos", "uom_display": "个", "rate": 80,
				"warehouse": "Stores - TC", "conversion_factor": 1,
			}],
		}}
		mock_create_draft.return_value = {
			"name": "AI-DRAFT-PURCHASE-UPDATE", "title": "修改图片里的采购订单",
			"validation": {"ready_for_handoff": True},
		}

		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.session.user = "user@example.com"
			mock_frappe.local.lang = "zh-CN"
			mock_frappe.has_permission.return_value = True
			generate_ai_purchase_order_draft_v1("修改图片里的采购订单", company="Test Company")

		payload = mock_create_draft.call_args.kwargs["payload"]
		self.assertEqual(payload["operation"], "update")
		self.assertEqual(payload["order_number"], "PO-001")
		self.assertFalse(payload["update_items_explicit"])
		self.assertEqual(payload["supplier"], "SUP-1")
		self.assertEqual(payload["transaction_date"], "2026-07-02")
		self.assertEqual(payload["schedule_date"], "2026-07-06")
		self.assertEqual(payload["supplier_ref"], "REF-OLD")
		self.assertEqual(payload["remarks"], "新采购备注")
		self.assertEqual(payload["items"][0]["price_source"], "existing_order")
		self.assertTrue(mock_create_draft.call_args.kwargs["validation"]["ready_for_handoff"])

	@patch("myapp.services.ai_service.ai_repository.create_draft")
	@patch("myapp.services.ai_service.ai_repository.fail_run")
	@patch("myapp.services.ai_service.ai_repository.complete_run")
	@patch("myapp.services.ai_service.ai_repository.load_model_messages")
	@patch("myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-INVENTORY-DRAFT")
	@patch("myapp.services.ai_service.ai_repository.append_message")
	@patch("myapp.services.ai_service.ai_repository.create_conversation")
	@patch("myapp.services.ai_service._build_inventory_adjustment_draft")
	@patch("myapp.services.ai_service._call_ai_orchestrator_inventory_adjustment_draft")
	@patch("myapp.services.ai_service._resolve_company_scope", return_value="Test Company")
	def test_inventory_draft_uses_inventory_prompt_version_for_request_and_audit(
		self, _company, mock_call, mock_build_draft, mock_conversation, mock_append,
		mock_run, mock_messages, _complete, _fail, mock_create_draft,
	):
		mock_conversation.return_value = {"name": "AI-CONV-INVENTORY", "company": "Test Company"}
		mock_messages.return_value = [{"role": "user", "content": "把相机库存调整到8个"}]
		mock_call.return_value = {
			"draft": {"item_query": "相机", "quantity": 8, "adjustment_type": "set_target"},
			"model": "structured-model", "model_alias": "erp-structured",
			"trace_id": "trace-inventory", "usage": {},
		}
		mock_build_draft.return_value = (
			{
				"company": "Test Company", "adjustment_type": "set_target",
				"items": [{"item_code": "ITEM-1", "target_stock_qty": 8}],
			},
			{"ready_for_handoff": True, "errors": [], "warnings": []},
		)
		mock_create_draft.return_value = {
			"name": "AI-DRAFT-INVENTORY", "title": "把相机库存调整到8个",
			"validation": {"ready_for_handoff": True},
		}

		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.session.user = "user@example.com"
			mock_frappe.local.lang = "zh-CN"
			mock_frappe.has_permission.return_value = True
			generate_ai_inventory_adjustment_draft_v1(
				"把相机库存调整到8个",
				company="Test Company",
			)

		expected_prompt_version = _resolve_prompt_version("inventory_adjustment_draft")
		self.assertEqual(mock_call.call_args.args[0]["prompt_version"], expected_prompt_version)
		self.assertEqual(
			{call.kwargs["prompt_version"] for call in mock_append.call_args_list},
			{expected_prompt_version},
		)
		self.assertEqual(mock_run.call_args.kwargs["scenario"], "inventory_adjustment_draft")

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
		self.assertTrue(dsl["limit_explicit"])

	def test_build_order_query_dsl_parses_amount_threshold(self):
		dsl = _build_order_query_dsl(
			"近7天金额超过2万的销售订单，前3条",
			company="rgc (Demo)",
		)

		self.assertEqual(dsl["entity"], "sales_order")
		self.assertEqual(dsl["date_range"], "last_7_days")
		self.assertEqual(dsl["min_amount"], 20000)
		self.assertEqual(dsl["limit"], 3)

	def test_auto_scenario_routes_document_queries_to_controlled_tools(self):
		self.assertEqual(
			_infer_ai_scenario("查询最新的5条销售订单和销售发票，以及采购订单"),
			"order_query",
		)
		self.assertEqual(_infer_ai_scenario("解释本月销售表现"), "report_summary")
		self.assertEqual(_infer_ai_scenario("帮我找蓝色包装商品"), "product_search")
		self.assertEqual(_infer_ai_scenario("我记得有个叫Camera的商品，帮我看看库存和售价"), "product_search")
		self.assertEqual(_infer_ai_scenario("商品 Camera，告诉我真实匹配"), "product_search")
		self.assertEqual(_infer_ai_scenario("你可以做什么"), "general")

	@patch("myapp.services.ai_service._get_ai_orchestrator_settings", side_effect=RuntimeError("missing token"))
	def test_structured_intent_parser_configuration_failure_uses_local_fallback(self, _settings):
		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			result = _call_ai_intent_orchestrator(
				content="仓里还剩迪莫吗",
				user="user@example.com",
				company="Demo Company",
			)

		self.assertEqual(result, {})
		mock_frappe.log_error.assert_called_once()

	@patch(
		"myapp.services.ai_service._get_ai_orchestrator_settings",
		return_value=("http://ai", "service-token"),
	)
	@patch("myapp.services.ai_service.urllib.request.urlopen")
	def test_structured_intent_parser_forwards_selected_model_alias(self, mock_urlopen, _settings):
		response = MagicMock()
		response.read.return_value = json.dumps({
			"intent": {
				"intent": "general", "confidence": 0.9, "product_query": None,
				"entities": [], "report_type": None, "date_preset": "all",
				"date_from": None, "date_to": None, "status": "all", "sort": "latest",
				"min_amount": None, "limit": 10,
			},
		}).encode("utf-8")
		mock_urlopen.return_value.__enter__.return_value = response

		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.local.lang = "zh-CN"
			result = _call_ai_intent_orchestrator(
				content="你好",
				user="user@example.com",
				company="Demo Company",
				model_alias="gpt-5.5",
			)

		request = mock_urlopen.call_args.args[0]
		payload = json.loads(request.data.decode("utf-8"))
		self.assertEqual(result["intent"], "general")
		self.assertEqual(payload["model_alias"], "gpt-5.5")
		self.assertEqual(request.full_url, "http://ai/internal/v1/intent/parse")

	def test_context_merge_inherits_order_filters_and_applies_current_status(self):
		state = {
			"active_scenario": "order_query",
			"order": {
				"entities": ["sales_order"], "date_preset": "last_month",
				"date_from": None, "date_to": None, "status": "all",
				"sort": "amount_desc", "min_amount": 20000, "limit": 5,
			},
		}
		merged = _merge_intent_with_conversation_state(
			"只看未完成的",
			{
				"intent": "order_query", "confidence": 0.96, "product_query": None,
				"entities": [], "report_type": None, "date_preset": "all",
				"date_from": None, "date_to": None, "status": "unfinished",
				"sort": "latest", "min_amount": None, "limit": 10,
			},
			state,
		)

		self.assertEqual(merged["entities"], ["sales_order"])
		self.assertEqual(merged["date_preset"], "last_month")
		self.assertEqual(merged["status"], "unfinished")
		self.assertEqual(merged["sort"], "amount_desc")
		self.assertEqual(merged["min_amount"], 20000)
		self.assertEqual(merged["limit"], 5)

	def test_context_merge_resolves_product_pronoun_from_unique_state(self):
		merged = _merge_intent_with_conversation_state(
			"那它的售价呢",
			{
				"intent": "product_search", "confidence": 0.93, "product_query": None,
				"entities": [], "report_type": None, "date_preset": "all",
				"date_from": None, "date_to": None, "status": "all", "sort": "latest",
				"min_amount": None, "limit": 10,
			},
			{
				"active_scenario": "product_search",
				"product": {"query": "SKU010", "item_code": "SKU010", "resolution_status": "resolved"},
			},
		)

		self.assertEqual(merged["product_query"], "SKU010")

	def test_next_conversation_state_keeps_only_compact_product_and_result_references(self):
		state = _build_next_conversation_state(
			previous_state={"active_scenario": "general"},
			scenario="product_search",
			structured_intent={"product_query": "Camera"},
			tool_context={
				"tool": "search_products", "query": "查询 Camera 的库存", "company": "Demo Company",
				"resolved_product": {"item_code": "SKU010", "item_name": "Camera"},
				"retrieval": {"status": "resolved"},
				"products": [{"item_code": "SKU010", "item_name": "Camera", "price": 999, "qty": 4}],
			},
			citations=[],
		)

		self.assertEqual(state["product"]["item_code"], "SKU010")
		self.assertEqual(state["last_result_set"]["entity_ids"], ["SKU010"])
		self.assertNotIn("price", state["product"])
		self.assertNotIn("qty", state["product"])

	@patch("myapp.services.ai_service.ai_repository.complete_run")
	@patch("myapp.services.ai_service.ai_repository.update_conversation_state")
	@patch("myapp.services.ai_service.ai_repository.append_message")
	def test_complete_run_audits_state_version_conflict_without_failing_answer(
		self, _append, mock_update_state, mock_complete,
	):
		mock_update_state.return_value = {"updated": False, "version": 4, "reason": "version_conflict"}
		prepared = {
			"started": 0, "conversation_id": "AI-CONV-1", "user": "user@example.com",
			"scenario": "order_query", "run_id": "AI-RUN-1", "citations": [],
			"prompt_version": "erp-readonly-v8", "tool_calls": [],
			"conversation_state_version": 3,
			"next_conversation_state": {"active_scenario": "order_query"},
		}
		with patch("myapp.services.ai_service.time.perf_counter", return_value=0), patch(
			"myapp.services.ai_service.frappe",
		):
			_complete_chat_run(prepared, {"usage": {}}, "已完成")

		self.assertEqual(prepared["tool_calls"][-1]["mode"], "state_update_skipped")
		mock_complete.assert_called_once()

	@patch("myapp.services.ai_service.ai_repository.revoke_agent_capability")
	@patch("myapp.services.ai_service.ai_repository.complete_run")
	@patch("myapp.services.ai_service.ai_repository.update_conversation_state")
	@patch("myapp.services.ai_service.ai_repository.append_message")
	def test_complete_run_retries_whole_transaction_after_agent_callback_write_conflict(
		self, mock_append, mock_update_state, mock_complete, mock_revoke,
	):
		mock_update_state.return_value = {"updated": True, "version": 4}
		mock_complete.side_effect = [QueryDeadlockError("concurrent Agent callback"), None]
		prepared = {
			"started": 0, "conversation_id": "AI-CONV-1", "user": "user@example.com",
			"scenario": "general", "run_id": "AI-RUN-1", "citations": [],
			"prompt_version": "erp-readonly-v8", "tool_calls": [],
			"conversation_state_version": 3,
			"next_conversation_state": {"active_scenario": "general"},
			"agent_mode": True,
		}
		with patch("myapp.services.ai_service.time.perf_counter", return_value=0), patch(
			"myapp.services.ai_service.frappe",
		) as mock_frappe:
			_complete_chat_run(prepared, {"usage": {}}, "已完成")

		self.assertEqual(mock_append.call_count, 2)
		self.assertEqual(mock_update_state.call_count, 2)
		self.assertEqual(mock_complete.call_count, 2)
		mock_frappe.db.rollback.assert_called_once()
		mock_frappe.db.commit.assert_called_once()
		mock_revoke.assert_called_once_with(run_id="AI-RUN-1", user="user@example.com")
		self.assertEqual(
			[call["tool"] for call in prepared["tool_calls"]],
			["update_conversation_state"],
		)

	@patch("myapp.services.ai_service.urllib.request.urlopen")
	def test_sync_agent_call_preserves_checkpoint_failure_code(self, mock_urlopen):
		body = json.dumps({
			"detail": {
				"code": "AI_AGENT_CHECKPOINT_UNAVAILABLE",
				"message": "Agent 运行检查点暂时无法持久化。",
			},
		}).encode()
		mock_urlopen.side_effect = urllib.error.HTTPError(
			"http://ai-orchestrator/internal/v1/agent/run", 422,
			"Unprocessable Entity", {}, io.BytesIO(body),
		)
		with patch.dict(os.environ, {"MYAPP_AI_SERVICE_TOKEN": "x" * 40}), patch(
			"myapp.services.ai_service.frappe.log_error",
		):
			with self.assertRaises(AiServiceError) as raised:
				_call_ai_orchestrator({"capability_token": "y" * 40})

		self.assertEqual(raised.exception.code, "AI_AGENT_CHECKPOINT_UNAVAILABLE")
		self.assertEqual(raised.exception.http_status, 422)

	def test_order_dsl_understands_negative_status_recent_month_and_chinese_count(self):
		dsl = _build_order_query_dsl(
			"最近一个月还没完成的销售订单，按金额最高列前三张",
			company="rgc (Demo)",
			as_of=date(2026, 7, 26),
		)

		self.assertEqual(dsl["date_range"], "last_30_days")
		self.assertEqual(dsl["status_filter"], "unfinished")
		self.assertEqual(dsl["sort_by"], "amount_desc")
		self.assertEqual(dsl["limit"], 3)

	def test_order_dsl_applies_structured_entities_amount_and_custom_dates(self):
		dsl = _build_order_query_dsl(
			"帮我看看这些业务单据",
			company="rgc (Demo)",
			structured_intent={
				"intent": "order_query", "confidence": 0.97,
				"entities": ["purchase_invoice", "purchase_order"],
				"date_preset": "custom", "date_from": "2026-07-01", "date_to": "2026-07-20",
				"min_amount": 20000, "status": "all", "sort": "amount_desc", "limit": 5,
			},
		)

		self.assertEqual(dsl["entities"], ["purchase_order", "purchase_invoice"])
		self.assertEqual(dsl["date_range"], "custom")
		self.assertEqual(dsl["date_from"], "2026-07-01")
		self.assertEqual(dsl["date_to"], "2026-07-20")
		self.assertEqual(dsl["min_amount"], 20000)

	def test_order_dsl_ignores_invalid_structured_custom_dates(self):
		dsl = _build_order_query_dsl(
			"查询最新销售订单",
			company="rgc (Demo)",
			structured_intent={
				"intent": "order_query", "confidence": 0.97,
				"date_preset": "custom", "date_from": "2026-07-20", "date_to": "2026-07-01",
			},
		)

		self.assertEqual(dsl["date_range"], "all")
		self.assertIsNone(dsl["date_from"])

	def test_order_dsl_applies_valid_high_confidence_structured_filters(self):
		dsl = _build_order_query_dsl(
			"帮我处理一下这些单据",
			company="rgc (Demo)",
			as_of=date(2026, 7, 26),
			structured_intent={
				"intent": "order_query", "confidence": 0.96,
				"date_preset": "last_30_days", "status": "unfinished",
				"sort": "amount_desc", "limit": 3,
			},
		)

		self.assertEqual(dsl["date_from"], "2026-06-27")
		self.assertEqual(dsl["date_to"], "2026-07-26")
		self.assertEqual(dsl["status_filter"], "unfinished")
		self.assertEqual(dsl["sort_by"], "amount_desc")
		self.assertEqual(dsl["limit"], 3)

	def test_report_dsl_applies_structured_date_without_changing_report_type(self):
		dsl = _build_report_query_dsl(
			"看看销售表现",
			company="rgc (Demo)",
			as_of=date(2026, 7, 26),
			structured_intent={
				"intent": "report_summary", "confidence": 0.9, "date_preset": "last_30_days",
			},
		)

		self.assertEqual(dsl["report_type"], "sales")
		self.assertEqual(dsl["date_range"], "last_30_days")

	def test_report_dsl_applies_structured_report_type_when_local_text_is_ambiguous(self):
		dsl = _build_report_query_dsl(
			"帮我看一下这段经营数据",
			company="rgc (Demo)",
			structured_intent={
				"intent": "report_summary", "confidence": 0.94,
				"report_type": "cashflow", "date_preset": "all",
			},
		)

		self.assertEqual(dsl["report_type"], "cashflow")

	def test_action_scenario_routes_product_creation_to_draft(self):
		self.assertEqual(
			_infer_ai_action_scenario("添加一个新的商品叫做传承结晶，1000个，售价9999元每个"),
			"product_setup_draft",
		)
		self.assertEqual(
			_infer_ai_action_scenario("添加一个新商品，煌星，10000一个，入库5000个"),
			"product_setup_draft",
		)
		self.assertEqual(
			_infer_ai_action_scenario("查询并添加一个新商品，名字叫煌星"),
			"product_setup_draft",
		)
		self.assertEqual(
			_infer_ai_action_scenario("查询最新销售订单"),
			"order_query",
		)
		self.assertEqual(
			_infer_ai_action_scenario("给迪莫添加10个库存"),
			"inventory_adjustment_draft",
		)
		self.assertEqual(
			_infer_ai_action_scenario("完善迪莫商品资料"),
			"product_setup_draft",
		)
		self.assertEqual(
			_infer_ai_action_scenario("更新迪莫商品库存"),
			"inventory_adjustment_draft",
		)

	def test_auto_scenario_routes_product_stock_status_queries_to_product_search(self):
		self.assertEqual(
			_infer_ai_action_scenario("查询一下煌星是否已经正常入库"),
			"product_search",
		)
		self.assertEqual(
			_infer_ai_action_scenario("煌星现在有现货吗"),
			"product_search",
		)
		self.assertEqual(_extract_product_search_terms("查询一下煌星是否已经正常入库"), ["煌星"])
		self.assertEqual(_extract_product_search_terms("查询迪莫商品是否已正常入库"), ["迪莫"])
		self.assertEqual(_extract_product_search_terms("煌星现在有现货吗"), ["煌星"])

	@patch("myapp.services.ai_service._resolve_sales_draft_warehouse", return_value="Stores - TC")
	@patch("myapp.services.ai_service._resolve_optional_master_name", return_value=None)
	@patch("myapp.services.ai_service._resolve_product_setup_uom", return_value=("Unit", [{"name": "Unit"}]))
	@patch("myapp.services.ai_service._resolve_existing_product_for_setup", return_value=(None, []))
	def test_product_setup_draft_keeps_selling_price_separate_from_default_buying_price(
		self, _existing, _uom, _master, _warehouse,
	):
		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.db.exists.return_value = False
			mock_frappe.db.get_value.return_value = "CNY"
			payload, validation = _build_product_setup_draft(
				{
					"item_name": "传承结晶", "opening_qty": 1000,
					"opening_uom": "个", "standard_selling_rate": 9999,
				},
				company="Test Company",
			)

		self.assertEqual(payload["standard_selling_rate"], 9999)
		self.assertIsNone(payload["standard_buying_rate"])
		self.assertFalse(validation["ready_for_handoff"])
		self.assertTrue(any("默认采购价" in error for error in validation["errors"]))

	@patch("myapp.services.ai_service._resolve_sales_draft_warehouse", return_value="Stores - TC")
	@patch("myapp.services.ai_service._resolve_optional_master_name", return_value=None)
	@patch("myapp.services.ai_service._resolve_product_setup_uom", return_value=("Unit", [{"name": "Unit"}]))
	@patch("myapp.services.ai_service._resolve_existing_product_for_setup", return_value=(None, []))
	def test_product_setup_draft_accepts_default_buying_price_for_opening_stock(
		self, _existing, _uom, _master, _warehouse,
	):
		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.db.exists.return_value = False
			mock_frappe.db.get_value.return_value = "CNY"
			mock_frappe.has_permission.return_value = True
			payload, validation = _build_product_setup_draft(
				{
					"item_name": "传承结晶", "opening_qty": 1000,
					"stock_uom": "Unit", "standard_selling_rate": 9999,
					"wholesale_rate": 8800, "retail_rate": 10800,
					"standard_buying_rate": 5000, "warehouse": "Stores - TC",
				},
				company="Test Company",
			)

		self.assertEqual(payload["standard_buying_rate"], 5000)
		self.assertEqual(payload["wholesale_rate"], 8800)
		self.assertEqual(payload["retail_rate"], 10800)
		self.assertTrue(validation["ready_for_handoff"])

	@patch("myapp.services.ai_service._resolve_existing_product_for_setup")
	@patch("myapp.services.ai_service._resolve_sales_draft_warehouse", return_value=None)
	@patch("myapp.services.ai_service._resolve_optional_master_name", return_value=None)
	@patch("myapp.services.ai_service._resolve_product_setup_uom", return_value=("Unit", [{"name": "Unit"}]))
	def test_product_setup_auto_hydrates_existing_product_without_turning_stock_into_opening_stock(
		self, _uom, _master, _warehouse, mock_existing,
	):
		mock_existing.return_value = ({
			"item_code": "ITEM-DIMO",
			"item_name": "迪莫",
			"item_group": "Products",
			"brand": None,
			"stock_uom": "Unit",
			"stock_uom_display": "个",
			"description": None,
			"image": "/files/dimo.png",
			"standard_rate": 0,
			"total_qty": 1000,
			"warehouse_stock_details": [{"warehouse": "Stores - TC", "qty": 1000}],
			"modified": "2026-07-31 10:00:00",
			"price_summary": {
				"selling_prices": [
					{"price_list": "Standard Selling", "rate": 5, "currency": "CNY"},
					{"price_list": "Wholesale", "rate": 3, "currency": "CNY"},
				],
				"buying_prices": [],
			},
		}, [{"name": "ITEM-DIMO"}])
		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.db.get_value.return_value = "CNY"
			mock_frappe.has_permission.return_value = True
			payload, validation = _build_product_setup_draft(
				{"operation": "auto", "item_name": "迪莫", "description": "补充说明"},
				company="Test Company",
			)

		self.assertEqual(payload["operation"], "update")
		self.assertEqual(payload["standard_selling_rate"], 5)
		self.assertEqual(payload["wholesale_rate"], 3)
		self.assertEqual(payload["image"], "/files/dimo.png")
		self.assertIsNone(payload["opening_qty"])
		self.assertEqual(payload["_state"]["context"]["company_total_qty"], 1000)
		self.assertEqual(payload["_state"]["patch"], {"description": "补充说明"})
		self.assertFalse(validation["ready_for_handoff"])
		self.assertTrue(payload["operation_decision_required"])
		self.assertEqual(payload["duplicate_candidates"][0]["item_code"], "ITEM-DIMO")
		self.assertTrue(any("明确选择" in error for error in validation["errors"]))

	@patch("myapp.services.ai_service._resolve_existing_product_for_setup")
	@patch("myapp.services.ai_service._resolve_sales_draft_warehouse", return_value=None)
	@patch("myapp.services.ai_service._resolve_optional_master_name", side_effect=lambda _doctype, value: value)
	@patch("myapp.services.ai_service._resolve_product_setup_uom", return_value=("Unit", [{"name": "Unit"}]))
	def test_switching_photo_create_draft_to_update_does_not_replace_existing_image(
		self, _uom, _master, _warehouse, mock_existing,
	):
		existing = {
			"item_code": "ITEM-EXISTING", "item_name": "已有商品", "item_group": "Products",
			"brand": None, "stock_uom": "Unit", "stock_uom_display": "个",
			"description": None, "image": "/files/existing.png", "modified": "2026-08-14 10:00:00",
			"standard_rate": 0, "total_qty": 0, "warehouse_stock_details": [],
			"price_summary": {"selling_prices": [], "buying_prices": []},
		}
		mock_existing.side_effect = [(None, []), (existing, [{"name": "ITEM-EXISTING"}])]
		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.db.get_value.return_value = "CNY"
			mock_frappe.db.exists.return_value = False
			mock_frappe.has_permission.return_value = True
			created, _ = _build_product_setup_draft(
				{"operation": "create", "item_name": "照片商品", "stock_uom": "Unit"},
				company="Test Company",
				default_image_url="/files/from-photo.webp",
				source_attachments=[{"attachment_id": "AI-ATT-1"}],
			)
			updated, _ = _build_product_setup_draft(
				{
					**created,
					"operation": "update",
					"item_code": "ITEM-EXISTING",
					"item_name": "已有商品",
				},
				company="Test Company",
				source_attachments=created["source_attachments"],
			)

		self.assertEqual(created["image"], "/files/from-photo.webp")
		self.assertEqual(updated["image"], "/files/existing.png")
		self.assertNotIn("image", updated["_state"]["patch"])

	@patch("myapp.services.ai_service._resolve_existing_product_for_setup")
	@patch("myapp.services.ai_service._resolve_sales_draft_warehouse", return_value=None)
	@patch("myapp.services.ai_service._resolve_optional_master_name", side_effect=lambda _doctype, value: value)
	@patch("myapp.services.ai_service._resolve_product_setup_uom", return_value=("Unit", [{"name": "Unit"}]))
	def test_explicit_photo_update_replaces_existing_image_in_patch(
		self, _uom, _master, _warehouse, mock_existing,
	):
		mock_existing.return_value = ({
			"item_code": "ITEM-EXISTING", "item_name": "已有商品", "item_group": "Products",
			"brand": None, "stock_uom": "Unit", "stock_uom_display": "个",
			"description": None, "image": "/files/existing.png", "modified": "2026-08-14 10:00:00",
			"standard_rate": 0, "total_qty": 0, "warehouse_stock_details": [],
			"price_summary": {"selling_prices": [], "buying_prices": []},
		}, [{"name": "ITEM-EXISTING"}])
		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.db.get_value.return_value = "CNY"
			mock_frappe.has_permission.return_value = True
			payload, validation = _build_product_setup_draft(
				{
					"operation": "update", "item_code": "ITEM-EXISTING",
					"item_name": "已有商品", "image": "/files/from-history.webp",
				},
				company="Test Company",
				source_attachments=[{"attachment_id": "AI-ATT-HISTORY"}],
			)

		self.assertEqual(payload["image"], "/files/from-history.webp")
		self.assertEqual(payload["_state"]["patch"]["image"], "/files/from-history.webp")
		self.assertEqual(payload["source_attachments"][0]["attachment_id"], "AI-ATT-HISTORY")
		self.assertTrue(validation["ready_for_handoff"])

	def test_build_order_query_dsl_supports_multiple_document_types(self):
		dsl = _build_order_query_dsl(
			"查询最新的5条销售订单和销售发票，以及采购订单",
			company="rgc (Demo)",
		)

		self.assertEqual(
			dsl["entities"],
			["sales_order", "sales_invoice", "purchase_order"],
		)
		self.assertEqual(dsl["date_range"], "all")
		self.assertIsNone(dsl["date_from"])
		self.assertIsNone(dsl["date_to"])
		self.assertEqual(dsl["limit"], 5)
		self.assertTrue(dsl["limit_explicit"])

	def test_build_order_query_dsl_does_not_report_default_limit_as_user_request(self):
		dsl = _build_order_query_dsl(
			"查询最新销售订单",
			company="rgc (Demo)",
		)

		self.assertEqual(dsl["limit"], 10)
		self.assertFalse(dsl["limit_explicit"])

	@patch("myapp.services.ai_service._query_business_document_entity")
	@patch("myapp.services.ai_service._resolve_company_scope", return_value="rgc (Demo)")
	def test_build_order_query_context_groups_mixed_documents(self, _company, mock_query):
		mock_query.side_effect = [
			([{"document_type": "sales_order", "name": "SO-1", "party": "客户A"}], {"visible_count": 4}),
			([{"document_type": "sales_invoice", "name": "SI-1", "party": "客户A"}], {"total": 1}),
			([{"document_type": "purchase_order", "name": "PO-1", "party": "供应商A"}], {"visible_count": 1}),
		]

		with patch("myapp.services.ai_service.now_datetime", return_value="2026-07-24 11:30:00"):
			context, citations, tool_calls = _build_order_query_context(
				query="查询最新的5条销售订单和销售发票，以及采购订单",
				company="rgc (Demo)",
			)

		self.assertEqual([group["entity"] for group in context["document_groups"]], [
			"sales_order", "sales_invoice", "purchase_order",
		])
		self.assertTrue(all("items" not in group for group in context["document_groups"]))
		self.assertNotIn("documents", context)
		self.assertNotIn("orders", context)
		self.assertEqual([citation["type"] for citation in citations], [
			"business_result_set", "sales_order", "sales_invoice", "purchase_order",
		])
		self.assertEqual(citations[0]["data"]["schema_version"], "business-result-set-v1")
		self.assertEqual(citations[0]["data"]["status_semantics"], "result_coverage_only")
		self.assertTrue(citations[0]["data"]["queried_at"])
		self.assertTrue(citations[0]["data"]["permission_filtered"])
		self.assertEqual(citations[0]["data"]["scope"]["limit_per_group"], 5)
		self.assertEqual(
			[group["status"] for group in citations[0]["data"]["groups"]],
			["partial", "partial", "partial"],
		)
		self.assertEqual(citations[0]["data"]["groups"][0]["available_count"], 4)
		self.assertTrue(citations[0]["data"]["groups"][0]["truncated"])
		self.assertIsNone(citations[0]["data"]["groups"][1]["available_count"])
		self.assertIsNone(citations[0]["data"]["groups"][1]["truncated"])
		self.assertEqual(citations[0]["data"]["groups"][2]["module_href"], "/purchase/orders")
		self.assertEqual([call["tool"] for call in tool_calls], [
			"search_sales_orders", "list_sales_invoices", "search_purchase_orders",
		])

	@patch("myapp.services.ai_service._resolve_company_scope", return_value="rgc (Demo)")
	def test_normalize_business_result_refresh_reuses_snapshot_scope(self, _company):
		dsl = _normalize_ai_business_result_refresh({
			"result_type": "business_documents",
			"scope": {
				"company": "rgc (Demo)", "date_range": "this_month",
				"date_from": "2026-07-01", "date_to": "2026-07-24",
				"status_filter": "unfinished", "sort_by": "amount_desc",
				"min_amount": 1000, "limit_per_group": 5,
			},
			"groups": [
				{"entity": "sales_order", "requested_count": 5},
				{"entity": "purchase_order", "requested_count": 5},
			],
		})

		self.assertEqual(dsl["entities"], ["sales_order", "purchase_order"])
		self.assertEqual(dsl["company"], "rgc (Demo)")
		self.assertEqual(dsl["status_filter"], "unfinished")
		self.assertEqual(dsl["sort_by"], "amount_desc")
		self.assertEqual(dsl["limit"], 5)
		self.assertTrue(dsl["limit_explicit"])

	@patch("myapp.services.ai_service._build_order_query_result")
	@patch("myapp.services.ai_service._normalize_ai_business_result_refresh")
	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	def test_refresh_business_result_is_read_only_and_does_not_call_model(
		self, _user, mock_normalize, mock_build,
	):
		mock_normalize.return_value = {"entities": ["sales_order"], "company": "rgc (Demo)"}
		mock_build.return_value = (
			{"result_type": "business_documents", "queried_at": "2026-07-24 11:30:00"},
			[{"type": "business_result_set", "data": {}}],
			[{"tool": "search_sales_orders"}],
		)

		result = refresh_ai_business_result_v1({"result_type": "business_documents"})

		self.assertEqual(result["data"]["result_set"]["queried_at"], "2026-07-24 11:30:00")
		self.assertEqual(result["data"]["citations"][0]["type"], "business_result_set")
		mock_build.assert_called_once_with(
			dsl=mock_normalize.return_value,
			snapshot_source="refresh",
		)

	@patch("myapp.services.ai_service.list_business_documents_v1")
	@patch("myapp.services.ai_service.frappe")
	def test_query_business_document_entity_normalizes_sales_invoice(self, mock_frappe, mock_list):
		mock_frappe.has_permission.return_value = True
		mock_frappe.get_list.return_value = ["SI-1"]
		mock_list.return_value = {
			"data": {
				"items": [{
					"name": "SI-1", "party_name": "客户A", "company": "rgc (Demo)",
					"posting_date": "2026-07-17", "due_date": "2026-07-20",
					"business_status": "Unpaid", "docstatus": 1, "amount": 1200,
					"outstanding_amount": 1200, "paid_amount": 0,
				}],
				"summary": {"total_count": 1},
			},
		}
		dsl = {
			"company": "rgc (Demo)", "date_from": None, "date_to": None,
			"status_filter": "all", "exclude_cancelled": True,
			"sort_by": "latest", "min_amount": None, "limit": 5,
		}

		items, summary = _query_business_document_entity(entity="sales_invoice", dsl=dsl)

		self.assertEqual(items[0]["document_type"], "sales_invoice")
		self.assertEqual(items[0]["transaction_date"], "2026-07-17")
		self.assertEqual(items[0]["outstanding_amount"], 1200)
		self.assertEqual(summary["total_count"], 1)

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
		self.assertEqual(_extract_product_search_terms("商品迪莫"), ["迪莫"])
		self.assertEqual(_extract_product_search_terms("迪莫商品"), ["迪莫"])

	def test_product_entity_normalization_handles_full_width_and_whitespace(self):
		self.assertEqual(_normalize_product_entity_text(" 商品：Ｃａｍｅｒａ  "), "商品:camera")

	@patch("myapp.services.ai_service.search_products_semantic")
	@patch("myapp.services.ai_service.search_product_v2")
	def test_shared_item_resolver_prefers_exact_match_without_semantic_dependency(
		self, mock_search, mock_semantic,
	):
		mock_search.return_value = {"data": [{"item_code": "SKU-1", "item_name": "Camera", "barcode": "69001"}]}
		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.get_list.return_value = ["SKU-1"]
			result = _resolve_item_candidates("商品：Camera", company="Demo Company")

		self.assertEqual(result["status"], "resolved")
		self.assertEqual(result["match_method"], "exact")
		self.assertEqual(result["selected"]["item_code"], "SKU-1")
		mock_semantic.assert_not_called()

	@patch("myapp.services.ai_service.search_products_semantic")
	@patch("myapp.services.ai_service.search_product_v2")
	def test_structured_product_query_searches_the_model_extracted_substring(
		self, mock_search, mock_semantic,
	):
		mock_search.return_value = {
			"data": [{"item_code": "ITEM-DIMO", "item_name": "迪莫", "nickname": "迪莫"}],
		}
		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.get_list.return_value = ["ITEM-DIMO"]
			result = _resolve_item_candidates(
				"查询一下有没有带莫字的商品",
				company="Demo Company",
				entity_query="莫",
			)

		self.assertEqual(result["search_terms"], ["莫"])
		self.assertEqual(result["candidates"][0]["item_name"], "迪莫")
		self.assertEqual(mock_search.call_args.kwargs["search_key"], "莫")
		mock_semantic.assert_not_called()

	@patch("myapp.services.ai_service.search_products_semantic", return_value={"available": True, "rows": []})
	@patch("myapp.services.ai_service.search_product_v2", return_value={"data": []})
	def test_shared_item_resolver_reports_not_found_and_semantic_availability(
		self, _mock_search, mock_semantic,
	):
		with patch("myapp.services.ai_service.frappe"):
			result = _resolve_item_candidates("适合拍照的相机", company="Demo Company")

		self.assertEqual(result["status"], "not_found")
		self.assertTrue(result["semantic_available"])
		mock_semantic.assert_called_once()

	@patch("myapp.services.ai_service.search_products_semantic", return_value={"available": False, "rows": []})
	@patch("myapp.services.ai_service.search_product_v2")
	def test_shared_item_resolver_keeps_duplicate_names_ambiguous(self, mock_search, _mock_semantic):
		mock_search.return_value = {"data": [
			{"item_code": "SKU-1", "item_name": "相同名称"},
			{"item_code": "SKU-2", "item_name": "相同名称"},
		]}
		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.get_list.return_value = ["SKU-1", "SKU-2"]
			result = _resolve_item_candidates("相同名称", company="Demo Company")

		self.assertEqual(result["status"], "ambiguous")
		self.assertIsNone(result["selected"])
		self.assertEqual(len(result["candidates"]), 2)

	def test_hybrid_product_rerank_merges_lexical_and_semantic_candidates(self):
		rows = _hybrid_rerank_product_rows(
			query="适合聚会整箱卖的蓝色饮料",
			lexical_rows=[{"item_code": "ITEM-001", "item_name": "蓝色饮料"}],
			semantic_rows=[
				{"item_code": "ITEM-002", "item_name": "派对分享装汽水", "semantic_score": 0.94},
				{"item_code": "ITEM-001", "item_name": "蓝色饮料", "semantic_score": 0.82},
			],
			limit=8,
		)

		self.assertEqual(rows[0]["item_code"], "ITEM-001")
		self.assertEqual(rows[0]["match_source"], "lexical+semantic")
		self.assertEqual(rows[1]["match_reason"], "语义相似匹配")

	def test_upstream_service_errors_map_to_retryable_http_status(self):
		self.assertEqual(
			map_exception_to_error(UpstreamServiceUnavailableError("temporarily unavailable")),
			("UPSTREAM_SERVICE_UNAVAILABLE", 503),
		)

	def test_ai_draft_version_conflicts_map_to_conflict_http_status(self):
		self.assertEqual(
			map_exception_to_error(AiDraftVersionConflictError("stale draft")),
			("AI_DRAFT_VERSION_CONFLICT", 409),
		)

	def test_ai_service_errors_preserve_stable_code_and_http_status(self):
		self.assertEqual(
			map_exception_to_error(
				AiServiceError("rate limited", code="AI_REQUEST_RATE_LIMITED", http_status=429)
			),
			("AI_REQUEST_RATE_LIMITED", 429),
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
			"can_view_advanced_diagnostics": True,
			"scenario": "general",
			"conversation_id": "AI-CONV-1",
			"run_id": "AI-RUN-1",
			"started": 1,
			"citations": [],
			"tool_calls": [],
			"warnings": ["兼容查询模式"],
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
		mock_complete.return_value = {
			"status": "completed", "latency_ms": 900, "first_token_ms": 120,
		}

		response = stream_ai_message_v1(content="你好")
		body = b"".join(response.iter_encoded()).decode()

		self.assertEqual(response.content_type, "text/event-stream; charset=utf-8")
		self.assertIn('"type":"run_started"', body)
		self.assertIn('"type":"run_progress"', body)
		self.assertIn('"phase":"model_started"', body)
		self.assertIn('"phase":"streaming"', body)
		self.assertIn('"delta":"你"', body)
		self.assertIn('"type":"completed"', body)
		self.assertIn('"latency_ms":900', body)
		self.assertIn('"first_token_ms":120', body)
		self.assertIn('"delta_count":2', body)
		self.assertIn('"streamed_chars":2', body)
		self.assertIn('"model_alias":"opencode-deepseek-v4-flash"', body)
		self.assertIn('"type":"warning","message":"兼容查询模式"', body)
		self.assertIn('"warnings":["兼容查询模式"]', body)
		mock_complete.assert_called_once()
		self.assertEqual(mock_complete.call_args.args[2], "你好")
		self.assertEqual(mock_complete.call_args.args[1]["warnings"], ["兼容查询模式"])
		self.assertGreaterEqual(mock_complete.call_args.kwargs["first_token_ms"], 0)

	@patch("myapp.services.ai_service._complete_chat_run")
	@patch("myapp.services.ai_service._stream_ai_orchestrator")
	@patch("myapp.services.ai_service._prepare_chat_run")
	def test_stream_ai_message_v1_redacts_advanced_diagnostics_for_business_user(
		self, mock_prepare, mock_stream, mock_complete,
	):
		mock_prepare.return_value = {
			"user": "user@example.com",
			"can_view_advanced_diagnostics": False,
			"scenario": "general",
			"conversation_id": "AI-CONV-1",
			"run_id": "AI-RUN-1",
			"started": 1,
			"citations": [],
			"tool_calls": [],
			"payload": {"messages": [{"role": "user", "content": "你好"}]},
		}
		mock_stream.return_value = iter([
			{"type": "started", "model_alias": "internal-alias"},
			{"type": "message_delta", "delta": "你好"},
			{
				"type": "completed",
				"message": {"role": "assistant", "content": "你好"},
				"model": "provider-model", "model_alias": "internal-alias",
				"trace_id": "trace-secret", "usage": {"total_tokens": 10},
				"warnings": [],
			},
		])
		mock_complete.return_value = {
			"status": "completed", "latency_ms": 900, "first_token_ms": 120,
		}

		response = stream_ai_message_v1(content="你好")
		body = b"".join(response.iter_encoded()).decode()

		self.assertIn('"type":"completed"', body)
		self.assertIn('"latency_ms":900', body)
		self.assertNotIn("internal-alias", body)
		self.assertNotIn("provider-model", body)
		self.assertNotIn("trace-secret", body)
		self.assertNotIn('"total_tokens":10', body)
		self.assertNotIn('"first_token_ms":120', body)

	@patch("myapp.services.ai_service._fail_chat_run")
	@patch("myapp.services.ai_service._stream_ai_orchestrator")
	@patch("myapp.services.ai_service._prepare_chat_run")
	def test_stream_ai_message_v1_preserves_stable_failure_code(
		self, mock_prepare, mock_stream, mock_fail,
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
		mock_stream.return_value = iter([
			{
				"type": "error",
				"code": "AI_REQUEST_RATE_LIMITED",
				"message": "AI 请求过于频繁，请稍后重试。",
			},
		])

		response = stream_ai_message_v1(content="你好")
		body = b"".join(response.iter_encoded()).decode()

		self.assertIn('"type":"error"', body)
		self.assertIn('"code":"AI_REQUEST_RATE_LIMITED"', body)
		self.assertIsInstance(mock_fail.call_args.args[1], AiServiceError)
		self.assertEqual(mock_fail.call_args.args[1].code, "AI_REQUEST_RATE_LIMITED")

	@patch("myapp.services.ai_service._prepare_agent_resume")
	@patch("myapp.services.ai_service._complete_chat_run", return_value={"status": "completed"})
	@patch("myapp.services.ai_service._call_ai_orchestrator")
	def test_resume_ai_run_uses_resume_orchestrator_endpoint(
		self, mock_call, mock_complete, mock_prepare,
	):
		prepared = {
			"payload": {"run_id": "AI-RUN-1", "capability_token": "token"},
			"conversation_id": "AI-CONV-1", "run_id": "AI-RUN-1", "user": "user@example.com",
			"started": 1.0, "citations": [], "tool_calls": [],
			"can_view_advanced_diagnostics": False,
		}
		mock_prepare.return_value = prepared
		mock_call.return_value = {"message": {"content": "恢复完成。"}, "warnings": []}

		result = resume_ai_run_v1("AI-RUN-1")

		self.assertTrue(result["data"]["resumed"])
		mock_call.assert_called_once_with(prepared["payload"], resume=True)
		mock_complete.assert_called_once()

	@patch("myapp.services.ai_service._prepare_agent_resume")
	@patch("myapp.services.ai_service._stream_prepared_ai_run", return_value="stream-response")
	def test_stream_agent_resume_uses_same_run_preparation(self, mock_stream, mock_prepare):
		prepared = {"run_id": "AI-RUN-1"}
		mock_prepare.return_value = prepared

		result = stream_ai_run_resume_v1("AI-RUN-1")

		self.assertEqual(result, "stream-response")
		mock_stream.assert_called_once_with(prepared, resume=True)

	@patch("myapp.services.ai_service.ai_repository.complete_run")
	@patch("myapp.services.ai_service.ai_repository.load_model_messages")
	@patch("myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-1")
	@patch("myapp.services.ai_service.ai_repository.append_message")
	@patch("myapp.services.ai_service.ai_repository.create_conversation")
	@patch("myapp.services.ai_service._call_ai_orchestrator")
	@patch("myapp.services.ai_service._resolve_company_scope", return_value="rgc (Demo)")
	@patch(
		"myapp.services.ai_service.resolve_ai_selected_model_alias",
		return_value="opencode-glm-5.2",
	)
	def test_chat_ai_v1_persists_conversation_run_and_messages(
		self,
		mock_selected_model,
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
			result = chat_ai_v1(
				content="  你好  ", scenario="general", company="rgc (Demo)",
				model_alias="opencode-glm-5.2",
			)

		self.assertEqual(result["data"]["conversation"], "AI-CONV-1")
		self.assertEqual(result["data"]["run_id"], "AI-RUN-1")
		self.assertEqual(result["data"]["message"]["content"], "你好")
		self.assertEqual(result["data"]["run"]["status"], "completed")
		self.assertGreaterEqual(result["data"]["run"]["latency_ms"], 0)
		self.assertNotIn("model", result["data"])
		self.assertNotIn("model_alias", result["data"])
		self.assertNotIn("trace_id", result["data"])
		self.assertNotIn("usage", result["data"])
		self.assertEqual(result["data"]["events"][-1], {"type": "completed"})
		self.assertEqual(mock_append_message.call_count, 2)
		mock_complete_run.assert_called_once()
		payload = mock_call.call_args.args[0]
		self.assertEqual(payload["messages"], [{"role": "user", "content": "你好"}])
		self.assertIsNone(payload["context"])
		self.assertEqual(payload["conversation_id"], "AI-CONV-1")
		self.assertEqual(payload["run_id"], "AI-RUN-1")
		self.assertEqual(payload["model_alias"], "opencode-glm-5.2")
		mock_selected_model.assert_called_once_with("opencode-glm-5.2")

	@patch("myapp.services.ai_service._complete_chat_run", return_value={
		"status": "completed", "latency_ms": 100, "first_token_ms": None,
	})
	@patch("myapp.services.ai_service._call_ai_orchestrator")
	@patch("myapp.services.ai_service._prepare_chat_run")
	def test_chat_ai_v1_returns_compatibility_warning_without_replaying_model_call(
		self, mock_prepare, mock_call, _mock_complete,
	):
		mock_prepare.return_value = {
			"user": "user@example.com", "can_view_advanced_diagnostics": False,
			"conversation_id": "AI-CONV-1", "run_id": "AI-RUN-1", "payload": {},
			"citations": [], "tool_calls": [], "warnings": ["兼容查询模式"],
		}
		mock_call.return_value = {
			"message": {"role": "assistant", "content": "找到商品 Camera。"},
			"warnings": ["只读模式"],
		}

		result = chat_ai_v1(content="查询 Camera", company="Demo Company")

		self.assertEqual(result["data"]["warnings"], ["兼容查询模式", "只读模式"])
		self.assertIn(
			{"type": "warning", "message": "兼容查询模式"}, result["data"]["events"],
		)
		mock_call.assert_called_once_with({})

	@patch("myapp.services.ai_service.ai_repository.complete_run")
	@patch("myapp.services.ai_service.ai_repository.load_model_messages")
	@patch("myapp.services.ai_service.ai_repository.create_run", return_value="AI-RUN-2")
	@patch("myapp.services.ai_service.ai_repository.append_message")
	@patch("myapp.services.ai_service.ai_repository.create_conversation")
	@patch("myapp.services.ai_service._call_ai_orchestrator")
	@patch(
		"myapp.services.ai_service.search_products_semantic",
		return_value={"available": False, "rows": [], "reason": "disabled"},
	)
	@patch("myapp.services.ai_service.search_product_v2")
	@patch("myapp.services.ai_service._resolve_company_scope", return_value="rgc (Demo)")
	def test_product_search_uses_read_only_backend_tool_and_returns_citations(
		self,
		mock_company,
		mock_search,
		mock_semantic_search,
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

		with patch("myapp.services.ai_service._call_ai_intent_orchestrator", return_value={
			"intent": "product_search", "confidence": 0.96,
			"product_query": "蓝色大包装饮料", "entities": [], "report_type": None,
			"date_preset": "all", "date_from": None, "date_to": None,
			"status": "all", "sort": "latest", "min_amount": None, "limit": 10,
		}), patch("myapp.services.ai_service.frappe") as mock_frappe, patch(
			"myapp.services.ai_service.now_datetime", return_value="2026-07-24 11:30:00",
		):
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
		self.assertEqual(payload["context"]["retrieval"]["mode"], "lexical_fallback")
		mock_semantic_search.assert_called_once()
		tool_calls = mock_complete_run.call_args.kwargs["tool_calls"]
		self.assertEqual(tool_calls[0]["tool"], "parse_ai_intent")
		self.assertTrue(any(call["risk_level"] == "L1_READ_ONLY" for call in tool_calls))

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

		with patch("myapp.services.ai_service._call_ai_intent_orchestrator", return_value={
			"intent": "report_summary", "confidence": 0.96,
			"product_query": None, "entities": [], "report_type": "sales",
			"date_preset": "this_month", "date_from": None, "date_to": None,
			"status": "all", "sort": "latest", "min_amount": None, "limit": 10,
		}), patch("myapp.services.ai_service.frappe") as mock_frappe:
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
		tool_calls = mock_complete_run.call_args.kwargs["tool_calls"]
		self.assertEqual(tool_calls[0]["tool"], "parse_ai_intent")
		self.assertTrue(any(call["risk_level"] == "L1_READ_ONLY" for call in tool_calls))

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

	@patch("myapp.services.ai_service._complete_chat_run")
	@patch("myapp.services.ai_service._pause_chat_run")
	@patch("myapp.services.ai_service._call_ai_orchestrator")
	@patch("myapp.services.ai_service._prepare_chat_run")
	def test_chat_ai_v1_returns_waiting_approval_without_completing_run(
		self, prepare, call_orchestrator, pause_run, complete_run,
	):
		prepare.return_value = {
			"conversation_id": "AI-CONV-1", "run_id": "AI-RUN-1",
			"payload": {}, "user": "user@example.com", "started": 0,
		}
		call_orchestrator.return_value = {
			"status": "waiting_approval",
			"approval": {"approval_id": "AI-APPROVAL-1", "run_id": "AI-RUN-1"},
		}
		pause_run.return_value = {
			"approval": {"approval_id": "AI-APPROVAL-1", "run_id": "AI-RUN-1"},
			"latency_ms": 12,
		}

		result = chat_ai_v1(content="需要审批的操作")

		self.assertEqual(result["data"]["run_status"], "waiting_approval")
		self.assertEqual(result["data"]["approval"]["approval_id"], "AI-APPROVAL-1")
		complete_run.assert_not_called()
