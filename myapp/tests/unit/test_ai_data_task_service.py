from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from myapp.services import ai_data_task_service
from myapp.services.ai_data_task_service import (
	_normalize_changes,
	_task_actions,
	execute_ai_data_task_v1,
	review_ai_data_task_v1,
	rollback_ai_data_task_v1,
)


def _run_immediately(_namespace, _request_id, callback, **_kwargs):
	return callback()


def _task(**overrides):
	values = {
		"name": "AI-DATA-1", "status": "approved", "risk_level": "low",
		"requested_by": "steward@example.com", "reviewer": "approver@example.com",
		"target_name": "ITEM-001", "before_value_json": frappe.as_json({"description": "old"}),
		"proposed_value_json": frappe.as_json({"description": "new"}), "version_no": 1,
	}
	values.update(overrides)
	return SimpleNamespace(**values)


class TestAiDataTaskService(TestCase):
	def test_task_actions_apply_role_and_separation_rules(self):
		with patch.object(ai_data_task_service.frappe, "get_roles") as get_roles:
			get_roles.return_value = ["AI Data Approver"]
			approver_actions = _task_actions(
				_task(status="review_required"), "approver@example.com",
			)
			requester_actions = _task_actions(
				_task(status="review_required"), "steward@example.com",
			)

		self.assertTrue(approver_actions["approve"]["allowed"])
		self.assertFalse(requester_actions["approve"]["allowed"])
		self.assertIn("不能审批", requester_actions["approve"]["reason"])

	@patch("myapp.services.ai_data_task_service.frappe.throw", side_effect=frappe.ValidationError)
	def test_product_change_whitelist_rejects_stock_or_price_fields(self, _mock_throw):
		with self.assertRaises(frappe.ValidationError):
			_normalize_changes({"standard_rate": 100, "warehouse_stock_qty": 5})

	@patch("myapp.services.ai_data_task_service._ensure_tables")
	@patch("myapp.services.ai_data_task_service._require_approver", return_value="steward@example.com")
	@patch("myapp.services.ai_data_task_service.run_idempotent", side_effect=_run_immediately)
	@patch("myapp.services.ai_data_task_service._get_task")
	@patch("myapp.services.ai_data_task_service.frappe.throw", side_effect=frappe.ValidationError)
	def test_requester_cannot_approve_own_task(
		self, _mock_throw, mock_get_task, _mock_idempotent, _mock_actor, _mock_tables,
	):
		mock_get_task.return_value = _task(status="review_required")
		with self.assertRaises(frappe.ValidationError):
			review_ai_data_task_v1("AI-DATA-1", "approve", "同意", "review-1")

	@patch("myapp.services.ai_data_task_service._audit")
	@patch("myapp.services.ai_data_task_service.now_datetime", return_value="2026-07-15 12:00:00")
	@patch("myapp.services.ai_data_task_service._serialize", return_value={"status": "failed"})
	@patch("myapp.services.ai_data_task_service._ensure_tables")
	@patch("myapp.services.ai_data_task_service._require_steward", return_value="executor@example.com")
	@patch("myapp.services.ai_data_task_service.run_idempotent", side_effect=_run_immediately)
	@patch("myapp.services.ai_data_task_service._get_task")
	@patch("myapp.services.ai_data_task_service.update_product_v2")
	def test_execution_fails_closed_when_source_changed(
		self, mock_update, mock_get_task, _mock_idempotent, _mock_actor, _mock_tables,
		_mock_serialize, _mock_now, mock_audit,
	):
		mock_get_task.side_effect = [_task(), _task(status="failed")]
		item = SimpleNamespace(description="changed", check_permission=Mock())
		with patch.object(ai_data_task_service, "frappe") as mock_frappe:
			mock_frappe.get_doc.return_value = item
			result = execute_ai_data_task_v1("AI-DATA-1", "execute-1")

		self.assertEqual(result["data"]["task"]["status"], "failed")
		mock_update.assert_not_called()
		mock_audit.assert_called_once()

	@patch("myapp.services.ai_data_task_service._audit")
	@patch("myapp.services.ai_data_task_service.now_datetime", return_value="2026-07-15 12:00:00")
	@patch("myapp.services.ai_data_task_service._serialize", return_value={"status": "executed"})
	@patch("myapp.services.ai_data_task_service._ensure_tables")
	@patch("myapp.services.ai_data_task_service._require_steward", return_value="executor@example.com")
	@patch("myapp.services.ai_data_task_service.run_idempotent", side_effect=_run_immediately)
	@patch("myapp.services.ai_data_task_service._get_task")
	@patch("myapp.services.ai_data_task_service.update_product_v2", return_value={"status": "success"})
	def test_execution_uses_existing_product_service_with_idempotency(
		self, mock_update, mock_get_task, _mock_idempotent, _mock_actor, _mock_tables,
		_mock_serialize, _mock_now, mock_audit,
	):
		mock_get_task.side_effect = [_task(), _task(status="executed")]
		item = SimpleNamespace(description="old", check_permission=Mock())
		with patch.object(ai_data_task_service, "frappe") as mock_frappe:
			mock_frappe.get_doc.return_value = item
			result = execute_ai_data_task_v1("AI-DATA-1", "execute-1")

		self.assertEqual(result["data"]["task"]["status"], "executed")
		mock_update.assert_called_once_with(
			item_code="ITEM-001", request_id="ai-data-task:AI-DATA-1:execute:v1",
			description="new",
		)
		mock_audit.assert_called_once()

	@patch("myapp.services.ai_data_task_service._ensure_tables")
	@patch("myapp.services.ai_data_task_service._require_steward", return_value="approver@example.com")
	@patch("myapp.services.ai_data_task_service.run_idempotent", side_effect=_run_immediately)
	@patch("myapp.services.ai_data_task_service._get_task")
	@patch("myapp.services.ai_data_task_service.frappe.throw", side_effect=frappe.ValidationError)
	def test_approver_cannot_execute_same_task(
		self, _mock_throw, mock_get_task, _mock_idempotent, _mock_actor, _mock_tables,
	):
		mock_get_task.return_value = _task()
		with self.assertRaises(frappe.ValidationError):
			execute_ai_data_task_v1("AI-DATA-1", "execute-1")

	@patch("myapp.services.ai_data_task_service._ensure_tables")
	@patch("myapp.services.ai_data_task_service._require_system_manager", return_value="admin@example.com")
	@patch("myapp.services.ai_data_task_service.run_idempotent", side_effect=_run_immediately)
	@patch("myapp.services.ai_data_task_service._get_task")
	@patch("myapp.services.ai_data_task_service.frappe.throw", side_effect=frappe.ValidationError)
	def test_rollback_rejects_post_execution_drift(
		self, _mock_throw, mock_get_task, _mock_idempotent, _mock_actor, _mock_tables,
	):
		mock_get_task.return_value = _task(status="executed")
		item = SimpleNamespace(description="edited-again", check_permission=Mock())
		with patch.object(ai_data_task_service, "frappe") as mock_frappe:
			mock_frappe.get_doc.return_value = item
			mock_frappe.throw.side_effect = frappe.ValidationError
			with self.assertRaises(frappe.ValidationError):
				rollback_ai_data_task_v1("AI-DATA-1", "恢复原值", "rollback-1")
