from __future__ import annotations

import hashlib
import json
import uuid

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from myapp.services.wholesale_service import update_product_v2
from myapp.utils.idempotency import run_idempotent


TASK_TABLE = "tabMyApp AI Data Task"
AUDIT_TABLE = "tabMyApp AI Audit Event"
VIEW_ROLES = {"System Manager", "AI Data Steward", "AI Data Approver", "AI Auditor"}
STEWARD_ROLES = {"System Manager", "AI Data Steward"}
APPROVER_ROLES = {"System Manager", "AI Data Approver"}
TASK_TYPES = {"product_field_update", "product_completeness"}
STATUSES = {"queued", "analyzed", "review_required", "approved", "executed", "rejected", "failed", "rolled_back"}
OPEN_STATUSES = {"queued", "analyzed", "review_required", "approved"}
ALLOWED_PRODUCT_FIELDS = {"item_name", "description", "brand", "item_group"}
HIGH_RISK_FIELDS = {"item_name", "item_group"}
MEDIUM_RISK_FIELDS = {"brand"}
MAX_PAGE_SIZE = 100


def _current_user() -> str:
	user = str(getattr(frappe.session, "user", "") or "").strip()
	if not user or user == "Guest":
		raise frappe.PermissionError(_("请先登录。"))
	return user


def _require_roles(roles: set[str], message: str) -> str:
	user = _current_user()
	if user == "Administrator":
		return user
	if not (set(frappe.get_roles(user) or []) & roles):
		raise frappe.PermissionError(message)
	return user


def _require_viewer() -> str:
	return _require_roles(VIEW_ROLES, _("无权查看 AI 数据治理任务。"))


def _require_steward() -> str:
	return _require_roles(STEWARD_ROLES, _("无权创建或执行 AI 数据治理任务。"))


def _require_approver() -> str:
	return _require_roles(APPROVER_ROLES, _("无权审批 AI 数据治理任务。"))


def _require_system_manager() -> str:
	return _require_roles({"System Manager"}, _("只有系统管理员可以回滚 AI 数据治理任务。"))


def _ensure_tables() -> None:
	if not frappe.db.table_exists("MyApp AI Data Task"):
		frappe.throw(_("AI 数据治理任务表尚未初始化，请先执行 bench migrate。"))


def _json(value) -> str:
	return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _loads(value, default):
	if value in (None, ""):
		return default
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return default


def _hash(value) -> str:
	return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _text(value, *, limit: int = 1000) -> str:
	return " ".join(str(value or "").split())[:limit]


def _name() -> str:
	return f"AI-DATA-{uuid.uuid4().hex}"


def _item_snapshot(item, fields: set[str]) -> dict:
	return {field: str(getattr(item, field, "") or "") for field in sorted(fields)}


def _normalize_changes(value) -> dict:
	value = _loads(value, value)
	if not isinstance(value, dict) or not value:
		frappe.throw(_("建议变更必须是非空对象。"))
	unknown = set(value) - ALLOWED_PRODUCT_FIELDS
	if unknown:
		frappe.throw(_("首期数据治理不允许修改字段：{0}。").format(", ".join(sorted(unknown))))
	changes = {}
	for field, raw in value.items():
		resolved = _text(raw, limit=2000 if field == "description" else 255)
		if field in {"item_name", "item_group"} and not resolved:
			frappe.throw(_("{0}不能为空。").format(field))
		changes[field] = resolved
	return changes


def _risk_level(fields: set[str]) -> str:
	if fields & HIGH_RISK_FIELDS:
		return "high"
	if fields & MEDIUM_RISK_FIELDS:
		return "medium"
	return "low"


def _serialize(row) -> dict:
	return {
		"name": row.name,
		"task_type": row.task_type,
		"target_doctype": row.target_doctype,
		"target_name": row.target_name,
		"company": row.company,
		"status": row.status,
		"risk_level": row.risk_level,
		"before_value": _loads(row.before_value_json, {}),
		"proposed_value": _loads(row.proposed_value_json, {}),
		"evidence": _loads(row.evidence_json, {}),
		"analysis": _loads(row.analysis_json, {}),
		"model_alias": row.model_alias,
		"prompt_version": row.prompt_version,
		"policy_code": row.policy_code,
		"policy_version": cint(row.policy_version) or None,
		"source_run": row.source_run,
		"requested_by": row.requested_by,
		"analyzed_by": row.analyzed_by,
		"analyzed_at": row.analyzed_at,
		"reviewer": row.reviewer,
		"reviewed_at": row.reviewed_at,
		"review_reason": row.review_reason,
		"executed_by": row.executed_by,
		"executed_at": row.executed_at,
		"execution_result": _loads(row.execution_result_json, None),
		"rollback_by": row.rollback_by,
		"rollback_at": row.rollback_at,
		"rollback_reason": row.rollback_reason,
		"rollback_result": _loads(row.rollback_result_json, None),
		"version": cint(row.version_no) or 1,
		"creation": row.creation,
		"modified": row.modified,
	}


