import json
from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services import product_lifecycle_plan_service as service


class TestLifecyclePlanOwnership(TestCase):
	def test_read_and_lock_both_scope_query_to_current_owner(self):
		with patch.object(service.frappe, "db", new=MagicMock()) as db, patch.object(service, "current_user", return_value="USER-B"):
			db.sql.return_value = []
			for lock in [False, True]:
				with self.subTest(lock=lock), self.assertRaises(frappe.PermissionError):
					service._read_plan("PLAN-OF-USER-A", lock=lock)
				query, params = db.sql.call_args.args
				self.assertIn("owner=%s", query)
				self.assertEqual(params, ("PLAN-OF-USER-A", "USER-B"))
				self.assertEqual("FOR UPDATE" in query, lock)


class TestLifecyclePlans(TestCase):
	def setUp(self):
		self.db = self._patch("frappe.db", new=MagicMock())
		self.db.sql.return_value = [("ITEM-1",)]
		self.now = datetime(2026, 9, 7, 12)
		self.db.sql.return_value = [("ITEM-1", self.now)]
		self._patch("now_datetime", return_value=self.now)
		self._patch("current_user", return_value="owner")
		self.preview = {"operation": "disable", "reason": "重复建档", "preflight_passed": True,
			"targets": [{"item_code": "ITEM-1", "item_modified": str(self.now),
				"disabled": False, "already_in_requested_state": False, "blockers": []}]}
		self.plan = frappe._dict(name="PLAN-1", owner="owner", version_no=1, status="pending",
			expires_at=self.now + timedelta(minutes=15), preview_json=json.dumps(self.preview))
		self.read = self._patch("_read_plan", return_value=self.plan)
		self.fresh = self._patch("preview_product_lifecycle", return_value=self.preview)
		self.item = MagicMock(modified=self.now)
		self.permission = self._patch("require_document_permission", return_value=self.item)

	def _patch(self, name, **kwargs):
		patcher = patch(f"myapp.services.product_lifecycle_plan_service.{name}", **kwargs)
		self.addCleanup(patcher.stop)
		return patcher.start()

	def execute(self, **overrides):
		params = dict(confirmed=True, shared_scope_confirmed=True, request_id="REQ-1")
		params.update(overrides)
		return service.execute_product_lifecycle_plan("PLAN-1", 1, **params)

	def test_requires_explicit_confirmation_and_request_key(self):
		for overrides in [dict(confirmed="true"), dict(shared_scope_confirmed=False), dict(request_id=" ")]:
			with self.subTest(overrides=overrides), self.assertRaises(frappe.ValidationError):
				self.execute(**overrides)
		self.read.assert_not_called()

	def test_requires_exact_integer_version(self):
		for version in [True, "1", 2]:
			with self.subTest(version=version), self.assertRaises(frappe.ValidationError):
				service.execute_product_lifecycle_plan("PLAN-1", version, confirmed=True,
					shared_scope_confirmed=True, request_id="REQ-1")

	def test_expiry_blocks_before_business_writes(self):
		self.plan.expires_at = self.now
		with self.assertRaises(frappe.ValidationError):
			self.execute()
		self.item.save.assert_not_called()

	def test_success_has_audited_receipt_and_no_internal_commit(self):
		result = self.execute()
		self.read.assert_called_once_with("PLAN-1", lock=True)
		self.assertFalse(result["replayed"])
		self.assertEqual(result["receipt"]["executed_by"], "owner")
		self.assertEqual(result["receipt"]["scope"], "shared_item_master")
		self.item.save.assert_called_once()
		self.assertEqual(self.item.disabled, 1)
		self.db.commit.assert_not_called()

	def test_replay_does_not_require_deleted_or_changed_item(self):
		self.plan.update(status="completed", request_id="REQ-1", receipt_json='{"saved": true}')
		self.plan.expires_at = self.now - timedelta(days=1)
		self.assertEqual(self.execute(), {"receipt": {"saved": True}, "replayed": True})
		self.fresh.assert_not_called()
		self.item.save.assert_not_called()

	def test_different_request_cannot_reexecute_completed_plan(self):
		self.plan.update(status="completed", request_id="OTHER", receipt_json="{}")
		with self.assertRaises(frappe.ValidationError):
			self.execute()
		self.item.save.assert_not_called()

	def test_changed_item_version_rejects_entire_batch(self):
		self.fresh.return_value = {**self.preview, "targets": [{**self.preview["targets"][0],
			"item_modified": str(self.now + timedelta(seconds=1))}]}
		with self.assertRaises(frappe.ValidationError):
			self.execute()
		self.item.save.assert_not_called()

	def test_database_or_save_error_rolls_back_callbacks_and_all_writes(self):
		self.item.save.side_effect = RuntimeError("save failed")
		with self.assertRaises(RuntimeError):
			self.execute()
		self.db.rollback.assert_called_once_with()
		self.db.commit.assert_not_called()

	def test_delete_cannot_fall_back_to_disable(self):
		self.plan.preview_json = json.dumps({**self.preview, "operation": "delete"})
		with self.assertRaises(frappe.ValidationError):
			self.execute()
		self.item.save.assert_not_called()

	def test_already_in_requested_state_is_audited_noop(self):
		self.preview["targets"][0]["already_in_requested_state"] = True
		self.assertEqual(len(self.execute()["receipt"]["targets"]), 1)
		self.item.save.assert_not_called()

	def test_native_reference_error_is_redacted_after_full_rollback(self):
		self.preview["operation"] = "delete"
		self.plan.preview_json = json.dumps(self.preview)
		with patch.object(service, "_lock_deletion_dependencies"), \
			patch.object(service.frappe, "delete_doc", side_effect=frappe.LinkExistsError("SECRET-INVOICE")), \
			patch.object(service.frappe, "clear_last_message") as clear:
			with self.assertRaises(frappe.ValidationError) as rejected:
				self.execute(deletion_confirmed=True)
			self.assertNotIn("SECRET", str(rejected.exception))
			clear.assert_called_once()
		self.db.rollback.assert_called_once()

	def test_plan_creation_is_immutable_and_time_bounded(self):
		result = service.create_product_lifecycle_plan("disable", ["ITEM-1"], "原因")
		args = self.db.sql.call_args_list[0].args[1]
		self.assertEqual(args[3] - args[2], timedelta(minutes=15))
		self.assertEqual(result["version"], 1)
		self.item.save.assert_not_called()
