from __future__ import annotations

import hashlib
import json
import os
import re

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from myapp.services.ai_model_governance_service import (
	REGISTRY_TABLE,
	_call_orchestrator,
	_normalize_text,
	_record_audit,
	_require_approver,
	_require_manager,
	_require_system_manager,
	_require_viewer,
)
from myapp.services.ai_vector_service import (
	MAX_VECTOR_BATCH_SIZE,
	build_product_vector_document,
)
from myapp.utils.idempotency import run_idempotent


RELEASE_TABLE = "tabMyApp AI Vector Release"
BUILD_ITEM_TABLE = "tabMyApp AI Vector Build Item"
RESOURCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,139}$")
ENVIRONMENTS = {"development", "test", "staging", "production"}


def _ensure_tables():
	if not frappe.db.table_exists("MyApp AI Vector Release"):
		frappe.throw(_("AI 向量发布治理表尚未初始化，请先执行 bench migrate。"))


def _resource(value, label: str, *, max_length: int = 140) -> str:
	resolved = _normalize_text(value, max_length=max_length)
	if not resolved or not RESOURCE_PATTERN.fullmatch(resolved):
		frappe.throw(_("{0}格式不正确。").format(label))
	return resolved


def _configured_alias() -> str:
	return os.environ.get("MYAPP_AI_QDRANT_ALIAS", "").strip()


def _serialize(row) -> dict:
	return {
		"release_code": row.release_code,
		"alias_name": row.alias_name,
		"collection_name": row.collection_name,
		"embedding_model": row.embedding_model,
		"index_version": row.index_version,
		"environment": row.environment,
		"status": row.status,
		"total_items": cint(row.total_items),
		"indexed_count": cint(row.indexed_count),
		"failed_count": cint(row.failed_count),
		"vector_size": cint(row.vector_size) or None,
		"previous_collection": row.previous_collection,
		"validation": json.loads(row.validation_json) if row.validation_json else None,
		"created_by": row.created_by,
		"approved_by": row.approved_by,
		"approved_at": str(row.approved_at or "") or None,
		"published_by": row.published_by,
		"published_at": str(row.published_at or "") or None,
		"rollback_from_release": row.rollback_from_release,
		"change_reason": row.change_reason,
		"creation": str(row.creation or "") or None,
		"modified": str(row.modified or "") or None,
	}


def _get_release(release_code: str, *, for_update: bool = False):
	lock = " FOR UPDATE" if for_update else ""
	rows = frappe.db.sql(
		f"SELECT * FROM `{RELEASE_TABLE}` WHERE release_code = %s LIMIT 1{lock}",
		(_normalize_text(release_code, max_length=140),), as_dict=True,
	)
	if not rows:
		frappe.throw(_("AI 向量发布版本不存在。"))
	return rows[0]


def _refresh_counts(release_code: str):
	counts = frappe.db.sql(
		f"""
		SELECT COUNT(*) AS total_items,
			SUM(status = 'indexed') AS indexed_count,
			SUM(status = 'failed') AS failed_count
		FROM `{BUILD_ITEM_TABLE}` WHERE release_code = %s
		""",
		(release_code,), as_dict=True,
	)[0]
	frappe.db.sql(
		f"UPDATE `{RELEASE_TABLE}` SET total_items = %s, indexed_count = %s, failed_count = %s, modified = %s WHERE release_code = %s",
		(
			cint(counts.total_items), cint(counts.indexed_count), cint(counts.failed_count),
			now_datetime(), release_code,
		),
	)
	return {
		"total_items": cint(counts.total_items),
		"indexed_count": cint(counts.indexed_count),
		"failed_count": cint(counts.failed_count),
	}


def list_ai_vector_releases_v1(*, start: int = 0, limit: int = 20) -> dict:
	_require_viewer()
	_ensure_tables()
	start = max(0, cint(start))
	limit = max(1, min(100, cint(limit) or 20))
	total = frappe.db.sql(f"SELECT COUNT(*) FROM `{RELEASE_TABLE}`")[0][0]
	rows = frappe.db.sql(
		f"SELECT * FROM `{RELEASE_TABLE}` ORDER BY creation DESC LIMIT %s OFFSET %s",
		(limit, start), as_dict=True,
	)
	return {"status": "success", "data": {"items": [_serialize(row) for row in rows], "pagination": {"total": cint(total), "start": start, "limit": limit}}}


