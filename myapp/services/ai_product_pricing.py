"""Typed product draft pricing; formal writes remain in the product domain."""

import math
from copy import deepcopy

from myapp.utils.uom import resolve_uom_relation_factors
from myapp.utils.uom_display import resolve_uom_display_name

VERSION = "product-pricing-v1"
PRICE_FIELDS = {"Standard Selling": "standard_selling_rate", "Wholesale": "wholesale_rate",
	"Retail": "retail_rate", "Standard Buying": "standard_buying_rate"}


def preserve_price_provenance(incoming, previous):
	"""Only unchanged server rows retain model/default provenance after editing."""
	if not isinstance(incoming, list):
		return incoming
	old_rows = {str(row.get("row_id")): row for row in previous or [] if isinstance(row, dict)}
	result = deepcopy(incoming)
	for row in result:
		if not isinstance(row, dict):
			continue
		old = old_rows.get(str(row.get("row_id")))
		unchanged = old and all(row.get(key) == old.get(key) for key in ("price_list", "rate", "uom", "currency"))
		row["interpretation"] = old.get("interpretation") if unchanged else "user"
		row["evidence"] = old.get("evidence") if unchanged else "用户在草稿编辑器中修改。"
	return result


def build_product_pricing(payload, *, resolve_uom, resolve_price_currency=None):
	errors, warnings = [], []
	stock = payload.get("stock_uom")
	currency = payload.get("currency")
	prices, relations = [], []
	raw_prices, raw_relations = payload.get("prices"), payload.get("uom_relations")
	if not isinstance(raw_prices, list) or len(raw_prices) > 40:
		return {}, ["价格明细必须是数组，且最多40行。"], []
	if raw_relations is None:
		raw_relations = []
	if not isinstance(raw_relations, list) or len(raw_relations) > 20:
		return {}, ["单位关系必须是数组，且最多20行。"], []
	for index, raw in enumerate(raw_relations, 1):
		if not isinstance(raw, dict):
			errors.append(f"第{index}条单位关系格式无效。")
			continue
		row = {key: raw.get(key) for key in ("from_qty", "to_qty", "evidence")}
		for key in ("from_uom", "to_uom"):
			row[key] = resolve_uom(raw.get(key)) if isinstance(raw.get(key), str) and raw.get(key) else None
			if not row[key]:
				errors.append(f"第{index}条单位关系的单位无法唯一匹配，请选择正式单位。")
		relations.append(row)
		if row.get("from_qty") in (None, "") or row.get("to_qty") in (None, ""):
			errors.append(f"第{index}条单位关系数量尚未补齐。")
	seen, ids = set(), set()
	for index, raw in enumerate(raw_prices, 1):
		if not isinstance(raw, dict):
			errors.append(f"第{index}行价格格式无效。")
			continue
		row = {key: raw.get(key) for key in ("price_list", "rate", "evidence", "interpretation")}
		row["row_id"] = str(raw.get("row_id") or f"price-{index}")[:80]
		if row["row_id"] in ids:
			errors.append("价格明细行标识重复，请重新生成草稿。")
		ids.add(row["row_id"])
		row["uom"] = resolve_uom(raw.get("uom")) if isinstance(raw.get("uom"), str) and raw.get("uom") else None
		row["uom_display"] = resolve_uom_display_name(row["uom"]) if row["uom"] else None
		row["currency"] = str(raw.get("currency") or currency or "").strip()
		if not isinstance(row["price_list"], str) or row["price_list"] not in PRICE_FIELDS:
			errors.append(f"第{index}行价格用途不受支持，请选择价格表。")
		if not row["uom"]:
			errors.append(f"第{index}行价格单位无法唯一匹配。")
		if row["currency"] != currency:
			errors.append(f"第{index}行价格币种与草稿币种不一致，请拆分到正式价格维护处理。")
		if resolve_price_currency and isinstance(row["price_list"], str) and row["price_list"] in PRICE_FIELDS:
			list_currency = resolve_price_currency(row["price_list"])
			if not list_currency or list_currency != row["currency"]:
				errors.append(f"第{index}行价格币种与正式价格表币种不一致或价格表不存在，不能自动改币种保存。")
		value = row["rate"]
		if type(value) not in (int, float) or not 0 <= value <= 1_000_000_000 or not math.isfinite(value):
			errors.append(f"第{index}行价格必须是0至十亿之间的有效数字。")
		key = (str(row["price_list"]), row["uom"], row["currency"])
		if key in seen:
			errors.append(f"第{index}行与其他行价格表、币种和单位重复。")
		seen.add(key)
		if row.get("interpretation") == "inferred":
			warnings.append("批发/零售用途含业务推断，请核对价格明细后再确认执行。")
		prices.append(row)
	try:
		factors = resolve_uom_relation_factors(stock, relations) if stock else {}
	except ValueError as error:
		factors = {stock: 1} if stock else {}
		errors.append(str(error))
	for relation in relations:
		if any(relation.get(key) and relation[key] not in factors for key in ("from_uom", "to_uom")):
			errors.append("单位关系尚未连接到库存基准单位，请补齐换算，不能忽略未连接的单位。")
	for unit in dict.fromkeys(row["uom"] for row in prices if row["uom"]):
		if unit not in factors:
			errors.append(f"请补充{resolve_uom_display_name(unit)}与库存基准单位{resolve_uom_display_name(stock)}的数量换算，例如12瓶=1箱；不能按售价比例推算。")
			if not any(unit in {row.get("from_uom"), row.get("to_uom")} for row in relations):
				relations.append({"from_uom": unit, "from_qty": None, "to_uom": stock, "to_qty": 1, "evidence": ""})
	# A documented domain default, never a synonym for stock_uom or an overwrite
	# of an explicitly supplied Standard Selling row.
	prices = [row for row in prices if not (row["price_list"] == "Standard Selling" and row.get("interpretation") == "default")]
	if not any(row["price_list"] == "Standard Selling" for row in prices):
		candidates = [row for row in prices if row["price_list"] == "Wholesale" and row["uom"] == stock]
		if len(candidates) == 1:
			if any(row["row_id"] == "default-standard-selling" for row in prices):
				errors.append("价格行标识与默认参考价冲突，请重新生成草稿。")
			row = {**deepcopy(candidates[0]), "row_id": "default-standard-selling", "price_list": "Standard Selling",
				"interpretation": "default", "evidence": "默认策略：采用同库存基准单位的批发价作为标准销售参考。"}
			prices.append(row)
			warnings.append(row["evidence"])
			if resolve_price_currency and resolve_price_currency("Standard Selling") != row["currency"]:
				errors.append("默认标准销售参考价币种与正式价格表不一致，不能自动改币种保存。")
	result = {"pricing_contract_version": VERSION, "prices": prices, "uom_relations": relations,
		"uom_conversions": [{"uom": unit, "conversion_factor": factor} for unit, factor in factors.items()]}
	for mode in ("wholesale", "retail"):
		units = list(dict.fromkeys(row["uom"] for row in prices if row["price_list"] == mode.title() and row["uom"]))
		requested = payload.get(f"{mode}_default_uom")
		chosen = resolve_uom(requested) if requested else units[0] if len(units) == 1 else stock if not units else None
		result[f"{mode}_default_uom"] = chosen
		if not chosen or chosen not in factors:
			errors.append(f"请明确{'批发' if mode == 'wholesale' else '零售'}默认单位并补齐换算。")
	for price_list, field in PRICE_FIELDS.items():
		unit = result.get(f"{price_list.lower()}_default_uom", stock)
		matches = [row for row in prices if row["price_list"] == price_list and row["uom"] == unit]
		result[field] = matches[0]["rate"] if len(matches) == 1 else None
	return result, list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))
