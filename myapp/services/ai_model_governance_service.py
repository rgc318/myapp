from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from myapp.utils.idempotency import run_idempotent


REGISTRY_TABLE = "tabMyApp AI Model Registry"
POLICY_TABLE = "tabMyApp AI Model Policy"
POLICY_VERSION_TABLE = "tabMyApp AI Model Policy Version"
USAGE_TABLE = "tabMyApp AI Model Usage Daily"
AUDIT_TABLE = "tabMyApp AI Audit Event"

VIEW_ROLES = {"System Manager", "AI Model Manager", "AI Model Approver", "AI Auditor"}
MANAGE_ROLES = {"System Manager", "AI Model Manager"}
APPROVE_ROLES = {"System Manager", "AI Model Approver"}
CAPABILITIES = {"fast_chat", "reasoning", "structured", "vision", "embedding", "rerank"}
MODEL_STATUSES = {"discovered", "validated", "active", "degraded", "disabled", "retired"}
MANAGED_MODEL_STATUSES = {"validated", "active", "degraded", "disabled", "retired"}
POLICY_SCENARIOS = {
	"general",
	"product_search",
	"order_query",
	"report_summary",
	"sales_order_draft",
	"purchase_order_draft",
	"inventory_adjustment_draft",
	"product_setup_draft",
}
BUDGET_ACTIONS = {"warn", "use_lower_cost_fallback", "reject_noncritical"}
ENVIRONMENTS = {"development", "test", "staging", "production"}
MAX_PAGE_SIZE = 100


def _name(prefix: str) -> str:
	return f"{prefix}-{uuid.uuid4().hex}"


def _current_user() -> str:
	user = str(getattr(frappe.session, "user", "") or "").strip()
	if not user or user == "Guest":
		raise frappe.PermissionError(_("请先登录。"))
	return user


def _require_roles(allowed_roles: set[str], message: str) -> str:
	user = _current_user()
	if user == "Administrator":
		return user
	if not (set(frappe.get_roles(user) or []) & allowed_roles):
		raise frappe.PermissionError(message)
	return user


def _require_viewer() -> str:
	return _require_roles(VIEW_ROLES, _("无权查看 AI 模型治理信息。"))


def _require_manager() -> str:
	return _require_roles(MANAGE_ROLES, _("无权维护 AI 模型或策略草稿。"))


def _require_approver() -> str:
	return _require_roles(APPROVE_ROLES, _("无权审批 AI 模型策略。"))


def _require_system_manager() -> str:
	return _require_roles({"System Manager"}, _("只有系统管理员可以发布或回滚 AI 模型策略。"))


def _ensure_tables() -> None:
	if not frappe.db.table_exists("MyApp AI Model Registry"):
		frappe.throw(_("AI 模型治理表尚未初始化，请先执行 bench migrate。"))


def _safe_json_loads(value, default):
	if value in (None, ""):
		return default
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return default


def _canonical_json(value) -> str:
	return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_json(value) -> str:
	return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_text(value, *, max_length: int | None = None) -> str:
	resolved = " ".join(str(value or "").split())
	return resolved[:max_length] if max_length else resolved


def _normalize_list(value, *, max_items: int = 100) -> list[str]:
	parsed = _safe_json_loads(value, value)
	if parsed in (None, ""):
		return []
	if isinstance(parsed, str):
		parsed = [part.strip() for part in parsed.split(",")]
	if not isinstance(parsed, (list, tuple, set)):
		frappe.throw(_("列表字段格式不正确。"))
	result = []
	for item in parsed:
		resolved = _normalize_text(item, max_length=140)
		if resolved and resolved not in result:
			result.append(resolved)
	return result[:max_items]


def _normalize_nonnegative_decimal(value, field_label: str) -> Decimal:
	try:
		resolved = Decimal(str(value or 0))
	except (InvalidOperation, ValueError):
		frappe.throw(_("{0}格式不正确。").format(field_label))
	if resolved < 0:
		frappe.throw(_("{0}不能小于 0。").format(field_label))
	return resolved


def _normalize_nonnegative_int(value, field_label: str, *, maximum: int = 10_000_000) -> int:
	try:
		resolved = int(value or 0)
	except (TypeError, ValueError):
		frappe.throw(_("{0}格式不正确。").format(field_label))
	if resolved < 0 or resolved > maximum:
		frappe.throw(_("{0}必须在 0 到 {1} 之间。").format(field_label, maximum))
	return resolved


def _normalize_policy_payload(payload) -> dict:
	payload = _safe_json_loads(payload, payload)
	if not isinstance(payload, dict):
		frappe.throw(_("策略载荷必须是对象。"))
	policy_code = _normalize_text(payload.get("policy_code"), max_length=140)
	policy_name = _normalize_text(payload.get("policy_name"), max_length=255)
	scenario = _normalize_text(payload.get("scenario"), max_length=80)
	capability = _normalize_text(payload.get("capability"), max_length=30)
	environment = _normalize_text(payload.get("environment") or "development", max_length=30).lower()
	primary_model_alias = _normalize_text(payload.get("primary_model_alias"), max_length=140)
	if not policy_code or not policy_name or not primary_model_alias:
		frappe.throw(_("策略编码、名称和主模型不能为空。"))
	if scenario not in POLICY_SCENARIOS:
		frappe.throw(_("不支持的 AI 策略场景。"))
	if capability not in CAPABILITIES:
		frappe.throw(_("不支持的模型能力类型。"))
	if environment not in ENVIRONMENTS:
		frappe.throw(_("不支持的运行环境。"))
	budget_action = _normalize_text(payload.get("budget_action") or "warn", max_length=40)
	if budget_action not in BUDGET_ACTIONS:
		frappe.throw(_("预算动作不正确。"))
	try:
		rollout_percentage = Decimal(str(payload.get("rollout_percentage", 100)))
	except (InvalidOperation, ValueError):
		frappe.throw(_("灰度比例格式不正确。"))
	if rollout_percentage < 0 or rollout_percentage > 100:
		frappe.throw(_("灰度比例必须在 0 到 100 之间。"))
	fallback_aliases = _normalize_list(payload.get("fallback_model_aliases"), max_items=10)
	if primary_model_alias in fallback_aliases:
		frappe.throw(_("主模型不能重复出现在降级链中。"))
	return {
		"policy_code": policy_code,
		"policy_name": policy_name,
		"scenario": scenario,
		"capability": capability,
		"company_scope": _normalize_list(payload.get("company_scope"), max_items=100),
		"role_scope": _normalize_list(payload.get("role_scope"), max_items=100),
		"environment": environment,
		"primary_model_alias": primary_model_alias,
		"fallback_model_aliases": fallback_aliases,
		"reasoning_effort": _normalize_text(payload.get("reasoning_effort"), max_length=20) or None,
		"max_completion_tokens": _normalize_nonnegative_int(payload.get("max_completion_tokens"), _("最大输出 Token")),
		"timeout_seconds": _normalize_nonnegative_int(payload.get("timeout_seconds", 60), _("超时时间"), maximum=600),
		"max_concurrency": _normalize_nonnegative_int(payload.get("max_concurrency"), _("最大并发"), maximum=10000),
		"requests_per_minute": _normalize_nonnegative_int(payload.get("requests_per_minute"), _("每分钟请求数")),
		"tokens_per_minute": _normalize_nonnegative_int(payload.get("tokens_per_minute"), _("每分钟 Token")),
		"daily_budget": str(_normalize_nonnegative_decimal(payload.get("daily_budget"), _("日预算"))),
		"monthly_budget": str(_normalize_nonnegative_decimal(payload.get("monthly_budget"), _("月预算"))),
		"budget_currency": _normalize_text(payload.get("budget_currency"), max_length=10) or None,
		"budget_action": budget_action,
		"rollout_percentage": str(rollout_percentage),
		"rollout_seed": _normalize_text(payload.get("rollout_seed"), max_length=140) or _hash_json(policy_code)[:24],
		"effective_from": payload.get("effective_from") or None,
		"effective_to": payload.get("effective_to") or None,
	}


