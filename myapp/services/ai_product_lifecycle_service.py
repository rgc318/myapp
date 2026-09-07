"""Model-proposed lifecycle targets, resolved and confirmed by server-owned plans."""
import hashlib
import json
import math

import frappe

from myapp.services.data_permission_service import current_user
from myapp.services.product_lifecycle_plan_service import (
	_persist_preview, _read_plan, create_product_lifecycle_plan,
)
from myapp.services.product_lifecycle_service import LIFECYCLE_OPERATIONS


def is_lifecycle_intent(intent):
	action = intent.get("action_contract") or {}
	return intent.get("intent") == "product_setup_draft" and any(
		operation in LIFECYCLE_OPERATIONS for operation in action.get("operations") or []
	)


def validate_lifecycle_intent(intent, content):
	action = intent.get("action_contract") or {}
	operations = action.get("operations") or []
	confidence = float(intent.get("confidence") or 0)
	if (not is_lifecycle_intent(intent) or action.get("schema_version") != "ai-action-contract-v1"
		or action.get("request_mode") != "execute_request" or len(operations) != 1
		or not math.isfinite(confidence) or confidence < 0.6):
		raise frappe.ValidationError("请明确一个商品启用、停用或删除动作；咨询、否定和混合操作不会执行。")
	targets = action.get("product_targets") or []
	preserve = action.get("preserve_product_targets") or []
	if (not isinstance(targets, list) or not isinstance(preserve, list) or not 1 <= len(targets) <= 20
		or len(preserve) > 20 or type(action.get("target_count")) is not int
		or action["target_count"] != len(targets) or bool(action.get("has_preserve_targets")) != bool(preserve)):
		raise frappe.ValidationError("AI 未完整列出操作和保留目标，请明确商品编码后重试。")
	for target in targets + preserve:
		if (not isinstance(target, dict) or not isinstance(target.get("query"), str)
			or not target["query"].strip() or len(target["query"]) > 200
			or not isinstance(target.get("evidence"), str) or not target["evidence"].strip()
			or target["evidence"] not in content):
			raise frappe.ValidationError("目标缺少当前原文证据，不能生成操作计划。")
	return operations[0], targets, preserve


def _identity(value):
	return "".join(char for char in str(value or "").casefold() if char.isalnum())


def _plan_context(previous, plan):
	"""Remember mentioned identities, never infer that a pending action executed."""
	state = dict(previous)
	state["active_scenario"] = "general"
	preview = plan["preview"]
	rows = [*preview.get("targets", []), *preview.get("preserve_targets", [])]
	resolved = len(rows) == 1 and not preview.get("resolution_groups")
	item = rows[0] if resolved else {}
	status = "resolved" if resolved else "ambiguous"
	state["product"] = {"query": item.get("item_code"), "item_code": item.get("item_code"),
		"item_name": item.get("item_name"), "resolution_status": status}
	state["active_entities"] = {**state.get("active_entities", {}), "product": {
		"entity_type": "product", "entity_id": item.get("item_code"), "display_name": item.get("item_name"),
		"resolution_status": status, "source": "product_lifecycle_plan", "source_result_set_id": plan["name"]}}
	# Bounded context cannot faithfully represent >20 identities: clear the set
	# instead of publishing a partial batch as if it were the complete selection.
	rows = rows if len(rows) <= 20 else []
	state["last_result_set"] = {"type": "products", "id": plan["name"],
		"entity_ids": [row["item_code"] for row in rows], "entity_refs": [
			{"entity_type": "product", "entity_id": row["item_code"], "display_name": row.get("item_name")}
			for row in rows]}
	return state


def _candidates(query, state):
	# All states included: enabling must find disabled Items too. get_list applies
	# DocType/User Permission; no raw global search results reach the client.
	match_kind = "exact"
	rows = frappe.get_list("Item", or_filters={"name": query, "item_name": query},
		fields=["name", "item_name", "disabled"], limit_page_length=21, order_by="name asc")
	if not rows:
		last = state.get("last_result_set") or {}
		codes = (last.get("entity_ids") or []) if last.get("type") == "products" else []
		active = (state.get("active_entities") or {}).get("product") or {}
		if active.get("resolution_status") == "resolved" and active.get("entity_id"):
			codes = [*codes, active["entity_id"]]
		matching = [code for code in codes if _identity(code) == _identity(query)]
		if matching:
			match_kind = "context_identity"
			rows = frappe.get_list("Item", filters={"name": ["in", matching]},
				fields=["name", "item_name", "disabled"], limit_page_length=21, order_by="name asc")
	if not rows:
		match_kind = "candidate"
		rows = frappe.get_list("Item", or_filters={"name": ["like", f"%{query}%"], "item_name": ["like", f"%{query}%"]},
			fields=["name", "item_name", "disabled"], limit_page_length=21, order_by="name asc")
	# A broad/truncated result is not a complete candidate set.
	if len(rows) > 20:
		return []
	return [{"item_code": row.name, "item_name": row.item_name, "disabled": bool(row.disabled), "match_kind": match_kind} for row in rows]


def plan_from_intent(intent, content, state, source):
	operation, targets, preserve = validate_lifecycle_intent(intent, content)
	groups = []
	for role, selectors in [("target", targets), ("preserve", preserve)]:
		for index, selector in enumerate(selectors):
			groups.append({"id": f"{role}-{index}", "role": role, **selector,
				"candidates": _candidates(selector["query"], state)})
	if all(len(group["candidates"]) == 1 and group["candidates"][0]["match_kind"] != "candidate" for group in groups):
		return create_product_lifecycle_plan(operation,
			[group["candidates"][0]["item_code"] for group in groups if group["role"] == "target"],
			content[:500], source=source,
			preserve_codes=[group["candidates"][0]["item_code"] for group in groups if group["role"] == "preserve"])
	return _persist_preview({"schema_version": "product-lifecycle-preview-v1", "operation": operation,
		"reason": content[:500], "source": source, "targets": [], "preserve_targets": [],
		"scope": "shared_item_master", "scope_warning": "操作影响共享商品主档及所有使用该商品的公司。",
		"preflight_passed": False, "execution_available": False, "resolution_groups": groups})


