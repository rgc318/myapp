"""Owner-scoped immutable lifecycle plans with human-confirmed execution.

Execution owns the request transaction: callers must not catch failures and commit
unrelated writes. Full rollback also clears Frappe's queued after-commit hooks.
"""

import json
import secrets
from datetime import timedelta

import frappe
from frappe.utils import get_datetime, now_datetime

from myapp.services.data_permission_service import current_user, require_document_permission
from myapp.services.product_lifecycle_service import preview_product_lifecycle

TABLE = "tabMyApp Product Lifecycle Plan"


def _lock_deletion_dependencies(codes):
	"""Current-read cascade dependencies before native Item.on_trash can remove them.

	On MariaDB/InnoDB REPEATABLE READ, empty predicates retain gap locks until
	commit. This covers native cascade tables, not every third-party raw SQL writer.
	"""
	for code in sorted(codes):
		for table, predicate, values in (
			("tabStock Ledger Entry", "item_code=%s", (code,)),
			("tabBin", "item_code=%s", (code,)),
			("tabItem Price", "item_code=%s", (code,)),
			("tabItem", "variant_of=%s", (code,)),
			("tabFile", "attached_to_doctype=%s AND attached_to_name=%s", ("Item", code)),
		):
			if frappe.db.sql(f"SELECT name FROM `{table}` WHERE {predicate} LIMIT 1 FOR UPDATE", values):
				raise frappe.ValidationError("商品存在关联记录，整批删除取消，请重新预检。")


def _dump(value):
	return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _read_plan(plan_id, *, lock=False):
	if not isinstance(plan_id, str) or not plan_id.strip():
		raise frappe.ValidationError("操作计划不能为空。")
	rows = frappe.db.sql(
		f"SELECT * FROM `{TABLE}` WHERE name=%s AND owner=%s" + (" FOR UPDATE" if lock else ""),
		(plan_id, current_user()), as_dict=True,
	)
	if not rows:
		raise frappe.PermissionError("操作计划不存在或无权访问。")
	return rows[0]


def get_product_lifecycle_plan(plan_id):
	row = _read_plan(plan_id)
	return {
		"name": row.name, "version": row.version_no,
		"expires_in_seconds": max(0, int((get_datetime(row.expires_at) - now_datetime()).total_seconds())),
		"status": "expired" if row.status == "pending" and get_datetime(row.expires_at) <= now_datetime() else row.status,
		"expires_at": str(row.expires_at), "preview": json.loads(row.preview_json),
		"receipt": json.loads(row.receipt_json) if row.receipt_json else None,
	}


def _persist_preview(preview):
	name = "PRODUCT-PLAN-" + secrets.token_hex(16)
	now = now_datetime()
	frappe.db.sql(
		f"""INSERT INTO `{TABLE}`
		(name, owner, creation, expires_at, status, version_no, preview_json)
		VALUES (%s, %s, %s, %s, 'pending', 1, %s)""",
		(name, current_user(), now, now + timedelta(minutes=15), _dump(preview)),
	)
	return get_product_lifecycle_plan(name)


def create_product_lifecycle_plan(operation, item_codes, reason, *, source=None, preserve_codes=None):
	if preserve_codes and (not isinstance(preserve_codes, list) or len(preserve_codes) > 20
		or any(not isinstance(code, str) or not code.strip() for code in preserve_codes)
		or len(set(preserve_codes)) != len(preserve_codes)):
		raise frappe.ValidationError("保留目标重复或不完整，请重新确认。")
	preview = preview_product_lifecycle(operation, item_codes, reason)
	preview["execution_available"] = preview["preflight_passed"]
	preview["source"] = source or {}
	preview["preserve_targets"] = []
	for code in preserve_codes or []:
		if code in item_codes:
			raise frappe.ValidationError("操作目标和保留目标冲突，请重新明确要求。")
		item = require_document_permission("Item", code, "read")
		preview["preserve_targets"].append({"item_code": item.name, "item_name": item.item_name})
	return _persist_preview(preview)


def list_product_lifecycle_plans(limit=20):
	limit = max(1, min(int(limit), 50))
	rows = frappe.db.sql(f"SELECT name FROM `{TABLE}` WHERE owner=%s ORDER BY creation DESC LIMIT %s",
		(current_user(), limit), as_dict=True)
	return [get_product_lifecycle_plan(row.name) for row in rows]


def discard_product_lifecycle_plan(plan_id):
	row = _read_plan(plan_id, lock=True)
	if row.status == "pending":
		frappe.db.sql(f"UPDATE `{TABLE}` SET status='discarded' WHERE name=%s AND owner=%s",
			(row.name, current_user()))
	return get_product_lifecycle_plan(plan_id)


