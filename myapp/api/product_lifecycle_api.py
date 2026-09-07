"""Public adapters; Gateway and direct adapters share the same permission boundary."""
import frappe

from myapp.services import product_lifecycle_plan_service as plans
from myapp.services.ai_product_lifecycle_service import (
	generate_ai_product_lifecycle_plan_v1 as generate_plan,
	resolve_product_lifecycle_plan,
)
from myapp.utils.idempotency import get_current_request_id


def _result(data):
	return {"status": "success", "data": data}


def _atomic(callback):
	# Gateway converts exceptions to response envelopes, so rollback must happen
	# before an exception reaches that boundary, including generation failures.
	try:
		return callback()
	except Exception:
		frappe.db.rollback()
		raise


@frappe.whitelist(methods=["POST"])
def create_product_lifecycle_plan_v1(operation, item_codes, reason):
	return _atomic(lambda: _result(plans.create_product_lifecycle_plan(operation, frappe.parse_json(item_codes), reason)))


@frappe.whitelist(methods=["POST"])
def get_product_lifecycle_plan_v1(plan_id):
	return _result(plans.get_product_lifecycle_plan(plan_id))


@frappe.whitelist(methods=["POST"])
def list_product_lifecycle_plans_v1(limit=20):
	return _result({"items": plans.list_product_lifecycle_plans(limit)})


@frappe.whitelist(methods=["POST"])
def discard_product_lifecycle_plan_v1(plan_id):
	return _result(plans.discard_product_lifecycle_plan(plan_id))


@frappe.whitelist(methods=["POST"])
def resolve_product_lifecycle_plan_v1(plan_id, expected_version, selections):
	return _atomic(lambda: _result(resolve_product_lifecycle_plan(plan_id, expected_version, frappe.parse_json(selections))))


@frappe.whitelist(methods=["POST"])
def execute_product_lifecycle_plan_v1(plan_id, expected_version, confirmed=False,
	shared_scope_confirmed=False, deletion_confirmed=False, request_id=None):
	return _result(plans.execute_product_lifecycle_plan(plan_id, expected_version, confirmed=confirmed,
		shared_scope_confirmed=shared_scope_confirmed, deletion_confirmed=deletion_confirmed,
		request_id=get_current_request_id(request_id)))


@frappe.whitelist(methods=["POST"])
def generate_ai_product_lifecycle_plan_v1(content, company=None, conversation_id=None,
	model_alias=None, scenario_resolution_id=None):
	return _atomic(lambda: generate_plan(content, company, conversation_id, model_alias, scenario_resolution_id))
