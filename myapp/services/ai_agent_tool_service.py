from __future__ import annotations

import json
import re
import time

import frappe
from frappe import _
from frappe.utils import cint

from myapp.services import ai_repository


ALLOWED_TOOLS = {
	"search_products",
	"query_business_documents",
	"get_business_report",
}
TOOL_POLICIES = {
	"search_products": {"risk_level": "L1_READ_ONLY", "approval_required": False},
	"query_business_documents": {"risk_level": "L1_READ_ONLY", "approval_required": False},
	"get_business_report": {"risk_level": "L1_READ_ONLY", "approval_required": False},
}
PRODUCT_SEARCH_FIELDS = {
	"barcode", "item_code", "item_name", "nickname", "specification", "brand", "item_group",
}
TOOL_ARGUMENT_SCHEMAS = {
	"search_products": {
		"type": "object",
		"properties": {
			"query": {"type": "string", "minLength": 1, "maxLength": 500},
			"query_variants": {
				"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 140},
				"maxItems": 8,
			},
			"hypotheses": {
				"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 140},
				"maxItems": 5,
			},
			"attributes": {
				"type": "object",
				"properties": {
					"brand": {"type": ["string", "null"], "maxLength": 140},
					"item_group": {"type": ["string", "null"], "maxLength": 140},
					"color": {"type": ["string", "null"], "maxLength": 80},
					"flavor": {"type": ["string", "null"], "maxLength": 140},
					"specification": {"type": ["string", "null"], "maxLength": 200},
					"capacity": {"type": ["string", "null"], "maxLength": 80},
					"packaging": {"type": ["string", "null"], "maxLength": 140},
				},
				"required": ["brand", "item_group", "color", "flavor", "specification", "capacity", "packaging"],
				"additionalProperties": False,
			},
			"match_mode": {"type": "string", "enum": ["auto", "exact", "contains", "semantic"]},
			"search_fields": {
				"type": "array",
				"items": {"type": "string", "enum": sorted(PRODUCT_SEARCH_FIELDS)},
				"maxItems": 7,
			},
			"limit": {"type": "integer", "minimum": 1, "maximum": 8},
		},
		# Keep v1 calls valid during rolling deployment; the v2 model-side strict
		# schema always supplies the structured hint fields.
		"required": ["query", "match_mode", "search_fields", "limit"],
		"additionalProperties": False,
	},
	"query_business_documents": {
		"type": "object",
		"properties": {
			"entities": {
				"type": "array",
				"items": {
					"type": "string",
					"enum": ["sales_order", "sales_invoice", "purchase_order", "purchase_invoice"],
				},
				"minItems": 1,
				"maxItems": 4,
			},
			"date_from": {"type": ["string", "null"], "pattern": r"^\d{4}-\d{2}-\d{2}$"},
			"date_to": {"type": ["string", "null"], "pattern": r"^\d{4}-\d{2}-\d{2}$"},
			"status": {
				"type": "string",
				"enum": ["all", "unfinished", "completed", "cancelled", "delivering", "receiving", "paying"],
			},
			"sort": {"type": "string", "enum": ["latest", "oldest", "amount_desc", "amount_asc"]},
			"min_amount": {"type": ["number", "null"], "minimum": 0},
			"limit": {"type": "integer", "minimum": 1, "maximum": 20},
			"document_name": {"type": ["string", "null"], "maxLength": 140},
		},
		"required": [
			"entities", "date_from", "date_to", "status", "sort", "min_amount", "limit",
			"document_name",
		],
		"additionalProperties": False,
	},
	"get_business_report": {
		"type": "object",
		"properties": {
			"report_type": {
				"type": "string",
				"enum": ["overview", "sales", "purchase", "cashflow", "receivable_payable"],
			},
			"date_from": {"type": ["string", "null"], "pattern": r"^\d{4}-\d{2}-\d{2}$"},
			"date_to": {"type": ["string", "null"], "pattern": r"^\d{4}-\d{2}-\d{2}$"},
		},
		"required": ["report_type", "date_from", "date_to"],
		"additionalProperties": False,
	},
}


