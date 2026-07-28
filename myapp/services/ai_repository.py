from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_datetime, now_datetime

from myapp.utils.ai_errors import AiDraftVersionConflictError


CONVERSATION_TABLE = "tabMyApp AI Conversation"
MESSAGE_TABLE = "tabMyApp AI Message"
RUN_TABLE = "tabMyApp AI Run"
AGENT_STEP_TABLE = "tabMyApp AI Agent Step"
AGENT_APPROVAL_TABLE = "tabMyApp AI Agent Approval"
FEEDBACK_TABLE = "tabMyApp AI Feedback"
DRAFT_TABLE = "tabMyApp AI Draft"
DRAFT_LINE_TABLE = "tabMyApp AI Draft Line"
DRAFT_VERSION_TABLE = "tabMyApp AI Draft Version"
DEFAULT_RETENTION_DAYS = 30
DEFAULT_CONVERSATION_STATE_TTL_HOURS = 168
MAX_CONVERSATION_PAGE_SIZE = 50
DEFAULT_MESSAGE_PAGE_SIZE = 40
MAX_MESSAGE_PAGE_SIZE = 100
MAX_DRAFT_PAGE_SIZE = 100
MAX_CONVERSATION_STATE_BYTES = 12000
MAX_AGENT_STATE_BYTES = 200000
MAX_AGENT_EVENT_BYTES = 30000
MAX_AGENT_APPROVAL_ARGUMENT_BYTES = 30000
CONVERSATION_STATE_SCHEMA_VERSION = "conversation-state-v1"
ALLOWED_CONTEXT_SCENARIOS = {"general", "product_search", "order_query", "report_summary"}
ALLOWED_ORDER_ENTITIES = {"sales_order", "sales_invoice", "purchase_order", "purchase_invoice"}
ALLOWED_ORDER_STATUSES = {"all", "unfinished", "completed", "cancelled", "delivering", "receiving", "paying"}
ALLOWED_ORDER_SORTS = {"latest", "oldest", "amount_desc", "amount_asc"}
ALLOWED_DATE_PRESETS = {"all", "today", "this_week", "last_month", "this_month", "last_30_days", "custom"}
ALLOWED_REPORT_TYPES = {"overview", "sales", "purchase", "cashflow", "receivable_payable"}


def _name(prefix: str) -> str:
	return f"{prefix}-{uuid.uuid4().hex}"


def _retention_days() -> int:
	try:
		value = int(os.environ.get("MYAPP_AI_RETENTION_DAYS", DEFAULT_RETENTION_DAYS))
	except (TypeError, ValueError):
		value = DEFAULT_RETENTION_DAYS
	return max(1, min(value, 365))


def _conversation_state_ttl_hours() -> int:
	try:
		value = int(os.environ.get(
			"MYAPP_AI_CONVERSATION_STATE_TTL_HOURS",
			DEFAULT_CONVERSATION_STATE_TTL_HOURS,
		))
	except (TypeError, ValueError):
		value = DEFAULT_CONVERSATION_STATE_TTL_HOURS
	return max(1, min(value, 720))


def _default_conversation_state() -> dict:
	return {
		"schema_version": CONVERSATION_STATE_SCHEMA_VERSION,
		"active_scenario": "general",
	}


def _conversation_state_has_context(state: dict) -> bool:
	return bool(
		state.get("active_scenario") != "general"
		or any(state.get(key) for key in ("product", "order", "report", "last_result_set"))
	)


def _conversation_state_expires_at(updated_at):
	if not updated_at:
		return None
	try:
		return get_datetime(updated_at) + timedelta(hours=_conversation_state_ttl_hours())
	except (TypeError, ValueError):
		return None


def _conversation_state_is_expired(updated_at, *, now=None) -> bool:
	expires_at = _conversation_state_expires_at(updated_at)
	if not expires_at:
		return False
	current_time = get_datetime(now) if now is not None else datetime.now()
	return expires_at <= current_time


def _ensure_tables():
	if not frappe.db.table_exists("MyApp AI Conversation"):
		frappe.throw(_("AI 会话表尚未初始化，请先执行 bench migrate。"))


def _safe_json_loads(value, default):
	if not value:
		return default
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return default


def _bounded_text(value, *, limit: int = 200) -> str | None:
	resolved = " ".join(str(value or "").strip().split())
	return resolved[:limit] or None


def _normalize_conversation_state(state) -> dict:
	"""Validate the small, server-owned working state persisted between turns."""
	if state in (None, ""):
		state = {}
	if isinstance(state, str):
		try:
			state = json.loads(state)
		except (TypeError, ValueError):
			frappe.throw(_("AI 会话状态格式不正确。"))
	if not isinstance(state, dict):
		frappe.throw(_("AI 会话状态格式不正确。"))
	allowed_top_level = {
		"schema_version", "active_scenario", "product", "order", "report", "last_result_set",
	}
	if set(state) - allowed_top_level:
		frappe.throw(_("AI 会话状态包含不受支持的字段。"))

	active_scenario = str(state.get("active_scenario") or "general").strip()
	if active_scenario not in ALLOWED_CONTEXT_SCENARIOS:
		active_scenario = "general"
	result = {
		"schema_version": CONVERSATION_STATE_SCHEMA_VERSION,
		"active_scenario": active_scenario,
	}

	product = state.get("product")
	if isinstance(product, dict):
		allowed_product = {"query", "item_code", "item_name", "resolution_status"}
		if set(product) - allowed_product:
			frappe.throw(_("AI 商品上下文包含不受支持的字段。"))
		resolution_status = str(product.get("resolution_status") or "").strip()
		result["product"] = {
			"query": _bounded_text(product.get("query")),
			"item_code": _bounded_text(product.get("item_code"), limit=140),
			"item_name": _bounded_text(product.get("item_name"), limit=140),
			"resolution_status": resolution_status if resolution_status in {"resolved", "ambiguous", "not_found"} else None,
		}

	order = state.get("order")
	if isinstance(order, dict):
		allowed_order = {
			"entities", "date_preset", "date_from", "date_to", "status", "sort", "min_amount", "limit",
		}
		if set(order) - allowed_order:
			frappe.throw(_("AI 单据上下文包含不受支持的字段。"))
		entities = order.get("entities") if isinstance(order.get("entities"), list) else []
		entities = [entity for entity in entities if entity in ALLOWED_ORDER_ENTITIES][:4]
		date_preset = str(order.get("date_preset") or "all").strip()
		status = str(order.get("status") or "all").strip()
		sort = str(order.get("sort") or "latest").strip()
		min_amount = order.get("min_amount")
		if not isinstance(min_amount, (int, float)) or isinstance(min_amount, bool):
			min_amount = None
		else:
			min_amount = max(0, min(float(min_amount), 1000000000000000))
		result["order"] = {
			"entities": entities,
			"date_preset": date_preset if date_preset in ALLOWED_DATE_PRESETS else "all",
			"date_from": _bounded_text(order.get("date_from"), limit=10),
			"date_to": _bounded_text(order.get("date_to"), limit=10),
			"status": status if status in ALLOWED_ORDER_STATUSES else "all",
			"sort": sort if sort in ALLOWED_ORDER_SORTS else "latest",
			"min_amount": min_amount,
			"limit": max(1, min(20, cint(order.get("limit")) or 10)),
		}

	report = state.get("report")
	if isinstance(report, dict):
		allowed_report = {"report_type", "date_preset", "date_from", "date_to"}
		if set(report) - allowed_report:
			frappe.throw(_("AI 报表上下文包含不受支持的字段。"))
		report_type = str(report.get("report_type") or "overview").strip()
		date_preset = str(report.get("date_preset") or "all").strip()
		result["report"] = {
			"report_type": report_type if report_type in ALLOWED_REPORT_TYPES else "overview",
			"date_preset": date_preset if date_preset in ALLOWED_DATE_PRESETS else "all",
			"date_from": _bounded_text(report.get("date_from"), limit=10),
			"date_to": _bounded_text(report.get("date_to"), limit=10),
		}

	last_result_set = state.get("last_result_set")
	if isinstance(last_result_set, dict):
		allowed_result = {"type", "id", "entity_ids", "scope"}
		if set(last_result_set) - allowed_result:
			frappe.throw(_("AI 结果集上下文包含不受支持的字段。"))
		entity_ids = last_result_set.get("entity_ids") if isinstance(last_result_set.get("entity_ids"), list) else []
		scope = last_result_set.get("scope") if isinstance(last_result_set.get("scope"), dict) else {}
		allowed_scope = {
			"company", "report_type", "date_range", "date_from", "date_to", "status_filter",
			"exclude_cancelled", "sort_by", "min_amount", "limit_per_group",
		}
		result["last_result_set"] = {
			"type": _bounded_text(last_result_set.get("type"), limit=40),
			"id": _bounded_text(last_result_set.get("id"), limit=140),
			"entity_ids": [_bounded_text(value, limit=140) for value in entity_ids[:20] if _bounded_text(value, limit=140)],
			"scope": {key: scope[key] for key in allowed_scope if key in scope},
		}

	encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
	if len(encoded.encode("utf-8")) > MAX_CONVERSATION_STATE_BYTES:
		frappe.throw(_("AI 会话状态超过允许大小。"))
	return result


def _serialize_conversation(row) -> dict:
	return {
		"name": row.name,
		"title": row.title or _("新会话"),
		"status": row.status,
		"company": row.company_scope,
		"message_count": cint(row.message_count),
		"pending_draft_count": cint(getattr(row, "pending_draft_count", 0)),
		"last_message_at": str(row.last_message_at or "") or None,
		"creation": str(row.creation or "") or None,
		"modified": str(row.modified or "") or None,
	}


def _serialize_message_run(row, *, include_advanced_diagnostics: bool) -> dict | None:
	if not row.run_id:
		return None
	run = {
		"status": row.run_status,
		"latency_ms": cint(row.latency_ms),
		"error_code": row.error_code,
		"error": row.error,
	}
	if include_advanced_diagnostics:
		run.update({
			"model_alias": row.model_alias,
			"model": row.model,
			"trace_id": row.trace_id,
			"usage": {
				"prompt_tokens": cint(row.prompt_tokens),
				"completion_tokens": cint(row.completion_tokens),
				"total_tokens": cint(row.total_tokens),
				"reasoning_tokens": cint(row.reasoning_tokens),
			},
			"first_token_ms": cint(row.first_token_ms) if row.first_token_ms is not None else None,
		})
	return run


def _get_owned_conversation(conversation_id: str, user: str, *, for_update: bool = False):
	lock_sql = " FOR UPDATE" if for_update else ""
	rows = frappe.db.sql(
		f"""
		SELECT name, title, status, company_scope, message_count, last_message_at, creation, modified,
			state_version, working_state_json, state_updated_at, context_start_sequence
		FROM `{CONVERSATION_TABLE}`
		WHERE name = %s AND owner = %s
		LIMIT 1{lock_sql}
		""",
		(conversation_id, user),
		as_dict=True,
	)
	if not rows:
		raise frappe.PermissionError(_("AI 会话不存在或无权访问。"))
	return rows[0]


def create_conversation(*, user: str, title: str | None = None, company: str | None = None) -> dict:
	_ensure_tables()
	now = now_datetime()
	conversation_id = _name("AI-CONV")
	resolved_title = " ".join((title or "").split())[:120] or _("新会话")
	frappe.db.sql(
		f"""
		INSERT INTO `{CONVERSATION_TABLE}`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 status, title, company_scope, message_count, last_message_at, retention_until,
			 state_version, working_state_json, state_updated_at, context_start_sequence)
		VALUES (%s, %s, %s, %s, %s, 0, 0, 'active', %s, %s, 0, %s, %s, 0, NULL, NULL, 1)
		""",
		(
			conversation_id,
			now,
			now,
			user,
			user,
			resolved_title,
			(company or "").strip() or None,
			now,
			add_days(now, _retention_days()),
		),
	)
	return _serialize_conversation(_get_owned_conversation(conversation_id, user))


