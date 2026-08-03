from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.services.ai_model_governance_service import (
	_normalize_model_metadata_payload,
	_normalize_policy_payload,
	_validate_budget_and_cost,
	_validate_policy_conflicts,
	_validate_registry_models,
	approve_ai_model_policy_v1,
	check_ai_model_availability_v1,
	get_ai_model_governance_overview_v1,
	list_ai_selectable_models_v1,
	list_ai_audit_events_v1,
	publish_ai_model_policy_v1,
	resolve_ai_agent_runtime_readiness,
	resolve_ai_selected_model_alias,
	validate_ai_model_policy_v1,
	update_ai_model_registry_v1,
)
from myapp.services import ai_model_governance_service


def _run_immediately(_namespace, _request_id, callback, **_kwargs):
	return callback()


class TestAiModelGovernanceService(TestCase):
	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	def test_runtime_readiness_is_safe_when_no_policy_is_published(self, _mock_tables):
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.db.sql.return_value = []
			result = resolve_ai_agent_runtime_readiness(
				scenario="product_search", environment="staging",
				company="Demo Company", user="user@example.com",
			)

		self.assertEqual(result, {
			"ready": False, "reason": "no_published_policy", "policy_code": None,
		})

	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	def test_runtime_readiness_matches_scope_and_requires_tools_on_all_models(self, _mock_tables):
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.get_roles.return_value = ["Sales User"]
			mock_frappe.db.sql.side_effect = [
				[SimpleNamespace(
					policy_code="product-demo", published_version=3,
					snapshot_json=frappe.as_json({
						"scenario": "product_search", "environment": "staging",
						"company_scope": ["Demo Company"], "role_scope": ["Sales User"],
						"rollout_percentage": "100", "primary_model_alias": "erp-fast-chat",
						"fallback_model_aliases": ["erp-fallback"],
					}),
				)],
				[
					SimpleNamespace(model_alias="erp-fast-chat", status="active", supports_tools=1),
					SimpleNamespace(model_alias="erp-fallback", status="validated", supports_tools=0),
				],
			]
			result = resolve_ai_agent_runtime_readiness(
				scenario="product_search", environment="staging",
				company="Demo Company", user="user@example.com",
			)

		self.assertFalse(result["ready"])
		self.assertEqual(result["reason"], "model_tools_unverified")
		self.assertEqual(result["policy_code"], "product-demo")
		self.assertEqual(result["unverified_model_aliases"], ["erp-fallback"])

	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	def test_runtime_readiness_rejects_ambiguous_highest_priority_policies(self, _mock_tables):
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.get_roles.return_value = []
			policy = {
				"scenario": "general", "environment": "staging", "rollout_percentage": "100",
				"primary_model_alias": "erp-fast-chat", "fallback_model_aliases": [],
			}
			mock_frappe.db.sql.return_value = [
				SimpleNamespace(policy_code="general-a", published_version=1, snapshot_json=frappe.as_json(policy)),
				SimpleNamespace(policy_code="general-b", published_version=1, snapshot_json=frappe.as_json(policy)),
			]
			result = resolve_ai_agent_runtime_readiness(
				scenario="general", environment="staging",
				company="Demo Company", user="user@example.com",
			)

		self.assertEqual(result["reason"], "ambiguous_policy")
		self.assertFalse(result["ready"])

	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	def test_runtime_readiness_accepts_unique_policy_and_explicit_tool_model(self, _mock_tables):
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.get_roles.return_value = ["Sales User"]
			mock_frappe.db.sql.side_effect = [
				[SimpleNamespace(
					policy_code="general-staging", published_version=2,
					snapshot_json=frappe.as_json({
						"scenario": "general", "environment": "staging",
						"company_scope": [], "role_scope": [], "rollout_percentage": "100",
						"primary_model_alias": "erp-fast-chat", "fallback_model_aliases": [],
					}),
				)],
				[
					SimpleNamespace(model_alias="erp-fast-chat", status="active", supports_tools=1),
					SimpleNamespace(model_alias="erp-fixed", status="validated", supports_tools=1),
				],
			]
			result = resolve_ai_agent_runtime_readiness(
				scenario="general", environment="staging", company="Demo Company",
				user="user@example.com", model_alias="erp-fixed",
			)

		self.assertEqual(result, {
			"ready": True, "reason": "ready", "policy_code": "general-staging",
			"policy_version": 2,
		})

	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	def test_runtime_readiness_uses_compatibility_fallback_for_scope_mismatch(self, _mock_tables):
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.get_roles.return_value = ["Sales User"]
			mock_frappe.db.sql.return_value = [SimpleNamespace(
				policy_code="product-other", published_version=1,
				snapshot_json=frappe.as_json({
					"scenario": "product_search", "environment": "staging",
					"company_scope": ["Other Company"], "role_scope": ["Sales User"],
					"rollout_percentage": "100", "primary_model_alias": "erp-fast-chat",
				}),
			)]
			result = resolve_ai_agent_runtime_readiness(
				scenario="product_search", environment="staging",
				company="Demo Company", user="user@example.com",
			)

		self.assertEqual(result["reason"], "no_matching_policy")
		self.assertFalse(result["ready"])

	@patch("myapp.services.ai_model_governance_service._record_audit")
	@patch("myapp.services.ai_model_governance_service._call_orchestrator")
	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	@patch("myapp.services.ai_model_governance_service._require_manager", return_value="manager@example.com")
	@patch("myapp.services.ai_model_governance_service.run_idempotent", side_effect=_run_immediately)
	def test_availability_check_updates_health_without_changing_governance_status(
		self, _mock_idempotent, _mock_actor, _mock_tables, mock_orchestrator, mock_audit,
	):
		mock_orchestrator.return_value = {
			"source": "litellm",
			"items": [
				{
					"model_alias": "erp-fast-chat", "capability": "fast_chat",
					"available": True, "latency_ms": 123.8,
					"provider_model": "openai/gpt-5", "error_code": None,
				},
				{
					"model_alias": "erp-embedding", "capability": "embedding",
					"available": False, "latency_ms": 456.2,
					"provider_model": None, "error_code": "PROVIDER_HTTP_429",
				},
			],
		}
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe, patch(
			"myapp.services.ai_model_governance_service.now_datetime",
			return_value="2026-07-22 18:00:00",
		):
			mock_frappe.db.sql.side_effect = [
				[
					frappe._dict(model_alias="erp-embedding"),
					frappe._dict(model_alias="erp-fast-chat"),
				],
				None,
				None,
			]
			result = check_ai_model_availability_v1(request_id="health-1")

		self.assertEqual(result["data"]["checked_count"], 2)
		self.assertEqual(result["data"]["available_count"], 1)
		self.assertEqual(result["data"]["unavailable_count"], 1)
		mock_orchestrator.assert_called_once_with(
			"/internal/v1/governance/models/availability",
			payload={"model_aliases": ["erp-embedding", "erp-fast-chat"]},
			method="POST",
			timeout=180,
		)
		update_calls = mock_frappe.db.sql.call_args_list[1:]
		self.assertTrue(all("SET last_health_at" in call.args[0] for call in update_calls))
		self.assertTrue(all("SET status" not in call.args[0] for call in update_calls))
		self.assertEqual(update_calls[0].args[1][1], "available")
		self.assertEqual(update_calls[1].args[1][1], "unavailable")
		self.assertEqual(update_calls[1].args[1][2], "PROVIDER_HTTP_429")
		mock_audit.assert_called_once()
		self.assertEqual(mock_audit.call_args.kwargs["action"], "check_model_availability")

	@patch("myapp.services.ai_model_governance_service._record_audit")
	@patch("myapp.services.ai_model_governance_service._call_orchestrator")
	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	@patch("myapp.services.ai_model_governance_service._require_manager", return_value="manager@example.com")
	@patch("myapp.services.ai_model_governance_service.run_idempotent", side_effect=_run_immediately)
	def test_availability_check_limits_provider_calls_to_selected_models(
		self, _idempotent, _actor, _tables, mock_orchestrator, mock_audit,
	):
		mock_orchestrator.return_value = {
			"source": "litellm",
			"items": [{
				"model_alias": "gpt-5.5", "capability": "structured",
				"available": True, "latency_ms": 210,
				"provider_model": "openai/gpt-5.5", "error_code": None,
			}],
		}
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe, patch(
			"myapp.services.ai_model_governance_service.now_datetime",
			return_value="2026-08-01 12:00:00",
		):
			mock_frappe.db.sql.side_effect = [
				[frappe._dict(model_alias="gpt-5.5")],
				None,
			]
			result = check_ai_model_availability_v1(
				model_aliases=["gpt-5.5"],
				request_id="health-selected-1",
			)

		self.assertEqual(result["data"]["requested_count"], 1)
		self.assertEqual(result["data"]["trigger"], "manual_selected")
		mock_orchestrator.assert_called_once_with(
			"/internal/v1/governance/models/availability",
			payload={"model_aliases": ["gpt-5.5"]},
			method="POST",
			timeout=180,
		)
		self.assertIn("model_alias IN (%s)", mock_frappe.db.sql.call_args_list[0].args[0])
		self.assertEqual(mock_audit.call_args.kwargs["parameters"]["trigger"], "manual_selected")

	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	@patch("myapp.services.ai_model_governance_service._current_user", return_value="user@example.com")
	def test_selectable_models_only_include_active_chat_capabilities(self, _user, _tables):
		rows = [
			frappe._dict(
				model_alias="gpt-5.5", capability="fast_chat", provider_model_display="GPT 5.5",
				supports_streaming=1, supports_json_schema=0, status="active",
				last_health_at="2026-08-03 09:00:00", last_health_status="available",
				last_error_code=None,
			),
			frappe._dict(
				model_alias="opencode-glm-5.2", capability="reasoning", provider_model_display=None,
				supports_streaming=1, supports_json_schema=1, status="validated",
			),
		]
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.get_roles.return_value = ["AI Model Manager"]
			mock_frappe.db.sql.return_value = rows
			result = list_ai_selectable_models_v1()

		self.assertEqual(
			[item["model_alias"] for item in result["data"]["items"]],
			["gpt-5.5", "opencode-glm-5.2"],
		)
		self.assertTrue(result["data"]["capabilities"]["can_select_fixed_model"])
		self.assertTrue(result["data"]["capabilities"]["can_view_advanced_diagnostics"])
		self.assertEqual(result["data"]["items"][0]["last_health_status"], "available")
		self.assertIn("status IN ('active', 'validated')", mock_frappe.db.sql.call_args.args[0])
		self.assertIn("capability IN ('fast_chat', 'reasoning', 'structured')", mock_frappe.db.sql.call_args.args[0])

	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	@patch("myapp.services.ai_model_governance_service._current_user", return_value="user@example.com")
	def test_selectable_models_hide_fixed_model_inventory_from_business_users(self, _user, _tables):
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.get_roles.return_value = ["Sales User"]
			result = list_ai_selectable_models_v1()

		self.assertEqual(result["data"]["items"], [])
		self.assertEqual(result["data"]["capabilities"], {
			"can_select_fixed_model": False,
			"can_view_advanced_diagnostics": False,
		})
		mock_frappe.db.sql.assert_not_called()

	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	@patch("myapp.services.ai_model_governance_service._current_user", return_value="user@example.com")
	def test_approvers_and_auditors_can_view_diagnostics_without_fixed_model_inventory(
		self, _user, _tables,
	):
		for role in ("AI Model Approver", "AI Auditor"):
			with self.subTest(role=role), patch.object(
				ai_model_governance_service, "frappe",
			) as mock_frappe:
				mock_frappe.get_roles.return_value = [role]
				result = list_ai_selectable_models_v1()

				self.assertEqual(result["data"]["items"], [])
				self.assertEqual(result["data"]["capabilities"], {
					"can_select_fixed_model": False,
					"can_view_advanced_diagnostics": True,
				})
				mock_frappe.db.sql.assert_not_called()

	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	@patch("myapp.services.ai_model_governance_service._current_user", return_value="user@example.com")
	def test_selected_model_rejects_unavailable_or_embedding_alias(self, _user, _tables):
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.get_roles.return_value = ["AI Model Manager"]
			mock_frappe.db.sql.return_value = []
			mock_frappe.throw.side_effect = frappe.ValidationError
			with self.assertRaises(frappe.ValidationError):
				resolve_ai_selected_model_alias("erp-embedding")

	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	@patch("myapp.services.ai_model_governance_service._current_user", return_value="user@example.com")
	def test_selected_model_returns_registered_active_alias(self, _user, _tables):
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.get_roles.return_value = ["AI Model Manager"]
			mock_frappe.db.sql.return_value = [frappe._dict(model_alias="opencode-glm-5.2")]
			result = resolve_ai_selected_model_alias("opencode-glm-5.2")

		self.assertEqual(result, "opencode-glm-5.2")

	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	@patch("myapp.services.ai_model_governance_service._current_user", return_value="user@example.com")
	def test_selected_model_rejects_latest_unavailable_health(self, _user, _tables):
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.get_roles.return_value = ["AI Model Manager"]
			mock_frappe.ValidationError = frappe.ValidationError
			mock_frappe.throw.side_effect = frappe.ValidationError
			mock_frappe.db.sql.return_value = [frappe._dict(
				model_alias="opencode-deepseek-v4-flash",
				last_health_status="unavailable",
			)]

			with self.assertRaises(frappe.ValidationError):
				resolve_ai_selected_model_alias("opencode-deepseek-v4-flash")

	@patch("myapp.services.ai_model_governance_service._current_user", return_value="user@example.com")
	def test_selected_model_rejects_business_user_override(self, _user):
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.get_roles.return_value = ["Sales User"]
			mock_frappe.PermissionError = frappe.PermissionError
			with self.assertRaises(frappe.PermissionError):
				resolve_ai_selected_model_alias("opencode-glm-5.2")

		mock_frappe.db.sql.assert_not_called()

	@patch("myapp.services.ai_model_governance_service._call_orchestrator")
	@patch("myapp.services.ai_model_governance_service._require_viewer")
	def test_governance_overview_aggregates_runtime_usage_tasks_and_vectors(
		self, _viewer, mock_orchestrator,
	):
		mock_orchestrator.return_value = {
			"status": "ok", "model_alias": "erp-fast-chat",
			"embedding_model": "erp-embedding", "vector_collection": "products-live",
			"vector_search_configured": True, "runtime_governance_configured": True,
			"langfuse_configured": True, "prompt_versions": {"general": "v5"},
		}
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.conf = {}
			mock_frappe.db.table_exists.return_value = True
			mock_frappe.db.sql.side_effect = [
				[frappe._dict(status="active", count=2)],
				[frappe._dict(status="active", count=1)],
				[],
				[frappe._dict(status="review_required", count=3)],
				[frappe._dict(status="indexed", count=140), frappe._dict(status="failed", count=3)],
				[frappe._dict(
					request_count=20, success_count=19, error_count=1, total_tokens=1200,
					estimated_cost=2.5, cost_currency="CNY", latency_p95_ms=1800,
					first_token_p95_ms=500,
				)],
				[frappe._dict(last_health_at="2026-08-01 03:15:00")],
			]
			result = get_ai_model_governance_overview_v1()

		self.assertTrue(result["data"]["runtime"]["reachable"])
		self.assertEqual(result["data"]["data_task_counts"]["review_required"], 3)
		self.assertEqual(result["data"]["vector_counts"]["failed"], 3)
		self.assertEqual(result["data"]["usage_7d"]["request_count"], 20)
		self.assertTrue(result["data"]["model_health_schedule"]["enabled"])
		self.assertEqual(
			result["data"]["model_health_schedule"]["last_health_at"],
			"2026-08-01 03:15:00",
		)

	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	@patch("myapp.services.ai_model_governance_service._require_viewer")
	def test_audit_list_is_filtered_and_paginated(self, _viewer, _tables):
		row = frappe._dict({
			"name": "AI-AUDIT-1", "actor": "admin@example.com", "action": "publish_policy",
			"object_type": "model_policy", "object_name": "general-prod",
			"reason": "正式发布", "priority": "high", "parameter_hash": "a" * 64,
			"result_hash": "b" * 64, "metadata_json": '{"result":{"status":"active"}}',
			"creation": "2026-07-16 10:00:00",
		})
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.db.sql.side_effect = [[frappe._dict(total=1)], [row]]
			result = list_ai_audit_events_v1(
				search="general", object_type="model_policy", priority="high",
				date_from="2026-07-01", date_to="2026-07-16", start=20, limit=10,
			)

		self.assertEqual(result["data"]["pagination"]["total"], 1)
		self.assertEqual(result["data"]["items"][0]["metadata"]["result"]["status"], "active")
		self.assertEqual(mock_frappe.db.sql.call_args_list[1].args[1][-2:], (10, 20))

	def test_policy_validation_requires_model_region_and_retention_review(self):
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.db.sql.return_value = [frappe._dict({
				"model_alias": "erp-fast-chat", "capability": "fast_chat", "status": "active",
				"supports_json_schema": 0, "data_region": None, "retention_policy": None,
			})]
			errors = _validate_registry_models({
				"primary_model_alias": "erp-fast-chat", "fallback_model_aliases": [],
				"capability": "fast_chat",
			})

		self.assertTrue(any("数据区域" in error for error in errors))
		self.assertTrue(any("留存策略" in error for error in errors))

	@patch("myapp.services.ai_model_governance_service.frappe.throw", side_effect=frappe.ValidationError)
	def test_model_metadata_rejects_provider_managed_fields(self, _mock_throw):
		with self.assertRaises(frappe.ValidationError):
			_normalize_model_metadata_payload({"provider_family": "openai"})

	@patch("myapp.services.ai_model_governance_service._record_audit")
	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	@patch("myapp.services.ai_model_governance_service._require_manager", return_value="manager@example.com")
	@patch("myapp.services.ai_model_governance_service.run_idempotent", side_effect=_run_immediately)
	def test_model_metadata_update_is_versioned_and_reports_active_policy_impact(
		self, _mock_idempotent, _mock_actor, _mock_tables, mock_audit,
	):
		model = frappe._dict({
			"model_alias": "erp-fast-chat", "capability": "fast_chat", "status": "discovered",
			"provider_family": "openai", "provider_model_display": "Fast Chat",
			"supports_streaming": 1, "supports_json_schema": 0, "supports_vision": 0,
			"embedding_dimensions": None, "embedding_space_version": None,
			"data_region": None, "retention_policy": None, "sensitive_data_allowed": 0,
			"input_cost": "0", "output_cost": "0", "currency": None,
			"last_health_at": None, "last_health_status": "healthy", "last_error_code": None,
			"registry_version": 1, "modified": "2026-07-14 12:00:00",
		})
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe, patch(
			"myapp.services.ai_model_governance_service.now_datetime",
			return_value="2026-07-15 09:00:00",
		):
			mock_frappe.db.sql.side_effect = [[model], [frappe._dict(policy_code="general-prod")], None]
			result = update_ai_model_registry_v1(
				model_alias="erp-fast-chat",
				payload={
					"status": "active", "data_region": "cn-east", "retention_policy": "no-training-30d",
					"input_cost": "1.5", "output_cost": "4", "currency": "cny",
				},
				reason="完成供应商数据治理复核", request_id="model-update-1",
			)

		self.assertEqual(result["data"]["model"]["registry_version"], 2)
		self.assertEqual(result["data"]["model"]["currency"], "CNY")
		self.assertEqual(result["data"]["affected_active_policies"], ["general-prod"])
		mock_audit.assert_called_once()

	def test_conflicting_active_company_role_policy_is_rejected(self):
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.db.sql.return_value = [frappe._dict(
				policy_code="existing-policy",
				snapshot_json=frappe.as_json({
					"scenario": "general", "environment": "production",
					"company_scope": ["Demo Company"], "role_scope": ["Sales Manager"],
					"effective_from": None, "effective_to": None,
				}),
			)]
			errors = _validate_policy_conflicts({
				"scenario": "general", "environment": "production",
				"company_scope": ["Demo Company"], "role_scope": ["Sales Manager", "Sales User"],
				"effective_from": None, "effective_to": None,
			}, exclude_policy_code="new-policy")

		self.assertEqual(len(errors), 1)
		self.assertIn("existing-policy", errors[0])

	def test_global_role_scope_without_company_is_rejected(self):
		errors = _validate_policy_conflicts({
			"scenario": "general", "environment": "production",
			"company_scope": [], "role_scope": ["Sales Manager"],
		}, exclude_policy_code="invalid-role-policy")

		self.assertTrue(errors)

	def test_lower_cost_budget_action_requires_fallback_model(self):
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.db.sql.return_value = []
			errors = _validate_budget_and_cost({
				"primary_model_alias": "erp-fast-chat", "fallback_model_aliases": [],
				"daily_budget": "10", "monthly_budget": "100", "budget_currency": "CNY",
				"budget_action": "use_lower_cost_fallback",
			})

		self.assertTrue(any("降级模型" in error for error in errors))

	def test_lower_cost_budget_action_rejects_fallback_that_is_not_strictly_cheaper(self):
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.db.sql.return_value = [
				frappe._dict(model_alias="primary", currency="CNY", input_cost="2", output_cost="8"),
				frappe._dict(model_alias="fallback", currency="CNY", input_cost="1", output_cost="9"),
			]
			errors = _validate_budget_and_cost({
				"primary_model_alias": "primary", "fallback_model_aliases": ["fallback"],
				"daily_budget": "10", "monthly_budget": "100", "budget_currency": "CNY",
				"budget_action": "use_lower_cost_fallback",
			})

		self.assertTrue(any("至少一项更低" in error for error in errors))

	def test_budget_governance_requires_registered_cost_and_currency(self):
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe:
			mock_frappe.db.sql.return_value = [
				frappe._dict(model_alias="primary", currency=None, input_cost="0", output_cost="0"),
			]
			errors = _validate_budget_and_cost({
				"primary_model_alias": "primary", "fallback_model_aliases": [],
				"daily_budget": "10", "monthly_budget": "100", "budget_currency": "CNY",
				"budget_action": "reject_noncritical",
			})

		self.assertTrue(any("成本币种" in error for error in errors))
		self.assertTrue(any("有效成本" in error for error in errors))

	@patch("myapp.services.ai_model_governance_service.frappe.throw", side_effect=frappe.ValidationError)
	def test_policy_payload_rejects_primary_model_in_fallback_chain(self, _mock_throw):
		with self.assertRaises(frappe.ValidationError):
			_normalize_policy_payload({
				"policy_code": "general-default",
				"policy_name": "通用助手默认策略",
				"scenario": "general",
				"capability": "fast_chat",
				"primary_model_alias": "erp-fast-chat",
				"fallback_model_aliases": ["erp-fast-chat"],
			})

	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	@patch("myapp.services.ai_model_governance_service._require_approver", return_value="manager@example.com")
	@patch("myapp.services.ai_model_governance_service.run_idempotent", side_effect=_run_immediately)
	@patch("myapp.services.ai_model_governance_service._get_policy")
	@patch("myapp.services.ai_model_governance_service._get_policy_version")
	@patch("myapp.services.ai_model_governance_service.frappe.throw", side_effect=frappe.ValidationError)
	def test_production_policy_cannot_be_self_approved(
		self, _mock_throw, mock_version, mock_policy, _mock_idempotent, _mock_actor, _mock_tables,
	):
		mock_policy.return_value = SimpleNamespace(
			policy_code="general-prod", current_version=1,
			status="review_required", environment="production",
		)
		mock_version.return_value = SimpleNamespace(status="review_required", created_by="manager@example.com")

		with self.assertRaises(frappe.ValidationError):
			approve_ai_model_policy_v1(
				policy_code="general-prod", reason="生产发布审批", request_id="approve-1",
			)

	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	@patch("myapp.services.ai_model_governance_service._require_system_manager", return_value="admin@example.com")
	@patch("myapp.services.ai_model_governance_service.run_idempotent", side_effect=_run_immediately)
	@patch("myapp.services.ai_model_governance_service._get_policy")
	@patch("myapp.services.ai_model_governance_service._get_policy_version")
	@patch("myapp.services.ai_model_governance_service.frappe.throw", side_effect=frappe.ValidationError)
	def test_publish_rejects_policy_without_full_release_gate(
		self, _mock_throw, mock_version, mock_policy, _mock_idempotent, _mock_actor, _mock_tables,
	):
		mock_policy.return_value = SimpleNamespace(
			policy_code="general-prod", current_version=2, published_version=1, status="approved",
		)
		mock_version.return_value = SimpleNamespace(
			status="approved", validation_json=frappe.as_json({"valid": True, "release_gate_eligible": False}),
		)

		with self.assertRaises(frappe.ValidationError):
			publish_ai_model_policy_v1(
				policy_code="general-prod", reason="尝试发布", request_id="publish-1",
			)

	@patch("myapp.services.ai_model_governance_service._record_audit")
	@patch("myapp.services.ai_model_governance_service._ensure_tables")
	@patch("myapp.services.ai_model_governance_service._require_manager", return_value="manager@example.com")
	@patch("myapp.services.ai_model_governance_service.run_idempotent", side_effect=_run_immediately)
	@patch("myapp.services.ai_model_governance_service._get_policy")
	@patch("myapp.services.ai_model_governance_service._get_policy_version")
	@patch("myapp.services.ai_model_governance_service._validate_registry_models", return_value=[])
	@patch("myapp.services.ai_model_governance_service._call_orchestrator")
	def test_validation_keeps_policy_in_draft_when_live_gate_is_missing(
		self, mock_orchestrator, _mock_registry, mock_version, mock_policy,
		_mock_idempotent, _mock_actor, _mock_tables, _mock_audit,
	):
		mock_policy.return_value = SimpleNamespace(policy_code="general-prod", current_version=1)
		mock_version.return_value = SimpleNamespace(snapshot_json=frappe.as_json({
			"policy_code": "general-prod", "scenario": "general", "capability": "fast_chat",
			"primary_model_alias": "erp-fast-chat", "fallback_model_aliases": [],
		}))
		mock_orchestrator.return_value = {
			"release_gate_eligible": False,
			"errors": ["live gate missing"],
			"warnings": [],
			"evaluation": {"offline": {"passed": True}},
		}
		with patch.object(ai_model_governance_service, "frappe") as mock_frappe, patch(
			"myapp.services.ai_model_governance_service.now_datetime",
			return_value="2026-07-14 12:00:00",
		):
			mock_frappe.as_json.side_effect = frappe.as_json
			result = validate_ai_model_policy_v1(policy_code="general-prod", request_id="validate-1")

		self.assertEqual(result["data"]["status"], "draft")
		self.assertFalse(result["data"]["validation"]["valid"])
		self.assertGreaterEqual(mock_frappe.db.sql.call_count, 2)
