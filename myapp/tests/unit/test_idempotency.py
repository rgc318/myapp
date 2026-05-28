from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

import frappe

from myapp.utils.idempotency import IdempotencyConflictError, build_request_fingerprint, run_idempotent


class TestIdempotency(TestCase):
	@patch("myapp.utils.idempotency.store_idempotent_result")
	@patch("myapp.utils.idempotency.get_idempotent_result")
	def test_run_idempotent_returns_cached_result(self, mock_get_idempotent_result, mock_store_idempotent_result):
		mock_get_idempotent_result.return_value = {"status": "success", "order": "SO-0001"}

		callback_called = False

		def callback():
			nonlocal callback_called
			callback_called = True
			return {"status": "success", "order": "SO-0002"}

		result = run_idempotent("create_order_immediate", "req-1", callback)

		self.assertEqual(result["order"], "SO-0001")
		self.assertFalse(callback_called)
		mock_store_idempotent_result.assert_not_called()

	@patch("myapp.utils.idempotency.store_idempotent_result")
	@patch("myapp.utils.idempotency.filelock")
	@patch("myapp.utils.idempotency.get_idempotent_result")
	def test_run_idempotent_rechecks_cache_inside_lock(
		self, mock_get_idempotent_result, mock_filelock, mock_store_idempotent_result
	):
		mock_get_idempotent_result.side_effect = [
			None,
			{"status": "success", "order": "SO-0009"},
		]
		mock_filelock.return_value = MagicMock()

		callback_called = False

		def callback():
			nonlocal callback_called
			callback_called = True
			return {"status": "success", "order": "SO-0010"}

		result = run_idempotent("create_order", "req-9", callback)

		self.assertEqual(result["order"], "SO-0009")
		self.assertFalse(callback_called)
		mock_store_idempotent_result.assert_not_called()
		mock_filelock.assert_called_once()

	@patch("myapp.utils.idempotency.store_idempotent_result")
	@patch("myapp.utils.idempotency.filelock")
	def test_run_idempotent_without_request_id_skips_lock(self, mock_filelock, mock_store_idempotent_result):
		mock_store_idempotent_result.return_value = {"status": "success", "order": "SO-0011"}

		result = run_idempotent("create_order", None, lambda: {"status": "success", "order": "SO-0011"})

		self.assertEqual(result["order"], "SO-0011")
		mock_filelock.assert_not_called()

	@patch("myapp.utils.idempotency._run_persistent_idempotent")
	@patch("myapp.utils.idempotency._table_exists", return_value=True)
	@patch("myapp.utils.idempotency.get_idempotent_result", return_value=None)
	@patch("myapp.utils.idempotency._get_request_header", return_value=None)
	def test_run_idempotent_uses_persistent_store_when_table_exists(
		self, mock_get_request_header, mock_get_idempotent_result, mock_table_exists, mock_run_persistent
	):
		mock_run_persistent.return_value = {"status": "success", "order": "SO-0020"}

		result = run_idempotent("create_order", "req-20", lambda: {"status": "success", "order": "SO-0021"})

		self.assertEqual(result["order"], "SO-0020")
		mock_table_exists.assert_called_once()
		args = mock_run_persistent.call_args.args
		self.assertEqual(args[0], "create_order")
		self.assertEqual(args[1], "req-20")

	@patch("myapp.utils.idempotency._run_persistent_idempotent")
	@patch("myapp.utils.idempotency._table_exists", return_value=True)
	@patch("myapp.utils.idempotency.get_idempotent_result", return_value=None)
	@patch("myapp.utils.idempotency._get_request_header")
	def test_run_idempotent_prefers_idempotency_key_header(
		self, mock_get_request_header, mock_get_idempotent_result, mock_table_exists, mock_run_persistent
	):
		mock_get_request_header.side_effect = lambda header_name: "header-req-1" if header_name == "Idempotency-Key" else None
		mock_run_persistent.return_value = {"status": "success", "order": "SO-0022"}

		result = run_idempotent("create_order", "body-req-1", lambda: {"status": "success", "order": "SO-0023"})

		self.assertEqual(result["order"], "SO-0022")
		args = mock_run_persistent.call_args.args
		self.assertEqual(args[1], "header-req-1")

	@patch("myapp.utils.idempotency._refresh_transaction_snapshot")
	@patch("myapp.utils.idempotency.store_idempotent_result")
	@patch(
		"myapp.utils.idempotency._get_record",
		return_value=SimpleNamespace(
			status="succeeded",
			request_hash=None,
			response_json='{"status": "success", "order": "SO-0030"}',
			error=None,
		),
	)
	@patch("myapp.utils.idempotency.get_idempotent_result", return_value=None)
	def test_wait_for_record_result_returns_persisted_response(
		self, mock_get_idempotent_result, mock_get_record, mock_store_idempotent_result, mock_refresh_snapshot
	):
		from myapp.utils.idempotency import _wait_for_record_result

		mock_store_idempotent_result.return_value = {"status": "success", "order": "SO-0030"}

		result = _wait_for_record_result("create_order", "req-30", None)

		self.assertEqual(result["order"], "SO-0030")
		mock_store_idempotent_result.assert_called_once()
		mock_refresh_snapshot.assert_called_once()

	def test_build_request_fingerprint_is_stable_and_ignores_cmd(self):
		first_hash, first_json = build_request_fingerprint(
			{"cmd": "myapp.api.gateway.create_order", "items": [{"qty": 1}], "customer": "CUST-001"}
		)
		second_hash, second_json = build_request_fingerprint({"customer": "CUST-001", "items": [{"qty": 1}]})

		self.assertEqual(first_hash, second_hash)
		self.assertEqual(first_json, second_json)

	def test_build_request_fingerprint_changes_when_payload_changes(self):
		first_hash, _first_json = build_request_fingerprint({"customer": "CUST-001", "qty": 1})
		second_hash, _second_json = build_request_fingerprint({"customer": "CUST-001", "qty": 2})

		self.assertNotEqual(first_hash, second_hash)

	def test_wait_for_record_result_rejects_same_request_id_with_different_payload(self):
		from myapp.utils.idempotency import _wait_for_record_result

		stored_hash, _stored_json = build_request_fingerprint({"qty": 1})
		incoming_hash, _incoming_json = build_request_fingerprint({"qty": 2})

		with (
			patch("myapp.utils.idempotency._refresh_transaction_snapshot"),
			patch(
				"myapp.utils.idempotency._get_record",
				return_value=SimpleNamespace(
					status="succeeded",
					request_hash=stored_hash,
					response_json='{"status": "success"}',
					error=None,
				),
			),
		):
			with self.assertRaises(IdempotencyConflictError):
				_wait_for_record_result("create_order", "req-31", incoming_hash)

	def test_concurrent_insert_conflict_is_recognized_for_idempotency_table(self):
		from myapp.utils.idempotency import _is_concurrent_insert_conflict

		exc = Exception(1020, "Record has changed since last read in table 'tabMyApp Idempotency Key'")

		self.assertTrue(_is_concurrent_insert_conflict(exc))

	@patch("myapp.utils.idempotency._mark_record_failed")
	@patch("myapp.utils.idempotency._insert_processing_record", return_value=True)
	def test_persistent_store_marks_validation_failure_as_final(self, mock_insert_processing_record, mock_mark_record_failed):
		from myapp.utils.idempotency import _run_persistent_idempotent

		def callback():
			raise frappe.ValidationError("missing customer")

		with self.assertRaises(frappe.ValidationError):
			_run_persistent_idempotent("create_order", "req-final-fail", None, None, callback, 60)

		mock_mark_record_failed.assert_called_once()
		self.assertFalse(mock_mark_record_failed.call_args.kwargs["retryable"])

	@patch("myapp.utils.idempotency._mark_record_failed")
	@patch("myapp.utils.idempotency._insert_processing_record", return_value=True)
	def test_persistent_store_marks_system_failure_as_retryable(self, mock_insert_processing_record, mock_mark_record_failed):
		from myapp.utils.idempotency import _run_persistent_idempotent

		def callback():
			raise RuntimeError("database temporarily unavailable")

		with self.assertRaises(RuntimeError):
			_run_persistent_idempotent("create_order", "req-retryable-fail", None, None, callback, 60)

		mock_mark_record_failed.assert_called_once()
		self.assertTrue(mock_mark_record_failed.call_args.kwargs["retryable"])

	@patch("myapp.utils.idempotency._execute_and_store_result")
	@patch("myapp.utils.idempotency._claim_retryable_record", return_value=True)
	@patch("myapp.utils.idempotency._insert_processing_record", return_value=False)
	def test_persistent_store_retries_previous_retryable_failure(
		self, mock_insert_processing_record, mock_claim_retryable_record, mock_execute_and_store_result
	):
		from myapp.utils.idempotency import _run_persistent_idempotent

		mock_execute_and_store_result.return_value = {"status": "success", "order": "SO-0040"}

		result = _run_persistent_idempotent(
			"create_order",
			"req-retryable",
			"hash-1",
			'{"customer": "CUST-001"}',
			lambda: {"status": "success", "order": "SO-0040"},
			60,
		)

		self.assertEqual(result["order"], "SO-0040")
		mock_claim_retryable_record.assert_called_once()
		mock_execute_and_store_result.assert_called_once()

	@patch("myapp.utils.idempotency._table_exists", return_value=True)
	@patch("myapp.utils.idempotency.now_datetime", return_value="2026-05-27 10:00:00")
	def test_cleanup_expired_idempotency_records_deletes_final_expired_rows(self, mock_now_datetime, mock_table_exists):
		from myapp.utils.idempotency import cleanup_expired_idempotency_records

		with patch("myapp.utils.idempotency.frappe") as mock_frappe:
			mock_frappe.db.sql.side_effect = [
				[SimpleNamespace(name="idem-1"), SimpleNamespace(name="idem-2")],
				None,
			]

			result = cleanup_expired_idempotency_records(batch_size=2)

		self.assertEqual(result["data"]["deleted_count"], 2)
		self.assertIn(
			"status IN ('succeeded', 'failed', 'retryable_failed')",
			mock_frappe.db.sql.call_args_list[0].args[0],
		)
		self.assertIn("DELETE FROM `tabMyApp Idempotency Key`", mock_frappe.db.sql.call_args_list[1].args[0])
		self.assertEqual(mock_frappe.db.sql.call_args_list[1].args[1], ["idem-1", "idem-2"])