def _reset_conversation_state_row(*, conversation, user: str, reason: str) -> dict:
	current_version = max(0, cint(getattr(conversation, "state_version", 0)))
	next_version = current_version + 1
	now = now_datetime()
	context_start_sequence = max(1, cint(getattr(conversation, "message_count", 0)) + 1)
	state = _default_conversation_state()
	frappe.db.sql(
		f"""
		UPDATE `{CONVERSATION_TABLE}`
		SET working_state_json = %s, state_version = %s, state_updated_at = %s,
			context_start_sequence = %s, modified = %s, modified_by = %s
		WHERE name = %s AND owner = %s AND state_version = %s
		""",
		(
			frappe.as_json(state), next_version, now, context_start_sequence, now, user,
			conversation.name, user, current_version,
		),
	)
	return {
		"version": next_version,
		"state": state,
		"status": "empty",
		"reset_reason": reason,
		"updated_at": str(now),
		"expires_at": str(_conversation_state_expires_at(now)),
		"context_start_sequence": context_start_sequence,
	}


def get_conversation_state(
	*, conversation_id: str, user: str, expire_if_needed: bool = False,
) -> dict:
	resolved_conversation_id = (conversation_id or "").strip()
	conversation = (
		_get_owned_conversation(resolved_conversation_id, user, for_update=True)
		if expire_if_needed
		else _get_owned_conversation(resolved_conversation_id, user)
	)
	raw_state = getattr(conversation, "working_state_json", None)
	state = {}
	status = "empty"
	reset_reason = None
	try:
		if raw_state:
			state = json.loads(raw_state) if isinstance(raw_state, str) else raw_state
		state = _normalize_conversation_state(state)
	except Exception:
		state = _default_conversation_state()
		status = "invalid"
		reset_reason = "invalid_state"
	else:
		status = "active" if _conversation_state_has_context(state) else "empty"
	updated_at = getattr(conversation, "state_updated_at", None)
	if status == "active" and _conversation_state_is_expired(updated_at):
		state = _default_conversation_state()
		status = "expired"
		reset_reason = "expired"
	if expire_if_needed and reset_reason:
		return _reset_conversation_state_row(
			conversation=conversation, user=user, reason=reset_reason,
		)
	expires_at = _conversation_state_expires_at(updated_at) if status == "active" else None
	return {
		"version": max(0, cint(getattr(conversation, "state_version", 0))),
		"state": state,
		"status": status,
		"reset_reason": reset_reason,
		"updated_at": str(updated_at or "") or None,
		"expires_at": str(expires_at) if expires_at else None,
		"context_start_sequence": max(1, cint(getattr(conversation, "context_start_sequence", 1)) or 1),
	}


def reset_conversation_state(*, conversation_id: str, user: str) -> dict:
	conversation = _get_owned_conversation(
		(conversation_id or "").strip(), user, for_update=True,
	)
	if getattr(conversation, "status", "active") != "active":
		frappe.throw(_("已归档的 AI 会话不能修改工作上下文。"))
	return _reset_conversation_state_row(
		conversation=conversation, user=user, reason="user_reset",
	)


def update_conversation_state(
	*, conversation_id: str, user: str, state: dict, expected_version: int,
) -> dict:
	normalized = _normalize_conversation_state(state)
	conversation = _get_owned_conversation((conversation_id or "").strip(), user, for_update=True)
	current_version = max(0, cint(getattr(conversation, "state_version", 0)))
	if current_version != max(0, cint(expected_version)):
		return {"updated": False, "version": current_version, "reason": "version_conflict"}
	next_version = current_version + 1
	now = now_datetime()
	frappe.db.sql(
		f"""
		UPDATE `{CONVERSATION_TABLE}`
		SET working_state_json = %s, state_version = %s, state_updated_at = %s,
			modified = %s, modified_by = %s
		WHERE name = %s AND owner = %s AND state_version = %s
		""",
		(
			frappe.as_json(normalized), next_version, now, now, user,
			conversation.name, user, current_version,
		),
	)
	return {"updated": True, "version": next_version, "state": normalized, "updated_at": str(now)}


def list_conversations(
	*, user: str, status: str = "active", search: str | None = None,
	start: int = 0, limit: int = 20,
) -> dict:
	_ensure_tables()
	resolved_status = (status or "active").strip().lower()
	if resolved_status not in {"active", "archived", "all"}:
		frappe.throw(_("AI 会话状态筛选不正确。"))
	resolved_search = " ".join(str(search or "").split())[:100]
	start = max(0, cint(start))
	limit = max(1, min(MAX_CONVERSATION_PAGE_SIZE, cint(limit) or 20))
	conditions = ["c.owner = %s"]
	params: list = [user]
	if resolved_status != "all":
		conditions.append("c.status = %s")
		params.append(resolved_status)
	if resolved_search:
		conditions.append(
			f"(LOCATE(%s, c.title) > 0 OR EXISTS ("
			f"SELECT 1 FROM `{MESSAGE_TABLE}` m "
			"WHERE m.conversation = c.name AND LOCATE(%s, m.content) > 0))"
		)
		params.extend([resolved_search, resolved_search])
	where_sql = " AND ".join(conditions)
	count_rows = frappe.db.sql(
		f"SELECT COUNT(*) AS total FROM `{CONVERSATION_TABLE}` c WHERE {where_sql}",
		tuple(params),
		as_dict=True,
	)
	pending_rows = frappe.db.sql(
		f"SELECT COUNT(*) AS total FROM `{DRAFT_TABLE}` WHERE owner = %s AND status = 'draft'",
		(user,), as_dict=True,
	)
	rows = frappe.db.sql(
		f"""
		SELECT c.name, c.title, c.status, c.company_scope, c.message_count,
			c.last_message_at, c.creation, c.modified,
			COALESCE(d.pending_draft_count, 0) AS pending_draft_count
		FROM `{CONVERSATION_TABLE}` c
		LEFT JOIN (
			SELECT conversation, COUNT(*) AS pending_draft_count
			FROM `{DRAFT_TABLE}`
			WHERE owner = %s AND status = 'draft'
			GROUP BY conversation
		) d ON d.conversation = c.name
		WHERE {where_sql}
		ORDER BY c.last_message_at DESC, c.creation DESC
		LIMIT %s OFFSET %s
		""",
		(user, *params, limit, start),
		as_dict=True,
	)
	return {
		"items": [_serialize_conversation(row) for row in rows],
		"pagination": {"start": start, "limit": limit, "total": cint(count_rows[0].total if count_rows else 0)},
		"pending_draft_total": cint(pending_rows[0].total if pending_rows else 0),
	}


def rename_conversation(*, conversation_id: str, user: str, title: str) -> dict:
	conversation = _get_owned_conversation((conversation_id or "").strip(), user, for_update=True)
	resolved_title = " ".join(str(title or "").split())
	if not resolved_title:
		frappe.throw(_("AI 会话名称不能为空。"))
	if len(resolved_title) > 120:
		frappe.throw(_("AI 会话名称不能超过 120 个字符。"))
	frappe.db.sql(
		f"UPDATE `{CONVERSATION_TABLE}` SET title = %s, modified = %s, modified_by = %s WHERE name = %s",
		(resolved_title, now_datetime(), user, conversation.name),
	)
	return _serialize_conversation(_get_owned_conversation(conversation.name, user))


def get_conversation(
	*,
	conversation_id: str,
	user: str,
	before_sequence: int | None = None,
	limit: int = DEFAULT_MESSAGE_PAGE_SIZE,
	include_advanced_diagnostics: bool = False,
) -> dict:
	_ensure_tables()
	conversation = _get_owned_conversation((conversation_id or "").strip(), user)
	resolved_limit = max(1, min(MAX_MESSAGE_PAGE_SIZE, cint(limit) or DEFAULT_MESSAGE_PAGE_SIZE))
	resolved_before = None
	if before_sequence not in (None, ""):
		resolved_before = cint(before_sequence)
		if resolved_before <= 0:
			frappe.throw(_("AI 消息分页游标不正确。"))
	sequence_sql = ""
	params = [user, user, conversation.name]
	if resolved_before is not None:
		sequence_sql = " AND m.sequence_no < %s"
		params.append(resolved_before)
	rows = frappe.db.sql(
		f"""
		SELECT m.name, m.sequence_no, m.role, m.content, m.scenario, m.run_id,
			m.citations_json, m.prompt_version, m.creation,
			r.status AS run_status, r.model_alias, r.model, r.trace_id,
			r.prompt_tokens, r.completion_tokens, r.total_tokens, r.reasoning_tokens,
			r.latency_ms, r.first_token_ms, r.error_code, r.error,
			f.rating AS feedback_rating, f.category AS feedback_category,
			f.comment AS feedback_comment
		FROM `{MESSAGE_TABLE}` m
		LEFT JOIN `{RUN_TABLE}` r ON r.name = m.run_id AND r.requested_by = %s
		LEFT JOIN `{FEEDBACK_TABLE}` f ON f.run_id = m.run_id AND f.owner = %s
		WHERE m.conversation = %s{sequence_sql}
		ORDER BY m.sequence_no DESC
		LIMIT %s
		""",
		(*params, resolved_limit + 1),
		as_dict=True,
	)
	has_more = len(rows) > resolved_limit
	messages = list(reversed(rows[:resolved_limit]))
	next_before_sequence = cint(messages[0].sequence_no) if has_more and messages else None
	return {
		"conversation": _serialize_conversation(conversation),
		"context": get_conversation_state(
			conversation_id=conversation.name,
			user=user,
		),
		"messages": [
			{
				"name": row.name,
				"sequence": cint(row.sequence_no),
				"role": row.role,
				"content": row.content or "",
				"scenario": row.scenario,
				"run_id": row.run_id,
				"citations": _refresh_conversation_citations(
					_safe_json_loads(row.citations_json, []), user=user,
				),
				"prompt_version": row.prompt_version,
				"creation": str(row.creation or "") or None,
				"run": _serialize_message_run(
					row,
					include_advanced_diagnostics=include_advanced_diagnostics,
				),
				"feedback": {
					"rating": row.feedback_rating,
					"category": row.feedback_category,
					"comment": row.feedback_comment,
				} if row.feedback_rating else None,
			}
			for row in messages
		],
		"pagination": {
			"before_sequence": resolved_before,
			"limit": resolved_limit,
			"total": cint(conversation.message_count),
			"returned_count": len(messages),
			"has_more": has_more,
			"next_before_sequence": next_before_sequence,
		},
	}


def archive_conversation(*, conversation_id: str, user: str) -> dict:
	conversation = _get_owned_conversation((conversation_id or "").strip(), user, for_update=True)
	if conversation.status != "archived":
		frappe.db.sql(
			f"UPDATE `{CONVERSATION_TABLE}` SET status = 'archived', modified = %s, modified_by = %s WHERE name = %s",
			(now_datetime(), user, conversation.name),
		)
	return _serialize_conversation(_get_owned_conversation(conversation.name, user))


def append_message(
	*,
	conversation_id: str,
	user: str,
	role: str,
	content: str,
	scenario: str,
	run_id: str | None = None,
	citations: list[dict] | None = None,
	prompt_version: str | None = None,
) -> dict:
	conversation = _get_owned_conversation(conversation_id, user, for_update=True)
	if conversation.status != "active":
		frappe.throw(_("已归档的 AI 会话不能继续发送消息。"))
	now = now_datetime()
	sequence_no = cint(conversation.message_count) + 1
	message_id = _name("AI-MSG")
	frappe.db.sql(
		f"""
		INSERT INTO `{MESSAGE_TABLE}`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 conversation, sequence_no, role, content, content_hash, scenario,
			 run_id, citations_json, prompt_version)
		VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s)
		""",
		(
			message_id,
			now,
			now,
			user,
			user,
			conversation_id,
			sequence_no,
			role,
			content,
			hashlib.sha256(content.encode("utf-8")).hexdigest(),
			scenario,
			run_id,
			frappe.as_json(citations or []),
			prompt_version,
		),
	)
	frappe.db.sql(
		f"""
		UPDATE `{CONVERSATION_TABLE}`
		SET modified = %s, modified_by = %s, message_count = %s,
			last_message_at = %s, retention_until = %s
		WHERE name = %s
		""",
		(now, user, sequence_no, now, add_days(now, _retention_days()), conversation_id),
	)
	return {"name": message_id, "sequence": sequence_no}


