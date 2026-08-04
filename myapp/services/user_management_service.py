from __future__ import annotations

import json
from collections import Counter, defaultdict

import frappe
from frappe import _
from frappe.permissions import AUTOMATIC_ROLES
from frappe.query_builder import Order
from frappe.utils import cint, sha256_hash
from frappe.utils.file_manager import save_file

from myapp.auth.jwt_service import (
	count_user_refresh_tokens,
	get_user_auth_generation,
	revoke_all_user_tokens,
)
from myapp.services.media_service import (
	_decode_base64_file_content,
	_ensure_folder_path,
	_normalize_image_filename,
	_validate_image_content_type,
)
from myapp.utils.image_processing import USER_AVATAR_PROFILE, normalize_image_upload
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

USER_AVATAR_FOLDER = "Home/Attachments/MyApp User Avatars"
PERMISSION_SNAPSHOT_DOCTYPES = (
	"User",
	"Item",
	"Customer",
	"Supplier",
	"Sales Order",
	"Delivery Note",
	"Sales Invoice",
	"Purchase Order",
	"Purchase Receipt",
	"Purchase Invoice",
	"Payment Entry",
	"Warehouse",
	"Stock Entry",
)


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


def _ensure_can_manage_user(user):
	actor = _ensure_authenticated_user()
	if actor == user or actor == "Administrator" or "System Manager" in frappe.get_roles(actor):
		return actor
	raise frappe.PermissionError(_("只能查看或管理本人安全信息。"))


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
	user = _ensure_authenticated_user()
	if not _normalize_text(old_password) or not _normalize_text(new_password):
		frappe.throw(_("旧密码和新密码均不能为空。"))
	from frappe.core.doctype.user.user import update_password

	update_password(new_password=new_password, old_password=old_password, logout_all_sessions=cint(logout_all_sessions))
	generation = revoke_all_user_tokens(user)
	return {"status": "success", "code": "CURRENT_USER_PASSWORD_CHANGED", "message": _("密码已更新，请重新登录。"), "data": {"reauthentication_required": True, "auth_generation": generation}}


def upload_current_user_avatar(filename, file_content_base64, content_type=None):
	user = _ensure_authenticated_user()
	resolved_filename = _normalize_image_filename(filename, content_type)
	_validate_image_content_type(resolved_filename, content_type)
	file_bytes = _decode_base64_file_content(file_content_base64)
	normalized_image = normalize_image_upload(
		filename=resolved_filename,
		content=file_bytes,
		profile=USER_AVATAR_PROFILE,
	)
	folder = _ensure_folder_path(USER_AVATAR_FOLDER)
	doc = frappe.get_doc("User", user)
	previous_url = _normalize_text(doc.user_image) or None
	file_doc = save_file(
		fname=normalized_image.filename,
		content=normalized_image.content,
		dt="User",
		dn=user,
		folder=folder,
		df="user_image",
		is_private=0,
	)
	doc.user_image = file_doc.file_url
	doc.save(ignore_permissions=True)
	if previous_url and previous_url != file_doc.file_url:
		previous_file = frappe.db.get_value(
			"File",
			{"file_url": previous_url, "attached_to_doctype": "User", "attached_to_name": user},
			"name",
		)
		if previous_file:
			frappe.delete_doc("File", previous_file, ignore_permissions=True, force=True)
	return {
		"status": "success",
		"code": "CURRENT_USER_AVATAR_UPDATED",
		"message": _("头像已更新。"),
		"data": {
			"file_url": file_doc.file_url,
			"file_id": file_doc.name,
			"file_name": file_doc.file_name,
			"content_type": normalized_image.content_type,
			"file_size": normalized_image.file_size,
			"width": normalized_image.width,
			"height": normalized_image.height,
			"profile": normalized_image.profile,
			"quality": normalized_image.quality,
			"source_width": normalized_image.source_width,
			"source_height": normalized_image.source_height,
			"source_format": normalized_image.source_format,
		},
	}


