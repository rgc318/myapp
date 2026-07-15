from __future__ import annotations

import hashlib
import html
import json
import os
import re

import frappe
from frappe import _
from frappe.utils import cint, now_datetime
import requests

from myapp.services.wholesale_service import search_product_v2


PRODUCT_VECTOR_INDEX_VERSION = "product-semantic-v1"
MAX_VECTOR_DOCUMENT_CHARS = 8000
MAX_VECTOR_BATCH_SIZE = 128
MAX_VECTOR_BATCH_CHARS = 120000
MAX_SEMANTIC_CANDIDATES = 30


def _enabled() -> bool:
	flag = os.environ.get("MYAPP_AI_VECTOR_SEARCH_ENABLED", "0").strip().lower() in {"1", "true", "yes"}
	return flag and bool(_configured_embedding_model())


def _orchestrator_url() -> str:
	return os.environ.get("MYAPP_AI_ORCHESTRATOR_URL", "http://ai-orchestrator:4010").strip().rstrip("/")


def _configured_embedding_model() -> str:
	return os.environ.get("MYAPP_AI_EMBEDDING_MODEL", "").strip()


def _vector_collection() -> str:
	return (
		os.environ.get("MYAPP_AI_QDRANT_ALIAS", "").strip()
		or os.environ.get("MYAPP_AI_QDRANT_COLLECTION", "myapp-products-v1").strip()
		or "myapp-products-v1"
	)


def _service_token() -> str:
	token = os.environ.get("MYAPP_AI_SERVICE_TOKEN", "").strip()
	if not token:
		raise RuntimeError("MYAPP_AI_SERVICE_TOKEN is not configured")
	return token


def _call_vector_orchestrator(path: str, payload: dict, *, timeout: float = 20) -> dict:
	response = requests.post(
		f"{_orchestrator_url()}{path}",
		headers={"Authorization": f"Bearer {_service_token()}", "Content-Type": "application/json"},
		data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
		timeout=timeout,
	)
	response.raise_for_status()
	body = response.json()
	if not isinstance(body, dict):
		raise RuntimeError("AI vector service returned an invalid response")
	return body


def _plain_text(value) -> str:
	text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
	return " ".join(text.split())


def _item_barcodes(item) -> list[str]:
	barcodes = []
	for row in getattr(item, "barcodes", []) or []:
		value = _plain_text(getattr(row, "barcode", None))
		if value and value not in barcodes:
			barcodes.append(value)
	return barcodes


def build_product_vector_document(item) -> dict:
	parts = [
		f"商品编码：{_plain_text(item.name)}",
		f"商品名称：{_plain_text(getattr(item, 'item_name', None))}",
	]
	optional_fields = [
		("昵称", getattr(item, "custom_nickname", None)),
		("规格", getattr(item, "custom_specification", None)),
		("品牌", getattr(item, "brand", None)),
		("分类", getattr(item, "item_group", None)),
		("描述与用途", getattr(item, "description", None)),
		("库存单位", getattr(item, "stock_uom", None)),
		("批发默认单位", getattr(item, "custom_wholesale_default_uom", None)),
		("零售默认单位", getattr(item, "custom_retail_default_uom", None)),
	]
	for label, value in optional_fields:
		resolved = _plain_text(value)
		if resolved:
			parts.append(f"{label}：{resolved}")
	barcodes = _item_barcodes(item)
	if barcodes:
		parts.append(f"条码：{'、'.join(barcodes)}")
	text = "；".join(parts)[:MAX_VECTOR_DOCUMENT_CHARS]
	return {
		"item_code": item.name,
		"text": text,
		"content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
		"index_version": PRODUCT_VECTOR_INDEX_VERSION,
		"source_modified": str(getattr(item, "modified", "") or "") or None,
		"disabled": cint(getattr(item, "disabled", 0)),
		"is_sales_item": cint(getattr(item, "is_sales_item", 0)),
		"is_purchase_item": cint(getattr(item, "is_purchase_item", 0)),
		"is_stock_item": cint(getattr(item, "is_stock_item", 0)),
		"item_group": _plain_text(getattr(item, "item_group", None)) or None,
		"brand": _plain_text(getattr(item, "brand", None)) or None,
		# ERPNext Item is global master data. Company and record permissions are re-applied in Frappe after retrieval.
		"company_scope": ["*"],
	}