def load_model_messages(*, conversation_id: str, user: str, limit: int = 20) -> list[dict]:
	conversation = _get_owned_conversation(conversation_id, user)
	context_start_sequence = max(1, cint(getattr(conversation, "context_start_sequence", 1)) or 1)
	rows = frappe.db.sql(
		f"""
		SELECT role, content
		FROM `{MESSAGE_TABLE}`
		WHERE conversation = %s AND sequence_no >= %s
		ORDER BY sequence_no DESC
		LIMIT %s
		""",
		(conversation_id, context_start_sequence, max(1, min(20, cint(limit) or 20))),
		as_dict=True,
	)
	return [{"role": row.role, "content": row.content or ""} for row in reversed(rows)]


def create_run(
	*, conversation_id: str, user: str, scenario: str,
	tool_calls: list[dict] | None = None, model_alias: str | None = None,
) -> str:
	_get_owned_conversation(conversation_id, user)
	now = now_datetime()
	run_id = _name("AI-RUN")
	frappe.db.sql(
		f"""
		INSERT INTO `{RUN_TABLE}`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 conversation, requested_by, scenario, environment, status, model_alias, tool_calls_json, started_at)
		VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, 'running', %s, %s, %s)
		""",
		(
			run_id, now, now, user, user, conversation_id, user, scenario,
			os.environ.get("MYAPP_AI_ENVIRONMENT", "development").strip() or "development",
			model_alias, frappe.as_json(tool_calls or []), now,
		),
	)
	return run_id


def issue_agent_capability(
	*, run_id: str, user: str, allowed_tools: list[str], ttl_seconds: int = 300,
) -> str:
	"""Issue one opaque, short-lived capability for a single owned Agent Run."""
	resolved_tools = sorted({str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()})
	if not resolved_tools:
		frappe.throw(_("Agent Run 没有可用工具。"))
	run_rows = frappe.db.sql(
		f"""
		SELECT status
		FROM `{RUN_TABLE}`
		WHERE name = %s AND requested_by = %s
		LIMIT 1
		FOR UPDATE
		""",
		(run_id, user),
		as_dict=True,
	)
	if not run_rows or str(run_rows[0].status or "") != "running":
		raise frappe.PermissionError(_("Agent Run 不存在或已结束，不能签发能力令牌。"))
	token = secrets.token_urlsafe(32)
	token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
	now = now_datetime()
	expires_at = now + timedelta(seconds=max(30, min(int(ttl_seconds or 300), 900)))
	frappe.db.sql(
		f"""
		UPDATE `{RUN_TABLE}`
		SET allowed_tools_json = %s, capability_token_hash = %s,
			capability_expires_at = %s, modified = %s, modified_by = %s
		WHERE name = %s AND requested_by = %s AND status = 'running'
		""",
		(frappe.as_json(resolved_tools), token_hash, expires_at, now, user, run_id, user),
	)
	return token


def validate_agent_run_capability(*, run_id: str, capability_token: str) -> dict:
	rows = frappe.db.sql(
		f"""
		SELECT r.name, r.requested_by, r.status, r.allowed_tools_json,
			r.capability_token_hash, r.capability_expires_at, r.cancellation_requested,
			c.company_scope
		FROM `{RUN_TABLE}` r
		JOIN `{CONVERSATION_TABLE}` c ON c.name = r.conversation
		WHERE r.name = %s
		LIMIT 1
		""",
		(run_id,), as_dict=True,
	)
	if not rows:
		raise frappe.PermissionError(_("Agent Run 不存在。"))
	row = rows[0]
	if row.status != "running" or cint(row.cancellation_requested):
		raise frappe.PermissionError(_("Agent Run 已停止，不能继续执行工具。"))
	if not row.capability_expires_at or get_datetime(row.capability_expires_at) <= now_datetime():
		raise frappe.PermissionError(_("Agent 能力令牌已过期。"))
	provided_hash = hashlib.sha256(str(capability_token or "").encode("utf-8")).hexdigest()
	if not row.capability_token_hash or not hmac.compare_digest(provided_hash, row.capability_token_hash):
		raise frappe.PermissionError(_("Agent 能力令牌无效。"))
	allowed_tools = _safe_json_loads(row.allowed_tools_json, [])
	return {
		"run_id": row.name,
		"user": row.requested_by,
		"company": row.company_scope,
		"allowed_tools": allowed_tools,
	}


def validate_agent_capability(*, run_id: str, capability_token: str, tool: str) -> dict:
	capability = validate_agent_run_capability(
		run_id=run_id, capability_token=capability_token,
	)
	allowed_tools = capability["allowed_tools"]
	if tool not in allowed_tools:
		raise frappe.PermissionError(_("当前 Agent Run 无权调用该工具。"))
	return capability


def get_agent_run_control(*, run_id: str) -> dict:
	"""Return the minimum internal control state needed for cancellation propagation."""
	rows = frappe.db.sql(
		f"""
		SELECT status, cancellation_requested
		FROM `{RUN_TABLE}`
		WHERE name = %s
		LIMIT 1
		""",
		(run_id,),
		as_dict=True,
	)
	if not rows:
		return {"run_id": run_id, "status": "missing", "cancelled": True}
	status = str(rows[0].status or "")
	return {
		"run_id": run_id,
		"status": status,
		"cancelled": bool(cint(rows[0].cancellation_requested) or status == "cancelled"),
	}


def _normalize_agent_checkpoint(checkpoint, *, run_id: str | None = None) -> dict | None:
	if checkpoint in (None, ""):
		return None
	if isinstance(checkpoint, str):
		checkpoint = _safe_json_loads(checkpoint, None)
	allowed_keys = {
		"schema_version", "run_id", "stage", "next_model_step", "tool_count",
		"runtime_messages", "agent_steps", "tool_calls", "pending_tool_calls",
		"tool_results", "citations",
		"usage", "model", "trace_id", "agent_span_id", "final_content",
		"model_alias", "prompt_version",
		"pending_approval",
	}
	if (
		not isinstance(checkpoint, dict)
		or checkpoint.get("schema_version") != "agent-state-v1"
		or set(checkpoint) - allowed_keys
		or (run_id and str(checkpoint.get("run_id") or "") != run_id)
	):
		frappe.throw(_("Agent 检查点格式不正确。"))
	if checkpoint.get("stage") not in {
		"input_guardrail", "model_decision", "tool_completed", "waiting_approval", "output_guardrail",
	}:
		frappe.throw(_("Agent 检查点阶段不正确。"))
	if checkpoint.get("stage") == "waiting_approval":
		pending_approval = checkpoint.get("pending_approval")
		if not isinstance(pending_approval, dict):
			frappe.throw(_("Agent 待审批检查点缺少审批上下文。"))
		if set(pending_approval) - {"approval_id", "call_id", "tool", "risk_level"}:
			frappe.throw(_("Agent 待审批上下文字段不正确。"))
	if not isinstance(checkpoint.get("runtime_messages") or [], list) or len(checkpoint.get("runtime_messages") or []) > 40:
		frappe.throw(_("Agent 检查点消息数量超出限制。"))
	if not isinstance(checkpoint.get("agent_steps") or [], list) or len(checkpoint.get("agent_steps") or []) > 40:
		frappe.throw(_("Agent 检查点步骤数量超出限制。"))
	if not isinstance(checkpoint.get("tool_calls") or [], list) or len(checkpoint.get("tool_calls") or []) > 6:
		frappe.throw(_("Agent 检查点工具调用数量超出限制。"))
	if not isinstance(checkpoint.get("pending_tool_calls") or [], list) or len(checkpoint.get("pending_tool_calls") or []) > 3:
		frappe.throw(_("Agent 检查点待执行工具数量超出限制。"))
	if not isinstance(checkpoint.get("tool_results") or [], list) or len(checkpoint.get("tool_results") or []) > 6:
		frappe.throw(_("Agent 检查点工具结果数量超出限制。"))
	if not isinstance(checkpoint.get("citations") or [], list) or len(checkpoint.get("citations") or []) > 100:
		frappe.throw(_("Agent 检查点引用数量超出限制。"))
	if _contains_agent_secret_key(checkpoint):
		frappe.throw(_("Agent 检查点包含不允许持久化的敏感字段。"))
	encoded = frappe.as_json(checkpoint).encode("utf-8")
	if len(encoded) > MAX_AGENT_STATE_BYTES:
		frappe.throw(_("Agent 检查点超过持久化大小限制。"))
	return checkpoint


def _canonical_agent_arguments(arguments) -> tuple[dict, str, str]:
	if not isinstance(arguments, dict):
		frappe.throw(_("Agent 工具参数必须是对象。"))
	if _contains_agent_secret_key(arguments):
		frappe.throw(_("Agent 工具参数包含不允许进入审批记录的敏感字段。"))
	encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
	if len(encoded.encode("utf-8")) > MAX_AGENT_APPROVAL_ARGUMENT_BYTES:
		frappe.throw(_("Agent 工具参数超过审批大小限制。"))
	return arguments, encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _summarize_agent_arguments(value, *, depth: int = 0):
	if depth >= 3:
		return "[truncated]"
	if isinstance(value, dict):
		result = {}
		for index, (key, child) in enumerate(sorted(value.items())):
			if index >= 20:
				result["_truncated"] = True
				break
			resolved_key = str(key)[:80]
			if resolved_key.strip().lower() in {
				"authorization", "api_key", "apikey", "capability_token", "cookie",
				"password", "service_token",
			}:
				result[resolved_key] = "[redacted]"
			else:
				result[resolved_key] = _summarize_agent_arguments(child, depth=depth + 1)
		return result
	if isinstance(value, list):
		result = [_summarize_agent_arguments(child, depth=depth + 1) for child in value[:20]]
		if len(value) > 20:
			result.append("[truncated]")
		return result
	if isinstance(value, str):
		return value[:300]
	if value is None or isinstance(value, (bool, int, float)):
		return value
	return str(value)[:300]


def _agent_checkpoint_pending_call(checkpoint: dict) -> tuple[dict, dict]:
	pending_calls = checkpoint.get("pending_tool_calls") or []
	pending_approval = checkpoint.get("pending_approval") or {}
	if checkpoint.get("stage") != "waiting_approval" or not pending_calls:
		frappe.throw(_("Agent 待审批检查点没有待执行工具调用。"))
	call = pending_calls[0]
	if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
		frappe.throw(_("Agent 待审批工具调用格式不正确。"))
	arguments = call.get("arguments")
	if arguments is None:
		arguments = _safe_json_loads(call["function"].get("arguments"), None)
	if not isinstance(arguments, dict):
		frappe.throw(_("Agent 待审批工具参数格式不正确。"))
	call_id = str(call.get("id") or "").strip()
	tool = str(call["function"].get("name") or "").strip()
	if (
		not call_id or not tool
		or str(pending_approval.get("call_id") or "") != call_id
		or str(pending_approval.get("tool") or "") != tool
	):
		frappe.throw(_("Agent 待审批上下文与工具调用不一致。"))
	return call, arguments


