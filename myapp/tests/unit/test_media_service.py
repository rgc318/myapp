import base64

from unittest import TestCase
from unittest.mock import MagicMock, call, patch

import frappe

from myapp.services.media_service import (
	bind_uploaded_item_image,
	cleanup_expired_temporary_item_images,
	cleanup_temporary_item_image,
	delete_item_image,
	replace_item_image,
	upload_item_image,
)


class TestMediaService(TestCase):
	@patch("myapp.services.media_service.save_file")
	@patch("myapp.services.media_service._ensure_item_image_folder", return_value="Home/Attachments/MyApp Item Images")
	def test_upload_item_image_uses_frappe_file_storage(self, _mock_ensure_item_image_folder, mock_save_file):
		mock_save_file.return_value = frappe._dict(
			{
				"name": "FILE-0001",
				"file_name": "item.png",
				"file_url": "/files/item.png",
				"is_private": 0,
				"attached_to_doctype": "Item",
				"attached_to_name": "ITEM-001",
			}
		)

		result = upload_item_image(
			filename="item.png",
			file_content_base64="ZmFrZS1pbWFnZQ==",
			content_type="image/png",
			item_code="ITEM-001",
		)

		mock_save_file.assert_called_once_with(
			fname="item.png",
			content=b"fake-image",
			dt="Item",
			dn="ITEM-001",
			folder="Home/Attachments/MyApp Item Images",
			df="image",
			is_private=0,
		)
		self.assertEqual(result["data"]["file_url"], "/files/item.png")
		self.assertEqual(result["data"]["storage_provider"], "frappe_file")

	def test_upload_item_image_rejects_unsupported_extension(self):
		with self.assertRaises(frappe.ValidationError):
			upload_item_image(
				filename="item.txt",
				file_content_base64="ZmFrZS1pbWFnZQ==",
				content_type="text/plain",
			)

	def test_upload_item_image_rejects_invalid_base64(self):
		with self.assertRaises(frappe.ValidationError):
			upload_item_image(
				filename="item.png",
				file_content_base64="not-base64",
				content_type="image/png",
			)

	def test_upload_item_image_rejects_oversized_payload(self):
		oversized = base64.b64encode(b"a" * (5 * 1024 * 1024 + 1)).decode()
		with self.assertRaises(frappe.ValidationError):
			upload_item_image(
				filename="item.png",
				file_content_base64=oversized,
				content_type="image/png",
			)

	@patch("myapp.services.media_service._delete_managed_file_by_url")
	@patch("myapp.services.media_service.save_file")
	@patch("myapp.services.media_service._ensure_item_image_folder", return_value="Home/Attachments/MyApp Item Images")
	@patch("myapp.services.media_service.frappe.get_doc")
	def test_replace_item_image_deletes_previous_managed_file(
		self,
		mock_get_doc,
		_mock_ensure_item_image_folder,
		mock_save_file,
		mock_delete_managed_file_by_url,
	):
		item = MagicMock()
		item.image = "/files/item-old.png"
		mock_get_doc.return_value = item
		mock_save_file.return_value = frappe._dict(
			{
				"name": "FILE-NEW",
				"file_name": "item-new.png",
				"file_url": "/files/item-new.png",
				"is_private": 0,
				"attached_to_doctype": "Item",
				"attached_to_name": "ITEM-001",
			}
		)
		mock_delete_managed_file_by_url.return_value = True

		result = replace_item_image(
			item_code="ITEM-001",
			filename="item-new.png",
			file_content_base64="ZmFrZS1pbWFnZQ==",
			content_type="image/png",
		)

		self.assertEqual(item.image, "/files/item-new.png")
		item.save.assert_called_once_with()
		mock_delete_managed_file_by_url.assert_called_once_with(
			file_url="/files/item-old.png",
			item_code="ITEM-001",
			skip_if_shared=True,
		)
		self.assertTrue(result["data"]["cleanup"]["deleted"])
		self.assertEqual(result["data"]["previous_file_url"], "/files/item-old.png")

	@patch("myapp.services.media_service._delete_managed_file_by_url")
	@patch("myapp.services.media_service.save_file")
	@patch("myapp.services.media_service._ensure_item_image_folder", return_value="Home/Attachments/MyApp Item Images")
	@patch("myapp.services.media_service.frappe.get_doc")
	def test_replace_item_image_rolls_back_new_upload_when_item_save_fails(
		self,
		mock_get_doc,
		_mock_ensure_item_image_folder,
		mock_save_file,
		mock_delete_managed_file_by_url,
	):
		item = MagicMock()
		item.image = "/files/item-old.png"
		item.save.side_effect = RuntimeError("save failed")
		mock_get_doc.return_value = item
		mock_save_file.return_value = frappe._dict(
			{
				"name": "FILE-NEW",
				"file_name": "item-new.png",
				"file_url": "/files/item-new.png",
				"is_private": 0,
				"attached_to_doctype": "Item",
				"attached_to_name": "ITEM-001",
			}
		)

		with self.assertRaises(RuntimeError):
			replace_item_image(
				item_code="ITEM-001",
				filename="item-new.png",
				file_content_base64="ZmFrZS1pbWFnZQ==",
				content_type="image/png",
			)

		mock_delete_managed_file_by_url.assert_called_once_with(
			file_url="/files/item-new.png",
			item_code="ITEM-001",
			skip_if_shared=False,
		)

	@patch("myapp.services.media_service._delete_managed_file_by_url")
	@patch("myapp.services.media_service.save_file")
	@patch("myapp.services.media_service._ensure_item_image_folder", return_value="Home/Attachments/MyApp Item Images")
	@patch("myapp.services.media_service.frappe.get_doc")
	def test_replace_item_image_skips_cleanup_when_old_url_is_shared(
		self,
		mock_get_doc,
		_mock_ensure_item_image_folder,
		mock_save_file,
		mock_delete_managed_file_by_url,
	):
		item = MagicMock()
		item.image = "/files/shared.png"
		mock_get_doc.return_value = item
		mock_save_file.return_value = frappe._dict(
			{
				"name": "FILE-NEW",
				"file_name": "item-new.png",
				"file_url": "/files/item-new.png",
				"is_private": 0,
				"attached_to_doctype": "Item",
				"attached_to_name": "ITEM-001",
			}
		)
		mock_delete_managed_file_by_url.return_value = False

		result = replace_item_image(
			item_code="ITEM-001",
			filename="item-new.png",
			file_content_base64="ZmFrZS1pbWFnZQ==",
			content_type="image/png",
		)

		mock_delete_managed_file_by_url.assert_called_once_with(
			file_url="/files/shared.png",
			item_code="ITEM-001",
			skip_if_shared=True,
		)
		self.assertFalse(result["data"]["cleanup"]["deleted"])

	@patch("myapp.services.media_service._delete_managed_file_by_url")
	@patch("myapp.services.media_service.frappe.get_doc")
	def test_delete_item_image_clears_item_image_and_deletes_managed_file(
		self,
		mock_get_doc,
		mock_delete_managed_file_by_url,
	):
		item = MagicMock()
		item.image = "/files/item-old.png"
		mock_get_doc.return_value = item
		mock_delete_managed_file_by_url.return_value = True

		result = delete_item_image(item_code="ITEM-001")

		self.assertIsNone(item.image)
		item.save.assert_called_once_with()
		mock_delete_managed_file_by_url.assert_called_once_with(
			file_url="/files/item-old.png",
			item_code="ITEM-001",
			skip_if_shared=True,
		)
		self.assertTrue(result["data"]["deleted"])

	@patch("myapp.services.media_service.frappe.get_doc")
	def test_delete_item_image_returns_empty_when_item_has_no_image(self, mock_get_doc):
		item = MagicMock()
		item.image = None
		mock_get_doc.return_value = item

		result = delete_item_image(item_code="ITEM-001")

		self.assertFalse(result["data"]["deleted"])
		item.save.assert_not_called()

	@patch("myapp.services.media_service._ensure_item_image_folder", return_value="Home/Attachments/MyApp Item Images")
	@patch("myapp.services.media_service.frappe.get_doc")
	@patch("myapp.services.media_service.frappe.get_all")
	def test_bind_uploaded_item_image_attaches_temp_file_to_item(
		self, mock_get_all, mock_get_doc, mock_ensure_item_image_folder
	):
		mock_get_all.return_value = [
			frappe._dict(
				{
					"name": "FILE-TEMP-001",
					"attached_to_doctype": None,
					"attached_to_name": None,
					"attached_to_field": None,
				}
			)
		]
		file_doc = MagicMock()
		mock_get_doc.return_value = file_doc

		bound = bind_uploaded_item_image(file_url="/files/item.png", item_code="ITEM-001")

		self.assertTrue(bound)
		mock_get_doc.assert_called_once_with("File", "FILE-TEMP-001")
		self.assertEqual(file_doc.attached_to_doctype, "Item")
		self.assertEqual(file_doc.attached_to_name, "ITEM-001")
		self.assertEqual(file_doc.attached_to_field, "image")
		self.assertEqual(file_doc.folder, "Home/Attachments/MyApp Item Images")
		file_doc.save.assert_called_once_with(ignore_permissions=True)

	@patch("myapp.services.media_service.create_new_folder")
	def test_ensure_item_image_folder_creates_missing_nested_folders(self, mock_create_new_folder):
		from myapp.services.media_service import _ensure_item_image_folder
		from myapp.services import media_service

		fake_db = MagicMock()
		existing_folders = {"Home/Attachments"}

		def fake_exists(_doctype, name):
			return name in existing_folders

		def fake_create_new_folder(file_name, folder):
			existing_folders.add(f"{folder}/{file_name}")

		fake_db.exists.side_effect = fake_exists
		mock_create_new_folder.side_effect = fake_create_new_folder

		with patch.object(media_service.frappe, "db", fake_db):
			folder = _ensure_item_image_folder(is_temporary=True)

		self.assertEqual(folder, "Home/Attachments/MyApp Item Images/Temporary")
		self.assertEqual(
			mock_create_new_folder.call_args_list,
			[
				call("MyApp Item Images", "Home/Attachments"),
				call("Temporary", "Home/Attachments/MyApp Item Images"),
			],
		)

	@patch("myapp.services.media_service.frappe.delete_doc")
	@patch("myapp.services.media_service.frappe.get_all")
	def test_cleanup_temporary_item_image_deletes_only_unattached_file(self, mock_get_all, mock_delete_doc):
		mock_get_all.return_value = [
			frappe._dict(
				{
					"name": "FILE-TEMP-001",
					"attached_to_doctype": None,
					"attached_to_name": None,
					"attached_to_field": None,
				}
			)
		]

		deleted = cleanup_temporary_item_image(file_url="/files/item.png")

		self.assertTrue(deleted)
		mock_delete_doc.assert_called_once_with("File", "FILE-TEMP-001", ignore_permissions=True, force=True)

	@patch("myapp.services.media_service.cleanup_temporary_item_image")
	@patch("myapp.services.media_service.now_datetime")
	@patch("myapp.services.media_service.frappe.get_all")
	def test_cleanup_expired_temporary_item_images_deletes_only_old_temp_files(
		self, mock_get_all, mock_now_datetime, mock_cleanup_temporary_item_image
	):
		from datetime import datetime

		mock_now_datetime.return_value = datetime(2026, 4, 7, 12, 0, 0)
		mock_get_all.return_value = [
			frappe._dict(
				{
					"name": "FILE-OLD-001",
					"file_url": "/files/old.png",
					"modified": "2026-04-06 09:00:00",
				}
			),
			frappe._dict(
				{
					"name": "FILE-NEW-001",
					"file_url": "/files/new.png",
					"modified": "2026-04-07 11:30:00",
				}
			),
		]
		mock_cleanup_temporary_item_image.return_value = True

		result = cleanup_expired_temporary_item_images(older_than_hours=24)

		mock_cleanup_temporary_item_image.assert_called_once_with(file_url="/files/old.png")
		self.assertEqual(result["data"]["deleted_files"], ["FILE-OLD-001"])
		self.assertEqual(result["data"]["skipped_recent_files"], ["FILE-NEW-001"])