def _switch_user(user: str) -> None:
	frappe.set_user(user)


def _commit_agent_tool_result() -> None:
	frappe.db.commit()


def _tool_policy(tool: str) -> dict:
	policy = TOOL_POLICIES.get(tool)
	if not policy:
		raise frappe.PermissionError(_("Agent 工具策略不存在。"))
	return policy


def _payload(value) -> dict:
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except (TypeError, ValueError):
			frappe.throw(_("Agent 工具参数格式不正确。"))
	if not isinstance(value, dict):
		frappe.throw(_("Agent 工具参数必须是对象。"))
	return value


def _matches_type(value, expected) -> bool:
	types = expected if isinstance(expected, list) else [expected]
	return any(
		(value_type == "null" and value is None)
		or (value_type == "string" and isinstance(value, str))
		or (value_type == "array" and isinstance(value, list))
		or (value_type == "object" and isinstance(value, dict))
		or (value_type == "integer" and isinstance(value, int) and not isinstance(value, bool))
		or (value_type == "number" and isinstance(value, (int, float)) and not isinstance(value, bool))
		for value_type in types
	)


def _validate_schema(value, schema: dict, *, path: str) -> None:
	if not _matches_type(value, schema.get("type")):
		frappe.throw(_("工具参数 {0} 类型不正确。").format(path))
	if value is None:
		return
	if "enum" in schema and value not in schema["enum"]:
		frappe.throw(_("工具参数 {0} 不在允许范围内。").format(path))
	if isinstance(value, str):
		if len(value) < int(schema.get("minLength") or 0):
			frappe.throw(_("工具参数 {0} 不能为空。").format(path))
		if schema.get("maxLength") is not None and len(value) > int(schema["maxLength"]):
			frappe.throw(_("工具参数 {0} 超出长度限制。").format(path))
		if schema.get("pattern") and not re.fullmatch(str(schema["pattern"]), value):
			frappe.throw(_("工具参数 {0} 格式不正确。").format(path))
	if isinstance(value, (int, float)) and not isinstance(value, bool):
		if schema.get("minimum") is not None and value < schema["minimum"]:
			frappe.throw(_("工具参数 {0} 小于允许值。").format(path))
		if schema.get("maximum") is not None and value > schema["maximum"]:
			frappe.throw(_("工具参数 {0} 大于允许值。").format(path))
	if isinstance(value, list):
		if schema.get("minItems") is not None and len(value) < int(schema["minItems"]):
			frappe.throw(_("工具参数 {0} 项目过少。").format(path))
		if schema.get("maxItems") is not None and len(value) > int(schema["maxItems"]):
			frappe.throw(_("工具参数 {0} 项目过多。").format(path))
		for index, child in enumerate(value):
			_validate_schema(child, schema.get("items") or {}, path=f"{path}[{index}]")
	if isinstance(value, dict):
		properties = schema.get("properties") or {}
		missing = [name for name in schema.get("required") or [] if name not in value]
		if missing:
			frappe.throw(_("工具参数缺少必填字段：{0}。").format(", ".join(missing)))
		if schema.get("additionalProperties") is False:
			extra = sorted(set(value) - set(properties))
			if extra:
				frappe.throw(_("工具参数包含未授权字段：{0}。").format(", ".join(extra)))
		for name, child in value.items():
			if name in properties:
				_validate_schema(child, properties[name], path=f"{path}.{name}")


def _validate_tool_arguments(tool: str, arguments) -> dict:
	resolved = _payload(arguments)
	schema = TOOL_ARGUMENT_SCHEMAS.get(tool)
	if not schema:
		raise frappe.PermissionError(_("Agent 工具参数 Schema 不存在。"))
	_validate_schema(resolved, schema, path=tool)
	return resolved


def _bounded_text(value, *, limit: int = 200) -> str | None:
	resolved = " ".join(str(value or "").strip().split())
	return resolved[:limit] or None


