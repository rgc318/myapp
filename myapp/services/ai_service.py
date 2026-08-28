from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

import frappe
from frappe import _
from frappe.exceptions import QueryDeadlockError
from frappe.utils import cint, flt, getdate, now_datetime, nowdate
from frappe.utils.synchronization import filelock
from werkzeug.wrappers import Response

from myapp.services import ai_repository
from myapp.services.ai_attachment_service import (
	hydrate_ai_message_attachments,
	resolve_ai_attachments,
	stage_attachment_as_item_image,
)
from myapp.services.ai_vector_service import search_products_semantic
from myapp.services.customer_service import list_customers_v2
from myapp.services.document_list_service import list_business_documents_v1
from myapp.services.inventory_service import reconcile_inventory_stock_v1
from myapp.services.ai_model_governance_service import (
	ADVANCED_DIAGNOSTIC_ROLES,
	resolve_ai_agent_runtime_readiness,
	resolve_ai_selected_model_alias,
)
from myapp.services.order_service import (
	create_order_v2,
	get_sales_order_detail,
	search_sales_orders_v2,
	update_order_items_v2,
	update_order_v2,
)
from myapp.services.purchase_service import (
	create_purchase_order,
	get_purchase_order_detail_v2,
	list_suppliers_v2,
	search_purchase_orders_v2,
	update_purchase_order_items_v2,
	update_purchase_order_v2,
)
from myapp.services.report_service import (
	get_business_report_overview_v1,
	get_cashflow_report_v1,
	get_purchase_report_v1,
	get_receivable_payable_report_v1,
	get_sales_report_v1,
)
from myapp.services.wholesale_service import (
	create_product_v2,
	get_product_detail_v2,
	search_product_v2,
	update_product_v2,
)
from myapp.services.ai_draft_state import (
	SCHEMA_VERSION as AI_DRAFT_STATE_SCHEMA_VERSION,
	build_draft_state,
	classify_value,
	derive_patch_from_submission,
	field_fact,
	merge_baseline_patch,
)
from myapp.utils.ai_errors import AiDraftVersionConflictError, AiServiceError
from myapp.utils.api_response import UpstreamServiceUnavailableError
from myapp.utils.idempotency import get_current_request_id, run_idempotent
from myapp.utils.uom import resolve_item_quantity_to_stock
from myapp.utils.uom_display import resolve_uom_display_name
from myapp.utils.standard_uoms import STANDARD_UOMS

MAX_AI_MESSAGES = 20
MAX_AI_MESSAGE_CHARS = 8000
MAX_AI_PRODUCT_RESULTS = 8
CONVERSATION_STATE_SCHEMA_VERSION = "conversation-state-v2"
AI_INTENT_PROMPT_VERSION = "erp-intent-v6"
CONVERSATION_STATE_BUSINESS_SCENARIOS = {"product_search", "order_query", "report_summary"}
ALLOWED_AI_ROLES = {"user", "assistant"}
ALLOWED_AI_SCENARIOS = {"auto", "general", "product_search", "order_query", "report_summary"}
AI_ACTION_SCENARIOS = {
	"general", "product_search", "order_query", "report_summary",
	"sales_order_draft", "purchase_order_draft", "inventory_adjustment_draft",
	"product_setup_draft",
}
AI_DRAFT_SCENARIOS = {
	"sales_order_draft", "purchase_order_draft", "inventory_adjustment_draft",
	"product_setup_draft",
}
PROMPT_VERSION_BY_SCENARIO = {
	"general": "erp-readonly-v11",
	"product_search": "erp-readonly-v11",
	"order_query": "erp-readonly-v11",
	"report_summary": "erp-readonly-v11",
	"sales_order_draft": "sales-order-draft-v4",
	"purchase_order_draft": "purchase-order-draft-v4",
	"inventory_adjustment_draft": "inventory-adjustment-draft-v2",
	"product_setup_draft": "product-setup-draft-v6",
}

PRODUCT_SETUP_EDITABLE_FIELDS = (
	"item_name",
	"image",
	"barcode",
	"specification",
	"item_group",
	"brand",
	"stock_uom",
	"standard_selling_rate",
	"wholesale_rate",
	"retail_rate",
	"standard_buying_rate",
	"currency",
	"description",
)
PRODUCT_SEARCH_PREFIX_PATTERN = re.compile(
	r"^(?:请|麻烦|可以|能否|帮我|给我|我想|我要)*(?:查询|查看|查找|搜索|检索|找一下|找一找|找找|找)?(?:一下|下)?"
)
PRODUCT_SEARCH_STATUS_SUFFIX_PATTERN = re.compile(
	r"(?:现在|目前)?(?:是否|有没有|有无)?(?:已|已经)?(?:正常)?(?:有)?(?:入库|到货|有货|现货|库存)"
	r"(?:情况|状态|数量)?(?:了)?(?:吗)?$"
)
GENERIC_IMAGE_PRODUCT_QUERY_TOKENS = (
	"我们的商品中", "我们的商品里", "我们的商品", "商品中", "商品里",
	"图片中的", "图片里的", "图片上的", "照片中的", "照片里的", "照片上的",
	"图中的", "图里的", "图上的", "这个商品", "该商品", "那个商品",
	"这款商品", "这件商品", "这个产品", "该产品", "这个饮料", "这个东西",
	"有没有", "是否有", "有无", "能不能找到", "能否找到", "查询一下",
	"查一下", "找一下", "查询", "查找", "搜索", "帮我", "请", "看看",
	"看下", "一下", "我们的", "商品", "产品", "饮料", "东西", "这个",
	"那个", "该", "中", "里", "的", "吗", "呢", "是", "有",
)
LOW_INFORMATION_VISUAL_PRODUCT_QUERY_TOKENS = (
	"红色", "橙色", "黄色", "绿色", "青色", "蓝色", "紫色", "黑色", "白色", "灰色",
	"透明", "彩色", "深色", "浅色", "大包装", "小包装", "包装", "外包装", "标签",
	"瓶装", "罐装", "盒装", "袋装", "桶装", "箱装", "杯装", "散装", "整箱",
	"瓶子", "罐子", "盒子", "袋子", "桶", "箱子", "杯子", "容器",
	"圆形", "方形", "长方形", "大瓶", "小瓶", "大罐", "小罐",
	"饮料", "食品", "零食", "日用品", "商品", "产品", "东西",
)
PRODUCT_CONTEXT_TARGET_PATTERN = re.compile(
	r"(?:这|该|那)(?:一个|个|款|件)?商品"
	r"|(?:它|刚才那个|上面那个|前面那个)(?:商品)?"
	r"|(?:刚才|之前|前面|上面|上一(?:条|个)|查询到|查到|找到)(?:的)?(?:这|该|那)?(?:一个|个|款|件)?商品"
)
ORDER_CONTEXT_TARGET_PATTERN = re.compile(
	r"(?:这|该|那)(?:一个|个|张|笔|份)?(?:订单|单据)"
	r"|(?:它|刚才那个|上面那个|前面那个)(?:订单|单据)?"
	r"|(?:刚才|之前|前面|上面|上一(?:条|个|张|笔|份)|查询到|查到|找到)(?:的)?"
	r"(?:这|该|那)?(?:一个|个|张|笔|份)?(?:订单|单据)"
)
BUSINESS_PARTNER_CONTEXT_TARGET_PATTERN = re.compile(
	r"(?:这|该|那)(?:一个|个|位|家)?(?:客户|供应商)"
	r"|(?:刚才那个|上面那个|前面那个)(?:客户|供应商)"
	r"|(?:刚才|之前|前面|上面|上一(?:个|位|家)|查询到|查到|找到)(?:的)?"
	r"(?:这|该|那)?(?:一个|个|位|家)?(?:客户|供应商)"
)
PRODUCT_UPDATE_ACTION_PATTERN = re.compile(
	r"(?:修改|更新|完善|补充|调整|改成|改为|替换|设置|设为|变更)"
	r"|(?:添加|增加|删除|移除).{0,8}(?:条码|规格|品牌|名称|描述|价格|单位|图片|主图|封面)"
)
ORDER_UPDATE_ACTION_PATTERN = re.compile(
	r"(?:修改|更新|完善|补充|调整|改成|改为|替换|设置|设为|变更)"
	r"|(?:添加|增加|删除|移除).{0,8}(?:商品|明细|行项目|订单项)"
)
PRODUCT_IMAGE_REFERENCE_PATTERN = re.compile(
	r"(?:之前|刚才|前面|上面|上一(?:张|个)|那(?:张|个)|这(?:张|个)|我(?:给你)?(?:发|上传|提供))"
	r".{0,12}(?:图片|照片|图)"
	"|"
	r"(?:图片|照片|图).{0,12}(?:之前|刚才|前面|上面|上一(?:张|个)|那(?:张|个)|这(?:张|个)|我(?:给你)?(?:发|上传|提供))"
)
PRODUCT_IMAGE_TARGET_PATTERN = re.compile(r"(?:商品图片|商品图|主图|封面|图片字段)")
PRODUCT_IMAGE_APPLY_ACTION_PATTERN = re.compile(
	r"(?:使用|采用|沿用|设为|设置为|作为|用作|替换|换成|改成|更新成|放进|加入|添加)"
)
PRODUCT_IMAGE_NEGATION_PATTERN = re.compile(
	r"(?:不要|别|无需|不用|不再|不需要).{0,10}(?:使用|采用|沿用|替换|更新|修改|设置)?.{0,8}(?:图片|照片|图)"
	"|"
	r"(?:保留|沿用).{0,8}(?:现有|原有|当前).{0,8}(?:图片|照片|图|主图|封面)"
)


def _current_user() -> str:
	user = str(getattr(frappe.session, "user", None) or "").strip()
	if not user or user == "Guest":
		frappe.throw(_("请先登录后再使用 AI 助手。"), frappe.AuthenticationError)
	return user


def _can_view_advanced_diagnostics(user: str) -> bool:
	roles = set(frappe.get_roles(user) or [])
	return user == "Administrator" or bool(roles & ADVANCED_DIAGNOSTIC_ROLES)


def _diagnostic_user() -> str:
	try:
		return _current_user()
	except (RuntimeError, frappe.AuthenticationError):
		return "Guest"


def _resolve_ai_model_display(model_alias: str | None) -> str | None:
	resolved_alias = str(model_alias or "").strip()
	if not resolved_alias:
		return None
	try:
		display = frappe.db.get_value(
			"MyApp AI Model Registry",
			{"model_alias": resolved_alias},
			"provider_model_display",
		)
	except Exception:
		display = None
	return str(display).strip() if isinstance(display, str) and display.strip() else resolved_alias


def _public_ai_model_display(
	model_alias: str | None,
	*,
	include_advanced_diagnostics: bool,
) -> str | None:
	resolved_alias = str(model_alias or "").strip() or None
	if not resolved_alias:
		return None
	display = _resolve_ai_model_display(resolved_alias)
	if include_advanced_diagnostics or display != resolved_alias:
		return display
	return _("策略自动选择模型")


def _public_model_details(model_alias: str | None, *, user: str) -> dict:
	resolved_alias = str(model_alias or "").strip() or None
	if not resolved_alias:
		return {}
	advanced = _can_view_advanced_diagnostics(user)
	result = {
		"model_display": _public_ai_model_display(
			resolved_alias,
			include_advanced_diagnostics=advanced,
		),
	}
	if advanced:
		result["model_alias"] = resolved_alias
	return result


def _public_run_summary(run: dict, *, include_advanced_diagnostics: bool) -> dict:
	public = {
		"status": run.get("status"),
		"latency_ms": cint(run.get("latency_ms")),
		"model_selection": run.get("model_selection") or "auto",
		"requested_model_display": run.get("requested_model_display"),
	}
	if run.get("error_code"):
		public["error_code"] = run.get("error_code")
	if run.get("error"):
		public["error"] = run.get("error")
	if include_advanced_diagnostics:
		public["first_token_ms"] = run.get("first_token_ms")
		public["requested_model_alias"] = run.get("requested_model_alias")
	return public


def _public_ai_result_details(
	*, result: dict, run: dict, include_advanced_diagnostics: bool,
	stream: dict | None = None,
) -> dict:
	model_alias = str(result.get("model_alias") or "").strip() or None
	public = {
		"run": _public_run_summary(
			run,
			include_advanced_diagnostics=include_advanced_diagnostics,
		),
		"model_display": _public_ai_model_display(
			model_alias,
			include_advanced_diagnostics=include_advanced_diagnostics,
		),
		"warnings": result.get("warnings") or [],
	}
	if include_advanced_diagnostics:
		public.update({
			"model": result.get("model"),
			"model_alias": model_alias,
			"policy_code": result.get("policy_code"),
			"policy_version": result.get("policy_version"),
			"fallback_reason": result.get("fallback_reason"),
			"trace_id": result.get("trace_id"),
			"usage": result.get("usage") or {},
		})
		if stream is not None:
			public["stream"] = stream
	return public


def _merge_ai_warnings(*groups) -> list[str]:
	result = []
	for group in groups:
		for warning in group or []:
			resolved = str(warning or "").strip()
			if resolved and resolved not in result:
				result.append(resolved)
	return result


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


def _load_model_messages(*, conversation_id: str, user: str) -> list[dict]:
	return hydrate_ai_message_attachments(
		ai_repository.load_model_messages(
			conversation_id=conversation_id,
			user=user,
			limit=MAX_AI_MESSAGES,
		),
		user=user,
	)


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
		word in text for word in (
			"查询", "查找", "查看", "看看", "搜索", "找", "告诉我", "确认", "有没有", "哪些", "是否", "状态", "吗",
		)
	):
		return "product_search"
	return "general"


def _conversation_state_for_intent(state: dict | None) -> dict:
	"""Return only the bounded, non-sensitive working state sent to the parser."""
	if not isinstance(state, dict):
		return {"schema_version": CONVERSATION_STATE_SCHEMA_VERSION, "active_scenario": "general"}
	allowed = {
		"schema_version", "active_scenario", "product", "order", "report",
		"active_entities", "last_result_set",
	}
	result = {key: state[key] for key in allowed if key in state}
	result["schema_version"] = CONVERSATION_STATE_SCHEMA_VERSION
	result.setdefault("active_scenario", "general")
	return result


def _resolved_conversation_entity(
	conversation_state: dict | None,
	*,
	slot: str,
	allowed_entity_types: set[str],
) -> dict | None:
	"""Resolve one server-owned entity reference without treating it as live ERP data."""
	state = _conversation_state_for_intent(conversation_state)
	active_entities = state.get("active_entities") if isinstance(state.get("active_entities"), dict) else {}
	has_active_slot = slot in active_entities and isinstance(active_entities.get(slot), dict)
	active = active_entities.get(slot) if has_active_slot else {}
	entity_type = str(active.get("entity_type") or "").strip()
	entity_id = str(active.get("entity_id") or "").strip()
	if (
		active.get("resolution_status") == "resolved"
		and entity_type in allowed_entity_types
		and entity_id
	):
		return {
			"entity_type": entity_type,
			"entity_id": entity_id,
			"display_name": str(active.get("display_name") or "").strip() or None,
			"source": "conversation_active_entity",
			"context_ref": f"active_entities.{slot}",
		}
	# An explicit ambiguous/not-found slot is authoritative.  Falling back to an
	# older result set here would silently resurrect a stale entity.
	if has_active_slot:
		return None

	# Read legacy product state during the rolling migration to conversation-state-v2.
	if slot == "product" and "product" in allowed_entity_types:
		product = state.get("product") if isinstance(state.get("product"), dict) else {}
		item_code = str(product.get("item_code") or "").strip()
		if item_code and product.get("resolution_status") == "resolved":
			return {
				"entity_type": "product",
				"entity_id": item_code,
				"display_name": str(product.get("item_name") or "").strip() or None,
				"source": "conversation_product",
				"context_ref": "product",
			}

	last_result_set = (
		state.get("last_result_set")
		if isinstance(state.get("last_result_set"), dict)
		else {}
	)
	entity_refs = [
		row for row in last_result_set.get("entity_refs") or []
		if isinstance(row, dict)
		and str(row.get("entity_type") or "").strip() in allowed_entity_types
		and str(row.get("entity_id") or "").strip()
	]
	if len(entity_refs) == 1:
		row = entity_refs[0]
		return {
			"entity_type": str(row.get("entity_type") or "").strip(),
			"entity_id": str(row.get("entity_id") or "").strip(),
			"display_name": str(row.get("display_name") or "").strip() or None,
			"source": "conversation_result_set",
			"context_ref": f"last_result_set:{last_result_set.get('id') or 'latest'}",
		}

	# Legacy product result sets only carried entity_ids.
	legacy_ids = [
		str(value or "").strip()
		for value in last_result_set.get("entity_ids") or []
		if str(value or "").strip()
	]
	if (
		slot == "product"
		and "product" in allowed_entity_types
		and last_result_set.get("type") == "products"
		and len(legacy_ids) == 1
	):
		return {
			"entity_type": "product",
			"entity_id": legacy_ids[0],
			"display_name": None,
			"source": "conversation_result_set",
			"context_ref": f"last_result_set:{last_result_set.get('id') or 'latest'}",
		}
	return None


def _candidate_uses_context_reference(
	*, content: str, candidate_value: str | None, pattern: re.Pattern,
) -> bool:
	"""Return true only when the current request is deictic rather than explicitly named."""
	compact_content = re.sub(r"\s+", "", str(content or ""))
	compact_candidate = re.sub(r"\s+", "", str(candidate_value or ""))
	if not compact_content:
		return False
	if compact_candidate and pattern.search(compact_candidate):
		return True
	if not pattern.search(compact_content):
		return False
	# An explicit entity appearing in the current message always wins over old state.
	if compact_candidate and compact_candidate in compact_content:
		return False
	return True


def _resolve_conversation_product_target(
	*, content: str, item_query: str | None, conversation_state: dict | None,
) -> dict | None:
	if not _candidate_uses_context_reference(
		content=content, candidate_value=item_query, pattern=PRODUCT_CONTEXT_TARGET_PATTERN,
	):
		return None
	target = _resolved_conversation_entity(
		conversation_state, slot="product", allowed_entity_types={"product"},
	)
	if not target:
		return None
	return {
		"item_code": target["entity_id"],
		"item_name": target.get("display_name"),
		"source": target["source"],
		"context_ref": target["context_ref"],
	}


def _resolve_conversation_order_target(
	*, content: str, order_number: str | None, conversation_state: dict | None,
	allowed_entity_type: str,
) -> dict | None:
	if not _candidate_uses_context_reference(
		content=content, candidate_value=order_number, pattern=ORDER_CONTEXT_TARGET_PATTERN,
	):
		return None
	target = _resolved_conversation_entity(
		conversation_state,
		slot="business_document",
		allowed_entity_types={allowed_entity_type},
	)
	if not target:
		return None
	return {
		"order_number": target["entity_id"],
		"source": target["source"],
		"context_ref": target["context_ref"],
	}


def _resolve_conversation_business_partner_target(
	*, content: str, party_query: str | None, conversation_state: dict | None,
	allowed_entity_type: str,
) -> dict | None:
	if not _candidate_uses_context_reference(
		content=content,
		candidate_value=party_query,
		pattern=BUSINESS_PARTNER_CONTEXT_TARGET_PATTERN,
	):
		return None
	target = _resolved_conversation_entity(
		conversation_state,
		slot="business_partner",
		allowed_entity_types={allowed_entity_type},
	)
	if not target:
		return None
	return {
		"party_name": target["entity_id"],
		"display_name": target.get("display_name"),
		"source": target["source"],
		"context_ref": target["context_ref"],
	}


def _state_intent_defaults(state: dict | None) -> dict:
	state = _conversation_state_for_intent(state)
	active = str(state.get("active_scenario") or "general")
	if active == "product_search" and isinstance(state.get("product"), dict):
		product = state["product"]
		return {
			"intent": "product_search", "confidence": 0.9,
			"product_query": product.get("query"), "entities": [], "report_type": None,
			"date_preset": "all", "date_from": None, "date_to": None,
			"status": "all", "sort": "latest", "min_amount": None, "limit": 10,
		}
	if active == "order_query" and isinstance(state.get("order"), dict):
		order = state["order"]
		return {
			"intent": "order_query", "confidence": 0.9,
			"product_query": None, "entities": order.get("entities") or [], "report_type": None,
			"date_preset": order.get("date_preset") or "all", "date_from": order.get("date_from"),
			"date_to": order.get("date_to"), "status": order.get("status") or "all",
			"sort": order.get("sort") or "latest", "min_amount": order.get("min_amount"),
			"limit": order.get("limit") or 10,
		}
	if active == "report_summary" and isinstance(state.get("report"), dict):
		report = state["report"]
		return {
			"intent": "report_summary", "confidence": 0.9,
			"product_query": None, "entities": [], "report_type": report.get("report_type") or "overview",
			"date_preset": report.get("date_preset") or "all", "date_from": report.get("date_from"),
			"date_to": report.get("date_to"), "status": "all", "sort": "latest",
			"min_amount": None, "limit": 10,
		}
	return {}


def _query_explicitly_mentions(content: str, *terms: str) -> bool:
	text = " ".join(str(content or "").split())
	return any(term in text for term in terms)


def _merge_intent_with_conversation_state(
	content: str, candidate: dict, conversation_state: dict | None, *,
	has_current_attachments: bool = False,
) -> dict:
	"""Merge only omitted/default parser fields from state; explicit current text wins."""
	if not isinstance(candidate, dict) or not _structured_intent_is_confident(candidate):
		return candidate if isinstance(candidate, dict) else {}
	base = _state_intent_defaults(conversation_state)
	if not base or candidate.get("intent") != base.get("intent"):
		return candidate
	merged = dict(candidate)
	if candidate.get("intent") == "product_search":
		# A new image is a new source of product identity.  If vision extraction
		# fails, do not silently reuse the previous product and query the wrong Item.
		if (
			not has_current_attachments
			and not str(candidate.get("product_query") or "").strip()
			and base.get("product_query")
		):
			merged["product_query"] = base["product_query"]
		return merged
	if candidate.get("intent") == "order_query":
		if not candidate.get("entities") and not _query_explicitly_mentions(content, "订单", "发票", "销售", "采购"):
			merged["entities"] = base.get("entities") or []
		if candidate.get("date_preset") in (None, "all") and not _query_explicitly_mentions(
			content, "今天", "本周", "这周", "上月", "上个月", "本月", "这个月", "最近一个月", "近",
		):
			for key in ("date_preset", "date_from", "date_to"):
				merged[key] = base.get(key)
		if candidate.get("status") in (None, "all") and not _query_explicitly_mentions(
			content, "未完成", "完成", "取消", "作废", "待发货", "待收货", "付款", "收款",
		):
			merged["status"] = base.get("status") or "all"
		if candidate.get("sort") in (None, "latest") and not _query_explicitly_mentions(
			content, "最高", "最低", "最大", "最小", "大额", "最早", "从高", "从低",
		):
			merged["sort"] = base.get("sort") or "latest"
		if candidate.get("min_amount") is None and not _query_explicitly_mentions(
			content, "超过", "大于", "高于", "不少于", "至少",
		):
			merged["min_amount"] = base.get("min_amount")
		if cint(candidate.get("limit")) == 10 and not _query_explicitly_mentions(
			content, "前", "后", "条", "笔", "张", "个",
		):
			merged["limit"] = base.get("limit") or 10
		return merged
	if candidate.get("intent") == "report_summary":
		if candidate.get("report_type") in (None, "overview") and not _query_explicitly_mentions(
			content, "销售", "采购", "现金流", "资金", "应收", "应付", "经营总览",
		):
			merged["report_type"] = base.get("report_type") or "overview"
		if candidate.get("date_preset") in (None, "all") and not _query_explicitly_mentions(
			content, "今天", "本周", "这周", "上月", "上个月", "本月", "这个月", "最近一个月", "近",
		):
			for key in ("date_preset", "date_from", "date_to"):
				merged[key] = base.get(key)
	return merged


def _infer_ai_action_scenario(content: str, conversation_state: dict | None = None) -> str:
	text = " ".join((content or "").strip().split())
	write_words = ("创建", "新增", "添加", "生成", "新建", "建档", "录入")
	product_write_words = write_words + ("完善", "修改", "补充", "维护", "更新")
	if any(word in text for word in ("库存", "存量")) and any(
		word in text
		for word in (
			"调整", "盘点", "增加", "添加", "补充", "减少", "扣减", "移除",
			"改为", "设置为", "设为", "更新",
		)
	):
		return "inventory_adjustment_draft"
	if any(word in text for word in ("采购订单", "采购单", "向供应商采购", "进货")) and any(
		word in text for word in write_words + ("向供应商", "进货",)
	):
		return "purchase_order_draft"
	if any(word in text for word in ("采购这个商品", "采购该商品", "购买这个商品", "购买该商品")):
		return "purchase_order_draft"
	if any(word in text for word in ("销售订单", "销售单", "给客户", "卖给")) and any(
		word in text for word in write_words + ("给客户", "卖给", "开",)
	):
		return "sales_order_draft"
	if any(word in text for word in ("销售这个商品", "销售该商品", "出售这个商品", "出售该商品")):
		return "sales_order_draft"
	if ORDER_UPDATE_ACTION_PATTERN.search(text) and ORDER_CONTEXT_TARGET_PATTERN.search(text):
		target = _resolved_conversation_entity(
			conversation_state,
			slot="business_document",
			allowed_entity_types={"sales_order", "purchase_order"},
		)
		if target and target.get("entity_type") == "sales_order":
			return "sales_order_draft"
		if target and target.get("entity_type") == "purchase_order":
			return "purchase_order_draft"
	if any(word in text for word in ("商品", "产品", "SKU")) and any(
		word in text for word in product_write_words
	):
		return "product_setup_draft"
	return _infer_ai_scenario(text)


def _resolve_ai_action_scenario(
	content: str,
	conversation_state: dict | None,
	semantic_intent: dict | None,
) -> tuple[str, str, float | None]:
	"""Resolve semantic routing first while keeping deterministic write safety."""
	local_scenario = _infer_ai_action_scenario(content, conversation_state)
	intent = semantic_intent if isinstance(semantic_intent, dict) else {}
	candidate = str(intent.get("intent") or "").strip()
	try:
		confidence = min(1.0, max(0.0, float(intent.get("confidence") or 0)))
	except (TypeError, ValueError):
		confidence = 0
	if candidate not in AI_ACTION_SCENARIOS or confidence < 0.6:
		return local_scenario, "local_rules", None

	# A confident semantic router is authoritative for normal routing.  The
	# deterministic layer only prevents an explicit write request from being
	# downgraded into a read-only Agent path, and preserves the typed document
	# target when both layers identify different draft workflows.
	if local_scenario in AI_DRAFT_SCENARIOS and (
		candidate not in AI_DRAFT_SCENARIOS or candidate != local_scenario
	):
		return local_scenario, "structured_intent_write_guard", confidence
	return candidate, "structured_intent", confidence


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


