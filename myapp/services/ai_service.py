from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowdate
from frappe.utils.synchronization import filelock
from werkzeug.wrappers import Response

from myapp.services import ai_repository
from myapp.services.ai_vector_service import search_products_semantic
from myapp.services.customer_service import list_customers_v2
from myapp.services.document_list_service import list_business_documents_v1
from myapp.services.inventory_service import reconcile_inventory_stock_v1
from myapp.services.ai_model_governance_service import resolve_ai_selected_model_alias
from myapp.services.order_service import create_order_v2, search_sales_orders_v2
from myapp.services.purchase_service import create_purchase_order, list_suppliers_v2, search_purchase_orders_v2
from myapp.services.report_service import (
	get_business_report_overview_v1,
	get_cashflow_report_v1,
	get_purchase_report_v1,
	get_receivable_payable_report_v1,
	get_sales_report_v1,
)
from myapp.services.wholesale_service import create_product_v2, search_product_v2
from myapp.utils.ai_errors import AiDraftVersionConflictError
from myapp.utils.api_response import UpstreamServiceUnavailableError
from myapp.utils.idempotency import get_current_request_id, run_idempotent
from myapp.utils.uom import resolve_item_quantity_to_stock
from myapp.utils.uom_display import resolve_uom_display_name
from myapp.utils.standard_uoms import STANDARD_UOMS

MAX_AI_MESSAGES = 20
MAX_AI_MESSAGE_CHARS = 8000
MAX_AI_PRODUCT_RESULTS = 8
ALLOWED_AI_ROLES = {"user", "assistant"}
ALLOWED_AI_SCENARIOS = {"auto", "general", "product_search", "order_query", "report_summary"}
PROMPT_VERSION_BY_SCENARIO = {
	"general": "erp-readonly-v7",
	"product_search": "erp-readonly-v7",
	"order_query": "erp-readonly-v7",
	"report_summary": "erp-readonly-v7",
	"sales_order_draft": "sales-order-draft-v2",
	"purchase_order_draft": "purchase-order-draft-v2",
	"inventory_adjustment_draft": "inventory-adjustment-draft-v2",
	"product_setup_draft": "product-setup-draft-v2",
}
PRODUCT_SEARCH_PREFIX_PATTERN = re.compile(
	r"^(?:请|麻烦|可以|能否|帮我|给我|我想|我要)*(?:查询|查看|查找|搜索|检索|找一下|找一找|找找|找)?(?:一下|下)?"
)
PRODUCT_SEARCH_STATUS_SUFFIX_PATTERN = re.compile(
	r"(?:现在|目前)?(?:是否|有没有|有无)?(?:已经)?(?:正常)?(?:有)?(?:入库|到货|有货|现货|库存)"
	r"(?:情况|状态|数量)?(?:了)?(?:吗)?$"
)


def _current_user() -> str:
	user = str(getattr(frappe.session, "user", None) or "").strip()
	if not user or user == "Guest":
		frappe.throw(_("请先登录后再使用 AI 助手。"), frappe.AuthenticationError)
	return user


def _normalize_content(content) -> str:
	resolved = str(content or "").strip()
	if not resolved:
		frappe.throw(_("AI 消息内容不能为空。"))
	if len(resolved) > MAX_AI_MESSAGE_CHARS:
		frappe.throw(_("单条 AI 消息不能超过 {0} 个字符。").format(MAX_AI_MESSAGE_CHARS))
	return resolved


def _normalize_messages(messages):
	if isinstance(messages, str):
		messages = frappe.parse_json(messages)
	if not isinstance(messages, list) or not messages:
		frappe.throw(_("messages 必须是非空数组。"))
	if len(messages) > MAX_AI_MESSAGES:
		frappe.throw(_("单次 AI 请求最多携带 {0} 条消息。").format(MAX_AI_MESSAGES))

	normalized = []
	for row in messages:
		if not isinstance(row, dict):
			frappe.throw(_("AI 消息格式不正确。"))
		role = str(row.get("role") or "").strip().lower()
		if role not in ALLOWED_AI_ROLES:
			frappe.throw(_("AI 消息 role 只支持 user 或 assistant。"))
		normalized.append({"role": role, "content": _normalize_content(row.get("content"))})
	return normalized


def _resolve_scenario(scenario: str | None) -> str:
	resolved = (scenario or "auto").strip().lower()
	if resolved not in ALLOWED_AI_SCENARIOS:
		frappe.throw(_("不支持的 AI 场景。"))
	return resolved


def _infer_ai_scenario(content: str) -> str:
	text = " ".join((content or "").strip().split())
	if any(word in text for word in ("订单", "发票", "送货单", "收货单", "单据")) and any(
		word in text for word in ("查询", "查找", "查看", "列出", "最新", "最近", "前")
	):
		return "order_query"
	if any(word in text for word in ("报表", "分析", "趋势", "表现", "销售额", "采购额", "应收", "应付", "现金流")):
		return "report_summary"
	if any(word in text for word in ("商品", "产品", "SKU", "库存", "入库", "到货", "现货", "价格")) and any(
		word in text for word in ("查询", "查找", "查看", "搜索", "找", "有没有", "哪些", "是否", "状态", "吗")
	):
		return "product_search"
	return "general"


def _infer_ai_action_scenario(content: str) -> str:
	text = " ".join((content or "").strip().split())
	write_words = ("创建", "新增", "添加", "生成", "新建", "建档", "录入")
	if any(word in text for word in ("库存", "存量")) and any(
		word in text for word in ("调整", "盘点", "增加", "减少", "改为", "设置为")
	):
		return "inventory_adjustment_draft"
	if any(word in text for word in ("采购订单", "采购单", "向供应商采购", "进货")) and any(
		word in text for word in write_words + ("向供应商", "进货",)
	):
		return "purchase_order_draft"
	if any(word in text for word in ("销售订单", "销售单", "给客户", "卖给")) and any(
		word in text for word in write_words + ("给客户", "卖给", "开",)
	):
		return "sales_order_draft"
	if any(word in text for word in ("商品", "产品", "SKU")) and any(word in text for word in write_words):
		return "product_setup_draft"
	return _infer_ai_scenario(text)


def _resolve_prompt_version(scenario: str) -> str:
	try:
		return PROMPT_VERSION_BY_SCENARIO[scenario]
	except KeyError as error:
		raise ValueError(f"Prompt version is not configured for AI scenario: {scenario}") from error


def _get_ai_orchestrator_settings():
	base_url = os.environ.get("MYAPP_AI_ORCHESTRATOR_URL", "http://ai-orchestrator:4010").strip().rstrip("/")
	service_token = os.environ.get("MYAPP_AI_SERVICE_TOKEN", "").strip()
	if not service_token:
		frappe.throw(_("AI 服务令牌尚未配置。"))
	return base_url, service_token


def _call_ai_orchestrator(payload: dict) -> dict:
	base_url, service_token = _get_ai_orchestrator_settings()
	request = urllib.request.Request(
		f"{base_url}/internal/v1/chat",
		data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
		headers={
			"Authorization": f"Bearer {service_token}",
			"Content-Type": "application/json",
			"Accept": "application/json",
		},
		method="POST",
	)
	try:
		with urllib.request.urlopen(request, timeout=70) as response:
			result = json.loads(response.read().decode("utf-8") or "{}")
	except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
		frappe.log_error(frappe.get_traceback(), _("AI Orchestrator 调用失败"))
		raise UpstreamServiceUnavailableError(_("AI 服务暂时不可用，请稍后重试。"))

	message = result.get("message") if isinstance(result, dict) else None
	if not isinstance(message, dict) or not str(message.get("content") or "").strip():
		raise UpstreamServiceUnavailableError(_("AI 服务返回了无效响应。"))
	return result


def _sync_ai_feedback_to_orchestrator(payload: dict) -> bool:
	if not payload.get("trace_id"):
		return False
	base_url, service_token = _get_ai_orchestrator_settings()
	request = urllib.request.Request(
		f"{base_url}/internal/v1/feedback",
		data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
		headers={
			"Authorization": f"Bearer {service_token}",
			"Content-Type": "application/json",
			"Accept": "application/json",
		},
		method="POST",
	)
	try:
		with urllib.request.urlopen(request, timeout=8) as response:
			result = json.loads(response.read().decode("utf-8") or "{}")
			return bool(result.get("observability_synced"))
	except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
		frappe.log_error(frappe.get_traceback(), _("AI 反馈可观测性同步失败"))
		return False


def _call_ai_orchestrator_sales_draft(payload: dict) -> dict:
	base_url, service_token = _get_ai_orchestrator_settings()
	request = urllib.request.Request(
		f"{base_url}/internal/v1/drafts/sales-order",
		data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
		headers={
			"Authorization": f"Bearer {service_token}",
			"Content-Type": "application/json",
			"Accept": "application/json",
		},
		method="POST",
	)
	try:
		with urllib.request.urlopen(request, timeout=90) as response:
			result = json.loads(response.read().decode("utf-8") or "{}")
	except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
		frappe.log_error(frappe.get_traceback(), _("AI 销售订单草稿调用失败"))
		raise UpstreamServiceUnavailableError(_("AI 草稿服务暂时不可用，请稍后重试。"))
	if not isinstance(result.get("draft"), dict):
		raise UpstreamServiceUnavailableError(_("AI 草稿服务返回了无效响应。"))
	return result


def _call_ai_orchestrator_purchase_draft(payload: dict) -> dict:
	base_url, service_token = _get_ai_orchestrator_settings()
	request = urllib.request.Request(
		f"{base_url}/internal/v1/drafts/purchase-order",
		data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
		headers={"Authorization": f"Bearer {service_token}", "Content-Type": "application/json", "Accept": "application/json"},
		method="POST",
	)
	try:
		with urllib.request.urlopen(request, timeout=90) as response:
			result = json.loads(response.read().decode("utf-8") or "{}")
	except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
		frappe.log_error(frappe.get_traceback(), _("AI 采购订单草稿调用失败"))
		raise UpstreamServiceUnavailableError(_("AI 草稿服务暂时不可用，请稍后重试。"))
	if not isinstance(result.get("draft"), dict):
		raise UpstreamServiceUnavailableError(_("AI 草稿服务返回了无效响应。"))
	return result


def _call_ai_orchestrator_inventory_adjustment_draft(payload: dict) -> dict:
	base_url, service_token = _get_ai_orchestrator_settings()
	request = urllib.request.Request(
		f"{base_url}/internal/v1/drafts/inventory-adjustment",
		data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
		headers={"Authorization": f"Bearer {service_token}", "Content-Type": "application/json", "Accept": "application/json"},
		method="POST",
	)
	try:
		with urllib.request.urlopen(request, timeout=90) as response:
			result = json.loads(response.read().decode("utf-8") or "{}")
	except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
		frappe.log_error(frappe.get_traceback(), _("AI 库存调整草稿调用失败"))
		raise UpstreamServiceUnavailableError(_("AI 草稿服务暂时不可用，请稍后重试。"))
	if not isinstance(result.get("draft"), dict):
		raise UpstreamServiceUnavailableError(_("AI 草稿服务返回了无效响应。"))
	return result


def _call_ai_orchestrator_product_setup_draft(payload: dict) -> dict:
	base_url, service_token = _get_ai_orchestrator_settings()
	request = urllib.request.Request(
		f"{base_url}/internal/v1/drafts/product-setup",
		data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
		headers={"Authorization": f"Bearer {service_token}", "Content-Type": "application/json", "Accept": "application/json"},
		method="POST",
	)
	try:
		with urllib.request.urlopen(request, timeout=90) as response:
			result = json.loads(response.read().decode("utf-8") or "{}")
	except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
		frappe.log_error(frappe.get_traceback(), _("AI 商品建档草稿调用失败"))
		raise UpstreamServiceUnavailableError(_("AI 草稿服务暂时不可用，请稍后重试。"))
	if not isinstance(result.get("draft"), dict):
		raise UpstreamServiceUnavailableError(_("AI 草稿服务返回了无效响应。"))
	return result


def _stream_ai_orchestrator(payload: dict):
	base_url, service_token = _get_ai_orchestrator_settings()
	request = urllib.request.Request(
		f"{base_url}/internal/v1/chat/stream",
		data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
		headers={
			"Authorization": f"Bearer {service_token}",
			"Content-Type": "application/json",
			"Accept": "text/event-stream",
		},
		method="POST",
	)
	try:
		with urllib.request.urlopen(request, timeout=90) as response:
			for raw_line in response:
				line = raw_line.decode("utf-8").strip()
				if not line or line.startswith(":") or not line.startswith("data:"):
					continue
				data = json.loads(line[5:].strip())
				if isinstance(data, dict):
					yield data
	except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
		frappe.log_error(frappe.get_traceback(), _("AI Orchestrator 流式调用失败"))
		raise UpstreamServiceUnavailableError(_("AI 流式服务暂时不可用，请稍后重试。"))


def _resolve_company_scope(company: str | None, *, required: bool = False) -> str | None:
	resolved = (company or "").strip()
	if not resolved:
		try:
			resolved = str(frappe.defaults.get_user_default("company") or "").strip()
		except Exception:
			resolved = ""
	if not resolved:
		if required:
			frappe.throw(_("请先选择公司，再使用商品搜索。"))
		return None
	allowed = frappe.get_list("Company", filters={"name": resolved}, pluck="name", limit_page_length=1)
	if not allowed:
		raise frappe.PermissionError(_("无权访问公司 {0}。").format(resolved))
	return resolved


def _extract_product_search_terms(query: str) -> list[str]:
	text = " ".join((query or "").strip().split())
	text = PRODUCT_SEARCH_PREFIX_PATTERN.sub("", text).strip(" ：:")
	text = PRODUCT_SEARCH_STATUS_SUFFIX_PATTERN.sub("", text).strip(" ：:")
	segments = [part.strip() for part in re.split(r"[，,。；;！？!?、]", text) if part.strip()]
	terms = []

	def add_term(value: str):
		value = PRODUCT_SEARCH_PREFIX_PATTERN.sub("", value).strip(" ：:")
		if 2 <= len(value) <= 40 and value not in terms:
			terms.append(value)

	for segment in segments[:4]:
		if segment.startswith(("只说明", "只返回", "请说明", "并说明", "需要说明")):
			continue
		add_term(segment)
		for part in re.split(r"(?:适合|用于|用来|可以|能够|的)", segment):
			add_term(part)
		if len(terms) >= 5:
			break
	return terms[:5] or [text[:40]]


