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


def validate_draft_action(contract, *, scenario, operation, user, company):
	"""Check trusted stored metadata, not a contract supplied by the browser."""
	if not isinstance(contract, dict) or contract.get("scenario") != scenario:
		raise ValueError("AI 草稿缺少有效动作契约，请重新生成。")
	if contract.get("user") != user or contract.get("company") != company:
		raise ValueError("AI 草稿动作契约的账号或公司范围不一致。")
	intent = {"intent": scenario, "action_contract": contract.get("action")}
	if assess_action_contract(intent) != "supported":
		raise ValueError("AI 草稿动作不受支持或尚未明确。")
	if contract["action"]["operations"] != [operation]:
		raise ValueError("AI 草稿动作与用户要求不一致；不能自动替换为其他操作。")


def bind_draft_scope(contract, payload):
	"""Freeze resolved scope; unresolved candidates may be bound once after validation.

	This is a server-resolved scope snapshot, not proof of correct model extraction.
	"""
	contract = dict(contract)
	scope = dict(contract.get("resolved_scope") or {})
	scenario = contract.get("scenario")
	current = {}
	if scenario == "product_setup_draft" and payload.get("operation") == "update":
		entity = (payload.get("_state") or {}).get("entity") or {}
		code = payload.get("item_code")
		if entity.get("name") and code and entity["name"] != code:
			raise ValueError("商品目标与服务端实体绑定不一致。")
		current["target"] = entity.get("name") or code
	elif scenario in {"sales_order_draft", "purchase_order_draft"} and payload.get("operation") == "update":
		current["target"] = payload.get("order_number")
	elif scenario == "inventory_adjustment_draft":
		items = payload.get("items") or []
		if len(items) != 1 or not isinstance(items[0], dict):
			raise ValueError("库存调整契约仅支持一个商品，不能增删目标行。")
		current = {"target": items[0].get("item_code"),
			"warehouse": items[0].get("warehouse") or payload.get("warehouse"),
			"adjustment_type": payload.get("adjustment_type")}
		if items[0].get("warehouse") and payload.get("warehouse") and items[0]["warehouse"] != payload["warehouse"]:
			raise ValueError("库存行仓库与草稿仓库不一致。")
		if items[0].get("adjustment_type") and current["adjustment_type"] != items[0]["adjustment_type"]:
			raise ValueError("库存行方向与草稿调整方向不一致。")
	for key, value in current.items():
		if scope.get(key) and scope[key] != value:
			raise ValueError("草稿已绑定的目标、仓库或库存调整方向发生变化，请重新发起对应请求。")
		if value:
			scope[key] = value
	contract["resolved_scope"] = scope
	return contract


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