def _get_task(task_name: str, *, lock: bool = False):
	rows = frappe.db.sql(
		f"SELECT * FROM `{TASK_TABLE}` WHERE name = %s{' FOR UPDATE' if lock else ''}",
		(task_name,), as_dict=True,
	)
	if not rows:
		frappe.throw(_("AI 数据治理任务不存在。"), frappe.DoesNotExistError)
	return rows[0]


def _audit(*, actor: str, action: str, task_name: str, reason: str, parameters, result, priority="normal"):
	if not frappe.db.table_exists("MyApp AI Audit Event"):
		return
	now = now_datetime()
	frappe.db.sql(
		f"""
		INSERT INTO `{AUDIT_TABLE}`
		(name, creation, modified, modified_by, owner, actor, action, object_type, object_name,
		 reason, parameter_hash, result_hash, metadata_json, priority)
		VALUES (%s, %s, %s, %s, %s, %s, %s, 'ai_data_task', %s, %s, %s, %s, %s, %s)
		""",
		(
			f"AI-AUDIT-{uuid.uuid4().hex}", now, now, actor, actor, actor, action, task_name,
			reason, _hash(parameters), _hash(result), _json({"status": result.get("status")}), priority,
		),
	)


def _insert_task(*, actor: str, task_type: str, target_name: str, before: dict, proposed: dict, evidence: dict,
	model_alias: str, prompt_version: str, source_run: str | None = None, policy_code: str | None = None,
	policy_version: int | None = None) -> dict:
	if task_type not in TASK_TYPES:
		frappe.throw(_("不支持的数据治理任务类型。"))
	proposal_hash = _hash({"task_type": task_type, "target_name": target_name, "proposed": proposed})
	existing = frappe.db.sql(
		f"SELECT * FROM `{TASK_TABLE}` WHERE proposal_hash = %s AND status IN ('queued','analyzed','review_required','approved') ORDER BY creation DESC LIMIT 1",
		(proposal_hash,), as_dict=True,
	)
	if existing:
		return _serialize(existing[0])
	now = now_datetime()
	name = _name()
	risk = _risk_level(set(proposed))
	analysis = {
		"valid": True,
		"allowed_fields": sorted(proposed),
		"risk_level": risk,
		"execution_service": "update_product_v2",
		"formal_document_write": False,
	}
	frappe.db.sql(
		f"""
		INSERT INTO `{TASK_TABLE}`
		(name, creation, modified, modified_by, owner, task_type, target_doctype, target_name,
		 status, risk_level, before_value_json, proposed_value_json, evidence_json, analysis_json,
		 proposal_hash, model_alias, prompt_version, policy_code, policy_version, source_run,
		 requested_by, analyzed_by, analyzed_at, version_no)
		VALUES (%s,%s,%s,%s,%s,%s,'Item',%s,'review_required',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
		""",
		(
			name, now, now, actor, actor, task_type, target_name, risk,
			_json(before), _json(proposed), _json(evidence), _json(analysis), proposal_hash,
			model_alias, prompt_version, policy_code, policy_version, source_run,
			actor, actor, now,
		),
	)
	task = _serialize(_get_task(name))
	_audit(actor=actor, action="ai_data_task_analyzed", task_name=name, reason="task analyzed",
		parameters={"before": before, "proposed": proposed}, result={"status": task["status"]},
		priority="critical" if risk == "high" else "normal")
	return task


def create_ai_data_task_v1(payload, reason: str, request_id: str | None = None) -> dict:
	actor = _require_steward()
	_ensure_tables()
	payload = _loads(payload, payload)
	if not isinstance(payload, dict):
		frappe.throw(_("任务载荷必须是对象。"))
	target_name = _text(payload.get("target_name"), limit=140)
	resolved_reason = _text(reason, limit=1000)
	if not target_name or not resolved_reason:
		frappe.throw(_("目标商品和创建原因不能为空。"))
	proposed = _normalize_changes(payload.get("proposed_value"))

	def create():
		item = frappe.get_doc("Item", target_name)
		item.check_permission("write")
		before = _item_snapshot(item, set(proposed))
		if before == proposed:
			frappe.throw(_("建议值与当前值相同，无需创建任务。"))
		task = _insert_task(
			actor=actor, task_type="product_field_update", target_name=item.name,
			before=before, proposed=proposed,
			evidence={"source": "manual_governance", "reason": resolved_reason},
			model_alias=_text(payload.get("model_alias"), limit=140) or "human-governed-suggestion",
			prompt_version=_text(payload.get("prompt_version"), limit=140) or "product-data-quality-v1",
			source_run=_text(payload.get("source_run"), limit=140) or None,
			policy_code=_text(payload.get("policy_code"), limit=140) or None,
			policy_version=cint(payload.get("policy_version")) or None,
		)
		return {"status": "success", "data": {"task": task}}

	return run_idempotent("create_ai_data_task_v1", request_id, create)