def _get_frappe_sessions(user):
	sessions = frappe.qb.DocType("Sessions")
	rows = (
		frappe.qb.from_(sessions)
		.select(sessions.sid, sessions.sessiondata, sessions.lastupdate)
		.where(sessions.user == user)
		.orderby(sessions.lastupdate, order=Order.desc)
	).run(as_dict=True)
	result = []
	for row in rows:
		try:
			data = frappe.parse_json(row.sessiondata or "{}")
		except Exception:
			data = frappe._dict()
		result.append(
			{
				"id": sha256_hash(row.sid),
				"ip_address": data.get("session_ip"),
				"user_agent": data.get("user_agent"),
				"session_created": data.get("creation"),
				"last_updated": data.get("last_updated") or row.lastupdate,
				"is_current": user == frappe.session.user and row.sid == getattr(frappe.session, "sid", None),
			}
		)
	return result


def get_user_security(user=None):
	resolved_user = _normalize_text(user) or _ensure_authenticated_user()
	_ensure_can_manage_user(resolved_user)
	if not frappe.db.exists("User", resolved_user):
		raise frappe.DoesNotExistError(_("用户不存在。"))
	from frappe.twofactor import two_factor_is_enabled

	user_row = frappe.db.get_value(
		"User",
		resolved_user,
		["restrict_ip", "simultaneous_sessions", "last_login", "last_active", "last_ip", "last_password_reset_date"],
		as_dict=True,
	) or {}
	sessions = _get_frappe_sessions(resolved_user)
	return {
		"status": "success",
		"code": "USER_SECURITY_FETCHED",
		"message": _("已获取账号安全信息。"),
		"data": {
			"user": resolved_user,
			"two_factor_enabled": bool(two_factor_is_enabled(resolved_user)),
			"two_factor_method": frappe.get_system_settings("two_factor_method"),
			"restrict_ip": user_row.get("restrict_ip"),
			"simultaneous_sessions": cint(user_row.get("simultaneous_sessions") or 1),
			"last_login": user_row.get("last_login"),
			"last_active": user_row.get("last_active"),
			"last_ip": user_row.get("last_ip"),
			"last_password_reset_date": user_row.get("last_password_reset_date"),
			"frappe_sessions": sessions,
			"frappe_session_count": len(sessions),
			"jwt_refresh_session_count": count_user_refresh_tokens(resolved_user),
			"auth_generation": get_user_auth_generation(resolved_user),
		},
	}


def revoke_user_sessions(user=None):
	resolved_user = _normalize_text(user) or _ensure_authenticated_user()
	actor = _ensure_can_manage_user(resolved_user)
	from frappe.sessions import clear_sessions

	clear_sessions(user=resolved_user, keep_current=False, force=True)
	generation = revoke_all_user_tokens(resolved_user)
	return {
		"status": "success",
		"code": "USER_SESSIONS_REVOKED",
		"message": _("该账号的所有会话已注销。"),
		"data": {
			"user": resolved_user,
			"revoked_by": actor,
			"auth_generation": generation,
			"reauthentication_required": actor == resolved_user,
		},
	}


def get_user_permission_snapshot(user):
	_ensure_system_manager()
	if not frappe.db.exists("User", user):
		raise frappe.DoesNotExistError(_("用户不存在。"))
	permissions = []
	for doctype in PERMISSION_SNAPSHOT_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		role_permissions = frappe.permissions.get_role_permissions(doctype, user=user)
		permissions.append(
			{
				"doctype": doctype,
				"read": bool(role_permissions.get("read")),
				"write": bool(role_permissions.get("write")),
				"create": bool(role_permissions.get("create")),
				"delete": bool(role_permissions.get("delete")),
				"submit": bool(role_permissions.get("submit")),
				"cancel": bool(role_permissions.get("cancel")),
				"report": bool(role_permissions.get("report")),
				"export": bool(role_permissions.get("export")),
				"if_owner": bool(role_permissions.get("has_if_owner_enabled")),
			}
		)
	return {
		"status": "success",
		"code": "USER_PERMISSION_SNAPSHOT_FETCHED",
		"message": _("已生成用户权限快照。"),
		"data": {"user": user, "roles": frappe.get_roles(user), "permissions": permissions},
	}


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