def _state_table_exists() -> bool:
	return frappe.db.table_exists("MyApp AI Product Vector State")


def _require_vector_admin() -> None:
	if "System Manager" not in set(frappe.get_roles() or []):
		raise frappe.PermissionError(_("只有系统管理员可以管理 AI 商品向量索引。"))


def _normalize_item_codes(value) -> list[str]:
	if value in (None, "", []):
		return []
	parsed = value
	if isinstance(value, str):
		try:
			parsed = frappe.parse_json(value)
		except Exception:
			parsed = [part.strip() for part in value.split(",")]
	if not isinstance(parsed, list):
		raise ValueError("item_codes must be a list")
	result = []
	for value in parsed:
		item_code = str(value or "").strip()
		if item_code and item_code not in result:
			result.append(item_code)
	return result[:500]


def _record_state(
	*, item_code: str, status: str, document: dict | None = None,
	embedding_model: str | None = None, vector_collection: str | None = None,
	error: str | None = None,
) -> None:
	if not _state_table_exists():
		return
	now = now_datetime()
	document = document or {}
	frappe.db.sql(
		"""
		INSERT INTO `tabMyApp AI Product Vector State`
			(name, creation, modified, modified_by, owner, item_code, content_hash,
			 index_version, embedding_model, vector_collection, source_modified, status, last_error,
			 last_attempt_at, indexed_at)
		VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
		ON DUPLICATE KEY UPDATE
			modified = VALUES(modified), modified_by = VALUES(modified_by),
			content_hash = VALUES(content_hash), index_version = VALUES(index_version),
			embedding_model = VALUES(embedding_model), vector_collection = VALUES(vector_collection),
			source_modified = VALUES(source_modified),
			status = VALUES(status), last_error = VALUES(last_error),
			last_attempt_at = VALUES(last_attempt_at), indexed_at = VALUES(indexed_at)
		""",
		(
			item_code, now, now, frappe.session.user, frappe.session.user, item_code,
			document.get("content_hash"), document.get("index_version"), embedding_model, vector_collection,
			document.get("source_modified"), status, (error or "")[:500] or None, now,
			now if status == "indexed" else None,
		),
	)


def _prepare_product_vector_document(item_code: str) -> tuple[str, dict | None]:
	item_code = str(item_code or "").strip()
	if not item_code:
		raise ValueError("item_code is required")
	if not frappe.db.exists("Item", item_code):
		return "deleted", None
	item = frappe.get_doc("Item", item_code)
	document = build_product_vector_document(item)
	existing_rows = (
		frappe.db.sql(
			"""
			SELECT content_hash, index_version, embedding_model, vector_collection, status
			FROM `tabMyApp AI Product Vector State`
			WHERE item_code = %s
			LIMIT 1
			""",
			(item_code,),
			as_dict=True,
		)
		if _state_table_exists()
		else []
	)
	existing = existing_rows[0] if existing_rows else None
	if (
		existing
		and existing.get("status") == "indexed"
		and existing.get("content_hash") == document["content_hash"]
		and existing.get("index_version") == PRODUCT_VECTOR_INDEX_VERSION
		and existing.get("embedding_model") == _configured_embedding_model()
		and existing.get("vector_collection") == _vector_collection()
	):
		_record_state(
			item_code=item_code,
			status="indexed",
			document=document,
			embedding_model=existing.get("embedding_model"),
			vector_collection=existing.get("vector_collection"),
		)
		return "unchanged", document
	_record_state(
		item_code=item_code,
		status="pending",
		document=document,
		embedding_model=_configured_embedding_model(),
		vector_collection=_vector_collection(),
	)
	return "pending", document


