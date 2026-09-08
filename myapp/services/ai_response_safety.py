"""Shared ingress and egress checks for the read-only public chat boundary.

Claim patterns are defense in depth, not a semantic proof or an execution receipt.
Never accept model-generated receipt fields as authorization to skip this check.
"""

import math
import re

from myapp.utils.ai_errors import AiServiceError

READ_SCENARIOS = {"general", "product_search", "order_query", "report_summary"}
INTENT_SCENARIOS = READ_SCENARIOS | {
	"product_setup_draft", "sales_order_draft", "purchase_order_draft",
	"inventory_adjustment_draft", "product_lifecycle_plan",
}
MAX_CHAT_RESPONSE_CHARS = 128_000


def require_reliable_intent(intent):
	confidence = intent.get("confidence") if isinstance(intent, dict) else None
	if (
		not isinstance(intent, dict)
		or not isinstance(intent.get("intent"), str)
		or intent.get("intent") not in INTENT_SCENARIOS
		or type(confidence) not in (int, float)
		or not 0.6 <= confidence <= 1
		or not math.isfinite(confidence)
	):
		raise AiServiceError(
			"本次 AI 未能可靠识别请求，已停止处理，未执行业务操作。请重试或明确操作和目标。",
			code="AI_INTENT_UNCERTAIN", public_data={"retryable": True},
		)


def require_readonly_chat_intent(intent):
	require_reliable_intent(intent)
	# Write contracts, including unsupported and uncertain operations, must never
	# be laundered through general chat or a caller-selected read scenario.
	if intent["intent"] not in READ_SCENARIOS or intent.get("action_contract") is not None:
		raise AiServiceError(
			"此请求不能作为普通查询继续，未执行业务操作。请使用自动识别进入草稿或操作计划并确认；若是咨询，请明确说明。",
			code="AI_CHAT_ACTION_REQUIRES_WORKFLOW", http_status=422,
			public_data={"retryable": False},
		)


_ACTION = r"(?:修改|更改|改成|改为|替换|更新|设置|设为|删除|停用|启用|创建|新增|提交|取消|付款|支付|退款|收款|扣减|增加库存|减少库存|保存|生成图片|生成封面|重绘)"
_COMPLETION_CLAIM = re.compile(
	r"(?:^|[。！？；\n])\s*(?:我|我们|系统)?\s*(?:已经|已|成功)"
	r"(?:(?:为|帮|替|按|将|把)[^。！？；\n]{0,100})?(?:成功|完成了?)?" + _ACTION
	+ r"|(?:^|[。！？；\n])\s*(?:商品图片|图片|封面|商品|订单|库存)?"
	+ _ACTION + r"(?:成功|已完成)(?:[。！\n]|$)"
	+ r"|\b(?:I|we)\s+(?:have\s+)?(?:successfully\s+)?"
	r"(?:updated|changed|replaced|deleted|disabled|enabled|created|submitted|cancelled|paid|refunded|saved)\b",
	re.IGNORECASE,
)


def check_readonly_chat_output(content):
	if len(content) > MAX_CHAT_RESPONSE_CHARS:
		raise AiServiceError("AI 回答超过安全长度限制，请缩小问题范围。", code="AI_OUTPUT_TOO_LARGE")
	if _COMPLETION_CLAIM.search(content):
		raise AiServiceError(
			"模型回答包含未经执行回执证实的操作成功描述，已拦截。本轮聊天没有执行业务修改或生成图片，请通过草稿或正式业务页面确认操作。",
			code="AI_UNVERIFIED_ACTION_CLAIM", http_status=422,
			public_data={"retryable": True},
		)