def _hybrid_rerank_product_rows(
	*, query: str, lexical_rows: list[dict], semantic_rows: list[dict], limit: int,
) -> list[dict]:
	candidates: dict[str, dict] = {}
	for source, rows in (("lexical", lexical_rows), ("semantic", semantic_rows)):
		for rank, row in enumerate(rows, start=1):
			item_code = str(row.get("item_code") or "").strip()
			if not item_code:
				continue
			entry = candidates.setdefault(item_code, {"row": dict(row), "sources": set(), "score": 0.0})
			entry["sources"].add(source)
			entry["score"] += 1 / (60 + rank)
			if source == "semantic":
				entry["row"].update(row)
				entry["score"] += max(0.0, min(float(row.get("semantic_score") or 0), 1.0)) * 0.01
	query_key = re.sub(r"\s+", "", query).lower()
	for entry in candidates.values():
		row = entry["row"]
		document_key = re.sub(
			r"\s+",
			"",
			" ".join(
				str(row.get(field) or "")
				for field in ("item_code", "item_name", "nickname", "specification", "brand", "item_group", "description")
			),
		).lower()
		if query_key and query_key in document_key:
			entry["score"] += 0.05
		row["match_source"] = "+".join(sorted(entry["sources"]))
		row["match_reason"] = (
			"关键词与语义混合匹配" if len(entry["sources"]) > 1
			else "语义相似匹配" if "semantic" in entry["sources"]
			else "编码、名称或主数据字段匹配"
		)
		row["retrieval_score"] = round(entry["score"], 6)
	return [
		entry["row"]
		for entry in sorted(
			candidates.values(),
			key=lambda entry: (-entry["score"], str(entry["row"].get("item_code") or "")),
		)[:limit]
	]


def _build_product_search_context(*, query: str, company: str | None) -> tuple[dict, list[dict], list[dict]]:
	if not frappe.has_permission("Item", ptype="read"):
		raise frappe.PermissionError(_("无权读取商品资料。"))
	resolved_company = _resolve_company_scope(company, required=True)
	search_terms = _extract_product_search_terms(query)
	lexical_rows = []
	seen_codes = set()
	for search_term in search_terms:
		search_result = search_product_v2(
			search_key=search_term,
			company=resolved_company,
			limit=MAX_AI_PRODUCT_RESULTS * 2,
			disabled=0,
			search_fields=["barcode", "item_code", "item_name", "nickname", "specification"],
			item_context="sales",
		)
		for row in (search_result or {}).get("data") or []:
			item_code = row.get("item_code")
			if item_code and item_code not in seen_codes:
				seen_codes.add(item_code)
				lexical_rows.append(row)
				if len(lexical_rows) >= MAX_AI_PRODUCT_RESULTS * 2:
					break
		if len(lexical_rows) >= MAX_AI_PRODUCT_RESULTS * 2:
			break
	semantic_result = search_products_semantic(
		query,
		company=resolved_company,
		limit=MAX_AI_PRODUCT_RESULTS * 2,
		item_context="sales",
	)
	result_rows = _hybrid_rerank_product_rows(
		query=query,
		lexical_rows=lexical_rows,
		semantic_rows=semantic_result.get("rows") or [],
		limit=MAX_AI_PRODUCT_RESULTS,
	)
	candidate_codes = [row.get("item_code") for row in result_rows if row.get("item_code")]
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
	products = []
	for row in result_rows:
		if row.get("item_code") not in allowed_codes:
			continue
		products.append(
			{
				"item_code": row.get("item_code"),
				"item_name": row.get("item_name"),
				"nickname": row.get("nickname"),
				"specification": row.get("specification"),
				"brand": row.get("brand"),
				"item_group": row.get("item_group"),
				"uom": row.get("uom"),
				"uom_display": row.get("uom_display"),
				"price": row.get("price"),
				"qty": row.get("qty"),
				"image": row.get("image"),
				"match_source": row.get("match_source"),
				"match_reason": row.get("match_reason"),
				"retrieval_score": row.get("retrieval_score"),
				"semantic_score": row.get("semantic_score"),
			}
		)
	citations = [
		{
			"type": "product",
			"id": row.get("item_code"),
			"label": row.get("item_name") or row.get("item_code"),
			"href": f"/products/{row.get('item_code')}",
			"data": row,
		}
		for row in products
	]
	tool_calls = [
		{
			"tool": "search_products",
			"risk_level": "L1_READ_ONLY",
			"query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
			"search_term_hashes": [hashlib.sha256(term.encode("utf-8")).hexdigest() for term in search_terms],
			"company": resolved_company,
			"result_count": len(products),
			"retrieval_mode": "hybrid" if semantic_result.get("available") else "lexical_fallback",
			"semantic_result_count": len(semantic_result.get("rows") or []),
			"embedding_model": semantic_result.get("embedding_model"),
			"vector_collection": semantic_result.get("collection"),
		}
	]
	context = {
		"tool": "search_products",
		"query": query,
		"search_terms": search_terms,
		"company": resolved_company,
		"products": products,
		"retrieval": {
			"mode": "hybrid" if semantic_result.get("available") else "lexical_fallback",
			"semantic_available": bool(semantic_result.get("available")),
		},
		"instructions": "商品数据是只读工具结果。只能基于这些候选解释匹配原因；不得编造商品、价格或库存。",
	}
	return context, citations, tool_calls


def _parse_amount_value(value: str, unit: str | None) -> float:
	amount = float(value.replace(",", ""))
	if unit == "万":
		amount *= 10000
	elif unit == "千":
		amount *= 1000
	return amount


def _resolve_natural_date_range(
	query: str, *, as_of: date | None = None, default_days: int | None = 30,
) -> dict:
	text = " ".join((query or "").strip().split())
	today = as_of or date.today()
	date_to = today if default_days is not None else None
	date_from = today - timedelta(days=max(1, default_days or 1) - 1) if default_days is not None else None
	date_range = f"last_{max(1, default_days or 1)}_days" if default_days is not None else "all"
	if "今天" in text or "今日" in text:
		date_from = date_to = today
		date_range = "today"
	elif "本周" in text or "这周" in text:
		date_from = today - timedelta(days=today.weekday())
		date_to = today
		date_range = "this_week"
	elif "上月" in text or "上个月" in text:
		last_month_end = today.replace(day=1) - timedelta(days=1)
		date_from = last_month_end.replace(day=1)
		date_to = last_month_end
		date_range = "last_month"
	elif "本月" in text or "这个月" in text:
		date_from = today.replace(day=1)
		date_to = today
		date_range = "this_month"
	elif match := re.search(r"近\s*(\d{1,3})\s*天", text):
		days = max(1, min(366, int(match.group(1))))
		date_from = today - timedelta(days=days - 1)
		date_to = today
		date_range = f"last_{days}_days"
	return {
		"date_range": date_range,
		"date_from": str(date_from) if date_from else None,
		"date_to": str(date_to) if date_to else None,
	}


def _build_order_query_dsl(query: str, *, company: str, as_of: date | None = None) -> dict:
	text = " ".join((query or "").strip().split())
	mentions_sales = any(word in text for word in ("销售", "客户", "收款", "发货"))
	mentions_purchase = any(word in text for word in ("采购", "供应商", "付款", "收货"))
	entities = []
	for entity, terms in (
		("sales_order", ("销售订单", "客户订单")),
		("sales_invoice", ("销售发票", "客户发票")),
		("purchase_order", ("采购订单", "供应商订单")),
		("purchase_invoice", ("采购发票", "供应商发票")),
	):
		if any(term in text for term in terms):
			entities.append(entity)
	shared_invoice_noun = bool(
		re.search(r"(?:销售\s*(?:和|与|、)\s*采购|采购\s*(?:和|与|、)\s*销售)发票", text)
	)
	shared_order_noun = bool(
		re.search(r"(?:销售\s*(?:和|与|、)\s*采购|采购\s*(?:和|与|、)\s*销售)订单", text)
	)
	if "发票" in text and (shared_invoice_noun or not any(entity.endswith("_invoice") for entity in entities)):
		if shared_invoice_noun or mentions_sales:
			entities.append("sales_invoice")
		if shared_invoice_noun or (mentions_purchase and not mentions_sales):
			entities.append("purchase_invoice")
		if not mentions_sales and not mentions_purchase:
			entities.append("sales_invoice")
	if "订单" in text and (shared_order_noun or not any(entity.endswith("_order") for entity in entities)):
		if shared_order_noun or mentions_sales:
			entities.append("sales_order")
		if shared_order_noun or (mentions_purchase and not mentions_sales):
			entities.append("purchase_order")
	if not entities:
		entities.append("purchase_order" if mentions_purchase else "sales_order")
	entities = [
		entity
		for entity in ("sales_order", "sales_invoice", "purchase_order", "purchase_invoice")
		if entity in entities
	]
	entity = entities[0]

	date_filter = _resolve_natural_date_range(text, as_of=as_of, default_days=None)

	status_filter = "all"
	if "未完成" in text or "进行中" in text:
		status_filter = "unfinished"
	elif "已完成" in text or "完成的" in text:
		status_filter = "completed"
	elif "取消" in text or "作废" in text:
		status_filter = "cancelled"
	elif entity == "sales_order" and any(word in text for word in ("待发货", "未发货", "发货中")):
		status_filter = "delivering"
	elif entity == "purchase_order" and any(word in text for word in ("待收货", "未收货", "收货中")):
		status_filter = "receiving"
	elif any(word in text for word in ("待付款", "未付款", "待收款", "未收款")):
		status_filter = "paying"

	sort_by = "latest"
	if any(word in text for word in ("大额", "金额最高", "金额最大", "从高到低")):
		sort_by = "amount_desc"
	elif any(word in text for word in ("金额最低", "金额最小", "从低到高")):
		sort_by = "amount_asc"
	elif "最早" in text:
		sort_by = "oldest"

	min_amount = None
	if match := re.search(r"(?:超过|大于|高于|不少于|至少)\s*([0-9][0-9,.]*)\s*(万|千)?", text):
		min_amount = _parse_amount_value(match.group(1), match.group(2))
	limit = 10
	limit_explicit = False
	if match := re.search(r"(?:前\s*)?(\d{1,2})\s*(?:条|个|笔)", text):
		limit = max(1, min(20, int(match.group(1))))
		limit_explicit = True

	return {
		"entity": entity,
		"entities": entities,
		"company": company,
		**date_filter,
		"status_filter": status_filter,
		"exclude_cancelled": status_filter != "cancelled",
		"sort_by": sort_by,
		"min_amount": min_amount,
		"limit": limit,
		"limit_explicit": limit_explicit,
	}


BUSINESS_DOCUMENT_QUERY_CONFIG = {
	"sales_order": {
		"doctype": "Sales Order",
		"label": "销售订单",
		"citation_type": "sales_order",
		"href_prefix": "/sales/orders",
		"tool": "search_sales_orders",
	},
	"sales_invoice": {
		"doctype": "Sales Invoice",
		"label": "销售发票",
		"citation_type": "sales_invoice",
		"href_prefix": "/sales/invoices",
		"tool": "list_sales_invoices",
	},
	"purchase_order": {
		"doctype": "Purchase Order",
		"label": "采购订单",
		"citation_type": "purchase_order",
		"href_prefix": "/purchase/orders",
		"tool": "search_purchase_orders",
	},
	"purchase_invoice": {
		"doctype": "Purchase Invoice",
		"label": "采购发票",
		"citation_type": "purchase_invoice",
		"href_prefix": "/purchase/invoices",
		"tool": "list_purchase_invoices",
	},
}


def _filter_allowed_document_names(doctype: str, rows: list[dict], name_field: str) -> set[str]:
	candidate_names = [row.get(name_field) for row in rows if row.get(name_field)]
	if not candidate_names:
		return set()
	return set(
		frappe.get_list(
			doctype,
			filters={"name": ["in", candidate_names]},
			pluck="name",
			limit_page_length=max(1, len(candidate_names)),
		)
	)


def _query_business_document_entity(*, entity: str, dsl: dict) -> tuple[list[dict], dict]:
	config = BUSINESS_DOCUMENT_QUERY_CONFIG[entity]
	doctype = config["doctype"]
	if not frappe.has_permission(doctype, ptype="read"):
		raise frappe.PermissionError(_("无权读取{0}。").format(config["label"]))
	query_limit = 50 if dsl.get("min_amount") is not None else dsl["limit"]
	if entity in {"sales_order", "purchase_order"}:
		is_sales = entity == "sales_order"
		search = search_sales_orders_v2 if is_sales else search_purchase_orders_v2
		result = search(
			company=dsl["company"],
			date_from=dsl["date_from"],
			date_to=dsl["date_to"],
			status_filter=dsl["status_filter"],
			exclude_cancelled=dsl["exclude_cancelled"],
			sort_by=dsl["sort_by"],
			limit=query_limit,
			start=0,
		)
		data = (result or {}).get("data") or {}
		rows = data.get("items") or []
		name_field = "order_name" if is_sales else "purchase_order_name"
		allowed_names = _filter_allowed_document_names(doctype, rows, name_field)
		items = []
		for row in rows:
			name = row.get(name_field)
			amount = float(row.get("order_amount_estimate") or 0)
			if name not in allowed_names:
				continue
			if dsl.get("min_amount") is not None and amount < dsl["min_amount"]:
				continue
			items.append(
				{
					"document_type": entity,
					"name": name,
					"party": row.get("customer_name") if is_sales else row.get("supplier_name"),
					"company": row.get("company"),
					"transaction_date": str(row.get("transaction_date") or ""),
					"delivery_date": str(row.get("delivery_date") or "") or None,
					"document_status": row.get("document_status"),
					"currency": row.get("currency") or "CNY",
					"amount": amount,
					"outstanding_amount": float(row.get("outstanding_amount") or 0),
					"completion": row.get("completion") or {},
				}
			)
			if len(items) >= dsl["limit"]:
				break
		return items, data.get("summary") or {}

	docstatus = 2 if dsl["status_filter"] == "cancelled" else 1 if dsl["status_filter"] == "completed" else None
	result = list_business_documents_v1(
		doctype=doctype,
		company=dsl["company"],
		date_from=dsl["date_from"],
		date_to=dsl["date_to"],
		docstatus=docstatus,
		sort_by=dsl["sort_by"],
		limit=query_limit,
		start=0,
	)
	data = (result or {}).get("data") or {}
	rows = data.get("items") or []
	allowed_names = _filter_allowed_document_names(doctype, rows, "name")
	items = []
	for row in rows:
		amount = float(row.get("amount") or 0)
		if row.get("name") not in allowed_names:
			continue
		if dsl["exclude_cancelled"] and int(row.get("docstatus") or 0) == 2:
			continue
		if dsl.get("min_amount") is not None and amount < dsl["min_amount"]:
			continue
		items.append(
			{
				"document_type": entity,
				"name": row.get("name"),
				"party": row.get("party_name") or row.get("party"),
				"company": row.get("company"),
				"transaction_date": str(row.get("posting_date") or ""),
				"due_date": str(row.get("due_date") or "") or None,
				"document_status": row.get("business_status") or row.get("document_status"),
				"currency": row.get("currency") or "CNY",
				"amount": amount,
				"outstanding_amount": float(row.get("outstanding_amount") or 0),
				"paid_amount": float(row.get("paid_amount") or 0),
			}
		)
		if len(items) >= dsl["limit"]:
			break
	return items, data.get("summary") or {}


