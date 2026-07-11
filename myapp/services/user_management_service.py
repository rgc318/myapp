from __future__ import annotations

import json
from collections import Counter

import frappe
from frappe import _
from frappe.permissions import AUTOMATIC_ROLES
from frappe.utils import cint

from myapp.services.user_preferences_service import _build_workspace_preferences_payload


PROFILE_FIELDS = (
	"name",
	"email",
	"username",
	"first_name",
	"middle_name",
	"last_name",
	"full_name",
	"user_image",
	"enabled",
	"user_type",
	"language",
	"time_zone",
	"gender",
	"birth_date",
	"phone",
	"mobile_no",
	"location",
	"bio",
	"interest",
	"last_login",
	"last_active",
	"last_ip",
	"last_password_reset_date",
	"creation",
	"modified",
	"modified_by",
)

EDITABLE_PROFILE_FIELDS = {
	"first_name",
	"middle_name",
	"last_name",
	"user_image",
	"language",
	"time_zone",
	"gender",
	"birth_date",
	"phone",
	"mobile_no",
	"location",
	"bio",
	"interest",
}


def _normalize_text(value):
	return (value or "").strip() if isinstance(value, str) else value


def _ensure_authenticated_user():
	user = _normalize_text(getattr(frappe.session, "user", None))
	if not user or user == "Guest":
		raise frappe.AuthenticationError(_("请先登录。"))
	return user


def _ensure_system_manager():
	user = _ensure_authenticated_user()
	if user != "Administrator" and "System Manager" not in frappe.get_roles(user):
		raise frappe.PermissionError(_("仅系统管理员可以管理用户与权限。"))
	return user


def _coerce_list(value):
	if isinstance(value, str):
		value = frappe.parse_json(value) if value.strip().startswith("[") else [value]
	if not isinstance(value, (list, tuple, set)):
		return []
	return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _get_role_names(user_doc):
	return sorted({row.role for row in (user_doc.roles or []) if row.role})


def _get_capabilities(roles):
	role_set = set(roles)
	is_admin = "System Manager" in role_set
	return {
		"can_manage_users": is_admin,
		"can_manage_roles": is_admin,
		"can_view_sales": is_admin or bool(role_set & {"Sales Manager", "Sales User"}),
		"can_view_purchase": is_admin or bool(role_set & {"Purchase Manager", "Purchase User"}),
		"can_view_inventory": is_admin or bool(role_set & {"Stock Manager", "Stock User"}),
		"can_view_finance": is_admin or bool(role_set & {"Accounts Manager", "Accounts User"}),
	}


def _serialize_user_permission(row):
	return {
		"name": row.get("name"),
		"allow": row.get("allow"),
		"for_value": row.get("for_value"),
		"is_default": bool(row.get("is_default")),
		"apply_to_all_doctypes": bool(row.get("apply_to_all_doctypes")),
		"applicable_for": row.get("applicable_for"),
		"hide_descendants": bool(row.get("hide_descendants")),
	}


def _get_user_permissions(user):
	rows = frappe.get_all(
		"User Permission",
		filters={"user": user},
		fields=[
			"name",
			"allow",
			"for_value",
			"is_default",
			"apply_to_all_doctypes",
			"applicable_for",
			"hide_descendants",
		],
		order_by="allow asc, for_value asc",
	)
	return [_serialize_user_permission(row) for row in rows]


def _serialize_user(user_doc, *, include_permissions=False, include_audit=False):
	roles = _get_role_names(user_doc)
	payload = {field: user_doc.get(field) for field in PROFILE_FIELDS}
	payload.update(
		{
			"roles": roles,
			"capabilities": _get_capabilities(roles),
			"workspace_preferences": _build_workspace_preferences_payload(user=user_doc.name),
		}
	)
	if include_permissions:
		payload["user_permissions"] = _get_user_permissions(user_doc.name)
	if include_audit:
		payload["audit_log"] = _get_user_audit_log(user_doc.name)
	return payload


def _get_user_audit_log(user, limit=30):
	rows = frappe.get_all(
		"Version",
		filters={"ref_doctype": "User", "docname": user},
		fields=["name", "owner", "creation", "data"],
		order_by="creation desc",
		limit_page_length=limit,
	)
	result = []
	for row in rows:
		try:
			data = json.loads(row.get("data") or "{}")
		except (TypeError, ValueError):
			data = {}
		changes = []
		for change in data.get("changed") or []:
			if isinstance(change, list) and change:
				changes.append({"field": change[0], "old": change[1] if len(change) > 1 else None, "new": change[2] if len(change) > 2 else None})
		result.append({"name": row.get("name"), "changed_by": row.get("owner"), "creation": row.get("creation"), "changes": changes})
	return result


