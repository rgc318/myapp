from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.services import ai_vector_governance_service
from myapp.services.ai_vector_governance_service import (
	_resource,
	_validate_release,
	approve_ai_vector_release_v1,
	publish_ai_vector_release_v1,
)


def _run_immediately(_namespace, _request_id, callback, **_kwargs):
	return callback()


class TestAiVectorGovernanceService(TestCase):
	@patch("myapp.services.ai_vector_governance_service.frappe.throw", side_effect=frappe.ValidationError)
	def test_vector_resource_names_reject_paths(self, _mock_throw):
		with self.assertRaises(frappe.ValidationError):
			_resource("../myapp-products-v2", "Collection")

	@patch("myapp.services.ai_vector_governance_service.now_datetime", return_value="2026-07-15 12:00:00")
	@patch("myapp.services.ai_vector_governance_service._refresh_counts")
	@patch("myapp.services.ai_vector_governance_service._call_orchestrator")
	def test_release_validation_requires_exact_full_collection_and_gate(
		self, mock_call, mock_counts, _mock_now,
	):
		mock_counts.return_value = {"total_items": 582, "indexed_count": 582, "failed_count": 0}
		mock_call.side_effect = [
			{"collection_exists": True, "points_count": 582, "vector_size": 1024},
			{"release_gate_eligible": True, "errors": [], "warnings": [], "evaluation": {"summary": {"passed": True}}},
		]
		release = SimpleNamespace(
			release_code="products-v2", collection_name="myapp-products-v2",
			alias_name="myapp-products-live", embedding_model="erp-embedding-v2",
			index_version="product-semantic-v2",
		)

		validation = _validate_release(release)

		self.assertTrue(validation["valid"])
		self.assertTrue(validation["release_gate_eligible"])

	@patch("myapp.services.ai_vector_governance_service._ensure_tables")
	@patch("myapp.services.ai_vector_governance_service._require_approver", return_value="manager@example.com")
	@patch("myapp.services.ai_vector_governance_service.run_idempotent", side_effect=_run_immediately)
	@patch("myapp.services.ai_vector_governance_service._get_release")
	@patch("myapp.services.ai_vector_governance_service.frappe.throw", side_effect=frappe.ValidationError)
	def test_production_vector_release_cannot_be_self_approved(
		self, _mock_throw, mock_release, _mock_idempotent, _mock_actor, _mock_tables,
	):
		mock_release.return_value = SimpleNamespace(
			release_code="products-v2", status="review_required", environment="production",
			created_by="manager@example.com",
			validation_json=frappe.as_json({"valid": True, "release_gate_eligible": True}),
		)

		with self.assertRaises(frappe.ValidationError):
			approve_ai_vector_release_v1(
				release_code="products-v2", reason="生产审批", request_id="approve-vector-1",
			)

	@patch("myapp.services.ai_vector_governance_service._record_audit")
	@patch("myapp.services.ai_vector_governance_service._ensure_tables")
	@patch("myapp.services.ai_vector_governance_service._require_system_manager", return_value="admin@example.com")
	@patch("myapp.services.ai_vector_governance_service.run_idempotent", side_effect=_run_immediately)
	@patch("myapp.services.ai_vector_governance_service._get_release")
	@patch("myapp.services.ai_vector_governance_service._validate_release")
	@patch("myapp.services.ai_vector_governance_service._call_orchestrator")
	def test_publish_uses_atomic_alias_switch_and_supersedes_previous_release(
		self, mock_call, mock_validate, mock_release, _mock_idempotent,
		_mock_actor, _mock_tables, mock_audit,
	):
		mock_release.return_value = SimpleNamespace(
			release_code="products-v2", status="approved", alias_name="myapp-products-live",
			collection_name="myapp-products-v2",
		)
		mock_validate.return_value = {
			"valid": True, "release_gate_eligible": True,
			"provider": {"vector_size": 1024},
		}
		mock_call.return_value = {
			"previous_collection": "myapp-products-v1", "vector_size": 1024,
		}
		with patch.object(ai_vector_governance_service, "frappe") as mock_frappe, patch(
			"myapp.services.ai_vector_governance_service.now_datetime",
			return_value="2026-07-15 12:00:00",
		):
			mock_frappe.as_json.side_effect = frappe.as_json
			result = publish_ai_vector_release_v1(
				release_code="products-v2", reason="通过完整门禁后发布", request_id="publish-vector-1",
			)

		self.assertEqual(result["data"]["status"], "active")
		self.assertEqual(result["data"]["previous_collection"], "myapp-products-v1")
		mock_call.assert_called_once_with(
			"/internal/v1/vector/governance/switch-alias",
			payload={
				"alias_name": "myapp-products-live",
				"target_collection": "myapp-products-v2",
			},
			method="POST",
		)
		self.assertGreaterEqual(mock_frappe.db.sql.call_count, 2)
		mock_audit.assert_called_once()
