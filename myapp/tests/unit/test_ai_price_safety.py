import json
from contextlib import ExitStack
from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.services import ai_repository as repository
from myapp.services import ai_service as service
from myapp.services.ai_price_safety import extract_product_price_requirements, product_price_errors


def resolve_unit(value):
	return {"瓶": "Bottle", "箱": "Box", "公斤": "Kg", "克": "G", "Box": "Box"}.get(value)


class TestAiPriceSafety(TestCase):
	def test_action_contract_and_actual_builder_preserve_source_unit_blocker(self):
		content = "新增600ml百事可乐，3.5元每瓶，30元每箱，标准单位箱，进价25元每箱"
		intent = {"intent": "product_setup_draft", "confidence": 0.99, "action_contract": {
			"schema_version": "ai-action-contract-v1", "request_mode": "execute_request", "operations": ["create"]}}
		with patch.object(service, "_call_ai_intent_orchestrator", return_value=intent):
			contract = service._prepare_draft_action_contract({"scenario": "product_setup_draft", "user": "u", "company": "c",
				"messages": [{"role": "user", "content": content}]})
		with ExitStack() as stack:
			stack.enter_context(patch.object(service, "_resolve_sales_draft_warehouse", return_value=None))
			stack.enter_context(patch.object(service, "_resolve_optional_master_name", side_effect=lambda _doctype, value: value))
			stack.enter_context(patch.object(service, "_resolve_product_setup_uom", side_effect=lambda value: (resolve_unit(value), [])))
			stack.enter_context(patch.object(service, "_resolve_existing_product_for_setup", return_value=(None, [])))
			framework = stack.enter_context(patch.object(service, "frappe"))
			framework.db.get_value.return_value = "CNY"
			framework.db.exists.return_value = False
			framework.has_permission.return_value = True
			payload, validation = service._build_product_setup_draft({"operation": "create", "target": {}, "patch": {
				"item_name": "百事可乐", "stock_uom": "Box", "standard_selling_rate": 3.5, "standard_buying_rate": 25},
				"_action_contract": contract}, company="c")
			self.assertFalse(validation["ready_for_handoff"])
			self.assertTrue(any("3.5元每瓶" in error for error in validation["errors"]))
			validation = service._apply_product_price_requirements(payload, validation, check_amounts=True)
			self.assertTrue(any("30元每箱" in error for error in validation["errors"]))
			self.assertEqual(payload["_action_contract"], contract)
			_, rebuilt_validation = service._build_product_setup_draft(payload, company="c")
			self.assertFalse(rebuilt_validation["ready_for_handoff"])

	def test_existing_product_baseline_selects_default_unit_without_first_row_bias(self):
		detail = {"stock_uom": "Box", "retail_default_uom": "Bottle", "price_summary": {"selling_prices": [
			{"price_list": "Retail", "uom": "Box", "rate": 40},
			{"price_list": "Retail", "uom": "Bottle", "rate": 3.5},
		]}}
		self.assertEqual(service._product_price_fact(detail, "Retail")[0], 3.5)

	def test_original_request_retains_all_per_unit_quotes(self):
		requirements = extract_product_price_requirements("新增600ml的百事可乐3.5元每瓶，30元每箱，标准单位是箱，进价25元每箱")
		self.assertEqual([(row["rate"], row["uom"]) for row in requirements["quotes"]],
			[("3.5", "瓶"), ("30", "箱"), ("25", "箱")])
		errors = product_price_errors({"stock_uom": "Box", "standard_selling_rate": 3.5, "standard_buying_rate": 25},
			requirements, resolve_uom=resolve_unit, check_amounts=True)
		self.assertTrue(any("3.5元每瓶" in message and "基准单位" in message for message in errors))
		self.assertTrue(any("30元每箱" in message and "未保留" in message for message in errors))

	def test_moving_bottle_price_to_retail_scalar_does_not_fix_missing_unit(self):
		payload = {"stock_uom": "Box", "standard_selling_rate": 30, "wholesale_rate": 30,
			"retail_rate": 3.5, "standard_buying_rate": 25}
		errors = product_price_errors(payload, extract_product_price_requirements("3.5元/瓶，30元/箱，25元/箱"),
			resolve_uom=resolve_unit, check_amounts=True)
		self.assertEqual(len(errors), 1)
		self.assertIn("3.5元/瓶", errors[0])

	def test_unit_alias_and_same_unit_multi_role_prices_are_supported(self):
		payload = {"stock_uom": "Box", "standard_selling_rate": 30, "standard_buying_rate": 25}
		for content in ("每箱30元，进价每箱25元", "30元/Box，25元／箱"):
			self.assertEqual(product_price_errors(payload, extract_product_price_requirements(content),
				resolve_uom=resolve_unit, check_amounts=True), [])

	def test_weight_units_are_not_guessed_or_converted_from_price_ratios(self):
		errors = product_price_errors({"stock_uom": "Kg", "retail_rate": 0.1, "wholesale_rate": 90},
			extract_product_price_requirements("0.1元每克，90元每公斤"), resolve_uom=resolve_unit)
		self.assertEqual(len(errors), 1)
		self.assertIn("0.1元每克", errors[0])

	def test_order_reference_price_is_bound_to_unit_not_row_order(self):
		for buying in (False, True):
			price_list = "Standard Buying" if buying else "Standard Selling"
			rows = [{"price_list": price_list, "uom": "Bottle", "rate": 3.5},
				{"price_list": price_list, "uom": "Box", "rate": 30}]
			for ordered in (rows, list(reversed(rows))):
				selected = {"uom": "Bottle", "standard_rate": 3.5,
					"price_summary": {"buying_prices" if buying else "selling_prices": ordered}}
				self.assertEqual(service._authoritative_reference_price(selected, buying=buying, requested_uom="Box")[0], 30)
				self.assertEqual(service._authoritative_reference_price(selected, buying=buying, requested_uom="Bottle")[0], 3.5)
				self.assertIsNone(service._authoritative_reference_price(selected, buying=buying, requested_uom="Kg")[0])

	def test_duplicate_prices_or_missing_unit_never_fall_back_to_arbitrary_rate(self):
		selected = {"uom": "Bottle", "standard_rate": 3.5, "price_summary": {"selling_prices": [
			{"price_list": "Standard Selling", "uom": "Box", "rate": 30},
			{"price_list": "Standard Selling", "uom": "Box", "rate": 40},
		]}}
		self.assertIsNone(service._authoritative_reference_price(selected, buying=False, requested_uom="Box")[0])
		self.assertIsNone(service._authoritative_reference_price({"uom": "Bottle", "standard_rate": 3.5}, buying=False, requested_uom="Box")[0])

	def test_order_unit_change_drops_old_price_and_client_state(self):
		previous = {"item_code": "A", "uom": "Bottle", "price": 3.5, "_state": {"trusted": True}}
		current = {**previous, "uom": "Box", "_state": {"forged": True}}
		result = service._draft_item_with_preserved_context_provenance(current, previous)
		self.assertIsNone(result["price"])
		self.assertNotIn("_state", result)
		result = service._draft_item_with_preserved_context_provenance({**current, "price": 30}, previous)
		self.assertEqual(result["price"], 30)
		result = service._draft_item_with_preserved_context_provenance({**current, "uom": "Bottle"}, previous)
		self.assertEqual(result["_state"], {"trusted": True})

	def test_product_execution_rejects_legacy_or_unrepresentable_prices_before_business_call(self):
		base = {"draft_type": "product_setup", "source_run": "run", "company": "c",
			"payload": {"stock_uom": "Box", "standard_selling_rate": 3.5}}
		with self.assertRaisesRegex(frappe.ValidationError, "缺少价格单位证据"):
			service._check_stored_draft_action(base, user="u")
		base["payload"]["_action_contract"] = {"price_requirements": extract_product_price_requirements("3.5元每瓶")}
		with patch.object(service, "_resolve_product_setup_uom", side_effect=lambda value: (resolve_unit(value), [])):
			with self.assertRaisesRegex(frappe.ValidationError, "基准单位"):
				service._check_stored_draft_action(base, user="u")

	def test_product_locked_evidence_cannot_be_removed_to_pass_validation(self):
		contract = {"scenario": "product_setup_draft", "user": "u", "company": "c", "action": {
			"schema_version": "ai-action-contract-v1", "request_mode": "execute_request", "operations": ["create"]},
			"price_requirements": extract_product_price_requirements("3.5元每瓶")}
		with ExitStack() as stack:
			framework = stack.enter_context(patch.object(repository, "frappe"))
			for name, value in (("_ensure_tables", None), ("now_datetime", "2026-09-08 12:00:00"),
				("_retention_days", 30), ("_insert_draft_version", None), ("get_draft", {})):
				stack.enter_context(patch.object(repository, name, return_value=value))
			stack.enter_context(patch.object(service, "_resolve_product_setup_uom", side_effect=lambda value: (resolve_unit(value), [])))
			framework.db.sql.return_value = [frappe._dict(status="draft", version_no=1, draft_type="product_setup", company="c",
				payload_json=json.dumps({"_action_contract": contract}))]
			framework.as_json.side_effect = json.dumps
			repository.update_draft(draft_id="d", user="u", payload={"operation": "create", "stock_uom": "Box",
				"_action_contract": {"price_requirements": {"quotes": []}}}, validation={"ready_for_handoff": True}, expected_version=1)
			args = framework.db.sql.call_args_list[1].args[1]
			self.assertEqual(json.loads(args[3])["_action_contract"]["price_requirements"]["quotes"][0]["evidence"], "3.5元每瓶")
			self.assertFalse(json.loads(args[4])["ready_for_handoff"])

	def test_sales_and_purchase_edit_and_execution_share_measurement_errors(self):
		for kind in ("sales_order", "purchase_order"):
			for error_key in ("uom_resolution_error", "price_resolution_error"):
				with self.subTest(kind=kind, error_key=error_key), ExitStack() as stack:
					party = "customer" if kind == "sales_order" else "supplier"
					resolver = "_resolve_sales_draft_item" if kind == "sales_order" else "_resolve_purchase_draft_item"
					party_resolver = "_resolve_sales_draft_customer" if kind == "sales_order" else "_resolve_purchase_draft_supplier"
					row = {"item_code": "A", "qty": 1, "uom": "Box", "price": None,
						"warehouse": "W", "warnings": [], error_key: "单位或价格未确认"}
					payload = {party: "P", "warehouse": "W", "currency": "CNY", "items": [row],
						"transaction_date": "2026-09-08", "delivery_date": "2026-09-08", "schedule_date": "2026-09-08"}
					draft = {"draft_type": kind, "company": "c", "payload": payload}
					stack.enter_context(patch.object(service, "_current_user", return_value="u"))
					stack.enter_context(patch.object(service.ai_repository, "get_draft", return_value=draft))
					update = stack.enter_context(patch.object(service.ai_repository, "update_draft", return_value={}))
					stack.enter_context(patch.object(service, party_resolver, return_value=({"name": "P"}, [])))
					stack.enter_context(patch.object(service, resolver, return_value=row))
					stack.enter_context(patch.object(service, "_resolve_sales_draft_warehouse", return_value="W"))
					service._update_ai_draft_once("d", payload, expected_version=1)
					self.assertFalse(update.call_args.kwargs["validation"]["ready_for_handoff"])
					_, validation = service._rebuild_order_draft_before_execution(draft)
					self.assertFalse(validation["ready_for_handoff"])
					self.assertIn("单位或价格未确认", validation["errors"][0])
