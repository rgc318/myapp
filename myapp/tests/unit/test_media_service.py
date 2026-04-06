from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.media_service import replace_item_image, upload_item_image


class TestMediaService(TestCase):
	@patch("myapp.services.media_service.save_file")
	def test_upload_item_image_uses_frappe_file_storage(self, mock_save_file):
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

	@patch("myapp.services.media_service._delete_managed_file_by_url")
	@patch("myapp.services.media_service.save_file")
	@patch("myapp.services.media_service.frappe.get_doc")
	def test_replace_item_image_deletes_previous_managed_file(
		self,
		mock_get_doc,
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
	@patch("myapp.services.media_service.frappe.get_doc")
	def test_replace_item_image_rolls_back_new_upload_when_item_save_fails(
		self,
		mock_get_doc,
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
	@patch("myapp.services.media_service.frappe.get_doc")
	def test_replace_item_image_skips_cleanup_when_old_url_is_shared(
		self,
		mock_get_doc,
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
