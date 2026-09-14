from copy import deepcopy
from contextlib import ExitStack
from unittest import TestCase
from unittest.mock import patch

from myapp.services.ai_product_pricing import build_product_pricing, preserve_price_provenance
from myapp.services import ai_service as service
from myapp.utils.uom import resolve_uom_relation_factors


class TestAiProductPricing(TestCase):
	def setUp(self):
		self.display = patch("myapp.services.ai_product_pricing.resolve_uom_display_name", side_effect=lambda value: value)
		self.display.start()
		self.addCleanup(self.display.stop)
		self.payload = {"stock_uom": "Box", "currency": "CNY", "prices": [
			{"price_list": "Retail", "rate": 3.5, "uom": "Bottle", "interpretation": "inferred"},
			{"price_list": "Wholesale", "rate": 30, "uom": "Box", "interpretation": "inferred"},
			{"price_list": "Standard Buying", "rate": 25, "uom": "Box", "interpretation": "explicit"}],
			"uom_relations": [{"from_uom": "Bottle", "from_qty": 12, "to_uom": "Box", "to_qty": 1}]}

	def build(self, payload=None):
		return build_product_pricing(payload or self.payload, resolve_uom=lambda value: value if value in {"Box", "Bottle", "Pallet", "Kg", "G"} else None)

	def test_original_request_retains_four_prices_and_explicit_conversion(self):
		result, errors, warnings = self.build()
		self.assertEqual(errors, [])
		self.assertTrue(warnings)
		self.assertEqual([(r["price_list"], r["rate"], r["uom"]) for r in result["prices"]], [
			("Retail", 3.5, "Bottle"), ("Wholesale", 30, "Box"), ("Standard Buying", 25, "Box"), ("Standard Selling", 30, "Box")])
		self.assertEqual(result["retail_default_uom"], "Bottle")
		self.assertEqual(result["wholesale_default_uom"], "Box")
		self.assertAlmostEqual(next(r["conversion_factor"] for r in result["uom_conversions"] if r["uom"] == "Bottle"), 1 / 12)

	def test_missing_packaging_blocks_without_losing_prices_or_guessing(self):
		self.payload["uom_relations"] = []
		result, errors, _ = self.build()
		self.assertTrue(errors)
		self.assertEqual(result["wholesale_rate"], 30)
		self.assertEqual(result["retail_rate"], 3.5)
		self.assertIsNone(result["uom_relations"][0]["from_qty"])
		self.assertEqual(result["uom_conversions"], [{"uom": "Box", "conversion_factor": 1}])

	def test_default_refresh_and_explicit_standard_price_preserved(self):
		first, _, _ = self.build()
		edited = {**self.payload, **first}
		edited["prices"][1]["rate"] = 32
		second, errors, _ = self.build(edited)
		self.assertEqual(errors, [])
		self.assertEqual(second["standard_selling_rate"], 32)
		explicit = deepcopy(second["prices"])
		explicit[-1]["rate"] = 40
		explicit[-1]["interpretation"] = "default"
		explicit = preserve_price_provenance(explicit, second["prices"])
		self.assertEqual(explicit[-1]["interpretation"], "user")
		third, errors, _ = self.build({**edited, "prices": explicit})
		self.assertEqual(errors, [])
		self.assertEqual(third["standard_selling_rate"], 40)

	def test_rebuild_is_idempotent(self):
		first, errors, warnings = self.build()
		second, next_errors, next_warnings = self.build({**self.payload, **first})
		self.assertEqual((first, errors, warnings), (second, next_errors, next_warnings))

	def test_invalid_prices_fail_closed(self):
		for changes in ({"rate": float("nan")}, {"rate": -1}, {"rate": True}, {"rate": "3.5"}, {"price_list": []}, {"currency": "USD"}, {"uom": "unknown"}):
			with self.subTest(changes=changes):
				payload = deepcopy(self.payload)
				payload["prices"][0].update(changes)
				self.assertTrue(self.build(payload)[1])

	def test_duplicate_prices_and_zero_price(self):
		self.payload["prices"][0]["rate"] = 0
		self.assertEqual(self.build()[1], [])
		self.payload["prices"].append(deepcopy(self.payload["prices"][0]))
		self.assertTrue(self.build()[1])

	def test_formal_price_list_currency_mismatch_is_not_relabelled(self):
		result, errors, _ = build_product_pricing(self.payload, resolve_uom=lambda value: value,
			resolve_price_currency=lambda value: "USD")
		self.assertTrue(any("正式价格表币种" in error for error in errors))
		self.assertEqual(result["prices"][0]["currency"], "CNY")
		_, errors, _ = build_product_pricing(self.payload, resolve_uom=lambda value: value,
			resolve_price_currency=lambda value: "USD" if value == "Standard Selling" else "CNY")
		self.assertTrue(any("默认标准销售参考价币种" in error for error in errors))

	def test_multilevel_weight_and_contradictory_relations(self):
		relations = self.payload["uom_relations"] + [{"from_uom": "Box", "from_qty": 20, "to_uom": "Pallet", "to_qty": 1}]
		self.assertAlmostEqual(resolve_uom_relation_factors("Bottle", relations)["Pallet"], 240)
		self.assertEqual(resolve_uom_relation_factors("Kg", [{"from_uom": "G", "from_qty": 1000, "to_uom": "Kg", "to_qty": 1}])["G"], 0.001)
		with self.assertRaises(ValueError):
			resolve_uom_relation_factors("Box", relations + [{"from_uom": "Bottle", "from_qty": 10, "to_uom": "Box", "to_qty": 1}])

	def test_real_draft_builder_rebuild_and_execution_preserve_unit_prices(self):
		with ExitStack() as stack:
			stack.enter_context(patch.object(service, "_resolve_sales_draft_warehouse", return_value=None))
			stack.enter_context(patch.object(service, "_resolve_optional_master_name", side_effect=lambda _doctype, value: value))
			stack.enter_context(patch.object(service, "_resolve_product_setup_uom", side_effect=lambda value: (value, [])))
			stack.enter_context(patch.object(service, "_resolve_existing_product_for_setup", return_value=(None, [])))
			framework = stack.enter_context(patch.object(service, "frappe"))
			framework.db.get_value.return_value = "CNY"
			framework.db.exists.return_value = False
			framework.has_permission.return_value = True
			candidate = {"operation": "create", "target": {}, "pricing_contract_version": "product-pricing-v1",
				"patch": {**self.payload, "item_name": "Pricing test", "item_group": "Products"}}
			payload, validation = service._build_product_setup_draft(candidate, company="c")
			self.assertEqual(validation["errors"], [])
			self.assertEqual(payload["wholesale_rate"], 30)
			self.assertEqual(len(payload["prices"]), 4)
			rebuilt, validation = service._build_product_setup_draft(payload, company="c")
			self.assertEqual(validation["errors"], [])
			self.assertEqual(rebuilt["prices"], payload["prices"])
			create = stack.enter_context(patch.object(service, "create_product_v2", return_value={"data": {"item_code": "TEST"}}))
			result = service._execute_ai_draft_payload({"draft_type": "product_setup", "payload": rebuilt}, request_id="test")
			self.assertEqual(result["target_name"], "TEST")
			kwargs = create.call_args.kwargs
			self.assertEqual([(r["price_list"], r["rate"], r["uom"]) for r in kwargs["selling_prices"]],
				[("Retail", 3.5, "Bottle"), ("Wholesale", 30, "Box"), ("Standard Selling", 30, "Box")])
			self.assertEqual(kwargs["buying_prices"][0]["uom"], "Box")
			self.assertEqual(kwargs["retail_default_uom"], "Bottle")

	def test_update_repair_discards_null_legacy_price_patch_when_unit_prices_exist(self):
		prices = [
			{"row_id": "retail", "price_list": "Retail", "rate": 3, "uom": "Bottle", "currency": "CNY"},
			{"row_id": "wholesale", "price_list": "Wholesale", "rate": 52, "uom": "Box", "currency": "CNY"},
			{"row_id": "selling", "price_list": "Standard Selling", "rate": 3, "uom": "Bottle", "currency": "CNY"},
			{"row_id": "buying", "price_list": "Standard Buying", "rate": 50, "uom": "Box", "currency": "CNY"},
		]
		relations = [
			{"from_qty": 1, "from_uom": "Box", "to_qty": 24, "to_uom": "Bottle",
			 "evidence": "现有商品单位换算"},
		]
		baseline = {
			"item_name": "可口可乐 5000ml", "item_code": "ITEM-PRICED", "item_group": "Products",
			"brand": "Demo", "stock_uom": "Bottle", "currency": "CNY",
			"standard_selling_rate": 3, "wholesale_rate": 52, "retail_rate": 3,
			"standard_buying_rate": 50, "prices": prices, "uom_relations": relations,
			"wholesale_default_uom": "Box", "retail_default_uom": "Bottle",
		}
		bad_patch = {
			"item_name": "可口可乐-500ml", "standard_selling_rate": None,
			"wholesale_rate": None, "retail_rate": None, "prices": prices,
		}
		candidate = {
			**baseline, "item_name": "可口可乐-500ml", "operation": "update",
			"pricing_contract_version": "product-pricing-v1",
			"_state": {
				"schema_version": service.AI_DRAFT_STATE_SCHEMA_VERSION,
				"operation": "update", "entity": {"name": "ITEM-PRICED"},
				"baseline": baseline, "patch": bad_patch,
			},
		}
		with ExitStack() as stack:
			stack.enter_context(patch.object(service, "_resolve_sales_draft_warehouse", return_value=None))
			stack.enter_context(patch.object(service, "_resolve_optional_master_name", side_effect=lambda _doctype, value: value))
			stack.enter_context(patch.object(service, "_resolve_product_setup_uom", side_effect=lambda value: (value, [])))
			stack.enter_context(patch.object(service, "_resolve_existing_product_for_setup", return_value=(
				{"item_code": "ITEM-PRICED", "item_name": "可口可乐 5000ml", "modified": "2026-09-14"}, [],
			)))
			stack.enter_context(patch.object(service, "_build_existing_product_baseline", return_value=(baseline, {}, {})))
			framework = stack.enter_context(patch.object(service, "frappe"))
			framework.db.get_value.return_value = "CNY"
			framework.db.exists.return_value = True
			framework.has_permission.return_value = True

			payload, validation = service._build_product_setup_draft(candidate, company="c")

		self.assertFalse(any("删除价格" in error for error in validation["errors"]))
		self.assertEqual(payload["_state"]["patch"]["item_name"], "可口可乐-500ml")
		self.assertEqual(
			[(row["price_list"], row["rate"], row["uom"]) for row in payload["_state"]["patch"]["prices"]],
			[("Retail", 3, "Bottle"), ("Wholesale", 52, "Box"),
			 ("Standard Selling", 3, "Bottle"), ("Standard Buying", 50, "Box")],
		)
		for field in service.PRODUCT_SETUP_LEGACY_PRICE_FIELDS:
			self.assertNotIn(field, payload["_state"]["patch"])