def get_ai_vector_release_v1(*, release_code: str, failure_limit: int = 50) -> dict:
	_require_viewer()
	_ensure_tables()
	release = _get_release(release_code)
	failures = frappe.db.sql(
		f"SELECT item_code, last_error, last_attempt_at FROM `{BUILD_ITEM_TABLE}` WHERE release_code = %s AND status = 'failed' ORDER BY modified DESC LIMIT %s",
		(release.release_code, max(1, min(100, cint(failure_limit) or 50))), as_dict=True,
	)
	try:
		provider = _call_orchestrator(
			"/internal/v1/vector/governance/status",
			payload={"collection": release.collection_name, "alias_name": release.alias_name},
			method="POST",
		)
	except Exception as error:
		provider = {"reachable": False, "error": type(error).__name__}
	return {"status": "success", "data": {"release": _serialize(release), "failures": [dict(row) for row in failures], "provider": provider}}


def create_ai_vector_release_v1(*, payload, reason: str, request_id: str | None = None) -> dict:
	actor = _require_manager()
	_ensure_tables()
	payload = frappe.parse_json(payload) if isinstance(payload, str) else payload
	if not isinstance(payload, dict):
		frappe.throw(_("向量发布载荷必须是对象。"))
	release_code = _resource(payload.get("release_code"), _("发布编码"))
	alias_name = _resource(payload.get("alias_name"), _("Qdrant Alias"))
	collection_name = _resource(payload.get("collection_name"), _("Qdrant Collection"))
	embedding_model = _resource(payload.get("embedding_model"), _("Embedding 模型"))
	index_version = _resource(payload.get("index_version"), _("索引版本"), max_length=40)
	environment = _normalize_text(payload.get("environment") or "development", max_length=30).lower()
	resolved_reason = _normalize_text(reason, max_length=1000)
	if environment not in ENVIRONMENTS:
		frappe.throw(_("向量发布环境不正确。"))
	if alias_name == collection_name:
		frappe.throw(_("Qdrant Alias 与物理 Collection 不能同名。"))
	if not resolved_reason:
		frappe.throw(_("创建向量发布必须填写原因。"))
	if _configured_alias() != alias_name:
		frappe.throw(_("运行环境必须先配置与发布一致的 MYAPP_AI_QDRANT_ALIAS。"))

	def _create():
		model = frappe.db.sql(
			f"SELECT capability, status, data_region, retention_policy FROM `{REGISTRY_TABLE}` WHERE model_alias = %s LIMIT 1",
			(embedding_model,), as_dict=True,
		)
		if not model or model[0].capability != "embedding" or model[0].status not in {"validated", "active", "degraded"}:
			frappe.throw(_("Embedding 模型尚未完成注册和健康验证。"))
		if not model[0].data_region or not model[0].retention_policy:
			frappe.throw(_("Embedding 模型尚未完成数据区域和留存策略复核。"))
		provider = _call_orchestrator(
			"/internal/v1/vector/governance/status",
			payload={"collection": collection_name, "alias_name": alias_name}, method="POST",
		)
		if provider.get("collection_exists"):
			frappe.throw(_("候选 Collection 已存在；为避免混用向量空间，请使用新的不可变名称。"))
		now = now_datetime()
		name = f"AI-VECTOR-RELEASE-{hashlib.sha256(release_code.encode()).hexdigest()[:24]}"
		frappe.db.sql(
			f"""
			INSERT INTO `{RELEASE_TABLE}`
				(name, creation, modified, modified_by, owner, docstatus, idx, release_code,
				 alias_name, collection_name, embedding_model, index_version, environment,
				 status, total_items, previous_collection, created_by, change_reason)
			VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, %s, %s,
				'building', 0, %s, %s, %s)
			""",
			(
				name, now, now, actor, actor, release_code, alias_name, collection_name,
				embedding_model, index_version, environment,
				(provider.get("alias") or {}).get("collection"), actor, resolved_reason,
			),
		)
		items = frappe.get_all("Item", pluck="name", order_by="name asc", limit_page_length=1_000_000)
		for item_code in items:
			item_name = f"AI-VECTOR-BUILD-{hashlib.sha256(f'{release_code}:{item_code}'.encode()).hexdigest()}"
			frappe.db.sql(
				f"""
				INSERT INTO `{BUILD_ITEM_TABLE}`
					(name, creation, modified, modified_by, owner, docstatus, idx,
					 release_code, item_code, status)
				VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, 'pending')
				""",
				(item_name, now, now, actor, actor, release_code, item_code),
			)
		frappe.db.sql(
			f"UPDATE `{RELEASE_TABLE}` SET total_items = %s WHERE release_code = %s",
			(len(items), release_code),
		)
		for offset in range(0, len(items), 64):
			frappe.enqueue(
				"myapp.services.ai_vector_governance_service.build_ai_vector_release_batch",
				queue="ai-vector", release_code=release_code, item_codes=items[offset:offset + 64],
				job_name=f"AI vector release {release_code} batch {offset // 64 + 1}",
				enqueue_after_commit=True,
			)
		response = {"release_code": release_code, "status": "building", "queued_count": len(items)}
		_record_audit(actor=actor, action="create_vector_release", object_type="vector_release", object_name=release_code, parameters=payload, result=response, reason=resolved_reason, priority="critical")
		return {"status": "success", "message": _("AI 向量候选版本已创建并开始补建。"), "data": response}

	return run_idempotent("create_ai_vector_release_v1", request_id, _create, request_payload={"payload": payload, "reason": resolved_reason})