def _call_ai_orchestrator(payload: dict, *, resume: bool = False) -> dict:
	base_url, service_token = _get_ai_orchestrator_settings()
	endpoint = (
		"/internal/v1/agent/run/resume"
		if resume else "/internal/v1/agent/run"
	) if payload.get("capability_token") else "/internal/v1/chat"
	request = urllib.request.Request(
		f"{base_url}{endpoint}",
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
	except urllib.error.HTTPError as error:
		frappe.log_error(frappe.get_traceback(), _("AI Orchestrator 调用失败"))
		code = {
			401: "AI_SERVICE_AUTHENTICATION_FAILED",
			403: "AI_SERVICE_AUTHENTICATION_FAILED",
			409: "AI_PROMPT_VERSION_MISMATCH",
			422: "AI_REQUEST_INVALID",
			429: "AI_REQUEST_RATE_LIMITED",
		}.get(error.code, "AI_SERVICE_UNAVAILABLE")
		model_alias = str(payload.get("model_alias") or "").strip() or None
		provider_error_code = None
		try:
			body = json.loads(error.read().decode("utf-8") or "{}")
			detail = body.get("detail") if isinstance(body, dict) else None
			candidate = detail.get("code") if isinstance(detail, dict) else None
			if isinstance(candidate, str) and (
				candidate.startswith("AI_") or candidate == "MODEL_PROVIDER_REJECTED"
			):
				code = candidate
			if isinstance(detail, dict):
				model_alias = str(detail.get("model_alias") or model_alias or "").strip() or None
				provider_error_code = str(detail.get("provider_error_code") or "").strip() or None
		except (UnicodeDecodeError, json.JSONDecodeError):
			pass
		user = _diagnostic_user()
		model_display = _public_model_details(model_alias, user=user).get("model_display")
		message = {
			"AI_SELECTED_MODEL_NO_VISION": _("当前固定模型不支持图片输入，请切换为自动模型或选择多模态模型。"),
			"AI_VISION_MODEL_REQUIRED": _("当前策略没有可用的多模态模型，请联系管理员完成视觉能力检测。"),
			"AI_AGENT_CHECKPOINT_UNAVAILABLE": _("Agent 运行状态暂时无法保存，请稍后重试。"),
			"AI_DAILY_BUDGET_EXCEEDED": _("今日 AI 使用预算已达到上限。"),
			"AI_LOCAL_CONCURRENCY_LIMITED": _("当前 AI 请求较多，请稍后重试。"),
			"AI_MODEL_CIRCUIT_OPEN": _("当前模型暂时不可用，请稍后重试。"),
			"AI_MONTHLY_BUDGET_EXCEEDED": _("本月 AI 使用预算已达到上限。"),
			"AI_PROMPT_VERSION_MISMATCH": _("AI 配置版本不一致，请联系管理员处理。"),
			"AI_REQUEST_INVALID": _("AI 请求内容未通过校验，请修改后重试。"),
			"AI_REQUEST_RATE_LIMITED": _("AI 请求过于频繁，请稍后重试。"),
			"AI_RUNTIME_GOVERNANCE_UNAVAILABLE": _("AI 运行治理服务暂时不可用。"),
			"AI_SERVICE_AUTHENTICATION_FAILED": _("AI 内部服务认证失败，请联系管理员。"),
			"MODEL_PROVIDER_REJECTED": _("模型 {0} 暂时不可用，请更换模型或稍后重试。").format(
				model_display or _("当前自动模型")
			),
		}.get(code, _("AI 服务暂时不可用，请稍后重试。"))
		public_data = {
			**_public_model_details(model_alias, user=user),
			"retryable": code in {"AI_SERVICE_UNAVAILABLE", "MODEL_PROVIDER_REJECTED"},
		}
		if provider_error_code and _can_view_advanced_diagnostics(user):
			public_data["provider_error_code"] = provider_error_code
		raise AiServiceError(
			message,
			code=code,
			http_status=error.code,
			model_alias=model_alias,
			provider_error_code=provider_error_code,
			public_data=public_data,
		) from error
	except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
		frappe.log_error(frappe.get_traceback(), _("AI Orchestrator 调用失败"))
		raise UpstreamServiceUnavailableError(_("AI 服务暂时不可用，请稍后重试。"))

	message = result.get("message") if isinstance(result, dict) else None
	if not isinstance(message, dict) or not str(message.get("content") or "").strip():
		raise UpstreamServiceUnavailableError(_("AI 服务返回了无效响应。"))
	return result


def _call_ai_intent_orchestrator(
	*, content: str, user: str, company: str | None, conversation_state: dict | None = None,
	model_alias: str | None = None, attachments: list[dict] | None = None,
) -> dict:
	try:
		base_url, service_token = _get_ai_orchestrator_settings()
		payload = {
			"messages": [{"role": "user", "content": content}],
			"scenario": "intent_parse",
			"user": user,
			"company": company,
			"locale": getattr(frappe.local, "lang", None) or "zh-CN",
			"prompt_version": AI_INTENT_PROMPT_VERSION,
			"context": {"conversation_state": _conversation_state_for_intent(conversation_state)},
		}
		if attachments:
			payload["attachments"] = attachments
		if model_alias:
			payload["model_alias"] = model_alias
		request = urllib.request.Request(
			f"{base_url}/internal/v1/intent/parse",
			data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
			headers={
				"Authorization": f"Bearer {service_token}",
				"Content-Type": "application/json",
				"Accept": "application/json",
			},
			method="POST",
		)
		# Intent parsing is a separate model call.  Keep its timeout below the
		# normal chat budget, but long enough for reasoning models on a cold route;
		# a 20s ceiling caused valid contextual follow-ups to silently fall back.
		with urllib.request.urlopen(request, timeout=45) as response:
			result = json.loads(response.read().decode("utf-8") or "{}")
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("AI 意图解析调用失败，已回退本地规则"))
		return {}
	intent = result.get("intent") if isinstance(result, dict) else None
	return intent if isinstance(intent, dict) else {}


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


def _draft_provider_error(error: urllib.error.HTTPError, *, payload: dict) -> AiServiceError:
	code = "AI_SERVICE_UNAVAILABLE"
	model_alias = str(payload.get("model_alias") or "").strip() or None
	provider_error_code = None
	try:
		body = json.loads(error.read().decode("utf-8") or "{}")
		detail = body.get("detail") if isinstance(body, dict) else None
		if isinstance(detail, dict):
			candidate = str(detail.get("code") or "").strip()
			if candidate == "MODEL_PROVIDER_REJECTED" or candidate.startswith("AI_"):
				code = candidate
			model_alias = str(detail.get("model_alias") or model_alias or "").strip() or None
			provider_error_code = str(detail.get("provider_error_code") or "").strip() or None
	except (UnicodeDecodeError, json.JSONDecodeError):
		pass
	user = _diagnostic_user()
	if code == "MODEL_PROVIDER_REJECTED":
		model_display = _public_model_details(model_alias, user=user).get("model_display") or _("当前自动模型")
		message = _("模型 {0} 暂时不可用，请更换模型或稍后重试。").format(model_display)
	elif code == "AI_SELECTED_MODEL_NO_VISION":
		message = _("当前固定模型不支持图片输入，请切换为自动模型或选择多模态模型。")
	elif code == "AI_VISION_MODEL_REQUIRED":
		message = _("当前策略没有可用的多模态模型，请联系管理员完成视觉能力检测。")
	else:
		message = _("AI 草稿服务暂时不可用，请稍后重试。")
	public_data = {
		**_public_model_details(model_alias, user=user),
		"retryable": code not in {"AI_SELECTED_MODEL_NO_VISION", "AI_VISION_MODEL_REQUIRED"},
	}
	if provider_error_code and _can_view_advanced_diagnostics(user):
		public_data["provider_error_code"] = provider_error_code
	return AiServiceError(
		message,
		code=code,
		http_status=502 if code == "MODEL_PROVIDER_REJECTED" else error.code,
		model_alias=model_alias,
		provider_error_code=provider_error_code,
		public_data=public_data,
	)


