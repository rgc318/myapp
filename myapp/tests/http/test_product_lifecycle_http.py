"""Real HTTP contract tests: preview/confirmation rejection only, no Item writes."""
import os

from .test_ai_draft_action_http import DraftActionHttpTest
from .test_ai_model_check_http import ModelCheckHttpTest
from unittest import TestCase


class LifecycleHttpTest(TestCase):
	setUpClass = classmethod(ModelCheckHttpTest.setUpClass.__func__)
	request = DraftActionHttpTest.request

	def setUp(self):
		self.item = os.getenv("MYAPP_HTTP_LIFECYCLE_ITEM")
		if not self.item:
			self.skipTest("Set MYAPP_HTTP_LIFECYCLE_ITEM to a readable existing Item for preview-only tests")
		self.plans = []

	def tearDown(self):
		for plan_id in getattr(self, "plans", []):
			self.request("discard_product_lifecycle_plan_v1", {"plan_id": plan_id})

	def test_preview_history_and_strict_confirmation_boundary(self):
		plan = self.request("create_product_lifecycle_plan_v1", {
			"operation": "disable", "item_codes": [self.item], "reason": "HTTP 只预检，不执行"})
		self.plans.append(plan["name"])
		self.assertEqual(plan["preview"]["targets"][0]["item_code"], self.item)
		self.assertEqual(plan["status"], "pending")
		self.assertGreater(plan["expires_in_seconds"], 0)
		for confirmed in [False, "false", "true", 1]:
			rejected = self.request("execute_product_lifecycle_plan_v1", {
				"plan_id": plan["name"], "expected_version": 1,
				"confirmed": confirmed, "shared_scope_confirmed": True,
				"request_id": "lifecycle-http-no-execution"}, success=False)
			self.assertEqual(rejected["code"], "VALIDATION_ERROR")
		latest = self.request("get_product_lifecycle_plan_v1", {"plan_id": plan["name"]})
		self.assertEqual(latest["status"], "pending")
		self.assertIsNone(latest["receipt"])
		listing = self.request("list_product_lifecycle_plans_v1", {"limit": 50})
		self.assertIn(plan["name"], [row["name"] for row in listing["items"]])

	def test_ai_route_preserves_resolution_without_business_execution(self):
		model = os.getenv("MYAPP_HTTP_ACTION_TEST_MODEL")
		if not model:
			self.skipTest("Set MYAPP_HTTP_ACTION_TEST_MODEL for one billable intent call")
		payload = {"content": f"删除商品编码 {self.item}", "model_alias": model}
		resolution = self.request("resolve_ai_scenario_v1", payload)
		self.assertEqual(resolution["scenario"], "product_lifecycle_plan")
		result = self.request("generate_ai_product_lifecycle_plan_v1", {
			**payload, "scenario_resolution_id": resolution["resolution_id"]})
		self.plans.append(result["plan"]["name"])
		try:
			self.assertEqual(result["plan"]["preview"]["operation"], "delete")
			self.assertEqual(result["plan"]["preview"]["targets"][0]["item_code"], self.item)
			self.assertIsNone(result["plan"]["receipt"])
		finally:
			self.request("archive_ai_conversation_v1", {"conversation_id": result["conversation_id"]})