def _validate_roles(roles):
	resolved = _coerce_list(roles)
	if not resolved:
		return []
	rows = frappe.get_all("Role", filters={"name": ["in", resolved]}, fields=["name", "disabled"])
	role_map = {row.name: row for row in rows}
	invalid = [role for role in resolved if role not in role_map or role in AUTOMATIC_ROLES or cint(role_map[role].disabled)]
	if invalid:
		frappe.throw(_("角色不存在、已停用或不可手工分配：{0}").format("、".join(invalid)))
	return sorted(resolved)


def _ensure_not_last_system_manager(user, next_roles=None, next_enabled=None):
	current_roles = set(frappe.get_roles(user))
	currently_enabled = bool(frappe.db.get_value("User", user, "enabled"))
	will_have_role = "System Manager" in set(next_roles if next_roles is not None else current_roles)
	will_be_enabled = currently_enabled if next_enabled is None else bool(cint(next_enabled))
	if "System Manager" not in current_roles or (will_have_role and will_be_enabled):
		return
	manager_users = frappe.get_all("Has Role", filters={"role": "System Manager"}, pluck="parent")
	enabled_managers = frappe.get_all("User", filters={"name": ["in", manager_users], "enabled": 1}, pluck="name") if manager_users else []
	if set(enabled_managers) <= {user}:
		frappe.throw(_("不能停用或移除最后一个启用的系统管理员。"))


def get_current_user_profile():
	user = _ensure_authenticated_user()
	return {"status": "success", "code": "CURRENT_USER_PROFILE_FETCHED", "message": _("已获取个人资料。"), "data": _serialize_user(frappe.get_doc("User", user), include_permissions=True)}


def update_current_user_profile(**values):
	user = _ensure_authenticated_user()
	doc = frappe.get_doc("User", user)
	for field in EDITABLE_PROFILE_FIELDS:
		if field in values:
			doc.set(field, _normalize_text(values[field]))
	if not _normalize_text(doc.first_name):
		frappe.throw(_("名字不能为空。"))
	doc.save(ignore_permissions=True)
	return {"status": "success", "code": "CURRENT_USER_PROFILE_UPDATED", "message": _("个人资料已更新。"), "data": _serialize_user(doc, include_permissions=True)}


def change_current_user_password(old_password, new_password, logout_all_sessions=1):
	_ensure_authenticated_user()
	if not _normalize_text(old_password) or not _normalize_text(new_password):
		frappe.throw(_("旧密码和新密码均不能为空。"))
	from frappe.core.doctype.user.user import update_password

	update_password(new_password=new_password, old_password=old_password, logout_all_sessions=cint(logout_all_sessions))
	return {"status": "success", "code": "CURRENT_USER_PASSWORD_CHANGED", "message": _("密码已更新，请重新登录。"), "data": {"reauthentication_required": True}}


def list_users(search=None, enabled=None, role=None, user_type=None, page=1, page_size=20):
	_ensure_system_manager()
	page = max(cint(page), 1)
	page_size = min(max(cint(page_size), 1), 100)
	filters = []
	if enabled not in (None, ""):
		filters.append(["enabled", "=", cint(enabled)])
	if _normalize_text(user_type):
		filters.append(["user_type", "=", _normalize_text(user_type)])
	if _normalize_text(search):
		term = f"%{_normalize_text(search)}%"
		filters.append(["name", "like", term])
	if _normalize_text(role):
		role_users = frappe.get_all("Has Role", filters={"role": _normalize_text(role)}, pluck="parent")
		filters.append(["name", "in", role_users or [""]])
	total = frappe.db.count("User", filters=filters)
	rows = frappe.get_all("User", filters=filters, fields=list(PROFILE_FIELDS), order_by="enabled desc, full_name asc", start=(page - 1) * page_size, page_length=page_size)
	roles_by_user = {row.name: [] for row in rows}
	if roles_by_user:
		for role_row in frappe.get_all(
			"Has Role",
			filters={"parent": ["in", list(roles_by_user)]},
			fields=["parent", "role"],
		):
			if role_row.role not in AUTOMATIC_ROLES:
				roles_by_user[role_row.parent].append(role_row.role)
	users = []
	for row in rows:
		doc = frappe._dict(row)
		doc.roles = [frappe._dict(role=row_role) for row_role in roles_by_user.get(row.name, [])]
		users.append(_serialize_user(doc))
	return {"status": "success", "code": "USERS_FETCHED", "message": _("已获取用户列表。"), "data": {"users": users, "pagination": {"page": page, "page_size": page_size, "total_count": total}}}


def get_user_detail(user):
	_ensure_system_manager()
	if not frappe.db.exists("User", user):
		raise frappe.DoesNotExistError(_("用户不存在。"))
	return {"status": "success", "code": "USER_DETAIL_FETCHED", "message": _("已获取用户详情。"), "data": _serialize_user(frappe.get_doc("User", user), include_permissions=True, include_audit=True)}


