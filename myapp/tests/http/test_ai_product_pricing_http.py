"""Opt-in real model + public Gateway draft round trip. No ERP execution."""
import os
import secrets
import unittest

from .test_ai_draft_action_http import DraftActionHttpTest


class ProductPricingHttpTest(unittest.TestCase):
	setUpClass = classmethod(DraftActionHttpTest.setUpClass.__func__)
	request = DraftActionHttpTest.request

	def test_generate_edit_and_read_preserve_per_unit_prices(self):
		model = os.getenv("MYAPP_HTTP_PRICING_TEST_MODEL")
		if not model:
			self.skipTest("Set MYAPP_HTTP_PRICING_TEST_MODEL for a billable pricing acceptance test")
		company = os.getenv("MYAPP_HTTP_ACTION_TEST_COMPANY", "rgc (Demo)")
		conversation = self.request("create_ai_conversation_v1", {"title": "逐单位价格隔离验收", "company": company})["name"]
		draft_id = None
		try:
			payload = {"content": f"新增商品AI定价验收{secrets.token_hex(5)}600ml百事可乐，3.5元每瓶，30元每箱，标准单位箱，进价25元每箱。",
				"company": company, "conversation_id": conversation, "model_alias": model}
			resolution = self.request("resolve_ai_scenario_v1", payload)
			self.assertEqual(resolution["scenario"], "product_setup_draft")
			result = self.request("generate_ai_product_setup_draft_v1", {**payload, "scenario_resolution_id": resolution["resolution_id"]})
			draft = result["draft"]
			draft_id = draft["name"]
			data = draft["payload"]
			self.assertEqual(data["pricing_contract_version"], "product-pricing-v1")
			self.assertEqual({(row["price_list"], row["rate"], row["uom"]) for row in data["prices"]}, {
				("Retail", 3.5, "Bottle"), ("Wholesale", 30, "Box"), ("Standard Buying", 25, "Box"), ("Standard Selling", 30, "Box")})
			self.assertFalse(draft["validation"]["ready_for_handoff"])
			data["uom_relations"] = [{"from_uom": "Bottle", "from_qty": 12, "to_uom": "Box", "to_qty": 1}]
			# This test isolates pricing. An unregistered model-proposed brand is
			# explicitly cleared as a human editor may do; do not create master data.
			data["brand"] = None
			data["brand_query"] = None
			updated = self.request("update_ai_draft_v1", {"draft_id": draft_id, "expected_version": draft["version"], "payload": data})
			self.assertEqual(updated["payload"]["prices"], data["prices"])
			self.assertFalse(any("换算" in error for error in updated["validation"]["errors"]), updated["validation"]["errors"])
			self.assertTrue(updated["validation"]["ready_for_handoff"], updated["validation"]["errors"])
			read = self.request("get_ai_draft_v1", {"draft_id": draft_id})
			self.assertEqual(read["payload"]["prices"], updated["payload"]["prices"])
			changed_payload = read["payload"]
			for row in changed_payload["prices"]:
				if row["price_list"] == "Wholesale":
					row["rate"] = 32
			changed = self.request("update_ai_draft_v1", {"draft_id": draft_id, "expected_version": read["version"], "payload": changed_payload})
			self.assertEqual(changed["payload"]["standard_selling_rate"], 32)
			restored = self.request("restore_ai_draft_version_v1", {"draft_id": draft_id, "version": updated["version"], "expected_version": changed["version"]})
			self.assertEqual(restored["payload"]["standard_selling_rate"], 30)
			self.assertEqual(next(row["interpretation"] for row in restored["payload"]["prices"] if row["price_list"] == "Standard Selling"), "default")
		finally:
			if draft_id:
				self.request("discard_ai_draft_v1", {"draft_id": draft_id})
			self.request("archive_ai_conversation_v1", {"conversation_id": conversation})
