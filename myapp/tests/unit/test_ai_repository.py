from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.services import ai_repository
from myapp.services.ai_repository import _nearest_rank_percentile, submit_feedback


class TestAiRepository(TestCase):
	def test_nearest_rank_percentile_uses_sorted_observations(self):
		values = [900, 100, 500, 300, 700]

		self.assertEqual(_nearest_rank_percentile(values, 0.50), 500)
		self.assertEqual(_nearest_rank_percentile(values, 0.95), 900)

	def test_nearest_rank_percentile_handles_empty_samples(self):
		self.assertIsNone(_nearest_rank_percentile([], 0.50))

	def test_feedback_rating_change_applies_daily_counter_deltas(self):
		run = frappe._dict({
			"name": "AI-RUN-1", "conversation": "AI-CONV-1", "status": "completed",
			"trace_id": "trace-1", "scenario": "general", "environment": "production",
			"company": "Demo Company", "policy_code": "general-prod", "policy_version": 2,
			"model_alias": "erp-fast-chat", "usage_date": "2026-07-15",
			"previous_rating": "negative",
		})
		with patch.object(ai_repository, "frappe") as mock_frappe, patch(
			"myapp.services.ai_repository.now_datetime", return_value="2026-07-15 10:00:00",
		):
			mock_frappe.db.table_exists.return_value = True
			mock_frappe.db.sql.side_effect = [[run], None, None]
			result = submit_feedback(
				run_id="AI-RUN-1", user="user@example.com", rating="positive",
				category="helpful", comment=None,
			)

		self.assertEqual(result["rating"], "positive")
		daily_params = mock_frappe.db.sql.call_args_list[2].args[1]
		self.assertEqual(daily_params[-2:], (1, -1))
