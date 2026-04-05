from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from myapp.services.printing_service import build_print_file_download_v1, get_print_file_v1, get_print_preview_v1


class TestPrintingService(TestCase):
	@patch("myapp.services.printing_service._render_print_preview_payload")
	@patch("myapp.services.printing_service._load_print_document")
	@patch("myapp.services.printing_service._ensure_template_ready")
	def test_get_print_preview_v1_returns_preview_data(
		self,
		mock_ensure_template_ready,
		mock_load_print_document,
		mock_render_print_preview_payload,
	):
		document = frappe._dict({"doctype": "Sales Invoice", "name": "SINV-0001"})
		mock_load_print_document.return_value = document
		mock_render_print_preview_payload.return_value = {
			"doctype": "Sales Invoice",
			"docname": "SINV-0001",
			"title": "Sales Invoice SINV-0001",
			"template": {
				"key": "standard",
				"label": "标准发票",
				"print_format": "myapp Sales Invoice Standard",
				"is_default": True,
				"source": "myapp",
			},
			"available_templates": [
				{
					"key": "standard",
					"label": "标准发票",
					"print_format": "myapp Sales Invoice Standard",
					"is_default": True,
					"source": "myapp",
				}
			],
			"output": "html",
			"html": "<html />",
			"mime_type": "text/html",
		}

		result = get_print_preview_v1(doctype="Sales Invoice", docname="SINV-0001")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["docname"], "SINV-0001")
		self.assertEqual(result["data"]["output"], "html")
		self.assertEqual(result["meta"]["template"], "standard")
		mock_ensure_template_ready.assert_called_once()
		mock_load_print_document.assert_called_once_with("Sales Invoice", "SINV-0001")

	@patch("myapp.services.printing_service._save_print_pdf_file")
	@patch("myapp.services.printing_service._render_print_pdf")
	@patch("myapp.services.printing_service._load_print_document")
	@patch("myapp.services.printing_service._ensure_template_ready")
	def test_get_print_file_v1_returns_file_metadata(
		self,
		mock_ensure_template_ready,
		mock_load_print_document,
		mock_render_print_pdf,
		mock_save_print_pdf_file,
	):
		document = frappe._dict({"doctype": "Sales Invoice", "name": "SINV-0001"})
		mock_load_print_document.return_value = document
		mock_render_print_pdf.return_value = b"%PDF-test"
		mock_save_print_pdf_file.return_value = frappe._dict({"file_url": "/private/files/invoice.pdf", "is_private": 1})

		result = get_print_file_v1(doctype="Sales Invoice", docname="SINV-0001")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["output"], "pdf")
		self.assertEqual(result["data"]["mime_type"], "application/pdf")
		self.assertEqual(result["data"]["filename"], "Sales Invoice-SINV-0001-standard.pdf")
		self.assertEqual(result["data"]["status"], "ready")
		self.assertEqual(result["data"]["file_size"], 9)
		self.assertEqual(result["data"]["file_url"], "/private/files/invoice.pdf")
		self.assertTrue(result["data"]["is_private"])
		mock_ensure_template_ready.assert_called_once()

	def test_get_print_preview_v1_rejects_unsupported_output(self):
		with patch("myapp.services.printing_service.frappe.throw", side_effect=frappe.ValidationError):
			with self.assertRaises(frappe.ValidationError):
				get_print_preview_v1(doctype="Sales Invoice", docname="SINV-0001", output="docx")

	def test_get_print_preview_v1_requires_supported_template(self):
		with patch("myapp.printing.registry.frappe.throw", side_effect=frappe.ValidationError):
			with self.assertRaises(frappe.ValidationError):
				get_print_preview_v1(doctype="Sales Invoice", docname="SINV-0001", template="unknown")

	@patch("myapp.services.printing_service._render_print_pdf")
	@patch("myapp.services.printing_service._load_print_document")
	@patch("myapp.services.printing_service._ensure_template_ready")
	def test_build_print_file_download_v1_returns_bytes_payload(
		self,
		mock_ensure_template_ready,
		mock_load_print_document,
		mock_render_print_pdf,
	):
		document = frappe._dict({"doctype": "Sales Invoice", "name": "SINV-0001"})
		mock_load_print_document.return_value = document
		mock_render_print_pdf.return_value = b"%PDF-download"

		result = build_print_file_download_v1(doctype="Sales Invoice", docname="SINV-0001")

		self.assertEqual(result["filename"], "Sales Invoice-SINV-0001-standard.pdf")
		self.assertEqual(result["template"], "standard")
		self.assertEqual(result["content"], b"%PDF-download")
		mock_ensure_template_ready.assert_called_once()

	def test_load_print_document_checks_permission(self):
		from myapp.services.printing_service import _load_print_document

		document = Mock()
		document.doctype = "Sales Invoice"
		document.name = "SINV-0001"
		with patch("myapp.services.printing_service.frappe") as mock_frappe:
			mock_frappe.db.exists.return_value = True
			mock_frappe.get_doc.return_value = document
			mock_frappe.has_permission.return_value = True

			result = _load_print_document("Sales Invoice", "SINV-0001")

		self.assertIs(result, document)
		mock_frappe.get_doc.assert_called_once_with("Sales Invoice", "SINV-0001")
		mock_frappe.has_permission.assert_called_once_with("Sales Invoice", ptype="read", doc=document)
