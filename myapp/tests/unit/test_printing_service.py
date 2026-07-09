from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from myapp.services.printing_service import (
	build_print_file_download_v1,
	get_print_file_v1,
	get_print_preview_v1,
	get_print_templates_v1,
	list_print_jobs_v1,
	list_print_doctypes_v1,
	record_print_job_v1,
)


class TestPrintingService(TestCase):
	def test_list_print_doctypes_v1_returns_registered_documents(self):
		result = list_print_doctypes_v1()

		self.assertEqual(result["status"], "success")
		self.assertGreaterEqual(result["data"]["count"], 6)
		self.assertEqual(result["data"]["doctypes"][0]["capabilities"], ["preview", "download_pdf", "archive_pdf"])
		self.assertIn("templates", result["data"]["doctypes"][0])

	def test_get_print_templates_v1_returns_doctype_templates(self):
		result = get_print_templates_v1("Sales Invoice")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["doctype"], "Sales Invoice")
		self.assertEqual(result["data"]["default_template"], "standard")
		self.assertEqual(result["data"]["templates"][0]["paper_size"], "A4")
		self.assertEqual(result["data"]["templates"][0]["orientation"], "Portrait")
		self.assertTrue(result["data"]["templates"][0]["managed"])
		self.assertTrue(result["data"]["templates"][0]["template_version"])
		self.assertTrue(result["data"]["templates"][0]["template_hash"])
		self.assertIn("preview", result["data"]["capabilities"])

	def test_attach_printing_derived_fields_adds_governance_labels(self):
		from myapp.services.printing_service import _attach_printing_derived_fields

		document = frappe._dict(
			{
				"doctype": "Sales Invoice",
				"name": "SINV-0001",
				"docstatus": 0,
				"grand_total": 123.45,
			}
		)
		with patch(
			"myapp.services.printing_service._get_print_history_summary",
			return_value={
				"total_count": 0,
				"successful_count": 0,
				"latest_printed_by": None,
				"latest_printed_at": None,
			},
		):
			_attach_printing_derived_fields(document)

		self.assertEqual(document.myapp_print_status_label, "草稿")
		self.assertEqual(document.myapp_print_copy_label, "首次打印")
		self.assertEqual(document.myapp_print_watermark, "草稿")
		self.assertEqual(document.myapp_amount_in_words_zh, "壹佰贰拾叁元肆角伍分")

	def test_attach_printing_derived_fields_marks_reprint(self):
		from myapp.services.printing_service import _attach_printing_derived_fields

		document = frappe._dict(
			{
				"doctype": "Sales Invoice",
				"name": "SINV-0001",
				"docstatus": 1,
				"grand_total": 100,
			}
		)
		with patch(
			"myapp.services.printing_service._get_print_history_summary",
			return_value={
				"total_count": 2,
				"successful_count": 2,
				"latest_printed_by": "test@example.com",
				"latest_printed_at": "2026-07-09 10:30:00",
			},
		):
			_attach_printing_derived_fields(document)

		self.assertEqual(document.myapp_print_status_label, "正式")
		self.assertEqual(document.myapp_print_copy_label, "第 3 次打印")
		self.assertEqual(document.myapp_print_watermark, "补打")

	@patch("myapp.services.printing_service._load_print_document")
	@patch("myapp.services.printing_service._print_job_table_exists", return_value=False)
	def test_record_print_job_v1_skips_when_table_missing(self, mock_table_exists, mock_load_print_document):
		mock_load_print_document.return_value = frappe._dict({"doctype": "Sales Invoice", "name": "SINV-0001"})

		result = record_print_job_v1(doctype="Sales Invoice", docname="SINV-0001", action="download")

		self.assertEqual(result["status"], "success")
		self.assertFalse(result["data"]["recorded"])
		self.assertEqual(result["data"]["reason"], "table_missing")
		mock_table_exists.assert_called_once()

	@patch("myapp.services.printing_service.uuid4")
	@patch("myapp.services.printing_service.now_datetime")
	@patch("myapp.services.printing_service._load_print_document")
	@patch("myapp.services.printing_service._print_job_table_exists", return_value=True)
	def test_record_print_job_v1_inserts_audit_row(
		self,
		mock_table_exists,
		mock_load_print_document,
		mock_now_datetime,
		mock_uuid4,
	):
		from datetime import datetime

		mock_load_print_document.return_value = frappe._dict({"doctype": "Sales Invoice", "name": "SINV-0001"})
		mock_now_datetime.return_value = datetime(2026, 7, 9, 10, 30, 0)
		mock_uuid4.return_value.hex = "abcdef1234567890"

		with patch("myapp.services.printing_service.frappe") as mock_frappe:
			mock_frappe.session.user = "test@example.com"
			result = record_print_job_v1(
				doctype="Sales Invoice",
				docname="SINV-0001",
				action="share",
				filename="invoice.pdf",
				metadata={"source": "mobile"},
			)

		self.assertTrue(result["data"]["recorded"])
		self.assertEqual(result["data"]["job_id"], "PRN-JOB-20260709103000-abcdef12")
		self.assertEqual(result["data"]["action"], "share")
		mock_frappe.db.sql.assert_called_once()
		self.assertIn("template_hash", mock_frappe.db.sql.call_args.args[1][-1])
		mock_frappe.db.commit.assert_called_once()

	@patch("myapp.services.printing_service._load_print_document")
	@patch("myapp.services.printing_service._print_job_table_exists", return_value=True)
	def test_list_print_jobs_v1_returns_rows(self, mock_table_exists, mock_load_print_document):
		mock_load_print_document.return_value = frappe._dict({"doctype": "Sales Invoice", "name": "SINV-0001"})

		with patch("myapp.services.printing_service.frappe") as mock_frappe:
			mock_frappe.db.sql.return_value = [
				frappe._dict(
					{
						"name": "PRN-JOB-001",
						"reference_doctype": "Sales Invoice",
						"reference_name": "SINV-0001",
						"template": "standard",
						"template_label": "标准发票",
						"print_format": "myapp Sales Invoice Standard",
						"action": "download",
						"output": "pdf",
						"status": "success",
						"filename": "invoice.pdf",
						"file_url": None,
						"printed_by": "test@example.com",
						"printed_at": "2026-07-09 10:30:00",
						"error": None,
						"metadata_json": '{"source": "web"}',
					}
				)
			]

			result = list_print_jobs_v1(doctype="Sales Invoice", docname="SINV-0001", action="download", limit=5)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["count"], 1)
		self.assertTrue(result["data"]["table_ready"])
		self.assertEqual(result["data"]["jobs"][0]["job_id"], "PRN-JOB-001")
		self.assertEqual(result["data"]["jobs"][0]["metadata"]["source"], "web")
		mock_frappe.db.sql.assert_called_once()

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

	@patch("myapp.services.printing_service._render_print_pdf")
	@patch("myapp.services.printing_service._load_print_document")
	@patch("myapp.services.printing_service._ensure_template_ready")
	def test_get_print_file_v1_returns_stream_metadata_by_default(
		self,
		mock_ensure_template_ready,
		mock_load_print_document,
		mock_render_print_pdf,
	):
		document = frappe._dict({"doctype": "Sales Invoice", "name": "SINV-0001"})
		mock_load_print_document.return_value = document
		mock_render_print_pdf.return_value = b"%PDF-test"

		result = get_print_file_v1(doctype="Sales Invoice", docname="SINV-0001")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["output"], "pdf")
		self.assertEqual(result["data"]["mime_type"], "application/pdf")
		self.assertEqual(result["data"]["filename"], "Sales Invoice-SINV-0001-standard.pdf")
		self.assertEqual(result["data"]["status"], "ready")
		self.assertEqual(result["data"]["file_size"], 9)
		self.assertIsNone(result["data"]["file_url"])
		self.assertTrue(result["data"]["is_private"])
		self.assertFalse(result["data"]["archived"])
		self.assertEqual(result["data"]["storage_mode"], "stream")
		mock_ensure_template_ready.assert_called_once()

	@patch("myapp.services.printing_service._save_print_pdf_file")
	@patch("myapp.services.printing_service._render_print_pdf")
	@patch("myapp.services.printing_service._load_print_document")
	@patch("myapp.services.printing_service._ensure_template_ready")
	def test_get_print_file_v1_archives_file_when_requested(
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

		result = get_print_file_v1(doctype="Sales Invoice", docname="SINV-0001", archive=1)

		self.assertEqual(result["data"]["file_url"], "/private/files/invoice.pdf")
		self.assertEqual(result["data"]["status"], "archived")
		self.assertTrue(result["data"]["archived"])
		self.assertEqual(result["data"]["storage_mode"], "archive")
		mock_save_print_pdf_file.assert_called_once()

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

	def test_coerce_bool_flag_handles_common_truthy_values(self):
		from myapp.services.printing_service import _coerce_bool_flag

		self.assertTrue(_coerce_bool_flag(True))
		self.assertTrue(_coerce_bool_flag("1"))
		self.assertTrue(_coerce_bool_flag("true"))
		self.assertFalse(_coerce_bool_flag(False))
		self.assertFalse(_coerce_bool_flag("0"))

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