def sync_product_vector_batch(item_codes) -> dict:
	if not _enabled():
		return {"status": "disabled", "indexed_count": 0, "unchanged_count": 0, "deleted_count": 0}
	codes = _normalize_item_codes(item_codes)[:MAX_VECTOR_BATCH_SIZE]
	if not codes:
		raise ValueError("item_codes are required")
	documents = []
	unchanged = []
	deleted = []
	deferred = []
	total_chars = 0
	for item_code in codes:
		state, document = _prepare_product_vector_document(item_code)
		if state == "deleted":
			deleted.append(item_code)
			continue
		if state == "unchanged":
			unchanged.append(item_code)
			continue
		document_chars = len(document.get("text") or "")
		if documents and total_chars + document_chars > MAX_VECTOR_BATCH_CHARS:
			deferred.append(item_code)
			continue
		documents.append(document)
		total_chars += document_chars
	frappe.db.commit()

	if deleted:
		try:
			_call_vector_orchestrator(
				"/internal/v1/vector/products/delete",
				{"item_codes": deleted},
			)
		except Exception as error:
			for item_code in deleted:
				_record_state(item_code=item_code, status="failed", error=str(error))
			frappe.db.commit()
			raise
		for item_code in deleted:
			_record_state(item_code=item_code, status="deleted")

	result = {}
	if documents:
		try:
			result = _call_vector_orchestrator(
				"/internal/v1/vector/products/upsert",
				{"documents": documents},
			)
		except Exception as error:
			for document in documents:
				_record_state(
					item_code=document["item_code"],
					status="failed",
					document=document,
					embedding_model=_configured_embedding_model(),
					vector_collection=_vector_collection(),
					error=str(error),
				)
			frappe.db.commit()
			raise
		for document in documents:
			_record_state(
				item_code=document["item_code"],
				status="indexed",
				document=document,
				embedding_model=result.get("embedding_model"),
				vector_collection=result.get("collection"),
			)

	if deferred:
		frappe.enqueue(
			"myapp.services.ai_vector_service.sync_product_vector_batch",
			queue="ai-vector",
			item_codes=deferred,
			job_name=f"AI product vector deferred batch {len(deferred)}",
		)
	frappe.db.commit()
	return {
		"status": "completed",
		"indexed_count": len(documents),
		"unchanged_count": len(unchanged),
		"deleted_count": len(deleted),
		"deferred_count": len(deferred),
		"embedding_model": result.get("embedding_model") or _configured_embedding_model(),
		"collection": result.get("collection") or _vector_collection(),
	}


def sync_product_vector_index(item_code: str) -> dict:
	if not _enabled():
		return {"status": "disabled", "item_code": item_code}
	item_code = str(item_code or "").strip()
	result = sync_product_vector_batch([item_code])
	if result["unchanged_count"]:
		return {"status": "unchanged", "item_code": item_code}
	if result["deleted_count"]:
		return {"status": "deleted", "item_code": item_code}
	return {"status": "indexed", "item_code": item_code}


def delete_product_vector_index(item_code: str) -> dict:
	item_code = str(item_code or "").strip()
	if not item_code:
		raise ValueError("item_code is required")
	if not _enabled():
		return {"status": "disabled", "item_code": item_code}
	try:
		_call_vector_orchestrator(
			"/internal/v1/vector/products/delete",
			{"item_codes": [item_code]},
		)
	except Exception as error:
		_record_state(item_code=item_code, status="failed", error=str(error))
		frappe.db.commit()
		raise
	_record_state(item_code=item_code, status="deleted")
	frappe.db.commit()
	return {"status": "deleted", "item_code": item_code}


def enqueue_product_vector_sync(doc, method: str | None = None) -> None:
	if not _enabled() or not getattr(doc, "name", None):
		return
	frappe.enqueue(
		"myapp.services.ai_vector_service.sync_product_vector_batch",
		queue="ai-vector",
		enqueue_after_commit=True,
		item_codes=[doc.name],
		job_name=f"AI product vector sync {doc.name}",
	)


