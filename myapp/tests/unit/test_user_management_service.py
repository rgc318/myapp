from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from myapp.services.user_management_service import (
	_ensure_system_manager,
	_validate_roles,
	add_user_permission,
	batch_set_users_enabled,
	get_user_management_overview,
	get_user_permission_snapshot,
	list_roles,
	set_user_enabled,
	upload_current_user_avatar,
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

	@patch("myapp.services.user_management_service._ensure_system_manager", return_value="manager@example.com")
	@patch("myapp.services.user_management_service.frappe.throw", side_effect=frappe.ValidationError)
	def test_batch_status_update_limits_batch_size(self, _mock_throw, _mock_manager):
		with self.assertRaises(frappe.ValidationError):
			batch_set_users_enabled([f"user-{index}@example.com" for index in range(101)], 1)

	@patch("myapp.services.user_management_service._ensure_system_manager", return_value="manager@example.com")
	@patch("myapp.services.user_management_service.frappe.get_all")
	def test_user_management_overview_builds_governance_metrics(self, mock_get_all, _mock_manager):
		mock_db = Mock()
		mock_db.count.side_effect = [10, 8, 7, 3, 2]
		mock_get_all.side_effect = [
			[
				frappe._dict(parent="manager@example.com", role="System Manager"),
				frappe._dict(parent="sales@example.com", role="Sales User"),
			],
			["manager@example.com", "sales@example.com", "plain@example.com"],
			["manager@example.com"],
		]
		with patch.object(user_management_service.frappe, "db", mock_db):
			result = get_user_management_overview()

		self.assertEqual(result["data"]["total_users"], 10)
		self.assertEqual(result["data"]["disabled_users"], 2)
		self.assertEqual(result["data"]["system_managers"], 1)
		self.assertEqual(result["data"]["users_without_roles"], 1)

	@patch("myapp.services.user_management_service._ensure_system_manager", return_value="manager@example.com")
	@patch("myapp.services.user_management_service.frappe.get_all")
	def test_role_summary_includes_permission_coverage(self, mock_get_all, _mock_manager):
		mock_get_all.side_effect = [
			[frappe._dict(name="Sales User", desk_access=1, restrict_to_domain=None, disabled=0)],
			["Sales User", "Sales User"],
			[frappe._dict(role="Sales User", parent="Sales Order", read=1, write=1, create=1, delete=0, submit=0, cancel=0)],
			[frappe._dict(role="Sales User", parent="Sales Invoice", read=1, write=0, create=0, delete=0, submit=0, cancel=0)],
		]

		result = list_roles()
		role = result["data"]["roles"][0]

		self.assertEqual(role["user_count"], 2)
		self.assertEqual(role["permission_count"], 2)
		self.assertEqual(role["doctype_count"], 2)
		self.assertEqual(role["write_doctype_count"], 1)

	@patch("myapp.services.user_management_service.frappe.get_roles", return_value=["Sales User"])
	@patch("myapp.services.user_management_service.frappe.permissions.get_role_permissions")
	@patch("myapp.services.user_management_service._ensure_system_manager", return_value="manager@example.com")
	def test_permission_snapshot_uses_frappe_effective_role_permissions(
		self,
		_mock_manager,
		mock_get_role_permissions,
		_mock_roles,
	):
		mock_db = Mock()
		mock_db.exists.return_value = True
		mock_get_role_permissions.return_value = {"read": 1, "write": 1, "create": 0}

		with patch.object(user_management_service.frappe, "db", mock_db):
			result = get_user_permission_snapshot("user@example.com")

		self.assertTrue(result["data"]["permissions"])
		self.assertTrue(result["data"]["permissions"][0]["read"])
		self.assertTrue(result["data"]["permissions"][0]["write"])
		self.assertFalse(result["data"]["permissions"][0]["create"])

	@patch("myapp.services.user_management_service._ensure_authenticated_user", return_value="user@example.com")
	@patch("myapp.services.user_management_service._normalize_image_filename", return_value="avatar.png")
	@patch("myapp.services.user_management_service._validate_image_content_type")
	@patch("myapp.services.user_management_service._decode_base64_file_content", return_value=b"image")
	@patch("myapp.services.user_management_service.normalize_image_upload")
	@patch("myapp.services.user_management_service._ensure_folder_path", return_value="Home/Avatars")
	@patch("myapp.services.user_management_service.save_file")
	@patch("myapp.services.user_management_service.frappe.get_doc")
	def test_avatar_upload_binds_frappe_file_to_current_user(
		self,
		mock_get_doc,
		mock_save_file,
		_mock_folder,
		mock_normalize_image_upload,
		_mock_decode,
		_mock_validate,
		_mock_filename,
		_mock_user,
	):
		mock_normalize_image_upload.return_value = Mock(
			aspect_ratio=1,
			content=b"avatar-webp",
			content_type="image/webp",
			filename="avatar.webp",
			file_size=100,
			height=512,
			profile="avatar-square-v1",
			quality=85,
			source_format="png",
			source_height=600,
			source_width=800,
			width=512,
		)
		user_doc = Mock(user_image=None)
		mock_get_doc.return_value = user_doc
		mock_save_file.return_value = Mock(file_url="/files/avatar.png", name="FILE-1", file_name="avatar.png")

		result = upload_current_user_avatar("avatar.png", "base64", "image/png")

		self.assertEqual(result["data"]["file_url"], "/files/avatar.png")
		self.assertEqual(result["data"]["aspect_ratio"], 1)
		self.assertEqual(result["data"]["profile"], "avatar-square-v1")
		self.assertEqual(user_doc.user_image, "/files/avatar.png")
		user_doc.save.assert_called_once_with(ignore_permissions=True)
