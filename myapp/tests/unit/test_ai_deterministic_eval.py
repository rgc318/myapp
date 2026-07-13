import json
from datetime import date
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.services.ai_service import (
	_build_order_query_dsl,
	_build_report_query_dsl,
	_extract_product_search_terms,
)

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "ai_deterministic_eval_v1.json"


class TestAiDeterministicEval(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
		cls.as_of = date.fromisoformat(cls.fixture["as_of"])
		cls.company = cls.fixture["company"]

	def test_fixture_is_versioned_synthetic_and_has_twenty_cases(self):
		self.assertEqual(self.fixture["fixture_version"], "ai-deterministic-eval-v1")
		self.assertIs(self.fixture["synthetic"], True)
		self.assertEqual(
			sum(len(cases) for cases in self.fixture["scenarios"].values()),
			20,
		)

	def test_product_search_phrase_cases(self):
		for case in self.fixture["scenarios"]["product_search_terms"]:
			with self.subTest(case=case["id"]):
				self.assertEqual(_extract_product_search_terms(case["query"]), case["expected"])

	def test_order_query_dsl_cases(self):
		for case in self.fixture["scenarios"]["order_query_dsl"]:
			with self.subTest(case=case["id"]):
				if expected_error := case.get("expected_error"):
					with patch(
						"myapp.services.ai_service.frappe.throw",
						side_effect=frappe.ValidationError(expected_error),
					):
						with self.assertRaisesRegex(frappe.ValidationError, expected_error):
							_build_order_query_dsl(
								case["query"],
								company=self.company,
								as_of=self.as_of,
							)
					continue
				self.assertEqual(
					_build_order_query_dsl(
						case["query"],
						company=self.company,
						as_of=self.as_of,
					),
					case["expected"],
				)

	def test_report_query_dsl_cases(self):
		for case in self.fixture["scenarios"]["report_query_dsl"]:
			with self.subTest(case=case["id"]):
				self.assertEqual(
					_build_report_query_dsl(
						case["query"],
						company=self.company,
						as_of=self.as_of,
					),
					case["expected"],
				)