def _execute_search_products(arguments: dict, *, company: str) -> tuple[dict, list[dict], str]:
	from myapp.services.ai_service import _build_product_search_context

	query = _bounded_text(arguments.get("query"), limit=500)
	if not query:
		return {"tool": "search_products", "products": [], "retrieval": {"status": "not_found"}}, [], "not_found"
	match_mode = str(arguments.get("match_mode") or "auto").strip()
	if match_mode not in {"auto", "exact", "contains", "semantic"}:
		frappe.throw(_("商品匹配方式不受支持。"))
	search_fields = arguments.get("search_fields") or []
	if not isinstance(search_fields, list) or any(str(field) not in PRODUCT_SEARCH_FIELDS for field in search_fields):
		frappe.throw(_("商品搜索字段不受支持。"))
	limit = max(1, min(8, cint(arguments.get("limit")) or 8))
	context, citations, _audit = _build_product_search_context(
		query=query,
		company=company,
		structured_intent={
			"product_query": query,
			"product_terms": arguments.get("query_variants") or [],
			"product_hypotheses": arguments.get("hypotheses") or [],
			"product_attributes": arguments.get("attributes") or {},
			"match_mode": match_mode,
			"search_fields": search_fields,
			"limit": limit,
		},
	)
	status = str((context.get("retrieval") or {}).get("status") or "not_found")
	return context, citations, "ok" if status == "resolved" else status


def _execute_business_documents(arguments: dict, *, company: str) -> tuple[dict, list[dict], str]:
	from myapp.services.ai_service import _build_order_query_context

	entities = arguments.get("entities") or []
	allowed_entities = {"sales_order", "sales_invoice", "purchase_order", "purchase_invoice"}
	if (
		not isinstance(entities, list)
		or not entities
		or any(str(entity) not in allowed_entities for entity in entities)
	):
		frappe.throw(_("业务单据类型不受支持。"))
	document_name = _bounded_text(arguments.get("document_name"), limit=140)
	if document_name and len(entities) != 1:
		frappe.throw(_("精确单据查询必须且只能指定一种单据类型。"))
	status = str(arguments.get("status") or "all").strip()
	if status not in {"all", "unfinished", "completed", "cancelled", "delivering", "receiving", "paying"}:
		frappe.throw(_("业务单据状态不受支持。"))
	sort = str(arguments.get("sort") or "latest").strip()
	if sort not in {"latest", "oldest", "amount_desc", "amount_asc"}:
		frappe.throw(_("业务单据排序不受支持。"))
	limit = max(1, min(20, cint(arguments.get("limit")) or 10))
	intent = {
		"intent": "order_query",
		"confidence": 1,
		"entities": entities,
		"date_preset": "custom" if arguments.get("date_from") and arguments.get("date_to") else "all",
		"date_from": _bounded_text(arguments.get("date_from"), limit=10),
		"date_to": _bounded_text(arguments.get("date_to"), limit=10),
		"status": status,
		"sort": sort,
		"min_amount": arguments.get("min_amount"),
		"limit": limit,
		"document_name": document_name,
	}
	context, citations, _audit = _build_order_query_context(
		query="", company=company, structured_intent=intent,
	)
	groups = (context.get("result_set") or {}).get("groups") or []
	has_results = any(cint(group.get("returned_count")) > 0 for group in groups)
	return context, citations, "ok" if has_results else "not_found"


def _execute_business_report(arguments: dict, *, company: str) -> tuple[dict, list[dict], str]:
	from myapp.services.ai_service import _build_report_query_context

	report_type = str(arguments.get("report_type") or "overview").strip()
	if report_type not in {"overview", "sales", "purchase", "cashflow", "receivable_payable"}:
		frappe.throw(_("业务报表类型不受支持。"))
	intent = {
		"intent": "report_summary",
		"confidence": 1,
		"report_type": report_type,
		"date_preset": "custom" if arguments.get("date_from") and arguments.get("date_to") else "all",
		"date_from": _bounded_text(arguments.get("date_from"), limit=10),
		"date_to": _bounded_text(arguments.get("date_to"), limit=10),
	}
	context, citations, _audit = _build_report_query_context(
		query="", company=company, structured_intent=intent,
	)
	return context, citations, "ok"