def _build_order_query_context(*, query: str, company: str | None) -> tuple[dict, list[dict], list[dict]]:
	resolved_company = _resolve_company_scope(company, required=True)
	dsl = _build_order_query_dsl(query, company=resolved_company)
	groups = []
	citations = []
	tool_calls = []
	for entity in dsl["entities"]:
		config = BUSINESS_DOCUMENT_QUERY_CONFIG[entity]
		items, summary = _query_business_document_entity(entity=entity, dsl=dsl)
		groups.append(
			{
				"entity": entity,
				"label": config["label"],
				"summary": summary,
				"items": items,
			}
		)
		citations.extend(
			{
				"type": config["citation_type"],
				"id": row["name"],
				"label": f"{config['label']} {row['name']} · {row.get('party') or ''}",
				"href": f"{config['href_prefix']}/{row['name']}",
				"data": row,
			}
			for row in items
		)
		tool_calls.append(
			{
				"tool": config["tool"],
				"risk_level": "L1_READ_ONLY",
				"dsl_hash": hashlib.sha256(
					json.dumps({**dsl, "entity": entity}, sort_keys=True).encode("utf-8")
				).hexdigest(),
				"company": resolved_company,
				"result_count": len(items),
			}
		)
	result_set = {
		"schema_version": "business-result-set-v1",
		"result_type": "business_documents",
		"status_semantics": "result_coverage_only",
		"scope": {
			"company": resolved_company,
			"date_range": dsl["date_range"],
			"date_from": dsl["date_from"],
			"date_to": dsl["date_to"],
			"status_filter": dsl["status_filter"],
			"sort_by": dsl["sort_by"],
			"min_amount": dsl["min_amount"],
			"limit_per_group": dsl["limit"],
		},
		"groups": [
			{
				"entity": group["entity"],
				"label": group["label"],
				"requested_count": dsl["limit"] if dsl["limit_explicit"] else None,
				"returned_count": len(group["items"]),
				"status": (
					"empty"
					if not group["items"]
					else "partial"
					if dsl["limit_explicit"] and len(group["items"]) < dsl["limit"]
					else "success"
				),
			}
			for group in groups
		],
	}
	result_set_id = hashlib.sha256(
		json.dumps(result_set, ensure_ascii=False, sort_keys=True).encode("utf-8")
	).hexdigest()[:24]
	citations.insert(
		0,
		{
			"type": "business_result_set",
			"id": result_set_id,
			"label": _("业务查询结果"),
			"href": None,
			"data": result_set,
		},
	)
	context = {
		"tool": "query_business_documents",
		"query": query,
		"dsl": dsl,
		"result_set": result_set,
		"document_groups": result_set["groups"],
		"instructions": (
			"业务单据来自当前账号权限和公司范围内的受控业务查询。"
			"界面会直接展示按单据类型分组的结构化明细、查询范围和数量不足提示。"
			"回答不要逐条复述单据号、往来单位、日期、状态、金额或未结金额，也不要重复生成明细清单。"
			"分组 status 只表示结果数量覆盖情况，不表示单据业务健康或没有异常。"
			"只用最多三个简短要点概括查询范围、各类型返回数量和空结果；未提供明确异常字段时不得声称结果正常、无异常或无需关注。"
			"不得编造未返回的记录。"
		),
	}
	return context, citations, tool_calls


def _build_report_query_dsl(query: str, *, company: str, as_of: date | None = None) -> dict:
	text = " ".join((query or "").strip().split())
	mentions_sales = any(word in text for word in ("销售", "营收", "客户"))
	mentions_purchase = any(word in text for word in ("采购", "供应商"))
	mentions_cashflow = any(word in text for word in ("现金流", "资金", "收款", "付款", "净流入", "净流出"))
	mentions_receivable = "应收" in text
	mentions_payable = "应付" in text
	mentions_receivable_payable = (
		(mentions_receivable and mentions_payable)
		or any(word in text for word in ("欠款", "往来账"))
		or (mentions_receivable and not mentions_sales)
		or (mentions_payable and not mentions_purchase)
	)

	if mentions_receivable_payable:
		report_type = "receivable_payable"
	elif mentions_cashflow and not (mentions_sales or mentions_purchase):
		report_type = "cashflow"
	elif mentions_sales and mentions_purchase:
		report_type = "overview"
	elif mentions_purchase:
		report_type = "purchase"
	elif mentions_sales:
		report_type = "sales"
	else:
		report_type = "overview"

	return {
		"report_type": report_type,
		"company": company,
		**_resolve_natural_date_range(text, as_of=as_of),
		"limit": 10,
	}


def _require_report_permissions(report_type: str):
	required_doctypes = {
		"overview": ("Sales Order", "Purchase Order", "Payment Entry", "Sales Invoice", "Purchase Invoice"),
		"sales": ("Sales Order", "Payment Entry", "Sales Invoice"),
		"purchase": ("Purchase Order", "Payment Entry", "Purchase Invoice"),
		"cashflow": ("Payment Entry",),
		"receivable_payable": ("Sales Invoice", "Purchase Invoice"),
	}[report_type]
	for doctype in required_doctypes:
		if not frappe.has_permission(doctype, ptype="read"):
			raise frappe.PermissionError(_("无权读取报表所需的 {0} 数据。").format(doctype))


def _build_report_query_context(*, query: str, company: str | None) -> tuple[dict, list[dict], list[dict]]:
	resolved_company = _resolve_company_scope(company, required=True)
	dsl = _build_report_query_dsl(query, company=resolved_company)
	report_type = dsl["report_type"]
	_require_report_permissions(report_type)
	params = {
		"company": resolved_company,
		"date_from": dsl["date_from"],
		"date_to": dsl["date_to"],
	}
	if report_type == "sales":
		result = get_sales_report_v1(**params, limit=dsl["limit"])
	elif report_type == "purchase":
		result = get_purchase_report_v1(**params, limit=dsl["limit"])
	elif report_type == "cashflow":
		result = get_cashflow_report_v1(**params)
	elif report_type == "receivable_payable":
		result = get_receivable_payable_report_v1(**params, limit=dsl["limit"])
	else:
		result = get_business_report_overview_v1(**params)

	report_data = (result or {}).get("data") or {}
	report_labels = {
		"overview": "经营总览",
		"sales": "销售分析",
		"purchase": "采购分析",
		"cashflow": "资金分析",
		"receivable_payable": "应收应付分析",
	}
	citation_data = {
		"report_type": report_type,
		"overview": report_data.get("overview") or {},
		"meta": report_data.get("meta") or params,
	}
	citations = [
		{
			"type": "business_report",
			"id": f"{report_type}:{dsl['date_from']}:{dsl['date_to']}",
			"label": f"{report_labels[report_type]} · {dsl['date_from']} 至 {dsl['date_to']}",
			"href": "/reports",
			"data": citation_data,
		}
	]
	tool_calls = [
		{
			"tool": "get_business_report",
			"risk_level": "L1_READ_ONLY",
			"dsl_hash": hashlib.sha256(json.dumps(dsl, sort_keys=True).encode("utf-8")).hexdigest(),
			"company": resolved_company,
			"report_type": report_type,
			"result_count": len(report_data.get("tables") or report_data.get("trend") or []) or 1,
		}
	]
	context = {
		"tool": "get_business_report",
		"query": query,
		"dsl": dsl,
		"report": report_data,
		"instructions": (
			"报表数据来自受控只读报表服务。回答必须说明公司、日期范围、报表类型和指标口径；"
			"区分订单金额、实际收付款和发票未结金额，不得虚构趋势、原因或未返回的明细。"
		),
	}
	return context, citations, tool_calls


def _build_events(*, content: str, citations: list[dict], warnings: list[str], tool_calls: list[dict]) -> list[dict]:
	events = []
	for tool_call in tool_calls:
		events.extend(
			[
				{"type": "tool_started", "tool": tool_call.get("tool")},
				{
					"type": "tool_completed",
					"tool": tool_call.get("tool"),
					"result_count": tool_call.get("result_count", 0),
				},
			]
		)
	events.append({"type": "message_delta", "delta": content})
	events.extend({"type": "citation", "citation": citation} for citation in citations)
	events.extend({"type": "warning", "message": warning} for warning in warnings)
	events.append({"type": "completed"})
	return events


def create_ai_conversation_v1(title: str | None = None, company: str | None = None):
	user = _current_user()
	resolved_company = _resolve_company_scope(company)
	return {
		"status": "success",
		"message": _("AI 会话已创建。"),
		"data": ai_repository.create_conversation(user=user, title=title, company=resolved_company),
	}


def list_ai_conversations_v1(status: str = "active", start: int = 0, limit: int = 20):
	user = _current_user()
	return {
		"status": "success",
		"message": _("已获取 AI 会话列表。"),
		"data": ai_repository.list_conversations(user=user, status=status, start=start, limit=limit),
	}


def get_ai_conversation_v1(conversation_id: str):
	user = _current_user()
	return {
		"status": "success",
		"message": _("已获取 AI 会话。"),
		"data": ai_repository.get_conversation(conversation_id=conversation_id, user=user),
	}


def archive_ai_conversation_v1(conversation_id: str):
	user = _current_user()
	return {
		"status": "success",
		"message": _("AI 会话已归档。"),
		"data": ai_repository.archive_conversation(conversation_id=conversation_id, user=user),
	}


def resolve_ai_scenario_v1(content: str):
	resolved_content = _normalize_content(content)
	return {
		"status": "success",
		"message": _("AI 场景识别完成。"),
		"data": {"scenario": _infer_ai_action_scenario(resolved_content)},
	}


def submit_ai_feedback_v1(
	run_id: str,
	rating: str,
	category: str | None = None,
	comment: str | None = None,
):
	user = _current_user()
	resolved_rating = (rating or "").strip().lower()
	if resolved_rating not in {"positive", "negative"}:
		frappe.throw(_("AI 反馈 rating 只支持 positive 或 negative。"))
	resolved_category = (category or "").strip().lower() or None
	allowed_categories = {"helpful", "incorrect", "incomplete", "unsafe", "other"}
	if resolved_category and resolved_category not in allowed_categories:
		frappe.throw(_("AI 反馈 category 不正确。"))
	resolved_comment = (comment or "").strip() or None
	if resolved_comment and len(resolved_comment) > 1000:
		frappe.throw(_("AI 反馈说明不能超过 1000 个字符。"))
	feedback = ai_repository.submit_feedback(
		run_id=(run_id or "").strip(),
		user=user,
		rating=resolved_rating,
		category=resolved_category,
		comment=resolved_comment,
	)
	feedback["observability_synced"] = _sync_ai_feedback_to_orchestrator(
		{
			"trace_id": feedback.get("trace_id"),
			"run_id": feedback["run_id"],
			"rating": feedback["rating"],
			"category": feedback.get("category"),
			"comment": feedback.get("comment"),
		}
	)
	return {
		"status": "success",
		"message": _("AI 反馈已记录。"),
		"data": feedback,
	}


def _resolve_sales_draft_customer(query: str | None) -> tuple[dict | None, list[dict]]:
	query = str(query or "").strip()
	if not query:
		return None, []
	result = list_customers_v2(search_key=query, disabled=0, limit=5, start=0)
	rows = (result or {}).get("data") or []
	allowed = set(
		frappe.get_list(
			"Customer",
			filters={"name": ["in", [row.get("name") for row in rows if row.get("name")]]},
			pluck="name",
			limit_page_length=max(1, len(rows)),
		)
		if rows
		else []
	)
	candidates = [
		{"name": row.get("name"), "display_name": row.get("display_name") or row.get("customer_name")}
		for row in rows
		if row.get("name") in allowed
	]
	exact = next(
		(
			row for row in candidates
			if query.lower() in {str(row.get("name") or "").lower(), str(row.get("display_name") or "").lower()}
		),
		None,
	)
	return exact or (candidates[0] if len(candidates) == 1 else None), candidates


def _resolve_purchase_draft_supplier(query: str | None) -> tuple[dict | None, list[dict]]:
	query = str(query or "").strip()
	if not query:
		return None, []
	rows = (list_suppliers_v2(search_key=query, disabled=0, limit=5, start=0) or {}).get("data") or []
	allowed = set(
		frappe.get_list(
			"Supplier", filters={"name": ["in", [row.get("name") for row in rows if row.get("name")]]},
			pluck="name", limit_page_length=max(1, len(rows)),
		) if rows else []
	)
	candidates = [
		{"name": row.get("name"), "display_name": row.get("display_name") or row.get("supplier_name")}
		for row in rows if row.get("name") in allowed
	]
	exact = next(
		(row for row in candidates if query.lower() in {
			str(row.get("name") or "").lower(), str(row.get("display_name") or "").lower(),
		}), None,
	)
	return exact or (candidates[0] if len(candidates) == 1 else None), candidates


