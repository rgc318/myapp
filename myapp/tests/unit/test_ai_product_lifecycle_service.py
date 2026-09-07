from copy import deepcopy
from datetime import datetime, timedelta
import json
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services import ai_product_lifecycle_service as service


class LifecycleIntentTests(TestCase):
	def setUp(self):
		self.content = "删除百事可乐2和3，只保留百事可乐"
		self.intent = {"intent": "product_setup_draft", "confidence": 0.95, "action_contract": {
			"schema_version": "ai-action-contract-v1", "request_mode": "execute_request",
			"operations": ["delete"], "target_count": 2, "has_preserve_targets": True,
			"product_targets": [{"query": "百事可乐2", "evidence": "百事可乐2"},
				{"query": "百事可乐3", "evidence": "3"}],
			"preserve_product_targets": [{"query": "百事可乐", "evidence": "只保留百事可乐"}]}}

	def test_full_operation_and_preserve_targets_are_retained(self):
		operation, targets, preserve = service.validate_lifecycle_intent(self.intent, self.content)
		self.assertEqual(operation, "delete")
		self.assertEqual(len(targets), 2)
		self.assertEqual(preserve[0]["query"], "百事可乐")

	def test_incomplete_or_non_execution_contracts_fail_closed(self):
		for update in [{"target_count": 1}, {"target_count": True}, {"target_count": None},
			{"has_preserve_targets": False}, {"request_mode": "question"},
			{"operations": ["delete", "update"]}, {"product_targets": []}]:
			intent = deepcopy(self.intent)
			intent["action_contract"].update(update)
			with self.subTest(update=update), self.assertRaises(frappe.ValidationError):
				service.validate_lifecycle_intent(intent, self.content)

	def test_hallucinated_evidence_and_nonfinite_confidence_rejected(self):
		for confidence in [float("nan"), float("inf"), 0.59]:
			with self.subTest(confidence=confidence), self.assertRaises(frappe.ValidationError):
				service.validate_lifecycle_intent({**self.intent, "confidence": confidence}, self.content)
		self.intent["action_contract"]["product_targets"][0]["evidence"] = "不存在的原文"
		with self.assertRaises(frappe.ValidationError):
			service.validate_lifecycle_intent(self.intent, self.content)

	def test_single_fuzzy_match_still_requires_human_selection(self):
		with patch.object(service, "_candidates", return_value=[{"item_code": "ONE", "match_kind": "candidate"}]), \
			patch.object(service, "_persist_preview", side_effect=lambda value: value), \
			patch.object(service, "create_product_lifecycle_plan") as create:
			preview = service.plan_from_intent(self.intent, self.content, {}, {})
			self.assertFalse(preview["execution_available"])
			self.assertEqual(len(preview["resolution_groups"]), 3)
			create.assert_not_called()

	def test_exact_targets_and_preserve_are_forwarded_separately(self):
		with patch.object(service, "_candidates", side_effect=lambda query, state: [
			{"item_code": query, "match_kind": "exact"}]), \
			patch.object(service, "create_product_lifecycle_plan") as create:
			service.plan_from_intent(self.intent, self.content, {}, {"content": self.content})
			self.assertEqual(create.call_args.args[:2], ("delete", ["百事可乐2", "百事可乐3"]))
			self.assertEqual(create.call_args.kwargs["preserve_codes"], ["百事可乐"])

	def test_broad_candidate_list_is_not_silently_truncated(self):
		with patch.object(service.frappe, "get_list", return_value=[frappe._dict(name=str(i)) for i in range(21)]):
			self.assertEqual(service._candidates("可乐", {}), [])

	def test_disabled_exact_match_is_available_for_enabling(self):
		with patch.object(service.frappe, "get_list", return_value=[frappe._dict(name="A", item_name="A", disabled=1)]) as query:
			self.assertTrue(service._candidates("A", {})[0]["disabled"])
			self.assertNotIn("disabled", query.call_args.kwargs.get("filters", {}))

	def test_plan_context_does_not_retain_an_unrelated_previous_target(self):
		previous = {"product": {"item_code": "OLD"}, "active_entities": {"product": {
			"entity_type": "product", "entity_id": "OLD", "resolution_status": "resolved"}}}
		plan = {"name": "PLAN", "preview": {"resolution_groups": [{"id": "target-0"}]}}
		state = service._plan_context(previous, plan)
		self.assertIsNone(state["active_entities"]["product"]["entity_id"])
		self.assertEqual(state["active_entities"]["product"]["resolution_status"], "ambiguous")
		self.assertEqual(state["last_result_set"]["entity_ids"], [])

	def test_preserve_targets_make_singular_pronoun_ambiguous(self):
		plan = {"name": "PLAN", "preview": {"targets": [{"item_code": "A"}],
			"preserve_targets": [{"item_code": "B"}]}}
		state = service._plan_context({}, plan)
		self.assertEqual(state["last_result_set"]["entity_ids"], ["A", "B"])
		self.assertEqual(state["product"]["resolution_status"], "ambiguous")

	def test_single_target_is_remembered_without_claiming_execution(self):
		state = service._plan_context({}, {"name": "PLAN", "preview": {"targets": [{"item_code": "A"}]}})
		self.assertEqual(state["product"]["item_code"], "A")
		self.assertEqual(state["active_entities"]["product"]["source"], "product_lifecycle_plan")

	def test_candidate_resolution_requires_every_server_owned_group(self):
		plan = frappe._dict(name="PLAN", status="pending", version_no=1,
			expires_at=datetime.now() + timedelta(minutes=15), preview_json=json.dumps({
				"operation": "delete", "reason": "删除 A，保留 B", "resolution_groups": [
					{"id": "target-0", "role": "target", "candidates": [{"item_code": "A"}]},
					{"id": "preserve-0", "role": "preserve", "candidates": [{"item_code": "B"}]}]}))
		with patch.object(service, "_read_plan", return_value=plan), \
			patch("frappe.utils.now_datetime", return_value=datetime.now()), \
			patch.object(service, "create_product_lifecycle_plan", return_value={"name": "NEW"}) as create, \
			patch.object(service, "current_user", return_value="owner"), \
			patch.object(service.frappe, "db", new=MagicMock()) as db:
			for selections in [{"target-0": "A"}, {"target-0": "FORGED", "preserve-0": "B"},
				{"target-0": "A", "preserve-0": "B", "extra": "C"}]:
				with self.subTest(selections=selections), self.assertRaises(frappe.ValidationError):
					service.resolve_product_lifecycle_plan("PLAN", 1, selections)
			create.assert_not_called()
			result = service.resolve_product_lifecycle_plan("PLAN", 1, {"target-0": "A", "preserve-0": "B"})
			self.assertEqual(result["name"], "NEW")
			self.assertEqual(create.call_args.args[:2], ("delete", ["A"]))
			self.assertEqual(create.call_args.kwargs["preserve_codes"], ["B"])
			self.assertIn("superseded", db.sql.call_args.args[0])