def enqueue_product_vector_delete(doc, method: str | None = None) -> None:
	if not _enabled() or not getattr(doc, "name", None):
		return
	frappe.enqueue(
		"myapp.services.ai_vector_service.delete_product_vector_index",
		queue="ai-vector",
		enqueue_after_commit=True,
		item_code=doc.name,
		job_name=f"AI product vector delete {doc.name}",
	)


def reconcile_product_vector_index(batch_size: int = 100) -> dict:
	if not _enabled() or not _state_table_exists():
		return {"status": "disabled", "queued_count": 0}
	batch_size = max(1, min(int(batch_size or 100), 500))
	rows = frappe.db.sql(
		"""
		SELECT item.name AS item_code
		FROM `tabItem` item
		LEFT JOIN `tabMyApp AI Product Vector State` state ON state.item_code = item.name
		WHERE state.item_code IS NULL
		   OR state.index_version != %s
		   OR state.source_modified IS NULL
		   OR item.modified > state.source_modified
		   OR state.status = 'failed'
		   OR COALESCE(state.embedding_model, '') != %s
		   OR COALESCE(state.vector_collection, '') != %s
		ORDER BY item.modified ASC
		LIMIT %s
		""",
		(PRODUCT_VECTOR_INDEX_VERSION, _configured_embedding_model(), _vector_collection(), batch_size),
		as_dict=True,
	)
	item_codes = [row.item_code for row in rows]
	for offset in range(0, len(item_codes), 64):
		batch = item_codes[offset:offset + 64]
		frappe.enqueue(
			"myapp.services.ai_vector_service.sync_product_vector_batch",
			queue="ai-vector",
			item_codes=batch,
			job_name=f"AI product vector reconcile batch {offset // 64 + 1}",
		)
	return {"status": "queued", "queued_count": len(rows)}


def get_product_vector_index_status_v1(failure_limit: int = 20) -> dict:
	_require_vector_admin()
	failure_limit = max(1, min(int(failure_limit or 20), 100))
	counts = {"pending": 0, "indexed": 0, "failed": 0, "deleted": 0}
	failures = []
	tracked_count = 0
	due_count = 0
	if _state_table_exists():
		for row in frappe.db.sql(
			"SELECT status, COUNT(*) AS count FROM `tabMyApp AI Product Vector State` GROUP BY status",
			as_dict=True,
		):
			counts[str(row.status)] = int(row.count or 0)
		tracked_count = sum(counts.values())
		due_count = int(
			frappe.db.sql(
				"""
				SELECT COUNT(*)
				FROM `tabItem` item
				LEFT JOIN `tabMyApp AI Product Vector State` state ON state.item_code = item.name
				WHERE state.item_code IS NULL
				   OR state.index_version != %s
				   OR state.source_modified IS NULL
				   OR item.modified > state.source_modified
				   OR state.status = 'failed'
				   OR COALESCE(state.embedding_model, '') != %s
				   OR COALESCE(state.vector_collection, '') != %s
				""",
				(PRODUCT_VECTOR_INDEX_VERSION, _configured_embedding_model(), _vector_collection()),
			)[0][0]
			or 0
		)
		failures = frappe.db.sql(
			"""
			SELECT item_code, last_error, last_attempt_at
			FROM `tabMyApp AI Product Vector State`
			WHERE status = 'failed'
			ORDER BY last_attempt_at DESC
			LIMIT %s
			""",
			(failure_limit,),
			as_dict=True,
		)
	try:
		provider = _call_vector_orchestrator("/internal/v1/vector/products/status", {})
	except Exception as error:
		provider = {"reachable": False, "error": type(error).__name__}
	return {
		"status": "success",
		"message": _("AI 商品向量索引状态获取成功。"),
		"data": {
			"enabled": _enabled(),
			"index_version": PRODUCT_VECTOR_INDEX_VERSION,
			"embedding_model": _configured_embedding_model() or None,
			"vector_collection": _vector_collection(),
			"total_items": int(frappe.db.count("Item") or 0),
			"tracked_count": tracked_count,
			"due_count": due_count,
			"counts": counts,
			"recent_failures": failures,
			"provider": provider,
		},
	}


