import hashlib
import time

import frappe
from frappe.utils import add_to_date, now_datetime
from frappe.utils.synchronization import filelock


DEFAULT_TTL = 24 * 60 * 60
LOCK_TIMEOUT_SECONDS = 60
POLL_INTERVAL_SECONDS = 0.2
CLEANUP_BATCH_SIZE = 1000
TABLE_NAME = "tabMyApp Idempotency Key"
DOCTYPE_NAME = "MyApp Idempotency Key"
IGNORED_FINGERPRINT_KEYS = {"cmd"}


class IdempotencyConflictError(Exception):
	pass


FINAL_FAILURE_EXCEPTIONS = (
	frappe.ValidationError,
	frappe.PermissionError,
	frappe.AuthenticationError,
	frappe.DoesNotExistError,
	frappe.DuplicateEntryError,
	IdempotencyConflictError,
)


def normalize_request_id(request_id) -> str | None:
	request_id = (request_id or "").strip()
	return request_id or None


def build_idempotency_key(namespace: str, request_id: str) -> str:
	return f"myapp:idempotency:{namespace}:{request_id}"


def build_idempotency_lock_name(namespace: str, request_id: str) -> str:
	return build_idempotency_key(namespace, request_id).replace(":", "_")


def build_idempotency_record_name(namespace: str, request_id: str) -> str:
	digest = hashlib.sha256(f"{namespace}:{request_id}".encode()).hexdigest()
	return f"idem-{digest}"


def _normalize_fingerprint_value(value):
	if isinstance(value, dict):
		return {
			key: _normalize_fingerprint_value(value[key])
			for key in sorted(value)
			if key not in IGNORED_FINGERPRINT_KEYS
		}
	if isinstance(value, (list, tuple)):
		return [_normalize_fingerprint_value(item) for item in value]
	return value


def build_request_fingerprint(payload) -> tuple[str | None, str | None]:
	if payload is None:
		return None, None

	normalized = _normalize_fingerprint_value(payload)
	payload_json = frappe.as_json(normalized)
	return hashlib.sha256(payload_json.encode()).hexdigest(), payload_json


def _get_current_request_payload():
	try:
		form_dict = getattr(frappe.local, "form_dict", None)
	except Exception:
		return None

	if not form_dict:
		return None

	return dict(form_dict)


def get_idempotent_result(namespace: str, request_id) -> dict | None:
	request_id = normalize_request_id(request_id)
	if not request_id:
		return None

	return frappe.cache().get_value(build_idempotency_key(namespace, request_id))


def store_idempotent_result(
	namespace: str, request_id, result: dict, ttl_seconds: int = DEFAULT_TTL
) -> dict:
	request_id = normalize_request_id(request_id)
	if not request_id:
		return result

	frappe.cache().set_value(
		build_idempotency_key(namespace, request_id),
		result,
		expires_in_sec=ttl_seconds,
	)
	return result


def _table_exists() -> bool:
	try:
		return bool(frappe.db.table_exists(DOCTYPE_NAME))
	except Exception:
		return False


def _is_duplicate_key_error(exc: Exception) -> bool:
	args = getattr(exc, "args", ())
	return bool(args and args[0] == 1062)


def _is_concurrent_insert_conflict(exc: Exception) -> bool:
	message = str(exc)
	return "Record has changed since last read" in message and TABLE_NAME in message


def _expires_at(ttl_seconds: int):
	return add_to_date(now_datetime(), seconds=ttl_seconds)


def _is_retryable_exception(exc: Exception) -> bool:
	return not isinstance(exc, FINAL_FAILURE_EXCEPTIONS)


