from __future__ import annotations

import hashlib
import json
import os
import uuid

import frappe
from frappe import _
from frappe.utils import add_days, cint, now_datetime

from myapp.utils.ai_errors import AiDraftVersionConflictError


CONVERSATION_TABLE = "tabMyApp AI Conversation"
MESSAGE_TABLE = "tabMyApp AI Message"
RUN_TABLE = "tabMyApp AI Run"
FEEDBACK_TABLE = "tabMyApp AI Feedback"
DRAFT_TABLE = "tabMyApp AI Draft"
DRAFT_LINE_TABLE = "tabMyApp AI Draft Line"
DRAFT_VERSION_TABLE = "tabMyApp AI Draft Version"
DEFAULT_RETENTION_DAYS = 30
MAX_CONVERSATION_PAGE_SIZE = 50
DEFAULT_MESSAGE_PAGE_SIZE = 40
MAX_MESSAGE_PAGE_SIZE = 100
MAX_DRAFT_PAGE_SIZE = 100


def _name(prefix: str) -> str:
	return f"{prefix}-{uuid.uuid4().hex}"


def _retention_days() -> int:
	try:
		value = int(os.environ.get("MYAPP_AI_RETENTION_DAYS", DEFAULT_RETENTION_DAYS))
	except (TypeError, ValueError):
		value = DEFAULT_RETENTION_DAYS
	return max(1, min(value, 365))


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


def _serialize_conversation(row) -> dict:
	return {
		"name": row.name,
		"title": row.title or _("新会话"),
		"status": row.status,
		"company": row.company_scope,
		"message_count": cint(row.message_count),
		"last_message_at": str(row.last_message_at or "") or None,
		"creation": str(row.creation or "") or None,
		"modified": str(row.modified or "") or None,
	}


def _get_owned_conversation(conversation_id: str, user: str, *, for_update: bool = False):
	lock_sql = " FOR UPDATE" if for_update else ""
	rows = frappe.db.sql(
		f"""
		SELECT name, title, status, company_scope, message_count, last_message_at, creation, modified
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
			 status, title, company_scope, message_count, last_message_at, retention_until)
		VALUES (%s, %s, %s, %s, %s, 0, 0, 'active', %s, %s, 0, %s, %s)
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


def list_conversations(*, user: str, status: str = "active", start: int = 0, limit: int = 20) -> dict:
	_ensure_tables()
	resolved_status = (status or "active").strip().lower()
	if resolved_status not in {"active", "archived", "all"}:
		frappe.throw(_("AI 会话状态筛选不正确。"))
	start = max(0, cint(start))
	limit = max(1, min(MAX_CONVERSATION_PAGE_SIZE, cint(limit) or 20))
	status_sql = "" if resolved_status == "all" else " AND status = %s"
	params = [user]
	if resolved_status != "all":
		params.append(resolved_status)
	count_rows = frappe.db.sql(
		f"SELECT COUNT(*) AS total FROM `{CONVERSATION_TABLE}` WHERE owner = %s{status_sql}",
		tuple(params),
		as_dict=True,
	)
	rows = frappe.db.sql(
		f"""
		SELECT name, title, status, company_scope, message_count, last_message_at, creation, modified
		FROM `{CONVERSATION_TABLE}`
		WHERE owner = %s{status_sql}
		ORDER BY last_message_at DESC, creation DESC
		LIMIT %s OFFSET %s
		""",
		(*params, limit, start),
		as_dict=True,
	)
	return {
		"items": [_serialize_conversation(row) for row in rows],
		"pagination": {"start": start, "limit": limit, "total": cint(count_rows[0].total if count_rows else 0)},
	}


def get_conversation(
	*,
	conversation_id: str,
	user: str,
	before_sequence: int | None = None,
	limit: int = DEFAULT_MESSAGE_PAGE_SIZE,
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
		"messages": [
			{
				"name": row.name,
				"sequence": cint(row.sequence_no),
				"role": row.role,
				"content": row.content or "",
				"scenario": row.scenario,
				"run_id": row.run_id,
				"citations": _safe_json_loads(row.citations_json, []),
				"prompt_version": row.prompt_version,
				"creation": str(row.creation or "") or None,
				"run": {
					"status": row.run_status,
					"model_alias": row.model_alias,
					"model": row.model,
					"trace_id": row.trace_id,
					"usage": {
						"prompt_tokens": cint(row.prompt_tokens),
						"completion_tokens": cint(row.completion_tokens),
						"total_tokens": cint(row.total_tokens),
						"reasoning_tokens": cint(row.reasoning_tokens),
					},
					"latency_ms": cint(row.latency_ms),
					"first_token_ms": cint(row.first_token_ms) if row.first_token_ms is not None else None,
					"error_code": row.error_code,
					"error": row.error,
				} if row.run_id else None,
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
	_get_owned_conversation(conversation_id, user)
	rows = frappe.db.sql(
		f"""
		SELECT role, content
		FROM `{MESSAGE_TABLE}`
		WHERE conversation = %s
		ORDER BY sequence_no DESC
		LIMIT %s
		""",
		(conversation_id, max(1, min(20, cint(limit) or 20))),
		as_dict=True,
	)
	return [{"role": row.role, "content": row.content or ""} for row in reversed(rows)]


def create_run(*, conversation_id: str, user: str, scenario: str, tool_calls: list[dict] | None = None) -> str:
	_get_owned_conversation(conversation_id, user)
	now = now_datetime()
	run_id = _name("AI-RUN")
	frappe.db.sql(
		f"""
		INSERT INTO `{RUN_TABLE}`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 conversation, requested_by, scenario, environment, status, tool_calls_json, started_at)
		VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, 'running', %s, %s)
		""",
		(
			run_id, now, now, user, user, conversation_id, user, scenario,
			os.environ.get("MYAPP_AI_ENVIRONMENT", "development").strip() or "development",
			frappe.as_json(tool_calls or []), now,
		),
	)
	return run_id


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
		WHERE name = %s AND requested_by = %s
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
			WHERE r.name = %s AND r.requested_by = %s
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
		WHERE name = %s AND requested_by = %s
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
			WHERE r.name = %s AND r.requested_by = %s
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