def rebuild_product_vector_index_v1(
	item_codes=None,
	failed_only: bool | int = False,
	limit: int = 100,
) -> dict:
	_require_vector_admin()
	if not _enabled():
		frappe.throw(_("请先配置 Embedding 模型并启用 AI 商品向量检索。"))
	limit = max(1, min(int(limit or 100), 500))
	requested_codes = _normalize_item_codes(item_codes)
	if requested_codes:
		resolved_codes = frappe.get_all(
			"Item",
			filters={"name": ["in", requested_codes]},
			pluck="name",
			limit_page_length=min(limit, len(requested_codes)),
		)
	elif cint(failed_only) and _state_table_exists():
		resolved_codes = [
			row.item_code
			for row in frappe.db.sql(
				"""
				SELECT item.name AS item_code
				FROM `tabItem` item
				INNER JOIN `tabMyApp AI Product Vector State` state ON state.item_code = item.name
				WHERE state.status = 'failed'
				ORDER BY state.last_attempt_at ASC
				LIMIT %s
				""",
				(limit,),
				as_dict=True,
			)
		]
	else:
		resolved_codes = frappe.get_all(
			"Item",
			pluck="name",
			order_by="modified asc",
			limit_page_length=limit,
		)
	for offset in range(0, len(resolved_codes), 64):
		batch = resolved_codes[offset:offset + 64]
		frappe.enqueue(
			"myapp.services.ai_vector_service.sync_product_vector_batch",
			queue="ai-vector",
			item_codes=batch,
			job_name=f"AI product vector rebuild batch {offset // 64 + 1}",
		)
	return {
		"status": "success",
		"message": _("AI 商品向量索引重建任务已加入队列。"),
		"data": {
			"queued_count": len(resolved_codes),
			"item_codes": list(resolved_codes),
			"failed_only": bool(cint(failed_only)),
		},
	}


def search_products_semantic(
	query: str,
	*,
	company: str,
	limit: int = 16,
	item_context: str = "sales",
) -> dict:
	query = " ".join(str(query or "").split())
	if not query or not _enabled():
		return {"available": False, "rows": [], "reason": "disabled"}
	limit = max(1, min(int(limit or 16), MAX_SEMANTIC_CANDIDATES))
	try:
		result = _call_vector_orchestrator(
			"/internal/v1/vector/products/search",
			{"query": query, "company": company, "limit": limit, "item_context": item_context},
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("AI 商品向量检索失败，已降级为关键词检索"))
		return {"available": False, "rows": [], "reason": "upstream_unavailable"}
	matches = result.get("matches") or []
	candidate_codes = [str(row.get("item_code") or "") for row in matches if row.get("item_code")]
	allowed_codes = set(
		frappe.get_list(
			"Item",
			filters={"name": ["in", candidate_codes]},
			pluck="name",
			limit_page_length=max(1, len(candidate_codes)),
		)
		if candidate_codes
		else []
	)
	rows = []
	for match in matches:
		item_code = str(match.get("item_code") or "")
		if item_code not in allowed_codes:
			continue
		resolved = search_product_v2(
			search_key=item_code,
			company=company,
			limit=1,
			disabled=0,
			item_context=item_context,
		)
		row = next(
			(candidate for candidate in (resolved or {}).get("data") or [] if candidate.get("item_code") == item_code),
			None,
		)
		if not row:
			continue
		row = dict(row)
		row["semantic_score"] = float(match.get("score") or 0)
		row["semantic_index_version"] = match.get("index_version")
		rows.append(row)
	return {
		"available": True,
		"rows": rows,
		"embedding_model": result.get("embedding_model"),
		"collection": result.get("collection"),
	}
