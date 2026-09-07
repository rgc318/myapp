from unittest import TestCase
from unittest.mock import patch

from myapp.api import gateway, product_lifecycle_api as adapter


class LifecycleGatewayAdapterTests(TestCase):
	"""Patch behind the adapter: do not hide Gateway/adapter signature errors."""
	def test_execution_preserves_explicit_booleans_version_and_request_id(self):
		with patch.object(adapter.plans, "execute_product_lifecycle_plan", return_value={"receipt": {}}) as execute, \
			patch.object(adapter, "get_current_request_id", return_value="HEADER-KEY"):
			gateway.execute_product_lifecycle_plan_v1("PLAN", 1, confirmed=True,
				shared_scope_confirmed=True, deletion_confirmed=True)
			execute.assert_called_once_with("PLAN", 1, confirmed=True, shared_scope_confirmed=True,
				deletion_confirmed=True, request_id="HEADER-KEY")

	def test_string_confirmation_is_not_coerced_to_true(self):
		with patch.object(adapter.plans, "execute_product_lifecycle_plan", return_value={}) as execute, \
			patch.object(adapter, "get_current_request_id", return_value="KEY"):
			gateway.execute_product_lifecycle_plan_v1("PLAN", 1, confirmed="false")
			self.assertEqual(execute.call_args.kwargs["confirmed"], "false")
			self.assertIs(execute.call_args.kwargs["deletion_confirmed"], False)

	def test_generation_preserves_model_and_single_use_resolution(self):
		with patch.object(adapter, "generate_plan", return_value={"status": "success", "data": {}}) as generate:
			gateway.generate_ai_product_lifecycle_plan_v1("删除 A", "COMPANY", "CONV", "MODEL", "RESOLUTION")
			generate.assert_called_once_with("删除 A", "COMPANY", "CONV", "MODEL", "RESOLUTION")

	def test_resolution_forwards_all_candidate_selections(self):
		with patch.object(adapter, "resolve_product_lifecycle_plan", return_value={}) as resolve:
			gateway.resolve_product_lifecycle_plan_v1("PLAN", 1, '{"target-0":"A","preserve-0":"B"}')
			resolve.assert_called_once_with("PLAN", 1, {"target-0": "A", "preserve-0": "B"})