def _serialize_agent_approval(row, *, replayed: bool = False) -> dict:
	result = {
		"approval_id": row.name,
		"run_id": row.run_id,
		"call_id": row.call_id,
		"tool": row.tool_name,
		"risk_level": row.risk_level,
		"arguments_summary": _safe_json_loads(row.arguments_summary_json, {}),
		"status": row.status,
		"requested_by": row.requested_by,
		"requested_at": str(row.requested_at or ""),
		"reviewed_by": row.reviewed_by or None,
		"reviewed_at": str(row.reviewed_at or "") or None,
		"decision_reason": row.decision_reason or None,
		"expires_at": str(row.expires_at or ""),
		"executed_at": str(row.executed_at or "") or None,
		"version": cint(row.version),
		"replayed": replayed,
	}
	if getattr(row, "conversation_id", None):
		result["conversation_id"] = row.conversation_id
	return result


def request_agent_tool_approval(
	*, run_id: str, call_id: str, tool: str, arguments: dict, risk_level: str,
	checkpoint: dict, capability_token: str, ttl_seconds: int = 900,
) -> dict:
	"""Atomically persist the safe checkpoint and pause one approval-bound call."""
	capability = validate_agent_capability(
		run_id=run_id, capability_token=capability_token, tool=tool,
	)
	checkpoint = _normalize_agent_checkpoint(checkpoint, run_id=run_id)
	call, checkpoint_arguments = _agent_checkpoint_pending_call(checkpoint)
	arguments, _encoded, arguments_hash = _canonical_agent_arguments(arguments)
	_checkpoint_args, _checkpoint_encoded, checkpoint_hash = _canonical_agent_arguments(checkpoint_arguments)
	resolved_call_id = str(call_id or "").strip()[:140]
	resolved_tool = str(tool or "").strip()[:140]
	resolved_risk = str(risk_level or "").strip()[:30]
	if (
		call.get("id") != resolved_call_id
		or str((call.get("function") or {}).get("name") or "") != resolved_tool
		or checkpoint_hash != arguments_hash
		or str((checkpoint.get("pending_approval") or {}).get("risk_level") or "") != resolved_risk
	):
		frappe.throw(_("Agent 审批请求与持久检查点不一致。"))
	now = now_datetime()
	run_rows = frappe.db.sql(
		f"SELECT requested_by, status, last_step_no FROM `{RUN_TABLE}` WHERE name = %s FOR UPDATE",
		(run_id,), as_dict=True,
	)
	if not run_rows or run_rows[0].requested_by != capability["user"]:
		raise frappe.PermissionError(_("Agent Run 不存在或无权请求审批。"))
	if str(run_rows[0].status or "") != "running":
		raise frappe.PermissionError(_("Agent Run 已停止，不能请求审批。"))
	existing = frappe.db.sql(
		f"SELECT * FROM `{AGENT_APPROVAL_TABLE}` WHERE run_id = %s AND call_id = %s LIMIT 1",
		(run_id, resolved_call_id), as_dict=True,
	)
	if existing:
		row = existing[0]
		if row.tool_name != resolved_tool or row.arguments_hash != arguments_hash:
			raise frappe.PermissionError(_("Agent 审批绑定的工具或参数已发生变化。"))
		if row.status == "pending" and get_datetime(row.expires_at) <= now:
			frappe.db.sql(
				f"UPDATE `{AGENT_APPROVAL_TABLE}` SET status = 'expired', modified = %s, modified_by = %s, version = version + 1 WHERE name = %s AND status = 'pending'",
				(now, capability["user"], row.name),
			)
			row.status = "expired"
			row.version = cint(row.version) + 1
		if row.status in {"approved", "rejected", "expired"}:
			return _serialize_agent_approval(row, replayed=True)
		approval_id = row.name
	else:
		approval_id = _name("AI-APPROVAL")
		expires_at = now + timedelta(seconds=max(60, min(int(ttl_seconds or 900), 86400)))
		frappe.db.sql(
			f"""
			INSERT INTO `{AGENT_APPROVAL_TABLE}`
				(name, creation, modified, modified_by, owner, docstatus, idx,
				 run_id, call_id, tool_name, risk_level, arguments_hash,
				 arguments_summary_json, status, requested_by, requested_at, expires_at, version)
			VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, %s, %s,
				'pending', %s, %s, %s, 1)
			""",
			(
				approval_id, now, now, capability["user"], capability["user"],
				run_id, resolved_call_id, resolved_tool, resolved_risk, arguments_hash,
				frappe.as_json(_summarize_agent_arguments(arguments)),
				capability["user"], now, expires_at,
			),
		)
	checkpoint["pending_approval"] = {
		"approval_id": approval_id, "call_id": resolved_call_id,
		"tool": resolved_tool, "risk_level": resolved_risk,
	}
	sequence_no = cint(run_rows[0].last_step_no)
	if not existing:
		sequence_no += 1
		step_id = _name("AI-STEP")
		frappe.db.sql(
			f"""
			INSERT INTO `{AGENT_STEP_TABLE}`
				(name, creation, modified, modified_by, owner, docstatus, idx,
				 run_id, sequence_no, call_id, step_type, status, tool_name, result_json, started_at)
			VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, 'approval', 'pending', %s, %s, %s)
			""",
			(
				step_id, now, now, capability["user"], capability["user"], run_id,
				sequence_no, f"approval:{resolved_call_id}"[:140], resolved_tool,
				frappe.as_json({"approval_id": approval_id, "risk_level": resolved_risk}), now,
			),
		)
	frappe.db.sql(
		f"""
		UPDATE `{RUN_TABLE}`
		SET status = 'waiting_approval', agent_state_json = %s, last_step_no = %s,
			capability_token_hash = NULL, capability_expires_at = NULL,
			modified = %s, modified_by = %s
		WHERE name = %s AND status = 'running'
		""",
		(frappe.as_json(checkpoint), sequence_no, now, capability["user"], run_id),
	)
	rows = frappe.db.sql(
		f"SELECT * FROM `{AGENT_APPROVAL_TABLE}` WHERE name = %s LIMIT 1",
		(approval_id,), as_dict=True,
	)
	return _serialize_agent_approval(rows[0], replayed=bool(existing))


def get_agent_tool_approval_decision(
	*, run_id: str, call_id: str, tool: str, arguments: dict,
) -> dict:
	"""Return the durable decision bound to the exact tool arguments."""
	_arguments, _encoded, arguments_hash = _canonical_agent_arguments(arguments)
	rows = frappe.db.sql(
		f"SELECT * FROM `{AGENT_APPROVAL_TABLE}` WHERE run_id = %s AND call_id = %s LIMIT 1",
		(run_id, call_id), as_dict=True,
	)
	if not rows:
		raise frappe.PermissionError(_("Agent 工具缺少必需的审批记录。"))
	row = rows[0]
	if row.tool_name != tool or row.arguments_hash != arguments_hash:
		raise frappe.PermissionError(_("Agent 审批绑定的工具或参数不一致。"))
	if row.status in {"pending", "approved"} and get_datetime(row.expires_at) <= now_datetime():
		now = now_datetime()
		frappe.db.sql(
			f"""
			UPDATE `{AGENT_APPROVAL_TABLE}`
			SET status = 'expired', modified = %s, modified_by = %s, version = version + 1
			WHERE name = %s AND status IN ('pending', 'approved')
			""",
			(now, row.requested_by, row.name),
		)
		row.status = "expired"
		row.version = cint(row.version) + 1
	if row.status == "pending":
		raise frappe.PermissionError(_("Agent 工具仍在等待审批。"))
	return _serialize_agent_approval(row)