def _serialize_registry(row) -> dict:
	return {
		"model_alias": row.model_alias,
		"capability": row.capability,
		"status": row.status,
		"provider_family": row.provider_family,
		"provider_model_display": row.provider_model_display,
		"supports_streaming": bool(cint(row.supports_streaming)),
		"supports_json_schema": bool(cint(row.supports_json_schema)),
		"supports_vision": bool(cint(row.supports_vision)),
		"embedding_dimensions": cint(row.embedding_dimensions) or None,
		"embedding_space_version": row.embedding_space_version,
		"data_region": row.data_region,
		"retention_policy": row.retention_policy,
		"sensitive_data_allowed": bool(cint(row.sensitive_data_allowed)),
		"input_cost": str(row.input_cost or 0),
		"output_cost": str(row.output_cost or 0),
		"currency": row.currency,
		"last_health_at": str(row.last_health_at or "") or None,
		"last_health_status": row.last_health_status,
		"last_error_code": row.last_error_code,
		"registry_version": cint(row.registry_version),
		"modified": str(row.modified or "") or None,
	}


def _normalize_model_metadata_payload(payload) -> dict:
	payload = _safe_json_loads(payload, payload)
	if not isinstance(payload, dict):
		frappe.throw(_("模型治理元数据必须是对象。"))
	allowed_fields = {
		"status", "data_region", "retention_policy", "sensitive_data_allowed",
		"input_cost", "output_cost", "currency",
	}
	unknown_fields = sorted(set(payload) - allowed_fields)
	if unknown_fields:
		frappe.throw(_("不允许维护模型字段：{0}。").format(", ".join(unknown_fields)))
	if not payload:
		frappe.throw(_("至少需要提交一个模型治理字段。"))
	result = {}
	if "status" in payload:
		status = _normalize_text(payload.get("status"), max_length=20)
		if status not in MANAGED_MODEL_STATUSES:
			frappe.throw(_("模型治理状态不正确。"))
		result["status"] = status
	for field, maximum in (("data_region", 80), ("retention_policy", 140)):
		if field in payload:
			result[field] = _normalize_text(payload.get(field), max_length=maximum) or None
	if "sensitive_data_allowed" in payload:
		result["sensitive_data_allowed"] = 1 if cint(payload.get("sensitive_data_allowed")) else 0
	for field, label in (("input_cost", _("输入成本")), ("output_cost", _("输出成本"))):
		if field in payload:
			result[field] = str(_normalize_nonnegative_decimal(payload.get(field), label))
	if "currency" in payload:
		currency = _normalize_text(payload.get("currency"), max_length=10).upper()
		if currency and (len(currency) < 3 or not currency.isalnum()):
			frappe.throw(_("成本币种格式不正确。"))
		result["currency"] = currency or None
	return result


def _serialize_policy(row) -> dict:
	return {
		"policy_code": row.policy_code,
		"policy_name": row.policy_name,
		"scenario": row.scenario,
		"capability": row.capability,
		"company_scope": _safe_json_loads(row.company_scope_json, []),
		"role_scope": _safe_json_loads(row.role_scope_json, []),
		"environment": row.environment,
		"primary_model_alias": row.primary_model_alias,
		"fallback_model_aliases": _safe_json_loads(row.fallback_model_aliases_json, []),
		"reasoning_effort": row.reasoning_effort,
		"max_completion_tokens": cint(row.max_completion_tokens),
		"timeout_seconds": cint(row.timeout_seconds),
		"max_concurrency": cint(row.max_concurrency),
		"requests_per_minute": cint(row.requests_per_minute),
		"tokens_per_minute": cint(row.tokens_per_minute),
		"daily_budget": str(row.daily_budget or 0),
		"monthly_budget": str(row.monthly_budget or 0),
		"budget_currency": row.budget_currency,
		"budget_action": row.budget_action,
		"rollout_percentage": str(row.rollout_percentage or 0),
		"rollout_seed": row.rollout_seed,
		"effective_from": str(row.effective_from or "") or None,
		"effective_to": str(row.effective_to or "") or None,
		"status": row.status,
		"current_version": cint(row.current_version),
		"published_version": cint(row.published_version) or None,
		"last_validated_at": str(row.last_validated_at or "") or None,
		"validation": _safe_json_loads(row.last_validation_json, None),
		"approved_by": row.approved_by,
		"approved_at": str(row.approved_at or "") or None,
		"published_at": str(row.published_at or "") or None,
		"owner": row.owner,
		"modified": str(row.modified or "") or None,
	}


def _serialize_policy_version(row) -> dict:
	return {
		"policy_code": row.policy_code,
		"version": cint(row.version_no),
		"status": row.status,
		"snapshot": _safe_json_loads(row.snapshot_json, {}),
		"content_hash": row.content_hash,
		"evaluation": _safe_json_loads(row.evaluation_report_json, None),
		"validation": _safe_json_loads(row.validation_json, None),
		"created_by": row.created_by,
		"approved_by": row.approved_by,
		"approved_at": str(row.approved_at or "") or None,
		"published_by": row.published_by,
		"published_at": str(row.published_at or "") or None,
		"rollback_from_version": cint(row.rollback_from_version) or None,
		"change_reason": row.change_reason,
		"creation": str(row.creation or "") or None,
	}


def _get_policy(policy_code: str, *, for_update: bool = False):
	lock_sql = " FOR UPDATE" if for_update else ""
	rows = frappe.db.sql(
		f"SELECT * FROM `{POLICY_TABLE}` WHERE policy_code = %s LIMIT 1{lock_sql}",
		(_normalize_text(policy_code, max_length=140),),
		as_dict=True,
	)
	if not rows:
		frappe.throw(_("AI 模型策略不存在。"))
	return rows[0]


def _get_policy_version(policy_code: str, version_no: int, *, for_update: bool = False):
	lock_sql = " FOR UPDATE" if for_update else ""
	rows = frappe.db.sql(
		f"SELECT * FROM `{POLICY_VERSION_TABLE}` WHERE policy_code = %s AND version_no = %s LIMIT 1{lock_sql}",
		(policy_code, cint(version_no)),
		as_dict=True,
	)
	if not rows:
		frappe.throw(_("AI 模型策略版本不存在。"))
	return rows[0]


def _record_audit(*, actor: str, action: str, object_type: str, object_name: str, parameters, result, reason: str | None = None, priority: str = "normal") -> None:
	now = now_datetime()
	frappe.db.sql(
		f"""
		INSERT INTO `{AUDIT_TABLE}`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 actor, action, object_type, object_name, reason, parameter_hash,
			 result_hash, metadata_json, priority)
		VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s)
		""",
		(
			_name("AI-AUDIT"), now, now, actor, actor, actor, action, object_type, object_name,
			_normalize_text(reason, max_length=1000) or None, _hash_json(parameters), _hash_json(result),
			frappe.as_json({"parameters": parameters, "result": result}), priority,
		),
	)


def _orchestrator_settings() -> tuple[str, str]:
	base_url = os.environ.get("MYAPP_AI_ORCHESTRATOR_URL", "http://ai-orchestrator:4010").strip().rstrip("/")
	service_token = os.environ.get("MYAPP_AI_SERVICE_TOKEN", "").strip()
	if not service_token:
		frappe.throw(_("AI 服务令牌尚未配置。"))
	return base_url, service_token


def _call_orchestrator(path: str, *, payload: dict | None = None, method: str = "GET", timeout: int = 30) -> dict:
	base_url, service_token = _orchestrator_settings()
	request = urllib.request.Request(
		f"{base_url}{path}",
		data=_canonical_json(payload).encode("utf-8") if payload is not None else None,
		headers={
			"Authorization": f"Bearer {service_token}",
			"Content-Type": "application/json",
			"Accept": "application/json",
		},
		method=method,
	)
	try:
		with urllib.request.urlopen(request, timeout=timeout) as response:
			result = json.loads(response.read().decode("utf-8") or "{}")
	except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
		frappe.log_error(frappe.get_traceback(), _("AI 模型治理 Orchestrator 调用失败"))
		frappe.throw(_("AI 模型治理服务暂时不可用。"))
	if not isinstance(result, dict):
		frappe.throw(_("AI 模型治理服务返回了无效响应。"))
	return result