def _resolve_purchase_draft_item(
	candidate: dict, *, company: str, default_warehouse: str | None,
	allow_user_price: bool = False,
) -> dict:
	query = str(candidate.get("item_query") or "").strip()
	qty = float(candidate.get("qty") or 0)
	rows = (search_product_v2(
		search_key=query, company=company, limit=5, disabled=0, item_context="purchase",
	) or {}).get("data") or []
	allowed = set(
		frappe.get_list(
			"Item", filters={"name": ["in", [row.get("item_code") for row in rows if row.get("item_code")]]},
			pluck="name", limit_page_length=max(1, len(rows)),
		) if rows else []
	)
	rows = [row for row in rows if row.get("item_code") in allowed]
	exact = next((row for row in rows if query.lower() in {
		str(row.get("item_code") or "").lower(), str(row.get("item_name") or "").lower(),
		str(row.get("nickname") or "").lower(),
	}), None)
	selected = exact or (rows[0] if len(rows) == 1 else None)
	warnings = []
	warehouse = _resolve_sales_draft_warehouse(candidate.get("warehouse_query"), company) or default_warehouse
	if qty <= 0:
		warnings.append(_("数量必须大于 0。"))
	if not warehouse:
		warnings.append(_("缺少当前公司可用的收货仓库。"))
	if not selected:
		warnings.append(_("商品“{0}”无法唯一匹配，请人工选择。" ).format(query))
		return {
			"item_query": query, "item_code": None, "item_name": None, "qty": qty,
			"uom": candidate.get("uom"), "uom_display": None, "stock_uom": None,
			"stock_uom_display": None, "price": None, "warehouse": warehouse,
			"conversion_factor": None,
			"candidates": [{"item_code": row.get("item_code"), "item_name": row.get("item_name")} for row in rows],
			"warnings": warnings,
		}
	all_uoms = selected.get("all_uoms") or []
	requested_uom = str(candidate.get("uom") or "").strip()
	uom_row = next((row for row in all_uoms if str(row.get("uom") or "") == requested_uom), None)
	if requested_uom and not uom_row:
		warnings.append(_("商品 {0} 未配置单位 {1}，已改用采购默认单位。" ).format(selected.get("item_code"), requested_uom))
	resolved_uom = (uom_row or {}).get("uom") or selected.get("wholesale_default_uom") or selected.get("uom")
	price_summary = selected.get("price_summary") or {}
	buying_prices = price_summary.get("buying_prices") or []
	reference_price = float(
		price_summary.get("standard_buying_rate")
		or (buying_prices[0].get("rate") if buying_prices else 0)
		or 0
	)
	user_price = None if candidate.get("price") in (None, "") else float(candidate.get("price"))
	if allow_user_price and user_price is not None and user_price < 0:
		warnings.append(_("人工价格不能小于 0，已改用当前后端采购参考价。"))
		user_price = None
	resolved_price = user_price if allow_user_price and user_price is not None else reference_price
	if not allow_user_price and user_price is not None and user_price != reference_price:
		warnings.append(_("模型建议价格未采用，草稿使用当前后端采购参考价。"))
	return {
		"item_query": query, "item_code": selected.get("item_code"), "item_name": selected.get("item_name"),
		"qty": qty, "uom": resolved_uom,
		"uom_display": (uom_row or {}).get("uom_display") or resolve_uom_display_name(resolved_uom),
		"stock_uom": selected.get("uom"), "stock_uom_display": selected.get("uom_display"),
		"price": resolved_price, "warehouse": warehouse,
		"conversion_factor": float((uom_row or {}).get("conversion_factor") or 1),
		"candidates": [{"item_code": row.get("item_code"), "item_name": row.get("item_name")} for row in rows],
		"warnings": warnings,
	}


def _resolve_inventory_draft_warehouse(query: str | None, company: str) -> tuple[str | None, list[dict]]:
	query = str(query or "").strip() or str(frappe.defaults.get_user_default("warehouse") or "").strip()
	if not query:
		return None, []
	rows = frappe.get_list(
		"Warehouse",
		filters={"company": company, "disabled": 0, "is_group": 0},
		or_filters={"name": ["like", f"%{query}%"], "warehouse_name": ["like", f"%{query}%"]},
		fields=["name", "warehouse_name", "company"],
		limit_page_length=5,
	)
	candidates = [
		{"name": row.get("name"), "display_name": row.get("warehouse_name") or row.get("name")}
		for row in rows
	]
	exact = next(
		(
			row for row in candidates
			if query.lower() in {
				str(row.get("name") or "").lower(),
				str(row.get("display_name") or "").lower(),
			}
		),
		None,
	)
	selected = exact or (candidates[0] if len(candidates) == 1 else None)
	return (selected.get("name") if selected else None), candidates


def _resolve_inventory_draft_item(
	candidate: dict,
	*,
	company: str,
	warehouse: str | None,
) -> dict:
	query = str(candidate.get("item_query") or "").strip()
	adjustment_type = str(candidate.get("adjustment_type") or "set_target").strip()
	quantity_value = candidate.get("quantity")
	input_qty = None if quantity_value in (None, "") else flt(quantity_value)
	warnings = []
	rows = []
	if query:
		rows = (
			search_product_v2(
				search_key=query,
				company=company,
				warehouse=warehouse,
				limit=5,
				disabled=0,
				item_context="inventory",
			)
			or {}
		).get("data") or []
	allowed = set(
		frappe.get_list(
			"Item",
			filters={"name": ["in", [row.get("item_code") for row in rows if row.get("item_code")]]},
			pluck="name",
			limit_page_length=max(1, len(rows)),
		)
		if rows
		else []
	)
	rows = [row for row in rows if row.get("item_code") in allowed]
	exact = next(
		(
			row for row in rows
			if query.lower() in {
				str(row.get("item_code") or "").lower(),
				str(row.get("item_name") or "").lower(),
				str(row.get("nickname") or "").lower(),
			}
		),
		None,
	)
	selected = exact or (rows[0] if len(rows) == 1 else None)
	if not selected:
		warnings.append(_("商品“{0}”无法唯一匹配，请人工选择。").format(query or _("未填写")))
		return {
			"item_query": query,
			"item_code": None,
			"item_name": None,
			"qty": input_qty,
			"uom": candidate.get("uom"),
			"uom_display": None,
			"stock_uom": None,
			"stock_uom_display": None,
			"warehouse": warehouse,
			"conversion_factor": None,
			"current_stock_qty": None,
			"target_stock_qty": None,
			"qty_delta": None,
			"valuation_rate": None,
			"candidates": [
				{"item_code": row.get("item_code"), "item_name": row.get("item_name")}
				for row in rows
			],
			"warnings": warnings,
		}

	stock_uom = selected.get("uom")
	all_uoms = selected.get("all_uoms") or []
	requested_uom = str(candidate.get("uom") or "").strip()
	uom_row = next((row for row in all_uoms if str(row.get("uom") or "") == requested_uom), None)
	if requested_uom == stock_uom:
		uom_row = uom_row or {"uom": stock_uom, "conversion_factor": 1, "uom_display": selected.get("uom_display")}
	if requested_uom and not uom_row:
		warnings.append(_("商品 {0} 未配置单位 {1}，已改用库存单位。").format(selected.get("item_code"), requested_uom))
	resolved_uom = (uom_row or {}).get("uom") or stock_uom
	quantity_context = None
	if input_qty is not None:
		quantity_context = resolve_item_quantity_to_stock(
			item_code=selected.get("item_code"),
			qty=input_qty,
			uom=resolved_uom,
		)
	current_stock_qty = flt(selected.get("qty") or 0)
	resolved_stock_qty = flt((quantity_context or {}).get("stock_qty")) if quantity_context else None
	target_stock_qty = None
	if resolved_stock_qty is not None:
		if adjustment_type == "increase":
			target_stock_qty = flt(current_stock_qty + resolved_stock_qty)
		elif adjustment_type == "decrease":
			target_stock_qty = flt(current_stock_qty - resolved_stock_qty)
		else:
			target_stock_qty = resolved_stock_qty
	price_summary = selected.get("price_summary") or {}
	return {
		"item_query": query,
		"item_code": selected.get("item_code"),
		"item_name": selected.get("item_name"),
		"qty": input_qty,
		"uom": resolved_uom,
		"uom_display": (uom_row or {}).get("uom_display") or resolve_uom_display_name(resolved_uom),
		"stock_uom": stock_uom,
		"stock_uom_display": selected.get("uom_display") or resolve_uom_display_name(stock_uom),
		"warehouse": warehouse,
		"conversion_factor": flt((quantity_context or {}).get("conversion_factor") or 1),
		"current_stock_qty": current_stock_qty,
		"target_stock_qty": target_stock_qty,
		"qty_delta": flt(target_stock_qty - current_stock_qty) if target_stock_qty is not None else None,
		"valuation_rate": flt(price_summary.get("valuation_rate") or 0),
		"candidates": [
			{"item_code": row.get("item_code"), "item_name": row.get("item_name")}
			for row in rows
		],
		"warnings": warnings,
	}


def _build_inventory_adjustment_draft(candidate: dict, *, company: str) -> tuple[dict, dict]:
	items = candidate.get("items") if isinstance(candidate.get("items"), list) else []
	source_item = items[0] if items and isinstance(items[0], dict) else candidate
	adjustment_type = str(candidate.get("adjustment_type") or source_item.get("adjustment_type") or "set_target").strip()
	if adjustment_type not in {"set_target", "increase", "decrease"}:
		adjustment_type = "set_target"
	warehouse_query = candidate.get("warehouse") or candidate.get("warehouse_query") or source_item.get("warehouse")
	warehouse, warehouse_candidates = _resolve_inventory_draft_warehouse(warehouse_query, company)
	quantity = candidate.get("quantity")
	if quantity in (None, ""):
		quantity = source_item.get("qty")
	item = _resolve_inventory_draft_item(
		{
			"item_query": candidate.get("item_code") or candidate.get("item_query")
				or source_item.get("item_code") or source_item.get("item_query"),
			"adjustment_type": adjustment_type,
			"quantity": quantity,
			"uom": candidate.get("uom") or source_item.get("uom"),
		},
		company=company,
		warehouse=warehouse,
	)
	reason = str(candidate.get("reason") or candidate.get("remarks") or "").strip()[:1000] or None
	errors = []
	if not warehouse:
		errors.append(_("仓库无法唯一匹配，请人工选择。"))
	if not item.get("item_code"):
		errors.append(_("商品无法唯一匹配，请人工选择。"))
	if item.get("qty") is None:
		errors.append(_("请填写库存调整数量。"))
	elif adjustment_type in {"increase", "decrease"} and flt(item.get("qty")) <= 0:
		errors.append(_("增减库存数量必须大于 0。"))
	if item.get("target_stock_qty") is not None and flt(item.get("target_stock_qty")) < 0:
		errors.append(_("调整后的目标库存不能为负数。"))
	if not reason:
		errors.append(_("库存调整必须填写盘点差异或业务原因。"))
	try:
		posting_date = str(getdate(candidate.get("posting_date") or nowdate()))
	except Exception:
		posting_date = str(nowdate())
		errors.append(_("过账日期格式不正确。"))
	payload = {
		"company": company,
		"posting_date": posting_date,
		"adjustment_type": adjustment_type,
		"warehouse_query": warehouse_query,
		"warehouse": warehouse,
		"warehouse_candidates": warehouse_candidates,
		"reason": reason,
		"remarks": reason,
		"items": [item],
	}
	validation = {
		"ready_for_handoff": not errors,
		"errors": errors,
		"warnings": item.get("warnings") or [],
	}
	return payload, validation


def _resolve_sales_draft_warehouse(query: str | None, company: str) -> str | None:
	resolved = str(query or "").strip()
	if not resolved:
		resolved = str(frappe.defaults.get_user_default("warehouse") or "").strip()
	if not resolved:
		return None
	rows = frappe.get_list(
		"Warehouse",
		filters={"name": resolved, "company": company, "disabled": 0, "is_group": 0},
		pluck="name",
		limit_page_length=1,
	)
	return rows[0] if rows else None


def _resolve_sales_draft_item(
	candidate: dict, *, company: str, default_warehouse: str | None,
	allow_user_price: bool = False,
) -> dict:
	query = str(candidate.get("item_query") or "").strip()
	qty = float(candidate.get("qty") or 0)
	rows = (
		(search_product_v2(search_key=query, company=company, limit=5, disabled=0, item_context="sales") or {}).get("data")
		or []
	)
	allowed = set(
		frappe.get_list(
			"Item",
			filters={"name": ["in", [row.get("item_code") for row in rows if row.get("item_code")]]},
			pluck="name",
			limit_page_length=max(1, len(rows)),
		)
		if rows
		else []
	)
	rows = [row for row in rows if row.get("item_code") in allowed]
	exact = next(
		(
			row for row in rows
			if query.lower() in {
				str(row.get("item_code") or "").lower(),
				str(row.get("item_name") or "").lower(),
				str(row.get("nickname") or "").lower(),
			}
		),
		None,
	)
	selected = exact or (rows[0] if len(rows) == 1 else None)
	warnings = []
	if qty <= 0:
		warnings.append(_("数量必须大于 0。"))
	warehouse = _resolve_sales_draft_warehouse(candidate.get("warehouse_query"), company) or default_warehouse
	if not warehouse:
		warnings.append(_("缺少当前公司可用的明细仓库。"))
	if not selected:
		warnings.append(_("商品“{0}”无法唯一匹配，请人工选择。" ).format(query))
		return {
			"item_query": query, "item_code": None, "item_name": None, "qty": qty,
			"uom": candidate.get("uom"), "uom_display": None, "price": None,
			"stock_uom": None, "stock_uom_display": None,
			"warehouse": warehouse, "conversion_factor": None,
			"candidates": [{"item_code": row.get("item_code"), "item_name": row.get("item_name")} for row in rows],
			"warnings": warnings,
		}
	all_uoms = selected.get("all_uoms") or []
	requested_uom = str(candidate.get("uom") or "").strip()
	uom_row = next((row for row in all_uoms if str(row.get("uom") or "") == requested_uom), None)
	if requested_uom and not uom_row:
		warnings.append(_("商品 {0} 未配置单位 {1}，已改用默认单位。" ).format(selected.get("item_code"), requested_uom))
	resolved_uom = (uom_row or {}).get("uom") or selected.get("wholesale_default_uom") or selected.get("uom")
	reference_price = float(selected.get("price") or 0)
	user_price = None if candidate.get("price") in (None, "") else float(candidate.get("price"))
	if allow_user_price and user_price is not None and user_price < 0:
		warnings.append(_("人工价格不能小于 0，已改用当前后端参考价。"))
		user_price = None
	resolved_price = user_price if allow_user_price and user_price is not None else reference_price
	if not allow_user_price and user_price is not None and user_price != reference_price:
		warnings.append(_("模型建议价格未采用，草稿使用当前后端参考价。"))
	return {
		"item_query": query,
		"item_code": selected.get("item_code"),
		"item_name": selected.get("item_name"),
		"qty": qty,
		"uom": resolved_uom,
		"uom_display": (uom_row or {}).get("uom_display") or resolve_uom_display_name(resolved_uom),
		"stock_uom": selected.get("uom"),
		"stock_uom_display": selected.get("uom_display"),
		"price": resolved_price,
		"warehouse": warehouse,
		"conversion_factor": float((uom_row or {}).get("conversion_factor") or 1),
		"candidates": [{"item_code": row.get("item_code"), "item_name": row.get("item_name")} for row in rows],
		"warnings": warnings,
	}


