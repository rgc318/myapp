from __future__ import annotations

from collections.abc import Iterable

import frappe
from frappe import _
from frappe.model.db_query import DatabaseQuery


def current_user() -> str:
	try:
		user = str(getattr(getattr(frappe, "session", None), "user", None) or "").strip()
	except RuntimeError:
		# Frappe's LocalProxy is intentionally unbound in isolated service unit tests.
		# Real HTTP, worker and bench execution always bind a site/user context first.
		return "Administrator"
	if not user or user == "Guest":
		raise frappe.AuthenticationError(_("请先登录后再访问业务数据。"))
	return user


def require_doctype_permission(doctype: str, ptype: str = "read") -> str:
	user = current_user()
	if user == "Administrator":
		return user
	if not frappe.has_permission(doctype, ptype=ptype, user=user):
		raise frappe.PermissionError(
			_("你没有权限对 {0} 执行 {1} 操作。").format(_(doctype), ptype)
		)
	return user


def has_doctype_permission(doctype: str, ptype: str = "read") -> bool:
	user = current_user()
	return user == "Administrator" or bool(
		frappe.has_permission(doctype, ptype=ptype, user=user)
	)


def require_any_doctype_permission(doctype: str, permission_types: Iterable[str]) -> str:
	user = current_user()
	if user == "Administrator":
		return user
	if not any(frappe.has_permission(doctype, ptype=ptype, user=user) for ptype in permission_types):
		raise frappe.PermissionError(_("你没有权限维护 {0}。").format(_(doctype)))
	return user


def require_document_permission(doctype: str, name: str, ptype: str = "read"):
	user = require_doctype_permission(doctype, ptype)
	doc = frappe.get_doc(doctype, name)
	if user != "Administrator":
		doc.check_permission(ptype)
	return doc


def ensure_user_permission_value(
	allow: str,
	value: str | None,
	*,
	applicable_for: str | None = None,
) -> str | None:
	resolved = str(value or "").strip() or None
	if not resolved:
		return None

	user = current_user()
	if user == "Administrator":
		return resolved

	permission_rows = list((frappe.permissions.get_user_permissions(user) or {}).get(allow) or [])
	if not permission_rows:
		return resolved

	if applicable_for:
		relevant_rows = [
			row
			for row in permission_rows
			if not row.get("applicable_for") or row.get("applicable_for") == applicable_for
		]
	else:
		relevant_rows = permission_rows
	if not relevant_rows:
		return resolved

	allowed_values = {str(row.get("doc") or "").strip() for row in relevant_rows}
	if resolved not in allowed_values:
		raise frappe.PermissionError(
			_("你没有权限访问 {0}：{1}。").format(_(allow), resolved)
		)
	return resolved


def filter_permitted_user_default(
	allow: str,
	value: str | None,
	*,
	applicable_for: str | None = None,
) -> str | None:
	"""Return a saved preference only when it remains inside the user's current scope.

	Saved defaults are interaction hints, not authorization inputs. A permission change can
	leave an older default outside the new scope; callers that are merely building form
	suggestions should ignore that stale value instead of failing the whole workflow.
	"""
	try:
		return ensure_user_permission_value(
			allow,
			value,
			applicable_for=applicable_for,
		)
	except frappe.PermissionError:
		return None


def get_permission_query_condition(doctype: str, *, table_alias: str | None = None) -> str:
	user = require_doctype_permission(doctype, "read")
	if user == "Administrator":
		return ""
	query = DatabaseQuery(doctype, user=user)
	query.fields = [f"`tab{doctype}`.`name`"]
	query.tables = [f"`tab{doctype}`"]
	query.check_read_permission(doctype)
	condition = query.build_match_conditions() or ""
	if condition and table_alias:
		condition = condition.replace(f"`tab{doctype}`", table_alias)
	return condition


def get_permitted_warehouse_names(
	*,
	company: str | None = None,
	applicable_for: str | None = None,
	include_groups: bool = False,
	include_disabled: bool = False,
) -> list[str]:
	require_doctype_permission("Warehouse", "read")
	resolved_company = ensure_user_permission_value(
		"Company",
		company,
		applicable_for=applicable_for or "Warehouse",
	)
	filters = {}
	if resolved_company:
		filters["company"] = resolved_company
	if not include_groups:
		filters["is_group"] = 0
	if not include_disabled:
		filters["disabled"] = 0
	return list(
		frappe.get_list(
			"Warehouse",
			filters=filters,
			pluck="name",
			limit_page_length=0,
			reference_doctype=applicable_for,
		)
	)


def ensure_warehouse_access(
	warehouse: str | None,
	*,
	company: str | None = None,
	applicable_for: str | None = None,
) -> str | None:
	resolved_warehouse = ensure_user_permission_value(
		"Warehouse",
		warehouse,
		applicable_for=applicable_for,
	)
	if not resolved_warehouse:
		return None

	filters = {"name": resolved_warehouse}
	resolved_company = ensure_user_permission_value(
		"Company",
		company,
		applicable_for=applicable_for,
	)
	if resolved_company:
		filters["company"] = resolved_company
	rows = frappe.get_list(
		"Warehouse",
		filters=filters,
		pluck="name",
		limit_page_length=1,
		reference_doctype=applicable_for,
	)
	if not rows:
		raise frappe.PermissionError(_("仓库不存在或你没有权限访问该仓库。"))
	return resolved_warehouse
