import frappe

from myapp.services.user_preferences_service import (
	get_current_user_workspace_preferences as get_current_user_workspace_preferences_service,
	update_current_user_workspace_preferences as update_current_user_workspace_preferences_service,
)


@frappe.whitelist()
def get_current_user_workspace_preferences_v1():
	return get_current_user_workspace_preferences_service()


@frappe.whitelist()
def update_current_user_workspace_preferences_v1(
	default_company: str | None = None,
	default_warehouse: str | None = None,
):
	return update_current_user_workspace_preferences_service(
		default_company=default_company,
		default_warehouse=default_warehouse,
	)
