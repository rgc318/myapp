from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from myapp.services.user_management_service import (
	_ensure_system_manager,
	_validate_roles,
	add_user_permission,
	set_user_enabled,
	update_user_roles,
)
from myapp.services import user_management_service


class TestUserManagementService(TestCase):
	@patch("myapp.services.user_management_service.frappe.get_roles", return_value=["Sales User"])
	@patch("myapp.services.user_management_service._ensure_authenticated_user", return_value="user@example.com")
	def test_system_manager_role_is_required(self, _mock_authenticated, _mock_roles):
		with self.assertRaises(frappe.PermissionError):
			_ensure_system_manager()

	@patch("myapp.services.user_management_service.frappe.get_all")
	@patch("myapp.services.user_management_service.frappe.throw", side_effect=frappe.ValidationError)
	def test_role_validation_rejects_disabled_and_unknown_roles(self, _mock_throw, mock_get_all):
		mock_get_all.return_value = [frappe._dict(name="Sales User", disabled=0), frappe._dict(name="Old Role", disabled=1)]

		with self.assertRaises(frappe.ValidationError):
			_validate_roles(["Sales User", "Old Role", "Missing Role"])

	@patch("myapp.services.user_management_service._ensure_system_manager", return_value="manager@example.com")
	@patch("myapp.services.user_management_service.frappe.throw", side_effect=frappe.ValidationError)
	def test_manager_cannot_disable_current_account(self, _mock_throw, _mock_manager):
		with self.assertRaises(frappe.ValidationError):
			set_user_enabled("manager@example.com", 0)

	@patch("myapp.services.user_management_service._serialize_user", return_value={"name": "user@example.com"})
	@patch("myapp.services.user_management_service.frappe.get_doc")
	@patch("myapp.services.user_management_service._ensure_not_last_system_manager")
	@patch("myapp.services.user_management_service._validate_roles", return_value=["Sales User"])
	@patch("myapp.services.user_management_service._ensure_system_manager", return_value="manager@example.com")
	def test_update_roles_replaces_role_rows(
		self,
		_mock_manager,
		_mock_validate,
		_mock_last_manager,
		mock_get_doc,
		_mock_serialize,
	):
		doc = Mock()
		mock_get_doc.return_value = doc

		result = update_user_roles("user@example.com", ["Sales User"])

		doc.set.assert_called_once_with("roles", [])
		doc.append.assert_called_once_with("roles", {"role": "Sales User"})
		doc.save.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(result["code"], "USER_ROLES_UPDATED")

	@patch("myapp.services.user_management_service._serialize_user_permission", return_value={"name": "UP-1"})
	@patch("myapp.services.user_management_service.frappe.get_doc")
	@patch("myapp.services.user_management_service._ensure_system_manager", return_value="manager@example.com")
	def test_add_user_permission_uses_standard_frappe_document(
		self,
		_mock_manager,
		mock_get_doc,
		_mock_serialize,
	):
		doc = Mock()
		doc.as_dict.return_value = {"name": "UP-1"}
		mock_get_doc.return_value = doc

		mock_db = Mock()
		mock_db.exists.return_value = True
		with patch.object(user_management_service.frappe, "db", mock_db):
			result = add_user_permission("user@example.com", "Company", "Demo Company", is_default=1)

		doc.insert.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(result["code"], "USER_PERMISSION_CREATED")
