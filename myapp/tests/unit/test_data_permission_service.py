from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.data_permission_service import (
	ensure_user_permission_value,
	filter_permitted_user_default,
	get_permission_query_condition,
	has_doctype_permission,
	require_doctype_permission,
)


class TestDataPermissionService(TestCase):
	@patch("myapp.services.data_permission_service.current_user", return_value="user@example.com")
	@patch("myapp.services.data_permission_service.frappe.has_permission", return_value=False)
	def test_has_doctype_permission_returns_false_without_raising(
		self,
		_mock_has_permission,
		_mock_current_user,
	):
		self.assertFalse(has_doctype_permission("Sales Invoice", "create"))

	@patch("myapp.services.data_permission_service.current_user", return_value="user@example.com")
	@patch("myapp.services.data_permission_service.frappe.has_permission", return_value=False)
	def test_require_doctype_permission_rejects_missing_role_permission(
		self,
		_mock_has_permission,
		_mock_current_user,
	):
		with self.assertRaises(frappe.PermissionError):
			require_doctype_permission("Customer", "read")

	@patch("myapp.services.data_permission_service.current_user", return_value="user@example.com")
	@patch("myapp.services.data_permission_service.frappe.permissions.get_user_permissions")
	def test_ensure_user_permission_value_rejects_out_of_scope_company(
		self,
		mock_get_user_permissions,
		_mock_current_user,
	):
		mock_get_user_permissions.return_value = {
			"Company": [frappe._dict(doc="Allowed Company", applicable_for=None)]
		}
		with self.assertRaises(frappe.PermissionError):
			ensure_user_permission_value("Company", "Other Company", applicable_for="Sales Order")

	@patch("myapp.services.data_permission_service.ensure_user_permission_value")
	def test_filter_permitted_user_default_ignores_stale_value(self, mock_ensure_user_permission_value):
		mock_ensure_user_permission_value.side_effect = frappe.PermissionError("denied")

		result = filter_permitted_user_default(
			"Company",
			"Stale Company",
			applicable_for="Sales Order",
		)

		self.assertIsNone(result)

	@patch("myapp.services.data_permission_service.ensure_user_permission_value", return_value="Allowed Company")
	def test_filter_permitted_user_default_keeps_allowed_value(self, mock_ensure_user_permission_value):
		result = filter_permitted_user_default(
			"Company",
			"Allowed Company",
			applicable_for="Sales Order",
		)

		self.assertEqual(result, "Allowed Company")
		mock_ensure_user_permission_value.assert_called_once_with(
			"Company",
			"Allowed Company",
			applicable_for="Sales Order",
		)

	@patch("myapp.services.data_permission_service.DatabaseQuery")
	@patch("myapp.services.data_permission_service.require_doctype_permission", return_value="user@example.com")
	def test_permission_query_condition_supports_table_alias(
		self,
		_mock_require_permission,
		mock_database_query,
	):
		query = MagicMock()
		query.build_match_conditions.return_value = "`tabSales Order`.`company` in ('Allowed Company')"
		mock_database_query.return_value = query

		condition = get_permission_query_condition("Sales Order", table_alias="so")

		self.assertEqual(condition, "so.`company` in ('Allowed Company')")
		query.check_read_permission.assert_called_once_with("Sales Order")
