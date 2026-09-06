"""Pure capability boundary; never infer a supported write from an unknown verb."""

WRITE_CAPABILITIES = {
	"product_setup_draft": {"create", "update"},
	"sales_order_draft": {"create", "update"},
	"purchase_order_draft": {"create", "update"},
	"inventory_adjustment_draft": {"inventory_adjust"},
}
QUERY_DEFAULTS = {
	"product_query": None, "entities": [], "report_type": None,
	"date_preset": "all", "status": "all", "sort": "latest",
	"min_amount": None, "limit": 10,
}


def assess_action_contract(intent):
	contract = intent.get("action_contract")
	if contract is None:
		return "legacy"
	if not isinstance(contract, dict) or contract.get("schema_version") != "ai-action-contract-v1":
		return "clarification_required"
	if contract.get("request_mode") != "execute_request":
		return "clarification_required"
	operations = contract.get("operations")
	if not isinstance(operations, list) or not operations:
		return "clarification_required"
	allowed = WRITE_CAPABILITIES.get(intent.get("intent"), set())
	if any(not isinstance(op, str) or op not in allowed for op in operations):
		return "unsupported"
	# No mixed or multi-object writes until all targets and dependencies can be bound.
	if len(operations) != 1 or contract.get("has_preserve_targets"):
		return "clarification_required"
	count = contract.get("target_count")
	if count is not None and (type(count) is not int or count != 1):
		return "clarification_required"
	return "supported"


def apply_query_clears(candidate, merged):
	control = candidate.get("query_context_operations")
	if not isinstance(control, dict):
		return merged
	fields = control.get("clear_fields")
	fields = fields if isinstance(fields, list) else []
	# reset discards old context, but keeps new explicit filters from this request.
	result = dict(candidate if control.get("reset") is True else merged)
	for field in fields:
		if isinstance(field, str) and field in QUERY_DEFAULTS:
			result[field] = QUERY_DEFAULTS[field]
			if field == "date_preset":
				result.update(date_from=None, date_to=None)
			if field == "product_query":
				result.update(product_terms=[], product_hypotheses=[], product_attributes={})
	return result
