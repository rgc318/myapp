from contextlib import nullcontext
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.ai_service import (
	_build_draft_version_diff,
	_build_inventory_adjustment_draft,
	_build_order_query_context,
	_build_order_query_dsl,
	_build_product_setup_draft,
	_execute_ai_draft_payload,
	_build_report_query_dsl,
	_update_ai_draft_once,
	_hybrid_rerank_product_rows,
	_extract_product_search_terms,
	_infer_ai_scenario,
	_infer_ai_action_scenario,
	_prepare_chat_run,
	_query_business_document_entity,
	_resolve_inventory_draft_item,
	_resolve_purchase_draft_item,
	_resolve_prompt_version,
	_resolve_sales_draft_item,
	chat_ai_v1,
	execute_ai_draft_v1,
	generate_ai_inventory_adjustment_draft_v1,
	generate_ai_purchase_order_draft_v1,
	generate_ai_sales_order_draft_v1,
	list_ai_drafts_v1,
	stream_ai_message_v1,
	submit_ai_feedback_v1,
	update_ai_draft_v1,
)
from myapp.utils.api_response import UpstreamServiceUnavailableError, map_exception_to_error


class TestAiService(TestCase):
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
				"standard_buying_rate": 60, "buying_prices": [{"rate": 60}],
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
	@patch("myapp.services.ai_service.create_product_v2")
	def test_execute_product_setup_draft_reuses_product_domain_service(self, mock_create):
		mock_create.return_value = {"status": "success", "data": {"item_code": "ITEM-001"}}
		result = _execute_ai_draft_payload({
			"draft_type": "product_setup",
			"payload": {
				"item_name": "煌星", "item_code": "ITEM-001", "company": "Demo Company",
				"item_group": "Products", "brand": "Brand A", "stock_uom": "Unit",
				"standard_selling_rate": 10000, "standard_buying_rate": 5000,
				"currency": "CNY", "warehouse": "Stores - DC", "opening_qty": 5,
				"opening_uom": "Unit", "description": "测试商品",
			},
		}, request_id="REQ-1")

		self.assertEqual(result["target_doctype"], "Item")
		self.assertEqual(result["target_name"], "ITEM-001")
		mock_create.assert_called_once_with(
			item_name="煌星", item_code="ITEM-001", item_group="Products", brand="Brand A",
			stock_uom="Unit", standard_rate=10000, valuation_rate=5000, currency="CNY",
			buying_prices=[{"price_list": "Standard Buying", "rate": 5000, "currency": "CNY"}],
			description="测试商品", company="Demo Company", warehouse="Stores - DC",
			warehouse_stock_qty=5, warehouse_stock_uom="Unit", request_id="REQ-1",
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

	@patch("myapp.services.ai_service.run_idempotent", side_effect=lambda _namespace, _request_id, callback, **_kwargs: callback())
	@patch("myapp.services.ai_service.filelock", side_effect=lambda *_args, **_kwargs: nullcontext())
	@patch("myapp.services.ai_service._record_ai_draft_execution_audit")
	@patch("myapp.services.ai_service._execute_ai_draft_payload")
	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	def test_execute_ai_draft_checks_version_and_persists_receipt(
		self, _user, mock_execute, _audit, _lock, _idempotent,
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
	@patch("myapp.services.ai_service._resolve_company_scope", side_effect=lambda company, required=False: company)
	@patch("myapp.services.ai_service._current_user", return_value="user@example.com")
	def test_existing_conversation_uses_its_persisted_company_when_request_omits_company(
		self, _current_user, mock_resolve_company,
	):
		with patch("myapp.services.ai_service.ai_repository.get_conversation") as mock_get, patch(
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
			{"payload": {"customer": "CUST-1", "items": [{"item_code": "ITEM-1", "qty": 1, "uom": "Box"}]}},
			{"payload": {"customer": "CUST-2", "items": [
				{"item_code": "ITEM-1", "qty": 2, "uom": "Box"},
				{"item_code": "ITEM-2", "qty": 1, "uom": "Nos"},
			]}},
		)

		self.assertEqual(diff["fields"][0]["field"], "customer")
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
			"draft": {"customer_query": "客户A", "items": [{"item_query": "相机", "qty": 2}]},
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
		self.assertTrue(mock_create_draft.call_args.kwargs["validation"]["ready_for_handoff"])
		self.assertEqual(_complete.call_args.kwargs["tool_calls"][0]["risk_level"], "L2_DRAFT_ONLY")
		expected_prompt_version = _resolve_prompt_version("sales_order_draft")
		self.assertEqual(mock_call.call_args.args[0]["prompt_version"], expected_prompt_version)
		self.assertEqual(
			{call.kwargs["prompt_version"] for call in _append.call_args_list},
			{expected_prompt_version},
		)

	def test_prompt_versions_are_mapped_by_scenario(self):
		self.assertEqual(_resolve_prompt_version("general"), "erp-readonly-v7")
		draft_versions = {
			"sales_order_draft": "sales-order-draft-v2",
			"purchase_order_draft": "purchase-order-draft-v2",
			"inventory_adjustment_draft": "inventory-adjustment-draft-v2",
			"product_setup_draft": "product-setup-draft-v1",
		}
		for scenario, expected in draft_versions.items():
			with self.subTest(scenario=scenario):
				self.assertEqual(_resolve_prompt_version(scenario), expected)
				self.assertNotEqual(expected, "erp-readonly-v7")

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
		self.assertEqual(_infer_ai_scenario("你可以做什么"), "general")

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
		self.assertEqual(_extract_product_search_terms("煌星现在有现货吗"), ["煌星"])

	@patch("myapp.services.ai_service._resolve_sales_draft_warehouse", return_value="Stores - TC")
	@patch("myapp.services.ai_service._resolve_optional_master_name", return_value=None)
	@patch("myapp.services.ai_service._resolve_product_setup_uom", return_value=("Unit", [{"name": "Unit"}]))
	def test_product_setup_draft_keeps_selling_price_separate_from_default_buying_price(
		self, _uom, _master, _warehouse,
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
	def test_product_setup_draft_accepts_default_buying_price_for_opening_stock(
		self, _uom, _master, _warehouse,
	):
		with patch("myapp.services.ai_service.frappe") as mock_frappe:
			mock_frappe.db.exists.return_value = False
			mock_frappe.db.get_value.return_value = "CNY"
			mock_frappe.has_permission.return_value = True
			payload, validation = _build_product_setup_draft(
				{
					"item_name": "传承结晶", "opening_qty": 1000,
					"stock_uom": "Unit", "standard_selling_rate": 9999,
					"standard_buying_rate": 5000, "warehouse": "Stores - TC",
				},
				company="Test Company",
			)

		self.assertEqual(payload["standard_buying_rate"], 5000)
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
			([{"document_type": "sales_order", "name": "SO-1", "party": "客户A"}], {"total": 1}),
			([{"document_type": "sales_invoice", "name": "SI-1", "party": "客户A"}], {"total": 1}),
			([{"document_type": "purchase_order", "name": "PO-1", "party": "供应商A"}], {"total": 1}),
		]

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
		self.assertEqual(citations[0]["data"]["scope"]["limit_per_group"], 5)
		self.assertEqual(
			[group["status"] for group in citations[0]["data"]["groups"]],
			["partial", "partial", "partial"],
		)
		self.assertEqual([call["tool"] for call in tool_calls], [
			"search_sales_orders", "list_sales_invoices", "search_purchase_orders",
		])

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
			"scenario": "general",
			"conversation_id": "AI-CONV-1",
			"run_id": "AI-RUN-1",
			"started": 1,
			"citations": [],
			"tool_calls": [],
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
		mock_complete.assert_called_once()
		self.assertEqual(mock_complete.call_args.args[2], "你好")
		self.assertGreaterEqual(mock_complete.call_args.kwargs["first_token_ms"], 0)

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

		with patch("myapp.services.ai_service.frappe") as mock_frappe:
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
		self.assertEqual(mock_complete_run.call_args.kwargs["tool_calls"][0]["risk_level"], "L1_READ_ONLY")

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

		with patch("myapp.services.ai_service.frappe") as mock_frappe:
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
		self.assertEqual(mock_complete_run.call_args.kwargs["tool_calls"][0]["risk_level"], "L1_READ_ONLY")

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