def resolve_product_lifecycle_plan(plan_id, expected_version, selections):
	from frappe.utils import get_datetime, now_datetime
	from myapp.services.product_lifecycle_plan_service import TABLE
	plan = _read_plan(plan_id, lock=True)
	if (type(expected_version) is not int or expected_version != plan.version_no or plan.status != "pending"
		or get_datetime(plan.expires_at) <= now_datetime()):
		raise frappe.ValidationError("候选计划已失效，请重新发送请求。")
	preview = json.loads(plan.preview_json)
	groups = preview.get("resolution_groups") or []
	if not groups or not isinstance(selections, dict) or set(selections) != {group["id"] for group in groups}:
		raise frappe.ValidationError("请逐项确认全部操作目标和保留目标。")
	for group in groups:
		if selections[group["id"]] not in [candidate["item_code"] for candidate in group["candidates"]]:
			raise frappe.ValidationError("选择必须属于该项服务端候选集合。")
	result = create_product_lifecycle_plan(preview["operation"],
		[selections[group["id"]] for group in groups if group["role"] == "target"], preview["reason"],
		source={**preview.get("source", {}), "resolved_from": plan.name},
		preserve_codes=[selections[group["id"]] for group in groups if group["role"] == "preserve"])
	preview["replacement_plan_id"] = result["name"]
	frappe.db.sql(f"UPDATE `{TABLE}` SET status='superseded', preview_json=%s WHERE name=%s AND owner=%s",
		(json.dumps(preview, ensure_ascii=False), plan.name, current_user()))
	return result


def generate_ai_product_lifecycle_plan_v1(content, company=None, conversation_id=None,
	model_alias=None, scenario_resolution_id=None):
	# Lazy import avoids an ai_service -> lifecycle -> ai_service cycle.
	from myapp.services import ai_service as ai
	user = ai._current_user()
	content = ai._normalize_content(content)
	model_alias = ai.resolve_ai_selected_model_alias(model_alias)
	state_record = {"state": {}, "version": 0}
	if conversation_id:
		conversation = ai.ai_repository.get_conversation(conversation_id=conversation_id, user=user)["conversation"]
		if conversation["status"] != "active":
			raise frappe.ValidationError("已归档会话不能生成操作计划。")
		if company and conversation.get("company") and company != conversation["company"]:
			raise frappe.ValidationError("公司与会话范围不一致。")
		company = company or conversation.get("company")
		state_record = ai.ai_repository.get_conversation_state(conversation_id=conversation_id, user=user)
	company = ai._resolve_company_scope(company, required=False)
	if scenario_resolution_id:
		resolution = ai._take_ai_scenario_resolution(scenario_resolution_id, user=user, content=content,
			attachment_ids=[], company=company, conversation_id=conversation_id,
			conversation_state_version=state_record["version"], model_alias=model_alias)
		if not resolution or resolution["scenario"] != "product_lifecycle_plan":
			raise frappe.ValidationError("原请求解析凭据已失效，请重新发送。")
		intent = resolution["intent"]
	else:
		intent = ai._call_ai_intent_orchestrator(content=content, user=user, company=company,
			conversation_state=state_record["state"], model_alias=model_alias, attachments=[])
	validate_lifecycle_intent(intent, content)
	if conversation_id:
		locked = ai.ai_repository._get_owned_conversation(conversation_id, user, for_update=True)
		if locked.status != "active" or int(locked.state_version or 0) != state_record["version"]:
			raise frappe.ValidationError("会话上下文已变化，请重新发送请求。")
	if not conversation_id:
		conversation_id = ai.ai_repository.create_conversation(user=user, title=content[:140], company=company)["name"]
	source = {"content": content, "content_hash": hashlib.sha256(content.encode()).hexdigest(),
		"conversation_id": conversation_id, "conversation_state_version": state_record["version"],
		"action_contract": intent["action_contract"], "requested_model_alias": model_alias,
		"prompt_version": ai.AI_RUNTIME_EXPECTED_PROMPT_VERSIONS["intent_parse"]}
	plan = plan_from_intent(intent, content, state_record["state"], source)
	updated = ai.ai_repository.update_conversation_state(conversation_id=conversation_id, user=user,
		state=_plan_context(state_record["state"], plan), expected_version=state_record["version"])
	if not updated.get("updated"):
		raise frappe.ValidationError("会话上下文已变化，请重新生成计划。")
	ai.ai_repository.append_message(conversation_id=conversation_id, user=user, role="user",
		content=content, scenario="product_lifecycle_plan")
	message = "已生成商品操作计划，请核对目标、保留对象和阻断原因；确认前不会执行任何启停或删除。"
	citations = [{"type": "product_lifecycle_plan", "id": plan["name"], "label": "商品操作计划", "data": {"plan_id": plan["name"]}}]
	ai.ai_repository.append_message(conversation_id=conversation_id, user=user, role="assistant",
		content=message, scenario="product_lifecycle_plan", citations=citations)
	return {"status": "success", "data": {"conversation_id": conversation_id, "plan": plan,
		"message": {"content": message, "role": "assistant", "citations": citations}}}
