from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.services.user_preferences_service import (
	get_current_user_workspace_preferences,
	update_current_user_workspace_preferences,
)


class TestUserPreferencesService(TestCase):
	@patch("myapp.services.user_preferences_service._ensure_authenticated_user", return_value="demo@example.com")
	@patch("myapp.services.user_preferences_service.frappe.defaults.get_user_default")
	def test_get_current_user_workspace_preferences_reads_user_defaults(
		self,
		mock_get_user_default,
		_mock_ensure_authenticated_user,
	):
		mock_get_user_default.side_effect = ["Test Company", "Stores - RD", None]

		result = get_current_user_workspace_preferences()

		self.assertEqual(result["code"], "USER_WORKSPACE_PREFERENCES_FETCHED")
		self.assertEqual(
			result["data"],
			{
				"user": "demo@example.com",
				"default_company": "Test Company",
				"default_warehouse": "Stores - RD",
			},
		)

	@patch("myapp.services.user_preferences_service._ensure_authenticated_user", return_value="demo@example.com")
	@patch("myapp.services.user_preferences_service._validate_company", return_value="Test Company")
	@patch("myapp.services.user_preferences_service._validate_warehouse", return_value="Stores - RD")
	@patch("myapp.services.user_preferences_service.frappe.defaults.set_user_default")
	def test_update_current_user_workspace_preferences_persists_company_and_warehouse(
		self,
		mock_set_user_default,
		_mock_validate_warehouse,
		_mock_validate_company,
		_mock_ensure_authenticated_user,
	):
		with patch(
			"myapp.services.user_preferences_service.frappe.defaults.get_user_default",
			side_effect=["Test Company", "Stores - RD", None],
		):
			result = update_current_user_workspace_preferences(
				default_company="Test Company",
				default_warehouse="Stores - RD",
			)

		self.assertEqual(result["code"], "USER_WORKSPACE_PREFERENCES_UPDATED")
		mock_set_user_default.assert_any_call("company", "Test Company", user="demo@example.com")
		mock_set_user_default.assert_any_call("warehouse", "Stores - RD", user="demo@example.com")
		mock_set_user_default.assert_any_call("default_warehouse", "Stores - RD", user="demo@example.com")

	@patch("myapp.services.user_preferences_service._ensure_authenticated_user")
	def test_get_current_user_workspace_preferences_requires_authentication(self, mock_ensure_authenticated_user):
		mock_ensure_authenticated_user.side_effect = frappe.AuthenticationError("请先登录")
		with self.assertRaises(frappe.AuthenticationError):
			get_current_user_workspace_preferences()