def generate_ai_sales_order_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
):
	scenario = "sales_order_draft"
	prompt_version = _resolve_prompt_version(scenario)
	user = _current_user()
	model_alias = resolve_ai_selected_model_alias(model_alias)
	content = _normalize_content(content)
	company = _resolve_company_scope(company, required=True)
	if not frappe.has_permission("Sales Order", ptype="create"):
		raise frappe.PermissionError(_("无权创建销售订单草稿。"))
	if not conversation_id:
		conversation = ai_repository.create_conversation(user=user, title=content, company=company)
		conversation_id = conversation["name"]
	else:
		conversation = ai_repository.get_conversation(conversation_id=conversation_id, user=user)["conversation"]
		if conversation.get("company") and conversation.get("company") != company:
			frappe.throw(_("当前公司与会话公司范围不一致，请新建会话。"))
	ai_repository.append_message(
		conversation_id=conversation_id, user=user, role="user", content=content,
		scenario=scenario, prompt_version=prompt_version,
	)
	run_id = ai_repository.create_run(conversation_id=conversation_id, user=user, scenario=scenario)
	frappe.db.commit()
	started = time.perf_counter()
	try:
		model_messages = ai_repository.load_model_messages(conversation_id=conversation_id, user=user, limit=MAX_AI_MESSAGES)
		result = _call_ai_orchestrator_sales_draft(
			{
				"messages": model_messages, "scenario": scenario, "user": user,
				"company": company, "locale": getattr(frappe.local, "lang", None) or "zh-CN",
				"prompt_version": prompt_version, "conversation_id": conversation_id, "run_id": run_id,
				"model_alias": model_alias,
			}
		)
		candidate = result["draft"]
		customer, customer_candidates = _resolve_sales_draft_customer(candidate.get("customer_query"))
		default_warehouse = _resolve_sales_draft_warehouse(candidate.get("warehouse_query"), company)
		items = [
			_resolve_sales_draft_item(row, company=company, default_warehouse=default_warehouse)
			for row in candidate.get("items") or []
		]
		errors = []
		if not customer:
			errors.append(_("客户无法唯一匹配，请人工选择。"))
		if not items:
			errors.append(_("草稿没有有效商品明细。"))
		for index, row in enumerate(items, 1):
			if not row.get("item_code") or row.get("qty", 0) <= 0 or not row.get("warehouse"):
				errors.append(_("第 {0} 行需要人工补充商品、数量或仓库。" ).format(index))
		transaction_date = str(candidate.get("transaction_date") or nowdate())
		delivery_date = str(candidate.get("delivery_date") or transaction_date)
		try:
			transaction_date = str(getdate(transaction_date))
			delivery_date = str(getdate(delivery_date))
		except Exception:
			errors.append(_("订单日期或交货日期格式不正确。"))
		payload = {
			"company": company,
			"customer_query": candidate.get("customer_query"),
			"customer": customer.get("name") if customer else None,
			"customer_display_name": customer.get("display_name") if customer else None,
			"customer_candidates": customer_candidates,
			"transaction_date": transaction_date,
			"delivery_date": delivery_date,
			"default_sales_mode": candidate.get("default_sales_mode") or "wholesale",
			"warehouse": default_warehouse,
			"remarks": candidate.get("remarks"),
			"items": items,
		}
		validation = {
			"ready_for_handoff": not errors,
			"errors": errors,
			"warnings": [warning for row in items for warning in row.get("warnings") or []],
		}
		draft = ai_repository.create_draft(
			user=user, conversation_id=conversation_id, source_run=run_id,
			draft_type="sales_order", company=company, title=content,
			payload=payload, validation=validation,
		)
		assistant_content = _("已生成销售订单草稿；{0}" ).format(
			_("可以进入销售订单编辑器继续复核。") if validation["ready_for_handoff"] else _("仍有字段需要人工确认。")
		)
		citation = {"type": "ai_draft", "id": draft["name"], "label": draft["title"], "href": None, "data": draft}
		ai_repository.append_message(
			conversation_id=conversation_id, user=user, role="assistant", content=assistant_content,
			scenario=scenario, run_id=run_id, citations=[citation], prompt_version=prompt_version,
		)
		latency_ms = int((time.perf_counter() - started) * 1000)
		ai_repository.complete_run(
			run_id=run_id, user=user, result=result,
			latency_ms=latency_ms,
			tool_calls=[{"tool": "build_sales_order_draft", "risk_level": "L2_DRAFT_ONLY", "draft_id": draft["name"]}],
		)
		frappe.db.commit()
		return {
			"status": "success", "message": assistant_content,
			"data": {"conversation": conversation_id, "run_id": run_id, "draft": draft,
				"message": {"role": "assistant", "content": assistant_content, "citations": [citation]},
				"model": result.get("model"), "model_alias": result.get("model_alias"),
				"run": {"status": "completed", "latency_ms": latency_ms, "first_token_ms": None},
				"trace_id": result.get("trace_id"), "usage": result.get("usage") or {}, "warnings": result.get("warnings") or []},
		}
	except Exception as error:
		frappe.db.rollback()
		ai_repository.fail_run(run_id=run_id, user=user, error=error, latency_ms=int((time.perf_counter() - started) * 1000))
		frappe.db.commit()
		raise


def generate_ai_purchase_order_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
):
	scenario = "purchase_order_draft"
	prompt_version = _resolve_prompt_version(scenario)
	user = _current_user()
	model_alias = resolve_ai_selected_model_alias(model_alias)
	content = _normalize_content(content)
	company = _resolve_company_scope(company, required=True)
	if not frappe.has_permission("Purchase Order", ptype="create"):
		raise frappe.PermissionError(_("无权创建采购订单草稿。"))
	if not conversation_id:
		conversation = ai_repository.create_conversation(user=user, title=content, company=company)
		conversation_id = conversation["name"]
	else:
		conversation = ai_repository.get_conversation(conversation_id=conversation_id, user=user)["conversation"]
		if conversation.get("company") and conversation.get("company") != company:
			frappe.throw(_("当前公司与会话公司范围不一致，请新建会话。"))
	ai_repository.append_message(
		conversation_id=conversation_id, user=user, role="user", content=content,
		scenario=scenario, prompt_version=prompt_version,
	)
	run_id = ai_repository.create_run(conversation_id=conversation_id, user=user, scenario=scenario)
	frappe.db.commit()
	started = time.perf_counter()
	try:
		model_messages = ai_repository.load_model_messages(conversation_id=conversation_id, user=user, limit=MAX_AI_MESSAGES)
		result = _call_ai_orchestrator_purchase_draft({
			"messages": model_messages, "scenario": scenario, "user": user,
			"company": company, "locale": getattr(frappe.local, "lang", None) or "zh-CN",
			"prompt_version": prompt_version, "conversation_id": conversation_id, "run_id": run_id,
			"model_alias": model_alias,
		})
		candidate = result["draft"]
		supplier, supplier_candidates = _resolve_purchase_draft_supplier(candidate.get("supplier_query"))
		default_warehouse = _resolve_sales_draft_warehouse(candidate.get("warehouse_query"), company)
		items = [
			_resolve_purchase_draft_item(row, company=company, default_warehouse=default_warehouse)
			for row in candidate.get("items") or []
		]
		errors = []
		if not supplier:
			errors.append(_("供应商无法唯一匹配，请人工选择。"))
		if not items:
			errors.append(_("草稿没有有效商品明细。"))
		for index, row in enumerate(items, 1):
			if not row.get("item_code") or row.get("qty", 0) <= 0 or not row.get("warehouse"):
				errors.append(_("第 {0} 行需要人工补充商品、数量或收货仓库。" ).format(index))
		transaction_date = str(getdate(candidate.get("transaction_date") or nowdate()))
		schedule_date = str(getdate(candidate.get("schedule_date") or transaction_date))
		supplier_name = supplier.get("name") if supplier else None
		currency = str(candidate.get("currency") or "").strip() or None
		if supplier_name and not currency:
			currency = frappe.db.get_value("Supplier", supplier_name, "default_currency") or None
		if not currency:
			currency = frappe.db.get_value("Company", company, "default_currency") or None
		payload = {
			"company": company, "supplier_query": candidate.get("supplier_query"),
			"supplier": supplier_name,
			"supplier_display_name": supplier.get("display_name") if supplier else None,
			"supplier_candidates": supplier_candidates, "transaction_date": transaction_date,
			"schedule_date": schedule_date,
			"default_purchase_mode": candidate.get("default_purchase_mode") or "wholesale",
			"warehouse": default_warehouse, "currency": currency,
			"supplier_ref": candidate.get("supplier_ref"), "remarks": candidate.get("remarks"),
			"items": items,
		}
		validation = {
			"ready_for_handoff": not errors, "errors": errors,
			"warnings": [warning for row in items for warning in row.get("warnings") or []],
		}
		draft = ai_repository.create_draft(
			user=user, conversation_id=conversation_id, source_run=run_id,
			draft_type="purchase_order", company=company, title=content,
			payload=payload, validation=validation,
		)
		assistant_content = _("已生成采购订单草稿；{0}" ).format(
			_("可以进入采购订单编辑器继续复核。") if validation["ready_for_handoff"] else _("仍有字段需要人工确认。")
		)
		citation = {"type": "ai_draft", "id": draft["name"], "label": draft["title"], "href": None, "data": draft}
		ai_repository.append_message(
			conversation_id=conversation_id, user=user, role="assistant", content=assistant_content,
			scenario=scenario, run_id=run_id, citations=[citation], prompt_version=prompt_version,
		)
		latency_ms = int((time.perf_counter() - started) * 1000)
		ai_repository.complete_run(
			run_id=run_id, user=user, result=result,
			latency_ms=latency_ms,
			tool_calls=[{"tool": "build_purchase_order_draft", "risk_level": "L2_DRAFT_ONLY", "draft_id": draft["name"]}],
		)
		frappe.db.commit()
		return {
			"status": "success", "message": assistant_content,
			"data": {"conversation": conversation_id, "run_id": run_id, "draft": draft,
				"message": {"role": "assistant", "content": assistant_content, "citations": [citation]},
				"model": result.get("model"), "model_alias": result.get("model_alias"),
				"run": {"status": "completed", "latency_ms": latency_ms, "first_token_ms": None},
				"trace_id": result.get("trace_id"), "usage": result.get("usage") or {}, "warnings": result.get("warnings") or []},
		}
	except Exception as error:
		frappe.db.rollback()
		ai_repository.fail_run(run_id=run_id, user=user, error=error, latency_ms=int((time.perf_counter() - started) * 1000))
		frappe.db.commit()
		raise


def generate_ai_inventory_adjustment_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
):
	scenario = "inventory_adjustment_draft"
	prompt_version = _resolve_prompt_version(scenario)
	user = _current_user()
	model_alias = resolve_ai_selected_model_alias(model_alias)
	content = _normalize_content(content)
	company = _resolve_company_scope(company, required=True)
	if not frappe.has_permission("Stock Entry", ptype="create"):
		raise frappe.PermissionError(_("无权创建库存调整草稿。"))
	if not conversation_id:
		conversation = ai_repository.create_conversation(user=user, title=content, company=company)
		conversation_id = conversation["name"]
	else:
		conversation = ai_repository.get_conversation(conversation_id=conversation_id, user=user)["conversation"]
		if conversation.get("company") and conversation.get("company") != company:
			frappe.throw(_("当前公司与会话公司范围不一致，请新建会话。"))
	ai_repository.append_message(
		conversation_id=conversation_id,
		user=user,
		role="user",
		content=content,
		scenario=scenario,
		prompt_version=prompt_version,
	)
	run_id = ai_repository.create_run(
		conversation_id=conversation_id,
		user=user,
		scenario=scenario,
	)
	frappe.db.commit()
	started = time.perf_counter()
	try:
		model_messages = ai_repository.load_model_messages(
			conversation_id=conversation_id,
			user=user,
			limit=MAX_AI_MESSAGES,
		)
		result = _call_ai_orchestrator_inventory_adjustment_draft(
			{
				"messages": model_messages,
				"scenario": scenario,
				"user": user,
				"company": company,
				"locale": getattr(frappe.local, "lang", None) or "zh-CN",
				"prompt_version": prompt_version,
				"conversation_id": conversation_id,
				"run_id": run_id,
				"model_alias": model_alias,
			}
		)
		payload, validation = _build_inventory_adjustment_draft(result["draft"], company=company)
		draft = ai_repository.create_draft(
			user=user,
			conversation_id=conversation_id,
			source_run=run_id,
			draft_type="inventory_adjustment",
			company=company,
			title=content,
			payload=payload,
			validation=validation,
		)
		assistant_content = _("已生成库存调整草稿；{0}").format(
			_("可以进入库存调整编辑器继续复核。")
			if validation["ready_for_handoff"]
			else _("仍有字段需要人工确认。")
		)
		citation = {
			"type": "ai_draft",
			"id": draft["name"],
			"label": draft["title"],
			"href": None,
			"data": draft,
		}
		ai_repository.append_message(
			conversation_id=conversation_id,
			user=user,
			role="assistant",
			content=assistant_content,
			scenario=scenario,
			run_id=run_id,
			citations=[citation],
			prompt_version=prompt_version,
		)
		latency_ms = int((time.perf_counter() - started) * 1000)
		ai_repository.complete_run(
			run_id=run_id,
			user=user,
			result=result,
			latency_ms=latency_ms,
			tool_calls=[
				{
					"tool": "build_inventory_adjustment_draft",
					"risk_level": "L2_DRAFT_ONLY",
					"draft_id": draft["name"],
				}
			],
		)
		frappe.db.commit()
		return {
			"status": "success",
			"message": assistant_content,
			"data": {
				"conversation": conversation_id,
				"run_id": run_id,
				"draft": draft,
				"message": {"role": "assistant", "content": assistant_content, "citations": [citation]},
				"model": result.get("model"),
				"model_alias": result.get("model_alias"),
				"run": {"status": "completed", "latency_ms": latency_ms, "first_token_ms": None},
				"trace_id": result.get("trace_id"),
				"usage": result.get("usage") or {},
				"warnings": result.get("warnings") or [],
			},
		}
	except Exception as error:
		frappe.db.rollback()
		ai_repository.fail_run(
			run_id=run_id,
			user=user,
			error=error,
			latency_ms=int((time.perf_counter() - started) * 1000),
		)
		frappe.db.commit()
		raise


def _resolve_product_setup_uom(query: str | None) -> tuple[str | None, list[dict]]:
	resolved = str(query or "").strip()
	rows = frappe.get_all(
		"UOM",
		fields=["name", "uom_name", "symbol"],
		limit_page_length=0,
	)
	alias_map: dict[str, set[str]] = {}
	for spec in STANDARD_UOMS:
		values = {
			str(spec.get("name") or ""),
			str(spec.get("uom_name") or ""),
			str(spec.get("display_name") or ""),
			str(spec.get("symbol") or ""),
			*(str(value) for value in spec.get("aliases") or ()),
		}
		alias_map.setdefault(str(spec.get("name") or ""), set()).update(values)

	def row_values(row) -> set[str]:
		name = str(row.get("name") or "")
		return {
			name,
			str(row.get("uom_name") or ""),
			str(row.get("symbol") or ""),
			*alias_map.get(name, set()),
		}

	candidates = [
		{"name": row.get("name"), "display_name": resolve_uom_display_name(
			row.get("name"), uom_name=row.get("uom_name"), symbol=row.get("symbol")
		)}
		for row in rows
		if not resolved or any(resolved.casefold() in value.casefold() for value in row_values(row) if value)
	][:8]
	if not resolved:
		default_name = "Nos" if any(row.get("name") == "Nos" for row in rows) else (rows[0].get("name") if rows else None)
		return default_name, candidates
	exact = next(
		(
			row for row in rows
			if resolved.casefold() in {value.casefold() for value in row_values(row) if value}
		),
		None,
	)
	if exact:
		return str(exact.get("name")), candidates
	return (str(candidates[0]["name"]) if len(candidates) == 1 else None), candidates


