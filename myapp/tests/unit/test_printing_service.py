from unittest import TestCase
from unittest.mock import Mock, patch
from zipfile import ZipFile
from io import BytesIO

import frappe

from myapp.services.printing_service import (
	build_print_batch_archive_download_v1,
	build_print_file_download_v1,
	cancel_print_batch_v1,
	cleanup_expired_print_batches,
	create_print_batch_v1,
	get_print_file_v1,
	get_print_batch_v1,
	get_print_preview_v1,
	get_print_settings_v1,
	get_print_templates_v1,
	list_print_jobs_v1,
	list_print_doctypes_v1,
	process_print_batch_v1,
	record_print_job_v1,
	retry_print_batch_failed_v1,
	set_print_default_template_v1,
)


class TestPrintingService(TestCase):
	def test_list_print_doctypes_v1_returns_registered_documents(self):
		result = list_print_doctypes_v1()

		self.assertEqual(result["status"], "success")
		self.assertGreaterEqual(result["data"]["count"], 6)
		self.assertEqual(result["data"]["doctypes"][0]["capabilities"], ["preview", "download_pdf", "archive_pdf"])
		self.assertIn("templates", result["data"]["doctypes"][0])

	@patch("myapp.printing.registry.frappe.get_roles", return_value=["System Manager"])
	def test_get_print_templates_v1_returns_doctype_templates(self, mock_get_roles):
		result = get_print_templates_v1("Sales Invoice")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["doctype"], "Sales Invoice")
		self.assertEqual(result["data"]["default_template"], "standard")
		self.assertGreaterEqual(len(result["data"]["templates"]), 2)
		self.assertEqual(result["data"]["templates"][0]["paper_size"], "A4")
		self.assertEqual(result["data"]["templates"][0]["orientation"], "Portrait")
		self.assertTrue(result["data"]["templates"][0]["managed"])
		self.assertTrue(result["data"]["templates"][0]["template_version"])
		self.assertTrue(result["data"]["templates"][0]["template_hash"])
		self.assertIn("preview", result["data"]["capabilities"])
		self.assertEqual(result["data"]["templates"][1]["key"], "finance")
		self.assertEqual(result["data"]["templates"][1]["category"], "finance")
		self.assertEqual(result["data"]["templates"][1]["print_format"], "myapp Sales Invoice Finance")
		self.assertTrue(result["data"]["templates"][1]["managed"])
		self.assertTrue(result["data"]["templates"][1]["template_version"])
		self.assertTrue(result["data"]["templates"][1]["template_hash"])
		self.assertTrue(result["data"]["templates"][1]["restricted"])
		self.assertIn("Accounts User", result["data"]["templates"][1]["allowed_roles"])

	@patch("myapp.printing.registry.frappe.get_roles", return_value=["Sales User"])
	def test_get_print_templates_v1_hides_restricted_templates_without_role(self, mock_get_roles):
		result = get_print_templates_v1("Sales Invoice")

		self.assertEqual([item["key"] for item in result["data"]["templates"]], ["standard"])
		self.assertEqual(result["data"]["default_template"], "standard")

	@patch("myapp.printing.registry.frappe.get_roles", return_value=["Accounts User"])
	def test_get_print_templates_v1_allows_finance_role(self, mock_get_roles):
		result = get_print_templates_v1("Sales Invoice")

		self.assertEqual([item["key"] for item in result["data"]["templates"]], ["standard", "finance"])

	@patch("myapp.printing.registry.frappe.get_roles", return_value=["Sales User"])
	def test_resolve_print_template_rejects_restricted_template_without_role(self, mock_get_roles):
		from myapp.printing.registry import resolve_print_template

		with self.assertRaises(Exception):
			resolve_print_template("Sales Invoice", "finance")

	@patch("myapp.printing.registry._get_configured_default_template_key", return_value="finance")
	@patch("myapp.printing.registry.frappe.get_roles", return_value=["Accounts User"])
	def test_resolve_print_template_uses_configured_default_when_allowed(
		self,
		mock_get_roles,
		mock_get_configured_default_template_key,
	):
		from myapp.printing.registry import resolve_print_template

		template = resolve_print_template("Sales Invoice")

		self.assertEqual(template["key"], "finance")

	@patch("myapp.printing.registry._get_configured_default_template_key", return_value="finance")
	@patch("myapp.printing.registry.frappe.get_roles", return_value=["Sales User"])
	def test_resolve_print_template_falls_back_when_configured_default_not_allowed(
		self,
		mock_get_roles,
		mock_get_configured_default_template_key,
	):
		from myapp.printing.registry import resolve_print_template

		template = resolve_print_template("Sales Invoice")

		self.assertEqual(template["key"], "standard")

	@patch("myapp.services.printing_service._print_setting_table_exists", return_value=True)
	def test_get_print_settings_v1_returns_rows(self, mock_table_exists):
		with patch("myapp.services.printing_service.frappe") as mock_frappe:
			mock_frappe.db.sql.return_value = [
				frappe._dict(
					{
						"name": "PRINT-SETTING-Sales Invoice",
						"reference_doctype": "Sales Invoice",
						"default_template": "finance",
						"enabled": 1,
						"metadata_json": '{"source": "admin"}',
						"modified": "2026-07-10 10:00:00",
						"modified_by": "admin@example.com",
					}
				)
			]

			result = get_print_settings_v1()

		self.assertEqual(result["data"]["count"], 1)
		self.assertEqual(result["data"]["settings"][0]["default_template"], "finance")
		self.assertEqual(result["data"]["settings"][0]["metadata"]["source"], "admin")

	@patch("myapp.services.printing_service._print_setting_table_exists", return_value=True)
	@patch("myapp.services.printing_service.now_datetime", return_value="2026-07-10 10:00:00")
	@patch("myapp.services.printing_service._current_user", return_value="admin@example.com")
	@patch("myapp.printing.registry.frappe.get_roles", return_value=["System Manager"])
	@patch("myapp.services.printing_service.frappe.get_roles", return_value=["System Manager"])
	def test_set_print_default_template_v1_upserts_setting(
		self,
		mock_service_get_roles,
		mock_registry_get_roles,
		mock_current_user,
		mock_now_datetime,
		mock_table_exists,
	):
		with patch("myapp.services.printing_service.frappe") as mock_frappe:
			mock_frappe.get_roles.return_value = ["System Manager"]
			mock_frappe.db.sql.return_value = None
			result = set_print_default_template_v1(
				doctype="Sales Invoice",
				template="finance",
				metadata={"source": "admin"},
			)

		self.assertTrue(result["data"]["saved"])
		self.assertEqual(result["data"]["default_template"], "finance")
		self.assertIn("ON DUPLICATE KEY UPDATE", mock_frappe.db.sql.call_args.args[0])

	@patch("myapp.services.printing_service.frappe.get_roles", return_value=["Sales User"])
	def test_set_print_default_template_v1_requires_system_manager(self, mock_get_roles):
		with self.assertRaises(frappe.PermissionError):
			set_print_default_template_v1(doctype="Sales Invoice", template="standard")

	@patch("myapp.services.printing_service._render_print_preview_payload")
	@patch("myapp.services.printing_service._load_print_document")
	@patch("myapp.services.printing_service._ensure_template_ready")
	@patch("myapp.printing.registry.frappe.get_roles", return_value=["System Manager"])
	def test_get_print_preview_v1_accepts_secondary_template(
		self,
		mock_get_roles,
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
				"key": "finance",
				"label": "财务留档",
				"print_format": "myapp Sales Invoice Finance",
				"is_default": False,
				"source": "myapp",
			},
			"available_templates": [],
			"output": "html",
			"html": "<html />",
			"mime_type": "text/html",
		}

		result = get_print_preview_v1(doctype="Sales Invoice", docname="SINV-0001", template="finance")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["meta"]["template"], "finance")
		mock_ensure_template_ready.assert_called_once()
		self.assertEqual(mock_ensure_template_ready.call_args.args[0]["print_format"], "myapp Sales Invoice Finance")
		mock_load_print_document.assert_called_once_with("Sales Invoice", "SINV-0001")

	@patch("myapp.services.printing_service.get_print_batch_v1")
	@patch("myapp.services.printing_service._update_print_batch_enqueue_job_id")
	@patch("myapp.services.printing_service._enqueue_print_batch", return_value="rq-job-001")
	@patch("myapp.services.printing_service._insert_print_batch", return_value="PRN-BATCH-001")
	@patch("myapp.services.printing_service._print_batch_table_exists", return_value=True)
	@patch("myapp.printing.registry.frappe.get_roles", return_value=["System Manager"])
	def test_create_print_batch_v1_queues_batch(
		self,
		mock_get_roles,
		mock_table_exists,
		mock_insert_print_batch,
		mock_enqueue_print_batch,
		mock_update_enqueue_job_id,
		mock_get_print_batch,
	):
		mock_get_print_batch.return_value = {
			"status": "success",
			"data": {
				"batch_id": "PRN-BATCH-001",
				"status": "queued",
				"total_count": 2,
			},
		}

		result = create_print_batch_v1(
			documents=[
				{"doctype": "Sales Invoice", "docname": "SINV-0001", "template": "finance"},
				{"doctype": "Sales Invoice", "docname": "SINV-0002"},
			],
			metadata={"source": "web"},
		)

		self.assertEqual(result["status"], "success")
		self.assertTrue(result["data"]["queued"])
		self.assertEqual(result["data"]["batch_id"], "PRN-BATCH-001")
		self.assertEqual(result["data"]["enqueue_job_id"], "rq-job-001")
		mock_table_exists.assert_called_once()
		mock_insert_print_batch.assert_called_once()
		insert_items = mock_insert_print_batch.call_args.kwargs["items"]
		self.assertEqual(insert_items[0]["template"], "finance")
		self.assertEqual(insert_items[1]["template"], "standard")
		mock_enqueue_print_batch.assert_called_once_with("PRN-BATCH-001")
		mock_update_enqueue_job_id.assert_called_once_with("PRN-BATCH-001", "rq-job-001")

	@patch("myapp.services.printing_service._print_batch_table_exists", return_value=True)
	def test_get_print_batch_v1_returns_progress(self, mock_table_exists):
		with patch("myapp.services.printing_service.frappe") as mock_frappe:
			mock_frappe.db.sql.return_value = [
				frappe._dict(
					{
						"name": "PRN-BATCH-001",
						"status": "partial_failed",
						"output": "pdf",
						"requested_by": "test@example.com",
						"requested_at": "2026-07-09 10:30:00",
						"started_at": "2026-07-09 10:31:00",
						"completed_at": "2026-07-09 10:32:00",
						"enqueue_job_id": "rq-job-001",
						"total_count": 2,
						"success_count": 1,
						"failed_count": 1,
						"skipped_count": 0,
						"items_json": '[{"doctype": "Sales Invoice", "docname": "SINV-0001"}]',
						"results_json": '[{"status": "success"}]',
						"metadata_json": '{"source": "web"}',
						"error": None,
					}
				)
			]

			result = get_print_batch_v1("PRN-BATCH-001")

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["batch_id"], "PRN-BATCH-001")
		self.assertEqual(result["data"]["progress"], 1)
		self.assertEqual(result["data"]["metadata"]["source"], "web")
		mock_table_exists.assert_called_once()

	@patch("myapp.services.printing_service._update_print_batch_results")
	@patch("myapp.services.printing_service._update_print_batch_status")
	@patch("myapp.services.printing_service._process_print_batch_item")
	@patch("myapp.services.printing_service._get_print_batch_row")
	@patch("myapp.services.printing_service._print_batch_table_exists", return_value=True)
	def test_process_print_batch_v1_updates_partial_failed_status(
		self,
		mock_table_exists,
		mock_get_print_batch_row,
		mock_process_print_batch_item,
		mock_update_print_batch_status,
		mock_update_print_batch_results,
	):
		mock_get_print_batch_row.return_value = frappe._dict(
			{
				"name": "PRN-BATCH-001",
				"status": "queued",
				"requested_by": "test@example.com",
				"items_json": '[{"idx": 1, "doctype": "Sales Invoice", "docname": "SINV-0001"}, {"idx": 2, "doctype": "Sales Invoice", "docname": "SINV-0002"}]',
			}
		)
		mock_process_print_batch_item.side_effect = [
			{"idx": 1, "status": "success"},
			{"idx": 2, "status": "failed", "error": "boom"},
		]

		with patch("myapp.services.printing_service.frappe.set_user") as mock_set_user:
			result = process_print_batch_v1("PRN-BATCH-001")

		self.assertEqual(result["status"], "partial_failed")
		self.assertEqual(result["success_count"], 1)
		self.assertEqual(result["failed_count"], 1)
		mock_set_user.assert_called_once_with("test@example.com")
		mock_update_print_batch_status.assert_called_once_with("PRN-BATCH-001", "processing", started=True)
		self.assertEqual(mock_update_print_batch_results.call_args.kwargs["final_status"], "partial_failed")
		self.assertTrue(mock_update_print_batch_results.call_args.kwargs["completed"])

	@patch("myapp.services.printing_service._update_print_batch_results")
	@patch("myapp.services.printing_service._update_print_batch_status")
	@patch("myapp.services.printing_service._get_print_batch_row")
	@patch("myapp.services.printing_service._print_batch_table_exists", return_value=True)
	def test_process_print_batch_v1_skips_items_when_cancel_requested(
		self,
		mock_table_exists,
		mock_get_print_batch_row,
		mock_update_print_batch_status,
		mock_update_print_batch_results,
	):
		mock_get_print_batch_row.return_value = frappe._dict(
			{
				"name": "PRN-BATCH-001",
				"status": "cancel_requested",
				"requested_by": "test@example.com",
				"items_json": '[{"idx": 1, "doctype": "Sales Invoice", "docname": "SINV-0001"}]',
			}
		)

		result = process_print_batch_v1("PRN-BATCH-001")

		self.assertEqual(result["status"], "canceled")
		self.assertEqual(result["skipped_count"], 1)
		mock_update_print_batch_status.assert_not_called()
		self.assertEqual(mock_update_print_batch_results.call_args.kwargs["final_status"], "canceled")
		self.assertTrue(mock_update_print_batch_results.call_args.kwargs["completed"])

	@patch("myapp.services.printing_service.record_print_job_v1")
	@patch("myapp.services.printing_service.get_print_file_v1")
	def test_process_print_batch_item_archives_pdf_and_records_job(self, mock_get_print_file, mock_record_print_job):
		from myapp.services.printing_service import _process_print_batch_item

		mock_get_print_file.return_value = {
			"status": "success",
			"data": {
				"filename": "SINV-0001-finance.pdf",
				"file_url": "/private/files/SINV-0001-finance.pdf",
				"file_size": 2048,
			},
		}

		result = _process_print_batch_item(
			"PRN-BATCH-001",
			{"idx": 1, "doctype": "Sales Invoice", "docname": "SINV-0001", "template": "finance"},
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["file_url"], "/private/files/SINV-0001-finance.pdf")
		mock_get_print_file.assert_called_once_with(
			doctype="Sales Invoice",
			docname="SINV-0001",
			template="finance",
			filename=None,
			archive=True,
		)
		mock_record_print_job.assert_called_once()
		self.assertEqual(mock_record_print_job.call_args.kwargs["action"], "archive")
		self.assertEqual(mock_record_print_job.call_args.kwargs["metadata"]["batch_id"], "PRN-BATCH-001")

	@patch("myapp.services.printing_service._read_file_url_bytes")
	@patch("myapp.services.printing_service.get_print_batch_v1")
	def test_build_print_batch_archive_download_v1_returns_zip(self, mock_get_print_batch, mock_read_file_url_bytes):
		mock_get_print_batch.return_value = {
			"status": "success",
			"data": {
				"batch_id": "PRN-BATCH-001",
				"table_ready": True,
				"results": [
					{
						"idx": 1,
						"doctype": "Sales Invoice",
						"docname": "SINV-0001",
						"status": "success",
						"filename": "invoice.pdf",
						"file_url": "/private/files/invoice-1.pdf",
					},
					{
						"idx": 2,
						"doctype": "Sales Invoice",
						"docname": "SINV-0002",
						"status": "success",
						"filename": "invoice.pdf",
						"file_url": "/private/files/invoice-2.pdf",
					},
					{
						"idx": 3,
						"doctype": "Sales Invoice",
						"docname": "SINV-0003",
						"status": "failed",
						"error": "boom",
					},
				],
			},
		}
		mock_read_file_url_bytes.side_effect = [b"%PDF-1", b"%PDF-2"]

		result = build_print_batch_archive_download_v1("PRN-BATCH-001", filename="batch")

		self.assertEqual(result["filename"], "batch.zip")
		self.assertEqual(result["file_count"], 2)
		with ZipFile(BytesIO(result["content"])) as archive:
			self.assertEqual(sorted(archive.namelist()), ["invoice-2.pdf", "invoice.pdf"])
			self.assertEqual(archive.read("invoice.pdf"), b"%PDF-1")
			self.assertEqual(archive.read("invoice-2.pdf"), b"%PDF-2")
		mock_get_print_batch.assert_called_once_with("PRN-BATCH-001")

	@patch("myapp.services.printing_service._update_print_batch_results")
	@patch("myapp.services.printing_service._get_print_batch_row")
	@patch("myapp.services.printing_service._print_batch_table_exists", return_value=True)
	def test_cancel_print_batch_v1_cancels_queued_batch(
		self,
		mock_table_exists,
		mock_get_print_batch_row,
		mock_update_print_batch_results,
	):
		mock_get_print_batch_row.return_value = frappe._dict(
			{
				"name": "PRN-BATCH-001",
				"status": "queued",
				"items_json": '[{"idx": 1, "doctype": "Sales Invoice", "docname": "SINV-0001"}]',
			}
		)

		result = cancel_print_batch_v1("PRN-BATCH-001")

		self.assertTrue(result["data"]["canceled"])
		self.assertEqual(result["data"]["status"], "canceled")
		mock_update_print_batch_results.assert_called_once()
		self.assertEqual(mock_update_print_batch_results.call_args.kwargs["final_status"], "canceled")
		self.assertEqual(mock_update_print_batch_results.call_args.kwargs["skipped_count"], 1)

	@patch("myapp.services.printing_service._update_print_batch_status")
	@patch("myapp.services.printing_service._get_print_batch_row")
	@patch("myapp.services.printing_service._print_batch_table_exists", return_value=True)
	def test_cancel_print_batch_v1_requests_cancel_for_processing_batch(
		self,
		mock_table_exists,
		mock_get_print_batch_row,
		mock_update_print_batch_status,
	):
		mock_get_print_batch_row.return_value = frappe._dict({"name": "PRN-BATCH-001", "status": "processing"})

		result = cancel_print_batch_v1("PRN-BATCH-001")

		self.assertTrue(result["data"]["cancel_requested"])
		mock_update_print_batch_status.assert_called_once_with("PRN-BATCH-001", "cancel_requested")

	@patch("myapp.services.printing_service.create_print_batch_v1")
	@patch("myapp.services.printing_service.get_print_batch_v1")
	def test_retry_print_batch_failed_v1_creates_new_batch_from_failed_items(
		self,
		mock_get_print_batch,
		mock_create_print_batch,
	):
		mock_get_print_batch.return_value = {
			"status": "success",
			"data": {
				"batch_id": "PRN-BATCH-001",
				"table_ready": True,
				"output": "pdf",
				"results": [
					{"idx": 1, "doctype": "Sales Invoice", "docname": "SINV-0001", "template": "finance", "status": "success"},
					{"idx": 2, "doctype": "Sales Invoice", "docname": "SINV-0002", "template": "finance", "status": "failed"},
				],
			},
		}
		mock_create_print_batch.return_value = {
			"status": "success",
			"data": {"batch_id": "PRN-BATCH-002"},
		}

		result = retry_print_batch_failed_v1("PRN-BATCH-001", run_async=0, metadata={"source": "retry-button"})

		self.assertEqual(result["data"]["retry_of"], "PRN-BATCH-001")
		mock_create_print_batch.assert_called_once_with(
			documents=[
				{
					"doctype": "Sales Invoice",
					"docname": "SINV-0002",
					"template": "finance",
					"filename": None,
				}
			],
			output="pdf",
			run_async=0,
			metadata={"source": "retry-button", "retry_of": "PRN-BATCH-001"},
		)

	@patch("myapp.services.printing_service._print_batch_table_exists", return_value=True)
	@patch("myapp.services.printing_service.now_datetime", return_value="2026-07-09 10:00:00")
	@patch("myapp.services.printing_service.frappe")
	def test_cleanup_expired_print_batches_deletes_final_batches_and_archived_files(
		self,
		mock_frappe,
		mock_now_datetime,
		mock_table_exists,
	):
		mock_frappe.db.sql.side_effect = [
			[
				frappe._dict(
					{
						"name": "PRN-BATCH-001",
						"results_json": '[{"status": "success", "file_url": "/private/files/a.pdf"}, {"status": "failed"}]',
					}
				)
			],
			None,
		]
		mock_frappe.get_all.return_value = [{"name": "FILE-001"}]

		result = cleanup_expired_print_batches(retention_days=30, batch_size=10)

		self.assertEqual(result["data"]["deleted_count"], 1)
		self.assertEqual(result["data"]["deleted_file_count"], 1)
		self.assertIn("status IN ('completed', 'partial_failed', 'failed', 'canceled')", mock_frappe.db.sql.call_args_list[0].args[0])
		self.assertIn("DELETE FROM `tabMyApp Print Batch`", mock_frappe.db.sql.call_args_list[1].args[0])
		mock_frappe.get_all.assert_called_once_with(
			"File",
			filters={"file_url": "/private/files/a.pdf"},
			fields=["name"],
			limit=1,
		)
		mock_frappe.delete_doc.assert_called_once_with("File", "FILE-001", ignore_permissions=True)

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

	@patch("myapp.services.printing_service._print_job_table_exists", return_value=True)
	def test_print_history_summary_does_not_count_preview_as_print_copy(self, mock_table_exists):
		from myapp.services.printing_service import _get_print_history_summary

		with patch("myapp.services.printing_service.frappe") as mock_frappe:
			mock_frappe.db.sql.side_effect = [
				[
					frappe._dict(
						{
							"total_count": 3,
							"successful_count": 1,
							"latest_printed_at": "2026-07-10 10:00:00",
						}
					)
				],
				[frappe._dict({"printed_by": "test@example.com"})],
			]

			summary = _get_print_history_summary("Sales Invoice", "SINV-0001")

		self.assertEqual(summary["total_count"], 3)
		self.assertEqual(summary["successful_count"], 1)
		self.assertIn("action IN ('download', 'print', 'share', 'archive')", mock_frappe.db.sql.call_args_list[0].args[0])

	def test_attach_print_template_fields_adds_template_context(self):
		from myapp.services.printing_service import _attach_print_template_fields

		document = frappe._dict({"doctype": "Sales Invoice", "name": "SINV-0001"})
		_attach_print_template_fields(
			document,
			{
				"key": "finance",
				"label": "财务留档",
				"category": "finance",
				"print_format": "myapp Sales Invoice Finance",
			},
		)

		self.assertEqual(document.myapp_print_template_key, "finance")
		self.assertEqual(document.myapp_print_template_label, "财务留档")
		self.assertEqual(document.myapp_print_template_category, "finance")
		self.assertEqual(document.myapp_print_format, "myapp Sales Invoice Finance")

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
