from __future__ import annotations

import frappe
from frappe.utils.background_jobs import get_redis_conn

from myapp.services.ai_model_governance_service import run_scheduled_ai_model_availability_check
from myapp.services.ai_repository import cleanup_expired_ai_conversations, refresh_ai_usage_daily_metrics
from myapp.services.ai_vector_service import reconcile_product_vector_index
from myapp.services.media_service import cleanup_expired_temporary_item_images
from myapp.services.printing_service import cleanup_expired_print_batches
from myapp.utils.idempotency import cleanup_expired_idempotency_records


def cleanup_temporary_item_images():
	result = cleanup_expired_temporary_item_images()
	if result["data"]["deleted_count"]:
		frappe.db.commit()
	return result


def cleanup_idempotency_records():
	result = cleanup_expired_idempotency_records()
	if result["data"]["deleted_count"]:
		frappe.db.commit()
	return result


def cleanup_print_batches():
	result = cleanup_expired_print_batches()
	if result["data"]["deleted_count"] or result["data"]["deleted_file_count"]:
		frappe.db.commit()
	return result


def cleanup_ai_conversations():
	return cleanup_expired_ai_conversations()


def refresh_ai_usage_metrics():
	return refresh_ai_usage_daily_metrics()


def reconcile_ai_product_vectors():
	return reconcile_product_vector_index()


def check_ai_model_availability():
	lock = get_redis_conn().lock(
		f"myapp:ai-model-healthcheck:{frappe.local.site}",
		timeout=600,
		blocking_timeout=1,
	)
	if not lock.acquire(blocking=True):
		return {"status": "skipped", "message": "AI 模型健康检查已有任务正在执行。"}
	try:
		result = run_scheduled_ai_model_availability_check()
		if result.get("status") == "success":
			frappe.db.commit()
		return result
	finally:
		lock.release()