def get_user_management_overview():
	_ensure_system_manager()
	total_users = frappe.db.count("User")
	enabled_users = frappe.db.count("User", {"enabled": 1})
	system_users = frappe.db.count("User", {"user_type": "System User"})
	website_users = frappe.db.count("User", {"user_type": "Website User"})
	role_parents = {
		row.parent
		for row in frappe.get_all("Has Role", fields=["parent", "role"])
		if row.role not in AUTOMATIC_ROLES
	}
	enabled_system_users = set(
		frappe.get_all(
			"User",
			filters={"enabled": 1, "user_type": "System User"},
			pluck="name",
		)
	)
	manager_users = set(
		frappe.get_all("Has Role", filters={"role": "System Manager"}, pluck="parent")
	)
	never_logged_in = frappe.db.count("User", {"enabled": 1, "last_login": ["is", "not set"]})
	return {
		"status": "success",
		"code": "USER_MANAGEMENT_OVERVIEW_FETCHED",
		"message": _("已获取用户治理概览。"),
		"data": {
			"total_users": total_users,
			"enabled_users": enabled_users,
			"disabled_users": max(total_users - enabled_users, 0),
			"system_users": system_users,
			"website_users": website_users,
			"system_managers": len(enabled_system_users & manager_users),
			"users_without_roles": len(enabled_system_users - role_parents),
			"never_logged_in": never_logged_in,
		},
	}


def batch_set_users_enabled(users, enabled):
	actor = _ensure_system_manager()
	resolved_users = _coerce_list(users)
	if not resolved_users:
		frappe.throw(_("请至少选择一个用户。"))
	if len(resolved_users) > 100:
		frappe.throw(_("单次最多处理 100 个用户。"))
	missing = [user for user in resolved_users if not frappe.db.exists("User", user)]
	if missing:
		raise frappe.DoesNotExistError(_("以下用户不存在：{0}").format("、".join(missing)))
	if not cint(enabled):
		protected = set(resolved_users) & {"Administrator", "Guest", actor}
		if protected:
			frappe.throw(_("不能停用系统保留账号或当前登录账号：{0}").format("、".join(sorted(protected))))
		manager_users = set(
			frappe.get_all("Has Role", filters={"role": "System Manager"}, pluck="parent")
		)
		enabled_managers = set(
			frappe.get_all(
				"User",
				filters={"name": ["in", list(manager_users)], "enabled": 1},
				pluck="name",
			)
		) if manager_users else set()
		if enabled_managers and enabled_managers <= set(resolved_users):
			frappe.throw(_("批量停用会移除最后一个启用的系统管理员。"))

	updated = []
	for user in resolved_users:
		doc = frappe.get_doc("User", user)
		if bool(cint(doc.enabled)) == bool(cint(enabled)):
			continue
		doc.enabled = cint(enabled)
		doc.save(ignore_permissions=True)
		if not cint(enabled):
			revoke_all_user_tokens(user)
		updated.append(user)
	return {
		"status": "success",
		"code": "USER_STATUS_BATCH_UPDATED",
		"message": _("已批量更新用户状态。"),
		"data": {"users": updated, "enabled": bool(cint(enabled)), "updated_count": len(updated)},
	}


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
	if not cint(enabled):
		revoke_all_user_tokens(user)
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
	permission_rows = []
	for permission_doctype in ("DocPerm", "Custom DocPerm"):
		permission_rows.extend(
			frappe.get_all(
				permission_doctype,
				fields=["role", "parent", "read", "write", "create", "delete", "submit", "cancel"],
			)
		)
	permission_counts = Counter()
	doctypes_by_role = defaultdict(set)
	write_doctypes_by_role = defaultdict(set)
	for permission in permission_rows:
		if not permission.role:
			continue
		permission_counts[permission.role] += 1
		doctypes_by_role[permission.role].add(permission.parent)
		if any(cint(permission.get(field)) for field in ("write", "create", "delete", "submit", "cancel")):
			write_doctypes_by_role[permission.role].add(permission.parent)
	roles = [
		{
			**dict(row),
			"user_count": counts.get(row.name, 0),
			"automatic": row.name in AUTOMATIC_ROLES,
			"permission_count": permission_counts.get(row.name, 0),
			"doctype_count": len(doctypes_by_role[row.name]),
			"write_doctype_count": len(write_doctypes_by_role[row.name]),
		}
		for row in rows
	]
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