def _resolve_optional_master_name(doctype: str, query: str | None) -> str | None:
	resolved = str(query or "").strip()
	if not resolved:
		return None
	if frappe.db.exists(doctype, resolved):
		return resolved
	rows = frappe.get_all(
		doctype,
		filters={"name": ["like", f"%{resolved}%"]},
		pluck="name",
		limit_page_length=5,
	)
	return str(rows[0]) if len(rows) == 1 else None


def _build_product_setup_draft(candidate: dict, *, company: str) -> tuple[dict, dict]:
	item_name = str(candidate.get("item_name") or "").strip()[:140] or None
	item_code = str(candidate.get("item_code") or "").strip()[:140] or None
	item_group_query = str(candidate.get("item_group") or candidate.get("item_group_query") or "").strip() or None
	brand_query = str(candidate.get("brand") or candidate.get("brand_query") or "").strip() or None
	item_group = _resolve_optional_master_name("Item Group", item_group_query)
	brand = _resolve_optional_master_name("Brand", brand_query)
	requested_stock_uom = candidate.get("stock_uom") or candidate.get("opening_uom")
	stock_uom, uom_candidates = _resolve_product_setup_uom(requested_stock_uom)
	opening_uom, _opening_uom_candidates = _resolve_product_setup_uom(candidate.get("opening_uom") or stock_uom)
	warehouse_query = candidate.get("warehouse") or candidate.get("warehouse_query")
	warehouse = _resolve_sales_draft_warehouse(warehouse_query, company)
	opening_qty = None if candidate.get("opening_qty") in (None, "") else flt(candidate.get("opening_qty"))
	standard_selling_rate = (
		None if candidate.get("standard_selling_rate") in (None, "")
		else flt(candidate.get("standard_selling_rate"))
	)
	wholesale_rate = (
		None if candidate.get("wholesale_rate") in (None, "")
		else flt(candidate.get("wholesale_rate"))
	)
	retail_rate = (
		None if candidate.get("retail_rate") in (None, "")
		else flt(candidate.get("retail_rate"))
	)
	standard_buying_rate_value = candidate.get("standard_buying_rate")
	if standard_buying_rate_value in (None, ""):
		# 兼容已经生成的旧版商品草稿和当前 Orchestrator 字段；Web 新版本
		# 统一使用“成本价（默认采购价）”业务语义。
		standard_buying_rate_value = candidate.get("valuation_rate")
	standard_buying_rate = (
		None if standard_buying_rate_value in (None, "")
		else flt(standard_buying_rate_value)
	)
	company_currency = frappe.db.get_value("Company", company, "default_currency") or None
	currency_query = str(candidate.get("currency") or "").strip() or None
	currency = company_currency
	invalid_currency = False
	if currency_query:
		if frappe.db.exists("Currency", currency_query):
			currency = currency_query
		elif currency_query.upper() in {"RMB", "CNY"} or (
			currency_query in {"元", "人民币"} and company_currency == "CNY"
		):
			currency = "CNY"
		else:
			invalid_currency = True
	description = str(candidate.get("description") or "").strip()[:2000] or None
	errors = []
	warnings = []
	if not item_name:
		errors.append(_("请填写商品名称。"))
	elif frappe.db.exists("Item", {"item_name": item_name}):
		errors.append(_("商品名称 {0} 已存在，请确认是否应编辑现有商品。" ).format(item_name))
	if item_code and frappe.db.exists("Item", item_code):
		errors.append(_("商品编码 {0} 已存在。" ).format(item_code))
	if item_group_query and not item_group:
		errors.append(_("商品分类无法唯一匹配，请人工选择。"))
	elif not item_group:
		warnings.append(_("未指定商品分类，正式商品页面将使用后端默认分类。"))
	if brand_query and not brand:
		errors.append(_("品牌无法唯一匹配，请人工选择。"))
	if invalid_currency:
		errors.append(_("币种 {0} 无法识别，请人工选择标准币种代码。" ).format(currency_query))
	if not stock_uom:
		errors.append(_("库存单位无法唯一匹配，请人工选择。"))
	if opening_uom and stock_uom and opening_uom != stock_uom:
		errors.append(_("商品建档草稿首期只支持按库存基准单位初始化库存，请补充单位换算后再创建。"))
	if opening_qty is not None and opening_qty < 0:
		errors.append(_("初始库存数量不能为负数。"))
	if opening_qty and not warehouse:
		errors.append(_("填写初始库存时必须选择当前公司的叶子仓库。"))
	if opening_qty and standard_buying_rate is None:
		errors.append(_("填写初始库存时必须补充成本价（默认采购价）；系统会将其作为首次入库成本，售价不会用于库存计价。"))
	if opening_qty and not frappe.has_permission("Stock Entry", ptype="create"):
		errors.append(_("当前账号无权创建初始库存入库单。"))
	if any(rate is not None for rate in (standard_selling_rate, wholesale_rate, retail_rate)) and not frappe.has_permission(
		"Item Price", ptype="create"
	):
		errors.append(_("当前账号无权创建商品销售价格。"))
	if standard_selling_rate is not None and standard_selling_rate < 0:
		errors.append(_("标准售价不能为负数。"))
	if wholesale_rate is not None and wholesale_rate < 0:
		errors.append(_("批发价不能为负数。"))
	if retail_rate is not None and retail_rate < 0:
		errors.append(_("零售价不能为负数。"))
	if standard_buying_rate is not None and standard_buying_rate < 0:
		errors.append(_("成本价（默认采购价）不能为负数。"))
	payload = {
		"company": company,
		"item_name": item_name,
		"item_code": item_code,
		"item_group_query": item_group_query,
		"item_group": item_group,
		"brand_query": brand_query,
		"brand": brand,
		"stock_uom": stock_uom,
		"stock_uom_display": resolve_uom_display_name(stock_uom),
		"uom_candidates": uom_candidates,
		"warehouse_query": warehouse_query,
		"warehouse": warehouse,
		"opening_qty": opening_qty,
		"opening_uom": opening_uom or stock_uom,
		"opening_uom_display": resolve_uom_display_name(opening_uom or stock_uom),
		"standard_selling_rate": standard_selling_rate,
		"wholesale_rate": wholesale_rate,
		"retail_rate": retail_rate,
		"standard_buying_rate": standard_buying_rate,
		"currency": currency,
		"description": description,
	}
	return payload, {"ready_for_handoff": not errors, "errors": errors, "warnings": warnings}


def generate_ai_product_setup_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
):
	scenario = "product_setup_draft"
	prompt_version = _resolve_prompt_version(scenario)
	user = _current_user()
	model_alias = resolve_ai_selected_model_alias(model_alias)
	content = _normalize_content(content)
	company = _resolve_company_scope(company, required=True)
	if not frappe.has_permission("Item", ptype="create"):
		raise frappe.PermissionError(_("无权创建商品建档草稿。"))
	if not conversation_id:
		conversation = ai_repository.create_conversation(user=user, title=content, company=company)
		conversation_id = conversation["name"]
	else:
		conversation = ai_repository.get_conversation(conversation_id=conversation_id, user=user)["conversation"]
		if conversation.get("company") and conversation.get("company") != company:
			frappe.throw(_("当前公司与会话公司范围不一致，请新建会话。"))
	ai_repository.append_message(
		conversation_id=conversation_id, user=user, role="user", content=content,
		scenario=scenario, prompt_version=prompt_version,
	)
	run_id = ai_repository.create_run(conversation_id=conversation_id, user=user, scenario=scenario)
	frappe.db.commit()
	started = time.perf_counter()
	try:
		model_messages = ai_repository.load_model_messages(
			conversation_id=conversation_id, user=user, limit=MAX_AI_MESSAGES,
		)
		result = _call_ai_orchestrator_product_setup_draft({
			"messages": model_messages, "scenario": scenario, "user": user,
			"company": company, "locale": getattr(frappe.local, "lang", None) or "zh-CN",
			"prompt_version": prompt_version, "conversation_id": conversation_id, "run_id": run_id,
			"model_alias": model_alias,
		})
		payload, validation = _build_product_setup_draft(result["draft"], company=company)
		draft = ai_repository.create_draft(
			user=user, conversation_id=conversation_id, source_run=run_id,
			draft_type="product_setup", company=company, title=content,
			payload=payload, validation=validation,
		)
		assistant_content = _("已生成商品建档草稿；{0}").format(
			_("可以进入商品页面继续复核。") if validation["ready_for_handoff"]
			else _("仍有商品、价格或初始库存字段需要人工确认。")
		)
		citation = {"type": "ai_draft", "id": draft["name"], "label": draft["title"], "href": None, "data": draft}
		ai_repository.append_message(
			conversation_id=conversation_id, user=user, role="assistant", content=assistant_content,
			scenario=scenario, run_id=run_id, citations=[citation], prompt_version=prompt_version,
		)
		latency_ms = int((time.perf_counter() - started) * 1000)
		ai_repository.complete_run(
			run_id=run_id, user=user, result=result, latency_ms=latency_ms,
			tool_calls=[{"tool": "build_product_setup_draft", "risk_level": "L2_DRAFT_ONLY", "draft_id": draft["name"]}],
		)
		frappe.db.commit()
		return {
			"status": "success", "message": assistant_content,
			"data": {
				"conversation": conversation_id, "run_id": run_id, "draft": draft,
				"message": {"role": "assistant", "content": assistant_content, "citations": [citation]},
				"model": result.get("model"), "model_alias": result.get("model_alias"),
				"run": {"status": "completed", "latency_ms": latency_ms, "first_token_ms": None},
				"trace_id": result.get("trace_id"), "usage": result.get("usage") or {},
				"warnings": result.get("warnings") or [],
			},
		}
	except Exception as error:
		frappe.db.rollback()
		ai_repository.fail_run(
			run_id=run_id, user=user, error=error,
			latency_ms=int((time.perf_counter() - started) * 1000),
		)
		frappe.db.commit()
		raise


def get_ai_draft_v1(draft_id: str):
	return {"status": "success", "message": _("AI 草稿获取成功。"), "data": ai_repository.get_draft(draft_id=draft_id, user=_current_user())}


def list_ai_drafts_v1(
	status: str = "draft", draft_type: str | None = None,
	start: int = 0, limit: int = 20,
):
	return {
		"status": "success",
		"message": _("AI 草稿列表获取成功。"),
		"data": ai_repository.list_drafts(
			user=_current_user(), status=status, draft_type=draft_type,
			start=start, limit=limit,
		),
	}


def _update_ai_draft_once(
	draft_id: str, payload, *, expected_version: int, change_source: str = "user_edit",
):
	user = _current_user()
	draft = ai_repository.get_draft(draft_id=draft_id, user=user)
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	if not isinstance(payload, dict):
		frappe.throw(_("草稿 payload 格式不正确。"))
	if draft["draft_type"] == "inventory_adjustment":
		next_payload, validation = _build_inventory_adjustment_draft(payload, company=draft["company"])
		updated = ai_repository.update_draft(
			draft_id=draft_id,
			user=user,
			payload=next_payload,
			validation=validation,
			expected_version=expected_version,
			change_source=change_source,
		)
		return {
			"status": "success",
			"message": _("AI 库存调整草稿已更新并按实时库存重新校验。"),
			"data": updated,
		}
	if draft["draft_type"] == "product_setup":
		next_payload, validation = _build_product_setup_draft(payload, company=draft["company"])
		updated = ai_repository.update_draft(
			draft_id=draft_id,
			user=user,
			payload=next_payload,
			validation=validation,
			expected_version=expected_version,
			change_source=change_source,
		)
		return {
			"status": "success",
			"message": _("AI 商品建档草稿已更新并重新校验。"),
			"data": updated,
		}
	if draft["draft_type"] == "purchase_order":
		company = draft["company"]
		supplier_query = payload.get("supplier") or payload.get("supplier_query")
		supplier, supplier_candidates = _resolve_purchase_draft_supplier(supplier_query)
		default_warehouse = _resolve_sales_draft_warehouse(payload.get("warehouse"), company)
		items = [
			_resolve_purchase_draft_item(
				{"item_query": row.get("item_code") or row.get("item_query"), "qty": row.get("qty"),
				 "uom": row.get("uom"), "price": row.get("price"),
				 "warehouse_query": row.get("warehouse") or default_warehouse},
				company=company, default_warehouse=default_warehouse,
				allow_user_price=True,
			)
			for row in (payload.get("items") or []) if isinstance(row, dict)
		]
		errors = []
		if not supplier:
			errors.append(_("供应商无法唯一匹配，请人工选择。"))
		if not items:
			errors.append(_("草稿没有有效商品明细。"))
		for index, row in enumerate(items, 1):
			if not row.get("item_code") or row.get("qty", 0) <= 0 or not row.get("warehouse"):
				errors.append(_("第 {0} 行需要人工补充商品、数量或收货仓库。" ).format(index))
		supplier_name = supplier.get("name") if supplier else None
		currency = str(payload.get("currency") or "").strip() or None
		if supplier_name and not currency:
			currency = frappe.db.get_value("Supplier", supplier_name, "default_currency") or None
		if not currency:
			currency = frappe.db.get_value("Company", company, "default_currency") or None
		next_payload = {
			"company": company, "supplier_query": supplier_query, "supplier": supplier_name,
			"supplier_display_name": supplier.get("display_name") if supplier else None,
			"supplier_candidates": supplier_candidates,
			"transaction_date": str(getdate(payload.get("transaction_date") or nowdate())),
			"schedule_date": str(getdate(payload.get("schedule_date") or payload.get("transaction_date") or nowdate())),
			"default_purchase_mode": "retail" if payload.get("default_purchase_mode") == "retail" else "wholesale",
			"warehouse": default_warehouse, "currency": currency,
			"supplier_ref": str(payload.get("supplier_ref") or "")[:140] or None,
			"remarks": str(payload.get("remarks") or "")[:1000] or None, "items": items,
		}
		validation = {"ready_for_handoff": not errors, "errors": errors,
			"warnings": [warning for row in items for warning in row.get("warnings") or []]}
		updated = ai_repository.update_draft(
			draft_id=draft_id, user=user, payload=next_payload, validation=validation,
			expected_version=expected_version, change_source=change_source,
		)
		return {"status": "success", "message": _("AI 采购草稿已更新并重新校验。"), "data": updated}
	if draft["draft_type"] != "sales_order":
		frappe.throw(_("不支持的 AI 草稿类型。"))
	company = draft["company"]
	customer_query = payload.get("customer") or payload.get("customer_query")
	customer, customer_candidates = _resolve_sales_draft_customer(customer_query)
	default_warehouse = _resolve_sales_draft_warehouse(payload.get("warehouse"), company)
	items = [
		_resolve_sales_draft_item(
			{
				"item_query": row.get("item_code") or row.get("item_query"),
				"qty": row.get("qty"), "uom": row.get("uom"), "price": row.get("price"),
				"warehouse_query": row.get("warehouse") or default_warehouse,
			},
			company=company, default_warehouse=default_warehouse,
			allow_user_price=True,
		)
		for row in (payload.get("items") or []) if isinstance(row, dict)
	]
	errors = []
	if not customer:
		errors.append(_("客户无法唯一匹配，请人工选择。"))
	if not items:
		errors.append(_("草稿没有有效商品明细。"))
	for index, row in enumerate(items, 1):
		if not row.get("item_code") or row.get("qty", 0) <= 0 or not row.get("warehouse"):
			errors.append(_("第 {0} 行需要人工补充商品、数量或仓库。" ).format(index))
	transaction_date = str(getdate(payload.get("transaction_date") or nowdate()))
	delivery_date = str(getdate(payload.get("delivery_date") or transaction_date))
	next_payload = {
		"company": company, "customer_query": customer_query,
		"customer": customer.get("name") if customer else None,
		"customer_display_name": customer.get("display_name") if customer else None,
		"customer_candidates": customer_candidates, "transaction_date": transaction_date,
		"delivery_date": delivery_date,
		"default_sales_mode": "retail" if payload.get("default_sales_mode") == "retail" else "wholesale",
		"warehouse": default_warehouse, "remarks": str(payload.get("remarks") or "")[:1000] or None,
		"items": items,
	}
	validation = {
		"ready_for_handoff": not errors, "errors": errors,
		"warnings": [warning for row in items for warning in row.get("warnings") or []],
	}
	updated = ai_repository.update_draft(
		draft_id=draft_id, user=user, payload=next_payload, validation=validation,
		expected_version=expected_version, change_source=change_source,
	)
	return {"status": "success", "message": _("AI 草稿已更新并重新校验。"), "data": updated}