def _call_ai_orchestrator_draft(payload: dict, *, endpoint: str, log_title: str) -> dict:
	base_url, service_token = _get_ai_orchestrator_settings()
	request = urllib.request.Request(
		f"{base_url}{endpoint}",
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
	except urllib.error.HTTPError as error:
		frappe.log_error(frappe.get_traceback(), log_title)
		raise _draft_provider_error(error, payload=payload) from error
	except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
		frappe.log_error(frappe.get_traceback(), log_title)
		raise UpstreamServiceUnavailableError(_("AI 草稿服务暂时不可用，请稍后重试。"))
	if not isinstance(result.get("draft"), dict):
		raise UpstreamServiceUnavailableError(_("AI 草稿服务返回了无效响应。"))
	return result


def _call_ai_orchestrator_sales_draft(payload: dict) -> dict:
	return _call_ai_orchestrator_draft(
		payload,
		endpoint="/internal/v1/drafts/sales-order",
		log_title=_("AI 销售订单草稿调用失败"),
	)


def _call_ai_orchestrator_purchase_draft(payload: dict) -> dict:
	return _call_ai_orchestrator_draft(
		payload,
		endpoint="/internal/v1/drafts/purchase-order",
		log_title=_("AI 采购订单草稿调用失败"),
	)


def _call_ai_orchestrator_inventory_adjustment_draft(payload: dict) -> dict:
	return _call_ai_orchestrator_draft(
		payload,
		endpoint="/internal/v1/drafts/inventory-adjustment",
		log_title=_("AI 库存调整草稿调用失败"),
	)


def _call_ai_orchestrator_product_setup_draft(payload: dict) -> dict:
	return _call_ai_orchestrator_draft(
		payload,
		endpoint="/internal/v1/drafts/product-setup",
		log_title=_("AI 商品建档草稿调用失败"),
	)


def _stream_ai_orchestrator(payload: dict, *, resume: bool = False):
	base_url, service_token = _get_ai_orchestrator_settings()
	endpoint = (
		"/internal/v1/agent/run/resume/stream"
		if resume else "/internal/v1/agent/run/stream"
	) if payload.get("capability_token") else "/internal/v1/chat/stream"
	request = urllib.request.Request(
		f"{base_url}{endpoint}",
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
	except urllib.error.HTTPError as error:
		frappe.log_error(frappe.get_traceback(), _("AI Orchestrator 流式调用失败"))
		code = {
			401: "AI_SERVICE_AUTHENTICATION_FAILED",
			403: "AI_SERVICE_AUTHENTICATION_FAILED",
			409: "AI_PROMPT_VERSION_MISMATCH",
			422: "AI_REQUEST_INVALID",
			429: "AI_REQUEST_RATE_LIMITED",
		}.get(error.code, "AI_SERVICE_UNAVAILABLE")
		try:
			body = json.loads(error.read().decode("utf-8") or "{}")
			detail = body.get("detail") if isinstance(body, dict) else None
			candidate = detail.get("code") if isinstance(detail, dict) else None
			if isinstance(candidate, str) and (
				candidate.startswith("AI_") or candidate == "MODEL_PROVIDER_REJECTED"
			):
				code = candidate
		except (UnicodeDecodeError, json.JSONDecodeError):
			pass
		message = {
			"AI_DAILY_BUDGET_EXCEEDED": _("今日 AI 使用预算已达到上限。"),
			"AI_LOCAL_CONCURRENCY_LIMITED": _("当前 AI 请求较多，请稍后重试。"),
			"AI_MODEL_CIRCUIT_OPEN": _("当前模型暂时不可用，请稍后重试。"),
			"AI_MONTHLY_BUDGET_EXCEEDED": _("本月 AI 使用预算已达到上限。"),
			"AI_PROMPT_VERSION_MISMATCH": _("AI 配置版本不一致，请联系管理员处理。"),
			"AI_REQUEST_INVALID": _("AI 请求内容未通过校验，请修改后重试。"),
			"AI_REQUEST_RATE_LIMITED": _("AI 请求过于频繁，请稍后重试。"),
			"AI_RUNTIME_GOVERNANCE_UNAVAILABLE": _("AI 运行治理服务暂时不可用。"),
			"AI_SERVICE_AUTHENTICATION_FAILED": _("AI 内部服务认证失败，请联系管理员。"),
		}.get(code, _("AI 流式服务暂时不可用，请稍后重试。"))
		raise AiServiceError(message, code=code, http_status=error.code) from error
	except (urllib.error.URLError, TimeoutError):
		frappe.log_error(frappe.get_traceback(), _("AI Orchestrator 流式调用失败"))
		raise AiServiceError(
			_("AI 流式服务暂时不可用，请稍后重试。"),
			code="AI_SERVICE_UNAVAILABLE",
		) from None
	except (UnicodeDecodeError, json.JSONDecodeError):
		frappe.log_error(frappe.get_traceback(), _("AI Orchestrator 流式响应解析失败"))
		raise AiServiceError(
			_("AI 流式响应格式异常，请稍后重试。"),
			code="AI_STREAM_PROTOCOL_ERROR",
		) from None


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
		# “商品/产品” is request language in both “商品迪莫” and “查询迪莫商品”.
		value = re.sub(r"^(?:商品|产品)\s*[:：]?\s*", "", value).strip()
		if len(value) > 2 and value.endswith("商品"):
			value = value[:-2].rstrip(" ：:")
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


def _product_search_text_has_entity_hint(content: str | None) -> bool:
	"""Return whether text contains a product identity beyond deictic request language."""
	text = unicodedata.normalize("NFKC", str(content or "")).casefold()
	for token in sorted(GENERIC_IMAGE_PRODUCT_QUERY_TOKENS, key=len, reverse=True):
		text = text.replace(token, "")
	return bool(re.sub(r"[\W_]+", "", text, flags=re.UNICODE))


def _visual_product_query_has_reliable_entity_hint(content: str | None) -> bool:
	"""Reject model-produced appearance/category descriptions as image identity."""
	text = unicodedata.normalize("NFKC", str(content or "")).casefold()
	for token in sorted(
		GENERIC_IMAGE_PRODUCT_QUERY_TOKENS + LOW_INFORMATION_VISUAL_PRODUCT_QUERY_TOKENS,
		key=len,
		reverse=True,
	):
		text = text.replace(token, "")
	return bool(re.sub(r"[\W_]+", "", text, flags=re.UNICODE))


def _multimodal_product_query_is_unresolved(
	*, content: str, structured_intent: dict | None, attachment_payloads: list[dict],
) -> bool:
	if not attachment_payloads:
		return False
	if _product_search_text_has_entity_hint(content):
		return False
	product_query = str((structured_intent or {}).get("product_query") or "").strip()
	return not _visual_product_query_has_reliable_entity_hint(product_query)


def _normalize_product_entity_text(value: str) -> str:
	"""Normalize user-entered product identifiers without losing the raw query."""
	text = unicodedata.normalize("NFKC", str(value or ""))
	text = " ".join(text.strip().split())
	return text.casefold()


def _product_row_matches_exact(row: dict, query: str) -> tuple[bool, bool]:
	"""Return (raw_exact, normalized_exact) for code/name/nickname/barcode fields."""
	query_text = str(query or "").strip()
	query_normalized = _normalize_product_entity_text(query_text)
	values = [
		row.get("item_code"), row.get("item_name"), row.get("nickname"), row.get("barcode"),
	]
	for value in values:
		resolved = str(value or "").strip()
		if not resolved:
			continue
		if resolved == query_text:
			return True, True
		if _normalize_product_entity_text(resolved) == query_normalized:
			return False, True
	return False, False


def _product_row_exact_match_fields(row: dict, query: str) -> set[str]:
	"""Return fields whose normalized value exactly matches a query."""
	query_normalized = _normalize_product_entity_text(query)
	if not query_normalized:
		return set()
	return {
		field for field in ("item_code", "item_name", "nickname", "barcode")
		if _normalize_product_entity_text(row.get(field)) == query_normalized
	}


def _normalize_product_hint_values(values, *, limit: int, max_length: int = 140) -> list[str]:
	result = []
	for value in values if isinstance(values, (list, tuple)) else []:
		resolved = " ".join(str(value or "").strip().split())[:max_length]
		if resolved and resolved not in result:
			result.append(resolved)
		if len(result) >= limit:
			break
	return result


def _product_clarification_context(rows: list[dict], *, selected: dict | None) -> dict:
	if selected or not rows:
		return {"required": False, "reason": None, "candidate_count": len(rows), "suggested_fields": []}
	differentiators = []
	for field in ("brand", "specification", "item_name", "nickname", "item_code"):
		values = {str(row.get(field) or "").strip() for row in rows if str(row.get(field) or "").strip()}
		if len(values) > 1 or (len(rows) == 1 and values):
			differentiators.append(field)
	return {
		"required": True,
		"reason": "single_fuzzy_candidate" if len(rows) == 1 else "multiple_candidates",
		"candidate_count": len(rows),
		"suggested_fields": differentiators[:4],
	}


def _resolve_item_candidates(
	query: str,
	*,
	company: str | None,
	context: str = "sales",
	warehouse: str | None = None,
	limit: int = 8,
	entity_query: str | None = None,
	query_terms: list[str] | None = None,
	hypotheses: list[str] | None = None,
	attributes: dict | None = None,
	match_mode: str = "auto",
	search_fields: list[str] | None = None,
) -> dict:
	"""Resolve an ERP Item through one shared, permission-safe retrieval boundary."""
	raw_query = " ".join(str(query or "").strip().split())
	resolved_entity_query = " ".join(str(entity_query or "").strip().split())
	retrieval_query = resolved_entity_query or raw_query
	model_terms = _normalize_product_hint_values(query_terms, limit=8)
	model_hypotheses = _normalize_product_hint_values(hypotheses, limit=5)
	attribute_values = _normalize_product_hint_values(
		[(attributes or {}).get(field) for field in (
			"brand", "item_group", "color", "flavor", "specification", "capacity", "packaging",
		)],
		limit=7,
		max_length=200,
	)
	terms = _normalize_product_hint_values(
		[retrieval_query, *model_terms, *model_hypotheses, *_extract_product_search_terms(retrieval_query)],
		limit=12,
		max_length=200,
	)
	allowed_search_fields = {
		"barcode", "item_code", "item_name", "nickname", "specification", "brand", "item_group",
	}
	resolved_search_fields = [
		str(field) for field in (search_fields or []) if str(field) in allowed_search_fields
	] or ["barcode", "item_code", "item_name", "nickname", "specification", "brand", "item_group"]
	resolved_match_mode = str(match_mode or "auto").strip()
	if resolved_match_mode not in {"auto", "exact", "contains", "semantic"}:
		resolved_match_mode = "auto"
	lexical_rows = []
	seen_codes = set()
	for term in ([] if resolved_match_mode == "semantic" else terms[:12]):
		rows = (search_product_v2(
			search_key=term,
			company=company,
			warehouse=warehouse,
			limit=max(1, min(int(limit or 8) * 2, MAX_AI_PRODUCT_RESULTS * 2)),
			disabled=0,
			search_fields=resolved_search_fields,
			item_context=context,
		) or {}).get("data") or []
		for row in rows:
			code = str(row.get("item_code") or "").strip()
			if code and code not in seen_codes:
				seen_codes.add(code)
				lexical_rows.append(dict(row))
			if len(lexical_rows) >= max(1, int(limit or 8) * 2):
				break
		if len(lexical_rows) >= max(1, int(limit or 8) * 2):
			break

	# Hypotheses improve recall but never prove identity and therefore never participate
	# in automatic exact selection.
	confirmed_terms = _normalize_product_hint_values(
		[retrieval_query, *model_terms, *_extract_product_search_terms(retrieval_query)],
		limit=12,
		max_length=200,
	)
	entity_queries = [raw_query, resolved_entity_query] + [
		term for term in confirmed_terms if term not in {raw_query, resolved_entity_query}
	]
	entity_queries = [value for value in entity_queries if value]
	identifier_matches = [
		row for row in lexical_rows
		if any(_product_row_exact_match_fields(row, value) & {"item_code", "barcode"} for value in entity_queries)
	]
	text_matches = [
		row for row in lexical_rows
		if any(_product_row_exact_match_fields(row, value) & {"item_name", "nickname"} for value in entity_queries)
	]
	exact_identifier = identifier_matches[0] if len(identifier_matches) == 1 else None
	exact_text = text_matches[0] if len(text_matches) == 1 and len(lexical_rows) == 1 else None
	# Descriptive expressions and zero/multiple lexical hits benefit from semantic recall;
	# exact identifiers never depend on the vector service.
	descriptive = bool(model_hypotheses or attribute_values or len(model_terms) > 1) or any(
		word in retrieval_query for word in ("适合", "用于", "可以", "能够", "规格", "颜色", "包装")
	)
	semantic_query = "；".join(_normalize_product_hint_values(
		[
			raw_query if _product_search_text_has_entity_hint(raw_query) else None,
			retrieval_query,
			*model_terms,
			*attribute_values,
			*model_hypotheses,
		],
		limit=20,
		max_length=200,
	)) or retrieval_query
	semantic_result = {"available": False, "rows": [], "reason": "not_needed"}
	if not exact_identifier and (
		resolved_match_mode == "semantic"
		or (
			resolved_match_mode == "auto"
			and (not lexical_rows or len(lexical_rows) > 1 or descriptive)
		)
	):
		semantic_result = search_products_semantic(
			semantic_query,
			company=company,
			limit=max(1, min(int(limit or 8) * 2, MAX_AI_PRODUCT_RESULTS * 2)),
			item_context=context,
		)
	semantic_rows = semantic_result.get("rows") or []
	if semantic_rows:
		top_semantic_score = max(float(row.get("semantic_score") or 0) for row in semantic_rows)
		semantic_score_floor = max(0.5 if lexical_rows else 0.35, top_semantic_score - 0.12)
		filtered_semantic_rows = [
			row for row in semantic_rows
			if float(row.get("semantic_score") or 0) >= semantic_score_floor
		]
		semantic_result = {
			**semantic_result,
			"raw_result_count": len(semantic_rows),
			"score_floor": round(semantic_score_floor, 6),
			"rows": filtered_semantic_rows,
		}
		semantic_rows = filtered_semantic_rows
	rows = _hybrid_rerank_product_rows(
		query=retrieval_query,
		lexical_rows=lexical_rows,
		semantic_rows=semantic_rows,
		limit=max(1, int(limit or 8)),
		preferred_terms=model_hypotheses,
		attribute_terms=attribute_values,
	)
	if exact_identifier:
		selected = exact_identifier
		match_method, confidence = "exact", 1.0
	elif exact_text:
		selected = exact_text
		match_method = (
			"exact"
			if any(_product_row_matches_exact(exact_text, value)[0] for value in entity_queries)
			else "normalized"
		)
		confidence = 1.0 if match_method == "exact" else 0.99
	else:
		selected = None
		match_method, confidence = ("hybrid" if semantic_rows and lexical_rows else "semantic" if semantic_rows else "lexical"), 0.0
	# Re-apply current Item record permissions after both lexical and vector retrieval.
	codes = [row.get("item_code") for row in rows if row.get("item_code")]
	allowed = set(
		frappe.get_list(
			"Item", filters={"name": ["in", codes]}, pluck="name", limit_page_length=max(1, len(codes)),
		) if codes else []
	)
	rows = [row for row in rows if row.get("item_code") in allowed]
	if selected and selected.get("item_code") not in allowed:
		selected = None
	if selected:
		status = "resolved"
	elif rows:
		status = "ambiguous"
	else:
		status = "not_found"
	return {
		"resolved_query": retrieval_query,
		"semantic_query": semantic_query,
		"status": status,
		"selected": selected,
		"candidates": rows[: max(1, int(limit or 8))],
		"match_method": match_method,
		"confidence": confidence,
		"semantic_available": bool(semantic_result.get("available")),
		"semantic_result": semantic_result,
		"search_terms": terms,
		"hypotheses": model_hypotheses,
		"attributes": dict(attributes or {}),
		"clarification": _product_clarification_context(rows, selected=selected),
	}


def _hybrid_rerank_product_rows(
	*, query: str, lexical_rows: list[dict], semantic_rows: list[dict], limit: int,
	preferred_terms: list[str] | None = None, attribute_terms: list[str] | None = None,
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
	preferred_keys = [
		re.sub(r"\s+", "", _normalize_product_entity_text(term))
		for term in (preferred_terms or []) if str(term or "").strip()
	]
	attribute_keys = [
		re.sub(r"\s+", "", _normalize_product_entity_text(term))
		for term in (attribute_terms or []) if str(term or "").strip()
	]
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
		for term in preferred_keys:
			if term and term in document_key:
				entry["score"] += 0.04
		for term in attribute_keys:
			if term and term in document_key:
				entry["score"] += 0.012
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


def _build_product_search_context(
	*, query: str, company: str | None, structured_intent: dict | None = None,
	query_source: str | None = None,
) -> tuple[dict, list[dict], list[dict]]:
	if not frappe.has_permission("Item", ptype="read"):
		raise frappe.PermissionError(_("无权读取商品资料。"))
	resolved_company = _resolve_company_scope(company, required=True)
	requested_limit = max(1, min(
		MAX_AI_PRODUCT_RESULTS,
		cint((structured_intent or {}).get("limit")) or MAX_AI_PRODUCT_RESULTS,
	))
	resolution = _resolve_item_candidates(
		query,
		company=resolved_company,
		context="sales",
		limit=requested_limit,
		entity_query=(structured_intent or {}).get("product_query"),
		query_terms=(structured_intent or {}).get("product_terms")
			or (structured_intent or {}).get("query_variants"),
		hypotheses=(structured_intent or {}).get("product_hypotheses")
			or (structured_intent or {}).get("hypotheses"),
		attributes=(structured_intent or {}).get("product_attributes")
			or (structured_intent or {}).get("attributes"),
		match_mode=(structured_intent or {}).get("match_mode") or "auto",
		search_fields=(structured_intent or {}).get("search_fields"),
	)
	search_terms = resolution["search_terms"]
	semantic_result = resolution["semantic_result"]
	result_rows = resolution["candidates"]
	candidate_codes = [row.get("item_code") for row in result_rows if row.get("item_code")]
	allowed_codes = set(candidate_codes)
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
	queried_at = str(now_datetime())
	citations = [
		{
			"type": "product",
			"id": row.get("item_code"),
			"label": row.get("item_name") or row.get("item_code"),
			"href": f"/products/{row.get('item_code')}",
			"data": {
				**row,
				"company": resolved_company,
				"queried_at": queried_at,
			},
		}
		for row in products
	]
	tool_calls = [
		{
			"tool": "search_products",
			"risk_level": "L1_READ_ONLY",
			"query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
			"resolved_query_hash": hashlib.sha256(
				str(resolution.get("resolved_query") or query).encode("utf-8")
			).hexdigest(),
			"search_term_hashes": [hashlib.sha256(term.encode("utf-8")).hexdigest() for term in search_terms],
			"company": resolved_company,
			"result_count": len(products),
			"retrieval_mode": "hybrid" if semantic_result.get("available") else "lexical_fallback",
			"semantic_result_count": len(semantic_result.get("rows") or []),
			"embedding_model": semantic_result.get("embedding_model"),
			"vector_collection": semantic_result.get("collection"),
			"query_source": query_source or (
				"structured_intent" if str((structured_intent or {}).get("product_query") or "").strip()
				else "user_text"
			),
			"executed": True,
		}
	]
	context = {
		"tool": "search_products",
		"query": query,
		"resolved_query": resolution.get("resolved_query") or query,
		"search_terms": search_terms,
		"search_hints": {
			"hypotheses": resolution.get("hypotheses") or [],
			"attributes": resolution.get("attributes") or {},
		},
		"company": resolved_company,
		"products": products,
		"resolved_product": (
			{
				"item_code": resolution["selected"].get("item_code"),
				"item_name": resolution["selected"].get("item_name"),
			}
			if resolution.get("selected") else None
		),
		"retrieval": {
			"mode": "hybrid" if semantic_result.get("available") else "lexical_fallback",
			"semantic_available": bool(semantic_result.get("available")),
			"match_method": resolution["match_method"],
			"status": resolution["status"],
			"confidence": resolution["confidence"],
		},
		"clarification": resolution.get("clarification") or {"required": False},
		"query_resolution": {
			"status": "resolved",
			"source": tool_calls[0]["query_source"],
		},
		"instructions": (
			"商品数据是只读工具结果。当前结果是待确认候选；必须请用户结合候选的品牌、规格、口味或包装确认，"
			"不能声称唯一匹配，也不能擅自选择第一条。"
			if (resolution.get("clarification") or {}).get("required")
			else "商品数据是只读工具结果。只能基于这些候选解释匹配原因；不得编造商品、价格或库存。"
		),
	}
	return context, citations, tool_calls


def _build_unresolved_multimodal_product_search_context(
	*, query: str, company: str | None,
) -> tuple[dict, list[dict], list[dict]]:
	"""Represent a vision extraction miss without issuing a meaningless ERP search."""
	if not frappe.has_permission("Item", ptype="read"):
		raise frappe.PermissionError(_("无权读取商品资料。"))
	resolved_company = _resolve_company_scope(company, required=True)
	tool_call = {
		"tool": "search_products",
		"risk_level": "L1_READ_ONLY",
		"query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
		"search_term_hashes": [],
		"company": resolved_company,
		"result_count": 0,
		"retrieval_mode": "not_executed",
		"semantic_result_count": 0,
		"embedding_model": None,
		"vector_collection": None,
		"query_source": "multimodal_intent",
		"query_status": "unresolved_image_entity",
		"executed": False,
	}
	return (
		{
			"tool": "search_products",
			"query": None,
			"search_terms": [],
			"company": resolved_company,
			"products": [],
			"resolved_product": None,
			"retrieval": {
				"mode": "not_executed",
				"semantic_available": False,
				"match_method": "none",
				"status": "query_unresolved",
				"confidence": 0,
			},
			"query_resolution": {
				"status": "unresolved",
				"source": "multimodal_intent",
				"reason": "no_reliable_product_entity",
			},
			"instructions": (
				"图片中尚未提取出可靠的商品名称、品牌、编码、条码或规格，因此本轮没有执行商品数据库查询。"
				"必须明确说明尚未查询，要求用户提供更清晰图片或商品线索；不得表述为数据库中未找到商品。"
			),
		},
		[],
		[tool_call],
	)


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
	elif "最近一个月" in text or "最近1个月" in text or "最近一月" in text:
		days = 30
		date_from = today - timedelta(days=days - 1)
		date_to = today
		date_range = "last_30_days"
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


def _resolve_structured_intent_date_range(
	preset: str | None,
	*,
	date_from: str | None = None,
	date_to: str | None = None,
	as_of: date | None = None,
) -> dict | None:
	resolved = str(preset or "").strip()
	if resolved == "custom":
		try:
			resolved_from = date.fromisoformat(str(date_from or "").strip())
			resolved_to = date.fromisoformat(str(date_to or "").strip())
		except ValueError:
			return None
		if resolved_from > resolved_to:
			return None
		return {
			"date_range": "custom",
			"date_from": str(resolved_from),
			"date_to": str(resolved_to),
		}
	if resolved == "all":
		return {"date_range": "all", "date_from": None, "date_to": None}
	prompt_by_preset = {
		"today": "今天",
		"this_week": "本周",
		"last_month": "上月",
		"this_month": "本月",
		"last_30_days": "近30天",
	}
	prompt = prompt_by_preset.get(resolved)
	return _resolve_natural_date_range(prompt, as_of=as_of, default_days=None) if prompt else None


def _structured_intent_is_confident(intent: dict) -> bool:
	"""Treat the Orchestrator response as untrusted input at the execution boundary."""
	try:
		return 0.6 <= min(1.0, max(0.0, float(intent.get("confidence") or 0)))
	except (TypeError, ValueError):
		return False


def _build_order_query_dsl(
	query: str, *, company: str, as_of: date | None = None,
	structured_intent: dict | None = None, conversation_state: dict | None = None,
) -> dict:
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
	if any(phrase in text for phrase in ("未完成", "还没完成", "尚未完成", "没有完成", "进行中")):
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
	if match := re.search(r"(?:前\s*)?(\d{1,2})\s*(?:条|个|笔|张)", text):
		limit = max(1, min(20, int(match.group(1))))
		limit_explicit = True
	elif match := re.search(r"前\s*([一二两三四五六七八九十百]+)(?:条|个|笔|张)", text):
		chinese_numbers = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
		value = chinese_numbers.get(match.group(1))
		if value:
			limit = value
			limit_explicit = True

	structured_intent = structured_intent if isinstance(structured_intent, dict) else {}
	if structured_intent.get("intent") == "order_query" and _structured_intent_is_confident(structured_intent):
		candidate_entities = structured_intent.get("entities")
		if isinstance(candidate_entities, list):
			allowed_entities = {"sales_order", "sales_invoice", "purchase_order", "purchase_invoice"}
			resolved_entities = [
				candidate
				for candidate in ("sales_order", "sales_invoice", "purchase_order", "purchase_invoice")
				if candidate in candidate_entities and candidate in allowed_entities
			]
			if resolved_entities:
				entities = resolved_entities
				entity = entities[0]
		structured_date = _resolve_structured_intent_date_range(
			structured_intent.get("date_preset"),
			date_from=structured_intent.get("date_from"),
			date_to=structured_intent.get("date_to"),
			as_of=as_of,
		)
		if structured_date and (structured_intent.get("date_preset") != "all" or date_filter["date_range"] == "all"):
			date_filter = structured_date
		candidate_status = str(structured_intent.get("status") or "").strip()
		if candidate_status in {"all", "cancelled", "completed", "delivering", "paying", "receiving", "unfinished"} and (
			candidate_status != "all" or status_filter == "all"
		):
			status_filter = candidate_status
		candidate_sort = str(structured_intent.get("sort") or "").strip()
		if candidate_sort in {"amount_asc", "amount_desc", "latest", "oldest"} and (
			candidate_sort != "latest" or sort_by == "latest"
		):
			sort_by = candidate_sort
		candidate_limit = cint(structured_intent.get("limit"))
		if candidate_limit and (candidate_limit != 10 or not limit_explicit):
			limit = max(1, min(20, candidate_limit))
			limit_explicit = limit != 10 or bool(re.search(r"(?:前|列|返回|给我)", text))
		candidate_min_amount = structured_intent.get("min_amount")
		if min_amount is None and isinstance(candidate_min_amount, (int, float)) and not isinstance(candidate_min_amount, bool):
			min_amount = max(0, min(float(candidate_min_amount), 1000000000000000))

	target_document_name = str(structured_intent.get("document_name") or "").strip()[:140] or None
	target_document_entity = None
	if target_document_name and len(entities) == 1:
		target_document_entity = entities[0]
	elif ORDER_CONTEXT_TARGET_PATTERN.search(text):
		target = _resolved_conversation_entity(
			conversation_state,
			slot="business_document",
			allowed_entity_types={
				"sales_order", "sales_invoice", "purchase_order", "purchase_invoice",
			},
		)
		if target:
			target_document_entity = target["entity_type"]
			target_document_name = target["entity_id"]
	exclude_cancelled = status_filter != "cancelled"
	if target_document_entity and target_document_name:
		entity = target_document_entity
		entities = [target_document_entity]
		date_filter = {"date_range": "all", "date_from": None, "date_to": None}
		status_filter = "all"
		exclude_cancelled = False
		sort_by = "latest"
		min_amount = None
		limit = 1
		limit_explicit = True

	dsl = {
		"entity": entity,
		"entities": entities,
		"company": company,
		**date_filter,
		"status_filter": status_filter,
		"exclude_cancelled": exclude_cancelled,
		"sort_by": sort_by,
		"min_amount": min_amount,
		"limit": limit,
		"limit_explicit": limit_explicit,
	}
	if target_document_entity and target_document_name:
		dsl.update({
			"target_document_entity": target_document_entity,
			"target_document_name": target_document_name,
		})
	return dsl


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
	target_document_name = (
		str(dsl.get("target_document_name") or "").strip()
		if dsl.get("target_document_entity") == entity
		else ""
	)
	if entity in {"sales_order", "purchase_order"}:
		is_sales = entity == "sales_order"
		search = search_sales_orders_v2 if is_sales else search_purchase_orders_v2
		result = search(
			search_key=target_document_name or None,
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
			if target_document_name and name != target_document_name:
				continue
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
					"party_id": row.get("customer") if is_sales else row.get("supplier"),
					"party_display_name": (
						row.get("customer_name") if is_sales else row.get("supplier_name")
					),
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
		search_key=target_document_name or None,
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
		if target_document_name and row.get("name") != target_document_name:
			continue
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
				"party_id": row.get("party"),
				"party_display_name": row.get("party_name") or row.get("party"),
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


def _build_order_query_context(
	*, query: str, company: str | None, structured_intent: dict | None = None,
	conversation_state: dict | None = None,
) -> tuple[dict, list[dict], list[dict]]:
	resolved_company = _resolve_company_scope(company, required=True)
	dsl = _build_order_query_dsl(
		query, company=resolved_company, structured_intent=structured_intent,
		conversation_state=conversation_state,
	)
	result_set, citations, tool_calls = _build_order_query_result(dsl=dsl)
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


def _serialize_business_result_group(*, group: dict, dsl: dict) -> dict:
	returned_count = len(group["items"])
	summary = group.get("summary") or {}
	available_count = None
	if (
		group["entity"] in {"sales_order", "purchase_order"}
		and dsl.get("min_amount") is None
		and summary.get("visible_count") is not None
	):
		available_count = max(returned_count, cint(summary.get("visible_count")))
	return {
		"entity": group["entity"],
		"label": group["label"],
		"module_href": BUSINESS_DOCUMENT_QUERY_CONFIG[group["entity"]]["href_prefix"],
		"requested_count": dsl["limit"] if dsl["limit_explicit"] else None,
		"returned_count": returned_count,
		"available_count": available_count,
		"truncated": available_count > returned_count if available_count is not None else None,
		"status": (
			"empty"
			if not group["items"]
			else "partial"
			if dsl["limit_explicit"] and returned_count < dsl["limit"]
			else "success"
		),
	}


def _build_order_query_result(*, dsl: dict, snapshot_source: str = "answer") -> tuple[dict, list[dict], list[dict]]:
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
				"company": dsl["company"],
				"result_count": len(items),
			}
		)
	queried_at = str(now_datetime())
	result_set = {
		"schema_version": "business-result-set-v1",
		"result_type": "business_documents",
		"status_semantics": "result_coverage_only",
		"queried_at": queried_at,
		"snapshot_source": snapshot_source,
		"permission_filtered": True,
		"scope": {
			"company": dsl["company"],
			"date_range": dsl["date_range"],
			"date_from": dsl["date_from"],
			"date_to": dsl["date_to"],
			"status_filter": dsl["status_filter"],
			"exclude_cancelled": dsl["exclude_cancelled"],
			"sort_by": dsl["sort_by"],
			"min_amount": dsl["min_amount"],
			"limit_per_group": dsl["limit"],
		},
		"groups": [_serialize_business_result_group(group=group, dsl=dsl) for group in groups],
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
	return result_set, citations, tool_calls


def _normalize_ai_business_result_refresh(result_set) -> dict:
	if isinstance(result_set, str):
		result_set = frappe.parse_json(result_set)
	if not isinstance(result_set, dict):
		frappe.throw(_("业务查询快照格式不正确。"))
	if result_set.get("result_type") != "business_documents":
		frappe.throw(_("只支持刷新业务单据查询结果。"))
	scope = result_set.get("scope") or {}
	if not isinstance(scope, dict):
		frappe.throw(_("业务查询范围格式不正确。"))
	groups = result_set.get("groups") or []
	if not isinstance(groups, list):
		frappe.throw(_("业务查询分组格式不正确。"))
	entities = []
	for group in groups:
		entity = str((group or {}).get("entity") or "").strip()
		if entity in BUSINESS_DOCUMENT_QUERY_CONFIG and entity not in entities:
			entities.append(entity)
	if not entities:
		frappe.throw(_("业务查询快照不包含可刷新的单据类型。"))
	company = _resolve_company_scope(scope.get("company"), required=True)
	status_filter = str(scope.get("status_filter") or "all").strip().lower()
	if status_filter not in {"all", "cancelled", "completed", "delivering", "paying", "receiving", "unfinished"}:
		frappe.throw(_("业务查询状态筛选不受支持。"))
	sort_by = str(scope.get("sort_by") or "latest").strip().lower()
	if sort_by not in {"amount_asc", "amount_desc", "latest", "oldest"}:
		frappe.throw(_("业务查询排序方式不受支持。"))
	limit = max(1, min(20, cint(scope.get("limit_per_group") or 10)))
	min_amount = scope.get("min_amount")
	if min_amount is not None:
		min_amount = max(0, flt(min_amount))
	limit_explicit = any(
		isinstance(group, dict) and group.get("requested_count") is not None
		for group in groups
	)
	return {
		"entity": entities[0],
		"entities": entities,
		"company": company,
		"date_range": str(scope.get("date_range") or "all"),
		"date_from": str(scope.get("date_from") or "") or None,
		"date_to": str(scope.get("date_to") or "") or None,
		"status_filter": status_filter,
		"exclude_cancelled": status_filter != "cancelled",
		"sort_by": sort_by,
		"min_amount": min_amount,
		"limit": limit,
		"limit_explicit": limit_explicit,
	}


def refresh_ai_business_result_v1(result_set) -> dict:
	_current_user()
	dsl = _normalize_ai_business_result_refresh(result_set)
	refreshed_result_set, citations, _tool_calls = _build_order_query_result(
		dsl=dsl,
		snapshot_source="refresh",
	)
	return {
		"status": "success",
		"data": {
			"result_set": refreshed_result_set,
			"citations": citations,
		},
		"message": _("业务查询结果已按当前权限刷新。"),
	}


def _build_report_query_dsl(
	query: str, *, company: str, as_of: date | None = None, structured_intent: dict | None = None,
) -> dict:
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

	date_filter = _resolve_natural_date_range(text, as_of=as_of)
	structured_intent = structured_intent if isinstance(structured_intent, dict) else {}
	if structured_intent.get("intent") == "report_summary" and _structured_intent_is_confident(structured_intent):
		candidate_report_type = str(structured_intent.get("report_type") or "").strip()
		if candidate_report_type in {"overview", "sales", "purchase", "cashflow", "receivable_payable"} and (
			candidate_report_type != "overview" or report_type == "overview"
		):
			report_type = candidate_report_type
		structured_date = _resolve_structured_intent_date_range(
			structured_intent.get("date_preset"),
			date_from=structured_intent.get("date_from"),
			date_to=structured_intent.get("date_to"),
			as_of=as_of,
		)
		if structured_date and (structured_intent.get("date_preset") != "all" or date_filter["date_range"] == "all"):
			date_filter = structured_date

	return {
		"report_type": report_type,
		"company": company,
		**date_filter,
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


def _build_report_query_context(
	*, query: str, company: str | None, structured_intent: dict | None = None,
) -> tuple[dict, list[dict], list[dict]]:
	resolved_company = _resolve_company_scope(company, required=True)
	dsl = _build_report_query_dsl(query, company=resolved_company, structured_intent=structured_intent)
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
		if tool_call.get("event_visible") is False:
			continue
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


def list_ai_conversations_v1(
	status: str = "active", search: str | None = None,
	start: int = 0, limit: int = 20,
):
	user = _current_user()
	return {
		"status": "success",
		"message": _("已获取 AI 会话列表。"),
		"data": ai_repository.list_conversations(
			user=user, status=status, search=search, start=start, limit=limit,
		),
	}


def rename_ai_conversation_v1(conversation_id: str, title: str):
	user = _current_user()
	return {
		"status": "success",
		"message": _("AI 会话名称已更新。"),
		"data": ai_repository.rename_conversation(
			conversation_id=conversation_id, user=user, title=title,
		),
	}


def get_ai_conversation_v1(
	conversation_id: str,
	before_sequence: int | None = None,
	limit: int = 40,
):
	user = _current_user()
	return {
		"status": "success",
		"message": _("已获取 AI 会话。"),
		"data": ai_repository.get_conversation(
			conversation_id=conversation_id,
			user=user,
			before_sequence=before_sequence,
			limit=limit,
			include_advanced_diagnostics=_can_view_advanced_diagnostics(user),
		),
	}


def archive_ai_conversation_v1(conversation_id: str):
	user = _current_user()
	return {
		"status": "success",
		"message": _("AI 会话已归档。"),
		"data": ai_repository.archive_conversation(conversation_id=conversation_id, user=user),
	}


def reset_ai_conversation_context_v1(conversation_id: str):
	user = _current_user()
	return {
		"status": "success",
		"message": _("AI 会话工作上下文已清除，历史消息仍然保留。"),
		"data": ai_repository.reset_conversation_state(
			conversation_id=conversation_id, user=user,
		),
	}


def resolve_ai_scenario_v1(
	content: str | None = None,
	attachment_ids=None,
	model_alias: str | None = None,
	company: str | None = None,
	conversation_id: str | None = None,
):
	user = _current_user()
	_attachment_refs, attachment_payloads = resolve_ai_attachments(attachment_ids, user=user)
	if content in (None, "") and attachment_payloads:
		content = _("请识别附件图片对应的业务场景；无法确定时返回 general。")
	resolved_content = _normalize_content(content)
	conversation_state = {
		"schema_version": CONVERSATION_STATE_SCHEMA_VERSION,
		"active_scenario": "general",
	}
	conversation_company = None
	if conversation_id:
		conversation = ai_repository.get_conversation(
			conversation_id=str(conversation_id).strip(), user=user,
		)["conversation"]
		conversation_company = str(conversation.get("company") or "").strip() or None
		state_record = ai_repository.get_conversation_state(
			conversation_id=str(conversation_id).strip(), user=user,
			expire_if_needed=conversation.get("status") == "active",
		)
		conversation_state = state_record.get("state") or conversation_state
	requested_company = str(company or "").strip() or None
	if requested_company and conversation_company and requested_company != conversation_company:
		frappe.throw(_("当前公司与会话公司范围不一致，请新建会话。"))
	resolved_company = _resolve_company_scope(
		requested_company or conversation_company, required=False,
	)
	intent = _call_ai_intent_orchestrator(
		content=resolved_content,
		user=user,
		company=resolved_company,
		conversation_state=conversation_state,
		model_alias=resolve_ai_selected_model_alias(model_alias),
		attachments=attachment_payloads,
	)
	resolved_scenario, _resolution_mode, _confidence = _resolve_ai_action_scenario(
		resolved_content, conversation_state, intent,
	)
	return {
		"status": "success",
		"message": _("AI 场景识别完成。"),
		"data": {"scenario": resolved_scenario},
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


def _authoritative_reference_price(selected: dict, *, buying: bool) -> tuple[float | None, str]:
	price_summary = selected.get("price_summary") if isinstance(selected.get("price_summary"), dict) else {}
	price_list = "Standard Buying" if buying else str(selected.get("price_list") or "Standard Selling")
	rows = price_summary.get("buying_prices" if buying else "selling_prices") or []
	row = next((value for value in rows if str(value.get("price_list") or "") == price_list), None)
	if row:
		return flt(row.get("rate")), f"Item Price/{price_list}"
	if not buying and selected.get("standard_rate") not in (None, "", 0, 0.0):
		return flt(selected.get("standard_rate")), "Item/standard_rate"
	return None, f"Item Price/{price_list}"


def _resolve_line_price_intent(
	candidate: dict,
	*,
	reference_price: float | None,
	allow_user_price: bool,
) -> tuple[float | None, dict]:
	previous_state = candidate.get("_state") if isinstance(candidate.get("_state"), dict) else {}
	previous_patch = previous_state.get("patch") if isinstance(previous_state.get("patch"), dict) else {}
	previous_effective = previous_state.get("effective") if isinstance(previous_state.get("effective"), dict) else {}
	user_patch = dict(previous_patch)
	submitted_price = None if candidate.get("price") in (None, "") else flt(candidate.get("price"))
	if allow_user_price:
		if previous_state.get("schema_version") == AI_DRAFT_STATE_SCHEMA_VERSION:
			if submitted_price != previous_effective.get("price"):
				if submitted_price == reference_price:
					user_patch.pop("price", None)
				else:
					user_patch["price"] = submitted_price
		elif submitted_price is not None:
			user_patch["price"] = submitted_price
	if user_patch.get("price") is not None and flt(user_patch.get("price")) < 0:
		user_patch.pop("price", None)
	resolved_price = user_patch.get("price") if "price" in user_patch else reference_price
	return resolved_price, user_patch


def _build_transaction_line_state(
	*,
	selected: dict,
	reference_price: float | None,
	reference_source: str,
	resolved_price: float | None,
	user_patch: dict,
	uom: str | None,
	conversion_factor: float | None,
) -> dict:
	state = build_draft_state(
		operation="transaction",
		entity_doctype="Item",
		entity_name=selected.get("item_code"),
		entity_modified=selected.get("modified"),
		observed_at=datetime.now(),
		baseline={"price": reference_price},
		patch=user_patch,
		fields={
			"price": field_fact(
				resolved_price,
				source="user" if "price" in user_patch else reference_source,
			),
			"conversion_factor": field_fact(conversion_factor, source="UOM Conversion Detail"),
		},
		source_facts={
			"entity_modified": selected.get("modified"),
			"reference_price": reference_price,
			"reference_price_status": classify_value(reference_price),
			"uom": uom,
			"conversion_factor": conversion_factor,
		},
	)
	state["reference_price"] = reference_price
	state["reference_price_source"] = reference_source
	return state


def _resolve_purchase_draft_item(
	candidate: dict, *, company: str, default_warehouse: str | None,
	allow_user_price: bool = False,
) -> dict:
	query = str(candidate.get("item_query") or "").strip()
	target_source = str(candidate.get("_target_source") or "").strip() or "explicit_or_model_query"
	target_context_ref = str(candidate.get("_target_context_ref") or "").strip() or None
	qty = float(candidate.get("qty") or 0)
	resolution = _resolve_item_candidates(query, company=company, context="purchase", limit=5)
	rows = resolution["candidates"]
	selected = resolution["selected"]
	warnings = []
	warehouse_query = candidate.get("warehouse_query")
	warehouse = _resolve_sales_draft_warehouse(warehouse_query, company) or default_warehouse
	if qty <= 0:
		warnings.append(_("数量必须大于 0。"))
	if not warehouse:
		warnings.append(_("缺少当前公司可用的收货仓库。"))
	if not selected:
		warnings.append(_("商品“{0}”无法唯一匹配，请人工选择。" ).format(query))
		return {
			"item_query": query, "item_code": None, "item_name": None, "qty": qty,
			"target_source": target_source, "target_context_ref": target_context_ref,
			"uom": candidate.get("uom"), "uom_display": None, "stock_uom": None,
			"stock_uom_display": None, "price": None, "warehouse_query": warehouse_query,
			"warehouse": warehouse,
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
	reference_price, reference_source = _authoritative_reference_price(selected, buying=True)
	user_price = None if candidate.get("price") in (None, "") else flt(candidate.get("price"))
	if allow_user_price and user_price is not None and user_price < 0:
		warnings.append(_("人工价格不能小于 0，已改用当前后端采购参考价。"))
	resolved_price, user_patch = _resolve_line_price_intent(
		candidate,
		reference_price=reference_price,
		allow_user_price=allow_user_price,
	)
	if not allow_user_price and user_price is not None and user_price != reference_price:
		warnings.append(_("模型建议价格未采用，草稿使用当前后端采购参考价。"))
	conversion_factor = float((uom_row or {}).get("conversion_factor") or 1)
	return {
		"item_query": query, "item_code": selected.get("item_code"), "item_name": selected.get("item_name"),
		"target_source": target_source, "target_context_ref": target_context_ref,
		"qty": qty, "uom": resolved_uom,
		"uom_display": (uom_row or {}).get("uom_display") or resolve_uom_display_name(resolved_uom),
		"stock_uom": selected.get("uom"), "stock_uom_display": selected.get("uom_display"),
		"price": resolved_price, "reference_price": reference_price,
		"price_source": "user" if "price" in user_patch else "system",
		"warehouse_query": warehouse_query, "warehouse": warehouse,
		"conversion_factor": conversion_factor,
		"candidates": [{"item_code": row.get("item_code"), "item_name": row.get("item_name")} for row in rows],
		"warnings": warnings,
		"_state": _build_transaction_line_state(
			selected=selected,
			reference_price=reference_price,
			reference_source=reference_source,
			resolved_price=resolved_price,
			user_patch=user_patch,
			uom=resolved_uom,
			conversion_factor=conversion_factor,
		),
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
	target_source = str(candidate.get("_target_source") or "").strip() or "explicit_or_model_query"
	target_context_ref = str(candidate.get("_target_context_ref") or "").strip() or None
	adjustment_type = str(candidate.get("adjustment_type") or "set_target").strip()
	quantity_value = candidate.get("quantity")
	input_qty = None if quantity_value in (None, "") else flt(quantity_value)
	warnings = []
	resolution = _resolve_item_candidates(
		query, company=company, context="inventory", warehouse=warehouse, limit=5,
	) if query else {"candidates": [], "selected": None}
	rows = resolution["candidates"]
	selected = resolution["selected"]
	if not selected:
		warnings.append(_("商品“{0}”无法唯一匹配，请人工选择。").format(query or _("未填写")))
		return {
			"item_query": query,
			"item_code": None,
			"item_name": None,
			"target_source": target_source,
			"target_context_ref": target_context_ref,
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
	valuation_value = price_summary.get("valuation_rate")
	valuation_rate = None if valuation_value in (None, "") else flt(valuation_value)
	conversion_factor = flt((quantity_context or {}).get("conversion_factor") or 1)
	line_state = build_draft_state(
		operation="transaction",
		entity_doctype="Item",
		entity_name=selected.get("item_code"),
		entity_modified=selected.get("modified"),
		observed_at=datetime.now(),
		baseline={
			"current_stock_qty": current_stock_qty,
			"valuation_rate": valuation_rate,
			"conversion_factor": conversion_factor,
		},
		patch={
			"adjustment_type": adjustment_type,
			"quantity": input_qty,
			"uom": resolved_uom,
		},
		fields={
			"current_stock_qty": field_fact(current_stock_qty, source="Bin/actual_qty"),
			"valuation_rate": field_fact(valuation_rate, source="Item/valuation_rate"),
			"conversion_factor": field_fact(conversion_factor, source="UOM Conversion Detail"),
		},
		source_facts={
			"entity_modified": selected.get("modified"),
			"warehouse": warehouse,
			"current_stock_qty": current_stock_qty,
			"valuation_rate": valuation_rate,
			"uom": resolved_uom,
			"conversion_factor": conversion_factor,
		},
	)
	return {
		"item_query": query,
		"item_code": selected.get("item_code"),
		"item_name": selected.get("item_name"),
		"target_source": target_source,
		"target_context_ref": target_context_ref,
		"qty": input_qty,
		"uom": resolved_uom,
		"uom_display": (uom_row or {}).get("uom_display") or resolve_uom_display_name(resolved_uom),
		"stock_uom": stock_uom,
		"stock_uom_display": selected.get("uom_display") or resolve_uom_display_name(stock_uom),
		"warehouse": warehouse,
		"conversion_factor": conversion_factor,
		"current_stock_qty": current_stock_qty,
		"target_stock_qty": target_stock_qty,
		"qty_delta": flt(target_stock_qty - current_stock_qty) if target_stock_qty is not None else None,
		"valuation_rate": valuation_rate,
		"candidates": [
			{"item_code": row.get("item_code"), "item_name": row.get("item_name")}
			for row in rows
		],
		"warnings": warnings,
		"_state": line_state,
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
			"_target_source": candidate.get("_target_source") or source_item.get("_target_source"),
			"_target_context_ref": (
				candidate.get("_target_context_ref") or source_item.get("_target_context_ref")
			),
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
	default_sales_mode: str = "wholesale", allow_user_price: bool = False,
) -> dict:
	query = str(candidate.get("item_query") or "").strip()
	target_source = str(candidate.get("_target_source") or "").strip() or "explicit_or_model_query"
	target_context_ref = str(candidate.get("_target_context_ref") or "").strip() or None
	qty = float(candidate.get("qty") or 0)
	resolution = _resolve_item_candidates(query, company=company, context="sales", limit=5)
	rows = resolution["candidates"]
	selected = resolution["selected"]
	warnings = []
	if qty <= 0:
		warnings.append(_("数量必须大于 0。"))
	warehouse_query = candidate.get("warehouse_query")
	warehouse = _resolve_sales_draft_warehouse(warehouse_query, company) or default_warehouse
	if not warehouse:
		warnings.append(_("缺少当前公司可用的明细仓库。"))
	if not selected:
		warnings.append(_("商品“{0}”无法唯一匹配，请人工选择。" ).format(query))
		return {
			"item_query": query, "item_code": None, "item_name": None, "qty": qty,
			"target_source": target_source, "target_context_ref": target_context_ref,
			"uom": candidate.get("uom"), "uom_display": None, "price": None,
			"stock_uom": None, "stock_uom_display": None,
			"warehouse_query": warehouse_query, "warehouse": warehouse,
			"conversion_factor": None,
			"candidates": [{"item_code": row.get("item_code"), "item_name": row.get("item_name")} for row in rows],
			"warnings": warnings,
		}
	all_uoms = selected.get("all_uoms") or []
	requested_uom = str(candidate.get("uom") or "").strip()
	uom_row = next((row for row in all_uoms if str(row.get("uom") or "") == requested_uom), None)
	if requested_uom and not uom_row:
		warnings.append(_("商品 {0} 未配置单位 {1}，已改用默认单位。" ).format(selected.get("item_code"), requested_uom))
	resolved_sales_mode = "retail" if default_sales_mode == "retail" else "wholesale"
	mode_default_uom = (
		selected.get("retail_default_uom")
		if resolved_sales_mode == "retail"
		else selected.get("wholesale_default_uom")
	)
	if not uom_row and mode_default_uom:
		uom_row = next(
			(row for row in all_uoms if str(row.get("uom") or "") == mode_default_uom),
			None,
		)
	resolved_uom = (uom_row or {}).get("uom") or mode_default_uom or selected.get("uom")
	reference_price, reference_source = _authoritative_reference_price(selected, buying=False)
	user_price = None if candidate.get("price") in (None, "") else flt(candidate.get("price"))
	if allow_user_price and user_price is not None and user_price < 0:
		warnings.append(_("人工价格不能小于 0，已改用当前后端参考价。"))
	resolved_price, user_patch = _resolve_line_price_intent(
		candidate,
		reference_price=reference_price,
		allow_user_price=allow_user_price,
	)
	if not allow_user_price and user_price is not None and user_price != reference_price:
		warnings.append(_("模型建议价格未采用，草稿使用当前后端参考价。"))
	conversion_factor = float((uom_row or {}).get("conversion_factor") or 1)
	return {
		"item_query": query,
		"item_code": selected.get("item_code"),
		"item_name": selected.get("item_name"),
		"target_source": target_source,
		"target_context_ref": target_context_ref,
		"qty": qty,
		"uom": resolved_uom,
		"uom_display": (uom_row or {}).get("uom_display") or resolve_uom_display_name(resolved_uom),
		"stock_uom": selected.get("uom"),
		"stock_uom_display": selected.get("uom_display"),
		"price": resolved_price,
		"reference_price": reference_price,
		"price_source": "user" if "price" in user_patch else "system",
		"warehouse_query": warehouse_query, "warehouse": warehouse,
		"conversion_factor": conversion_factor,
		"candidates": [{"item_code": row.get("item_code"), "item_name": row.get("item_name")} for row in rows],
		"warnings": warnings,
		"_state": _build_transaction_line_state(
			selected=selected,
			reference_price=reference_price,
			reference_source=reference_source,
			resolved_price=resolved_price,
			user_patch=user_patch,
			uom=resolved_uom,
			conversion_factor=conversion_factor,
		),
	}


def _resolve_order_update_source(
	candidate: dict, *, draft_type: str, company: str,
) -> tuple[str, str | None, dict | None, list[str]]:
	requested_operation = str(candidate.get("operation") or "auto").strip().lower()
	if requested_operation not in {"auto", "create", "update"}:
		requested_operation = "auto"
	order_number = str(candidate.get("order_number") or "").strip()[:140] or None
	source_document_type = str(candidate.get("source_document_type") or "unstructured").strip()
	operation = requested_operation
	if operation == "auto":
		operation = "update" if order_number and source_document_type == "our_system_order" else "create"
	if operation != "update":
		return operation, order_number, None, []
	errors = []
	if not order_number:
		return operation, None, None, [_('修改订单时必须提供可识别的本系统订单号。')]
	try:
		response = (
			get_sales_order_detail(order_number)
			if draft_type == "sales_order"
			else get_purchase_order_detail_v2(order_number)
		)
		detail = (response or {}).get("data") or {}
	except frappe.DoesNotExistError:
		return operation, order_number, None, [_('未找到订单 {0}，请核对订单号。').format(order_number)]
	meta = detail.get("meta") if isinstance(detail.get("meta"), dict) else {}
	if str(meta.get("company") or "").strip() != company:
		errors.append(_("订单 {0} 不属于当前公司范围。" ).format(order_number))
		return operation, order_number, None, errors
	return operation, order_number, detail, errors


def _existing_order_draft_items(detail: dict) -> list[dict]:
	return [
		{
			"item_query": row.get("item_code"),
			"item_code": row.get("item_code"),
			"item_name": row.get("item_name"),
			"qty": row.get("qty"),
			"uom": row.get("uom"),
			"uom_display": row.get("uom_display"),
			"price": row.get("rate"),
			"reference_price": row.get("rate"),
			"price_source": "existing_order",
			"warehouse": row.get("warehouse"),
			"warehouse_query": row.get("warehouse"),
			"conversion_factor": row.get("conversion_factor") or 1,
			"candidates": [],
			"warnings": [],
		}
		for row in detail.get("items") or []
		if isinstance(row, dict)
	]


def _resolve_draft_retry_request(
	*, scenario: str, user: str, content, company, conversation_id, attachment_ids, retry_run_id,
) -> tuple[object, object, object, object, dict | None]:
	if not retry_run_id:
		return content, company, conversation_id, attachment_ids, None
	retry_context = ai_repository.prepare_failed_run_retry(
		run_id=str(retry_run_id).strip(), user=user,
	)
	if str(retry_context.get("scenario") or "") != scenario:
		frappe.throw(_("失败 Run 的业务场景与当前草稿类型不一致，不能重试。"))
	return (
		retry_context.get("content"),
		retry_context.get("company"),
		retry_context.get("conversation_id"),
		retry_context.get("attachment_ids") or [],
		retry_context,
	)


def _start_draft_generation_run(
	*, scenario: str, prompt_version: str, user: str, content: str,
	conversation_id: str, model_alias: str | None, attachment_ids,
	attachment_refs: list[dict], attachment_payloads: list[dict], retry_context: dict | None,
) -> str:
	user_message = None
	if not retry_context:
		user_message = ai_repository.append_message(
			conversation_id=conversation_id, user=user, role="user", content=content,
			scenario=scenario, attachments=attachment_refs, prompt_version=prompt_version,
		)
	run_id = ai_repository.create_run(
		conversation_id=conversation_id,
		user=user,
		scenario=scenario,
		model_alias=model_alias,
		retry_of_run_id=retry_context.get("source_run_id") if retry_context else None,
	)
	if attachment_payloads and not retry_context:
		resolve_ai_attachments(
			attachment_ids, user=user, conversation_id=conversation_id,
			message_id=user_message["name"], run_id=run_id,
		)
	if retry_context:
		ai_repository.rebind_failed_run_message_for_retry(
			message_id=retry_context["failed_message_id"],
			source_run_id=retry_context["source_run_id"],
			retry_run_id=run_id,
			user=user,
			scenario=scenario,
			prompt_version=prompt_version,
		)
	return run_id


def _save_draft_generation_assistant_message(
	*, retry_context: dict | None, conversation_id: str, user: str, content: str,
	scenario: str, run_id: str, citations: list[dict], prompt_version: str,
) -> None:
	if retry_context:
		ai_repository.complete_retried_run_message(
			run_id=run_id, user=user, content=content, scenario=scenario,
			citations=citations, prompt_version=prompt_version,
		)
		return
	ai_repository.append_message(
		conversation_id=conversation_id, user=user, role="assistant", content=content,
		scenario=scenario, run_id=run_id, citations=citations, prompt_version=prompt_version,
	)


def _fail_draft_generation_run(*, run_id: str, user: str, error: Exception, started: float) -> None:
	frappe.db.rollback()
	ai_repository.fail_run(
		run_id=run_id,
		user=user,
		error=error,
		latency_ms=int((time.perf_counter() - started) * 1000),
	)
	ai_repository.append_failed_run_message(run_id=run_id, user=user)
	frappe.db.commit()


def _bind_context_product_candidates(
	candidate: dict,
	*,
	content: str,
	conversation_state: dict | None,
) -> tuple[dict, list[dict]]:
	"""Bind deictic product mentions in any draft candidate to one server-owned Item reference."""
	bound = dict(candidate or {})
	targets = []
	rows = bound.get("items") if isinstance(bound.get("items"), list) else None
	if rows is None:
		rows = [bound]
		root_candidate = True
	else:
		root_candidate = False
	bound_rows = []
	for row in rows:
		resolved_row = dict(row) if isinstance(row, dict) else {}
		explicit_item_code = str(resolved_row.get("item_code") or "").strip()
		target = None if explicit_item_code else _resolve_conversation_product_target(
			content=content,
			item_query=resolved_row.get("item_query"),
			conversation_state=conversation_state,
		)
		if target:
			resolved_row["item_query"] = target["item_code"]
			resolved_row["_target_source"] = target["source"]
			resolved_row["_target_context_ref"] = target["context_ref"]
			targets.append(target)
		bound_rows.append(resolved_row)
	if root_candidate:
		bound = bound_rows[0]
	else:
		bound["items"] = bound_rows
	return bound, targets


def _bind_context_order_candidate(
	candidate: dict,
	*,
	content: str,
	conversation_state: dict | None,
	draft_type: str,
) -> tuple[dict, dict | None]:
	bound = dict(candidate or {})
	if str(bound.get("order_number") or "").strip():
		return bound, None
	if not ORDER_UPDATE_ACTION_PATTERN.search(str(content or "")):
		return bound, None
	entity_type = "sales_order" if draft_type == "sales_order" else "purchase_order"
	target = _resolve_conversation_order_target(
		content=content,
		order_number=bound.get("order_number"),
		conversation_state=conversation_state,
		allowed_entity_type=entity_type,
	)
	if not target:
		return bound, None
	bound["order_number"] = target["order_number"]
	bound["operation"] = "update"
	bound["_target_order_source"] = target["source"]
	bound["_target_order_context_ref"] = target["context_ref"]
	return bound, target


def _bind_context_business_partner_candidate(
	candidate: dict,
	*,
	content: str,
	conversation_state: dict | None,
	draft_type: str,
) -> tuple[dict, dict | None]:
	bound = dict(candidate or {})
	if draft_type == "sales_order":
		query_field = "customer_query"
		entity_type = "customer"
	else:
		query_field = "supplier_query"
		entity_type = "supplier"
	target = _resolve_conversation_business_partner_target(
		content=content,
		party_query=bound.get(query_field),
		conversation_state=conversation_state,
		allowed_entity_type=entity_type,
	)
	if not target:
		return bound, None
	bound[query_field] = target["party_name"]
	bound["_target_party_source"] = target["source"]
	bound["_target_party_context_ref"] = target["context_ref"]
	return bound, target


def _load_draft_conversation_state(
	*, conversation_id: str, user: str, has_existing_conversation: bool,
) -> dict:
	if not has_existing_conversation:
		return {
			"version": 0,
			"state": {
				"schema_version": CONVERSATION_STATE_SCHEMA_VERSION,
				"active_scenario": "general",
			},
			"status": "empty",
		}
	return ai_repository.get_conversation_state(
		conversation_id=conversation_id, user=user, expire_if_needed=True,
	)


def _draft_entity_state(
	*, entity_type: str, entity_id: str | None, display_name: str | None,
	resolution_status: str, source: str,
) -> dict:
	return {
		"entity_type": entity_type,
		"entity_id": str(entity_id or "").strip() or None,
		"display_name": str(display_name or "").strip() or None,
		"resolution_status": resolution_status,
		"source": source,
		"source_result_set_id": None,
	}


def _build_draft_conversation_state(
	*, previous_state: dict | None, draft_type: str, payload: dict,
	formal_target: dict | None = None,
) -> dict:
	"""Project a validated draft/execution into bounded server-owned entity slots."""
	previous = _conversation_state_for_intent(previous_state)
	next_state = {
		key: value for key, value in previous.items()
		if key in {"product", "order", "report", "active_entities", "last_result_set"}
	}
	next_state.update({
		"schema_version": CONVERSATION_STATE_SCHEMA_VERSION,
		# Draft scenarios must not inherit read-query filters into the next turn.
		"active_scenario": "general",
	})
	active_entities = (
		dict(next_state.get("active_entities"))
		if isinstance(next_state.get("active_entities"), dict)
		else {}
	)
	source = "draft_execution" if formal_target else f"{draft_type}_draft"
	formal_doctype = str((formal_target or {}).get("target_doctype") or "").strip()
	formal_name = str((formal_target or {}).get("target_name") or "").strip() or None

	product_rows = []
	if draft_type == "product_setup":
		item_code = str(payload.get("item_code") or "").strip() or None
		is_existing_item = payload.get("operation") == "update"
		if formal_doctype == "Item" and formal_name:
			item_code = formal_name
			is_existing_item = True
		if item_code and is_existing_item:
			product_rows.append({"item_code": item_code, "item_name": payload.get("item_name")})
	else:
		product_rows.extend(
			row for row in (payload.get("items") or [])
			if isinstance(row, dict) and str(row.get("item_code") or "").strip()
		)
	unique_products = {}
	for row in product_rows:
		item_code = str(row.get("item_code") or "").strip()
		if item_code:
			unique_products.setdefault(item_code, str(row.get("item_name") or "").strip() or None)
	if len(unique_products) == 1:
		item_code, item_name = next(iter(unique_products.items()))
		active_entities["product"] = _draft_entity_state(
			entity_type="product", entity_id=item_code, display_name=item_name,
			resolution_status="resolved", source=source,
		)
		next_state["product"] = {
			"query": item_code, "item_code": item_code, "item_name": item_name,
			"resolution_status": "resolved",
		}
	elif draft_type in {"product_setup", "inventory_adjustment", "sales_order", "purchase_order"}:
		status = "ambiguous" if len(unique_products) > 1 else "not_found"
		active_entities["product"] = _draft_entity_state(
			entity_type="product", entity_id=None, display_name=None,
			resolution_status=status, source=source,
		)
		next_state["product"] = {
			"query": None, "item_code": None, "item_name": None,
			"resolution_status": status,
		}

	if draft_type in {"sales_order", "purchase_order"}:
		entity_type = "sales_order" if draft_type == "sales_order" else "purchase_order"
		expected_doctype = "Sales Order" if draft_type == "sales_order" else "Purchase Order"
		order_number = None
		if formal_doctype == expected_doctype and formal_name:
			order_number = formal_name
		elif payload.get("operation") == "update" and payload.get("source_order_modified"):
			order_number = str(payload.get("order_number") or "").strip() or None
		active_entities["business_document"] = _draft_entity_state(
			entity_type=entity_type,
			entity_id=order_number,
			display_name=order_number,
			resolution_status="resolved" if order_number else "not_found",
			source=source,
		)
		party_field = "customer" if draft_type == "sales_order" else "supplier"
		party_display_field = f"{party_field}_display_name"
		party_name = str(payload.get(party_field) or "").strip() or None
		active_entities["business_partner"] = _draft_entity_state(
			entity_type=party_field,
			entity_id=party_name,
			display_name=payload.get(party_display_field),
			resolution_status="resolved" if party_name else "not_found",
			source=source,
		)

	next_state["active_entities"] = active_entities
	return next_state


def _persist_draft_conversation_state(
	*, conversation_id: str, user: str, state_record: dict, draft_type: str,
	payload: dict, formal_target: dict | None = None,
) -> dict:
	next_state = _build_draft_conversation_state(
		previous_state=state_record.get("state") or {},
		draft_type=draft_type,
		payload=payload,
		formal_target=formal_target,
	)
	result = ai_repository.update_conversation_state(
		conversation_id=conversation_id,
		user=user,
		state=next_state,
		expected_version=cint(state_record.get("version")),
	)
	return {
		"tool": "update_conversation_state",
		"risk_level": "L0_INTERNAL_STATE",
		"mode": "state_updated" if result.get("updated") else "state_update_skipped",
		"previous_version": cint(state_record.get("version")),
		"next_version": result.get("version"),
		"reason": result.get("reason"),
	}


def generate_ai_sales_order_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
	attachment_ids=None,
	retry_run_id: str | None = None,
):
	scenario = "sales_order_draft"
	prompt_version = _resolve_prompt_version(scenario)
	user = _current_user()
	content, company, conversation_id, attachment_ids, retry_context = _resolve_draft_retry_request(
		scenario=scenario, user=user, content=content, company=company,
		conversation_id=conversation_id, attachment_ids=attachment_ids, retry_run_id=retry_run_id,
	)
	attachment_refs, attachment_payloads = resolve_ai_attachments(attachment_ids, user=user)
	model_alias = resolve_ai_selected_model_alias(model_alias)
	if not str(content or "").strip() and attachment_payloads:
		content = _("请根据图片中明确可见的订单信息生成销售订单草稿，缺失字段保持为空。")
	content = _normalize_content(content)
	company = _resolve_company_scope(company, required=True)
	if not (
		frappe.has_permission("Sales Order", ptype="create")
		or frappe.has_permission("Sales Order", ptype="write")
	):
		raise frappe.PermissionError(_("无权创建或修改销售订单草稿。"))
	has_existing_conversation = bool(conversation_id)
	if not conversation_id:
		conversation = ai_repository.create_conversation(user=user, title=content, company=company)
		conversation_id = conversation["name"]
	else:
		conversation = ai_repository.get_conversation(conversation_id=conversation_id, user=user)["conversation"]
		if conversation.get("status") != "active":
			frappe.throw(_("已归档的 AI 会话为只读状态，请新建会话后继续操作。"))
		if conversation.get("company") and conversation.get("company") != company:
			frappe.throw(_("当前公司与会话公司范围不一致，请新建会话。"))
	conversation_state_record = _load_draft_conversation_state(
		conversation_id=conversation_id, user=user,
		has_existing_conversation=has_existing_conversation,
	)
	run_id = _start_draft_generation_run(
		scenario=scenario, prompt_version=prompt_version, user=user, content=content,
		conversation_id=conversation_id, model_alias=model_alias, attachment_ids=attachment_ids,
		attachment_refs=attachment_refs, attachment_payloads=attachment_payloads,
		retry_context=retry_context,
	)
	frappe.db.commit()
	started = time.perf_counter()
	try:
		model_messages = _load_model_messages(conversation_id=conversation_id, user=user)
		result = _call_ai_orchestrator_sales_draft(
			{
				"messages": model_messages, "scenario": scenario, "user": user,
				"company": company, "locale": getattr(frappe.local, "lang", None) or "zh-CN",
				"prompt_version": prompt_version, "conversation_id": conversation_id, "run_id": run_id,
				"model_alias": model_alias,
				"context": {"conversation_state": _conversation_state_for_intent(
					conversation_state_record.get("state") or {},
				)},
			}
		)
		candidate, order_context_target = _bind_context_order_candidate(
			result["draft"], content=content,
			conversation_state=conversation_state_record.get("state") or {},
			draft_type="sales_order",
		)
		candidate, party_context_target = _bind_context_business_partner_candidate(
			candidate, content=content,
			conversation_state=conversation_state_record.get("state") or {},
			draft_type="sales_order",
		)
		candidate, product_context_targets = _bind_context_product_candidates(
			candidate, content=content,
			conversation_state=conversation_state_record.get("state") or {},
		)
		operation, order_number, existing_order, errors = _resolve_order_update_source(
			candidate, draft_type="sales_order", company=company,
		)
		if operation == "create" and not frappe.has_permission("Sales Order", ptype="create"):
			errors.append(_("当前账号无权创建销售订单。"))
		if operation == "update" and not frappe.has_permission("Sales Order", ptype="write"):
			errors.append(_("当前账号无权修改销售订单。"))
		existing_customer = (
			existing_order.get("customer")
			if existing_order and isinstance(existing_order.get("customer"), dict)
			else {}
		)
		customer, customer_candidates = _resolve_sales_draft_customer(candidate.get("customer_query"))
		if operation == "update" and not candidate.get("customer_query") and existing_customer:
			customer = existing_customer
			customer_candidates = []
		existing_meta = (
			existing_order.get("meta")
			if existing_order and isinstance(existing_order.get("meta"), dict)
			else {}
		)
		default_sales_mode = (
			"retail"
			if candidate.get("default_sales_mode") == "retail"
			or (
				candidate.get("default_sales_mode") in (None, "")
				and existing_meta.get("default_sales_mode") == "retail"
			)
			else "wholesale"
		)
		default_warehouse = _resolve_sales_draft_warehouse(candidate.get("warehouse_query"), company)
		extracted_items = [
			_resolve_sales_draft_item(
				row, company=company, default_warehouse=default_warehouse,
				default_sales_mode=default_sales_mode, allow_user_price=True,
			)
			for row in candidate.get("items") or []
		]
		items = extracted_items or (
			_existing_order_draft_items(existing_order) if operation == "update" and existing_order else []
		)
		if not customer:
			errors.append(_("客户无法唯一匹配，请人工选择。"))
		if operation == "create" and not items:
			errors.append(_("草稿没有有效商品明细。"))
		for index, row in enumerate(items, 1):
			if not row.get("item_code") or row.get("qty", 0) <= 0 or not row.get("warehouse"):
				errors.append(_("第 {0} 行需要人工补充商品、数量或仓库。" ).format(index))
		transaction_date = str(
			candidate.get("transaction_date")
			or existing_meta.get("transaction_date")
			or nowdate()
		)
		delivery_date = str(
			candidate.get("delivery_date")
			or existing_meta.get("delivery_date")
			or transaction_date
		)
		try:
			transaction_date = str(getdate(transaction_date))
			delivery_date = str(getdate(delivery_date))
		except Exception:
			errors.append(_("订单日期或交货日期格式不正确。"))
		payload = {
			"source_attachments": attachment_refs,
			"operation": operation,
			"order_number": order_number,
			"target_order_source": (
				order_context_target.get("source") if order_context_target else "explicit_or_model_query"
			),
			"target_order_context_ref": (
				order_context_target.get("context_ref") if order_context_target else None
			),
			"source_order_modified": existing_meta.get("modified") if operation == "update" else None,
			"source_document_type": candidate.get("source_document_type") or "unstructured",
			"update_items_explicit": bool(extracted_items),
			"company": company,
			"customer_query": candidate.get("customer_query"),
			"customer": customer.get("name") if customer else None,
			"customer_display_name": customer.get("display_name") if customer else None,
			"customer_candidates": customer_candidates,
			"transaction_date": transaction_date,
			"delivery_date": delivery_date,
			"default_sales_mode": default_sales_mode,
			"warehouse_query": candidate.get("warehouse_query"),
			"warehouse": default_warehouse,
			"remarks": candidate.get("remarks") if candidate.get("remarks") is not None else existing_meta.get("remarks"),
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
		_save_draft_generation_assistant_message(
			retry_context=retry_context, conversation_id=conversation_id, user=user,
			content=assistant_content, scenario=scenario, run_id=run_id,
			citations=[citation], prompt_version=prompt_version,
		)
		state_tool_call = _persist_draft_conversation_state(
			conversation_id=conversation_id, user=user,
			state_record=conversation_state_record,
			draft_type="sales_order", payload=payload,
		)
		latency_ms = int((time.perf_counter() - started) * 1000)
		ai_repository.complete_run(
			run_id=run_id, user=user, result=result,
			latency_ms=latency_ms,
			tool_calls=[{
				"tool": "build_sales_order_draft", "risk_level": "L2_DRAFT_ONLY",
				"draft_id": draft["name"],
				"conversation_state_version": conversation_state_record.get("version"),
				"target_order_number": order_number,
				"target_order_source": (
					order_context_target.get("source") if order_context_target else "explicit_or_model_query"
				),
				"target_party_source": (
					party_context_target.get("source") if party_context_target else "explicit_or_model_query"
				),
				"target_party_context_ref": (
					party_context_target.get("context_ref") if party_context_target else None
				),
				"context_product_targets": [
					{"item_code": target.get("item_code"), "source": target.get("source"),
						"context_ref": target.get("context_ref")}
					for target in product_context_targets
				],
			}, state_tool_call],
		)
		frappe.db.commit()
		return {
			"status": "success", "message": assistant_content,
			"data": {"conversation": conversation_id, "run_id": run_id, "draft": draft,
				"message": {"role": "assistant", "content": assistant_content, "citations": [citation]},
				**_public_ai_result_details(
					result=result,
					run={"status": "completed", "latency_ms": latency_ms, "first_token_ms": None},
					include_advanced_diagnostics=_can_view_advanced_diagnostics(user),
				)},
		}
	except Exception as error:
		_fail_draft_generation_run(run_id=run_id, user=user, error=error, started=started)
		raise


def generate_ai_purchase_order_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
	attachment_ids=None,
	retry_run_id: str | None = None,
):
	scenario = "purchase_order_draft"
	prompt_version = _resolve_prompt_version(scenario)
	user = _current_user()
	content, company, conversation_id, attachment_ids, retry_context = _resolve_draft_retry_request(
		scenario=scenario, user=user, content=content, company=company,
		conversation_id=conversation_id, attachment_ids=attachment_ids, retry_run_id=retry_run_id,
	)
	attachment_refs, attachment_payloads = resolve_ai_attachments(attachment_ids, user=user)
	model_alias = resolve_ai_selected_model_alias(model_alias)
	if not str(content or "").strip() and attachment_payloads:
		content = _("请根据图片中明确可见的订单信息生成采购订单草稿，缺失字段保持为空。")
	content = _normalize_content(content)
	company = _resolve_company_scope(company, required=True)
	if not (
		frappe.has_permission("Purchase Order", ptype="create")
		or frappe.has_permission("Purchase Order", ptype="write")
	):
		raise frappe.PermissionError(_("无权创建或修改采购订单草稿。"))
	has_existing_conversation = bool(conversation_id)
	if not conversation_id:
		conversation = ai_repository.create_conversation(user=user, title=content, company=company)
		conversation_id = conversation["name"]
	else:
		conversation = ai_repository.get_conversation(conversation_id=conversation_id, user=user)["conversation"]
		if conversation.get("status") != "active":
			frappe.throw(_("已归档的 AI 会话为只读状态，请新建会话后继续操作。"))
		if conversation.get("company") and conversation.get("company") != company:
			frappe.throw(_("当前公司与会话公司范围不一致，请新建会话。"))
	conversation_state_record = _load_draft_conversation_state(
		conversation_id=conversation_id, user=user,
		has_existing_conversation=has_existing_conversation,
	)
	run_id = _start_draft_generation_run(
		scenario=scenario, prompt_version=prompt_version, user=user, content=content,
		conversation_id=conversation_id, model_alias=model_alias, attachment_ids=attachment_ids,
		attachment_refs=attachment_refs, attachment_payloads=attachment_payloads,
		retry_context=retry_context,
	)
	frappe.db.commit()
	started = time.perf_counter()
	try:
		model_messages = _load_model_messages(conversation_id=conversation_id, user=user)
		result = _call_ai_orchestrator_purchase_draft({
			"messages": model_messages, "scenario": scenario, "user": user,
			"company": company, "locale": getattr(frappe.local, "lang", None) or "zh-CN",
			"prompt_version": prompt_version, "conversation_id": conversation_id, "run_id": run_id,
			"model_alias": model_alias,
			"context": {"conversation_state": _conversation_state_for_intent(
				conversation_state_record.get("state") or {},
			)},
		})
		candidate, order_context_target = _bind_context_order_candidate(
			result["draft"], content=content,
			conversation_state=conversation_state_record.get("state") or {},
			draft_type="purchase_order",
		)
		candidate, party_context_target = _bind_context_business_partner_candidate(
			candidate, content=content,
			conversation_state=conversation_state_record.get("state") or {},
			draft_type="purchase_order",
		)
		candidate, product_context_targets = _bind_context_product_candidates(
			candidate, content=content,
			conversation_state=conversation_state_record.get("state") or {},
		)
		operation, order_number, existing_order, errors = _resolve_order_update_source(
			candidate, draft_type="purchase_order", company=company,
		)
		if operation == "create" and not frappe.has_permission("Purchase Order", ptype="create"):
			errors.append(_("当前账号无权创建采购订单。"))
		if operation == "update" and not frappe.has_permission("Purchase Order", ptype="write"):
			errors.append(_("当前账号无权修改采购订单。"))
		existing_supplier = (
			existing_order.get("supplier")
			if existing_order and isinstance(existing_order.get("supplier"), dict)
			else {}
		)
		supplier, supplier_candidates = _resolve_purchase_draft_supplier(candidate.get("supplier_query"))
		if operation == "update" and not candidate.get("supplier_query") and existing_supplier:
			supplier = existing_supplier
			supplier_candidates = []
		default_warehouse = _resolve_sales_draft_warehouse(candidate.get("warehouse_query"), company)
		extracted_items = [
			_resolve_purchase_draft_item(
				row, company=company, default_warehouse=default_warehouse,
				allow_user_price=True,
			)
			for row in candidate.get("items") or []
		]
		items = extracted_items or (
			_existing_order_draft_items(existing_order) if operation == "update" and existing_order else []
		)
		if not supplier:
			errors.append(_("供应商无法唯一匹配，请人工选择。"))
		if operation == "create" and not items:
			errors.append(_("草稿没有有效商品明细。"))
		for index, row in enumerate(items, 1):
			if not row.get("item_code") or row.get("qty", 0) <= 0 or not row.get("warehouse"):
				errors.append(_("第 {0} 行需要人工补充商品、数量或收货仓库。" ).format(index))
		existing_meta = (
			existing_order.get("meta")
			if existing_order and isinstance(existing_order.get("meta"), dict)
			else {}
		)
		transaction_date = str(getdate(
			candidate.get("transaction_date") or existing_meta.get("transaction_date") or nowdate()
		))
		schedule_date = str(getdate(
			candidate.get("schedule_date") or existing_meta.get("schedule_date") or transaction_date
		))
		supplier_name = supplier.get("name") if supplier else None
		currency = str(candidate.get("currency") or "").strip() or None
		if supplier_name and not currency:
			currency = frappe.db.get_value("Supplier", supplier_name, "default_currency") or None
		if not currency:
			currency = frappe.db.get_value("Company", company, "default_currency") or None
		payload = {
			"source_attachments": attachment_refs,
			"operation": operation,
			"order_number": order_number,
			"target_order_source": (
				order_context_target.get("source") if order_context_target else "explicit_or_model_query"
			),
			"target_order_context_ref": (
				order_context_target.get("context_ref") if order_context_target else None
			),
			"source_order_modified": existing_meta.get("modified") if operation == "update" else None,
			"source_document_type": candidate.get("source_document_type") or "unstructured",
			"update_items_explicit": bool(extracted_items),
			"company": company, "supplier_query": candidate.get("supplier_query"),
			"supplier": supplier_name,
			"supplier_display_name": supplier.get("display_name") if supplier else None,
			"supplier_candidates": supplier_candidates, "transaction_date": transaction_date,
			"schedule_date": schedule_date,
			"default_purchase_mode": candidate.get("default_purchase_mode") or "wholesale",
			"warehouse_query": candidate.get("warehouse_query"),
			"warehouse": default_warehouse, "currency": currency,
			"supplier_ref": candidate.get("supplier_ref") if candidate.get("supplier_ref") is not None else existing_meta.get("supplier_ref"),
			"remarks": candidate.get("remarks") if candidate.get("remarks") is not None else existing_meta.get("remarks"),
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
		_save_draft_generation_assistant_message(
			retry_context=retry_context, conversation_id=conversation_id, user=user,
			content=assistant_content, scenario=scenario, run_id=run_id,
			citations=[citation], prompt_version=prompt_version,
		)
		state_tool_call = _persist_draft_conversation_state(
			conversation_id=conversation_id, user=user,
			state_record=conversation_state_record,
			draft_type="purchase_order", payload=payload,
		)
		latency_ms = int((time.perf_counter() - started) * 1000)
		ai_repository.complete_run(
			run_id=run_id, user=user, result=result,
			latency_ms=latency_ms,
			tool_calls=[{
				"tool": "build_purchase_order_draft", "risk_level": "L2_DRAFT_ONLY",
				"draft_id": draft["name"],
				"conversation_state_version": conversation_state_record.get("version"),
				"target_order_number": order_number,
				"target_order_source": (
					order_context_target.get("source") if order_context_target else "explicit_or_model_query"
				),
				"target_party_source": (
					party_context_target.get("source") if party_context_target else "explicit_or_model_query"
				),
				"target_party_context_ref": (
					party_context_target.get("context_ref") if party_context_target else None
				),
				"context_product_targets": [
					{"item_code": target.get("item_code"), "source": target.get("source"),
						"context_ref": target.get("context_ref")}
					for target in product_context_targets
				],
			}, state_tool_call],
		)
		frappe.db.commit()
		return {
			"status": "success", "message": assistant_content,
			"data": {"conversation": conversation_id, "run_id": run_id, "draft": draft,
				"message": {"role": "assistant", "content": assistant_content, "citations": [citation]},
				**_public_ai_result_details(
					result=result,
					run={"status": "completed", "latency_ms": latency_ms, "first_token_ms": None},
					include_advanced_diagnostics=_can_view_advanced_diagnostics(user),
				)},
		}
	except Exception as error:
		_fail_draft_generation_run(run_id=run_id, user=user, error=error, started=started)
		raise


def generate_ai_inventory_adjustment_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
	attachment_ids=None,
	retry_run_id: str | None = None,
):
	scenario = "inventory_adjustment_draft"
	prompt_version = _resolve_prompt_version(scenario)
	user = _current_user()
	content, company, conversation_id, attachment_ids, retry_context = _resolve_draft_retry_request(
		scenario=scenario, user=user, content=content, company=company,
		conversation_id=conversation_id, attachment_ids=attachment_ids, retry_run_id=retry_run_id,
	)
	attachment_refs, attachment_payloads = resolve_ai_attachments(attachment_ids, user=user)
	model_alias = resolve_ai_selected_model_alias(model_alias)
	if not str(content or "").strip() and attachment_payloads:
		content = _("请根据图片中明确可见的信息生成库存调整草稿，缺失字段保持为空。")
	content = _normalize_content(content)
	company = _resolve_company_scope(company, required=True)
	if not frappe.has_permission("Stock Entry", ptype="create"):
		raise frappe.PermissionError(_("无权创建库存调整草稿。"))
	has_existing_conversation = bool(conversation_id)
	if not conversation_id:
		conversation = ai_repository.create_conversation(user=user, title=content, company=company)
		conversation_id = conversation["name"]
	else:
		conversation = ai_repository.get_conversation(conversation_id=conversation_id, user=user)["conversation"]
		if conversation.get("status") != "active":
			frappe.throw(_("已归档的 AI 会话为只读状态，请新建会话后继续操作。"))
		if conversation.get("company") and conversation.get("company") != company:
			frappe.throw(_("当前公司与会话公司范围不一致，请新建会话。"))
	conversation_state_record = _load_draft_conversation_state(
		conversation_id=conversation_id, user=user,
		has_existing_conversation=has_existing_conversation,
	)
	run_id = _start_draft_generation_run(
		scenario=scenario, prompt_version=prompt_version, user=user, content=content,
		conversation_id=conversation_id, model_alias=model_alias, attachment_ids=attachment_ids,
		attachment_refs=attachment_refs, attachment_payloads=attachment_payloads,
		retry_context=retry_context,
	)
	frappe.db.commit()
	started = time.perf_counter()
	try:
		model_messages = _load_model_messages(conversation_id=conversation_id, user=user)
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
				"context": {"conversation_state": _conversation_state_for_intent(
					conversation_state_record.get("state") or {},
				)},
			}
		)
		candidate, product_context_targets = _bind_context_product_candidates(
			result["draft"], content=content,
			conversation_state=conversation_state_record.get("state") or {},
		)
		payload, validation = _build_inventory_adjustment_draft(candidate, company=company)
		payload["source_attachments"] = attachment_refs
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
		_save_draft_generation_assistant_message(
			retry_context=retry_context, conversation_id=conversation_id, user=user,
			content=assistant_content, scenario=scenario, run_id=run_id,
			citations=[citation], prompt_version=prompt_version,
		)
		state_tool_call = _persist_draft_conversation_state(
			conversation_id=conversation_id, user=user,
			state_record=conversation_state_record,
			draft_type="inventory_adjustment", payload=payload,
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
					"conversation_state_version": conversation_state_record.get("version"),
					"target_item_code": (payload.get("items") or [{}])[0].get("item_code"),
					"target_source": (payload.get("items") or [{}])[0].get("target_source"),
					"target_context_ref": (payload.get("items") or [{}])[0].get("target_context_ref"),
					"context_product_targets": [
						{"item_code": target.get("item_code"), "source": target.get("source"),
							"context_ref": target.get("context_ref")}
						for target in product_context_targets
					],
				},
				state_tool_call,
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
				**_public_ai_result_details(
					result=result,
					run={"status": "completed", "latency_ms": latency_ms, "first_token_ms": None},
					include_advanced_diagnostics=_can_view_advanced_diagnostics(user),
				),
			},
		}
	except Exception as error:
		_fail_draft_generation_run(run_id=run_id, user=user, error=error, started=started)
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


def _resolve_existing_product_for_setup(candidate: dict) -> tuple[dict | None, list[dict]]:
	state = candidate.get("_state") if isinstance(candidate.get("_state"), dict) else {}
	state_entity = state.get("entity") if isinstance(state.get("entity"), dict) else {}
	item_code = str(state_entity.get("name") or candidate.get("item_code") or "").strip()
	item_name = str(candidate.get("item_name") or "").strip()
	barcode = str(candidate.get("barcode") or "").strip()
	matches: dict[str, dict] = {}
	if item_code:
		rows = frappe.get_list(
			"Item", filters={"name": item_code}, fields=["name", "item_name", "modified"], limit_page_length=2,
		)
		if len(rows) == 1:
			detail = (get_product_detail_v2(
				item_code=rows[0]["name"], company=candidate.get("company"),
			) or {}).get("data") or {}
			return detail, [dict(rows[0])]
		# An explicit or state-bound item code is authoritative. Never fall back
		# to a same-name item when that code is missing or invalid.
		return None, []
	if item_name:
		for row in frappe.get_list(
			"Item", filters={"item_name": item_name}, fields=["name", "item_name", "modified"], limit_page_length=5,
		):
			matches[str(row.get("name"))] = dict(row)
	if barcode:
		barcode_parent = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")
		if barcode_parent:
			for row in frappe.get_list(
				"Item", filters={"name": barcode_parent},
				fields=["name", "item_name", "modified"], limit_page_length=1,
			):
				matches[str(row.get("name"))] = dict(row)
	rows = list(matches.values())
	if len(rows) == 1:
		detail = (get_product_detail_v2(
			item_code=rows[0]["name"], company=candidate.get("company"),
		) or {}).get("data") or {}
		return detail, rows
	if rows:
		return None, rows
	query = " ".join(
		value for value in (
			item_name,
			str(candidate.get("brand") or candidate.get("brand_query") or "").strip(),
			str(candidate.get("specification") or "").strip(),
		) if value
	).strip()
	if not query:
		return None, []
	resolution = _resolve_item_candidates(
		query, company=candidate.get("company"), context="sales", limit=5,
	)
	return None, [
		{
			"name": row.get("item_code"),
			"item_name": row.get("item_name"),
			"brand": row.get("brand"),
			"specification": row.get("specification"),
			"match_method": resolution.get("match_method"),
		}
		for row in resolution.get("candidates") or []
	]


def _resolve_product_setup_context_target(
	*, content: str, candidate: dict, conversation_state: dict | None,
) -> dict | None:
	"""Resolve a deictic product reference from bounded, server-owned conversation state."""
	operation = str(candidate.get("operation") or "auto").strip().lower()
	if operation == "create" or str(candidate.get("item_code") or "").strip():
		return None
	compact = re.sub(r"\s+", "", str(content or ""))
	if (
		not compact
		or not PRODUCT_CONTEXT_TARGET_PATTERN.search(compact)
		or (operation == "auto" and not PRODUCT_UPDATE_ACTION_PATTERN.search(compact))
	):
		return None
	return _resolve_conversation_product_target(
		content=content, item_query=None, conversation_state=conversation_state,
	)


def _product_price_fact(detail: dict, price_list: str, *, buying: bool = False) -> tuple[float | None, str]:
	price_summary = detail.get("price_summary") if isinstance(detail.get("price_summary"), dict) else {}
	rows = price_summary.get("buying_prices" if buying else "selling_prices") or []
	row = next(
		(value for value in rows if str(value.get("price_list") or "") == price_list),
		None,
	)
	if row:
		return flt(row.get("rate")), f"Item Price/{price_list}"
	if price_list == "Standard Selling" and detail.get("standard_rate") not in (None, "", 0, 0.0):
		return flt(detail.get("standard_rate")), "Item/standard_rate"
	return None, f"Item Price/{price_list}"


def _build_existing_product_baseline(detail: dict, *, company: str) -> tuple[dict, dict, dict]:
	standard_selling_rate, standard_selling_source = _product_price_fact(detail, "Standard Selling")
	wholesale_rate, wholesale_source = _product_price_fact(detail, "Wholesale")
	retail_rate, retail_source = _product_price_fact(detail, "Retail")
	standard_buying_rate, standard_buying_source = _product_price_fact(
		detail, "Standard Buying", buying=True,
	)
	currency = detail.get("currency") or frappe.db.get_value("Company", company, "default_currency") or None
	baseline = {
		"item_name": detail.get("item_name"),
		"image": detail.get("image") or None,
		"barcode": detail.get("barcode") or None,
		"specification": detail.get("specification") or None,
		"item_code": detail.get("item_code"),
		"item_group": detail.get("item_group"),
		"brand": detail.get("brand"),
		"stock_uom": detail.get("stock_uom"),
		"standard_selling_rate": standard_selling_rate,
		"wholesale_rate": wholesale_rate,
		"retail_rate": retail_rate,
		"standard_buying_rate": standard_buying_rate,
		"currency": currency,
		"description": detail.get("description") or None,
	}
	sources = {
		"item_name": "Item/item_name",
		"image": "Item/image",
		"barcode": "Item Barcode/barcode",
		"specification": "Item/specification",
		"item_code": "Item/name",
		"item_group": "Item/item_group",
		"brand": "Item/brand",
		"stock_uom": "Item/stock_uom",
		"standard_selling_rate": standard_selling_source,
		"wholesale_rate": wholesale_source,
		"retail_rate": retail_source,
		"standard_buying_rate": standard_buying_source,
		"currency": "Company/default_currency",
		"description": "Item/description",
	}
	context = {
		"inventory_read_only": True,
		"company_total_qty": detail.get("total_qty"),
		"company_warehouse_stock": detail.get("warehouse_stock_details") or [],
		"stock_uom": detail.get("stock_uom"),
		"stock_uom_display": detail.get("stock_uom_display"),
	}
	return baseline, sources, context


def _initial_product_patch(candidate: dict, normalized: dict, *, operation: str) -> dict:
	if operation == "create":
		return {
			field: normalized.get(field)
			for field in PRODUCT_SETUP_EDITABLE_FIELDS
			if field in normalized and normalized.get(field) not in (None, "")
		}
	patch = {}
	for field in PRODUCT_SETUP_EDITABLE_FIELDS:
		if field == "item_name":
			continue
		if field in {"item_group", "brand", "stock_uom"}:
			explicit = {
				"item_group": candidate.get("item_group") or candidate.get("item_group_query"),
				"brand": candidate.get("brand") or candidate.get("brand_query"),
				"stock_uom": candidate.get("stock_uom"),
			}[field]
			if explicit not in (None, ""):
				patch[field] = normalized.get(field)
		elif candidate.get(field) not in (None, ""):
			patch[field] = normalized.get(field)
	return patch


def _references_prior_product_image(content: str) -> bool:
	compact = re.sub(r"\s+", "", str(content or "")).lower()
	return bool(compact and PRODUCT_IMAGE_REFERENCE_PATTERN.search(compact))


def _requests_product_image_application(content: str) -> bool:
	compact = re.sub(r"\s+", "", str(content or "")).lower()
	if not compact or PRODUCT_IMAGE_NEGATION_PATTERN.search(compact):
		return False
	if not PRODUCT_IMAGE_APPLY_ACTION_PATTERN.search(compact):
		return False
	return bool(
		PRODUCT_IMAGE_TARGET_PATTERN.search(compact)
		or PRODUCT_IMAGE_REFERENCE_PATTERN.search(compact)
	)


def _safe_attachment_ref(attachment: dict) -> dict | None:
	attachment_id = str(attachment.get("attachment_id") or "").strip()
	if not attachment_id:
		return None
	return {
		"attachment_id": attachment_id,
		"filename": attachment.get("filename"),
		"content_type": attachment.get("content_type") or attachment.get("mime_type"),
		"file_size": attachment.get("file_size"),
		"width": attachment.get("width"),
		"height": attachment.get("height"),
		"sha256": attachment.get("sha256"),
		"preview_url": attachment.get("preview_url"),
		"status": attachment.get("status"),
		"retention_until": attachment.get("retention_until"),
	}


def _deduplicate_attachment_refs(refs) -> list[dict]:
	result = []
	seen = set()
	for item in refs or []:
		if not isinstance(item, dict):
			continue
		ref = _safe_attachment_ref(item)
		if not ref or ref["attachment_id"] in seen:
			continue
		seen.add(ref["attachment_id"])
		result.append(ref)
	return result


def _candidate_evidence_attachment_ids(candidate: dict) -> list[str]:
	image_result = []
	result = []
	for evidence in candidate.get("evidence") or []:
		if not isinstance(evidence, dict):
			continue
		attachment_id = str(evidence.get("attachment_id") or "").strip()
		if attachment_id and attachment_id not in result:
			result.append(attachment_id)
			if str(evidence.get("field") or "").strip().lower() == "image":
				image_result.append(attachment_id)
	return image_result or result


def _candidate_requests_product_image_application(candidate: dict) -> bool:
	return any(
		isinstance(evidence, dict)
		and str(evidence.get("field") or "").strip().lower() == "image"
		and str(evidence.get("value") or "").strip().lower() == "use_as_product_image"
		and str(evidence.get("attachment_id") or "").strip()
		for evidence in candidate.get("evidence") or []
	)


def _resolve_product_setup_source_attachments(
	*, candidate: dict, model_messages: list[dict], current_attachment_refs: list[dict], content: str,
) -> list[dict]:
	"""Resolve only attachments that are valid in this conversation's current model window."""
	current_refs = _deduplicate_attachment_refs(current_attachment_refs)
	message_ref_groups = []
	available_refs = []
	for message in model_messages or []:
		if not isinstance(message, dict) or message.get("role") != "user":
			continue
		refs = _deduplicate_attachment_refs(message.get("attachments"))
		if refs:
			message_ref_groups.append(refs)
			available_refs.extend(refs)
	available_refs = _deduplicate_attachment_refs([*available_refs, *current_refs])
	available_by_id = {ref["attachment_id"]: ref for ref in available_refs}
	evidence_refs = [
		available_by_id[attachment_id]
		for attachment_id in _candidate_evidence_attachment_ids(candidate)
		if attachment_id in available_by_id
	]
	if evidence_refs:
		return _deduplicate_attachment_refs(evidence_refs)
	if current_refs:
		return current_refs
	if _references_prior_product_image(content) and message_ref_groups:
		# 商品封面只有一个主图字段；没有精确 evidence 时只回退到最近带图消息的第一张图。
		return message_ref_groups[-1][:1]
	return []


def _prepare_product_setup_image_binding(
	*, candidate: dict, model_messages: list[dict], current_attachment_refs: list[dict],
	content: str, user: str, resolved_operation: str, requested_operation: str,
	existing_matches: list[dict],
) -> tuple[dict, list[dict], str | None, bool, bool]:
	candidate = dict(candidate or {})
	source_attachments = _resolve_product_setup_source_attachments(
		candidate=candidate,
		model_messages=model_messages,
		current_attachment_refs=current_attachment_refs,
		content=content,
	)
	source_attachment_ids = {
		str(item.get("attachment_id") or "").strip()
		for item in source_attachments
		if isinstance(item, dict)
	}
	candidate_image_attachment_ids = {
		str(evidence.get("attachment_id") or "").strip()
		for evidence in candidate.get("evidence") or []
		if isinstance(evidence, dict)
		and str(evidence.get("field") or "").strip().lower() == "image"
		and str(evidence.get("value") or "").strip().lower() == "use_as_product_image"
	}
	apply_source_image = (
		_requests_product_image_application(content)
		or (
			_candidate_requests_product_image_application(candidate)
			and bool(source_attachment_ids & candidate_image_attachment_ids)
		)
	)
	should_stage_default_image = bool(
		source_attachments
		and (
			(
				resolved_operation == "create"
				and (requested_operation == "create" or not existing_matches)
			)
			or (resolved_operation == "update" and apply_source_image)
		)
	)
	default_image_url = None
	if should_stage_default_image:
		default_image_url = stage_attachment_as_item_image(
			attachment_id=source_attachments[0]["attachment_id"], user=user,
		)
	if resolved_operation == "update" and apply_source_image and default_image_url:
		candidate["image"] = default_image_url
	return (
		candidate,
		source_attachments,
		default_image_url,
		should_stage_default_image,
		apply_source_image,
	)


def _build_product_setup_draft(
	candidate: dict, *, company: str, default_image_url: str | None = None,
	source_attachments: list[dict] | None = None,
) -> tuple[dict, dict]:
	candidate = dict(candidate or {})
	candidate["company"] = company
	previous_state = candidate.get("_state") if isinstance(candidate.get("_state"), dict) else {}
	requested_operation = str(
		candidate.get("operation") or previous_state.get("operation") or "auto"
	).strip().lower()
	if requested_operation not in {"auto", "create", "update"}:
		requested_operation = "auto"
	existing_detail, existing_matches = _resolve_existing_product_for_setup(candidate)
	operation = requested_operation
	operation_decision_required = bool(requested_operation == "auto" and existing_matches)
	if operation == "auto":
		operation = "update" if existing_detail else "create"
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
	barcode = str(candidate.get("barcode") or "").strip()[:140] or None
	specification = str(candidate.get("specification") or "").strip()[:500] or None
	image = str(candidate.get("image") or "").strip() or None
	if operation == "create" and not image:
		image = str(default_image_url or "").strip() or None
	errors = []
	warnings = []
	if operation_decision_required:
		errors.append(_("发现疑似相同商品，请明确选择新增商品或完善某个现有商品。"))
	if operation == "update" and not existing_detail:
		errors.append(_("未找到唯一的现有商品，请补充准确商品名称或编码。"))
	elif operation == "create" and existing_detail:
		warnings.append(_("商品 {0} 已存在；已按用户明确的新增选择保留创建草稿，请确认新商品编码。").format(
			existing_detail.get("item_name") or existing_detail.get("item_code")
		))
	elif operation == "create" and existing_matches:
		warnings.append(_("存在疑似相同商品；已按用户明确的新增选择保留创建草稿。"))
	elif operation == "update" and len(existing_matches) > 1:
		errors.append(_("商品信息匹配到多条记录，请使用商品编码明确选择。"))
	if not item_name and operation == "create":
		errors.append(_("请填写商品名称。"))
	if operation == "create" and item_code and frappe.db.exists("Item", item_code):
		errors.append(_("商品编码 {0} 已存在。").format(item_code))
	if item_group_query and not item_group:
		errors.append(_("商品分类无法唯一匹配，请人工选择。"))
	elif operation == "create" and not item_group:
		warnings.append(_("未指定商品分类，正式商品页面将使用后端默认分类。"))
	if brand_query and not brand:
		errors.append(_("品牌无法唯一匹配，请人工选择。"))
	if invalid_currency:
		errors.append(_("币种 {0} 无法识别，请人工选择标准币种代码。" ).format(currency_query))
	if not stock_uom:
		errors.append(_("库存单位无法唯一匹配，请人工选择。"))
	if operation == "update" and opening_qty not in (None, 0, 0.0):
		errors.append(_("完善现有商品时不能把当前库存作为初始库存；请使用库存调整草稿处理库存变化。"))
	if operation == "create" and opening_uom and stock_uom and opening_uom != stock_uom:
		errors.append(_("商品建档草稿首期只支持按库存基准单位初始化库存，请补充单位换算后再创建。"))
	if operation == "create" and opening_qty is not None and opening_qty < 0:
		errors.append(_("初始库存数量不能为负数。"))
	if operation == "create" and opening_qty and not warehouse:
		errors.append(_("填写初始库存时必须选择当前公司的叶子仓库。"))
	if operation == "create" and opening_qty and standard_buying_rate is None:
		errors.append(_("填写初始库存时必须补充成本价（默认采购价）；系统会将其作为首次入库成本，售价不会用于库存计价。"))
	if operation == "create" and opening_qty and not frappe.has_permission("Stock Entry", ptype="create"):
		errors.append(_("当前账号无权创建初始库存入库单。"))
	if operation == "create" and not frappe.has_permission("Item", ptype="create"):
		errors.append(_("当前账号无权创建商品。"))
	if operation == "update" and existing_detail and not frappe.has_permission("Item", ptype="write"):
		errors.append(_("当前账号无权完善现有商品。"))
	if standard_selling_rate is not None and standard_selling_rate < 0:
		errors.append(_("标准售价不能为负数。"))
	if wholesale_rate is not None and wholesale_rate < 0:
		errors.append(_("批发价不能为负数。"))
	if retail_rate is not None and retail_rate < 0:
		errors.append(_("零售价不能为负数。"))
	if standard_buying_rate is not None and standard_buying_rate < 0:
		errors.append(_("成本价（默认采购价）不能为负数。"))
	normalized = {
		"item_name": item_name,
		"image": image,
		"barcode": barcode,
		"specification": specification,
		"item_code": item_code,
		"item_group": item_group,
		"brand": brand,
		"stock_uom": stock_uom,
		"standard_selling_rate": standard_selling_rate,
		"wholesale_rate": wholesale_rate,
		"retail_rate": retail_rate,
		"standard_buying_rate": standard_buying_rate,
		"currency": currency,
		"description": description,
	}
	baseline = {}
	field_sources = {field: "user" for field in PRODUCT_SETUP_EDITABLE_FIELDS}
	inventory_context = {}
	if operation == "update" and existing_detail:
		baseline, field_sources, inventory_context = _build_existing_product_baseline(
			existing_detail, company=company,
		)
		previous_entity = (
			previous_state.get("entity")
			if isinstance(previous_state.get("entity"), dict)
			else {}
		)
		state_matches_target = bool(
			previous_state.get("schema_version") == AI_DRAFT_STATE_SCHEMA_VERSION
			and previous_state.get("operation") == operation
			and str(previous_entity.get("name") or "")
			== str(existing_detail.get("item_code") or "")
		)
		if state_matches_target:
			patch = derive_patch_from_submission(
				baseline=previous_state.get("baseline"),
				previous_patch=previous_state.get("patch"),
				previous_effective=previous_state.get("effective"),
				submitted=normalized,
				fields=PRODUCT_SETUP_EDITABLE_FIELDS,
			)
		else:
			patch = _initial_product_patch(candidate, normalized, operation=operation)
			previous_effective = (
				previous_state.get("effective")
				if isinstance(previous_state.get("effective"), dict)
				else {}
			)
			if normalized.get("image") == previous_effective.get("image"):
				patch.pop("image", None)
	else:
		patch = _initial_product_patch(candidate, normalized, operation=operation)
	price_patch_fields = {
		"standard_selling_rate", "wholesale_rate", "retail_rate", "standard_buying_rate",
	}
	if price_patch_fields.intersection(patch) and not (
		frappe.has_permission("Item Price", ptype="create")
		or frappe.has_permission("Item Price", ptype="write")
	):
		errors.append(_("当前账号无权维护商品价格。"))
	for field in price_patch_fields.intersection(patch):
		if patch.get(field) is None:
			errors.append(_(
				"AI 完善草稿不支持直接删除价格；如需明确零价请输入 0，如需删除价格记录请进入商品模块处理。"
			))
			break
	for field, label in (
		("item_name", _("商品名称")),
		("item_group", _("商品分类")),
		("stock_uom", _("库存基准单位")),
		("currency", _("币种")),
	):
		if field in patch and patch.get(field) in (None, ""):
			errors.append(_("{0} 不能清空。").format(label))
	effective = merge_baseline_patch(baseline, patch)
	if operation == "update" and existing_detail:
		effective["item_code"] = existing_detail.get("item_code")
		effective["item_name"] = patch.get("item_name", baseline.get("item_name"))
	stock_uom = effective.get("stock_uom") or stock_uom
	state = build_draft_state(
		operation=operation,
		entity_doctype="Item",
		entity_name=existing_detail.get("item_code") if existing_detail else None,
		entity_modified=existing_detail.get("modified") if existing_detail else None,
		observed_at=datetime.now(),
		baseline=baseline,
		patch=patch,
		fields={
			field: field_fact(
				patch.get(field, baseline.get(field)),
				source="user" if field in patch else field_sources.get(field, "system"),
			)
			for field in PRODUCT_SETUP_EDITABLE_FIELDS
		},
		source_facts={
			"entity_modified": existing_detail.get("modified") if existing_detail else None,
			"baseline": baseline,
		},
	)
	state["context"] = inventory_context
	payload = {
		"source_attachments": source_attachments or [],
		"operation_decision_required": operation_decision_required,
		"duplicate_candidates": [
			{
				"item_code": row.get("name") or row.get("item_code"),
				"item_name": row.get("item_name"),
				"brand": row.get("brand"),
				"specification": row.get("specification"),
				"match_method": row.get("match_method") or "exact",
			}
			for row in existing_matches
		],
		"company": company,
		"operation": operation,
		"item_name": effective.get("item_name"),
		"image": effective.get("image"),
		"barcode": effective.get("barcode"),
		"specification": effective.get("specification"),
		"item_code": effective.get("item_code") or item_code,
		"item_group_query": item_group_query,
		"item_group": effective.get("item_group"),
		"brand_query": brand_query,
		"brand": effective.get("brand"),
		"stock_uom": stock_uom,
		"stock_uom_display": resolve_uom_display_name(stock_uom),
		"uom_candidates": uom_candidates,
		"warehouse_query": warehouse_query if operation == "create" else None,
		"warehouse": warehouse if operation == "create" else None,
		"opening_qty": opening_qty if operation == "create" else None,
		"opening_uom": opening_uom or stock_uom,
		"opening_uom_display": resolve_uom_display_name(opening_uom or stock_uom),
		"standard_selling_rate": effective.get("standard_selling_rate"),
		"wholesale_rate": effective.get("wholesale_rate"),
		"retail_rate": effective.get("retail_rate"),
		"standard_buying_rate": effective.get("standard_buying_rate"),
		"currency": effective.get("currency") or currency,
		"description": effective.get("description"),
		"_state": state,
	}
	if operation == "update" and existing_detail and not patch:
		errors.append(_("尚未修改现有商品字段；请填写需要完善的资料。"))
	return payload, {"ready_for_handoff": not errors, "errors": errors, "warnings": warnings}


def generate_ai_product_setup_draft_v1(
	content: str,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
	attachment_ids=None,
	retry_run_id: str | None = None,
):
	scenario = "product_setup_draft"
	prompt_version = _resolve_prompt_version(scenario)
	user = _current_user()
	content, company, conversation_id, attachment_ids, retry_context = _resolve_draft_retry_request(
		scenario=scenario, user=user, content=content, company=company,
		conversation_id=conversation_id, attachment_ids=attachment_ids, retry_run_id=retry_run_id,
	)
	attachment_refs, attachment_payloads = resolve_ai_attachments(attachment_ids, user=user)
	model_alias = resolve_ai_selected_model_alias(model_alias)
	if not str(content or "").strip() and attachment_payloads:
		content = _("请根据图片中明确可见的商品信息创建或完善商品草稿，缺失字段保持为空。")
	content = _normalize_content(content)
	company = _resolve_company_scope(company, required=True)
	if not (
		frappe.has_permission("Item", ptype="create")
		or frappe.has_permission("Item", ptype="write")
	):
		raise frappe.PermissionError(_("无权创建或完善商品草稿。"))
	has_existing_conversation = bool(conversation_id)
	if not conversation_id:
		conversation = ai_repository.create_conversation(user=user, title=content, company=company)
		conversation_id = conversation["name"]
	else:
		conversation = ai_repository.get_conversation(conversation_id=conversation_id, user=user)["conversation"]
		if conversation.get("status") != "active":
			frappe.throw(_("已归档的 AI 会话为只读状态，请新建会话后继续操作。"))
		if conversation.get("company") and conversation.get("company") != company:
			frappe.throw(_("当前公司与会话公司范围不一致，请新建会话。"))
	conversation_state_record = _load_draft_conversation_state(
		conversation_id=conversation_id, user=user,
		has_existing_conversation=has_existing_conversation,
	)
	run_id = _start_draft_generation_run(
		scenario=scenario, prompt_version=prompt_version, user=user, content=content,
		conversation_id=conversation_id, model_alias=model_alias, attachment_ids=attachment_ids,
		attachment_refs=attachment_refs, attachment_payloads=attachment_payloads,
		retry_context=retry_context,
	)
	frappe.db.commit()
	started = time.perf_counter()
	try:
		model_messages = _load_model_messages(conversation_id=conversation_id, user=user)
		result = _call_ai_orchestrator_product_setup_draft({
			"messages": model_messages, "scenario": scenario, "user": user,
			"company": company, "locale": getattr(frappe.local, "lang", None) or "zh-CN",
			"prompt_version": prompt_version, "conversation_id": conversation_id, "run_id": run_id,
			"model_alias": model_alias,
			"context": {"conversation_state": _conversation_state_for_intent(
				conversation_state_record.get("state") or {},
			)},
		})
		candidate = dict(result["draft"] or {})
		candidate["company"] = company
		context_target = _resolve_product_setup_context_target(
			content=content,
			candidate=candidate,
			conversation_state=conversation_state_record.get("state") or {},
		)
		if context_target:
			candidate["item_code"] = context_target["item_code"]
			candidate["operation"] = "update"
		existing_detail, existing_matches = _resolve_existing_product_for_setup(candidate)
		requested_operation = str(candidate.get("operation") or "auto").strip().lower()
		resolved_operation = (
			"update" if requested_operation == "auto" and existing_detail
			else "create" if requested_operation == "auto"
			else requested_operation
		)
		(
			candidate,
			source_attachments,
			default_image_url,
			should_stage_default_image,
			apply_source_image,
		) = _prepare_product_setup_image_binding(
			candidate=candidate,
			model_messages=model_messages,
			current_attachment_refs=attachment_refs,
			content=content,
			user=user,
			resolved_operation=resolved_operation,
			requested_operation=requested_operation,
			existing_matches=existing_matches,
		)
		payload, validation = _build_product_setup_draft(
			candidate,
			company=company,
			default_image_url=default_image_url,
			source_attachments=source_attachments,
		)
		payload["target_source"] = context_target.get("source") if context_target else "explicit_or_model_query"
		payload["target_context_ref"] = context_target.get("context_ref") if context_target else None
		if should_stage_default_image and not default_image_url:
			message = _("来源图片不符合商品封面要求，草稿未自动设置封面。")
			if apply_source_image:
				validation["errors"].append(message)
				validation["ready_for_handoff"] = False
			else:
				validation["warnings"].append(message)
		elif apply_source_image and not source_attachments:
			validation["errors"].append(_(
				"未在当前有效会话上下文中找到用户指定的图片，请重新上传或明确选择图片。"
			))
			validation["ready_for_handoff"] = False
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
		_save_draft_generation_assistant_message(
			retry_context=retry_context, conversation_id=conversation_id, user=user,
			content=assistant_content, scenario=scenario, run_id=run_id,
			citations=[citation], prompt_version=prompt_version,
		)
		state_tool_call = _persist_draft_conversation_state(
			conversation_id=conversation_id, user=user,
			state_record=conversation_state_record,
			draft_type="product_setup", payload=payload,
		)
		latency_ms = int((time.perf_counter() - started) * 1000)
		ai_repository.complete_run(
			run_id=run_id, user=user, result=result, latency_ms=latency_ms,
			tool_calls=[{
				"tool": "build_product_setup_draft", "risk_level": "L2_DRAFT_ONLY",
				"draft_id": draft["name"],
				"target_item_code": payload.get("item_code"),
				"target_source": context_target.get("source") if context_target else "model_or_user",
				"target_context_ref": context_target.get("context_ref") if context_target else None,
				"conversation_state_version": conversation_state_record.get("version"),
			}, state_tool_call],
		)
		frappe.db.commit()
		return {
			"status": "success", "message": assistant_content,
			"data": {
				"conversation": conversation_id, "run_id": run_id, "draft": draft,
				"message": {"role": "assistant", "content": assistant_content, "citations": [citation]},
				**_public_ai_result_details(
					result=result,
					run={"status": "completed", "latency_ms": latency_ms, "first_token_ms": None},
					include_advanced_diagnostics=_can_view_advanced_diagnostics(user),
				),
			},
		}
	except Exception as error:
		_fail_draft_generation_run(run_id=run_id, user=user, error=error, started=started)
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


def _order_draft_items_signature(items) -> tuple:
	result = []
	for row in items or []:
		if not isinstance(row, dict):
			continue
		qty = None if row.get("qty") in (None, "") else flt(row.get("qty"))
		price = None if row.get("price") in (None, "") else flt(row.get("price"))
		result.append((
			str(row.get("item_code") or row.get("item_query") or "").strip(),
			qty,
			str(row.get("uom") or "").strip(),
			price,
			str(row.get("warehouse") or row.get("warehouse_query") or "").strip(),
		))
	return tuple(result)


def _update_ai_draft_once(
	draft_id: str, payload, *, expected_version: int, change_source: str = "user_edit",
):
	user = _current_user()
	draft = ai_repository.get_draft(draft_id=draft_id, user=user)
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	if not isinstance(payload, dict):
		frappe.throw(_("草稿 payload 格式不正确。"))
	original_payload = draft.get("payload") if isinstance(draft.get("payload"), dict) else {}

	def finish(updated: dict, *, message: str) -> dict:
		conversation_id = str(draft.get("conversation") or "").strip()
		if conversation_id:
			try:
				conversation = ai_repository.get_conversation(
					conversation_id=conversation_id, user=user,
				)["conversation"]
				if conversation.get("status") == "active":
					state_record = ai_repository.get_conversation_state(
						conversation_id=conversation_id, user=user, expire_if_needed=True,
					)
					_persist_draft_conversation_state(
						conversation_id=conversation_id,
						user=user,
						state_record=state_record,
						draft_type=draft["draft_type"],
						payload=updated.get("payload") or {},
					)
			except Exception:
				# Draft persistence is authoritative.  Context projection is a bounded
				# continuity optimization and must not turn a valid user edit into a failure.
				frappe.log_error(frappe.get_traceback(), _("AI 草稿编辑后的会话状态同步失败"))
		return {"status": "success", "message": message, "data": updated}

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
		return finish(updated, message=_("AI 库存调整草稿已更新并按实时库存重新校验。"))
	if draft["draft_type"] == "product_setup":
		source_attachments = (
			payload.get("source_attachments")
			if isinstance(payload.get("source_attachments"), list)
			else original_payload.get("source_attachments") or []
		)
		requested_operation = str(payload.get("operation") or "auto").strip().lower()
		default_image_url = None
		if requested_operation == "create" and not str(payload.get("image") or "").strip():
			first_attachment = source_attachments[0] if source_attachments else {}
			attachment_id = str(first_attachment.get("attachment_id") or "").strip()
			if attachment_id:
				default_image_url = stage_attachment_as_item_image(
					attachment_id=attachment_id, user=user,
				)
		next_payload, validation = _build_product_setup_draft(
			payload,
			company=draft["company"],
			default_image_url=default_image_url,
			source_attachments=source_attachments,
		)
		updated = ai_repository.update_draft(
			draft_id=draft_id,
			user=user,
			payload=next_payload,
			validation=validation,
			expected_version=expected_version,
			change_source=change_source,
		)
		return finish(updated, message=_("AI 商品建档草稿已更新并重新校验。"))
	if draft["draft_type"] == "purchase_order":
		company = draft["company"]
		items_changed = _order_draft_items_signature(original_payload.get("items")) != (
			_order_draft_items_signature(payload.get("items"))
		)
		supplier_query = payload.get("supplier") or payload.get("supplier_query")
		supplier, supplier_candidates = _resolve_purchase_draft_supplier(supplier_query)
		warehouse_query = payload.get("warehouse") or payload.get("warehouse_query")
		default_warehouse = _resolve_sales_draft_warehouse(warehouse_query, company)
		items = [
			_resolve_purchase_draft_item(
				{"item_query": row.get("item_code") or row.get("item_query"), "qty": row.get("qty"),
				 "uom": row.get("uom"), "price": row.get("price"),
				 "warehouse_query": row.get("warehouse") or row.get("warehouse_query") or default_warehouse,
				 "_state": row.get("_state")},
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
			"source_attachments": payload.get("source_attachments") or original_payload.get("source_attachments") or [],
			"operation": payload.get("operation") or original_payload.get("operation") or "create",
			"order_number": payload.get("order_number") or original_payload.get("order_number"),
			"source_order_modified": original_payload.get("source_order_modified"),
			"source_document_type": payload.get("source_document_type") or original_payload.get("source_document_type") or "unstructured",
			"update_items_explicit": bool(
				(payload.get("operation") or original_payload.get("operation")) == "update"
				and (original_payload.get("update_items_explicit") or items_changed)
			),
			"company": company, "supplier_query": supplier_query, "supplier": supplier_name,
			"supplier_display_name": supplier.get("display_name") if supplier else None,
			"supplier_candidates": supplier_candidates,
			"transaction_date": str(getdate(payload.get("transaction_date") or nowdate())),
			"schedule_date": str(getdate(payload.get("schedule_date") or payload.get("transaction_date") or nowdate())),
			"default_purchase_mode": "retail" if payload.get("default_purchase_mode") == "retail" else "wholesale",
			"warehouse_query": warehouse_query, "warehouse": default_warehouse,
			"currency": currency,
			"supplier_ref": str(payload.get("supplier_ref") or "")[:140] or None,
			"remarks": str(payload.get("remarks") or "")[:1000] or None, "items": items,
		}
		validation = {"ready_for_handoff": not errors, "errors": errors,
			"warnings": [warning for row in items for warning in row.get("warnings") or []]}
		updated = ai_repository.update_draft(
			draft_id=draft_id, user=user, payload=next_payload, validation=validation,
			expected_version=expected_version, change_source=change_source,
		)
		return finish(updated, message=_("AI 采购草稿已更新并重新校验。"))
	if draft["draft_type"] != "sales_order":
		frappe.throw(_("不支持的 AI 草稿类型。"))
	company = draft["company"]
	items_changed = _order_draft_items_signature(original_payload.get("items")) != (
		_order_draft_items_signature(payload.get("items"))
	)
	customer_query = payload.get("customer") or payload.get("customer_query")
	customer, customer_candidates = _resolve_sales_draft_customer(customer_query)
	warehouse_query = payload.get("warehouse") or payload.get("warehouse_query")
	default_warehouse = _resolve_sales_draft_warehouse(warehouse_query, company)
	default_sales_mode = "retail" if payload.get("default_sales_mode") == "retail" else "wholesale"
	items = [
		_resolve_sales_draft_item(
			{
				"item_query": row.get("item_code") or row.get("item_query"),
				"qty": row.get("qty"), "uom": row.get("uom"), "price": row.get("price"),
				"warehouse_query": row.get("warehouse") or row.get("warehouse_query") or default_warehouse,
				"_state": row.get("_state"),
			},
			company=company, default_warehouse=default_warehouse,
			default_sales_mode=default_sales_mode,
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
		"source_attachments": payload.get("source_attachments") or original_payload.get("source_attachments") or [],
		"operation": payload.get("operation") or original_payload.get("operation") or "create",
		"order_number": payload.get("order_number") or original_payload.get("order_number"),
		"source_order_modified": original_payload.get("source_order_modified"),
		"source_document_type": payload.get("source_document_type") or original_payload.get("source_document_type") or "unstructured",
		"update_items_explicit": bool(
			(payload.get("operation") or original_payload.get("operation")) == "update"
			and (original_payload.get("update_items_explicit") or items_changed)
		),
		"company": company, "customer_query": customer_query,
		"customer": customer.get("name") if customer else None,
		"customer_display_name": customer.get("display_name") if customer else None,
		"customer_candidates": customer_candidates, "transaction_date": transaction_date,
		"delivery_date": delivery_date,
		"default_sales_mode": default_sales_mode,
		"warehouse_query": warehouse_query, "warehouse": default_warehouse,
		"remarks": str(payload.get("remarks") or "")[:1000] or None,
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
	return finish(updated, message=_("AI 草稿已更新并重新校验。"))


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
		"image",
		"barcode",
		"specification",
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
			"image": payload.get("image"),
			"barcode": payload.get("barcode"),
			"specification": payload.get("specification"),
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
			"operation": payload.get("operation"), "order_number": payload.get("order_number"),
			"company": payload.get("company"), "supplier": payload.get("supplier"),
			"transaction_date": payload.get("transaction_date"), "schedule_date": payload.get("schedule_date"),
			"default_purchase_mode": payload.get("default_purchase_mode"), "warehouse": payload.get("warehouse"),
			"currency": payload.get("currency"), "supplier_ref": payload.get("supplier_ref"),
			"remarks": payload.get("remarks"),
			"items": [{key: row.get(key) for key in ("item_code", "item_name", "qty", "uom", "uom_display", "stock_uom", "stock_uom_display", "price", "warehouse", "conversion_factor")} for row in payload.get("items") or []],
		}
	else:
		handoff_payload = {
			"operation": payload.get("operation"), "order_number": payload.get("order_number"),
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
		state = payload.get("_state") if isinstance(payload.get("_state"), dict) else {}
		operation = str(payload.get("operation") or state.get("operation") or "create")
		if operation == "update":
			entity = state.get("entity") if isinstance(state.get("entity"), dict) else {}
			item_code = str(entity.get("name") or payload.get("item_code") or "").strip()
			patch = state.get("patch") if isinstance(state.get("patch"), dict) else {}
			update_kwargs = {}
			for field in (
				"item_name", "image", "barcode", "specification", "item_group",
				"brand", "stock_uom", "description",
			):
				if field in patch:
					update_kwargs[field] = (
						"" if field in {
							"brand", "description", "image", "barcode", "specification",
						} and patch.get(field) is None
						else patch.get(field)
					)
			if "currency" in patch:
				update_kwargs["currency"] = patch.get("currency")
			if "standard_selling_rate" in patch:
				update_kwargs["standard_rate"] = patch.get("standard_selling_rate")
			selling_prices = []
			for price_list, field in (("Wholesale", "wholesale_rate"), ("Retail", "retail_rate")):
				if field in patch:
					selling_prices.append({
						"price_list": price_list,
						"rate": patch.get(field),
						"currency": payload.get("currency"),
					})
			if selling_prices:
				update_kwargs["selling_prices"] = selling_prices
			if "standard_buying_rate" in patch:
				update_kwargs["buying_prices"] = [{
					"price_list": "Standard Buying",
					"rate": patch.get("standard_buying_rate"),
					"currency": payload.get("currency"),
				}]
			result = update_product_v2(
				item_code=item_code,
				company=payload.get("company"),
				request_id=request_id,
				**update_kwargs,
			)
			return {"target_doctype": "Item", "target_name": item_code, "result": result}
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
			**({"image": payload.get("image")} if payload.get("image") else {}),
			**({"barcode": payload.get("barcode")} if payload.get("barcode") else {}),
			**({"specification": payload.get("specification")} if payload.get("specification") else {}),
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
		if payload.get("operation") == "update":
			order_number = str(payload.get("order_number") or "").strip()
			header_result = update_purchase_order_v2(
				order_name=order_number,
				transaction_date=payload.get("transaction_date"),
				schedule_date=payload.get("schedule_date"),
				supplier_ref=payload.get("supplier_ref"),
				remarks=payload.get("remarks"),
				expected_modified=payload.get("source_order_modified"),
				request_id=request_id,
			)
			result = header_result
			if payload.get("update_items_explicit"):
				header_modified = (header_result.get("meta") or {}).get("modified")
				result = update_purchase_order_items_v2(
					order_name=order_number,
					items=items,
					company=payload.get("company"),
					schedule_date=payload.get("schedule_date"),
					default_warehouse=payload.get("warehouse"),
					expected_modified=header_modified,
					request_id=request_id,
				)
			target_name = str(
				result.get("purchase_order") or header_result.get("purchase_order") or order_number
			)
			return {"target_doctype": "Purchase Order", "target_name": target_name, "result": result}
		result = create_purchase_order(
			supplier=payload.get("supplier"), items=items, company=payload.get("company"),
			transaction_date=payload.get("transaction_date"), schedule_date=payload.get("schedule_date"),
			default_warehouse=payload.get("warehouse"), currency=payload.get("currency"),
			supplier_ref=payload.get("supplier_ref"), remarks=payload.get("remarks"), request_id=request_id,
		)
		target_name = str(result.get("purchase_order") or "")
		return {"target_doctype": "Purchase Order", "target_name": target_name, "result": result}
	if draft_type == "sales_order":
		if payload.get("operation") == "update":
			order_number = str(payload.get("order_number") or "").strip()
			header_result = update_order_v2(
				order_name=order_number,
				transaction_date=payload.get("transaction_date"),
				delivery_date=payload.get("delivery_date"),
				default_sales_mode=payload.get("default_sales_mode"),
				remarks=payload.get("remarks"),
				expected_modified=payload.get("source_order_modified"),
				request_id=request_id,
			)
			result = header_result
			if payload.get("update_items_explicit"):
				header_modified = (header_result.get("meta") or {}).get("modified")
				result = update_order_items_v2(
					order_name=order_number,
					items=items,
					company=payload.get("company"),
					delivery_date=payload.get("delivery_date"),
					default_warehouse=payload.get("warehouse"),
					expected_modified=header_modified,
					request_id=request_id,
				)
			target_name = str(result.get("order") or header_result.get("order") or order_number)
			return {"target_doctype": "Sales Order", "target_name": target_name, "result": result}
		result = create_order_v2(
			customer=payload.get("customer"), items=items, immediate=False, company=payload.get("company"),
			transaction_date=payload.get("transaction_date"), delivery_date=payload.get("delivery_date"),
			default_warehouse=payload.get("warehouse"), default_sales_mode=payload.get("default_sales_mode"),
			remarks=payload.get("remarks"), request_id=request_id,
		)
		target_name = str(result.get("order") or "")
		return {"target_doctype": "Sales Order", "target_name": target_name, "result": result}
	frappe.throw(_("当前草稿类型不支持在 AI 工作台执行。"))


def _draft_source_hashes(payload: dict) -> list[str]:
	hashes = []
	if payload.get("source_order_modified"):
		hashes.append(f"order:{payload['source_order_modified']}")
	state = payload.get("_state") if isinstance(payload.get("_state"), dict) else {}
	if state.get("source_hash"):
		hashes.append(str(state["source_hash"]))
	for row in payload.get("items") or []:
		if not isinstance(row, dict):
			continue
		row_state = row.get("_state") if isinstance(row.get("_state"), dict) else {}
		if row_state.get("source_hash"):
			hashes.append(str(row_state["source_hash"]))
	return hashes


def _rebuild_order_draft_before_execution(draft: dict) -> tuple[dict, dict]:
	payload = draft.get("payload") or {}
	company = draft.get("company")
	draft_type = draft.get("draft_type")
	warehouse_query = payload.get("warehouse") or payload.get("warehouse_query")
	default_warehouse = _resolve_sales_draft_warehouse(warehouse_query, company)
	source_order_modified = payload.get("source_order_modified")
	current_order_modified = None
	order_source_errors = []
	if payload.get("operation") == "update":
		order_number = str(payload.get("order_number") or "").strip()
		try:
			response = (
				get_sales_order_detail(order_number)
				if draft_type == "sales_order"
				else get_purchase_order_detail_v2(order_number)
			)
			detail = (response or {}).get("data") or {}
			meta = detail.get("meta") if isinstance(detail.get("meta"), dict) else {}
			current_order_modified = meta.get("modified")
			if str(meta.get("company") or "").strip() != str(company or "").strip():
				order_source_errors.append(_("来源订单不属于当前公司范围。"))
		except frappe.DoesNotExistError:
			order_source_errors.append(_("来源订单已不存在，不能继续执行修改草稿。"))
		if source_order_modified and current_order_modified and (
			str(source_order_modified) != str(current_order_modified)
		):
			order_source_errors.append(_("来源订单已被其他用户修改，请重新生成修改草稿。"))
	if draft_type == "purchase_order":
		supplier_query = payload.get("supplier") or payload.get("supplier_query")
		supplier, supplier_candidates = _resolve_purchase_draft_supplier(supplier_query)
		items = [
			_resolve_purchase_draft_item(
				{
					"item_query": row.get("item_code") or row.get("item_query"),
					"qty": row.get("qty"),
					"uom": row.get("uom"),
					"price": row.get("price"),
					"warehouse_query": row.get("warehouse") or row.get("warehouse_query") or default_warehouse,
					"_state": row.get("_state"),
				},
				company=company,
				default_warehouse=default_warehouse,
				allow_user_price=True,
			)
			for row in payload.get("items") or []
			if isinstance(row, dict)
		]
		errors = list(order_source_errors)
		if not supplier:
			errors.append(_("供应商当前无法唯一匹配。"))
		next_payload = {
			**payload,
			"source_order_modified": source_order_modified or current_order_modified,
			"supplier": supplier.get("name") if supplier else None,
			"supplier_display_name": supplier.get("display_name") if supplier else None,
			"supplier_candidates": supplier_candidates,
			"warehouse_query": warehouse_query, "warehouse": default_warehouse,
			"items": items,
		}
	else:
		customer_query = payload.get("customer") or payload.get("customer_query")
		customer, customer_candidates = _resolve_sales_draft_customer(customer_query)
		default_sales_mode = "retail" if payload.get("default_sales_mode") == "retail" else "wholesale"
		items = [
			_resolve_sales_draft_item(
				{
					"item_query": row.get("item_code") or row.get("item_query"),
					"qty": row.get("qty"),
					"uom": row.get("uom"),
					"price": row.get("price"),
					"warehouse_query": row.get("warehouse") or row.get("warehouse_query") or default_warehouse,
					"_state": row.get("_state"),
				},
				company=company,
				default_warehouse=default_warehouse,
				default_sales_mode=default_sales_mode,
				allow_user_price=True,
			)
			for row in payload.get("items") or []
			if isinstance(row, dict)
		]
		errors = list(order_source_errors)
		if not customer:
			errors.append(_("客户当前无法唯一匹配。"))
		next_payload = {
			**payload,
			"source_order_modified": source_order_modified or current_order_modified,
			"customer": customer.get("name") if customer else None,
			"customer_display_name": customer.get("display_name") if customer else None,
			"customer_candidates": customer_candidates,
			"warehouse_query": warehouse_query, "warehouse": default_warehouse,
			"items": items,
		}
	for index, row in enumerate(items, 1):
		if not row.get("item_code") or flt(row.get("qty")) <= 0 or not row.get("warehouse"):
			errors.append(_("第 {0} 行当前无法通过商品、数量或仓库校验。").format(index))
	return next_payload, {
		"ready_for_handoff": not errors,
		"errors": errors,
		"warnings": [warning for row in items for warning in row.get("warnings") or []],
	}


def _refresh_ai_draft_before_execution(*, draft: dict, user: str) -> dict:
	previous_payload = draft.get("payload") or {}
	if draft.get("draft_type") == "product_setup":
		next_payload, validation = _build_product_setup_draft(
			previous_payload,
			company=draft.get("company"),
		)
	elif draft.get("draft_type") == "inventory_adjustment":
		next_payload, validation = _build_inventory_adjustment_draft(
			previous_payload,
			company=draft.get("company"),
		)
	elif draft.get("draft_type") in {"sales_order", "purchase_order"}:
		next_payload, validation = _rebuild_order_draft_before_execution(draft)
	else:
		return draft
	previous_hashes = _draft_source_hashes(previous_payload)
	next_hashes = _draft_source_hashes(next_payload)
	if not previous_hashes or previous_hashes != next_hashes:
		ai_repository.update_draft(
			draft_id=draft["name"],
			user=user,
			payload=next_payload,
			validation=validation,
			expected_version=cint(draft["version"]),
			change_source="system_refresh_before_execute",
		)
		frappe.db.commit()
		raise AiDraftVersionConflictError(
			_("业务主数据、价格、单位换算或实时库存发生变化，草稿已刷新；请检查新版本后重新确认。")
		)
	if not validation.get("ready_for_handoff"):
		frappe.throw(_("草稿按当前业务数据重新校验后已不可执行，请先修正校验问题。"))
	return {**draft, "payload": next_payload, "validation": validation}


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
			draft = _refresh_ai_draft_before_execution(draft=draft, user=user)
			try:
				execution_result = _execute_ai_draft_payload(draft, request_id=resolved_request_id)
				if not execution_result.get("target_name"):
					frappe.throw(_("正式业务操作未返回目标业务对象。"))
				updated = ai_repository.mark_draft_executed(
					draft_id=draft_id, user=user, request_id=resolved_request_id,
					target_doctype=execution_result["target_doctype"],
					target_name=execution_result["target_name"], result=execution_result["result"],
				)
				state_record = ai_repository.get_conversation_state(
					conversation_id=draft["conversation"], user=user, expire_if_needed=False,
				)
				state_tool_call = _persist_draft_conversation_state(
					conversation_id=draft["conversation"], user=user,
					state_record=state_record,
					draft_type=draft["draft_type"], payload=draft.get("payload") or {},
					formal_target=execution_result,
				)
				_record_ai_draft_execution_audit(
					user=user, draft=draft, action="execute_ai_draft_succeeded",
					request_id=resolved_request_id,
					result={
						"status": "succeeded", **execution_result,
						"conversation_state": state_tool_call,
					},
				)
				return {
					"status": "success", "message": _("AI 草稿已由当前用户确认并执行。"),
					"data": {
						"draft": updated, "execution": updated["execution"], "replayed": False,
						"conversation_state": state_tool_call,
					},
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


def _working_state_date_fields(dsl: dict) -> dict:
	date_range = str(dsl.get("date_range") or "all")
	allowed_presets = {"all", "today", "this_week", "last_month", "this_month", "last_30_days"}
	date_preset = date_range if date_range in allowed_presets else "custom" if dsl.get("date_from") and dsl.get("date_to") else "all"
	return {
		"date_preset": date_preset,
		"date_from": dsl.get("date_from") if date_preset == "custom" else None,
		"date_to": dsl.get("date_to") if date_preset == "custom" else None,
	}


def _compact_last_result_set(tool_context: dict | None, citations: list[dict]) -> dict | None:
	if not isinstance(tool_context, dict):
		return None
	tool = str(tool_context.get("tool") or "")
	if tool == "query_business_documents":
		result_set = tool_context.get("result_set") or {}
		result_citation = next(
			(citation for citation in citations if citation.get("type") == "business_result_set"),
			{},
		)
		entity_ids = [
			str(citation.get("id") or "")
			for citation in citations
			if citation.get("type") in {"sales_order", "sales_invoice", "purchase_order", "purchase_invoice"}
			and citation.get("id")
		]
		entity_refs = [
			{
				"entity_type": str(citation.get("type") or ""),
				"entity_id": str(citation.get("id") or ""),
				"display_name": str(citation.get("label") or "").strip() or None,
			}
			for citation in citations
			if citation.get("type") in {
				"sales_order", "sales_invoice", "purchase_order", "purchase_invoice",
			}
			and citation.get("id")
		]
		return {
			"type": "business_documents",
			"id": result_citation.get("id"),
			"entity_ids": entity_ids[:20],
			"entity_refs": entity_refs[:20],
			"scope": dict(result_set.get("scope") or {}),
		}
	if tool == "search_products":
		query_resolution = tool_context.get("query_resolution") or {}
		if query_resolution.get("status") == "unresolved":
			return None
		products = tool_context.get("products") or []
		return {
			"type": "products",
			"id": hashlib.sha256(
				json.dumps(
					[row.get("item_code") for row in products if row.get("item_code")],
					sort_keys=True,
				).encode("utf-8")
			).hexdigest()[:24],
			"entity_ids": [row.get("item_code") for row in products if row.get("item_code")][:20],
			"entity_refs": [
				{
					"entity_type": "product",
					"entity_id": row.get("item_code"),
					"display_name": row.get("item_name"),
				}
				for row in products if row.get("item_code")
			][:20],
			"scope": {"company": tool_context.get("company")},
		}
	if tool == "get_business_report":
		dsl = tool_context.get("dsl") or {}
		report_citation = next(
			(citation for citation in citations if citation.get("type") == "business_report"),
			{},
		)
		return {
			"type": "business_report",
			"id": report_citation.get("id"),
			"entity_ids": [],
			"entity_refs": [],
			"scope": {
				"company": dsl.get("company"), "report_type": dsl.get("report_type"),
				"date_range": dsl.get("date_range"), "date_from": dsl.get("date_from"),
				"date_to": dsl.get("date_to"),
			},
		}
	return None


def _build_next_conversation_state(
	*, previous_state: dict | None, scenario: str, structured_intent: dict | None,
	tool_context: dict | None, citations: list[dict],
) -> dict:
	previous = _conversation_state_for_intent(previous_state)
	next_state = {
		key: value for key, value in previous.items()
		if key in {"product", "order", "report", "active_entities", "last_result_set"}
	}
	next_state.update({
		"schema_version": CONVERSATION_STATE_SCHEMA_VERSION,
		"active_scenario": scenario if scenario in ALLOWED_AI_SCENARIOS else "general",
	})
	context = tool_context if isinstance(tool_context, dict) else {}
	intent = structured_intent if isinstance(structured_intent, dict) else {}
	last_result_set = _compact_last_result_set(context, citations)
	active_entities = (
		dict(next_state.get("active_entities"))
		if isinstance(next_state.get("active_entities"), dict)
		else {}
	)
	if scenario == "product_search":
		resolved_product = context.get("resolved_product") or {}
		retrieval = context.get("retrieval") or {}
		query_resolution = context.get("query_resolution") or {}
		next_state["product"] = {
			"query": (
				str(intent.get("product_query") or "").strip()
				or str(context.get("query") or "").strip()[:200]
			) if query_resolution.get("status") != "unresolved" else None,
			"item_code": resolved_product.get("item_code"),
			"item_name": resolved_product.get("item_name"),
			"resolution_status": retrieval.get("status"),
		}
		product_status = str(retrieval.get("status") or "").strip()
		product_id = str(resolved_product.get("item_code") or "").strip() or None
		active_entities["product"] = {
			"entity_type": "product",
			"entity_id": product_id if product_status == "resolved" else None,
			"display_name": (
				str(resolved_product.get("item_name") or "").strip() or None
				if product_status == "resolved" else None
			),
			"resolution_status": (
				product_status if product_status in {"resolved", "ambiguous", "not_found"}
				else "not_found"
			),
			"source": "product_search",
			"source_result_set_id": (last_result_set or {}).get("id"),
		}
	elif scenario == "order_query":
		dsl = context.get("dsl") or {}
		next_state["order"] = {
			"entities": list(dsl.get("entities") or []),
			**_working_state_date_fields(dsl),
			"status": dsl.get("status_filter") or "all",
			"sort": dsl.get("sort_by") or "latest",
			"min_amount": dsl.get("min_amount"),
			"limit": dsl.get("limit") or 10,
		}
		order_refs = [
			row for row in (last_result_set or {}).get("entity_refs") or []
			if isinstance(row, dict)
			and row.get("entity_type") in {
				"sales_order", "sales_invoice", "purchase_order", "purchase_invoice",
			}
		]
		resolved_order = order_refs[0] if len(order_refs) == 1 else {}
		active_entities["business_document"] = {
			"entity_type": resolved_order.get("entity_type") or (dsl.get("entities") or [None])[0],
			"entity_id": resolved_order.get("entity_id") if len(order_refs) == 1 else None,
			"display_name": resolved_order.get("display_name") if len(order_refs) == 1 else None,
			"resolution_status": "resolved" if len(order_refs) == 1 else (
				"ambiguous" if order_refs else "not_found"
			),
			"source": "order_query",
			"source_result_set_id": (last_result_set or {}).get("id"),
		}
		party_refs = {}
		party_type_by_document = {
			"sales_order": "customer", "sales_invoice": "customer",
			"purchase_order": "supplier", "purchase_invoice": "supplier",
		}
		for citation in citations:
			if not isinstance(citation, dict):
				continue
			party_type = party_type_by_document.get(str(citation.get("type") or ""))
			data = citation.get("data") if isinstance(citation.get("data"), dict) else {}
			party_id = str(data.get("party_id") or "").strip()
			if party_type and party_id:
				party_refs.setdefault(
					(party_type, party_id),
					str(data.get("party_display_name") or data.get("party") or "").strip() or None,
				)
		resolved_party = next(iter(party_refs.items())) if len(party_refs) == 1 else None
		document_entities = set(dsl.get("entities") or [])
		active_entities["business_partner"] = {
			"entity_type": resolved_party[0][0] if resolved_party else (
				"customer" if document_entities and document_entities <= {"sales_order", "sales_invoice"}
				else "supplier" if document_entities and document_entities <= {"purchase_order", "purchase_invoice"}
				else None
			),
			"entity_id": resolved_party[0][1] if resolved_party else None,
			"display_name": resolved_party[1] if resolved_party else None,
			"resolution_status": "resolved" if resolved_party else (
				"ambiguous" if party_refs else "not_found"
			),
			"source": "order_query",
			"source_result_set_id": (last_result_set or {}).get("id"),
		}
	elif scenario == "report_summary":
		dsl = context.get("dsl") or {}
		next_state["report"] = {
			"report_type": dsl.get("report_type") or "overview",
			**_working_state_date_fields(dsl),
		}
	if active_entities:
		next_state["active_entities"] = active_entities
	if last_result_set:
		next_state["last_result_set"] = last_result_set
	return next_state


def _prepare_chat_run(
	messages=None,
	scenario: str | None = None,
	company: str | None = None,
	conversation_id: str | None = None,
	content: str | None = None,
	model_alias: str | None = None,
	retry_run_id: str | None = None,
	attachment_ids=None,
):
	user = _current_user()
	attachment_refs, attachment_payloads = resolve_ai_attachments(attachment_ids, user=user)
	model_alias = resolve_ai_selected_model_alias(model_alias)
	requested_scenario = _resolve_scenario(scenario)
	legacy_messages = _normalize_messages(messages) if messages not in (None, "", []) else []
	if content in (None, "") and attachment_payloads:
		content = _("请分析我上传的图片，并根据明确可见的信息处理当前业务需求；不确定的字段不要猜测。")
	current_content = _normalize_content(content) if content not in (None, "") else None
	retry_context = None
	if retry_run_id:
		retry_context = ai_repository.prepare_failed_run_retry(
			run_id=str(retry_run_id).strip(), user=user,
		)
		conversation_id = retry_context["conversation_id"]
		requested_scenario = _resolve_scenario(retry_context["scenario"])
		current_content = retry_context["content"]
		company = retry_context.get("company")
		legacy_messages = []
		attachment_refs, attachment_payloads = resolve_ai_attachments(
			retry_context.get("attachment_ids"), user=user,
		)
	if not current_content:
		if legacy_messages and legacy_messages[-1]["role"] != "user":
			frappe.throw(_("messages 最后一条必须是 user 消息。"))
		user_messages = [row["content"] for row in legacy_messages if row["role"] == "user"]
		if not user_messages:
			frappe.throw(_("请提供用户消息。"))
		current_content = user_messages[-1]

	is_new_conversation = not conversation_id
	conversation = None
	conversation_state_record = {
		"version": 0,
		"state": {"schema_version": CONVERSATION_STATE_SCHEMA_VERSION, "active_scenario": "general"},
	}
	if conversation_id:
		conversation = ai_repository.get_conversation(
			conversation_id=conversation_id, user=user,
		)["conversation"]
		conversation_state_record = ai_repository.get_conversation_state(
			conversation_id=conversation_id,
			user=user,
			expire_if_needed=conversation.get("status") == "active",
		)
	conversation_state = conversation_state_record.get("state") or {}
	conversation_company = str((conversation or {}).get("company") or "").strip() or None
	requested_company = str(company or "").strip() or None
	intent_company = requested_company or conversation_company
	preparsed_intent = {}
	route_mode = "scenario_locked"
	route_confidence = None
	if requested_scenario == "auto":
		preparsed_intent = _call_ai_intent_orchestrator(
			content=current_content,
			user=user,
			company=intent_company,
			conversation_state=conversation_state,
			model_alias=model_alias,
			attachments=attachment_payloads,
		)
		preparsed_intent = _merge_intent_with_conversation_state(
			current_content,
			preparsed_intent,
			conversation_state,
			has_current_attachments=bool(attachment_payloads),
		)
		requested_action_scenario, route_mode, route_confidence = _resolve_ai_action_scenario(
			current_content, conversation_state, preparsed_intent,
		)
	else:
		requested_action_scenario = requested_scenario
	# Keep established draft workflows outside the read-only Agent Runtime.  The
	# semantic router proposes the workflow; deterministic rules only fail closed
	# when an explicit write would otherwise be downgraded to a read-only path.
	agent_runtime_requested = os.environ.get("MYAPP_AI_AGENT_RUNTIME_ENABLED", "1").strip().lower() in {
		"1", "true", "yes",
	}
	agent_runtime_candidate = bool(
		agent_runtime_requested
		and intent_company
		and not attachment_payloads
		and requested_action_scenario not in {
			"sales_order_draft", "purchase_order_draft", "inventory_adjustment_draft", "product_setup_draft",
		}
	)
	agent_runtime_readiness = None
	compatibility_warnings = []
	if agent_runtime_candidate:
		agent_scenario = "general" if requested_scenario == "auto" else requested_scenario
		try:
			agent_runtime_readiness = resolve_ai_agent_runtime_readiness(
				scenario=agent_scenario,
				environment=os.environ.get("MYAPP_AI_ENVIRONMENT", "development").strip() or "development",
				company=intent_company,
				user=user,
				model_alias=model_alias,
			)
		except Exception:
			frappe.log_error(frappe.get_traceback(), _("AI Agent Runtime 就绪预检失败"))
			agent_runtime_readiness = {
				"ready": False, "reason": "policy_readiness_unavailable", "policy_code": None,
			}
	agent_mode = bool(agent_runtime_candidate and agent_runtime_readiness.get("ready"))
	if agent_runtime_candidate and not agent_mode:
		compatibility_warnings.append(
			_("智能工具模式尚未就绪，本次已使用兼容查询模式，查询结果仍来自当前业务系统。")
		)

	resolved_scenario = requested_scenario
	intent_resolution = (
		{
			"mode": route_mode,
			"resolved_scenario": requested_action_scenario,
			"confidence": route_confidence,
			"scenario_locked": False,
			"structured_filters_used": requested_action_scenario in {
				"product_search", "order_query", "report_summary",
			},
		}
		if requested_scenario == "auto" else None
	)
	structured_intent = None
	if agent_mode:
		# The model selects a typed tool. Local routing remains available only as
		# a compatibility fallback when Agent Runtime cannot be used.
		resolved_scenario = "general" if requested_scenario == "auto" else requested_scenario
	else:
		if requested_scenario == "auto":
			resolved_scenario = requested_action_scenario
		if resolved_scenario not in {
			"sales_order_draft", "purchase_order_draft", "inventory_adjustment_draft", "product_setup_draft",
		}:
			# Compatibility mode still delegates semantic understanding and typed
			# filters to the model. Deterministic routing above exists only to keep
			# write intents inside the established draft + human review boundary.
			# Local keyword rules are the last fallback when the parser is unavailable,
			# unconfident, or returns a schema-invalid scenario.
			intent = preparsed_intent
			if requested_scenario != "auto":
				intent = _call_ai_intent_orchestrator(
					content=current_content,
					user=user,
					company=intent_company,
					conversation_state=conversation_state,
					model_alias=model_alias,
					attachments=attachment_payloads,
				)
				intent = _merge_intent_with_conversation_state(
					current_content,
					intent,
					conversation_state,
					has_current_attachments=bool(attachment_payloads),
				)
			candidate = str(intent.get("intent") or "").strip()
			try:
				confidence = min(1.0, max(0.0, float(intent.get("confidence") or 0)))
			except (TypeError, ValueError):
				confidence = 0
			candidate_is_usable = bool(
				candidate in {"general", "product_search", "order_query", "report_summary"}
				and confidence >= 0.6
				and (requested_scenario == "auto" or candidate == resolved_scenario)
			)
			if candidate_is_usable:
				if requested_scenario == "auto":
					resolved_scenario = requested_action_scenario
				structured_intent = intent
				if requested_scenario != "auto":
					intent_resolution = {
						"mode": "structured_intent", "resolved_scenario": resolved_scenario,
						"confidence": confidence,
						"scenario_locked": True,
						"structured_filters_used": candidate in {
							"product_search", "order_query", "report_summary",
						},
					}
			else:
				if requested_scenario != "auto":
					intent_resolution = {
						"mode": "structured_intent_fallback",
						"resolved_scenario": resolved_scenario,
					}
	prompt_version = _resolve_prompt_version(resolved_scenario)

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
	if retry_context:
		pass
	elif initial_messages:
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
		user_message = ai_repository.append_message(
			conversation_id=conversation_id,
			user=user,
			role="user",
			content=current_content,
			scenario=resolved_scenario,
			attachments=attachment_refs,
			prompt_version=prompt_version,
		)
	run_id = ai_repository.create_run(
		conversation_id=conversation_id,
		user=user,
		scenario=resolved_scenario,
		model_alias=model_alias,
		retry_of_run_id=retry_context.get("source_run_id") if retry_context else None,
	)
	if attachment_payloads and not retry_context:
		resolve_ai_attachments(
			attachment_ids,
			user=user,
			conversation_id=conversation_id,
			message_id=user_message["name"],
			run_id=run_id,
		)
	if retry_context:
		ai_repository.rebind_failed_run_message_for_retry(
			message_id=retry_context["failed_message_id"],
			source_run_id=retry_context["source_run_id"],
			retry_run_id=run_id,
			user=user,
			scenario=resolved_scenario,
			prompt_version=prompt_version,
		)
	allowed_agent_tools = []
	capability_token = None
	if agent_mode:
		if frappe.has_permission("Item", ptype="read"):
			allowed_agent_tools.append("search_products")
		allowed_agent_tools.extend(["query_business_documents", "get_business_report"])
		capability_token = ai_repository.issue_agent_capability(
			run_id=run_id, user=user, allowed_tools=allowed_agent_tools,
		)
	# AI audit records intentionally form their own durable boundary before the external model call.
	frappe.db.commit()

	started = time.perf_counter()
	tool_context = None
	citations = []
	context_audit = {
		"tool": "load_conversation_context",
		"risk_level": "L0_SESSION_STATE",
		"mode": conversation_state_record.get("status") or "empty",
		"reset_reason": conversation_state_record.get("reset_reason"),
		"state_version": cint(conversation_state_record.get("version")),
		"event_visible": False,
	}
	tool_calls = []
	try:
		if agent_mode:
			tool_context = None
		elif resolved_scenario == "product_search":
			if _multimodal_product_query_is_unresolved(
				content=current_content,
				structured_intent=structured_intent,
				attachment_payloads=attachment_payloads,
			):
				tool_context, citations, tool_calls = _build_unresolved_multimodal_product_search_context(
					query=current_content,
					company=resolved_company,
				)
			else:
				tool_context, citations, tool_calls = _build_product_search_context(
					query=current_content,
					company=resolved_company,
					structured_intent=structured_intent,
					query_source=(
						"multimodal_intent"
						if attachment_payloads and str((structured_intent or {}).get("product_query") or "").strip()
						else None
					),
				)
		elif resolved_scenario == "order_query":
			tool_context, citations, tool_calls = _build_order_query_context(
				query=current_content,
				company=resolved_company,
				structured_intent=structured_intent,
				conversation_state=conversation_state,
			)
		elif resolved_scenario == "report_summary":
			tool_context, citations, tool_calls = _build_report_query_context(
				query=current_content,
				company=resolved_company,
				structured_intent=structured_intent,
			)
		tool_calls.append(context_audit)
		if intent_resolution:
			tool_calls.insert(0, {
				"tool": "parse_ai_intent",
				"risk_level": "L0_ROUTING",
				"query_hash": hashlib.sha256(current_content.encode("utf-8")).hexdigest(),
				**intent_resolution,
			})
		if agent_runtime_candidate and not agent_mode:
			tool_calls.insert(0, {
				"tool": "agent_runtime_readiness",
				"risk_level": "L0_ROUTING",
				"mode": "compatibility_fallback",
				"reason": agent_runtime_readiness.get("reason"),
				"policy_code": agent_runtime_readiness.get("policy_code"),
				"event_visible": False,
			})
		model_messages = _load_model_messages(conversation_id=conversation_id, user=user)
		next_conversation_state = (
			conversation_state
			if agent_mode
			else _build_next_conversation_state(
				previous_state=conversation_state,
				scenario=resolved_scenario,
				structured_intent=structured_intent,
				tool_context=tool_context,
				citations=citations,
			)
		)
	except Exception as error:
		latency_ms = int((time.perf_counter() - started) * 1000)
		frappe.db.rollback()
		ai_repository.fail_run(run_id=run_id, user=user, error=error, latency_ms=latency_ms)
		frappe.db.commit()
		raise
	return {
		"user": user,
		"can_view_advanced_diagnostics": _can_view_advanced_diagnostics(user),
		"scenario": resolved_scenario,
		"company": resolved_company,
		"conversation_id": conversation_id,
		"run_id": run_id,
		"started": started,
		"prompt_version": prompt_version,
		"citations": citations,
		"tool_calls": tool_calls,
		"conversation_state_version": cint(conversation_state_record.get("version")),
		"next_conversation_state": next_conversation_state,
		"agent_mode": agent_mode,
		"warnings": compatibility_warnings,
		"retry_of_run_id": retry_context.get("source_run_id") if retry_context else None,
		"requested_model_alias": model_alias,
		"payload": {
			"messages": model_messages,
			"scenario": resolved_scenario,
			"user": user,
			"company": resolved_company,
			"locale": getattr(frappe.local, "lang", None) or "zh-CN",
			"context": (
				{"conversation_state": _conversation_state_for_intent(conversation_state)}
				if agent_mode else tool_context
			),
			"prompt_version": prompt_version,
			"conversation_id": conversation_id,
			"run_id": run_id,
			"policy_context": {
				"roles": sorted(set(frappe.get_roles(user) or [])),
				"environment": os.environ.get("MYAPP_AI_ENVIRONMENT", "development").strip() or "development",
			},
			"model_alias": model_alias,
			**(
				{
					"capability_token": capability_token,
					"allowed_tools": allowed_agent_tools,
					"policy_code": agent_runtime_readiness.get("policy_code"),
					"policy_version": agent_runtime_readiness.get("policy_version"),
				}
				if agent_mode else {}
			),
		},
	}


def _prepare_agent_resume(run_id: str) -> dict:
	user = _current_user()
	resolved_run_id = str(run_id or "").strip()
	if not resolved_run_id:
		frappe.throw(_("AI Run 编号不能为空。"))
	try:
		resume_context = ai_repository.prepare_agent_run_resume(
			run_id=resolved_run_id, user=user,
		)
		conversation_id = resume_context["conversation_id"]
		ai_repository.get_conversation(
			conversation_id=conversation_id, user=user,
		)
		conversation_state_record = ai_repository.get_conversation_state(
			conversation_id=conversation_id, user=user,
		)
		scenario = str(resume_context.get("scenario") or "general")
		prompt_version = str(resume_context.get("prompt_version") or "").strip()
		if prompt_version != _resolve_prompt_version(scenario):
			frappe.throw(_("AI Run 使用的 Prompt 版本已不可用，不能安全恢复。"))
		model_alias = resolve_ai_selected_model_alias(resume_context.get("model_alias"))
		company = _resolve_company_scope(resume_context.get("company"), required=True)
		model_messages = _load_model_messages(conversation_id=conversation_id, user=user)
		if not model_messages:
			frappe.throw(_("AI Run 所属会话没有可恢复的消息。"))
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise

	allowed_tools = list(resume_context["allowed_tools"])
	return {
		"user": user,
		"can_view_advanced_diagnostics": _can_view_advanced_diagnostics(user),
		"scenario": scenario,
		"company": company,
		"conversation_id": conversation_id,
		"run_id": resolved_run_id,
		"started": time.perf_counter(),
		"prompt_version": prompt_version,
		"citations": [],
		"tool_calls": [{
			"tool": "resume_agent_run", "risk_level": "L0_RUNTIME_CONTROL",
			"mode": "same_run_checkpoint", "checkpoint_stage": resume_context.get("checkpoint_stage"),
		}],
		"conversation_state_version": cint(conversation_state_record.get("version")),
		"next_conversation_state": conversation_state_record.get("state") or {},
		"agent_mode": True,
		"payload": {
			"messages": model_messages,
			"scenario": scenario,
			"user": user,
			"company": company,
			"locale": getattr(frappe.local, "lang", None) or "zh-CN",
			"context": {"conversation_state": _conversation_state_for_intent(
				conversation_state_record.get("state") or {},
			)},
			"prompt_version": prompt_version,
			"conversation_id": conversation_id,
			"run_id": resolved_run_id,
			"policy_context": {
				"roles": sorted(set(frappe.get_roles(user) or [])),
				"environment": os.environ.get("MYAPP_AI_ENVIRONMENT", "development").strip() or "development",
			},
			"model_alias": model_alias,
			"capability_token": resume_context["capability_token"],
			"allowed_tools": allowed_tools,
			**({"approval": resume_context["approval"]} if resume_context.get("approval") else {}),
		},
	}


def _prepare_agent_approval_resume(approval_id: str) -> dict:
	user = _current_user()
	resolved_approval_id = str(approval_id or "").strip()
	if not resolved_approval_id:
		frappe.throw(_("Agent 审批编号不能为空。"))
	try:
		resume_context = ai_repository.prepare_reviewed_agent_approval_resume(
			approval_id=resolved_approval_id, user=user,
		)
		conversation_id = resume_context["conversation_id"]
		conversation_state_record = ai_repository.get_conversation_state(
			conversation_id=conversation_id, user=user,
		)
		scenario = str(resume_context.get("scenario") or "general")
		prompt_version = str(resume_context.get("prompt_version") or "").strip()
		if prompt_version != _resolve_prompt_version(scenario):
			frappe.throw(_("AI Run 使用的 Prompt 版本已不可用，不能安全恢复。"))
		model_alias = resolve_ai_selected_model_alias(resume_context.get("model_alias"))
		company = _resolve_company_scope(resume_context.get("company"), required=True)
		model_messages = _load_model_messages(conversation_id=conversation_id, user=user)
		if not model_messages:
			frappe.throw(_("AI Run 所属会话没有可恢复的消息。"))
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise
	approval = resume_context["approval"]
	return {
		"user": user,
		"can_view_advanced_diagnostics": _can_view_advanced_diagnostics(user),
		"scenario": scenario, "company": company,
		"conversation_id": conversation_id, "run_id": resume_context["run_id"],
		"started": time.perf_counter(), "prompt_version": prompt_version,
		"citations": [],
		"tool_calls": [{
			"tool": "resume_agent_after_approval", "risk_level": "L0_RUNTIME_CONTROL",
			"mode": approval["status"], "approval_id": approval["approval_id"],
			"checkpoint_stage": resume_context.get("checkpoint_stage"),
		}],
		"conversation_state_version": cint(conversation_state_record.get("version")),
		"next_conversation_state": conversation_state_record.get("state") or {},
		"agent_mode": True,
		"payload": {
			"messages": model_messages, "scenario": scenario, "user": user,
			"company": company, "locale": getattr(frappe.local, "lang", None) or "zh-CN",
			"context": {"conversation_state": _conversation_state_for_intent(
				conversation_state_record.get("state") or {},
			)}, "prompt_version": prompt_version,
			"conversation_id": conversation_id, "run_id": resume_context["run_id"],
			"policy_context": {
				"roles": sorted(set(frappe.get_roles(user) or [])),
				"environment": os.environ.get("MYAPP_AI_ENVIRONMENT", "development").strip() or "development",
			},
			"model_alias": model_alias, "capability_token": resume_context["capability_token"],
			"allowed_tools": list(resume_context["allowed_tools"]), "approval": approval,
		},
	}


def _apply_agent_result(prepared: dict, result: dict) -> None:
	if not prepared.get("agent_mode"):
		return
	prepared["citations"] = list(result.get("citations") or [])
	prepared["tool_calls"] = list(result.get("tool_calls") or [])
	tool_results = result.get("tool_results") or []
	if not tool_results:
		return
	scenario_by_tool = {
		"search_products": "product_search",
		"query_business_documents": "order_query",
		"get_business_report": "report_summary",
	}
	next_state = prepared.get("next_conversation_state") or {}
	for tool_result in tool_results:
		if not isinstance(tool_result, dict):
			continue
		tool = str(tool_result.get("tool") or "")
		tool_context = (
			tool_result.get("model_context")
			if isinstance(tool_result.get("model_context"), dict)
			else {}
		)
		# Denied/retryable tool envelopes deliberately carry an empty context.
		# They must not erase a previously resolved entity.  Successful empty
		# searches still carry their typed tool marker and are applied as not_found.
		if tool not in scenario_by_tool or str(tool_context.get("tool") or "") != tool:
			continue
		next_state = _build_next_conversation_state(
			previous_state=next_state,
			scenario=scenario_by_tool[tool],
			structured_intent=None,
			tool_context=tool_context,
			citations=[
				citation for citation in (tool_result.get("citations") or [])
				if isinstance(citation, dict)
			],
		)
	prepared["next_conversation_state"] = next_state


def _complete_chat_run(
	prepared: dict, result: dict, assistant_content: str, *, first_token_ms: int | None = None,
):
	_apply_agent_result(prepared, result)
	latency_ms = int((time.perf_counter() - prepared["started"]) * 1000)
	base_tool_calls = list(prepared["tool_calls"])
	for attempt in range(2):
		prepared["tool_calls"] = list(base_tool_calls)
		try:
			if prepared.get("retry_of_run_id"):
				ai_repository.complete_retried_run_message(
					run_id=prepared["run_id"],
					user=prepared["user"],
					content=assistant_content,
					scenario=prepared["scenario"],
					citations=prepared["citations"],
					prompt_version=prepared["prompt_version"],
				)
			else:
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
			try:
				state_result = ai_repository.update_conversation_state(
					conversation_id=prepared["conversation_id"],
					user=prepared["user"],
					state=prepared.get("next_conversation_state") or {},
					expected_version=cint(prepared.get("conversation_state_version")),
				)
				prepared["tool_calls"].append({
					"tool": "update_conversation_state",
					"risk_level": "L0_SESSION_STATE",
					"mode": "patched" if state_result.get("updated") else "state_update_skipped",
					"state_version": state_result.get("version"),
				})
			except QueryDeadlockError:
				# The Orchestrator persists Agent steps through separate HTTP
				# transactions.  A final callback can briefly race this request's
				# conversation/Run finalization; retry the whole local transaction.
				raise
			except Exception:
				# Conversation state is an optimization for continuity; a failed state
				# write must never turn a successful read-only business answer into a run
				# failure.  The next turn will rebuild from durable messages.
				frappe.log_error(frappe.get_traceback(), _("AI 会话状态更新失败"))
				prepared["tool_calls"].append({
					"tool": "update_conversation_state",
					"risk_level": "L0_SESSION_STATE",
					"mode": "state_update_skipped",
				})
			ai_repository.complete_run(
				run_id=prepared["run_id"],
				user=prepared["user"],
				result=result,
				latency_ms=latency_ms,
				first_token_ms=first_token_ms,
				tool_calls=prepared["tool_calls"],
			)
			if prepared.get("agent_mode"):
				ai_repository.revoke_agent_capability(
					run_id=prepared["run_id"], user=prepared["user"],
				)
			frappe.db.commit()
			break
		except QueryDeadlockError:
			frappe.db.rollback()
			if attempt:
				raise
	return {
		"status": "completed",
		"latency_ms": latency_ms,
		"first_token_ms": first_token_ms,
		"model_selection": "fixed" if prepared.get("requested_model_alias") else "auto",
		"requested_model_alias": prepared.get("requested_model_alias"),
		"requested_model_display": _resolve_ai_model_display(
			prepared.get("requested_model_alias")
		),
	}


def _pause_chat_run(prepared: dict, result: dict) -> dict:
	approval = result.get("approval") or {}
	if not approval or str(approval.get("run_id") or "") != prepared["run_id"]:
		raise UpstreamServiceUnavailableError(_("AI 审批暂停响应无效。"))
	ai_repository.revoke_agent_capability(run_id=prepared["run_id"], user=prepared["user"])
	frappe.db.commit()
	return {
		"status": "waiting_approval",
		"latency_ms": int((time.perf_counter() - prepared["started"]) * 1000),
		"approval": approval,
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
	ai_repository.append_failed_run_message(
		run_id=prepared["run_id"], user=prepared["user"],
	)
	if prepared.get("agent_mode"):
		ai_repository.revoke_agent_capability(run_id=prepared["run_id"], user=prepared["user"])
	frappe.db.commit()


def chat_ai_v1(
	messages=None,
	scenario: str | None = None,
	company: str | None = None,
	conversation_id: str | None = None,
	content: str | None = None,
	model_alias: str | None = None,
	attachment_ids=None,
):
	prepared = _prepare_chat_run(
		messages=messages,
		scenario=scenario,
		company=company,
		conversation_id=conversation_id,
		content=content,
		model_alias=model_alias,
		attachment_ids=attachment_ids,
	)
	try:
		result = _call_ai_orchestrator(prepared["payload"])
		result = {
			**result,
			"warnings": _merge_ai_warnings(prepared.get("warnings"), result.get("warnings")),
		}
		if result.get("status") == "waiting_approval":
			pause = _pause_chat_run(prepared, result)
			return {
				"status": "success", "message": _("AI Run 正在等待人工审批。"),
				"data": {
					"conversation": prepared["conversation_id"], "run_id": prepared["run_id"],
					"run_status": "waiting_approval", "approval": pause["approval"],
					"latency_ms": pause["latency_ms"],
				},
			}
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
			**_public_ai_result_details(
				result=result,
				run=run_summary,
				include_advanced_diagnostics=prepared["can_view_advanced_diagnostics"],
			),
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


def cancel_ai_run_v1(run_id: str):
	user = _current_user()
	resolved_run_id = str(run_id or "").strip()
	if not resolved_run_id:
		frappe.throw(_("AI Run 编号不能为空。"))
	result = ai_repository.cancel_agent_run(run_id=resolved_run_id, user=user)
	frappe.db.commit()
	return {
		"status": "success",
		"message": _("AI Run 已取消。") if result["cancelled"] else _("AI Run 已结束。"),
		"data": result,
	}


def get_ai_agent_approval_v1(approval_id: str):
	return {
		"status": "success", "message": _("Agent 审批读取成功。"),
		"data": ai_repository.get_agent_approval(
			approval_id=str(approval_id or "").strip(), user=_current_user(),
		),
	}


def list_ai_agent_approvals_v1(
	run_id: str | None = None, status: str | None = None, start: int = 0, limit: int = 20,
):
	return {
		"status": "success", "message": _("Agent 审批列表读取成功。"),
		"data": ai_repository.list_agent_approvals(
			user=_current_user(), run_id=run_id, status=status, start=start, limit=limit,
		),
	}


def _resume_reviewed_agent_approval(approval_id: str):
	prepared = _prepare_agent_approval_resume(approval_id)
	try:
		result = _call_ai_orchestrator(prepared["payload"], resume=True)
		if result.get("status") == "waiting_approval":
			pause = _pause_chat_run(prepared, result)
			return {
				"status": "success", "message": _("AI Run 正在等待下一项人工审批。"),
				"data": {
					"conversation": prepared["conversation_id"], "run_id": prepared["run_id"],
					"run_status": "waiting_approval", "approval": pause["approval"],
					"resumed": True, "latency_ms": pause["latency_ms"],
				},
			}
		message = result.get("message") or {}
		assistant_content = str(message.get("content") or "").strip()
		if not assistant_content:
			raise UpstreamServiceUnavailableError(_("AI 审批恢复服务返回了无效响应。"))
		run_summary = _complete_chat_run(prepared, result, assistant_content)
	except Exception as error:
		_fail_chat_run(prepared, error)
		raise
	return {
		"status": "success", "message": _("Agent 审批决定已应用，AI Run 已恢复。"),
		"data": {
			"conversation": prepared["conversation_id"], "run_id": prepared["run_id"],
			"run_status": "completed", "resumed": True,
			"message": {
				"role": "assistant", "content": assistant_content,
				"citations": prepared["citations"],
			},
			**_public_ai_result_details(
				result=result, run=run_summary,
				include_advanced_diagnostics=prepared["can_view_advanced_diagnostics"],
			),
		},
	}


def review_ai_agent_approval_v1(
	approval_id: str, decision: str, expected_version: int, reason: str | None = None,
):
	user = _current_user()
	approval = ai_repository.review_agent_approval(
		approval_id=str(approval_id or "").strip(), user=user,
		decision=decision, expected_version=expected_version, reason=reason,
	)
	frappe.db.commit()
	if approval["status"] == "expired":
		return {
			"status": "success", "message": _("Agent 审批已过期，Run 未执行。"),
			"data": {"approval": approval, "run_status": "expired"},
		}
	if approval.get("replayed") and approval.get("run_status") != "waiting_approval":
		return {
			"status": "success", "message": _("Agent 审批决定已记录。"),
			"data": {"approval": approval, "run_status": approval.get("run_status")},
		}
	return _resume_reviewed_agent_approval(approval["approval_id"])


def resume_ai_agent_approval_v1(approval_id: str):
	"""Recover after a reviewed approval was committed but the resume call was interrupted."""
	return _resume_reviewed_agent_approval(str(approval_id or "").strip())


def resume_ai_run_v1(run_id: str):
	prepared = _prepare_agent_resume(run_id)
	try:
		result = _call_ai_orchestrator(prepared["payload"], resume=True)
		if result.get("status") == "waiting_approval":
			pause = _pause_chat_run(prepared, result)
			return {
				"status": "success", "message": _("AI Run 再次等待人工审批。"),
				"data": {
					"conversation": prepared["conversation_id"], "run_id": prepared["run_id"],
					"run_status": "waiting_approval", "approval": pause["approval"],
					"resumed": True, "latency_ms": pause["latency_ms"],
				},
			}
		message = result.get("message") or {}
		assistant_content = str(message.get("content") or "").strip()
		if not assistant_content:
			raise UpstreamServiceUnavailableError(_("AI 恢复服务返回了无效响应。"))
		run_summary = _complete_chat_run(prepared, result, assistant_content)
	except Exception as error:
		_fail_chat_run(prepared, error)
		raise

	warnings = result.get("warnings") or []
	return {
		"status": "success",
		"message": _("AI Run 恢复成功。"),
		"data": {
			"conversation": prepared["conversation_id"],
			"run_id": prepared["run_id"],
			"resumed": True,
			"message": {
				"role": "assistant", "content": assistant_content,
				"citations": prepared["citations"],
			},
			**_public_ai_result_details(
				result=result, run=run_summary,
				include_advanced_diagnostics=prepared["can_view_advanced_diagnostics"],
			),
			"events": _build_events(
				content=assistant_content, citations=prepared["citations"],
				warnings=warnings, tool_calls=prepared["tool_calls"],
			),
		},
	}


def stream_ai_message_v1(
	content: str,
	scenario: str | None = None,
	company: str | None = None,
	conversation_id: str | None = None,
	model_alias: str | None = None,
	retry_run_id: str | None = None,
	attachment_ids=None,
):
	prepared = _prepare_chat_run(
		scenario=scenario,
		company=company,
		conversation_id=conversation_id,
		content=content,
		model_alias=model_alias,
		retry_run_id=retry_run_id,
		attachment_ids=attachment_ids,
	)
	return _stream_prepared_ai_run(prepared)


def stream_ai_run_resume_v1(run_id: str):
	return _stream_prepared_ai_run(_prepare_agent_resume(run_id), resume=True)


def _stream_prepared_ai_run(prepared: dict, *, resume: bool = False):
	include_advanced_diagnostics = bool(prepared.get("can_view_advanced_diagnostics", False))

	def event_stream():
		content_parts = []
		completed_result = None
		paused_result = None
		active_model_alias = str(prepared.get("payload", {}).get("model_alias") or "").strip() or None
		streamed_warnings = _merge_ai_warnings(prepared.get("warnings"))
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
				if tool_call.get("event_visible") is False:
					continue
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
			for warning in streamed_warnings:
				yield _encode_sse({"type": "warning", "message": warning})

			yield _encode_sse(
				{
					"type": "run_progress",
					"phase": "generating",
					"message": _("正在请求模型，等待首个 Token"),
				}
			)
			for event in _stream_ai_orchestrator(prepared["payload"], resume=resume):
				event_type = event.get("type")
				if event_type == "started":
					active_model_alias = str(event.get("model_alias") or active_model_alias or "").strip() or None
					yield _encode_sse(
						{
							"type": "run_progress",
							"phase": "model_started",
							"message": _("模型已接收请求，等待首个 Token"),
							"model_display": _public_ai_model_display(
								active_model_alias,
								include_advanced_diagnostics=include_advanced_diagnostics,
							),
							**(
								{"model_alias": active_model_alias}
								if include_advanced_diagnostics else {}
							),
						}
					)
				elif event_type in {"model_started", "tool_started", "tool_completed", "approval_required"}:
					yield _encode_sse(event)
				elif event_type == "paused":
					paused_result = event
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
					streamed_warnings = _merge_ai_warnings(
						streamed_warnings, [event.get("message")],
					)
					yield _encode_sse(event)
				elif event_type == "error":
					active_model_alias = str(event.get("model_alias") or active_model_alias or "").strip() or None
					public_data = {
						"model_display": _public_ai_model_display(
							active_model_alias,
							include_advanced_diagnostics=include_advanced_diagnostics,
						),
						"retryable": True,
					}
					if active_model_alias and include_advanced_diagnostics:
						public_data["model_alias"] = active_model_alias
					provider_error_code = str(event.get("provider_error_code") or "").strip() or None
					if provider_error_code and include_advanced_diagnostics:
						public_data["provider_error_code"] = provider_error_code
					raise AiServiceError(
						(
							_("模型 {0} 暂时不可用，请更换模型或稍后重试。").format(
								_public_ai_model_display(
									active_model_alias,
									include_advanced_diagnostics=include_advanced_diagnostics,
								) or _("当前自动模型")
							)
							if event.get("code") == "MODEL_PROVIDER_REJECTED"
							else str(event.get("message") or _("AI 服务暂时不可用。"))
						),
						code=str(event.get("code") or "AI_SERVICE_UNAVAILABLE"),
						model_alias=active_model_alias,
						provider_error_code=provider_error_code,
						public_data=public_data,
					)
				elif event_type == "completed":
					completed_result = {
						**event,
						"warnings": _merge_ai_warnings(
							streamed_warnings, event.get("warnings"),
						),
					}

			if paused_result:
				pause = _pause_chat_run(prepared, paused_result)
				yield _encode_sse({
					"type": "waiting_approval", "conversation": prepared["conversation_id"],
					"run_id": prepared["run_id"], "run_status": "waiting_approval",
					"approval": pause["approval"], "latency_ms": pause["latency_ms"],
				})
				return
			assistant_content = "".join(content_parts).strip()
			if not assistant_content and completed_result:
				assistant_content = str((completed_result.get("message") or {}).get("content") or "").strip()
			if not assistant_content or not completed_result:
				raise UpstreamServiceUnavailableError(_("AI 流式服务返回了无效响应。"))
			run_summary = _complete_chat_run(
				prepared, completed_result, assistant_content, first_token_ms=first_token_ms,
			)
			stream_summary = {
				"delta_count": delta_count,
				"streamed_chars": streamed_chars,
			}
			yield _encode_sse({
				"type": "completed",
				"conversation": prepared["conversation_id"],
				"run_id": prepared["run_id"],
				"message": completed_result.get("message") or {
					"role": "assistant", "content": assistant_content,
				},
				"citations": prepared["citations"],
				**_public_ai_result_details(
					result=completed_result,
					run=run_summary,
					include_advanced_diagnostics=include_advanced_diagnostics,
					stream=stream_summary,
				),
			})
		except GeneratorExit as error:
			_fail_chat_run(prepared, RuntimeError("AI stream client disconnected"))
			raise error
		except Exception as error:
			_fail_chat_run(prepared, error)
			error_code = str(getattr(error, "code", "") or "AI_STREAM_FAILED")
			error_message = (
				str(error)
				if isinstance(error, AiServiceError)
				else _("AI 流式服务暂时不可用，请稍后重试。")
			)
			yield _encode_sse(
				{
					"type": "error",
					"code": error_code,
					"message": error_message,
					"conversation": prepared["conversation_id"],
					"run_id": prepared["run_id"],
					**getattr(error, "public_data", {}),
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