def build_ai_vector_release_batch(*, release_code: str, item_codes) -> dict:
	_ensure_tables()
	release = _get_release(release_code)
	if release.status not in {"building", "failed"}:
		return {"status": "ignored", "release_code": release.release_code}
	codes = [str(value or "").strip() for value in (item_codes or []) if str(value or "").strip()][:MAX_VECTOR_BATCH_SIZE]
	documents = []
	now = now_datetime()
	for item_code in codes:
		if not frappe.db.exists("Item", item_code):
			frappe.db.sql(
				f"UPDATE `{BUILD_ITEM_TABLE}` SET status = 'failed', last_error = 'Item no longer exists', last_attempt_at = %s, modified = %s WHERE release_code = %s AND item_code = %s",
				(now, now, release.release_code, item_code),
			)
			continue
		document = build_product_vector_document(frappe.get_doc("Item", item_code))
		document["index_version"] = release.index_version
		documents.append(document)
	if documents:
		try:
			result = _call_orchestrator(
				"/internal/v1/vector/products/upsert",
				payload={
					"documents": documents,
					"embedding_model": release.embedding_model,
					"collection": release.collection_name,
				},
				method="POST", timeout=180,
			)
		except Exception as error:
			for document in documents:
				frappe.db.sql(
					f"UPDATE `{BUILD_ITEM_TABLE}` SET content_hash = %s, status = 'failed', last_error = %s, last_attempt_at = %s, modified = %s WHERE release_code = %s AND item_code = %s",
					(document["content_hash"], str(error)[:500], now, now, release.release_code, document["item_code"]),
				)
			_refresh_counts(release.release_code)
			frappe.db.sql(f"UPDATE `{RELEASE_TABLE}` SET status = 'failed' WHERE release_code = %s", (release.release_code,))
			frappe.db.commit()
			raise
		for document in documents:
			frappe.db.sql(
				f"UPDATE `{BUILD_ITEM_TABLE}` SET content_hash = %s, status = 'indexed', last_error = NULL, last_attempt_at = %s, indexed_at = %s, modified = %s WHERE release_code = %s AND item_code = %s",
				(document["content_hash"], now, now, now, release.release_code, document["item_code"]),
			)
	else:
		result = {}
	counts = _refresh_counts(release.release_code)
	if counts["failed_count"] == 0:
		frappe.db.sql(f"UPDATE `{RELEASE_TABLE}` SET status = 'building' WHERE release_code = %s", (release.release_code,))
	frappe.db.commit()
	return {"status": "completed", "release_code": release.release_code, **counts, "embedding_mode": result.get("embedding_mode")}


def retry_ai_vector_release_v1(*, release_code: str, request_id: str | None = None) -> dict:
	actor = _require_manager()
	_ensure_tables()

	def _retry():
		release = _get_release(release_code, for_update=True)
		if release.status not in {"building", "failed"}:
			frappe.throw(_("当前向量发布状态不允许重试构建。"))
		codes = [row.item_code for row in frappe.db.sql(
			f"SELECT item_code FROM `{BUILD_ITEM_TABLE}` WHERE release_code = %s AND status != 'indexed' ORDER BY item_code",
			(release.release_code,), as_dict=True,
		)]
		frappe.db.sql(f"UPDATE `{RELEASE_TABLE}` SET status = 'building', modified = %s, modified_by = %s WHERE release_code = %s", (now_datetime(), actor, release.release_code))
		for offset in range(0, len(codes), 64):
			frappe.enqueue(
				"myapp.services.ai_vector_governance_service.build_ai_vector_release_batch",
				queue="ai-vector", release_code=release.release_code, item_codes=codes[offset:offset + 64],
				job_name=f"AI vector release retry {release.release_code} batch {offset // 64 + 1}",
				enqueue_after_commit=True,
			)
		return {"status": "success", "message": _("AI 向量候选版本重试任务已入队。"), "data": {"release_code": release.release_code, "queued_count": len(codes)}}

	return run_idempotent("retry_ai_vector_release_v1", request_id, _retry, request_payload={"release_code": release_code})


