import json
import secrets

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from myapp.services.data_permission_service import require_document_permission


CORRECTION_DOCTYPE = "MyApp Product Correction"
CORRECTION_TABLE = f"tab{CORRECTION_DOCTYPE}"


def _normalize_text(value):
	return str(value or "").strip()


def _table_exists():
	try:
		return bool(frappe.db.table_exists(CORRECTION_DOCTYPE))
	except Exception:
		return False


def _json_dump(value):
	return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, default=str)


def record_product_correction(
	*,
	source_item: str,
	target_item: str | None,
	correction_type: str,
	reason: str | None,
	source_modified_before,
	target_modified_after,
	before_snapshot: dict,
	after_snapshot: dict,
	metadata: dict | None,
	request_id: str | None,
):
	if not _table_exists():
		frappe.throw(_("商品纠正审计表尚未初始化，请先执行站点迁移。"))
	resolved_request_id = _normalize_text(request_id) or None
	if resolved_request_id:
		existing = frappe.db.get_value(CORRECTION_DOCTYPE, {"request_id": resolved_request_id}, "name")
		if existing:
			return existing

	now = now_datetime()
	user = frappe.session.user
	name = f"PRODUCT-CORRECTION-{secrets.token_hex(16)}"
	frappe.db.sql(
		f"""
		INSERT INTO `{CORRECTION_TABLE}` (
			name, creation, modified, modified_by, owner, docstatus, idx,
			source_item, target_item, correction_type, status, reason,
			source_modified_before, target_modified_after,
			before_snapshot_json, after_snapshot_json, metadata_json,
			request_id, executed_by, executed_at
		) VALUES (
			%(name)s, %(now)s, %(now)s, %(user)s, %(user)s, 0, 0,
			%(source_item)s, %(target_item)s, %(correction_type)s, 'completed', %(reason)s,
			%(source_modified_before)s, %(target_modified_after)s,
			%(before_snapshot_json)s, %(after_snapshot_json)s, %(metadata_json)s,
			%(request_id)s, %(user)s, %(now)s
		)
		""",
		{
			"name": name,
			"now": now,
			"user": user,
			"source_item": source_item,
			"target_item": target_item,
			"correction_type": correction_type,
			"reason": _normalize_text(reason) or None,
			"source_modified_before": source_modified_before,
			"target_modified_after": target_modified_after,
			"before_snapshot_json": _json_dump(before_snapshot),
			"after_snapshot_json": _json_dump(after_snapshot),
			"metadata_json": _json_dump(metadata),
			"request_id": resolved_request_id,
		},
	)
	return name


def list_product_corrections_for_history(item_code: str, *, limit: int = 100):
	resolved_item_code = _normalize_text(item_code)
	if not resolved_item_code or not _table_exists():
		return []
	resolved_limit = max(1, min(cint(limit or 100), 500))
	return frappe.db.sql(
		f"""
		SELECT
			name, creation, owner, modified_by, source_item, target_item,
			correction_type, status, reason, executed_by, executed_at
		FROM `{CORRECTION_TABLE}`
		WHERE source_item = %(item_code)s OR target_item = %(item_code)s
		ORDER BY creation DESC
		LIMIT %(limit)s
		""",
		{"item_code": resolved_item_code, "limit": resolved_limit},
		as_dict=True,
	)


def _latest_recorded_replacement(item_code: str):
	if not _table_exists():
		return None
	rows = frappe.db.sql(
		f"""
		SELECT name, target_item
		FROM `{CORRECTION_TABLE}`
		WHERE source_item = %s
			AND correction_type = 'replacement'
			AND status = 'completed'
			AND target_item IS NOT NULL
		ORDER BY creation DESC
		LIMIT 1
		""",
		(item_code,),
		as_dict=True,
	)
	return rows[0] if rows else None


def _legacy_replacement(item_code: str):
	if not cint(frappe.db.get_value("Item", item_code, "disabled") or 0):
		return None
	rows = frappe.get_list(
		"Item Alternative",
		filters={"item_code": item_code, "two_way": 0},
		fields=["name", "alternative_item_code"],
		limit_page_length=10,
	)
	active = []
	for row in rows:
		target = _normalize_text(row.alternative_item_code)
		if target and frappe.db.exists("Item", target) and not cint(
			frappe.db.get_value("Item", target, "disabled") or 0
		):
			active.append({"name": row.name, "target_item": target})
	return active[0] if len(active) == 1 else None


def resolve_active_product_reference(item_code: str, *, check_permission: bool = True):
	requested = _normalize_text(item_code)
	if not requested:
		frappe.throw(_("商品编码不能为空。"))
	if check_permission:
		require_document_permission("Item", requested, "read")
	elif not frappe.db.exists("Item", requested):
		frappe.throw(_("商品 {0} 不存在。").format(requested))

	current = requested
	chain = []
	visited = set()
	resolution_source = None
	requires_confirmation = False
	for _index in range(10):
		if current in visited:
			frappe.throw(_("商品替代关系存在循环，无法确定当前有效商品。"))
		visited.add(current)
		replacement = _latest_recorded_replacement(current)
		if replacement:
			target = _normalize_text(replacement.get("target_item"))
			source = "correction_record"
		else:
			replacement = _legacy_replacement(current)
			target = _normalize_text((replacement or {}).get("target_item"))
			source = "legacy_item_alternative"
		if not target:
			break
		chain.append({"source_item": current, "target_item": target, "source": source})
		current = target
		resolution_source = source
		requires_confirmation = True

	if check_permission and current != requested:
		require_document_permission("Item", current, "read")
	return {
		"requested_item_code": requested,
		"active_item_code": current,
		"changed": current != requested,
		"active_disabled": bool(cint(frappe.db.get_value("Item", current, "disabled") or 0)),
		"resolution_source": resolution_source,
		"requires_confirmation": requires_confirmation,
		"chain": chain,
	}


def resolve_active_product_v1(item_code: str):
	return {
		"status": "success",
		"data": resolve_active_product_reference(item_code),
	}