def execute_product_lifecycle_plan(plan_id, expected_version, *, confirmed=False,
	shared_scope_confirmed=False, deletion_confirmed=False, request_id=None):
	"""Execute lifecycle changes atomically through native Item lifecycle methods.

	Confirmation is explicit boolean true, never truthiness of browser strings.
	Replay is tied to the owner, immutable plan/version and same request ID.
	"""
	if confirmed is not True or shared_scope_confirmed is not True:
		raise frappe.ValidationError("请明确确认全部目标及共享主档影响范围。")
	if type(expected_version) is not int or expected_version != 1:
		raise frappe.ValidationError("操作计划版本不匹配，请重新预检。")
	if not isinstance(request_id, str) or not request_id.strip() or len(request_id.strip()) > 140:
		raise frappe.ValidationError("请提供有效的幂等请求号。")
	request_id = request_id.strip()
	try:
		plan = _read_plan(plan_id, lock=True)
		if plan.version_no != expected_version:
			raise frappe.ValidationError("操作计划版本已变化。")
		if plan.status == "completed":
			if plan.request_id != request_id:
				raise frappe.ValidationError("计划已由其他请求执行，请读取原回执。")
			return {"receipt": json.loads(plan.receipt_json), "replayed": True}
		if plan.status != "pending" or get_datetime(plan.expires_at) <= now_datetime():
			raise frappe.ValidationError("操作计划已失效，请重新预检。")
		preview = json.loads(plan.preview_json)
		operation = preview["operation"]
		if operation == "delete" and deletion_confirmed is not True:
			raise frappe.ValidationError("请单独确认删除风险；删除不会替换为停用。")
		if not preview.get("execution_available", preview.get("preflight_passed")) or preview.get("resolution_groups"):
			raise frappe.ValidationError("计划目标尚未确认或预检未通过，请重新生成计划。")
		targets = preview["targets"]
		codes = [row["item_code"] for row in targets]
		before = {row["item_code"]: row for row in targets}
		# Stable lock order avoids opposite-order batches deadlocking each other.
		for code in sorted(codes):
			locked = frappe.db.sql("SELECT name, modified FROM `tabItem` WHERE name=%s FOR UPDATE", (code,))
			if not locked:
				raise frappe.ValidationError("目标商品已不存在，请重新预检。")
			if get_datetime(locked[0][1]) != get_datetime(before[code]["item_modified"]):
				raise frappe.ValidationError("商品已变化，请重新预检并确认。")
		if operation == "delete":
			_lock_deletion_dependencies(codes)
		fresh = preview_product_lifecycle(operation, codes, preview["reason"])
		for row in fresh["targets"]:
			if get_datetime(row["item_modified"]) != get_datetime(before[row["item_code"]]["item_modified"]):
				raise frappe.ValidationError("商品已变化，请重新预检并确认。")
		if not fresh["preflight_passed"]:
			raise frappe.ValidationError("最新预检未通过，整批操作取消。")
		results = []
		for row in fresh["targets"]:
			item = require_document_permission("Item", row["item_code"], "delete" if operation == "delete" else "write")
			if operation == "delete":
				# Preserve native permission, link checks, Deleted Document and hooks.
				# Attachment/image blockers avoid non-transactional file cleanup.
				frappe.delete_doc("Item", item.name, ignore_missing=False)
			elif not row["already_in_requested_state"]:
				# Same Item.save path as disable_product_v2, without nesting its
				# request-wide idempotency or committing a partial batch receipt.
				item.disabled = int(operation == "disable")
				item.save()
			results.append({**row, "deleted": operation == "delete",
				"disabled_after": None if operation == "delete" else operation == "disable",
				"modified_after": None if operation == "delete" else str(item.modified)})
		receipt = {"plan_id": plan.name, "version": expected_version, "request_id": request_id,
			"operation": operation, "reason": preview["reason"], "scope": "shared_item_master",
			"executed_by": current_user(), "executed_at": str(now_datetime()), "targets": results}
		frappe.db.sql(
			f"""UPDATE `{TABLE}` SET status='completed', request_id=%s, receipt_json=%s,
			executed_at=%s WHERE name=%s AND owner=%s""",
			(request_id, _dump(receipt), receipt["executed_at"], plan.name, current_user()),
		)
		return {"receipt": receipt, "replayed": False}
	except frappe.LinkExistsError:
		frappe.db.rollback()
		frappe.clear_last_message()
		raise frappe.ValidationError("商品新增了关联记录，整批操作取消，请重新预检。") from None
	except Exception:
		frappe.db.rollback()
		raise