def analyze_ai_product_data_v1(item_codes=None, limit: int = 50, request_id: str | None = None) -> dict:
	actor = _require_steward()
	_ensure_tables()
	limit = max(1, min(cint(limit) or 50, 100))
	item_codes = _loads(item_codes, item_codes)
	if isinstance(item_codes, str):
		item_codes = [part.strip() for part in item_codes.split(",") if part.strip()]
	item_codes = list(dict.fromkeys(item_codes or []))[:100]

	def analyze():
		conditions = ["disabled = 0", "(description IS NULL OR TRIM(description) = '')"]
		values = []
		if item_codes:
			conditions.append(f"name IN ({', '.join(['%s'] * len(item_codes))})")
			values.extend(item_codes)
		rows = frappe.db.sql(
			f"SELECT name, item_name, item_group, brand, description FROM `tabItem` WHERE {' AND '.join(conditions)} ORDER BY modified DESC LIMIT %s",
			(*values, limit), as_dict=True,
		)
		tasks = []
		for row in rows:
			if not frappe.has_permission("Item", "write", row.name):
				continue
			parts = [str(row.item_name or row.name)]
			if row.brand:
				parts.append(str(row.brand))
			if row.item_group:
				parts.append(str(row.item_group))
			proposed = {"description": " · ".join(dict.fromkeys(parts))[:2000]}
			tasks.append(_insert_task(
				actor=actor, task_type="product_completeness", target_name=row.name,
				before={"description": str(row.description or "")}, proposed=proposed,
				evidence={
					"source": "deterministic_rule", "rule": "missing_description",
					"source_fields": ["item_name", "brand", "item_group"],
				},
				model_alias="deterministic-data-quality-v1",
				prompt_version="product-data-quality-v1",
			))
		return {"status": "success", "data": {"tasks": tasks, "created_or_reused": len(tasks)}}

	return run_idempotent("analyze_ai_product_data_v1", request_id, analyze)


def list_ai_data_tasks_v1(status: str | None = None, risk_level: str | None = None,
	task_type: str | None = None, start: int = 0, limit: int = 20) -> dict:
	_require_viewer()
	_ensure_tables()
	conditions = ["1=1"]
	values = []
	if status:
		if status not in STATUSES:
			frappe.throw(_("任务状态不正确。"))
		conditions.append("status = %s")
		values.append(status)
	if risk_level:
		conditions.append("risk_level = %s")
		values.append(risk_level)
	if task_type:
		conditions.append("task_type = %s")
		values.append(task_type)
	start = max(0, cint(start))
	limit = max(1, min(cint(limit) or 20, MAX_PAGE_SIZE))
	rows = frappe.db.sql(
		f"SELECT * FROM `{TASK_TABLE}` WHERE {' AND '.join(conditions)} ORDER BY modified DESC LIMIT %s OFFSET %s",
		(*values, limit, start), as_dict=True,
	)
	total = frappe.db.sql(
		f"SELECT COUNT(*) AS total FROM `{TASK_TABLE}` WHERE {' AND '.join(conditions)}",
		tuple(values), as_dict=True,
	)[0].total
	return {"status": "success", "data": {"tasks": [_serialize(row) for row in rows], "total": cint(total), "start": start, "limit": limit}}


def get_ai_data_task_v1(task_name: str) -> dict:
	_require_viewer()
	_ensure_tables()
	return {"status": "success", "data": {"task": _serialize(_get_task(task_name))}}


def review_ai_data_task_v1(task_name: str, action: str, reason: str, request_id: str | None = None) -> dict:
	actor = _require_approver()
	_ensure_tables()
	action = _text(action, limit=20).lower()
	reason = _text(reason, limit=1000)
	if action not in {"approve", "reject"} or not reason:
		frappe.throw(_("审批动作或原因不正确。"))

	def review():
		task = _get_task(task_name, lock=True)
		if task.status != "review_required":
			frappe.throw(_("只有待审批任务可以审批或驳回。"))
		if actor == task.requested_by:
			frappe.throw(_("任务发起人不能审批自己的数据变更建议。"))
		status = "approved" if action == "approve" else "rejected"
		now = now_datetime()
		frappe.db.sql(
			f"UPDATE `{TASK_TABLE}` SET status=%s, reviewer=%s, reviewed_at=%s, review_reason=%s, modified=%s, modified_by=%s WHERE name=%s",
			(status, actor, now, reason, now, actor, task_name),
		)
		result = _serialize(_get_task(task_name))
		_audit(actor=actor, action=f"ai_data_task_{status}", task_name=task_name, reason=reason,
			parameters={"action": action}, result={"status": status}, priority="critical" if task.risk_level == "high" else "normal")
		return {"status": "success", "data": {"task": result}}

	return run_idempotent("review_ai_data_task_v1", request_id, review)


