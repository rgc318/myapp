from unittest import TestCase
from unittest.mock import patch

import frappe
from myapp.services import ai_service as service
from myapp.services.ai_action_contract import bind_draft_scope


class TestAiActionSafety(TestCase):
	def test_inventory_builder_does_not_silently_drop_extra_rows(self):
		with self.assertRaises(frappe.ValidationError):
			service._build_inventory_adjustment_draft({"items": [{"item_code": "A"}, {"item_code": "B"}]}, company="c")
	def test_bound_product_and_order_targets_cannot_be_replaced_or_cleared(self):
		for scenario, field in (("product_setup_draft", "item_code"),
			("sales_order_draft", "order_number"), ("purchase_order_draft", "order_number")):
			bound = bind_draft_scope({"scenario": scenario}, {"operation": "update", field: "A"})
			for target in ("B", None):
				with self.subTest(scenario=scenario, target=target), self.assertRaises(ValueError):
					bind_draft_scope(bound, {"operation": "update", field: target})

	def test_unresolved_target_can_be_bound_once(self):
		initial = bind_draft_scope({"scenario": "product_setup_draft"}, {"operation": "update"})
		bound = bind_draft_scope(initial, {"operation": "update", "item_code": "A"})
		self.assertEqual(bound["resolved_scope"]["target"], "A")
		self.assertEqual(initial["resolved_scope"], {})

	def test_inventory_scope_and_direction_are_frozen_but_quantity_is_editable(self):
		payload = {"adjustment_type": "increase", "warehouse": "W", "items": [{"item_code": "A", "quantity": 2}]}
		bound = bind_draft_scope({"scenario": "inventory_adjustment_draft"}, payload)
		for change in ({"adjustment_type": "decrease"}, {"warehouse": "OTHER"},
			{"items": [{"item_code": "B"}]}, {"items": []}, {"items": [{"item_code": "A"}, {"item_code": "B"}]}):
			with self.subTest(change=change), self.assertRaises(ValueError):
				bind_draft_scope(bound, {**payload, **change})
		self.assertEqual(bind_draft_scope(bound, {**payload, "items": [{"item_code": "A", "quantity": 3}]}), bound)

	def test_product_entity_and_item_code_must_agree(self):
		with self.assertRaises(ValueError):
			bind_draft_scope({"scenario": "product_setup_draft"},
				{"operation": "update", "item_code": "A", "_state": {"entity": {"name": "B"}}})
	def test_valid_resolution_is_reused_without_second_model_call(self):
		intent = {"intent": "product_setup_draft", "confidence": 0.99, "action_contract": {
			"schema_version": "ai-action-contract-v1", "request_mode": "execute_request", "operations": ["update"]}}
		with patch.object(service, "_take_ai_scenario_resolution", return_value={"scenario": "product_setup_draft", "intent": intent}) as take, patch.object(
			service, "_call_ai_intent_orchestrator",
		) as parse:
			result = service._prepare_draft_action_contract({"scenario": "product_setup_draft", "user": "u", "company": "c",
				"_scenario_resolution_id": "proof", "_resolution_state_version": 3, "_resolution_conversation_id": "conv",
				"messages": [{"role": "user", "content": "修改商品"}]})
			parse.assert_not_called()
			self.assertEqual(take.call_args.kwargs["conversation_state_version"], 3)
			self.assertEqual(result["action"]["operations"], ["update"])

	def test_invalid_resolution_is_not_silently_reparsed(self):
		with patch.object(service, "_take_ai_scenario_resolution", return_value=None), patch.object(
			service, "_call_ai_intent_orchestrator",
		) as parse:
			with self.assertRaises(frappe.ValidationError):
				service._prepare_draft_action_contract({"scenario": "product_setup_draft", "user": "u", "company": "c",
					"_scenario_resolution_id": "expired", "messages": [{"role": "user", "content": "修改商品"}]})
			parse.assert_not_called()

	def test_all_gateway_adapters_preserve_resolution_parameter(self):
		from myapp.api import gateway, ai_api
		for kind in ("sales_order", "purchase_order", "inventory_adjustment", "product_setup"):
			name = f"generate_ai_{kind}_draft_v1"
			with patch.object(gateway, "_handle_gateway_call", side_effect=lambda callback, **kw: callback()), patch.object(
				ai_api, f"{name}_service", return_value={},
			) as generate:
				getattr(gateway, name)(content="请求", company="c", conversation_id="conv", scenario_resolution_id="proof")
				self.assertEqual(generate.call_args.kwargs["scenario_resolution_id"], "proof")

	def test_all_four_direct_draft_wrappers_reject_delete_before_generation(self):
		for scenario, call in (
			("product_setup_draft", service._call_ai_orchestrator_product_setup_draft),
			("sales_order_draft", service._call_ai_orchestrator_sales_draft),
			("purchase_order_draft", service._call_ai_orchestrator_purchase_draft),
			("inventory_adjustment_draft", service._call_ai_orchestrator_inventory_adjustment_draft),
		):
			intent = {"intent": scenario, "confidence": 0.99, "action_contract": {
				"schema_version": "ai-action-contract-v1", "request_mode": "execute_request", "operations": ["delete"]}}
			with self.subTest(scenario=scenario), patch.object(service, "_call_ai_intent_orchestrator", return_value=intent), patch.object(
				service.urllib.request, "urlopen",
			) as generate:
				with self.assertRaises(frappe.ValidationError):
					call({"scenario": scenario, "user": "u", "company": "c",
						"messages": [{"role": "user", "content": "删除商品"}]})
				generate.assert_not_called()

	def test_draft_generation_must_match_original_action(self):
		contract = {"scenario": "product_setup_draft", "user": "u", "company": "c", "action": {
			"schema_version": "ai-action-contract-v1", "request_mode": "execute_request", "operations": ["update"]}}
		with self.assertRaises(frappe.ValidationError):
			service._seal_draft_action({"operation": "create"}, {"_action_contract": contract},
				scenario="product_setup_draft", user="u", company="c")
		sealed = service._seal_draft_action({"operation": "update"}, {"_action_contract": contract},
			scenario="product_setup_draft", user="u", company="c")
		self.assertEqual(sealed["_action_contract"]["action"], contract["action"])

	def test_legacy_model_drafts_fail_before_execution_but_ui_actions_are_distinct(self):
		draft = {"source_run": "run", "draft_type": "product_setup", "company": "c", "payload": {"operation": "update"}}
		with self.assertRaises(frappe.ValidationError):
			service._check_stored_draft_action(draft, user="u")
		service._check_stored_draft_action({**draft, "origin_kind": "ui_product_action"}, user="u")

	def test_contract_scope_cannot_cross_user_or_company(self):
		contract = {"scenario": "product_setup_draft", "user": "u", "company": "c", "action": {
			"schema_version": "ai-action-contract-v1", "request_mode": "execute_request", "operations": ["update"]}}
		for user, company in (("other", "c"), ("u", "other")):
			with self.assertRaises(frappe.ValidationError):
				service._seal_draft_action({"operation": "update"}, {"_action_contract": contract},
					scenario="product_setup_draft", user=user, company=company)

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
