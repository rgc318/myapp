"""Opt-in real Gateway/adapter/draft contract verification; never executes ERP writes."""
import json
import os
import unittest
import urllib.error
import urllib.request

from . import test_ai_model_check_http as auth


class DraftActionHttpTest(unittest.TestCase):
	setUpClass = classmethod(auth.ModelCheckHttpTest.setUpClass.__func__)

	def request(self, method, payload, *, success=True):
		request = urllib.request.Request(self.base + "/api/method/myapp.api.gateway." + method,
			data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
		try:
			response = self.opener.open(request, timeout=120)
		except urllib.error.HTTPError as error:
			response = error
		with response:
			result = json.load(response)["message"]
		self.assertEqual(result["ok"], success, result.get("code"))
		return result["data"] if success else result

	def setUp(self):
		self.model = os.getenv("MYAPP_HTTP_ACTION_TEST_MODEL")
		self.item = os.getenv("MYAPP_HTTP_ACTION_TEST_ITEM")
		if not self.model or not self.item:
			self.skipTest("Set MYAPP_HTTP_ACTION_TEST_MODEL and MYAPP_HTTP_ACTION_TEST_ITEM for billable draft checks")
		self.company = os.getenv("MYAPP_HTTP_ACTION_TEST_COMPANY", "rgc (Demo)")
		self.draft_id = None
		self.conversation = self.request("create_ai_conversation_v1", {"title": "AI action contract HTTP verification", "company": self.company})["name"]

	def tearDown(self):
		if not hasattr(self, "conversation"):
			return
		try:
			if self.draft_id:
				self.request("discard_ai_draft_v1", {"draft_id": self.draft_id})
		finally:
			self.request("archive_ai_conversation_v1", {"conversation_id": self.conversation})

	def test_direct_draft_endpoint_rejects_delete(self):
		result = self.request("generate_ai_product_setup_draft_v1", {"content": f"删除商品编码 {self.item}",
			"company": self.company, "conversation_id": self.conversation, "model_alias": self.model}, success=False)
		self.assertEqual(result["code"], "VALIDATION_ERROR")

	def test_resolved_draft_persists_contract_and_rejects_operation_change(self):
		payload = {"content": f"修改商品编码 {self.item} 的描述为动作契约接口回归测试",
			"company": self.company, "conversation_id": self.conversation, "model_alias": self.model}
		resolution = self.request("resolve_ai_scenario_v1", payload)
		self.assertEqual(resolution["scenario"], "product_setup_draft")
		self.assertTrue(resolution["resolution_id"])
		result = self.request("generate_ai_product_setup_draft_v1", {**payload, "scenario_resolution_id": resolution["resolution_id"]})
		draft = result["draft"]
		self.draft_id = draft["name"]
		contract = draft["payload"]["_action_contract"]
		self.assertEqual(contract["action"]["operations"], ["update"])
		self.assertEqual(draft["payload"]["operation"], "update")
		self.assertEqual(contract["resolved_scope"]["target"], self.item)
		# Changing the browser payload to create must not rewrite the trusted contract.
		rejected = self.request("update_ai_draft_v1", {"draft_id": self.draft_id, "expected_version": draft["version"],
			"payload": {**draft["payload"], "operation": "create", "_action_contract": {"forged": True}}}, success=False)
		self.assertEqual(rejected["code"], "VALIDATION_ERROR")
		other_item = os.getenv("MYAPP_HTTP_ACTION_OTHER_ITEM")
		if other_item:
			changed = {**draft["payload"], "item_code": other_item, "_state": {}}
			rejected = self.request("update_ai_draft_v1", {"draft_id": self.draft_id,
				"expected_version": draft["version"], "payload": changed}, success=False)
			self.assertEqual(rejected["code"], "VALIDATION_ERROR")
			self.assertIn("已绑定", json.dumps(rejected, ensure_ascii=False))
