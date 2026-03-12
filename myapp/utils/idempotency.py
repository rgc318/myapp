import frappe
from frappe.utils.synchronization import filelock


DEFAULT_TTL = 24 * 60 * 60
LOCK_TIMEOUT_SECONDS = 10


def normalize_request_id(request_id) -> str | None:
	request_id = (request_id or "").strip()
	return request_id or None


def build_idempotency_key(namespace: str, request_id: str) -> str:
	return f"myapp:idempotency:{namespace}:{request_id}"


def build_idempotency_lock_name(namespace: str, request_id: str) -> str:
	return build_idempotency_key(namespace, request_id).replace(":", "_")


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


def run_idempotent(namespace: str, request_id, callback, ttl_seconds: int = DEFAULT_TTL):
	request_id = normalize_request_id(request_id)
	if cached_result := get_idempotent_result(namespace, request_id):
		return cached_result

	if not request_id:
		result = callback()
		return store_idempotent_result(namespace, request_id, result, ttl_seconds=ttl_seconds)

	lock_name = build_idempotency_lock_name(namespace, request_id)
	with filelock(lock_name, timeout=LOCK_TIMEOUT_SECONDS):
		if cached_result := get_idempotent_result(namespace, request_id):
			return cached_result

		result = callback()
		return store_idempotent_result(namespace, request_id, result, ttl_seconds=ttl_seconds)
