from unittest import TestCase
from unittest.mock import patch

import frappe
from myapp.services import ai_service as service


class TestAiActionSafety(TestCase):
	def test_explicit_delete_cannot_route_to_product_edit(self):
		intent = {"intent": "product_setup_draft", "confidence": 0.99,
			"action_contract": {"schema_version": "ai-action-contract-v1", "request_mode": "execute_request",
				"operations": ["delete"], "target_count": 2, "has_preserve_targets": True}}
		self.assertEqual(service._resolve_ai_action_scenario("删除两个保留一个", None, intent)[:2],
			("general", "action_unsupported"))

	def test_inquiry_and_multiple_targets_do_not_route_to_writes(self):
		for mode, count in (("inquire", 1), ("negate", 1), ("execute_request", 2)):
			intent = {"intent": "product_setup_draft", "confidence": 0.99,
				"action_contract": {"schema_version": "ai-action-contract-v1", "request_mode": mode,
					"operations": ["update"], "target_count": count}}
			self.assertEqual(service._resolve_ai_action_scenario("请求", None, intent)[1], "action_clarification_required")

	def test_explicit_query_reset_does_not_restore_old_filters(self):
		base = {"intent": "order_query", "date_preset": "last_month", "min_amount": 20000,
			"sort": "amount_desc", "limit": 3}
		candidate = {"intent": "order_query", "confidence": 0.99, "date_preset": "all",
			"min_amount": None, "sort": "latest", "limit": 10,
			"query_context_operations": {"reset": True, "clear_fields": []}}
		with patch.object(service, "_state_intent_defaults", return_value=base):
			result = service._merge_intent_with_conversation_state("清除所有筛选", candidate, {})
		self.assertEqual(result, candidate)

	def test_clear_amount_preserves_other_inherited_filters(self):
		base = {"intent": "order_query", "date_preset": "last_month", "min_amount": 20000}
		candidate = {"intent": "order_query", "confidence": 0.99, "date_preset": "all", "min_amount": None,
			"query_context_operations": {"reset": False, "clear_fields": ["min_amount"]}}
		with patch.object(service, "_state_intent_defaults", return_value=base):
			result = service._merge_intent_with_conversation_state("金额不限制", candidate, {})
		self.assertIsNone(result["min_amount"])
		self.assertEqual(result["date_preset"], "last_month")

	def test_uncertain_writes_never_use_lexical_write_routes(self):
		for content in (
			"不要创建商品，只查询库存", "先别修改商品，我只是问问能不能改",
			"不要给客户创建销售订单", "不要新增采购订单", "不要减少库存",
			"创建一个商品",  # Even affirmative writes need reliable semantic routing.
		):
			with self.subTest(content=content):
				result = service._resolve_ai_action_scenario(content, None, {"intent": "general", "confidence": 0.2})
				self.assertEqual(result[:2], ("general", "write_intent_requires_clarification"))

	def test_confident_supported_route_still_works(self):
		self.assertEqual(service._resolve_ai_action_scenario("新增商品", None,
			{"intent": "product_setup_draft", "confidence": 0.9})[0], "product_setup_draft")

	def test_unsupported_order_operation_is_not_created(self):
		for operation in ("cancel", "delete", "merge", "disable"):
			with self.subTest(operation=operation), self.assertRaises(frappe.ValidationError):
				service._resolve_order_update_source({"operation": operation}, draft_type="sales_order", company="demo")

	def test_unsupported_product_operation_fails_before_entity_lookup(self):
		with patch.object(service, "_normalize_product_setup_semantic_candidate", side_effect=lambda value: value), patch.object(
			service, "_resolve_existing_product_for_setup",
		) as resolve:
			with self.assertRaises(frappe.ValidationError):
				service._build_product_setup_draft({"operation": "delete"}, company="demo")
			resolve.assert_not_called()
