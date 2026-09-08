"""Conservative evidence checks, not a natural-language price interpreter.

Source amounts/units are retained to detect loss in legacy scalar product drafts.
Never infer a wholesale/retail role or a conversion factor from price ratios.
"""

import re
from decimal import Decimal, InvalidOperation

PRICE_FIELDS = ("standard_selling_rate", "wholesale_rate", "retail_rate", "standard_buying_rate")
_QUOTE = re.compile(
	r"(?P<rate>\d+(?:\.\d+)?)\s*元\s*(?:每|[/／])\s*(?P<uom>[A-Za-z\u3400-\u9fff]+)"
	r"|每\s*(?P<leading_uom>[A-Za-z\u3400-\u9fff]+)\s*(?P<leading_rate>\d+(?:\.\d+)?)\s*元"
)


def extract_product_price_requirements(content):
	return {
		"schema_version": "product-price-requirements-v1",
		"quotes": [
			{"rate": match.group("rate") or match.group("leading_rate"),
			 "uom": match.group("uom") or match.group("leading_uom"), "evidence": match.group(0)}
			for match in _QUOTE.finditer(content)
		],
	}


def product_price_errors(payload, requirements, *, resolve_uom, check_amounts=False):
	if not requirements:
		return []
	if requirements.get("schema_version") != "product-price-requirements-v1":
		return ["价格原文证据版本无效，请重新生成商品草稿。"]
	errors = []
	for quote in requirements.get("quotes") or []:
		unit = resolve_uom(quote["uom"])
		if payload.get("pricing_contract_version") == "product-pricing-v1":
			rows = [row for row in payload.get("prices") or [] if isinstance(row, dict) and row.get("uom") == unit]
			if not rows:
				errors.append(f"原文价格“{quote['evidence']}”的计价单位未保留，请补充价格明细。")
			elif check_amounts:
				try:
					values = {Decimal(str(row.get("rate"))) for row in rows if row.get("rate") is not None}
					if Decimal(quote["rate"]) not in values:
						errors.append(f"原文价格“{quote['evidence']}”未保留在对应单位的价格明细中。")
				except (InvalidOperation, ValueError, TypeError):
					errors.append("价格格式无效，请核对价格明细。")
			continue
		if not unit or unit != payload.get("stock_uom"):
			errors.append(
				f"原文价格“{quote['evidence']}”不能作为库存基准单位价格保存。"
				"当前 AI 商品草稿尚未完整支持逐条价格单位和换算，请在正式商品页面配置多单位价格；不得按价格比例推算包装数量。"
			)
		if check_amounts:
			try:
				values = {Decimal(str(payload[field])) for field in PRICE_FIELDS if payload.get(field) not in (None, "")}
				if Decimal(quote["rate"]) not in values:
					errors.append(f"原文价格“{quote['evidence']}”未保留在草稿中，请重新明确各价格的用途，不能忽略后继续执行。")
			except (InvalidOperation, ValueError, TypeError):
				errors.append("价格格式无效，请核对后重新生成草稿。")
	return list(dict.fromkeys(errors))