def _insert_processing_record(
	namespace: str,
	request_id: str,
	request_hash: str | None,
	request_json: str | None,
	ttl_seconds: int,
) -> bool:
	now = now_datetime()
	try:
		frappe.db.sql(
			f"""
			INSERT INTO `{TABLE_NAME}`
				(name, creation, modified, modified_by, owner, docstatus, idx,
				 namespace, request_id, request_hash, request_json, status, expires_at)
			VALUES
				(%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, 'processing', %s)
			""",
			(
				build_idempotency_record_name(namespace, request_id),
				now,
				now,
				frappe.session.user if getattr(frappe, "session", None) else "Administrator",
				frappe.session.user if getattr(frappe, "session", None) else "Administrator",
				namespace,
				request_id,
				request_hash,
				request_json,
				_expires_at(ttl_seconds),
			),
		)
		frappe.db.commit()
		return True
	except Exception as exc:
		if _is_duplicate_key_error(exc) or _is_concurrent_insert_conflict(exc):
			frappe.db.rollback()
			return False
		raise


def _mark_record_succeeded(namespace: str, request_id: str, result: dict, ttl_seconds: int):
	frappe.db.sql(
		f"""
		UPDATE `{TABLE_NAME}`
		SET modified = %s,
			status = 'succeeded',
			response_json = %s,
			error = NULL,
			expires_at = %s
		WHERE namespace = %s AND request_id = %s
		""",
		(
			now_datetime(),
			frappe.as_json(result),
			_expires_at(ttl_seconds),
			namespace,
			request_id,
		),
	)
	frappe.db.commit()


def _mark_record_failed(namespace: str, request_id: str, exc: Exception, ttl_seconds: int, retryable: bool = False):
	frappe.db.rollback()
	frappe.db.sql(
		f"""
		UPDATE `{TABLE_NAME}`
		SET modified = %s,
			status = %s,
			error = %s,
			expires_at = %s
		WHERE namespace = %s AND request_id = %s
		""",
		(
			now_datetime(),
			"retryable_failed" if retryable else "failed",
			str(exc),
			_expires_at(ttl_seconds),
			namespace,
			request_id,
		),
	)
	frappe.db.commit()


def _claim_retryable_record(
	namespace: str,
	request_id: str,
	request_hash: str | None,
	request_json: str | None,
	ttl_seconds: int,
) -> bool:
	_refresh_transaction_snapshot()
	row = _get_record(namespace, request_id)
	_assert_request_hash_matches(row, request_hash)

	if not row or row.status != "retryable_failed":
		return False

	now = now_datetime()
	frappe.db.sql(
		f"""
		UPDATE `{TABLE_NAME}`
		SET modified = %s,
			status = 'processing',
			request_hash = %s,
			request_json = %s,
			response_json = NULL,
			error = NULL,
			expires_at = %s
		WHERE namespace = %s
			AND request_id = %s
			AND status = 'retryable_failed'
		""",
		(
			now,
			request_hash,
			request_json,
			_expires_at(ttl_seconds),
			namespace,
			request_id,
		),
	)
	rows = frappe.db.sql("SELECT ROW_COUNT() AS row_count", as_dict=True)
	frappe.db.commit()
	return bool(rows and rows[0].row_count)


def _get_record(namespace: str, request_id: str):
	rows = frappe.db.sql(
		f"""
		SELECT status, request_hash, response_json, error
		FROM `{TABLE_NAME}`
		WHERE namespace = %s AND request_id = %s
		LIMIT 1
		""",
		(namespace, request_id),
		as_dict=True,
	)
	if not rows:
		return None

	return rows[0]


def _assert_request_hash_matches(row, request_hash: str | None):
	if not request_hash or not row or not row.request_hash:
		return

	if row.request_hash != request_hash:
		raise IdempotencyConflictError("相同 request_id 已被不同请求参数使用，请更换 request_id 后重试。")


def _get_record_result(namespace: str, request_id: str) -> dict | None:
	row = _get_record(namespace, request_id)
	if not row:
		return None

	if row.status != "succeeded" or not row.response_json:
		return None

	return frappe.parse_json(row.response_json)


def _refresh_transaction_snapshot():
	frappe.db.rollback()