def _build_grounding_contract(*, context: dict, citations: list[dict], company: str) -> dict:
	tool = str(context.get("tool") or "")
	result_sets = []
	if tool == "query_business_documents":
		for group in (context.get("result_set") or {}).get("groups") or []:
			truncated = group.get("truncated")
			result_sets.append({
				"type": str(group.get("entity") or "business_documents"),
				"complete": None if truncated is None else not bool(truncated),
				"returned_count": cint(group.get("returned_count")),
				"available_count": group.get("available_count"),
			})
	elif tool == "search_products":
		status = str((context.get("retrieval") or {}).get("status") or "not_found")
		result_sets.append({
			"type": "products",
			"complete": True if status == "not_found" else None,
			"returned_count": len(context.get("products") or []),
			"available_count": None,
		})
	elif tool == "get_business_report":
		result_sets.append({
			"type": "business_report", "complete": True,
			"returned_count": 1, "available_count": 1,
		})
	return {
		"schema_version": "agent-grounding-v1",
		"company": company,
		"result_sets": result_sets,
		"citation_refs": [
			{"type": citation.get("type"), "id": citation.get("id")}
			for citation in citations
			if citation.get("type") and citation.get("id")
		],
	}


def request_ai_agent_tool_approval_v1(
	*, run_id: str, call_id: str, tool: str, arguments, risk_level: str,
	checkpoint, capability_token: str,
) -> dict:
	resolved_tool = str(tool or "").strip()
	if resolved_tool not in ALLOWED_TOOLS:
		raise frappe.PermissionError(_("Agent 工具审批请求不受支持。"))
	policy = _tool_policy(resolved_tool)
	if not policy.get("approval_required"):
		raise frappe.PermissionError(_("该 Agent 工具不需要人工审批。"))
	if str(risk_level or "").strip() != policy["risk_level"]:
		raise frappe.PermissionError(_("Agent 工具审批风险等级不一致。"))
	result = ai_repository.request_agent_tool_approval(
		run_id=str(run_id or "").strip(),
		call_id=str(call_id or "").strip()[:140],
		tool=resolved_tool,
		arguments=_validate_tool_arguments(resolved_tool, arguments),
		risk_level=policy["risk_level"],
		checkpoint=checkpoint,
		capability_token=str(capability_token or ""),
	)
	frappe.db.commit()
	return result


