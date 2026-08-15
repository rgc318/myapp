import base64
from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.services.ai_attachment_service import (
	_decode_content,
	_normalize_ids,
	_validate_source_content_type,
)


class TestAiAttachmentService(TestCase):
	def test_normalize_ids_deduplicates_and_preserves_order(self):
		self.assertEqual(
			_normalize_ids('["AI-ATT-1", "AI-ATT-1", "AI-ATT-2"]'),
			["AI-ATT-1", "AI-ATT-2"],
		)

	def test_normalize_ids_rejects_more_than_four_images(self):
		with patch("myapp.services.ai_attachment_service.frappe") as mock_frappe:
			mock_frappe.ValidationError = frappe.ValidationError
			mock_frappe.parse_json.side_effect = frappe.parse_json
			with self.assertRaises(frappe.ValidationError):
				_normalize_ids([f"AI-ATT-{index}" for index in range(5)])

	def test_decode_content_accepts_data_url_and_rejects_invalid_base64(self):
		content = b"synthetic-image"
		encoded = base64.b64encode(content).decode()
		self.assertEqual(_decode_content(f"data:image/png;base64,{encoded}"), content)
		with patch("myapp.services.ai_attachment_service.frappe") as mock_frappe:
			mock_frappe.ValidationError = frappe.ValidationError
			with self.assertRaises(frappe.ValidationError):
				_decode_content("not-base64")

	def test_source_format_must_match_declared_content_type(self):
		_validate_source_content_type(source_format="png", content_type="image/png")
		with self.assertRaises(frappe.ValidationError):
			_validate_source_content_type(source_format="gif", content_type="image/png")