def _wait_for_record_result(namespace: str, request_id: str, request_hash: str | None):
	deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
	while time.monotonic() < deadline:
		# MariaDB's default repeatable-read transaction can keep seeing the old
		# "processing" row unless the polling request starts a fresh read.
		_refresh_transaction_snapshot()
		row = _get_record(namespace, request_id)
		_assert_request_hash_matches(row, request_hash)

		if cached_result := get_idempotent_result(namespace, request_id):
			return cached_result

		if row and row.status == "failed":
			frappe.throw(f"相同 request_id 的请求已失败：{row.error or '未知错误'}")

		if row and row.status == "retryable_failed":
			frappe.throw(f"相同 request_id 上次因系统异常失败，可使用相同参数重试：{row.error or '未知错误'}")

		if row and row.status == "succeeded" and row.response_json:
			result = frappe.parse_json(row.response_json)
			return store_idempotent_result(namespace, request_id, result)

		time.sleep(POLL_INTERVAL_SECONDS)

	_refresh_transaction_snapshot()
	frappe.throw("相同 request_id 的请求正在处理中，请稍后重试。")


def _execute_and_store_result(namespace: str, request_id: str, callback, ttl_seconds: int):
	try:
		result = callback()
	except Exception as exc:
		_mark_record_failed(namespace, request_id, exc, ttl_seconds, retryable=_is_retryable_exception(exc))
		raise

	store_idempotent_result(namespace, request_id, result, ttl_seconds=ttl_seconds)
	_mark_record_succeeded(namespace, request_id, result, ttl_seconds)
	return result


def _run_persistent_idempotent(
	namespace: str,
	request_id: str,
	request_hash: str | None,
	request_json: str | None,
	callback,
	ttl_seconds: int,
):
	if _insert_processing_record(namespace, request_id, request_hash, request_json, ttl_seconds):
		return _execute_and_store_result(namespace, request_id, callback, ttl_seconds)

	if _claim_retryable_record(namespace, request_id, request_hash, request_json, ttl_seconds):
		return _execute_and_store_result(namespace, request_id, callback, ttl_seconds)

	return _wait_for_record_result(namespace, request_id, request_hash)


def cleanup_expired_idempotency_records(batch_size: int = CLEANUP_BATCH_SIZE) -> dict:
	if not _table_exists():
		return {"status": "success", "data": {"deleted_count": 0, "batch_size": batch_size}}

	rows = frappe.db.sql(
		f"""
		SELECT name
		FROM `{TABLE_NAME}`
		WHERE expires_at IS NOT NULL
			AND expires_at < %s
			AND status IN ('succeeded', 'failed', 'retryable_failed')
		ORDER BY expires_at ASC
		LIMIT %s
		""",
		(now_datetime(), batch_size),
		as_dict=True,
	)
	names = [row.name for row in rows]
	if not names:
		return {"status": "success", "data": {"deleted_count": 0, "batch_size": batch_size}}

	placeholders = ", ".join(["%s"] * len(names))
	frappe.db.sql(f"DELETE FROM `{TABLE_NAME}` WHERE name IN ({placeholders})", names)
	return {"status": "success", "data": {"deleted_count": len(names), "batch_size": batch_size}}


def _run_filelock_idempotent(namespace: str, request_id: str, callback, ttl_seconds: int):
	lock_name = build_idempotency_lock_name(namespace, request_id)
	with filelock(lock_name, timeout=LOCK_TIMEOUT_SECONDS):
		if cached_result := get_idempotent_result(namespace, request_id):
			return cached_result

		result = callback()
		return store_idempotent_result(namespace, request_id, result, ttl_seconds=ttl_seconds)


def run_idempotent(namespace: str, request_id, callback, ttl_seconds: int = DEFAULT_TTL, request_payload=None):
	request_id = normalize_request_id(request_id)
	request_hash, request_json = build_request_fingerprint(
		_get_current_request_payload() if request_payload is None else request_payload
	)

	if not request_id:
		result = callback()
		return store_idempotent_result(namespace, request_id, result, ttl_seconds=ttl_seconds)

	if _table_exists():
		return _run_persistent_idempotent(namespace, request_id, request_hash, request_json, callback, ttl_seconds)

	if cached_result := get_idempotent_result(namespace, request_id):
		return cached_result

	return _run_filelock_idempotent(namespace, request_id, callback, ttl_seconds)