def execute_ai_data_task_v1(task_name: str, request_id: str | None = None) -> dict:
	actor = _require_steward()
	_ensure_tables()

	def execute():
		task = _get_task(task_name, lock=True)
		if task.status == "executed":
			return {"status": "success", "data": {"task": _serialize(task), "idempotent_replay": True}}
		if task.status != "approved":
			frappe.throw(_("只有已审批任务可以执行。"))
		if actor == task.reviewer:
			frappe.throw(_("审批人不能执行同一数据变更任务。"))
		item = frappe.get_doc("Item", task.target_name)
		item.check_permission("write")
		before = _loads(task.before_value_json, {})
		proposed = _loads(task.proposed_value_json, {})
		current = _item_snapshot(item, set(before))
		if current != before:
			now = now_datetime()
			failure = {"code": "SOURCE_CHANGED", "expected": before, "actual": current}
			frappe.db.sql(
				f"UPDATE `{TASK_TABLE}` SET status='failed', execution_result_json=%s, executed_by=%s, executed_at=%s, modified=%s, modified_by=%s WHERE name=%s",
				(_json(failure), actor, now, now, actor, task_name),
			)
			_audit(actor=actor, action="ai_data_task_failed", task_name=task_name, reason="source changed",
				parameters={"expected": before}, result={"status": "failed", **failure}, priority="critical")
			return {"status": "success", "data": {"task": _serialize(_get_task(task_name))}}
		service_result = update_product_v2(
			item_code=task.target_name,
			request_id=f"ai-data-task:{task_name}:execute:v{cint(task.version_no) or 1}",
			**proposed,
		)
		now = now_datetime()
		result_payload = {"service": "update_product_v2", "result": service_result}
		frappe.db.sql(
			f"UPDATE `{TASK_TABLE}` SET status='executed', execution_result_json=%s, executed_by=%s, executed_at=%s, modified=%s, modified_by=%s WHERE name=%s",
			(_json(result_payload), actor, now, now, actor, task_name),
		)
		result = _serialize(_get_task(task_name))
		_audit(actor=actor, action="ai_data_task_executed", task_name=task_name, reason="approved task execution",
			parameters={"proposed": proposed}, result={"status": "executed"}, priority="critical" if task.risk_level == "high" else "normal")
		return {"status": "success", "data": {"task": result}}

	return run_idempotent("execute_ai_data_task_v1", request_id, execute)


def rollback_ai_data_task_v1(task_name: str, reason: str, request_id: str | None = None) -> dict:
	actor = _require_system_manager()
	_ensure_tables()
	reason = _text(reason, limit=1000)
	if not reason:
		frappe.throw(_("回滚原因不能为空。"))

	def rollback():
		task = _get_task(task_name, lock=True)
		if task.status == "rolled_back":
			return {"status": "success", "data": {"task": _serialize(task), "idempotent_replay": True}}
		if task.status != "executed":
			frappe.throw(_("只有已执行任务可以回滚。"))
		item = frappe.get_doc("Item", task.target_name)
		item.check_permission("write")
		before = _loads(task.before_value_json, {})
		proposed = _loads(task.proposed_value_json, {})
		current = _item_snapshot(item, set(proposed))
		if current != proposed:
			frappe.throw(_("商品在任务执行后已再次变更，不能自动回滚。"))
		service_result = update_product_v2(
			item_code=task.target_name,
			request_id=f"ai-data-task:{task_name}:rollback:v{cint(task.version_no) or 1}",
			**before,
		)
		now = now_datetime()
		result_payload = {"service": "update_product_v2", "result": service_result}
		frappe.db.sql(
			f"UPDATE `{TASK_TABLE}` SET status='rolled_back', rollback_result_json=%s, rollback_by=%s, rollback_at=%s, rollback_reason=%s, modified=%s, modified_by=%s WHERE name=%s",
			(_json(result_payload), actor, now, reason, now, actor, task_name),
		)
		result = _serialize(_get_task(task_name))
		_audit(actor=actor, action="ai_data_task_rolled_back", task_name=task_name, reason=reason,
			parameters={"restore": before}, result={"status": "rolled_back"}, priority="critical")
		return {"status": "success", "data": {"task": result}}

	return run_idempotent("rollback_ai_data_task_v1", request_id, rollback)