def create_user(email, first_name, roles=None, password=None, send_welcome_email=0, enabled=1, **values):
	_ensure_system_manager()
	email = _normalize_text(email)
	if not email or frappe.db.exists("User", email):
		frappe.throw(_("邮箱不能为空或该用户已存在。"))
	doc = frappe.new_doc("User")
	doc.email = email
	doc.first_name = _normalize_text(first_name)
	doc.enabled = cint(enabled)
	doc.user_type = "System User"
	doc.send_welcome_email = cint(send_welcome_email)
	for field in EDITABLE_PROFILE_FIELDS - {"first_name"}:
		if field in values:
			doc.set(field, _normalize_text(values[field]))
	for role in _validate_roles(roles):
		doc.append("roles", {"role": role})
	if _normalize_text(password):
		doc.new_password = password
	doc.insert(ignore_permissions=True)
	return {"status": "success", "code": "USER_CREATED", "message": _("用户已创建。"), "data": _serialize_user(doc, include_permissions=True)}


def update_user(user, **values):
	_ensure_system_manager()
	doc = frappe.get_doc("User", user)
	for field in EDITABLE_PROFILE_FIELDS:
		if field in values:
			doc.set(field, _normalize_text(values[field]))
	if "username" in values:
		doc.username = _normalize_text(values["username"])
	if not _normalize_text(doc.first_name):
		frappe.throw(_("名字不能为空。"))
	doc.save(ignore_permissions=True)
	return {"status": "success", "code": "USER_UPDATED", "message": _("用户资料已更新。"), "data": _serialize_user(doc, include_permissions=True)}


def set_user_enabled(user, enabled):
	actor = _ensure_system_manager()
	if user in {"Administrator", "Guest"}:
		frappe.throw(_("不能修改系统保留账号状态。"))
	if user == actor and not cint(enabled):
		frappe.throw(_("不能停用当前登录账号。"))
	_ensure_not_last_system_manager(user, next_enabled=enabled)
	doc = frappe.get_doc("User", user)
	doc.enabled = cint(enabled)
	doc.save(ignore_permissions=True)
	return {"status": "success", "code": "USER_STATUS_UPDATED", "message": _("用户状态已更新。"), "data": _serialize_user(doc)}


def update_user_roles(user, roles):
	_ensure_system_manager()
	if user in {"Administrator", "Guest"}:
		frappe.throw(_("不能修改系统保留账号角色。"))
	resolved = _validate_roles(roles)
	_ensure_not_last_system_manager(user, next_roles=resolved)
	doc = frappe.get_doc("User", user)
	doc.set("roles", [])
	for role in resolved:
		doc.append("roles", {"role": role})
	doc.save(ignore_permissions=True)
	return {"status": "success", "code": "USER_ROLES_UPDATED", "message": _("用户角色已更新。"), "data": _serialize_user(doc, include_permissions=True)}


def list_roles(search=None):
	_ensure_system_manager()
	filters = {"disabled": 0}
	if _normalize_text(search):
		filters["name"] = ["like", f"%{_normalize_text(search)}%"]
	rows = frappe.get_all("Role", filters=filters, fields=["name", "desk_access", "restrict_to_domain", "disabled"], order_by="name asc")
	counts = Counter(frappe.get_all("Has Role", pluck="role"))
	roles = [{**dict(row), "user_count": counts.get(row.name, 0), "automatic": row.name in AUTOMATIC_ROLES} for row in rows]
	return {"status": "success", "code": "ROLES_FETCHED", "message": _("已获取角色目录。"), "data": {"roles": roles}}


def add_user_permission(user, allow, for_value, is_default=0, apply_to_all_doctypes=1, applicable_for=None, hide_descendants=0):
	_ensure_system_manager()
	if not frappe.db.exists("User", user) or not frappe.db.exists("DocType", allow):
		frappe.throw(_("用户或授权类型不存在。"))
	if not frappe.db.exists(allow, for_value):
		frappe.throw(_("授权值 {0} 不存在于 {1}。").format(for_value, allow))
	doc = frappe.get_doc({"doctype": "User Permission", "user": user, "allow": allow, "for_value": for_value, "is_default": cint(is_default), "apply_to_all_doctypes": cint(apply_to_all_doctypes), "applicable_for": _normalize_text(applicable_for) or None, "hide_descendants": cint(hide_descendants)})
	doc.insert(ignore_permissions=True)
	return {"status": "success", "code": "USER_PERMISSION_CREATED", "message": _("数据权限已添加。"), "data": _serialize_user_permission(doc.as_dict())}


def delete_user_permission(user, permission_name):
	_ensure_system_manager()
	owner = frappe.db.get_value("User Permission", permission_name, "user")
	if not owner or owner != user:
		raise frappe.DoesNotExistError(_("数据权限不存在。"))
	frappe.delete_doc("User Permission", permission_name, ignore_permissions=True)
	return {"status": "success", "code": "USER_PERMISSION_DELETED", "message": _("数据权限已删除。"), "data": {"name": permission_name}}