def _validate_release(release) -> dict:
	counts = _refresh_counts(release.release_code)
	provider = _call_orchestrator(
		"/internal/v1/vector/governance/status",
		payload={"collection": release.collection_name, "alias_name": release.alias_name}, method="POST",
	)
	gate = _call_orchestrator(
		"/internal/v1/vector/governance/validate-release",
		payload={
			"release_code": release.release_code,
			"embedding_model": release.embedding_model,
			"collection": release.collection_name,
			"index_version": release.index_version,
		}, method="POST",
	)
	errors = list(gate.get("errors") or [])
	if counts["total_items"] == 0:
		errors.append(_("向量发布没有任何商品构建项。"))
	if counts["indexed_count"] != counts["total_items"] or counts["failed_count"]:
		errors.append(_("向量候选版本尚未完成全量构建。"))
	if not provider.get("collection_exists"):
		errors.append(_("候选 Collection 不存在。"))
	if cint(provider.get("points_count")) != counts["total_items"]:
		errors.append(_("候选 Collection 点数与构建商品数不一致。"))
	if not provider.get("vector_size"):
		errors.append(_("候选 Collection 缺少有效向量维度。"))
	return {
		"valid": not errors,
		"release_gate_eligible": bool(gate.get("release_gate_eligible")) and not errors,
		"errors": errors,
		"warnings": gate.get("warnings") or [],
		"evaluation": gate.get("evaluation"),
		"provider": provider,
		"counts": counts,
		"validated_at": str(now_datetime()),
	}


def validate_ai_vector_release_v1(*, release_code: str, request_id: str | None = None) -> dict:
	actor = _require_manager()
	_ensure_tables()

	def _validate():
		release = _get_release(release_code, for_update=True)
		if release.status not in {"building", "failed", "review_required"}:
			frappe.throw(_("当前向量发布状态不允许校验。"))
		validation = _validate_release(release)
		next_status = "review_required" if validation["valid"] else ("failed" if validation["counts"]["failed_count"] else "building")
		frappe.db.sql(
			f"UPDATE `{RELEASE_TABLE}` SET status = %s, vector_size = %s, validation_json = %s, modified = %s, modified_by = %s WHERE release_code = %s",
			(next_status, validation["provider"].get("vector_size"), frappe.as_json(validation), now_datetime(), actor, release.release_code),
		)
		_record_audit(actor=actor, action="validate_vector_release", object_type="vector_release", object_name=release.release_code, parameters={}, result=validation, priority="critical")
		return {"status": "success", "message": _("AI 向量候选版本校验完成。"), "data": {"release_code": release.release_code, "status": next_status, "validation": validation}}

	return run_idempotent("validate_ai_vector_release_v1", request_id, _validate, request_payload={"release_code": release_code})


def approve_ai_vector_release_v1(*, release_code: str, reason: str, request_id: str | None = None) -> dict:
	actor = _require_approver()
	_ensure_tables()
	resolved_reason = _normalize_text(reason, max_length=1000)
	if not resolved_reason:
		frappe.throw(_("审批向量发布必须填写原因。"))

	def _approve():
		release = _get_release(release_code, for_update=True)
		if release.status != "review_required":
			frappe.throw(_("只有已通过校验的向量版本可以审批。"))
		validation = json.loads(release.validation_json or "{}")
		if not validation.get("valid") or not validation.get("release_gate_eligible"):
			frappe.throw(_("向量发布未通过完整门禁。"))
		if release.environment == "production" and release.created_by == actor:
			frappe.throw(_("生产向量发布的起草人与审批人必须分离。"))
		now = now_datetime()
		frappe.db.sql(f"UPDATE `{RELEASE_TABLE}` SET status = 'approved', approved_by = %s, approved_at = %s, modified = %s, modified_by = %s WHERE release_code = %s", (actor, now, now, actor, release.release_code))
		response = {"release_code": release.release_code, "status": "approved"}
		_record_audit(actor=actor, action="approve_vector_release", object_type="vector_release", object_name=release.release_code, parameters={}, result=response, reason=resolved_reason, priority="critical")
		return {"status": "success", "message": _("AI 向量候选版本已审批。"), "data": response}

	return run_idempotent("approve_ai_vector_release_v1", request_id, _approve, request_payload={"release_code": release_code, "reason": resolved_reason})


