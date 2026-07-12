import frappe

from myapp.services.user_management_service import (
	add_user_permission,
	batch_set_users_enabled,
	change_current_user_password,
	create_user,
	delete_user_permission,
	get_current_user_profile,
	get_user_permission_snapshot,
	get_user_security,
	get_user_management_overview,
	get_user_detail,
	list_roles,
	list_users,
	revoke_user_sessions,
	set_user_enabled,
	update_current_user_profile,
	update_user,
	update_user_roles,
	upload_current_user_avatar,
)


@frappe.whitelist()
def get_current_user_profile_v1():
	return get_current_user_profile()


@frappe.whitelist()
def update_current_user_profile_v1(**kwargs):
	return update_current_user_profile(**kwargs)


@frappe.whitelist()
def upload_current_user_avatar_v1(filename: str, file_content_base64: str, content_type=None):
	return upload_current_user_avatar(filename, file_content_base64, content_type)


@frappe.whitelist()
def change_current_user_password_v1(old_password: str, new_password: str, logout_all_sessions=1):
	return change_current_user_password(old_password, new_password, logout_all_sessions)


@frappe.whitelist()
def list_users_v1(search=None, enabled=None, role=None, user_type=None, page=1, page_size=20):
	return list_users(search, enabled, role, user_type, page, page_size)


@frappe.whitelist()
def get_user_management_overview_v1():
	return get_user_management_overview()


@frappe.whitelist()
def batch_set_users_enabled_v1(users=None, enabled=1):
	return batch_set_users_enabled(users, enabled)


@frappe.whitelist()
def get_user_detail_v1(user: str):
	return get_user_detail(user)


@frappe.whitelist()
def get_user_security_v1(user: str | None = None):
	return get_user_security(user)


@frappe.whitelist()
def revoke_user_sessions_v1(user: str | None = None):
	return revoke_user_sessions(user)


@frappe.whitelist()
def get_user_permission_snapshot_v1(user: str):
	return get_user_permission_snapshot(user)


@frappe.whitelist()
def create_user_v1(email: str, first_name: str, roles=None, password=None, send_welcome_email=0, enabled=1, **kwargs):
	return create_user(email, first_name, roles, password, send_welcome_email, enabled, **kwargs)


@frappe.whitelist()
def update_user_v1(user: str, **kwargs):
	return update_user(user, **kwargs)


@frappe.whitelist()
def set_user_enabled_v1(user: str, enabled=1):
	return set_user_enabled(user, enabled)


@frappe.whitelist()
def update_user_roles_v1(user: str, roles=None):
	return update_user_roles(user, roles)


@frappe.whitelist()
def list_roles_v1(search=None):
	return list_roles(search)


@frappe.whitelist()
def add_user_permission_v1(user: str, allow: str, for_value: str, is_default=0, apply_to_all_doctypes=1, applicable_for=None, hide_descendants=0):
	return add_user_permission(user, allow, for_value, is_default, apply_to_all_doctypes, applicable_for, hide_descendants)


@frappe.whitelist()
def delete_user_permission_v1(user: str, permission_name: str):
	return delete_user_permission(user, permission_name)