def update_ai_draft_v1(
	draft_id: str, payload, expected_version: int,
	request_id: str | None = None, _change_source: str = "user_edit",
):
	expected_version = cint(expected_version)
	if expected_version < 1:
		frappe.throw(_("草稿版本号不正确。"))
	resolved_request_id = get_current_request_id(request_id)
	namespace = (
		"restore_ai_draft_version_v1"
		if str(_change_source or "").startswith("restore_v")
		else "update_ai_draft_v1"
	)
	return run_idempotent(
		namespace,
		resolved_request_id,
		lambda: _update_ai_draft_once(
			draft_id=draft_id,
			payload=payload,
			expected_version=expected_version,
			change_source=_change_source,
		),
		request_payload={
			"draft_id": draft_id,
			"expected_version": expected_version,
			"payload": payload,
			"change_source": _change_source,
		},
	)


def discard_ai_draft_v1(draft_id: str):
	user = _current_user()
	draft = ai_repository.discard_draft(draft_id=draft_id, user=user)
	frappe.db.commit()
	return {"status": "success", "message": _("AI 草稿已放弃。"), "data": draft}


def _build_draft_version_diff(previous: dict | None, current: dict) -> dict:
	if not previous:
		return {"fields": [], "items": []}
	previous_payload = previous.get("payload") or {}
	current_payload = current.get("payload") or {}
	fields = []
	for field in (
		"customer",
		"supplier",
		"transaction_date",
		"delivery_date",
		"schedule_date",
		"posting_date",
		"default_sales_mode",
		"default_purchase_mode",
		"adjustment_type",
		"warehouse",
		"reason",
		"remarks",
		"item_name",
		"item_code",
		"item_group",
		"brand",
		"stock_uom",
		"opening_qty",
		"opening_uom",
		"standard_selling_rate",
		"valuation_rate",
		"currency",
		"description",
	):
		before = previous_payload.get(field)
		after = current_payload.get(field)
		if before != after:
			fields.append({"field": field, "before": before, "after": after})

	def item_map(payload):
		return {
			str(row.get("item_code") or row.get("item_query") or index): row
			for index, row in enumerate(payload.get("items") or [], 1)
		}

	before_items = item_map(previous_payload)
	after_items = item_map(current_payload)
	item_changes = []
	for key in sorted(set(before_items) | set(after_items)):
		before = before_items.get(key)
		after = after_items.get(key)
		if before is None:
			item_changes.append({"key": key, "change": "added", "before": None, "after": after})
		elif after is None:
			item_changes.append({"key": key, "change": "removed", "before": before, "after": None})
		else:
			changed_fields = [
				field for field in (
					"qty",
					"uom",
					"price",
					"warehouse",
					"current_stock_qty",
					"target_stock_qty",
					"qty_delta",
					"valuation_rate",
				)
				if before.get(field) != after.get(field)
			]
			if changed_fields:
				item_changes.append(
					{"key": key, "change": "modified", "fields": changed_fields, "before": before, "after": after}
				)
	return {"fields": fields, "items": item_changes}


def list_ai_draft_versions_v1(draft_id: str):
	user = _current_user()
	versions = ai_repository.list_draft_versions(draft_id=draft_id, user=user)
	items = []
	previous = None
	for version in versions:
		items.append({**version, "diff": _build_draft_version_diff(previous, version)})
		previous = version
	return {
		"status": "success", "message": _("AI 草稿版本获取成功。"),
		"data": {"draft_id": draft_id, "items": list(reversed(items))},
	}


def restore_ai_draft_version_v1(
	draft_id: str, version: int, expected_version: int,
	request_id: str | None = None,
):
	user = _current_user()
	snapshot = ai_repository.get_draft_version(draft_id=draft_id, user=user, version_no=version)
	result = update_ai_draft_v1(
		draft_id=draft_id,
		payload=snapshot["payload"],
		expected_version=expected_version,
		request_id=request_id,
		_change_source=f"restore_v{cint(version)}",
	)
	result["message"] = _("AI 草稿历史版本已重新校验并恢复为新版本。")
	return result


def prepare_ai_draft_handoff_v1(draft_id: str):
	user = _current_user()
	draft = ai_repository.get_draft(draft_id=draft_id, user=user)
	if draft["draft_type"] not in {"sales_order", "purchase_order", "inventory_adjustment", "product_setup"}:
		frappe.throw(_("当前草稿类型不支持交接。"))
	if draft["status"] != "draft":
		frappe.throw(_("只有 draft 状态的草稿可以交接。"))
	if not draft["validation"].get("ready_for_handoff"):
		frappe.throw(_("草稿仍有未解决的校验问题，不能交接。"))
	payload = draft["payload"]
	ai_repository.mark_draft_handed_off(draft_id=draft_id, user=user)
	frappe.db.commit()
	if draft["draft_type"] == "product_setup":
		standard_buying_rate = payload.get("standard_buying_rate")
		if standard_buying_rate in (None, ""):
			standard_buying_rate = payload.get("valuation_rate")
		handoff_payload = {
			"company": payload.get("company"),
			"item_name": payload.get("item_name"),
			"item_code": payload.get("item_code"),
			"item_group": payload.get("item_group"),
			"brand": payload.get("brand"),
			"stock_uom": payload.get("stock_uom"),
			"warehouse": payload.get("warehouse"),
			"warehouse_stock_qty": payload.get("opening_qty"),
			"warehouse_stock_uom": payload.get("opening_uom"),
			"standard_selling_rate": payload.get("standard_selling_rate"),
			"wholesale_rate": payload.get("wholesale_rate"),
			"retail_rate": payload.get("retail_rate"),
			"standard_buying_rate": standard_buying_rate,
			"valuation_rate": standard_buying_rate,
			"currency": payload.get("currency"),
			"description": payload.get("description"),
		}
	elif draft["draft_type"] == "inventory_adjustment":
		row = (payload.get("items") or [{}])[0]
		handoff_payload = {
			"company": payload.get("company"),
			"posting_date": payload.get("posting_date"),
			"adjustment_type": payload.get("adjustment_type"),
			"warehouse": payload.get("warehouse"),
			"reason": payload.get("reason"),
			"remarks": payload.get("remarks"),
			"item_code": row.get("item_code"),
			"item_name": row.get("item_name"),
			"target_qty": row.get("target_stock_qty"),
			"uom": row.get("stock_uom"),
			"uom_display": row.get("stock_uom_display"),
			"current_stock_qty": row.get("current_stock_qty"),
			"qty_delta": row.get("qty_delta"),
			"valuation_rate": row.get("valuation_rate"),
		}
	elif draft["draft_type"] == "purchase_order":
		handoff_payload = {
			"company": payload.get("company"), "supplier": payload.get("supplier"),
			"transaction_date": payload.get("transaction_date"), "schedule_date": payload.get("schedule_date"),
			"default_purchase_mode": payload.get("default_purchase_mode"), "warehouse": payload.get("warehouse"),
			"currency": payload.get("currency"), "supplier_ref": payload.get("supplier_ref"),
			"remarks": payload.get("remarks"),
			"items": [{key: row.get(key) for key in ("item_code", "item_name", "qty", "uom", "uom_display", "stock_uom", "stock_uom_display", "price", "warehouse", "conversion_factor")} for row in payload.get("items") or []],
		}
	else:
		handoff_payload = {
			"company": payload.get("company"), "customer": payload.get("customer"),
			"transaction_date": payload.get("transaction_date"), "delivery_date": payload.get("delivery_date"),
			"default_sales_mode": payload.get("default_sales_mode"), "warehouse": payload.get("warehouse"),
			"remarks": payload.get("remarks"),
			"items": [{key: row.get(key) for key in ("item_code", "item_name", "qty", "uom", "uom_display", "stock_uom", "stock_uom_display", "price", "warehouse", "conversion_factor")} for row in payload.get("items") or []],
		}
	return {
		"status": "success", "message": _("AI 草稿已准备交接。"),
		"data": {
			"draft_id": draft_id, "draft_type": draft["draft_type"], "payload": handoff_payload,
		},
	}


def _record_ai_draft_execution_audit(
	*, user: str, draft: dict, action: str, request_id: str | None,
	result: dict, priority: str = "high",
):
	if not frappe.db.table_exists("MyApp AI Audit Event"):
		return
	metadata = {
		"draft_type": draft.get("draft_type"),
		"draft_version": draft.get("version"),
		"request_id_hash": hashlib.sha256((request_id or "").encode()).hexdigest() if request_id else None,
		"status": result.get("status"),
		"target_doctype": result.get("target_doctype"),
		"target_name": result.get("target_name"),
	}
	parameter_hash = hashlib.sha256(
		frappe.as_json({"draft": draft.get("name"), "version": draft.get("version")}).encode()
	).hexdigest()
	result_hash = hashlib.sha256(frappe.as_json(metadata).encode()).hexdigest()
	now = now_datetime()
	frappe.db.sql(
		"""
		INSERT INTO `tabMyApp AI Audit Event`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 actor, action, object_type, object_name, reason, parameter_hash,
			 result_hash, metadata_json, priority)
		VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, 'ai_draft', %s, %s, %s, %s, %s, %s)
		""",
		(
			f"AI-AUDIT-{frappe.generate_hash(length=32)}", now, now, user, user,
			user, action, draft.get("name"), _("用户在 AI 工作台确认执行草稿。"),
			parameter_hash, result_hash, frappe.as_json(metadata), priority,
		),
	)


def _execute_ai_draft_payload(draft: dict, *, request_id: str | None) -> dict:
	payload = draft["payload"]
	draft_type = draft["draft_type"]
	if draft_type == "product_setup":
		standard_buying_rate = payload.get("standard_buying_rate")
		if standard_buying_rate in (None, ""):
			standard_buying_rate = payload.get("valuation_rate")
		buying_prices = []
		if standard_buying_rate not in (None, ""):
			buying_prices.append({
				"price_list": "Standard Buying",
				"rate": standard_buying_rate,
				"currency": payload.get("currency"),
			})
		selling_prices = []
		for price_list, rate in (
			("Wholesale", payload.get("wholesale_rate")),
			("Retail", payload.get("retail_rate")),
		):
			if rate not in (None, ""):
				selling_prices.append({
					"price_list": price_list,
					"rate": rate,
					"currency": payload.get("currency"),
				})
		result = create_product_v2(
			item_name=payload.get("item_name"), item_code=payload.get("item_code"),
			item_group=payload.get("item_group"), brand=payload.get("brand"),
			stock_uom=payload.get("stock_uom"), standard_rate=payload.get("standard_selling_rate"),
			valuation_rate=standard_buying_rate, currency=payload.get("currency"),
			selling_prices=selling_prices, buying_prices=buying_prices,
			description=payload.get("description"), company=payload.get("company"),
			warehouse=payload.get("warehouse"), warehouse_stock_qty=payload.get("opening_qty"),
			warehouse_stock_uom=payload.get("opening_uom"), request_id=request_id,
		)
		target_name = str((result.get("data") or {}).get("item_code") or "")
		return {"target_doctype": "Item", "target_name": target_name, "result": result}
	if draft_type == "inventory_adjustment":
		row = (payload.get("items") or [{}])[0]
		result = reconcile_inventory_stock_v1(
			item_code=row.get("item_code"), warehouse=payload.get("warehouse"),
			target_qty=row.get("target_stock_qty"), uom=row.get("stock_uom"),
			valuation_rate=row.get("valuation_rate"), posting_date=payload.get("posting_date"),
			remarks=payload.get("reason") or payload.get("remarks"), request_id=request_id,
		)
		stock_entry = (result.get("data") or {}).get("stock_entry")
		target_name = str(stock_entry or row.get("item_code") or "")
		return {
			"target_doctype": "Stock Entry" if stock_entry else "Item",
			"target_name": target_name, "result": result,
		}
	items = [
		{
			"item_code": row.get("item_code"), "qty": row.get("qty"), "uom": row.get("uom"),
			"price": row.get("price"), "warehouse": row.get("warehouse") or payload.get("warehouse"),
		}
		for row in payload.get("items") or []
	]
	if draft_type == "purchase_order":
		result = create_purchase_order(
			supplier=payload.get("supplier"), items=items, company=payload.get("company"),
			transaction_date=payload.get("transaction_date"), schedule_date=payload.get("schedule_date"),
			default_warehouse=payload.get("warehouse"), currency=payload.get("currency"),
			supplier_ref=payload.get("supplier_ref"), remarks=payload.get("remarks"), request_id=request_id,
		)
		target_name = str(result.get("purchase_order") or "")
		return {"target_doctype": "Purchase Order", "target_name": target_name, "result": result}
	if draft_type == "sales_order":
		result = create_order_v2(
			customer=payload.get("customer"), items=items, immediate=False, company=payload.get("company"),
			transaction_date=payload.get("transaction_date"), delivery_date=payload.get("delivery_date"),
			default_warehouse=payload.get("warehouse"), default_sales_mode=payload.get("default_sales_mode"),
			remarks=payload.get("remarks"), request_id=request_id,
		)
		target_name = str(result.get("order") or "")
		return {"target_doctype": "Sales Order", "target_name": target_name, "result": result}
	frappe.throw(_("当前草稿类型不支持在 AI 工作台执行。"))