def publish_ai_vector_release_v1(*, release_code: str, reason: str, request_id: str | None = None) -> dict:
	actor = _require_system_manager()
	_ensure_tables()
	resolved_reason = _normalize_text(reason, max_length=1000)
	if not resolved_reason:
		frappe.throw(_("发布向量版本必须填写原因。"))

	def _publish():
		release = _get_release(release_code, for_update=True)
		if release.status != "approved":
			frappe.throw(_("只有已审批的向量版本可以发布。"))
		validation = _validate_release(release)
		if not validation["valid"] or not validation["release_gate_eligible"]:
			frappe.throw(_("向量发布状态或完整门禁已失效，请重新校验审批。"))
		switch = _call_orchestrator(
			"/internal/v1/vector/governance/switch-alias",
			payload={"alias_name": release.alias_name, "target_collection": release.collection_name}, method="POST",
		)
		now = now_datetime()
		frappe.db.sql(f"UPDATE `{RELEASE_TABLE}` SET status = 'superseded', modified = %s, modified_by = %s WHERE alias_name = %s AND status = 'active'", (now, actor, release.alias_name))
		frappe.db.sql(
			f"UPDATE `{RELEASE_TABLE}` SET status = 'active', previous_collection = %s, vector_size = %s, validation_json = %s, published_by = %s, published_at = %s, modified = %s, modified_by = %s WHERE release_code = %s",
			(switch.get("previous_collection"), switch.get("vector_size"), frappe.as_json(validation), actor, now, now, actor, release.release_code),
		)
		response = {"release_code": release.release_code, "status": "active", "alias_name": release.alias_name, "collection_name": release.collection_name, "previous_collection": switch.get("previous_collection")}
		_record_audit(actor=actor, action="publish_vector_release", object_type="vector_release", object_name=release.release_code, parameters={}, result=response, reason=resolved_reason, priority="critical")
		return {"status": "success", "message": _("AI 向量版本已原子切换发布。"), "data": response}

	return run_idempotent("publish_ai_vector_release_v1", request_id, _publish, request_payload={"release_code": release_code, "reason": resolved_reason})


def rollback_ai_vector_release_v1(*, target_release_code: str, reason: str, request_id: str | None = None) -> dict:
	actor = _require_system_manager()
	_ensure_tables()
	resolved_reason = _normalize_text(reason, max_length=1000)
	if not resolved_reason:
		frappe.throw(_("回滚向量版本必须填写原因。"))

	def _rollback():
		target = _get_release(target_release_code, for_update=True)
		if target.status not in {"active", "superseded"}:
			frappe.throw(_("只能回滚到已发布且仍保留的向量版本。"))
		current_rows = frappe.db.sql(f"SELECT * FROM `{RELEASE_TABLE}` WHERE alias_name = %s AND status = 'active' LIMIT 1 FOR UPDATE", (target.alias_name,), as_dict=True)
		current = current_rows[0] if current_rows else None
		if current and current.release_code == target.release_code:
			return {"status": "success", "message": _("目标向量版本已是当前版本。"), "data": {"release_code": target.release_code, "status": "active"}}
		switch = _call_orchestrator(
			"/internal/v1/vector/governance/switch-alias",
			payload={"alias_name": target.alias_name, "target_collection": target.collection_name}, method="POST",
		)
		now = now_datetime()
		if current:
			frappe.db.sql(f"UPDATE `{RELEASE_TABLE}` SET status = 'superseded', modified = %s, modified_by = %s WHERE release_code = %s", (now, actor, current.release_code))
		frappe.db.sql(
			f"UPDATE `{RELEASE_TABLE}` SET status = 'active', rollback_from_release = %s, previous_collection = %s, published_by = %s, published_at = %s, modified = %s, modified_by = %s WHERE release_code = %s",
			(current.release_code if current else None, switch.get("previous_collection"), actor, now, now, actor, target.release_code),
		)
		response = {"release_code": target.release_code, "status": "active", "rolled_back_from": current.release_code if current else None, "collection_name": target.collection_name}
		_record_audit(actor=actor, action="rollback_vector_release", object_type="vector_release", object_name=target.release_code, parameters={}, result=response, reason=resolved_reason, priority="critical")
		return {"status": "success", "message": _("AI 向量版本已回滚。"), "data": response}

	return run_idempotent("rollback_ai_vector_release_v1", request_id, _rollback, request_payload={"target_release_code": target_release_code, "reason": resolved_reason})