def get_ai_model_governance_overview_v1() -> dict:
	_require_viewer()
	_ensure_tables()
	registry_counts = frappe.db.sql(
		f"SELECT status, COUNT(*) AS count FROM `{REGISTRY_TABLE}` GROUP BY status", as_dict=True,
	)
	policy_counts = frappe.db.sql(
		f"SELECT status, COUNT(*) AS count FROM `{POLICY_TABLE}` GROUP BY status", as_dict=True,
	)
	recent_audits = frappe.db.sql(
		f"""
		SELECT actor, action, object_type, object_name, reason, priority, creation
		FROM `{AUDIT_TABLE}` ORDER BY creation DESC LIMIT 20
		""",
		as_dict=True,
	)
	data_task_counts = {}
	if frappe.db.table_exists("MyApp AI Data Task"):
		data_task_counts = {
			row.status: cint(row.count)
			for row in frappe.db.sql(
				"SELECT status, COUNT(*) AS count FROM `tabMyApp AI Data Task` GROUP BY status",
				as_dict=True,
			)
		}
	vector_counts = {}
	if frappe.db.table_exists("MyApp AI Product Vector State"):
		vector_counts = {
			row.status: cint(row.count)
			for row in frappe.db.sql(
				"SELECT status, COUNT(*) AS count FROM `tabMyApp AI Product Vector State` GROUP BY status",
				as_dict=True,
			)
		}
	usage_rows = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(request_count), 0) AS request_count,
			COALESCE(SUM(success_count), 0) AS success_count,
			COALESCE(SUM(error_count), 0) AS error_count,
			COALESCE(SUM(total_tokens), 0) AS total_tokens,
			COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
			MAX(cost_currency) AS cost_currency,
			MAX(latency_p95_ms) AS latency_p95_ms,
			MAX(first_token_p95_ms) AS first_token_p95_ms
		FROM `{USAGE_TABLE}`
		WHERE usage_date >= DATE_SUB(CURDATE(), INTERVAL 6 DAY)
		""",
		as_dict=True,
	)
	usage_7d = dict(usage_rows[0]) if usage_rows else {}
	try:
		runtime_result = _call_orchestrator("/health", timeout=5)
		runtime = {
			"reachable": True,
			"status": runtime_result.get("status"),
			"model_alias": runtime_result.get("model_alias"),
			"embedding_model": runtime_result.get("embedding_model"),
			"vector_collection": runtime_result.get("vector_collection"),
			"vector_search_configured": bool(runtime_result.get("vector_search_configured")),
			"runtime_governance_configured": bool(runtime_result.get("runtime_governance_configured")),
			"langfuse_configured": bool(runtime_result.get("langfuse_configured")),
			"prompt_versions": runtime_result.get("prompt_versions") or {},
		}
	except Exception as error:
		runtime = {"reachable": False, "error": type(error).__name__}
	return {
		"status": "success",
		"data": {
			"registry_counts": {row.status: cint(row.count) for row in registry_counts},
			"policy_counts": {row.status: cint(row.count) for row in policy_counts},
			"data_task_counts": data_task_counts,
			"vector_counts": vector_counts,
			"usage_7d": usage_7d,
			"runtime": runtime,
			"recent_audits": [dict(row) for row in recent_audits],
		},
	}


def list_ai_audit_events_v1(
	*, search: str | None = None, action: str | None = None,
	object_type: str | None = None, priority: str | None = None,
	date_from: str | None = None, date_to: str | None = None,
	start: int = 0, limit: int = 20,
) -> dict:
	_require_viewer()
	_ensure_tables()
	start = max(0, cint(start))
	limit = max(1, min(100, cint(limit) or 20))
	conditions = []
	parameters: list = []
	resolved_search = _normalize_text(search, max_length=140)
	if resolved_search:
		conditions.append("(actor LIKE %s OR object_name LIKE %s OR reason LIKE %s)")
		pattern = f"%{resolved_search}%"
		parameters.extend((pattern, pattern, pattern))
	for column, value, max_length in (
		("action", action, 80),
		("object_type", object_type, 80),
		("priority", priority, 20),
	):
		resolved = _normalize_text(value, max_length=max_length)
		if resolved:
			conditions.append(f"{column} = %s")
			parameters.append(resolved)
	if date_from:
		conditions.append("creation >= %s")
		parameters.append(date_from)
	if date_to:
		conditions.append("creation < DATE_ADD(%s, INTERVAL 1 DAY)")
		parameters.append(date_to)
	where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
	count = frappe.db.sql(
		f"SELECT COUNT(*) AS total FROM `{AUDIT_TABLE}` {where_sql}",
		tuple(parameters), as_dict=True,
	)
	rows = frappe.db.sql(
		f"""
		SELECT name, actor, action, object_type, object_name, reason, priority,
			parameter_hash, result_hash, metadata_json, creation
		FROM `{AUDIT_TABLE}` {where_sql}
		ORDER BY creation DESC LIMIT %s OFFSET %s
		""",
		(*parameters, limit, start), as_dict=True,
	)
	return {
		"status": "success",
		"data": {
			"items": [
				{
					"name": row.name, "actor": row.actor, "action": row.action,
					"object_type": row.object_type, "object_name": row.object_name,
					"reason": row.reason, "priority": row.priority,
					"parameter_hash": row.parameter_hash, "result_hash": row.result_hash,
					"metadata": _safe_json_loads(row.metadata_json, {}),
					"creation": str(row.creation or "") or None,
				}
				for row in rows
			],
			"pagination": {
				"start": start, "limit": limit,
				"total": cint(count[0].total if count else 0),
			},
		},
	}


def sync_ai_model_registry_v1(*, request_id: str | None = None) -> dict:
	actor = _require_manager()
	_ensure_tables()

	def _sync():
		result = _call_orchestrator("/internal/v1/governance/models")
		models = result.get("models")
		if not isinstance(models, list):
			frappe.throw(_("Orchestrator 未返回有效模型列表。"))
		now = now_datetime()
		seen_aliases = []
		for source in models:
			if not isinstance(source, dict):
				continue
			model_alias = _normalize_text(source.get("model_alias"), max_length=140)
			capability = _normalize_text(source.get("capability"), max_length=30)
			status = _normalize_text(source.get("status") or "discovered", max_length=20)
			if not model_alias or capability not in CAPABILITIES or status not in MODEL_STATUSES:
				continue
			seen_aliases.append(model_alias)
			source_hash = _hash_json(source)
			frappe.db.sql(
				f"""
				INSERT INTO `{REGISTRY_TABLE}`
					(name, creation, modified, modified_by, owner, docstatus, idx, model_alias,
					 capability, status, provider_family, provider_model_display, supports_streaming,
					 supports_json_schema, supports_vision, embedding_dimensions, embedding_space_version,
					 data_region, retention_policy, sensitive_data_allowed, input_cost, output_cost,
					 currency, last_health_at, last_health_status, last_error_code, registry_version,
					 source_hash, source_json)
				VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, %s,
					%s, %s, %s, %s, %s, %s, %s,
					%s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
				ON DUPLICATE KEY UPDATE
					modified = VALUES(modified), modified_by = VALUES(modified_by), capability = VALUES(capability),
					status = CASE
						WHEN status IN ('disabled', 'retired') THEN status
						WHEN status = 'validated' AND VALUES(status) = 'active' THEN status
						ELSE VALUES(status)
					END,
					provider_family = VALUES(provider_family),
					provider_model_display = VALUES(provider_model_display), supports_streaming = VALUES(supports_streaming),
					supports_json_schema = VALUES(supports_json_schema), supports_vision = VALUES(supports_vision),
					embedding_dimensions = VALUES(embedding_dimensions), embedding_space_version = VALUES(embedding_space_version),
					last_health_at = VALUES(last_health_at),
					last_health_status = VALUES(last_health_status), last_error_code = VALUES(last_error_code),
					registry_version = IF(source_hash = VALUES(source_hash), registry_version, registry_version + 1),
					source_hash = VALUES(source_hash), source_json = VALUES(source_json)
				""",
				(
					_name("AI-MODEL"), now, now, actor, actor, model_alias, capability, status,
					_normalize_text(source.get("provider_family"), max_length=80) or None,
					_normalize_text(source.get("provider_model_display"), max_length=255) or None,
					cint(source.get("supports_streaming")), cint(source.get("supports_json_schema")),
					cint(source.get("supports_vision")), cint(source.get("embedding_dimensions")) or None,
					_normalize_text(source.get("embedding_space_version"), max_length=140) or None,
					_normalize_text(source.get("data_region"), max_length=80) or None,
					_normalize_text(source.get("retention_policy"), max_length=140) or None,
					cint(source.get("sensitive_data_allowed")),
					_normalize_nonnegative_decimal(source.get("input_cost"), _("输入成本")),
					_normalize_nonnegative_decimal(source.get("output_cost"), _("输出成本")),
					_normalize_text(source.get("currency"), max_length=10) or None,
					now, _normalize_text(source.get("last_health_status") or status, max_length=20),
					_normalize_text(source.get("last_error_code"), max_length=140) or None,
					source_hash, frappe.as_json(source),
				),
			)
		missing_count = 0
		if seen_aliases:
			placeholders = ", ".join(["%s"] * len(seen_aliases))
			missing_count = frappe.db.sql(
				f"""
				SELECT COUNT(*) FROM `{REGISTRY_TABLE}`
				WHERE provider_family = 'litellm'
					AND model_alias NOT IN ({placeholders})
					AND status NOT IN ('disabled', 'retired')
				""",
				tuple(seen_aliases),
			)[0][0]
			frappe.db.sql(
				f"""
				UPDATE `{REGISTRY_TABLE}`
				SET status = 'degraded', last_health_at = %s,
					last_health_status = 'missing', last_error_code = 'MODEL_ALIAS_NOT_FOUND',
					modified = %s, modified_by = %s
				WHERE provider_family = 'litellm'
					AND model_alias NOT IN ({placeholders})
					AND status NOT IN ('disabled', 'retired')
				""",
				(now, now, actor, *seen_aliases),
			)
		response = {
			"synced_count": len(seen_aliases),
			"missing_count": cint(missing_count),
			"model_aliases": seen_aliases,
		}
		_record_audit(actor=actor, action="sync_model_registry", object_type="model_registry", object_name="all", parameters={}, result=response)
		return {"status": "success", "message": _("AI 模型注册表已同步。"), "data": response}

	return run_idempotent("sync_ai_model_registry_v1", request_id, _sync, request_payload={})


def list_ai_models_v1(
	*, search: str | None = None, capability: str | None = None, status: str | None = None,
	start: int = 0, limit: int = 20,
) -> dict:
	_require_viewer()
	_ensure_tables()
	start = max(0, cint(start))
	limit = max(1, min(MAX_PAGE_SIZE, cint(limit) or 20))
	conditions = []
	params = []
	resolved_search = _normalize_text(search, max_length=140)
	if resolved_search:
		conditions.append("(model_alias LIKE %s OR provider_model_display LIKE %s OR provider_family LIKE %s)")
		like = f"%{resolved_search}%"
		params.extend([like, like, like])
	resolved_capability = _normalize_text(capability, max_length=30)
	if resolved_capability:
		if resolved_capability not in CAPABILITIES:
			frappe.throw(_("不支持的模型能力类型。"))
		conditions.append("capability = %s")
		params.append(resolved_capability)
	resolved_status = _normalize_text(status, max_length=20)
	if resolved_status:
		if resolved_status not in MODEL_STATUSES:
			frappe.throw(_("模型状态不正确。"))
		conditions.append("status = %s")
		params.append(resolved_status)
	where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
	total = frappe.db.sql(f"SELECT COUNT(*) FROM `{REGISTRY_TABLE}` {where_sql}", tuple(params))[0][0]
	rows = frappe.db.sql(
		f"SELECT * FROM `{REGISTRY_TABLE}` {where_sql} ORDER BY modified DESC, model_alias LIMIT %s OFFSET %s",
		(*params, limit, start), as_dict=True,
	)
	return {
		"status": "success",
		"data": {
			"items": [_serialize_registry(row) for row in rows],
			"pagination": {"start": start, "limit": limit, "total": cint(total)},
		},
	}


def list_ai_selectable_models_v1() -> dict:
	_current_user()
	_ensure_tables()
	rows = frappe.db.sql(
		f"""
		SELECT model_alias, capability, provider_model_display, supports_streaming,
			supports_json_schema, status
		FROM `{REGISTRY_TABLE}`
		WHERE status IN ('active', 'validated')
			AND capability IN ('fast_chat', 'reasoning', 'structured')
		ORDER BY model_alias
		""",
		as_dict=True,
	)
	return {
		"status": "success",
		"data": {
			"items": [
				{
					"model_alias": row.model_alias,
					"capability": row.capability,
					"display_name": row.provider_model_display or row.model_alias,
					"supports_streaming": bool(cint(row.supports_streaming)),
					"supports_json_schema": bool(cint(row.supports_json_schema)),
					"status": row.status,
				}
				for row in rows
			],
		},
	}


def resolve_ai_selected_model_alias(model_alias: str | None) -> str | None:
	resolved = _normalize_text(model_alias, max_length=140)
	if not resolved:
		return None
	_current_user()
	_ensure_tables()
	row = frappe.db.sql(
		f"""
		SELECT model_alias FROM `{REGISTRY_TABLE}`
		WHERE model_alias = %s
			AND status IN ('active', 'validated')
			AND capability IN ('fast_chat', 'reasoning', 'structured')
		LIMIT 1
		""",
		(resolved,),
		as_dict=True,
	)
	if not row:
		frappe.throw(_("所选 AI 模型不可用，请刷新模型列表后重试。"))
	return str(row[0].model_alias)


def update_ai_model_registry_v1(
	*, model_alias: str, payload, reason: str, request_id: str | None = None,
) -> dict:
	actor = _require_manager()
	_ensure_tables()
	resolved_alias = _normalize_text(model_alias, max_length=140)
	resolved_reason = _normalize_text(reason, max_length=1000)
	if not resolved_alias:
		frappe.throw(_("模型别名不能为空。"))
	if not resolved_reason:
		frappe.throw(_("维护模型治理元数据必须填写原因。"))
	normalized = _normalize_model_metadata_payload(payload)

	def _update():
		rows = frappe.db.sql(
			f"SELECT * FROM `{REGISTRY_TABLE}` WHERE model_alias = %s LIMIT 1 FOR UPDATE",
			(resolved_alias,), as_dict=True,
		)
		if not rows:
			frappe.throw(_("AI 模型尚未注册。"))
		row = rows[0]
		before = _serialize_registry(row)
		after = dict(before)
		after.update(normalized)
		input_cost = Decimal(str(after.get("input_cost") or 0))
		output_cost = Decimal(str(after.get("output_cost") or 0))
		if (input_cost or output_cost) and not after.get("currency"):
			frappe.throw(_("登记模型成本时必须指定成本币种。"))
		if after.get("status") in {"active", "validated"}:
			if not after.get("data_region") or not after.get("retention_policy"):
				frappe.throw(_("启用或验证模型前必须登记数据区域和留存策略。"))
		active_policies = frappe.db.sql(
			f"""
			SELECT policy_code FROM `{POLICY_TABLE}`
			WHERE status = 'active' AND (
				primary_model_alias = %s OR JSON_CONTAINS(COALESCE(fallback_model_aliases_json, '[]'), %s)
			)
			ORDER BY policy_code
			""",
			(resolved_alias, json.dumps(resolved_alias)), as_dict=True,
		)
		now = now_datetime()
		frappe.db.sql(
			f"""
			UPDATE `{REGISTRY_TABLE}`
			SET status = %s, data_region = %s, retention_policy = %s,
				sensitive_data_allowed = %s, input_cost = %s, output_cost = %s,
				currency = %s, registry_version = registry_version + 1,
				modified = %s, modified_by = %s
			WHERE model_alias = %s
			""",
			(
				after["status"], after.get("data_region"), after.get("retention_policy"),
				cint(after.get("sensitive_data_allowed")), input_cost, output_cost,
				after.get("currency"), now, actor, resolved_alias,
			),
		)
		after["registry_version"] = cint(before.get("registry_version")) + 1
		response = {
			"model": after,
			"affected_active_policies": [policy.policy_code for policy in active_policies],
		}
		_record_audit(
			actor=actor, action="update_model_registry", object_type="model_registry",
			object_name=resolved_alias, parameters={"before": before, "changes": normalized},
			result=response, reason=resolved_reason, priority="critical",
		)
		return {"status": "success", "message": _("AI 模型治理元数据已更新。"), "data": response}

	return run_idempotent(
		"update_ai_model_registry_v1", request_id, _update,
		request_payload={"model_alias": resolved_alias, "payload": normalized, "reason": resolved_reason},
	)


def list_ai_model_policies_v1(*, search: str | None = None, status: str | None = None, start: int = 0, limit: int = 20) -> dict:
	_require_viewer()
	_ensure_tables()
	start = max(0, cint(start))
	limit = max(1, min(MAX_PAGE_SIZE, cint(limit) or 20))
	conditions = []
	params = []
	resolved_search = _normalize_text(search, max_length=140)
	if resolved_search:
		conditions.append("(policy_code LIKE %s OR policy_name LIKE %s OR scenario LIKE %s)")
		like = f"%{resolved_search}%"
		params.extend([like, like, like])
	resolved_status = _normalize_text(status, max_length=30)
	if resolved_status:
		conditions.append("status = %s")
		params.append(resolved_status)
	where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
	total = frappe.db.sql(f"SELECT COUNT(*) FROM `{POLICY_TABLE}` {where_sql}", tuple(params))[0][0]
	rows = frappe.db.sql(
		f"SELECT * FROM `{POLICY_TABLE}` {where_sql} ORDER BY modified DESC LIMIT %s OFFSET %s",
		(*params, limit, start),
		as_dict=True,
	)
	return {
		"status": "success",
		"data": {"items": [_serialize_policy(row) for row in rows], "pagination": {"start": start, "limit": limit, "total": cint(total)}},
	}


def get_ai_model_policy_v1(*, policy_code: str) -> dict:
	_require_viewer()
	_ensure_tables()
	policy = _get_policy(policy_code)
	versions = frappe.db.sql(
		f"SELECT * FROM `{POLICY_VERSION_TABLE}` WHERE policy_code = %s ORDER BY version_no DESC",
		(policy.policy_code,), as_dict=True,
	)
	return {
		"status": "success",
		"data": {
			"policy": _serialize_policy(policy),
			"versions": [_serialize_policy_version(row) for row in versions],
		},
	}


def save_ai_model_policy_draft_v1(*, payload, reason: str, request_id: str | None = None) -> dict:
	actor = _require_manager()
	_ensure_tables()
	normalized = _normalize_policy_payload(payload)
	resolved_reason = _normalize_text(reason, max_length=1000)
	if not resolved_reason:
		frappe.throw(_("保存策略草稿必须填写原因。"))

	def _save():
		existing_rows = frappe.db.sql(
			f"SELECT * FROM `{POLICY_TABLE}` WHERE policy_code = %s LIMIT 1 FOR UPDATE",
			(normalized["policy_code"],), as_dict=True,
		)
		existing = existing_rows[0] if existing_rows else None
		version_no = cint(existing.current_version) + 1 if existing else 1
		now = now_datetime()
		policy_name = _name("AI-POLICY") if not existing else existing.name
		frappe.db.sql(
			f"""
			INSERT INTO `{POLICY_TABLE}`
				(name, creation, modified, modified_by, owner, docstatus, idx, policy_code, policy_name,
				 scenario, capability, company_scope_json, role_scope_json, environment, primary_model_alias,
				 fallback_model_aliases_json, reasoning_effort, max_completion_tokens, timeout_seconds,
				 max_concurrency, requests_per_minute, tokens_per_minute, daily_budget, monthly_budget,
				 budget_currency, budget_action, rollout_percentage, rollout_seed, effective_from,
				 effective_to, status, current_version, published_version)
			VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s,
				%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s)
			ON DUPLICATE KEY UPDATE
				modified = VALUES(modified), modified_by = VALUES(modified_by), policy_name = VALUES(policy_name),
				scenario = VALUES(scenario), capability = VALUES(capability), company_scope_json = VALUES(company_scope_json),
				role_scope_json = VALUES(role_scope_json), environment = VALUES(environment),
				primary_model_alias = VALUES(primary_model_alias), fallback_model_aliases_json = VALUES(fallback_model_aliases_json),
				reasoning_effort = VALUES(reasoning_effort), max_completion_tokens = VALUES(max_completion_tokens),
				timeout_seconds = VALUES(timeout_seconds), max_concurrency = VALUES(max_concurrency),
				requests_per_minute = VALUES(requests_per_minute), tokens_per_minute = VALUES(tokens_per_minute),
				daily_budget = VALUES(daily_budget), monthly_budget = VALUES(monthly_budget),
				budget_currency = VALUES(budget_currency), budget_action = VALUES(budget_action),
				rollout_percentage = VALUES(rollout_percentage), rollout_seed = VALUES(rollout_seed),
				effective_from = VALUES(effective_from), effective_to = VALUES(effective_to), status = 'draft',
				current_version = VALUES(current_version), approved_by = NULL, approved_at = NULL
			""",
			(
				policy_name, now, now, actor, actor, normalized["policy_code"], normalized["policy_name"],
				normalized["scenario"], normalized["capability"], frappe.as_json(normalized["company_scope"]),
				frappe.as_json(normalized["role_scope"]), normalized["environment"], normalized["primary_model_alias"],
				frappe.as_json(normalized["fallback_model_aliases"]), normalized["reasoning_effort"],
				normalized["max_completion_tokens"], normalized["timeout_seconds"], normalized["max_concurrency"],
				normalized["requests_per_minute"], normalized["tokens_per_minute"], normalized["daily_budget"],
				normalized["monthly_budget"], normalized["budget_currency"], normalized["budget_action"],
				normalized["rollout_percentage"], normalized["rollout_seed"], normalized["effective_from"],
				normalized["effective_to"], version_no, cint(existing.published_version) or None if existing else None,
			),
		)
		content_hash = _hash_json(normalized)
		frappe.db.sql(
			f"""
			INSERT INTO `{POLICY_VERSION_TABLE}`
				(name, creation, modified, modified_by, owner, docstatus, idx, policy_code, version_no,
				 status, snapshot_json, content_hash, created_by, change_reason)
			VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, 'draft', %s, %s, %s, %s)
			""",
			(_name("AI-POLICY-VERSION"), now, now, actor, actor, normalized["policy_code"], version_no,
			 frappe.as_json(normalized), content_hash, actor, resolved_reason),
		)
		response = {"policy_code": normalized["policy_code"], "version": version_no, "status": "draft", "content_hash": content_hash}
		_record_audit(actor=actor, action="save_policy_draft", object_type="model_policy", object_name=normalized["policy_code"], parameters=normalized, result=response, reason=resolved_reason)
		return {"status": "success", "message": _("AI 模型策略草稿已保存。"), "data": response}

	return run_idempotent(
		"save_ai_model_policy_draft_v1", request_id, _save,
		request_payload={"payload": normalized, "reason": resolved_reason},
	)


def _validate_registry_models(snapshot: dict) -> list[str]:
	aliases = [snapshot["primary_model_alias"], *snapshot.get("fallback_model_aliases", [])]
	placeholders = ", ".join(["%s"] * len(aliases))
	rows = frappe.db.sql(
		f"SELECT model_alias, capability, status, supports_json_schema, data_region, retention_policy FROM `{REGISTRY_TABLE}` WHERE model_alias IN ({placeholders})",
		tuple(aliases), as_dict=True,
	)
	by_alias = {row.model_alias: row for row in rows}
	errors = []
	for alias in aliases:
		row = by_alias.get(alias)
		if not row:
			errors.append(_("模型 {0} 尚未注册。").format(alias))
			continue
		if row.capability != snapshot["capability"]:
			errors.append(_("模型 {0} 的能力与策略不匹配。").format(alias))
		if row.status not in {"validated", "active", "degraded"}:
			errors.append(_("模型 {0} 尚未通过健康验证。").format(alias))
		if not str(row.data_region or "").strip():
			errors.append(_("模型 {0} 尚未完成数据区域复核。").format(alias))
		if not str(row.retention_policy or "").strip():
			errors.append(_("模型 {0} 尚未登记数据留存策略。").format(alias))
		if snapshot["capability"] == "structured" and not cint(row.supports_json_schema):
			errors.append(_("结构化模型 {0} 不支持 JSON Schema。").format(alias))
	return errors


def _parse_effective_datetime(value, *, end: bool = False):
	if not value:
		return datetime.max if end else datetime.min
	try:
		return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
	except ValueError:
		return None


def _effective_ranges_overlap(left: dict, right: dict) -> bool:
	left_start = _parse_effective_datetime(left.get("effective_from"))
	left_end = _parse_effective_datetime(left.get("effective_to"), end=True)
	right_start = _parse_effective_datetime(right.get("effective_from"))
	right_end = _parse_effective_datetime(right.get("effective_to"), end=True)
	if None in {left_start, left_end, right_start, right_end}:
		return True
	return left_start <= right_end and right_start <= left_end


def _scope_priority(snapshot: dict) -> int:
	companies = set(snapshot.get("company_scope") or [])
	roles = set(snapshot.get("role_scope") or [])
	if companies and roles:
		return 4
	if companies:
		return 3
	if roles:
		return 0
	return 2


def _scopes_overlap(left: dict, right: dict) -> bool:
	priority = _scope_priority(left)
	if not priority or priority != _scope_priority(right):
		return False
	left_companies = set(left.get("company_scope") or [])
	right_companies = set(right.get("company_scope") or [])
	if priority in {3, 4} and not (left_companies & right_companies):
		return False
	if priority == 4:
		return bool(set(left.get("role_scope") or []) & set(right.get("role_scope") or []))
	return True


def _validate_policy_conflicts(snapshot: dict, *, exclude_policy_code: str) -> list[str]:
	if snapshot.get("role_scope") and not snapshot.get("company_scope"):
		return [_('角色范围策略必须同时限定公司，不能创建全局角色策略。')]
	rows = frappe.db.sql(
		f"""
		SELECT p.policy_code, v.snapshot_json
		FROM `{POLICY_TABLE}` p
		JOIN `{POLICY_VERSION_TABLE}` v
			ON v.policy_code = p.policy_code AND v.version_no = p.published_version
		WHERE p.status = 'active' AND v.status = 'active'
			AND p.scenario = %s AND p.environment = %s AND p.policy_code != %s
		""",
		(snapshot.get("scenario"), snapshot.get("environment"), exclude_policy_code),
		as_dict=True,
	)
	errors = []
	for row in rows:
		existing = _safe_json_loads(row.snapshot_json, {})
		if _scopes_overlap(snapshot, existing) and _effective_ranges_overlap(snapshot, existing):
			errors.append(
				_("策略与已发布策略 {0} 的同优先级范围和生效期重叠。").format(row.policy_code)
			)
	return errors


def _validate_budget_and_cost(snapshot: dict) -> list[str]:
	errors = []
	daily_budget = Decimal(str(snapshot.get("daily_budget") or 0))
	monthly_budget = Decimal(str(snapshot.get("monthly_budget") or 0))
	has_budget = bool(daily_budget or monthly_budget)
	budget_currency = str(snapshot.get("budget_currency") or "").strip()
	if has_budget and not budget_currency:
		errors.append(_("配置预算时必须指定预算币种。"))
	if daily_budget and monthly_budget and monthly_budget < daily_budget:
		errors.append(_("月预算不能小于日预算。"))
	if snapshot.get("budget_action") == "use_lower_cost_fallback" and not snapshot.get("fallback_model_aliases"):
		errors.append(_("低成本降级预算动作必须配置降级模型。"))
	aliases = [snapshot.get("primary_model_alias"), *(snapshot.get("fallback_model_aliases") or [])]
	rows = frappe.db.sql(
		f"SELECT model_alias, currency, input_cost, output_cost FROM `{REGISTRY_TABLE}` WHERE model_alias IN ({', '.join(['%s'] * len(aliases))})",
		tuple(aliases),
		as_dict=True,
	) if aliases else []
	models = {str(row.model_alias): row for row in rows}
	for row in rows:
		model_currency = str(row.currency or "").strip()
		input_cost = Decimal(str(row.input_cost or 0))
		output_cost = Decimal(str(row.output_cost or 0))
		if has_budget and not model_currency:
			errors.append(_("模型 {0} 尚未登记成本币种。").format(row.model_alias))
		elif budget_currency and model_currency and model_currency != budget_currency:
			errors.append(_("模型 {0} 的成本币种与策略预算币种不一致。").format(row.model_alias))
		if has_budget and input_cost == 0 and output_cost == 0:
			errors.append(_("模型 {0} 尚未登记有效成本，不能执行预算治理。").format(row.model_alias))
	if snapshot.get("budget_action") == "use_lower_cost_fallback" and snapshot.get("fallback_model_aliases"):
		primary = models.get(str(snapshot.get("primary_model_alias") or ""))
		if primary:
			primary_input = Decimal(str(primary.input_cost or 0))
			primary_output = Decimal(str(primary.output_cost or 0))
			for alias in snapshot.get("fallback_model_aliases") or []:
				candidate = models.get(str(alias))
				if not candidate:
					continue
				candidate_input = Decimal(str(candidate.input_cost or 0))
				candidate_output = Decimal(str(candidate.output_cost or 0))
				is_strictly_lower = (
					candidate_input <= primary_input
					and candidate_output <= primary_output
					and (candidate_input < primary_input or candidate_output < primary_output)
				)
				if not is_strictly_lower:
					errors.append(
						_("低成本降级模型 {0} 的输入、输出单价必须均不高于主模型，且至少一项更低。").format(alias)
					)
	return errors


def validate_ai_model_policy_v1(*, policy_code: str, request_id: str | None = None) -> dict:
	actor = _require_manager()
	_ensure_tables()

	def _validate():
		policy = _get_policy(policy_code, for_update=True)
		version = _get_policy_version(policy.policy_code, policy.current_version, for_update=True)
		snapshot = _safe_json_loads(version.snapshot_json, {})
		errors = _validate_registry_models(snapshot)
		errors.extend(_validate_budget_and_cost(snapshot))
		errors.extend(_validate_policy_conflicts(snapshot, exclude_policy_code=policy.policy_code))
		orchestrator_result = _call_orchestrator(
			"/internal/v1/governance/validate-policy", payload={"policy": snapshot}, method="POST", timeout=120,
		)
		orchestrator_errors = orchestrator_result.get("errors") or []
		if isinstance(orchestrator_errors, list):
			errors.extend([_normalize_text(error, max_length=500) for error in orchestrator_errors if _normalize_text(error)])
		if not orchestrator_result.get("release_gate_eligible"):
			errors.append(_("当前模型/Prompt 组合没有通过完整发布评测。"))
		validation = {
			"valid": not errors,
			"errors": errors,
			"warnings": orchestrator_result.get("warnings") or [],
			"release_gate_eligible": bool(orchestrator_result.get("release_gate_eligible")),
			"evaluation": orchestrator_result.get("evaluation"),
			"validated_at": str(now_datetime()),
		}
		next_status = "review_required" if validation["valid"] else "draft"
		frappe.db.sql(
			f"UPDATE `{POLICY_TABLE}` SET status = %s, last_validated_at = %s, last_validation_json = %s, modified = %s, modified_by = %s WHERE policy_code = %s",
			(next_status, now_datetime(), frappe.as_json(validation), now_datetime(), actor, policy.policy_code),
		)
		frappe.db.sql(
			f"UPDATE `{POLICY_VERSION_TABLE}` SET status = %s, validation_json = %s, evaluation_report_json = %s, modified = %s, modified_by = %s WHERE policy_code = %s AND version_no = %s",
			(next_status, frappe.as_json(validation), frappe.as_json(orchestrator_result.get("evaluation")), now_datetime(), actor, policy.policy_code, policy.current_version),
		)
		_record_audit(actor=actor, action="validate_policy", object_type="model_policy", object_name=policy.policy_code, parameters={"version": policy.current_version}, result=validation)
		return {"status": "success", "message": _("AI 模型策略校验完成。"), "data": {"policy_code": policy.policy_code, "version": cint(policy.current_version), "status": next_status, "validation": validation}}

	return run_idempotent("validate_ai_model_policy_v1", request_id, _validate, request_payload={"policy_code": policy_code})


def approve_ai_model_policy_v1(*, policy_code: str, reason: str, request_id: str | None = None) -> dict:
	actor = _require_approver()
	_ensure_tables()
	resolved_reason = _normalize_text(reason, max_length=1000)
	if not resolved_reason:
		frappe.throw(_("审批策略必须填写原因。"))

	def _approve():
		policy = _get_policy(policy_code, for_update=True)
		version = _get_policy_version(policy.policy_code, policy.current_version, for_update=True)
		if policy.status != "review_required" or version.status != "review_required":
			frappe.throw(_("只有通过校验并等待审批的策略可以审批。"))
		if policy.environment == "production" and version.created_by == actor:
			frappe.throw(_("生产策略的起草人与审批人必须分离。"))
		now = now_datetime()
		frappe.db.sql(
			f"UPDATE `{POLICY_TABLE}` SET status = 'approved', approved_by = %s, approved_at = %s, modified = %s, modified_by = %s WHERE policy_code = %s",
			(actor, now, now, actor, policy.policy_code),
		)
		frappe.db.sql(
			f"UPDATE `{POLICY_VERSION_TABLE}` SET status = 'approved', approved_by = %s, approved_at = %s, modified = %s, modified_by = %s WHERE policy_code = %s AND version_no = %s",
			(actor, now, now, actor, policy.policy_code, policy.current_version),
		)
		response = {"policy_code": policy.policy_code, "version": cint(policy.current_version), "status": "approved", "approved_by": actor}
		_record_audit(actor=actor, action="approve_policy", object_type="model_policy", object_name=policy.policy_code, parameters={"version": policy.current_version}, result=response, reason=resolved_reason)
		return {"status": "success", "message": _("AI 模型策略已审批。"), "data": response}

	return run_idempotent("approve_ai_model_policy_v1", request_id, _approve, request_payload={"policy_code": policy_code, "reason": resolved_reason})


def publish_ai_model_policy_v1(*, policy_code: str, reason: str, request_id: str | None = None) -> dict:
	actor = _require_system_manager()
	_ensure_tables()
	resolved_reason = _normalize_text(reason, max_length=1000)
	if not resolved_reason:
		frappe.throw(_("发布策略必须填写原因。"))

	def _publish():
		policy = _get_policy(policy_code, for_update=True)
		version = _get_policy_version(policy.policy_code, policy.current_version, for_update=True)
		if policy.status != "approved" or version.status != "approved":
			frappe.throw(_("只有已审批的策略可以发布。"))
		validation = _safe_json_loads(version.validation_json, {})
		if not validation.get("valid") or not validation.get("release_gate_eligible"):
			frappe.throw(_("策略缺少有效的完整发布评测。"))
		conflict_errors = _validate_policy_conflicts(
			_safe_json_loads(version.snapshot_json, {}),
			exclude_policy_code=policy.policy_code,
		)
		if conflict_errors:
			frappe.throw("；".join(conflict_errors))
		now = now_datetime()
		if cint(policy.published_version):
			frappe.db.sql(
				f"UPDATE `{POLICY_VERSION_TABLE}` SET status = 'superseded', modified = %s, modified_by = %s WHERE policy_code = %s AND version_no = %s AND status = 'active'",
				(now, actor, policy.policy_code, policy.published_version),
			)
		frappe.db.sql(
			f"UPDATE `{POLICY_VERSION_TABLE}` SET status = 'active', published_by = %s, published_at = %s, modified = %s, modified_by = %s WHERE policy_code = %s AND version_no = %s",
			(actor, now, now, actor, policy.policy_code, policy.current_version),
		)
		frappe.db.sql(
			f"UPDATE `{POLICY_TABLE}` SET status = 'active', published_version = current_version, published_at = %s, modified = %s, modified_by = %s WHERE policy_code = %s",
			(now, now, actor, policy.policy_code),
		)
		response = {"policy_code": policy.policy_code, "version": cint(policy.current_version), "status": "active", "published_by": actor}
		_record_audit(actor=actor, action="publish_policy", object_type="model_policy", object_name=policy.policy_code, parameters={"version": policy.current_version}, result=response, reason=resolved_reason, priority="high")
		return {"status": "success", "message": _("AI 模型策略已发布。"), "data": response}

	return run_idempotent("publish_ai_model_policy_v1", request_id, _publish, request_payload={"policy_code": policy_code, "reason": resolved_reason})


def rollback_ai_model_policy_v1(*, policy_code: str, target_version: int, reason: str, request_id: str | None = None) -> dict:
	actor = _require_system_manager()
	_ensure_tables()
	resolved_reason = _normalize_text(reason, max_length=1000)
	if not resolved_reason:
		frappe.throw(_("回滚策略必须填写原因。"))

	def _rollback():
		policy = _get_policy(policy_code, for_update=True)
		target = _get_policy_version(policy.policy_code, cint(target_version), for_update=True)
		if target.status not in {"active", "superseded", "approved"}:
			frappe.throw(_("目标策略版本不允许回滚。"))
		if cint(policy.published_version) == cint(target.version_no):
			frappe.throw(_("目标版本已经是当前发布版本。"))
		now = now_datetime()
		new_version = cint(policy.current_version) + 1
		snapshot = _safe_json_loads(target.snapshot_json, {})
		frappe.db.sql(
			f"UPDATE `{POLICY_VERSION_TABLE}` SET status = 'superseded', modified = %s, modified_by = %s WHERE policy_code = %s AND version_no = %s AND status = 'active'",
			(now, actor, policy.policy_code, policy.published_version),
		)
		frappe.db.sql(
			f"""
			INSERT INTO `{POLICY_VERSION_TABLE}`
				(name, creation, modified, modified_by, owner, docstatus, idx, policy_code, version_no,
				 status, snapshot_json, content_hash, evaluation_report_json, validation_json, created_by,
				 approved_by, approved_at, published_by, published_at, rollback_from_version, change_reason)
			VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, 'active', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
			""",
			(
				_name("AI-POLICY-VERSION"), now, now, actor, actor, policy.policy_code, new_version,
				frappe.as_json(snapshot), target.content_hash, target.evaluation_report_json,
				target.validation_json, actor, actor, now, actor, now, policy.published_version, resolved_reason,
			),
		)
		frappe.db.sql(
			f"""
			UPDATE `{POLICY_TABLE}` SET
				policy_name = %s, scenario = %s, capability = %s, company_scope_json = %s,
				role_scope_json = %s, environment = %s, primary_model_alias = %s,
				fallback_model_aliases_json = %s, reasoning_effort = %s, max_completion_tokens = %s,
				timeout_seconds = %s, max_concurrency = %s, requests_per_minute = %s,
				tokens_per_minute = %s, daily_budget = %s, monthly_budget = %s,
				budget_currency = %s, budget_action = %s, rollout_percentage = %s,
				rollout_seed = %s, effective_from = %s, effective_to = %s, status = 'active',
				current_version = %s, published_version = %s, approved_by = %s, approved_at = %s,
				published_at = %s, modified = %s, modified_by = %s
			WHERE policy_code = %s
			""",
			(
				snapshot["policy_name"], snapshot["scenario"], snapshot["capability"],
				frappe.as_json(snapshot.get("company_scope", [])), frappe.as_json(snapshot.get("role_scope", [])),
				snapshot["environment"], snapshot["primary_model_alias"],
				frappe.as_json(snapshot.get("fallback_model_aliases", [])), snapshot.get("reasoning_effort"),
				snapshot.get("max_completion_tokens", 0), snapshot.get("timeout_seconds", 60),
				snapshot.get("max_concurrency", 0), snapshot.get("requests_per_minute", 0),
				snapshot.get("tokens_per_minute", 0), snapshot.get("daily_budget", 0),
				snapshot.get("monthly_budget", 0), snapshot.get("budget_currency"), snapshot.get("budget_action", "warn"),
				snapshot.get("rollout_percentage", 100), snapshot.get("rollout_seed"), snapshot.get("effective_from"),
				snapshot.get("effective_to"), new_version, new_version, actor, now, now, now, actor, policy.policy_code,
			),
		)
		response = {"policy_code": policy.policy_code, "version": new_version, "status": "active", "rolled_back_to_version": cint(target.version_no)}
		_record_audit(actor=actor, action="rollback_policy", object_type="model_policy", object_name=policy.policy_code, parameters={"target_version": cint(target.version_no)}, result=response, reason=resolved_reason, priority="critical")
		return {"status": "success", "message": _("AI 模型策略已回滚。"), "data": response}

	return run_idempotent(
		"rollback_ai_model_policy_v1", request_id, _rollback,
		request_payload={"policy_code": policy_code, "target_version": cint(target_version), "reason": resolved_reason},
	)


def get_ai_model_usage_summary_v1(
	*, date_from: str | None = None, date_to: str | None = None,
	environment: str | None = None, company: str | None = None,
) -> dict:
	_require_viewer()
	_ensure_tables()
	conditions = []
	params = []
	if date_from:
		conditions.append("usage_date >= %s")
		params.append(date_from)
	if date_to:
		conditions.append("usage_date <= %s")
		params.append(date_to)
	resolved_environment = _normalize_text(environment, max_length=30)
	if resolved_environment:
		conditions.append("environment = %s")
		params.append(resolved_environment)
	resolved_company = _normalize_text(company, max_length=140)
	if resolved_company:
		conditions.append("company = %s")
		params.append(resolved_company)
	where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
	rows = frappe.db.sql(
		f"""
		SELECT usage_date, environment, company, scenario, policy_code, policy_version, model_alias,
			SUM(request_count) AS request_count, SUM(success_count) AS success_count,
			SUM(error_count) AS error_count, SUM(total_tokens) AS total_tokens,
			SUM(estimated_cost) AS estimated_cost, MAX(cost_currency) AS cost_currency,
			SUM(fallback_count) AS fallback_count,
			SUM(latency_total_ms) AS latency_total_ms,
			SUM(latency_sample_count) AS latency_sample_count,
			MAX(latency_p50_ms) AS latency_p50_ms, MAX(latency_p95_ms) AS latency_p95_ms,
			SUM(first_token_total_ms) AS first_token_total_ms,
			SUM(first_token_sample_count) AS first_token_sample_count,
			MAX(first_token_p50_ms) AS first_token_p50_ms,
			MAX(first_token_p95_ms) AS first_token_p95_ms,
			SUM(positive_feedback_count) AS positive_feedback_count,
			SUM(negative_feedback_count) AS negative_feedback_count
		FROM `{USAGE_TABLE}` {where_sql}
		GROUP BY usage_date, environment, company, scenario, policy_code, policy_version, model_alias
		ORDER BY usage_date DESC, request_count DESC LIMIT 1000
		""",
		tuple(params), as_dict=True,
	)
	items = []
	for row in rows:
		item = dict(row)
		latency_samples = cint(item.get("latency_sample_count"))
		first_token_samples = cint(item.get("first_token_sample_count"))
		feedback_count = cint(item.get("positive_feedback_count")) + cint(item.get("negative_feedback_count"))
		item["latency_avg_ms"] = (
			float(item.get("latency_total_ms") or 0) / latency_samples if latency_samples else None
		)
		item["first_token_avg_ms"] = (
			float(item.get("first_token_total_ms") or 0) / first_token_samples if first_token_samples else None
		)
		item["positive_feedback_rate"] = (
			cint(item.get("positive_feedback_count")) / feedback_count if feedback_count else None
		)
		items.append(item)
	return {"status": "success", "data": {"items": items}}


def get_published_ai_model_policies_for_runtime() -> dict:
	"""Internal runtime snapshot; callers must add service authentication at the transport boundary."""
	_ensure_tables()
	rows = frappe.db.sql(
		f"""
		SELECT p.policy_code, p.published_version, v.snapshot_json, v.content_hash, v.published_at
		FROM `{POLICY_TABLE}` p
		JOIN `{POLICY_VERSION_TABLE}` v
			ON v.policy_code = p.policy_code AND v.version_no = p.published_version
		WHERE p.status = 'active' AND v.status = 'active'
		ORDER BY p.policy_code
		""",
		as_dict=True,
	)
	policies = [
			{
				"policy_code": row.policy_code,
				"policy_version": cint(row.published_version),
				"content_hash": row.content_hash,
				"published_at": str(row.published_at or "") or None,
				"policy": _safe_json_loads(row.snapshot_json, {}),
			}
			for row in rows
		]
	policy_aliases = sorted({
		alias
		for item in policies
		for alias in [
			item["policy"].get("primary_model_alias"),
			*(item["policy"].get("fallback_model_aliases") or []),
		]
		if alias
	})
	model_rows = frappe.db.sql(
		f"""
		SELECT model_alias, capability, status, supports_json_schema, input_cost, output_cost, currency,
			data_region, retention_policy, sensitive_data_allowed, registry_version
		FROM `{REGISTRY_TABLE}`
		WHERE status IN ('active', 'validated')
			OR model_alias IN ({', '.join(['%s'] * len(policy_aliases))})
		""",
		tuple(policy_aliases),
		as_dict=True,
	) if policy_aliases else frappe.db.sql(
		f"""
		SELECT model_alias, capability, status, supports_json_schema, input_cost, output_cost, currency,
			data_region, retention_policy, sensitive_data_allowed, registry_version
		FROM `{REGISTRY_TABLE}` WHERE status IN ('active', 'validated')
		""",
		as_dict=True,
	)
	return {
		"policies": policies,
		"models": {
			row.model_alias: {
				"capability": row.capability,
				"status": row.status,
				"supports_json_schema": bool(cint(row.supports_json_schema)),
				"input_cost": str(row.input_cost or 0),
				"output_cost": str(row.output_cost or 0),
				"currency": row.currency,
				"data_region": row.data_region,
				"retention_policy": row.retention_policy,
				"sensitive_data_allowed": bool(cint(row.sensitive_data_allowed)),
				"registry_version": cint(row.registry_version),
			}
			for row in model_rows
		},
	}