def mark_agent_tool_approval_executed(
	*, approval_id: str, result: dict, user: str,
) -> None:
	now = now_datetime()
	encoded = json.dumps(result or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
	result_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
	frappe.db.sql(
		f"""
		UPDATE `{AGENT_APPROVAL_TABLE}`
		SET executed_at = COALESCE(executed_at, %s), result_hash = COALESCE(result_hash, %s),
			modified = %s, modified_by = %s
		WHERE name = %s AND status = 'approved'
		""",
		(now, result_hash, now, user, approval_id),
	)


def get_agent_approval(*, approval_id: str, user: str) -> dict:
	rows = frappe.db.sql(
		f"""
		SELECT a.*, r.status AS run_status, r.conversation AS conversation_id
		FROM `{AGENT_APPROVAL_TABLE}` a
		JOIN `{RUN_TABLE}` r ON r.name = a.run_id
		WHERE a.name = %s AND a.requested_by = %s AND r.requested_by = %s
		LIMIT 1
		""",
		(approval_id, user, user), as_dict=True,
	)
	if not rows:
		raise frappe.PermissionError(_("Agent 审批不存在或无权访问。"))
	result = _serialize_agent_approval(rows[0])
	result["run_status"] = str(rows[0].run_status or "")
	return result


def list_agent_approvals(
	*, user: str, run_id: str | None = None, status: str | None = None,
	start: int = 0, limit: int = 20,
) -> dict:
	conditions = ["a.requested_by = %s", "r.requested_by = %s"]
	params: list = [user, user]
	if run_id:
		conditions.append("a.run_id = %s")
		params.append(str(run_id).strip())
	if status:
		resolved_status = str(status).strip()
		if resolved_status not in {"pending", "approved", "rejected", "expired"}:
			frappe.throw(_("Agent 审批状态不正确。"))
		conditions.append("a.status = %s")
		params.append(resolved_status)
	resolved_start = max(0, cint(start))
	resolved_limit = max(1, min(100, cint(limit) or 20))
	rows = frappe.db.sql(
		f"""
		SELECT a.*, r.status AS run_status, r.conversation AS conversation_id
		FROM `{AGENT_APPROVAL_TABLE}` a
		JOIN `{RUN_TABLE}` r ON r.name = a.run_id
		WHERE {' AND '.join(conditions)}
		ORDER BY a.requested_at DESC
		LIMIT %s OFFSET %s
		""",
		tuple([*params, resolved_limit + 1, resolved_start]), as_dict=True,
	)
	items = []
	for row in rows[:resolved_limit]:
		item = _serialize_agent_approval(row)
		item["run_status"] = str(row.run_status or "")
		items.append(item)
	return {
		"items": items, "start": resolved_start, "limit": resolved_limit,
		"has_more": len(rows) > resolved_limit,
	}


def review_agent_approval(
	*, approval_id: str, user: str, decision: str, expected_version: int,
	reason: str | None = None,
) -> dict:
	resolved_decision = str(decision or "").strip()
	if resolved_decision not in {"approved", "rejected"}:
		frappe.throw(_("Agent 审批决定只允许 approved 或 rejected。"))
	resolved_reason = " ".join(str(reason or "").strip().split())[:500] or None
	if resolved_decision == "rejected" and not resolved_reason:
		frappe.throw(_("拒绝 Agent 工具调用时必须填写原因。"))
	rows = frappe.db.sql(
		f"""
		SELECT a.*, r.status AS run_status, r.requested_by AS run_owner, r.agent_state_json
		FROM `{AGENT_APPROVAL_TABLE}` a
		JOIN `{RUN_TABLE}` r ON r.name = a.run_id
		WHERE a.name = %s AND a.requested_by = %s AND r.requested_by = %s
		LIMIT 1
		FOR UPDATE
		""",
		(approval_id, user, user), as_dict=True,
	)
	if not rows:
		raise frappe.PermissionError(_("Agent 审批不存在或无权访问。"))
	row = rows[0]
	if cint(row.version) != cint(expected_version):
		frappe.throw(_("Agent 审批版本已变化，请刷新后重试。"))
	if row.status != "pending":
		if row.status == resolved_decision:
			result = _serialize_agent_approval(row, replayed=True)
			result["run_status"] = str(row.run_status or "")
			return result
		frappe.throw(_("Agent 审批已经完成，不能重复修改决定。"))
	if str(row.run_status or "") != "waiting_approval":
		frappe.throw(_("Agent Run 当前不处于待审批状态。"))
	checkpoint = _normalize_agent_checkpoint(row.agent_state_json, run_id=row.run_id)
	call, arguments = _agent_checkpoint_pending_call(checkpoint)
	_arguments, _encoded, arguments_hash = _canonical_agent_arguments(arguments)
	if (
		str(call.get("id") or "") != row.call_id
		or str((call.get("function") or {}).get("name") or "") != row.tool_name
		or arguments_hash != row.arguments_hash
		or str((checkpoint.get("pending_approval") or {}).get("approval_id") or "") != row.name
	):
		raise frappe.PermissionError(_("Agent 审批记录与待执行检查点不一致。"))
	now = now_datetime()
	if get_datetime(row.expires_at) <= now:
		frappe.db.sql(
			f"UPDATE `{AGENT_APPROVAL_TABLE}` SET status = 'expired', modified = %s, modified_by = %s, version = version + 1 WHERE name = %s AND status = 'pending'",
			(now, user, approval_id),
		)
		frappe.db.sql(
			f"UPDATE `{RUN_TABLE}` SET status = 'expired', modified = %s, modified_by = %s WHERE name = %s AND status = 'waiting_approval'",
			(now, user, row.run_id),
		)
		row.status = "expired"
		row.version = cint(row.version) + 1
		return _serialize_agent_approval(row)
	frappe.db.sql(
		f"""
		UPDATE `{AGENT_APPROVAL_TABLE}`
		SET status = %s, reviewed_by = %s, reviewed_at = %s, decision_reason = %s,
			modified = %s, modified_by = %s, version = version + 1
		WHERE name = %s AND status = 'pending' AND version = %s
		""",
		(resolved_decision, user, now, resolved_reason, now, user, approval_id, cint(expected_version)),
	)
	rows = frappe.db.sql(
		f"SELECT * FROM `{AGENT_APPROVAL_TABLE}` WHERE name = %s LIMIT 1",
		(approval_id,), as_dict=True,
	)
	result = _serialize_agent_approval(rows[0])
	result["run_status"] = "waiting_approval"
	return result


def prepare_reviewed_agent_approval_resume(*, approval_id: str, user: str) -> dict:
	rows = frappe.db.sql(
		f"""
		SELECT a.*, r.conversation, r.scenario, r.status AS run_status, r.model_alias,
			r.allowed_tools_json, r.agent_state_json, c.company_scope,
			c.status AS conversation_status
		FROM `{AGENT_APPROVAL_TABLE}` a
		JOIN `{RUN_TABLE}` r ON r.name = a.run_id
		JOIN `{CONVERSATION_TABLE}` c ON c.name = r.conversation
		WHERE a.name = %s AND a.requested_by = %s AND r.requested_by = %s AND c.owner = %s
		LIMIT 1
		FOR UPDATE
		""",
		(approval_id, user, user, user), as_dict=True,
	)
	if not rows:
		raise frappe.PermissionError(_("Agent 审批不存在或无权恢复。"))
	row = rows[0]
	if row.status not in {"approved", "rejected"}:
		frappe.throw(_("Agent 审批尚未形成可恢复的决定。"))
	if str(row.run_status or "") != "waiting_approval":
		frappe.throw(_("Agent Run 已被其他请求恢复或结束。"))
	if str(row.conversation_status or "") != "active":
		frappe.throw(_("归档会话中的 Agent Run 不能恢复。"))
	checkpoint = _normalize_agent_checkpoint(row.agent_state_json, run_id=row.run_id)
	call, arguments = _agent_checkpoint_pending_call(checkpoint)
	_arguments, _encoded, arguments_hash = _canonical_agent_arguments(arguments)
	if (
		str(call.get("id") or "") != row.call_id
		or str((call.get("function") or {}).get("name") or "") != row.tool_name
		or arguments_hash != row.arguments_hash
	):
		raise frappe.PermissionError(_("Agent 审批恢复参数与原审批不一致。"))
	allowed_tools = _safe_json_loads(row.allowed_tools_json, [])
	if not isinstance(allowed_tools, list) or not allowed_tools:
		frappe.throw(_("Agent Run 没有可恢复的工具授权范围。"))
	now = now_datetime()
	frappe.db.sql(
		f"""
		UPDATE `{RUN_TABLE}`
		SET status = 'running', cancellation_requested = 0, error_code = NULL, error = NULL,
			completed_at = NULL, capability_token_hash = NULL, capability_expires_at = NULL,
			modified = %s, modified_by = %s
		WHERE name = %s AND requested_by = %s AND status = 'waiting_approval'
		""",
		(now, user, row.run_id, user),
	)
	capability_token = issue_agent_capability(
		run_id=row.run_id, user=user, allowed_tools=allowed_tools,
	)
	return {
		"run_id": row.run_id, "conversation_id": row.conversation,
		"scenario": row.scenario, "company": row.company_scope,
		"model_alias": checkpoint.get("model_alias") or row.model_alias,
		"prompt_version": checkpoint.get("prompt_version"),
		"allowed_tools": allowed_tools, "capability_token": capability_token,
		"checkpoint_stage": checkpoint.get("stage"),
		"approval": _serialize_agent_approval(row),
	}


def _contains_agent_secret_key(value) -> bool:
	secret_keys = {"authorization", "api_key", "apikey", "capability_token", "cookie", "password", "service_token"}
	if isinstance(value, dict):
		return any(
			str(key).strip().lower() in secret_keys or _contains_agent_secret_key(child)
			for key, child in value.items()
		)
	if isinstance(value, list):
		return any(_contains_agent_secret_key(child) for child in value)
	return False


def record_agent_runtime_event(
	*, run_id: str, event_id: str, step_type: str, status: str,
	data: dict | None = None, checkpoint: dict | None = None,
	span_id: str | None = None, error_code: str | None = None,
	capability_token: str,
) -> dict:
	validate_agent_run_capability(run_id=run_id, capability_token=capability_token)
	allowed_types = {
		"input_guardrail", "model_decision", "tool_guardrail", "output_guardrail",
		"checkpoint", "state_transition",
	}
	if step_type not in allowed_types or status not in {"completed", "failed"}:
		frappe.throw(_("Agent 运行事件类型或状态不正确。"))
	resolved_event_id = str(event_id or "").strip()[:140]
	if not resolved_event_id:
		frappe.throw(_("Agent 运行事件编号不能为空。"))
	checkpoint = _normalize_agent_checkpoint(checkpoint, run_id=run_id)
	encoded_data = frappe.as_json(data or {}).encode("utf-8")
	if len(encoded_data) > MAX_AGENT_EVENT_BYTES or _contains_agent_secret_key(data or {}):
		frappe.throw(_("Agent 运行事件包含超限或敏感数据。"))
	now = now_datetime()
	run_rows = frappe.db.sql(
		f"""
		SELECT requested_by, status, last_step_no
		FROM `{RUN_TABLE}`
		WHERE name = %s
		LIMIT 1
		FOR UPDATE
		""",
		(run_id,), as_dict=True,
	)
	if not run_rows:
		raise frappe.PermissionError(_("Agent Run 不存在。"))
	run = run_rows[0]
	if str(run.status or "") not in {"running", "waiting_approval"}:
		raise frappe.PermissionError(_("Agent Run 已结束，不能记录运行事件。"))
	existing = frappe.db.sql(
		f"""
		SELECT name, sequence_no
		FROM `{AGENT_STEP_TABLE}`
		WHERE run_id = %s AND call_id = %s
		LIMIT 1
		""",
		(run_id, resolved_event_id), as_dict=True,
	)
	if existing:
		return {
			"event_id": resolved_event_id, "step_id": existing[0].name,
			"sequence_no": cint(existing[0].sequence_no), "replayed": True,
		}
	sequence_no = cint(run.last_step_no) + 1
	step_id = _name("AI-STEP")
	frappe.db.sql(
		f"""
		INSERT INTO `{AGENT_STEP_TABLE}`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 run_id, sequence_no, call_id, step_type, status, result_json,
			 error_code, span_id, started_at, completed_at)
		VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
		""",
		(
			step_id, now, now, run.requested_by, run.requested_by,
			run_id, sequence_no, resolved_event_id, step_type, status,
			frappe.as_json(data or {}), str(error_code or "")[:140] or None,
			str(span_id or "")[:64] or None, now, now,
		),
	)
	frappe.db.sql(
		f"""
		UPDATE `{RUN_TABLE}`
		SET last_step_no = %s, agent_state_json = COALESCE(%s, agent_state_json),
			modified = %s, modified_by = %s
		WHERE name = %s
		""",
		(
			sequence_no,
			frappe.as_json(checkpoint) if checkpoint is not None else None,
			now, run.requested_by, run_id,
		),
	)
	return {
		"event_id": resolved_event_id, "step_id": step_id,
		"sequence_no": sequence_no, "replayed": False,
	}


def get_agent_checkpoint(*, run_id: str, capability_token: str) -> dict:
	validate_agent_run_capability(run_id=run_id, capability_token=capability_token)
	rows = frappe.db.sql(
		f"""
		SELECT status, agent_state_json, last_step_no
		FROM `{RUN_TABLE}`
		WHERE name = %s
		LIMIT 1
		""",
		(run_id,), as_dict=True,
	)
	if not rows:
		raise frappe.PermissionError(_("Agent Run 不存在。"))
	return {
		"run_id": run_id,
		"status": str(rows[0].status or ""),
		"last_step_no": cint(rows[0].last_step_no),
		"checkpoint": _safe_json_loads(rows[0].agent_state_json, None),
	}


def prepare_agent_run_resume(*, run_id: str, user: str) -> dict:
	"""Reopen one owned failed Agent Run and return its durable resume context."""
	rows = frappe.db.sql(
		f"""
		SELECT r.name, r.conversation, r.requested_by, r.scenario, r.status,
			r.model_alias, r.allowed_tools_json, r.agent_state_json,
			c.company_scope, c.status AS conversation_status
		FROM `{RUN_TABLE}` r
		JOIN `{CONVERSATION_TABLE}` c ON c.name = r.conversation
		WHERE r.name = %s AND r.requested_by = %s AND c.owner = %s
		LIMIT 1
		FOR UPDATE
		""",
		(run_id, user, user),
		as_dict=True,
	)
	if not rows:
		raise frappe.PermissionError(_("AI Run 不存在或无权访问。"))
	row = rows[0]
	if str(row.conversation_status or "") != "active":
		frappe.throw(_("归档会话中的 AI Run 不能恢复。"))
	if str(row.status or "") not in {"failed", "expired"}:
		frappe.throw(_("只有失败或过期的 Agent Run 可以恢复。"))
	checkpoint = _normalize_agent_checkpoint(row.agent_state_json, run_id=run_id)
	if checkpoint is None:
		frappe.throw(_("AI Run 没有可恢复的安全检查点。"))
	if not str(checkpoint.get("prompt_version") or "").strip():
		frappe.throw(_("AI Run 检查点缺少 Prompt 版本，不能安全恢复。"))
	if not str(checkpoint.get("model_alias") or row.model_alias or "").strip():
		frappe.throw(_("AI Run 检查点缺少模型别名，不能安全恢复。"))
	allowed_tools = _safe_json_loads(row.allowed_tools_json, [])
	if not isinstance(allowed_tools, list) or not allowed_tools:
		frappe.throw(_("AI Run 没有可恢复的工具授权范围。"))
	approval = None
	if checkpoint.get("stage") == "waiting_approval":
		pending = checkpoint.get("pending_approval") or {}
		approval_rows = frappe.db.sql(
			f"SELECT * FROM `{AGENT_APPROVAL_TABLE}` WHERE run_id = %s AND call_id = %s LIMIT 1",
			(run_id, str(pending.get("call_id") or "")), as_dict=True,
		)
		if not approval_rows or approval_rows[0].status not in {"approved", "rejected"}:
			frappe.throw(_("AI Run 仍缺少可恢复的审批决定。"))
		approval = _serialize_agent_approval(approval_rows[0])
	now = now_datetime()
	frappe.db.sql(
		f"""
		UPDATE `{RUN_TABLE}`
		SET modified = %s, modified_by = %s, status = 'running',
			cancellation_requested = 0, error_code = NULL, error = NULL,
			completed_at = NULL, capability_token_hash = NULL,
			capability_expires_at = NULL
		WHERE name = %s AND requested_by = %s AND status IN ('failed', 'expired')
		""",
		(now, user, run_id, user),
	)
	capability_token = issue_agent_capability(
		run_id=run_id, user=user, allowed_tools=allowed_tools,
	)
	return {
		"run_id": run_id,
		"conversation_id": row.conversation,
		"scenario": row.scenario,
		"company": row.company_scope,
		"model_alias": checkpoint.get("model_alias") or row.model_alias,
		"prompt_version": checkpoint.get("prompt_version"),
		"allowed_tools": allowed_tools,
		"capability_token": capability_token,
		"checkpoint_stage": checkpoint.get("stage"),
		"approval": approval,
	}


def revoke_agent_capability(*, run_id: str, user: str | None = None) -> None:
	conditions = ["name = %s"]
	params: list = [run_id]
	if user:
		conditions.append("requested_by = %s")
		params.append(user)
	frappe.db.sql(
		f"""
		UPDATE `{RUN_TABLE}`
		SET capability_token_hash = NULL, capability_expires_at = NULL
		WHERE {' AND '.join(conditions)}
		""",
		tuple(params),
	)


def cancel_agent_run(*, run_id: str, user: str) -> dict:
	rows = frappe.db.sql(
		f"SELECT status FROM `{RUN_TABLE}` WHERE name = %s AND requested_by = %s LIMIT 1",
		(run_id, user), as_dict=True,
	)
	if not rows:
		raise frappe.PermissionError(_("AI Run 不存在或无权访问。"))
	status = str(rows[0].status or "")
	if status not in {"running", "waiting_approval"}:
		return {"run_id": run_id, "status": status, "cancelled": status == "cancelled"}
	now = now_datetime()
	frappe.db.sql(
		f"""
		UPDATE `{RUN_TABLE}`
		SET modified = %s, modified_by = %s, status = 'cancelled',
			cancellation_requested = 1, capability_token_hash = NULL,
			capability_expires_at = NULL, completed_at = %s,
			error_code = 'AI_RUN_CANCELLED', error = %s
		WHERE name = %s AND requested_by = %s AND status IN ('running', 'waiting_approval')
		""",
		(now, user, now, _("用户已取消 AI Run。"), run_id, user),
	)
	frappe.db.sql(
		f"""
		UPDATE `{AGENT_APPROVAL_TABLE}`
		SET status = 'expired', modified = %s, modified_by = %s, version = version + 1
		WHERE run_id = %s AND status = 'pending'
		""",
		(now, user, run_id),
	)
	return {"run_id": run_id, "status": "cancelled", "cancelled": True}


def _validate_agent_tool_step_binding(row, *, tool: str, arguments: dict) -> None:
	stored_arguments = _safe_json_loads(row.arguments_json, None)
	if not isinstance(stored_arguments, dict):
		raise frappe.PermissionError(_("Agent 工具调用缺少可验证的原始参数。"))
	_stored, _stored_encoded, stored_hash = _canonical_agent_arguments(stored_arguments)
	_current, _current_encoded, current_hash = _canonical_agent_arguments(arguments)
	if str(row.tool_name or "") != str(tool or "") or stored_hash != current_hash:
		raise frappe.PermissionError(_("Agent call_id 已绑定其他工具或参数。"))


def get_agent_tool_result(
	*, run_id: str, call_id: str, tool: str, arguments: dict,
) -> dict | None:
	if not frappe.db.table_exists("MyApp AI Agent Step"):
		return None
	rows = frappe.db.sql(
		f"""
		SELECT tool_name, arguments_json, result_json FROM `{AGENT_STEP_TABLE}`
		WHERE run_id = %s AND call_id = %s AND status = 'completed'
		LIMIT 1
		""",
		(run_id, call_id), as_dict=True,
	)
	if not rows:
		return None
	_validate_agent_tool_step_binding(rows[0], tool=tool, arguments=arguments)
	return _safe_json_loads(rows[0].result_json, None)


def start_agent_tool_step(
	*, run_id: str, user: str, call_id: str, tool: str, arguments: dict,
) -> dict:
	now = now_datetime()
	rows = frappe.db.sql(
		f"SELECT last_step_no, status FROM `{RUN_TABLE}` WHERE name = %s FOR UPDATE",
		(run_id,), as_dict=True,
	)
	if not rows:
		raise frappe.PermissionError(_("Agent Run 不存在。"))
	if str(rows[0].status or "") != "running":
		raise frappe.PermissionError(_("Agent Run 已停止，不能继续执行工具。"))
	existing = frappe.db.sql(
		f"""
			SELECT name, status, tool_name, arguments_json, result_json
		FROM `{AGENT_STEP_TABLE}`
		WHERE run_id = %s AND call_id = %s
		LIMIT 1
		""",
		(run_id, call_id),
		as_dict=True,
	)
	if existing:
		row = existing[0]
		_validate_agent_tool_step_binding(row, tool=tool, arguments=arguments)
		return {
			"status": str(row.status or "running"),
			"step_id": row.name,
			"result": _safe_json_loads(row.result_json, None) if row.status == "completed" else None,
		}
	sequence_no = cint(rows[0].last_step_no) + 1
	step_id = _name("AI-STEP")
	frappe.db.sql(
		f"""
		INSERT INTO `{AGENT_STEP_TABLE}`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 run_id, sequence_no, call_id, step_type, status, tool_name,
			 arguments_json, started_at)
		VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, 'tool', 'running', %s, %s, %s)
		""",
		(
			step_id, now, now, user, user, run_id, sequence_no, call_id,
			tool, frappe.as_json(arguments or {}), now,
		),
	)
	frappe.db.sql(
		f"UPDATE `{RUN_TABLE}` SET last_step_no = %s WHERE name = %s",
		(sequence_no, run_id),
	)
	return {"status": "claimed", "step_id": step_id, "result": None}


def complete_agent_tool_step(*, step_id: str, user: str, result: dict, latency_ms: int) -> None:
	now = now_datetime()
	frappe.db.sql(
		f"""
		UPDATE `{AGENT_STEP_TABLE}`
		SET modified = %s, modified_by = %s, status = 'completed', result_json = %s,
			error_code = %s, completed_at = %s, latency_ms = %s
		WHERE name = %s
		""",
		(
			now, user, frappe.as_json(result),
			str((result.get("error") or {}).get("code") or "")[:140] or None,
			now, max(0, cint(latency_ms)), step_id,
		),
	)


def complete_run(
	*, run_id: str, user: str, result: dict, latency_ms: int,
	first_token_ms: int | None = None, tool_calls: list[dict] | None = None,
):
	usage = result.get("usage") or {}
	now = now_datetime()
	resolved_first_token_ms = max(0, cint(first_token_ms)) if first_token_ms is not None else None
	frappe.db.sql(
		f"""
		UPDATE `{RUN_TABLE}`
		SET modified = %s, modified_by = %s, status = 'completed', model_alias = %s,
			model = %s, trace_id = %s, prompt_tokens = %s, completion_tokens = %s,
			total_tokens = %s, reasoning_tokens = %s, latency_ms = %s, first_token_ms = %s,
			tool_calls_json = %s, policy_code = %s, policy_version = %s,
			fallback_reason = %s, estimated_cost = %s, cost_currency = %s,
			completed_at = %s, error_code = NULL, error = NULL
		WHERE name = %s AND requested_by = %s AND status = 'running'
		""",
		(
			now,
			user,
			result.get("model_alias"),
			result.get("model"),
			result.get("trace_id"),
			cint(usage.get("prompt_tokens")),
			cint(usage.get("completion_tokens")),
			cint(usage.get("total_tokens")),
			cint(usage.get("reasoning_tokens")),
			max(0, cint(latency_ms)),
			resolved_first_token_ms,
			frappe.as_json(tool_calls or []),
			result.get("policy_code"),
			cint(result.get("policy_version")) or None,
			str(result.get("fallback_reason") or "")[:255] or None,
			result.get("estimated_cost") or 0,
			str(result.get("cost_currency") or "")[:10] or None,
			now,
			run_id,
			user,
		),
	)
	if frappe.db.table_exists("MyApp AI Model Usage Daily"):
		environment = os.environ.get("MYAPP_AI_ENVIRONMENT", "development").strip() or "development"
		fallback_count = 1 if result.get("fallback_reason") else 0
		frappe.db.sql(
			"""
			INSERT INTO `tabMyApp AI Model Usage Daily`
				(name, creation, modified, modified_by, owner, docstatus, idx, usage_date,
				 environment, company, scenario, policy_code, policy_version, model_alias,
				 request_count, success_count, error_count, prompt_tokens, completion_tokens,
				 total_tokens, estimated_cost, cost_currency, latency_total_ms,
				 latency_sample_count, first_token_total_ms, first_token_sample_count,
				 fallback_count)
			SELECT %s, %s, %s, %s, %s, 0, 0, DATE(%s), %s,
				COALESCE(c.company_scope, ''), r.scenario, COALESCE(%s, ''), %s, COALESCE(%s, ''),
				1, 1, 0, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s
			FROM `tabMyApp AI Run` r
			JOIN `tabMyApp AI Conversation` c ON c.name = r.conversation
			WHERE r.name = %s AND r.requested_by = %s AND r.status = 'completed'
			ON DUPLICATE KEY UPDATE
				modified = VALUES(modified), modified_by = VALUES(modified_by),
				request_count = `tabMyApp AI Model Usage Daily`.request_count + 1,
				success_count = `tabMyApp AI Model Usage Daily`.success_count + 1,
				prompt_tokens = `tabMyApp AI Model Usage Daily`.prompt_tokens + VALUES(prompt_tokens),
				completion_tokens = `tabMyApp AI Model Usage Daily`.completion_tokens + VALUES(completion_tokens),
				total_tokens = `tabMyApp AI Model Usage Daily`.total_tokens + VALUES(total_tokens),
				estimated_cost = `tabMyApp AI Model Usage Daily`.estimated_cost + VALUES(estimated_cost),
				latency_total_ms = `tabMyApp AI Model Usage Daily`.latency_total_ms + VALUES(latency_total_ms),
				latency_sample_count = `tabMyApp AI Model Usage Daily`.latency_sample_count + 1,
				first_token_total_ms = `tabMyApp AI Model Usage Daily`.first_token_total_ms + VALUES(first_token_total_ms),
				first_token_sample_count = `tabMyApp AI Model Usage Daily`.first_token_sample_count + VALUES(first_token_sample_count),
				fallback_count = `tabMyApp AI Model Usage Daily`.fallback_count + VALUES(fallback_count)
			""",
			(
				_name("AI-USAGE"), now, now, user, user, now, environment,
				result.get("policy_code"), cint(result.get("policy_version")), result.get("model_alias"),
				cint(usage.get("prompt_tokens")), cint(usage.get("completion_tokens")),
				cint(usage.get("total_tokens")), result.get("estimated_cost") or 0,
				str(result.get("cost_currency") or "")[:10] or None, max(0, cint(latency_ms)),
				resolved_first_token_ms or 0, 1 if resolved_first_token_ms is not None else 0,
				fallback_count, run_id, user,
			),
		)


def fail_run(*, run_id: str, user: str, error: Exception, latency_ms: int):
	now = now_datetime()
	error_code = str(getattr(error, "code", "") or "").strip()
	if not error_code:
		if isinstance(error, frappe.PermissionError):
			error_code = "PERMISSION_DENIED"
		elif isinstance(error, frappe.AuthenticationError):
			error_code = "AUTHENTICATION_REQUIRED"
		elif isinstance(error, frappe.ValidationError):
			error_code = "VALIDATION_ERROR"
		elif type(error).__name__ == "UpstreamServiceUnavailableError":
			error_code = "AI_SERVICE_UNAVAILABLE"
		else:
			error_code = "AI_RUN_FAILED"
	error_message = (
		str(error)
		if error_code != "AI_RUN_FAILED"
		else _("AI 运行失败，请稍后重试或联系管理员查看诊断。")
	)
	frappe.db.sql(
		f"""
		UPDATE `{RUN_TABLE}`
		SET modified = %s, modified_by = %s, status = 'failed', latency_ms = %s,
			error_code = %s, error = %s, completed_at = %s
		WHERE name = %s AND requested_by = %s AND status = 'running'
		""",
		(
			now,
			user,
			max(0, cint(latency_ms)),
			error_code,
			error_message[:2000],
			now,
			run_id,
			user,
		),
	)
	if frappe.db.table_exists("MyApp AI Model Usage Daily"):
		environment = os.environ.get("MYAPP_AI_ENVIRONMENT", "development").strip() or "development"
		frappe.db.sql(
			"""
			INSERT INTO `tabMyApp AI Model Usage Daily`
				(name, creation, modified, modified_by, owner, docstatus, idx, usage_date,
				 environment, company, scenario, policy_code, policy_version, model_alias,
				 request_count, success_count, error_count, latency_total_ms, latency_sample_count)
			SELECT %s, %s, %s, %s, %s, 0, 0, DATE(%s), %s,
				COALESCE(c.company_scope, ''), r.scenario, COALESCE(r.policy_code, ''),
				COALESCE(r.policy_version, 0), COALESCE(r.model_alias, 'unknown'),
				1, 0, 1, %s, 1
			FROM `tabMyApp AI Run` r
			JOIN `tabMyApp AI Conversation` c ON c.name = r.conversation
			WHERE r.name = %s AND r.requested_by = %s AND r.status = 'failed'
			ON DUPLICATE KEY UPDATE
				modified = VALUES(modified), modified_by = VALUES(modified_by),
				request_count = `tabMyApp AI Model Usage Daily`.request_count + 1,
				error_count = `tabMyApp AI Model Usage Daily`.error_count + 1,
				latency_total_ms = `tabMyApp AI Model Usage Daily`.latency_total_ms + VALUES(latency_total_ms),
				latency_sample_count = `tabMyApp AI Model Usage Daily`.latency_sample_count + 1
			""",
			(
				_name("AI-USAGE"), now, now, user, user, now, environment,
				max(0, cint(latency_ms)), run_id, user,
			),
		)


def submit_feedback(
	*,
	run_id: str,
	user: str,
	rating: str,
	category: str | None = None,
	comment: str | None = None,
) -> dict:
	_ensure_tables()
	environment = os.environ.get("MYAPP_AI_ENVIRONMENT", "development").strip() or "development"
	rows = frappe.db.sql(
		f"""
		SELECT r.name, r.conversation, r.status, r.trace_id, r.scenario,
			COALESCE(r.environment, %s) AS environment, COALESCE(c.company_scope, '') AS company,
			COALESCE(r.policy_code, '') AS policy_code, COALESCE(r.policy_version, 0) AS policy_version,
			COALESCE(r.model_alias, 'unknown') AS model_alias, DATE(r.completed_at) AS usage_date,
			f.rating AS previous_rating
		FROM `{RUN_TABLE}` r
		JOIN `{CONVERSATION_TABLE}` c ON c.name = r.conversation
		LEFT JOIN `{FEEDBACK_TABLE}` f ON f.run_id = r.name AND f.owner = %s
		WHERE r.name = %s AND r.requested_by = %s
		LIMIT 1
		FOR UPDATE
		""",
		(environment, user, run_id, user),
		as_dict=True,
	)
	if not rows:
		raise frappe.PermissionError(_("AI Run 不存在或无权反馈。"))
	if rows[0].status != "completed":
		frappe.throw(_("只有已完成的 AI Run 可以提交反馈。"))
	now = now_datetime()
	feedback_id = _name("AI-FEEDBACK")
	frappe.db.sql(
		f"""
		INSERT INTO `{FEEDBACK_TABLE}`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 conversation, run_id, rating, category, comment)
		VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, %s)
		ON DUPLICATE KEY UPDATE
			modified = VALUES(modified), modified_by = VALUES(modified_by),
			rating = VALUES(rating), category = VALUES(category), comment = VALUES(comment)
		""",
		(
			feedback_id,
			now,
			now,
			user,
			user,
			rows[0].conversation,
			run_id,
			rating,
			category,
			comment,
		),
	)
	if frappe.db.table_exists("MyApp AI Model Usage Daily"):
		previous_rating = str(rows[0].previous_rating or "")
		positive_delta = int(rating == "positive") - int(previous_rating == "positive")
		negative_delta = int(rating == "negative") - int(previous_rating == "negative")
		frappe.db.sql(
			"""
			INSERT INTO `tabMyApp AI Model Usage Daily`
				(name, creation, modified, modified_by, owner, docstatus, idx, usage_date,
				 environment, company, scenario, policy_code, policy_version, model_alias,
				 positive_feedback_count, negative_feedback_count)
			VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s)
			ON DUPLICATE KEY UPDATE
				modified = VALUES(modified), modified_by = VALUES(modified_by),
				positive_feedback_count = GREATEST(0, positive_feedback_count + %s),
				negative_feedback_count = GREATEST(0, negative_feedback_count + %s)
			""",
			(
				_name("AI-USAGE"), now, now, user, user, rows[0].usage_date,
				rows[0].environment, rows[0].company, rows[0].scenario, rows[0].policy_code,
				cint(rows[0].policy_version), rows[0].model_alias,
				1 if rating == "positive" else 0, 1 if rating == "negative" else 0,
				positive_delta, negative_delta,
			),
		)
	return {
		"run_id": run_id,
		"conversation": rows[0].conversation,
		"trace_id": rows[0].trace_id,
		"rating": rating,
		"category": category,
		"comment": comment,
	}


def _nearest_rank_percentile(values: list[int], percentile: float) -> int | None:
	if not values:
		return None
	ordered = sorted(max(0, cint(value)) for value in values)
	index = max(0, min(len(ordered) - 1, int((len(ordered) * percentile) + 0.999999999) - 1))
	return ordered[index]


def refresh_ai_usage_daily_metrics(*, days: int = 3) -> dict:
	if not frappe.db.table_exists("MyApp AI Model Usage Daily"):
		return {"status": "success", "data": {"updated_count": 0}}
	resolved_days = max(1, min(31, cint(days) or 3))
	date_from = add_days(now_datetime().date(), -(resolved_days - 1))
	rows = frappe.db.sql(
		f"""
		SELECT DATE(r.completed_at) AS usage_date,
			COALESCE(r.environment, 'development') AS environment,
			COALESCE(c.company_scope, '') AS company, r.scenario,
			COALESCE(r.policy_code, '') AS policy_code,
			COALESCE(r.policy_version, 0) AS policy_version,
			COALESCE(r.model_alias, 'unknown') AS model_alias,
			r.latency_ms, r.first_token_ms, f.rating
		FROM `{RUN_TABLE}` r
		JOIN `{CONVERSATION_TABLE}` c ON c.name = r.conversation
		LEFT JOIN `{FEEDBACK_TABLE}` f ON f.run_id = r.name AND f.owner = r.requested_by
		WHERE r.completed_at IS NOT NULL AND DATE(r.completed_at) >= %s
		""",
		(date_from,), as_dict=True,
	)
	groups = {}
	for row in rows:
		key = (
			row.usage_date, row.environment, row.company, row.scenario,
			row.policy_code, cint(row.policy_version), row.model_alias,
		)
		group = groups.setdefault(key, {"latencies": [], "first_tokens": [], "positive": 0, "negative": 0})
		group["latencies"].append(cint(row.latency_ms))
		if row.first_token_ms is not None:
			group["first_tokens"].append(cint(row.first_token_ms))
		group["positive"] += int(row.rating == "positive")
		group["negative"] += int(row.rating == "negative")
	for key, group in groups.items():
		frappe.db.sql(
			"""
			UPDATE `tabMyApp AI Model Usage Daily`
			SET latency_p50_ms = %s, latency_p95_ms = %s,
				first_token_p50_ms = %s, first_token_p95_ms = %s,
				positive_feedback_count = %s, negative_feedback_count = %s,
				modified = %s, modified_by = 'Administrator'
			WHERE usage_date = %s AND environment = %s AND company = %s AND scenario = %s
				AND policy_code = %s AND policy_version = %s AND model_alias = %s
			""",
			(
				_nearest_rank_percentile(group["latencies"], 0.50),
				_nearest_rank_percentile(group["latencies"], 0.95),
				_nearest_rank_percentile(group["first_tokens"], 0.50),
				_nearest_rank_percentile(group["first_tokens"], 0.95),
				group["positive"], group["negative"], now_datetime(), *key,
			),
		)
	frappe.db.commit()
	return {"status": "success", "data": {"updated_count": len(groups), "date_from": str(date_from)}}


def _serialize_draft(row, lines=None) -> dict:
	execution_result = _safe_json_loads(getattr(row, "execution_result_json", None), {})
	return {
		"name": row.name,
		"conversation": row.conversation,
		"source_run": row.source_run,
		"draft_type": row.draft_type,
		"status": row.status,
		"company": row.company,
		"title": row.title,
		"version": cint(row.version_no),
		"payload": _safe_json_loads(row.payload_json, {}),
		"validation": _safe_json_loads(row.validation_json, {}),
		"execution": {
			"request_id": getattr(row, "execution_request_id", None),
			"executed_by": getattr(row, "executed_by", None),
			"executed_at": str(getattr(row, "executed_at", None) or "") or None,
			"target_doctype": getattr(row, "target_doctype", None),
			"target_name": getattr(row, "target_name", None),
			"result": execution_result,
		} if getattr(row, "target_name", None) or execution_result else None,
		"lines": lines or [],
		"creation": str(row.creation or "") or None,
		"modified": str(row.modified or "") or None,
	}


def _refresh_conversation_citations(citations: list[dict], *, user: str) -> list[dict]:
	"""Refresh actionable draft citations while keeping read-only result snapshots."""
	refreshed = []
	for citation in citations or []:
		if not isinstance(citation, dict) or citation.get("type") != "ai_draft":
			refreshed.append(citation)
			continue
		draft_id = str(citation.get("id") or "").strip()
		if not draft_id:
			refreshed.append(citation)
			continue
		try:
			draft = get_draft(draft_id=draft_id, user=user)
		except Exception:
			# Preserve the historical citation if the draft expired or is no longer visible.
			refreshed.append(citation)
			continue
		refreshed.append({
			**citation,
			"label": draft.get("title") or citation.get("label"),
			"data": draft,
		})
	return refreshed


def create_draft(
	*,
	user: str,
	conversation_id: str,
	source_run: str,
	draft_type: str,
	company: str,
	title: str,
	payload: dict,
	validation: dict,
) -> dict:
	_get_owned_conversation(conversation_id, user)
	now = now_datetime()
	draft_id = _name("AI-DRAFT")
	frappe.db.sql(
		f"""
		INSERT INTO `{DRAFT_TABLE}`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 conversation, source_run, draft_type, status, company, title,
			 version_no, payload_json, validation_json, retention_until)
		VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, 'draft', %s, %s, 1, %s, %s, %s)
		""",
		(
			draft_id,
			now,
			now,
			user,
			user,
			conversation_id,
			source_run,
			draft_type,
			company,
			title[:255],
			frappe.as_json(payload),
			frappe.as_json(validation),
			add_days(now, _retention_days()),
		),
	)
	for index, line in enumerate(payload.get("items") or [], 1):
		frappe.db.sql(
			f"""
			INSERT INTO `{DRAFT_LINE_TABLE}`
				(name, creation, modified, modified_by, owner, docstatus, idx,
				 draft, line_no, item_query, item_code, item_name, uom, uom_display,
				 qty, rate, warehouse, conversion_factor, candidates_json, warnings_json, user_overrides_json)
			VALUES (%s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s,
				%s, %s, %s, %s, %s, %s, %s)
			""",
			(
				_name("AI-DRAFT-LINE"), now, now, user, user, index, draft_id, index,
				line.get("item_query"), line.get("item_code"), line.get("item_name"),
				line.get("uom"), line.get("uom_display"), line.get("qty") or 0,
				line.get("price"), line.get("warehouse"), line.get("conversion_factor"),
				frappe.as_json(line.get("candidates") or []),
				frappe.as_json(line.get("warnings") or []), frappe.as_json({}),
			),
		)
	_insert_draft_version(
		draft_id=draft_id, user=user, version_no=1, change_source="generated",
		payload=payload, validation=validation, now=now,
	)
	return get_draft(draft_id=draft_id, user=user)


def get_draft(*, draft_id: str, user: str) -> dict:
	rows = frappe.db.sql(
		f"""
		SELECT name, conversation, source_run, draft_type, status, company, title,
			version_no, payload_json, validation_json, execution_request_id,
			executed_by, executed_at, target_doctype, target_name,
			execution_result_json, creation, modified
		FROM `{DRAFT_TABLE}` WHERE name = %s AND owner = %s LIMIT 1
		""",
		(draft_id, user),
		as_dict=True,
	)
	if not rows:
		raise frappe.PermissionError(_("AI 草稿不存在或无权访问。"))
	return _serialize_draft(rows[0])


def list_drafts(
	*, user: str, status: str = "draft", draft_type: str | None = None,
	start: int = 0, limit: int = 20,
) -> dict:
	_ensure_tables()
	resolved_status = str(status or "draft").strip().lower()
	if resolved_status not in {"draft", "executed", "handed_off", "discarded", "all"}:
		frappe.throw(_("AI 草稿状态筛选不正确。"))
	resolved_type = str(draft_type or "").strip()
	if resolved_type and resolved_type not in {
		"sales_order", "purchase_order", "inventory_adjustment", "product_setup",
	}:
		frappe.throw(_("AI 草稿类型筛选不正确。"))
	start = max(0, cint(start))
	limit = max(1, min(MAX_DRAFT_PAGE_SIZE, cint(limit) or 20))
	conditions = ["owner = %s"]
	parameters: list = [user]
	if resolved_status != "all":
		conditions.append("status = %s")
		parameters.append(resolved_status)
	if resolved_type:
		conditions.append("draft_type = %s")
		parameters.append(resolved_type)
	where_sql = " AND ".join(conditions)
	count = frappe.db.sql(
		f"SELECT COUNT(*) AS total FROM `{DRAFT_TABLE}` WHERE {where_sql}",
		tuple(parameters), as_dict=True,
	)
	rows = frappe.db.sql(
		f"""
		SELECT name, conversation, source_run, draft_type, status, company, title,
			version_no, payload_json, validation_json, execution_request_id,
			executed_by, executed_at, target_doctype, target_name,
			execution_result_json, creation, modified
		FROM `{DRAFT_TABLE}`
		WHERE {where_sql}
		ORDER BY modified DESC, creation DESC
		LIMIT %s OFFSET %s
		""",
		(*parameters, limit, start), as_dict=True,
	)
	return {
		"items": [_serialize_draft(row) for row in rows],
		"pagination": {
			"start": start, "limit": limit,
			"total": cint(count[0].total if count else 0),
		},
	}


def mark_draft_handed_off(*, draft_id: str, user: str) -> dict:
	draft = get_draft(draft_id=draft_id, user=user)
	if draft["status"] == "draft":
		frappe.db.sql(
			f"UPDATE `{DRAFT_TABLE}` SET status = 'handed_off', modified = %s, modified_by = %s WHERE name = %s",
			(now_datetime(), user, draft_id),
		)
	return get_draft(draft_id=draft_id, user=user)


def mark_draft_executed(
	*, draft_id: str, user: str, request_id: str | None,
	target_doctype: str, target_name: str, result: dict,
) -> dict:
	draft = get_draft(draft_id=draft_id, user=user)
	if draft["status"] == "executed":
		return draft
	if draft["status"] != "draft":
		frappe.throw(_("只有 draft 状态的 AI 草稿可以执行。"))
	now = now_datetime()
	frappe.db.sql(
		f"""
		UPDATE `{DRAFT_TABLE}` SET status = 'executed', modified = %s, modified_by = %s,
			execution_request_id = %s, executed_by = %s, executed_at = %s,
			target_doctype = %s, target_name = %s, execution_result_json = %s
		WHERE name = %s AND owner = %s AND status = 'draft'
		""",
		(
			now, user, request_id, user, now, target_doctype, target_name,
			frappe.as_json(result), draft_id, user,
		),
	)
	return get_draft(draft_id=draft_id, user=user)


def _insert_draft_version(
	*, draft_id: str, user: str, version_no: int, change_source: str,
	payload: dict, validation: dict, now=None,
):
	now = now or now_datetime()
	frappe.db.sql(
		f"""
		INSERT INTO `{DRAFT_VERSION_TABLE}`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 draft, version_no, change_source, payload_json, validation_json)
		VALUES (%s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s)
		""",
		(
			_name("AI-DRAFT-VERSION"), now, now, user, user, version_no, draft_id,
			version_no, change_source[:40], frappe.as_json(payload), frappe.as_json(validation),
		),
	)


def update_draft(
	*, draft_id: str, user: str, payload: dict, validation: dict,
	expected_version: int, change_source: str = "user_edit",
) -> dict:
	_ensure_tables()
	locked_rows = frappe.db.sql(
		f"""
		SELECT status, version_no
		FROM `{DRAFT_TABLE}`
		WHERE name = %s AND owner = %s
		LIMIT 1
		FOR UPDATE
		""",
		(draft_id, user),
		as_dict=True,
	)
	if not locked_rows:
		raise frappe.PermissionError(_("AI 草稿不存在或无权访问。"))
	locked = locked_rows[0]
	if locked.status != "draft":
		frappe.throw(_("只有 draft 状态的 AI 草稿可以修改。"))
	expected_version = cint(expected_version)
	if expected_version < 1 or cint(locked.version_no) != expected_version:
		raise AiDraftVersionConflictError(_("草稿版本已变化，请重新打开最新版本后再保存。"))
	now = now_datetime()
	next_version = expected_version + 1
	frappe.db.sql(
		f"""
		UPDATE `{DRAFT_TABLE}` SET modified = %s, modified_by = %s,
			version_no = %s, payload_json = %s, validation_json = %s,
			retention_until = %s WHERE name = %s AND owner = %s
		""",
		(
			now, user, next_version, frappe.as_json(payload), frappe.as_json(validation),
			add_days(now, _retention_days()), draft_id, user,
		),
	)
	frappe.db.sql(f"DELETE FROM `{DRAFT_LINE_TABLE}` WHERE draft = %s", (draft_id,))
	for index, line in enumerate(payload.get("items") or [], 1):
		frappe.db.sql(
			f"""
			INSERT INTO `{DRAFT_LINE_TABLE}`
				(name, creation, modified, modified_by, owner, docstatus, idx,
				 draft, line_no, item_query, item_code, item_name, uom, uom_display,
				 qty, rate, warehouse, conversion_factor, candidates_json, warnings_json, user_overrides_json)
			VALUES (%s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s,
				%s, %s, %s, %s, %s, %s, %s)
			""",
			(
				_name("AI-DRAFT-LINE"), now, now, user, user, index, draft_id, index,
				line.get("item_query"), line.get("item_code"), line.get("item_name"), line.get("uom"),
				line.get("uom_display"), line.get("qty") or 0, line.get("price"), line.get("warehouse"),
				line.get("conversion_factor"), frappe.as_json(line.get("candidates") or []),
				frappe.as_json(line.get("warnings") or []), frappe.as_json({"updated_by_user": True}),
			),
		)
	_insert_draft_version(
		draft_id=draft_id, user=user, version_no=next_version, change_source=change_source,
		payload=payload, validation=validation, now=now,
	)
	return get_draft(draft_id=draft_id, user=user)


def list_draft_versions(*, draft_id: str, user: str) -> list[dict]:
	get_draft(draft_id=draft_id, user=user)
	rows = frappe.db.sql(
		f"""
		SELECT version_no, change_source, payload_json, validation_json, creation, modified_by
		FROM `{DRAFT_VERSION_TABLE}` WHERE draft = %s
		ORDER BY version_no ASC
		""",
		(draft_id,),
		as_dict=True,
	)
	return [
		{
			"version": cint(row.version_no), "change_source": row.change_source,
			"payload": _safe_json_loads(row.payload_json, {}),
			"validation": _safe_json_loads(row.validation_json, {}),
			"creation": str(row.creation or "") or None, "modified_by": row.modified_by,
		}
		for row in rows
	]


def get_draft_version(*, draft_id: str, user: str, version_no: int) -> dict:
	versions = list_draft_versions(draft_id=draft_id, user=user)
	version = next((row for row in versions if row["version"] == cint(version_no)), None)
	if not version:
		frappe.throw(_("AI 草稿版本不存在。"))
	return version


def discard_draft(*, draft_id: str, user: str) -> dict:
	draft = get_draft(draft_id=draft_id, user=user)
	if draft["status"] == "handed_off":
		frappe.throw(_("已交接的 AI 草稿不能放弃。"))
	if draft["status"] != "discarded":
		frappe.db.sql(
			f"UPDATE `{DRAFT_TABLE}` SET status = 'discarded', modified = %s, modified_by = %s WHERE name = %s",
			(now_datetime(), user, draft_id),
		)
	return get_draft(draft_id=draft_id, user=user)


def cleanup_expired_ai_conversations(batch_size: int = 200) -> dict:
	_ensure_tables()
	batch_size = max(1, min(1000, cint(batch_size) or 200))
	rows = frappe.db.sql(
		f"""
		SELECT name FROM `{CONVERSATION_TABLE}`
		WHERE retention_until IS NOT NULL AND retention_until < %s
		ORDER BY retention_until ASC
		LIMIT %s
		""",
		(now_datetime(), batch_size),
		as_dict=True,
	)
	names = [row.name for row in rows]
	if not names:
		return {"deleted": 0}
	placeholders = ", ".join(["%s"] * len(names))
	draft_rows = frappe.db.sql(
		f"SELECT name FROM `{DRAFT_TABLE}` WHERE conversation IN ({placeholders})",
		tuple(names),
		as_dict=True,
	) if frappe.db.table_exists("MyApp AI Draft") else []
	draft_names = [row.name for row in draft_rows]
	if draft_names:
		draft_placeholders = ", ".join(["%s"] * len(draft_names))
		frappe.db.sql(f"DELETE FROM `{DRAFT_LINE_TABLE}` WHERE draft IN ({draft_placeholders})", tuple(draft_names))
		frappe.db.sql(f"DELETE FROM `{DRAFT_VERSION_TABLE}` WHERE draft IN ({draft_placeholders})", tuple(draft_names))
		frappe.db.sql(f"DELETE FROM `{DRAFT_TABLE}` WHERE name IN ({draft_placeholders})", tuple(draft_names))
	frappe.db.sql(f"DELETE FROM `{MESSAGE_TABLE}` WHERE conversation IN ({placeholders})", tuple(names))
	frappe.db.sql(f"DELETE FROM `{FEEDBACK_TABLE}` WHERE conversation IN ({placeholders})", tuple(names))
	frappe.db.sql(f"DELETE FROM `{RUN_TABLE}` WHERE conversation IN ({placeholders})", tuple(names))
	frappe.db.sql(f"DELETE FROM `{CONVERSATION_TABLE}` WHERE name IN ({placeholders})", tuple(names))
	frappe.db.commit()
	return {"deleted": len(names)}