def execute_ai_agent_tool_v1(
	*, run_id: str, call_id: str, tool: str, arguments, capability_token: str,
) -> dict:
	resolved_run_id = str(run_id or "").strip()
	resolved_call_id = str(call_id or "").strip()[:140]
	resolved_tool = str(tool or "").strip()
	if not resolved_run_id or not resolved_call_id or resolved_tool not in ALLOWED_TOOLS:
		raise frappe.PermissionError(_("Agent 工具调用不受支持。"))
	args = _validate_tool_arguments(resolved_tool, arguments)
	policy = _tool_policy(resolved_tool)
	capability = ai_repository.validate_agent_capability(
		run_id=resolved_run_id,
		capability_token=capability_token,
		tool=resolved_tool,
	)
	cached = ai_repository.get_agent_tool_result(
		run_id=resolved_run_id, call_id=resolved_call_id,
		tool=resolved_tool, arguments=args,
	)
	if cached:
		return cached
	approval = None
	if policy.get("approval_required"):
		approval = ai_repository.get_agent_tool_approval_decision(
			run_id=resolved_run_id, call_id=resolved_call_id,
			tool=resolved_tool, arguments=args,
		)

	user = capability["user"]
	company = str(capability.get("company") or "").strip()
	if not company:
		result = {
			"call_id": resolved_call_id,
			"tool": resolved_tool,
			"status": "denied",
			"data": {},
			"model_context": {},
			"citations": [],
			"error": {"code": "AI_AGENT_COMPANY_REQUIRED", "message": "工具调用需要明确公司范围。"},
			"retryable": False,
		}
		return result

	claim = ai_repository.start_agent_tool_step(
		run_id=resolved_run_id, user=user, call_id=resolved_call_id,
		tool=resolved_tool, arguments=args,
	)
	if isinstance(claim, str):
		# Compatibility for workers during a rolling deployment where the service
		# process may reload before the repository module.
		step_id = claim
	else:
		if claim.get("result"):
			_commit_agent_tool_result()
			return claim["result"]
		if claim.get("status") != "claimed":
			_commit_agent_tool_result()
			return {
				"call_id": resolved_call_id,
				"tool": resolved_tool,
				"status": "retryable_error",
				"data": {},
				"model_context": {},
				"citations": [],
				"error": {
					"code": "AI_AGENT_TOOL_IN_PROGRESS",
					"message": "相同工具调用正在执行，请稍后读取原结果。",
				},
				"retryable": True,
			}
		step_id = claim["step_id"]
	started = time.perf_counter()
	try:
		previous_user = str(getattr(frappe.session, "user", None) or "Guest")
	except RuntimeError:
		# Unit workers and background processes may not have a bound Frappe
		# request-local session yet. set_user() will establish the execution
		# identity for the scoped tool call below.
		previous_user = "Guest"
	try:
		_switch_user(user)
		if approval and approval.get("status") in {"rejected", "expired"}:
			result = {
				"call_id": resolved_call_id, "tool": resolved_tool, "status": "denied",
				"data": {"approval_id": approval["approval_id"], "approval_status": approval["status"]},
				"model_context": {}, "citations": [],
				"error": {
					"code": "AI_AGENT_TOOL_REJECTED" if approval["status"] == "rejected" else "AI_AGENT_APPROVAL_EXPIRED",
					"message": "该工具调用未获人工批准。" if approval["status"] == "rejected" else "该工具调用的审批已过期。",
				},
				"retryable": False,
			}
		elif resolved_tool == "search_products":
			context, citations, status = _execute_search_products(args, company=company)
			result = None
		elif resolved_tool == "query_business_documents":
			context, citations, status = _execute_business_documents(args, company=company)
			result = None
		else:
			context, citations, status = _execute_business_report(args, company=company)
			result = None
		if result is None:
			result = {
				"call_id": resolved_call_id,
				"tool": resolved_tool,
				"status": status,
				"data": {"result_count": len(citations)},
				"model_context": context,
				"citations": citations,
				"grounding": _build_grounding_contract(
					context=context, citations=citations, company=company,
				),
				"error": None,
				"retryable": False,
			}
	except frappe.PermissionError:
		result = {
			"call_id": resolved_call_id, "tool": resolved_tool, "status": "denied",
			"data": {}, "model_context": {}, "citations": [],
			"error": {"code": "AI_AGENT_TOOL_DENIED", "message": "当前用户无权执行该工具。"},
			"retryable": False,
		}
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("AI Agent 工具执行失败"))
		result = {
			"call_id": resolved_call_id, "tool": resolved_tool, "status": "retryable_error",
			"data": {}, "model_context": {}, "citations": [],
			"error": {"code": "AI_AGENT_TOOL_UNAVAILABLE", "message": "工具暂时不可用。"},
			"retryable": True,
		}
	finally:
		_switch_user(previous_user)

	ai_repository.complete_agent_tool_step(
		step_id=step_id,
		user=user,
		result=result,
		latency_ms=int((time.perf_counter() - started) * 1000),
	)
	if approval and approval.get("status") == "approved":
		ai_repository.mark_agent_tool_approval_executed(
			approval_id=approval["approval_id"], result=result, user=user,
		)
	_commit_agent_tool_result()
	return result
