import json
from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import patch

import frappe
from myapp.services import ai_model_check_service as service

NOW = datetime(2026, 9, 6, 12)


def row(**overrides):
	values = dict(name="job-1", owner="Administrator", status="queued", mode="basic",
		aliases_json='["a", "b"]', results_json="[]", cancel_requested=0,
		creation=NOW, modified=NOW)
	values.update(overrides)
	return frappe._dict(values)


class TestModelCheckJob(TestCase):
	def setUp(self):
		patcher = patch.object(service, "now_datetime", return_value=NOW)
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_stalled_view_retains_progress_and_targets_without_writing(self):
		result = service._view(row(status="running", modified=NOW - timedelta(hours=1)))
		self.assertEqual(result["status"], "interrupted")
		self.assertEqual(result["model_aliases"], ["a", "b"])

	@patch.object(service, "frappe")
	@patch.object(service, "_require_manager", return_value="Administrator")
	@patch.object(service, "_read")
	@patch.object(service, "_check_ai_model_availability")
	def test_failure_is_isolated_and_each_result_is_saved(self, check, read, manager, framework):
		read.side_effect = [row(), row(status="running"), row(status="running")]
		check.side_effect = [RuntimeError("upstream secret"), {"data": {"items": [{"model_alias": "b", "available": True}]}}]
		service.run_model_check_job("job-1")
		saves = [call.args[1] for call in framework.db.sql.call_args_list if "SET results_json" in call.args[0]]
		self.assertEqual(len(saves), 2)
		self.assertEqual(len(json.loads(saves[0][0])), 1)
		items = json.loads(saves[1][0])
		self.assertEqual(items[0]["check_status"], "error")
		self.assertNotIn("secret", saves[1][0])
		self.assertTrue(items[1]["available"])
		self.assertEqual(framework.db.sql.call_args.args[1][0], "partial")

	@patch.object(service, "frappe")
	@patch.object(service, "_require_manager", return_value="Administrator")
	@patch.object(service, "_read")
	@patch.object(service, "_check_ai_model_availability")
	def test_cancel_stops_before_next_probe(self, check, read, manager, framework):
		read.side_effect = [row(), row(status="running", cancel_requested=1)]
		service.run_model_check_job("job-1")
		check.assert_not_called()
		self.assertEqual(framework.db.sql.call_args.args[1][0], "cancelled")

	@patch.object(service, "frappe")
	@patch.object(service, "_read", return_value=row(status="completed"))
	@patch.object(service, "_check_ai_model_availability")
	def test_redelivery_of_completed_job_does_not_probe(self, check, read, framework):
		service.run_model_check_job("job-1")
		check.assert_not_called()
		framework.db.sql.assert_not_called()

	@patch.object(service, "_expire")
	@patch.object(service, "_resolve_healthcheck_model_aliases", return_value=["a"])
	@patch.object(service, "_require_manager", return_value="Administrator")
	@patch.object(service, "frappe")
	def test_matching_active_job_is_reused(self, framework, manager, aliases, expire):
		framework.db.sql.return_value = [row()]
		self.assertEqual(service._start(["a"], "basic")["data"]["job_id"], "job-1")
		framework.enqueue.assert_not_called()

	@patch.object(service, "_require_manager", side_effect=frappe.PermissionError)
	def test_start_and_read_require_manager(self, manager):
		with self.assertRaises(frappe.PermissionError):
			service.start_ai_model_check_v1(["a"])
		with self.assertRaises(frappe.PermissionError):
			service.get_ai_model_check_v1()

	def test_gateway_preserves_adapter_contract(self):
		from myapp.api import gateway, ai_api
		with patch.object(gateway, "_handle_gateway_call", side_effect=lambda callback, **kw: callback()), patch.object(
			ai_api, "start_ai_model_check_v1_service", return_value={"status": "success"},
		) as start:
			gateway.start_ai_model_check_v1(model_aliases=["a"], mode="basic", request_id="request-1")
			start.assert_called_once_with(model_aliases=["a"], mode="basic", request_id="request-1")