def execute_ai_draft_v1(
	draft_id: str, expected_version: int, confirmed: bool | int = False,
	request_id: str | None = None,
):
	user = _current_user()
	resolved_request_id = get_current_request_id(request_id)
	if not cint(confirmed):
		frappe.throw(_("执行 AI 草稿前必须由当前用户明确确认。"))
	expected_version = cint(expected_version)
	if expected_version < 1:
		frappe.throw(_("草稿版本号不正确。"))

	def _execute():
		lock_name = f"myapp_ai_draft_execute_{hashlib.sha256(draft_id.encode()).hexdigest()}"
		with filelock(lock_name, timeout=60):
			draft = ai_repository.get_draft(draft_id=draft_id, user=user)
			if draft["status"] == "executed" and draft.get("execution"):
				return {
					"status": "success", "message": _("AI 草稿已执行，返回已有业务回执。"),
					"data": {"draft": draft, "execution": draft["execution"], "replayed": True},
				}
			if draft["status"] != "draft":
				frappe.throw(_("只有 draft 状态的 AI 草稿可以执行。"))
			if cint(draft["version"]) != expected_version:
				raise AiDraftVersionConflictError(_("草稿版本已变化，请刷新并重新确认后再执行。"))
			if not draft["validation"].get("ready_for_handoff"):
				frappe.throw(_("草稿仍有未解决的校验问题，不能执行。"))
			try:
				execution_result = _execute_ai_draft_payload(draft, request_id=resolved_request_id)
				if not execution_result.get("target_name"):
					frappe.throw(_("正式业务操作未返回目标业务对象。"))
				updated = ai_repository.mark_draft_executed(
					draft_id=draft_id, user=user, request_id=resolved_request_id,
					target_doctype=execution_result["target_doctype"],
					target_name=execution_result["target_name"], result=execution_result["result"],
				)
				_record_ai_draft_execution_audit(
					user=user, draft=draft, action="execute_ai_draft_succeeded",
					request_id=resolved_request_id,
					result={"status": "succeeded", **execution_result},
				)
				return {
					"status": "success", "message": _("AI 草稿已由当前用户确认并执行。"),
					"data": {"draft": updated, "execution": updated["execution"], "replayed": False},
				}
			except Exception as error:
				frappe.db.rollback()
				_record_ai_draft_execution_audit(
					user=user, draft=draft, action="execute_ai_draft_failed",
					request_id=resolved_request_id,
					result={"status": "failed", "error_type": type(error).__name__},
					priority="high",
				)
				frappe.db.commit()
				raise

	return run_idempotent(
		"execute_ai_draft_v1", resolved_request_id, _execute,
		request_payload={
			"draft_id": draft_id, "expected_version": expected_version, "confirmed": True,
		},
	)


def _prepare_chat_run(
	messages=None,
	scenario: str | None = None,
	company: str | None = None,
	conversation_id: str | None = None,
	content: str | None = None,
	model_alias: str | None = None,
):
	user = _current_user()
	model_alias = resolve_ai_selected_model_alias(model_alias)
	requested_scenario = _resolve_scenario(scenario)
	legacy_messages = _normalize_messages(messages) if messages not in (None, "", []) else []
	current_content = _normalize_content(content) if content not in (None, "") else None
	if not current_content:
		if legacy_messages and legacy_messages[-1]["role"] != "user":
			frappe.throw(_("messages 最后一条必须是 user 消息。"))
		user_messages = [row["content"] for row in legacy_messages if row["role"] == "user"]
		if not user_messages:
			frappe.throw(_("请提供用户消息。"))
		current_content = user_messages[-1]
	resolved_scenario = (
		_infer_ai_scenario(current_content) if requested_scenario == "auto" else requested_scenario
	)
	prompt_version = _resolve_prompt_version(resolved_scenario)

	is_new_conversation = not conversation_id
	conversation = None
	if conversation_id:
		conversation = ai_repository.get_conversation(conversation_id=conversation_id, user=user)["conversation"]
	conversation_company = str((conversation or {}).get("company") or "").strip() or None
	requested_company = str(company or "").strip() or None
	resolved_company = _resolve_company_scope(
		requested_company or conversation_company,
		required=resolved_scenario in {"product_search", "order_query", "report_summary"},
	)
	if conversation_id:
		if resolved_company and conversation.get("company") and resolved_company != conversation.get("company"):
			frappe.throw(_("当前公司与会话公司范围不一致，请新建会话。"))
	else:
		conversation = ai_repository.create_conversation(
			user=user,
			title=current_content,
			company=resolved_company,
		)
		conversation_id = conversation["name"]

	initial_messages = legacy_messages if legacy_messages and content in (None, "") and is_new_conversation else []
	if initial_messages:
		for row in initial_messages:
			ai_repository.append_message(
				conversation_id=conversation_id,
				user=user,
				role=row["role"],
				content=row["content"],
				scenario=resolved_scenario,
				prompt_version=prompt_version,
			)
	else:
		ai_repository.append_message(
			conversation_id=conversation_id,
			user=user,
			role="user",
			content=current_content,
			scenario=resolved_scenario,
			prompt_version=prompt_version,
		)
	run_id = ai_repository.create_run(
		conversation_id=conversation_id,
		user=user,
		scenario=resolved_scenario,
	)
	# AI audit records intentionally form their own durable boundary before the external model call.
	frappe.db.commit()

	started = time.perf_counter()
	tool_context = None
	citations = []
	tool_calls = []
	try:
		if resolved_scenario == "product_search":
			tool_context, citations, tool_calls = _build_product_search_context(
				query=current_content,
				company=resolved_company,
			)
		elif resolved_scenario == "order_query":
			tool_context, citations, tool_calls = _build_order_query_context(
				query=current_content,
				company=resolved_company,
			)
		elif resolved_scenario == "report_summary":
			tool_context, citations, tool_calls = _build_report_query_context(
				query=current_content,
				company=resolved_company,
			)
		model_messages = ai_repository.load_model_messages(
			conversation_id=conversation_id,
			user=user,
			limit=MAX_AI_MESSAGES,
		)
	except Exception as error:
		latency_ms = int((time.perf_counter() - started) * 1000)
		frappe.db.rollback()
		ai_repository.fail_run(run_id=run_id, user=user, error=error, latency_ms=latency_ms)
		frappe.db.commit()
		raise
	return {
		"user": user,
		"scenario": resolved_scenario,
		"company": resolved_company,
		"conversation_id": conversation_id,
		"run_id": run_id,
		"started": started,
		"prompt_version": prompt_version,
		"citations": citations,
		"tool_calls": tool_calls,
		"payload": {
			"messages": model_messages,
			"scenario": resolved_scenario,
			"user": user,
			"company": resolved_company,
			"locale": getattr(frappe.local, "lang", None) or "zh-CN",
			"context": tool_context,
			"prompt_version": prompt_version,
			"conversation_id": conversation_id,
			"run_id": run_id,
			"policy_context": {
				"roles": sorted(set(frappe.get_roles(user) or [])),
				"environment": os.environ.get("MYAPP_AI_ENVIRONMENT", "development").strip() or "development",
			},
			"model_alias": model_alias,
		},
	}


def _complete_chat_run(
	prepared: dict, result: dict, assistant_content: str, *, first_token_ms: int | None = None,
):
	latency_ms = int((time.perf_counter() - prepared["started"]) * 1000)
	ai_repository.append_message(
		conversation_id=prepared["conversation_id"],
		user=prepared["user"],
		role="assistant",
		content=assistant_content,
		scenario=prepared["scenario"],
		run_id=prepared["run_id"],
		citations=prepared["citations"],
		prompt_version=prepared["prompt_version"],
	)
	ai_repository.complete_run(
		run_id=prepared["run_id"],
		user=prepared["user"],
		result=result,
		latency_ms=latency_ms,
		first_token_ms=first_token_ms,
		tool_calls=prepared["tool_calls"],
	)
	frappe.db.commit()
	return {
		"status": "completed",
		"latency_ms": latency_ms,
		"first_token_ms": first_token_ms,
	}


def _fail_chat_run(prepared: dict, error: Exception):
	latency_ms = int((time.perf_counter() - prepared["started"]) * 1000)
	frappe.db.rollback()
	ai_repository.fail_run(
		run_id=prepared["run_id"],
		user=prepared["user"],
		error=error,
		latency_ms=latency_ms,
	)
	frappe.db.commit()


def chat_ai_v1(
	messages=None,
	scenario: str | None = None,
	company: str | None = None,
	conversation_id: str | None = None,
	content: str | None = None,
	model_alias: str | None = None,
):
	prepared = _prepare_chat_run(
		messages=messages,
		scenario=scenario,
		company=company,
		conversation_id=conversation_id,
		content=content,
		model_alias=model_alias,
	)
	try:
		result = _call_ai_orchestrator(prepared["payload"])
		message = result.get("message") or {}
		assistant_content = str(message.get("content") or "").strip()
		run_summary = _complete_chat_run(prepared, result, assistant_content)
	except Exception as error:
		_fail_chat_run(prepared, error)
		raise

	warnings = result.get("warnings") or []
	return {
		"status": "success",
		"message": _("AI 回复生成成功。"),
		"data": {
			"conversation": prepared["conversation_id"],
			"run_id": prepared["run_id"],
			"message": {
				"role": "assistant",
				"content": assistant_content,
				"citations": prepared["citations"],
			},
			"model": result.get("model"),
			"model_alias": result.get("model_alias"),
			"policy_code": result.get("policy_code"),
			"policy_version": result.get("policy_version"),
			"fallback_reason": result.get("fallback_reason"),
			"trace_id": result.get("trace_id"),
			"run": run_summary,
			"usage": result.get("usage") or {},
			"warnings": warnings,
			"events": _build_events(
				content=assistant_content,
				citations=prepared["citations"],
				warnings=warnings,
				tool_calls=prepared["tool_calls"],
			),
		},
	}


def _encode_sse(event: dict) -> str:
	return f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"


def stream_ai_message_v1(
	content: str,
	scenario: str | None = None,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
):
	prepared = _prepare_chat_run(
		scenario=scenario,
		company=company,
		conversation_id=conversation_id,
		content=content,
		model_alias=model_alias,
	)

	def event_stream():
		content_parts = []
		completed_result = None
		first_token_ms = None
		delta_count = 0
		streamed_chars = 0
		try:
			yield _encode_sse(
				{
					"type": "run_started",
					"conversation": prepared["conversation_id"],
					"run_id": prepared["run_id"],
				}
			)
			yield _encode_sse(
				{
					"type": "run_progress",
					"phase": "context_ready",
					"message": _("已确认当前账号权限与公司范围"),
				}
			)
			for tool_call in prepared["tool_calls"]:
				yield _encode_sse({"type": "tool_started", "tool": tool_call.get("tool")})
				yield _encode_sse(
					{
						"type": "tool_completed",
						"tool": tool_call.get("tool"),
						"result_count": tool_call.get("result_count", 0),
					}
				)
			for citation in prepared["citations"]:
				yield _encode_sse({"type": "citation", "citation": citation})

			yield _encode_sse(
				{
					"type": "run_progress",
					"phase": "generating",
					"message": _("正在请求模型，等待首个 Token"),
				}
			)
			for event in _stream_ai_orchestrator(prepared["payload"]):
				event_type = event.get("type")
				if event_type == "started":
					yield _encode_sse(
						{
							"type": "run_progress",
							"phase": "model_started",
							"message": _("模型已接收请求，等待首个 Token"),
							"model_alias": event.get("model_alias"),
						}
					)
				elif event_type == "message_delta":
					delta = str(event.get("delta") or "")
					if delta and first_token_ms is None:
						first_token_ms = max(0, int((time.perf_counter() - prepared["started"]) * 1000))
						yield _encode_sse(
							{
								"type": "run_progress",
								"phase": "streaming",
								"message": _("首个 Token 已到达，正在实时输出"),
							}
						)
					if delta:
						delta_count += 1
						streamed_chars += len(delta)
					content_parts.append(delta)
					yield _encode_sse(event)
				elif event_type == "warning":
					yield _encode_sse(event)
				elif event_type == "error":
					raise UpstreamServiceUnavailableError(str(event.get("message") or _("AI 服务暂时不可用。")))
				elif event_type == "completed":
					completed_result = event

			assistant_content = "".join(content_parts).strip()
			if not assistant_content and completed_result:
				assistant_content = str((completed_result.get("message") or {}).get("content") or "").strip()
			if not assistant_content or not completed_result:
				raise UpstreamServiceUnavailableError(_("AI 流式服务返回了无效响应。"))
			run_summary = _complete_chat_run(
				prepared, completed_result, assistant_content, first_token_ms=first_token_ms,
			)
			yield _encode_sse(
				{
					**completed_result,
					"type": "completed",
					"conversation": prepared["conversation_id"],
					"run_id": prepared["run_id"],
					"run": run_summary,
					"stream": {
						"delta_count": delta_count,
						"streamed_chars": streamed_chars,
					},
					"citations": prepared["citations"],
				}
			)
		except GeneratorExit as error:
			_fail_chat_run(prepared, RuntimeError("AI stream client disconnected"))
			raise error
		except Exception as error:
			_fail_chat_run(prepared, error)
			yield _encode_sse(
				{
					"type": "error",
					"code": "AI_STREAM_FAILED",
					"message": str(error) or _("AI 流式服务暂时不可用。"),
					"conversation": prepared["conversation_id"],
					"run_id": prepared["run_id"],
				}
			)

	return Response(
		event_stream(),
		content_type="text/event-stream; charset=utf-8",
		headers={
			"Cache-Control": "no-cache, no-transform",
			"Connection": "keep-alive",
			"X-Accel-Buffering": "no",
		},
	)
