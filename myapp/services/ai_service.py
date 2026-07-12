from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request

import frappe
from frappe import _
from werkzeug.wrappers import Response

from myapp.services import ai_repository
from myapp.services.order_service import search_sales_orders_v2
from myapp.services.purchase_service import search_purchase_orders_v2
from myapp.services.wholesale_service import search_product_v2
from myapp.utils.api_response import UpstreamServiceUnavailableError


MAX_AI_MESSAGES = 20
MAX_AI_MESSAGE_CHARS = 8000
MAX_AI_PRODUCT_RESULTS = 8
ALLOWED_AI_ROLES = {"user", "assistant"}
ALLOWED_AI_SCENARIOS = {"general", "product_search", "order_query", "report_summary"}
PROMPT_VERSION = "erp-readonly-v2"
PRODUCT_SEARCH_PREFIX_PATTERN = re.compile(
	r"^(?:请|麻烦|可以|能否|帮我|给我|我想|我要)*(?:查找|搜索|找一下|找一找|找找|找)?"
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
	resolved = (scenario or "general").strip().lower()
	if resolved not in ALLOWED_AI_SCENARIOS:
		frappe.throw(_("不支持的 AI 场景。"))
	return resolved


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


def _build_product_search_context(*, query: str, company: str | None) -> tuple[dict, list[dict], list[dict]]:
	if not frappe.has_permission("Item", ptype="read"):
		raise frappe.PermissionError(_("无权读取商品资料。"))
	resolved_company = _resolve_company_scope(company, required=True)
	search_terms = _extract_product_search_terms(query)
	result_rows = []
	seen_codes = set()
	for search_term in search_terms:
		search_result = search_product_v2(
			search_key=search_term,
			company=resolved_company,
			limit=MAX_AI_PRODUCT_RESULTS,
			disabled=0,
			search_fields=["barcode", "item_code", "item_name", "nickname", "specification"],
			item_context="sales",
		)
		for row in (search_result or {}).get("data") or []:
			item_code = row.get("item_code")
			if item_code and item_code not in seen_codes:
				seen_codes.add(item_code)
				result_rows.append(row)
				if len(result_rows) >= MAX_AI_PRODUCT_RESULTS:
					break
		if len(result_rows) >= MAX_AI_PRODUCT_RESULTS:
			break
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
		}
	]
	context = {
		"tool": "search_products",
		"query": query,
		"search_terms": search_terms,
		"company": resolved_company,
		"products": products,
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


def _build_order_query_dsl(query: str, *, company: str) -> dict:
	text = " ".join((query or "").strip().split())
	mentions_sales = any(word in text for word in ("销售", "客户", "收款", "发货"))
	mentions_purchase = any(word in text for word in ("采购", "供应商", "付款", "收货"))
	if mentions_sales and mentions_purchase:
		frappe.throw(_("订单查询同时包含销售和采购语义，请拆成两个问题。"))
	entity = "purchase_order" if mentions_purchase else "sales_order"

	today = date.today()
	date_to = today
	date_from = today - timedelta(days=29)
	date_range = "last_30_days"
	if "今天" in text or "今日" in text:
		date_from = date_to = today
		date_range = "today"
	elif "本周" in text or "这周" in text:
		date_from = today - timedelta(days=today.weekday())
		date_range = "this_week"
	elif "上月" in text or "上个月" in text:
		last_month_end = today.replace(day=1) - timedelta(days=1)
		date_from = last_month_end.replace(day=1)
		date_to = last_month_end
		date_range = "last_month"
	elif "本月" in text or "这个月" in text:
		date_from = today.replace(day=1)
		date_range = "this_month"
	elif match := re.search(r"近\s*(\d{1,3})\s*天", text):
		days = max(1, min(366, int(match.group(1))))
		date_from = today - timedelta(days=days - 1)
		date_range = f"last_{days}_days"

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
	if match := re.search(r"(?:前\s*)?(\d{1,2})\s*(?:条|个|笔)", text):
		limit = max(1, min(20, int(match.group(1))))

	return {
		"entity": entity,
		"company": company,
		"date_range": date_range,
		"date_from": str(date_from),
		"date_to": str(date_to),
		"status_filter": status_filter,
		"exclude_cancelled": status_filter != "cancelled",
		"sort_by": sort_by,
		"min_amount": min_amount,
		"limit": limit,
	}


def _build_order_query_context(*, query: str, company: str | None) -> tuple[dict, list[dict], list[dict]]:
	resolved_company = _resolve_company_scope(company, required=True)
	dsl = _build_order_query_dsl(query, company=resolved_company)
	is_sales = dsl["entity"] == "sales_order"
	doctype = "Sales Order" if is_sales else "Purchase Order"
	if not frappe.has_permission(doctype, ptype="read"):
		raise frappe.PermissionError(_("无权读取{0}。" ).format(_("销售订单") if is_sales else _("采购订单")))
	query_limit = 50 if dsl.get("min_amount") is not None else dsl["limit"]
	if is_sales:
		result = search_sales_orders_v2(
			company=resolved_company,
			date_from=dsl["date_from"],
			date_to=dsl["date_to"],
			status_filter=dsl["status_filter"],
			exclude_cancelled=dsl["exclude_cancelled"],
			sort_by=dsl["sort_by"],
			limit=query_limit,
			start=0,
		)
	else:
		result = search_purchase_orders_v2(
			company=resolved_company,
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
	candidate_names = [row.get(name_field) for row in rows if row.get(name_field)]
	allowed_names = set(
		frappe.get_list(
			doctype,
			filters={"name": ["in", candidate_names]},
			pluck="name",
			limit_page_length=max(1, len(candidate_names)),
		)
		if candidate_names
		else []
	)
	items = []
	for row in rows:
		name = row.get(name_field)
		amount = float(row.get("order_amount_estimate") or 0)
		if name not in allowed_names:
			continue
		if dsl.get("min_amount") is not None and amount < dsl["min_amount"]:
			continue
		party_name = row.get("customer_name") if is_sales else row.get("supplier_name")
		items.append(
			{
				"name": name,
				"party": party_name,
				"company": row.get("company"),
				"transaction_date": str(row.get("transaction_date") or ""),
				"delivery_date": str(row.get("delivery_date") or "") or None,
				"document_status": row.get("document_status"),
				"amount": amount,
				"outstanding_amount": float(row.get("outstanding_amount") or 0),
				"completion": row.get("completion") or {},
			}
		)
		if len(items) >= dsl["limit"]:
			break
	citation_type = "sales_order" if is_sales else "purchase_order"
	href_prefix = "/sales/orders" if is_sales else "/purchases/orders"
	citations = [
		{
			"type": citation_type,
			"id": row["name"],
			"label": f"{row['name']} · {row.get('party') or ''}",
			"href": f"{href_prefix}/{row['name']}",
			"data": row,
		}
		for row in items
	]
	tool_calls = [
		{
			"tool": "search_sales_orders" if is_sales else "search_purchase_orders",
			"risk_level": "L1_READ_ONLY",
			"dsl_hash": hashlib.sha256(json.dumps(dsl, sort_keys=True).encode("utf-8")).hexdigest(),
			"company": resolved_company,
			"result_count": len(items),
		}
	]
	context = {
		"tool": tool_calls[0]["tool"],
		"query": query,
		"dsl": dsl,
		"summary": data.get("summary") or {},
		"orders": items,
		"instructions": "订单数据来自受控只读查询。回答必须说明公司、日期、状态和金额筛选口径，并引用订单号；不得编造未返回的订单。",
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
	return {
		"status": "success",
		"message": _("AI 反馈已记录。"),
		"data": ai_repository.submit_feedback(
			run_id=(run_id or "").strip(),
			user=user,
			rating=resolved_rating,
			category=resolved_category,
			comment=resolved_comment,
		),
	}


def _prepare_chat_run(
	messages=None,
	scenario: str | None = None,
	company: str | None = None,
	conversation_id: str | None = None,
	content: str | None = None,
):
	user = _current_user()
	resolved_scenario = _resolve_scenario(scenario)
	legacy_messages = _normalize_messages(messages) if messages not in (None, "", []) else []
	current_content = _normalize_content(content) if content not in (None, "") else None
	if not current_content:
		if legacy_messages and legacy_messages[-1]["role"] != "user":
			frappe.throw(_("messages 最后一条必须是 user 消息。"))
		user_messages = [row["content"] for row in legacy_messages if row["role"] == "user"]
		if not user_messages:
			frappe.throw(_("请提供用户消息。"))
		current_content = user_messages[-1]

	resolved_company = _resolve_company_scope(
		company,
		required=resolved_scenario in {"product_search", "order_query"},
	)
	is_new_conversation = not conversation_id
	if conversation_id:
		conversation = ai_repository.get_conversation(conversation_id=conversation_id, user=user)["conversation"]
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
				prompt_version=PROMPT_VERSION,
			)
	else:
		ai_repository.append_message(
			conversation_id=conversation_id,
			user=user,
			role="user",
			content=current_content,
			scenario=resolved_scenario,
			prompt_version=PROMPT_VERSION,
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
		"citations": citations,
		"tool_calls": tool_calls,
		"payload": {
			"messages": model_messages,
			"scenario": resolved_scenario,
			"user": user,
			"company": resolved_company,
			"locale": getattr(frappe.local, "lang", None) or "zh-CN",
			"context": tool_context,
			"prompt_version": PROMPT_VERSION,
		},
	}


def _complete_chat_run(prepared: dict, result: dict, assistant_content: str):
	latency_ms = int((time.perf_counter() - prepared["started"]) * 1000)
	ai_repository.append_message(
		conversation_id=prepared["conversation_id"],
		user=prepared["user"],
		role="assistant",
		content=assistant_content,
		scenario=prepared["scenario"],
		run_id=prepared["run_id"],
		citations=prepared["citations"],
		prompt_version=PROMPT_VERSION,
	)
	ai_repository.complete_run(
		run_id=prepared["run_id"],
		user=prepared["user"],
		result=result,
		latency_ms=latency_ms,
		tool_calls=prepared["tool_calls"],
	)
	frappe.db.commit()


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
):
	prepared = _prepare_chat_run(
		messages=messages,
		scenario=scenario,
		company=company,
		conversation_id=conversation_id,
		content=content,
	)
	try:
		result = _call_ai_orchestrator(prepared["payload"])
		message = result.get("message") or {}
		assistant_content = str(message.get("content") or "").strip()
		_complete_chat_run(prepared, result, assistant_content)
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
			"trace_id": result.get("trace_id"),
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
):
	prepared = _prepare_chat_run(
		scenario=scenario,
		company=company,
		conversation_id=conversation_id,
		content=content,
	)

	def event_stream():
		content_parts = []
		completed_result = None
		try:
			yield _encode_sse(
				{
					"type": "run_started",
					"conversation": prepared["conversation_id"],
					"run_id": prepared["run_id"],
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

			for event in _stream_ai_orchestrator(prepared["payload"]):
				event_type = event.get("type")
				if event_type == "message_delta":
					content_parts.append(str(event.get("delta") or ""))
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
			_complete_chat_run(prepared, completed_result, assistant_content)
			yield _encode_sse(
				{
					**completed_result,
					"type": "completed",
					"conversation": prepared["conversation_id"],
					"run_id": prepared["run_id"],
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
