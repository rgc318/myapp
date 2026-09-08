"""Opt-in real Item/Item Price transaction verification; never commit fixtures."""
import os
import secrets
from unittest import TestCase, skipUnless

import frappe

from myapp.services.ai_product_pricing import build_product_pricing
from myapp.services.ai_service import _build_existing_product_baseline, _execute_ai_draft_payload, _resolve_product_setup_uom
from myapp.services.wholesale_service import get_product_detail_v2


@skipUnless(os.getenv("MYAPP_PRICING_TEST_SITE"), "Set MYAPP_PRICING_TEST_SITE for isolated transaction tests")
class ProductPricingTransactions(TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.init(site=os.environ["MYAPP_PRICING_TEST_SITE"], sites_path="/home/frappe/frappe-bench/sites")
		frappe.connect()
		frappe.set_user("Administrator")

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		frappe.destroy()

	def tearDown(self):
		frappe.db.rollback()

	def test_formal_create_retains_actual_rates_units_and_conversion(self):
		company = frappe.db.get_value("Company", {"default_currency": "CNY"}, "name")
		code = "AI-PRICING-TEST-" + secrets.token_hex(8)
		payload = {"operation": "create", "item_code": code, "item_name": code, "company": company,
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
			"stock_uom": "Box", "currency": frappe.db.get_value("Company", company, "default_currency"),
			"prices": [{"price_list": "Retail", "rate": 3.5, "uom": "Bottle"},
				{"price_list": "Wholesale", "rate": 30, "uom": "Box"},
				{"price_list": "Standard Buying", "rate": 25, "uom": "Box"}],
			"uom_relations": [{"from_uom": "Bottle", "from_qty": 12, "to_uom": "Box", "to_qty": 1}]}
		pricing, errors, _ = build_product_pricing(payload, resolve_uom=lambda value: _resolve_product_setup_uom(value)[0])
		self.assertEqual(errors, [])
		payload.update(pricing)
		result = _execute_ai_draft_payload({"draft_type": "product_setup", "payload": payload}, request_id=None)
		self.assertEqual(result["target_name"], code)
		rows = frappe.get_all("Item Price", filters={"item_code": code}, fields=["price_list", "price_list_rate", "uom"])
		self.assertEqual({(r.price_list, float(r.price_list_rate), r.uom) for r in rows}, {
			("Retail", 3.5, "Bottle"), ("Wholesale", 30, "Box"), ("Standard Buying", 25, "Box"), ("Standard Selling", 30, "Box")})
		item = frappe.get_doc("Item", code)
		self.assertEqual(item.stock_uom, "Box")
		self.assertAlmostEqual(next(r.conversion_factor for r in item.uoms if r.uom == "Bottle"), 1 / 12, places=6)
		detail = get_product_detail_v2(item_code=code, company=company)["data"]
		baseline, _, _ = _build_existing_product_baseline(detail, company=company)
		self.assertEqual(len(baseline["prices"]), 4)
		updated = {**payload, "operation": "update", "_state": {"patch": {"prices": True}}}
		updated["prices"] = [{**row, "rate": 32} if row["price_list"] == "Wholesale" else row for row in payload["prices"]]
		_execute_ai_draft_payload({"draft_type": "product_setup", "payload": updated}, request_id=None)
		self.assertEqual(frappe.db.get_value("Item Price", {"item_code": code, "price_list": "Wholesale", "uom": "Box"}, "price_list_rate"), 32)
		self.assertEqual(frappe.db.get_value("Item Price", {"item_code": code, "price_list": "Standard Selling", "uom": "Box"}, "price_list_rate"), 32)
		self.assertEqual(frappe.db.count("Item Price", {"item_code": code}), 4)
		frappe.db.rollback()
		self.assertFalse(frappe.db.exists("Item", code))
