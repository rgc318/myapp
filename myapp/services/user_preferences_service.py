import frappe
from frappe import _


def _normalize_text(value: str | None):
	return (value or "").strip()


def _extract_default_value(value):
	if isinstance(value, (list, tuple)):
		for item in value:
			resolved = _normalize_text(item)
			if resolved:
				return resolved
		return None
	resolved = _normalize_text(value)
	return resolved or None


def _ensure_authenticated_user():
	user = _normalize_text(getattr(frappe.session, "user", None))
	if not user or user == "Guest":
		raise frappe.AuthenticationError(_("请先登录后再读取或保存工作偏好。"))
	return user


def _validate_company(company: str | None):
	resolved = _normalize_text(company) or None
	if resolved and not frappe.db.exists("Company", resolved):
		frappe.throw(_("公司 {0} 不存在。").format(resolved))
	return resolved


def _validate_warehouse(warehouse: str | None, *, company: str | None = None):
	resolved = _normalize_text(warehouse) or None
	if not resolved:
		return None

	if not frappe.db.exists("Warehouse", resolved):
		frappe.throw(_("仓库 {0} 不存在。").format(resolved))

	if company:
		warehouse_company = _normalize_text(frappe.db.get_value("Warehouse", resolved, "company")) or None
		if warehouse_company and warehouse_company != company:
			frappe.throw(_("仓库 {0} 不属于公司 {1}。").format(resolved, company))

	return resolved


def _build_workspace_preferences_payload(*, user: str):
	default_company = _extract_default_value(frappe.defaults.get_user_default("company", user))
	default_warehouse = _extract_default_value(
		frappe.defaults.get_user_default("default_warehouse", user)
	) or _extract_default_value(frappe.defaults.get_user_default("warehouse", user))

	return {
		"user": user,
		"default_company": default_company,
		"default_warehouse": default_warehouse,
	}


def get_current_user_workspace_preferences():
	user = _ensure_authenticated_user()
	return {
		"status": "success",
		"message": _("已获取当前用户工作偏好。"),
		"data": _build_workspace_preferences_payload(user=user),
		"code": "USER_WORKSPACE_PREFERENCES_FETCHED",
	}


def update_current_user_workspace_preferences(
	default_company: str | None = None,
	default_warehouse: str | None = None,
):
	user = _ensure_authenticated_user()
	resolved_company = _validate_company(default_company)
	resolved_warehouse = _validate_warehouse(default_warehouse, company=resolved_company)

	frappe.defaults.set_user_default("company", resolved_company, user=user)
	frappe.defaults.set_user_default("warehouse", resolved_warehouse, user=user)
	frappe.defaults.set_user_default("default_warehouse", resolved_warehouse, user=user)

	return {
		"status": "success",
		"message": _("已更新当前用户工作偏好。"),
		"data": _build_workspace_preferences_payload(user=user),
		"code": "USER_WORKSPACE_PREFERENCES_UPDATED",
	}
