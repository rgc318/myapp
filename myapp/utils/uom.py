import frappe
from frappe import _
from frappe.utils import flt

from myapp.utils.uom_display import build_uom_input_aliases, resolve_uom_display_name


def _normalize_uom(value: str | None) -> str | None:
	normalized = (value or "").strip()
	return normalized or None


def _normalize_uom_lookup(value: str | None) -> str | None:
	normalized = _normalize_uom(value)
	return " ".join(normalized.split()).casefold() if normalized else None


def build_item_uom_context_map(item_codes: list[str]) -> dict[str, dict]:
	item_codes = [code for code in {(_normalize_uom(item_code) or "") for item_code in item_codes} if code]
	if not item_codes:
		return {}

	item_rows = frappe.get_all("Item", filters={"name": ["in", item_codes]}, fields=["name", "stock_uom"])
	context_map = {
		row.name: {
			"stock_uom": _normalize_uom(row.stock_uom),
			"conversion_factors": {},
			"uom_metadata": {},
		}
		for row in item_rows
	}

	uom_rows = frappe.get_all(
		"UOM Conversion Detail",
		filters={"parent": ["in", list(context_map.keys())]},
		fields=["parent", "uom", "conversion_factor"],
	)
	for row in uom_rows:
		parent = getattr(row, "parent", None)
		uom = _normalize_uom(getattr(row, "uom", None))
		if not parent or not uom:
			continue
		context_map.setdefault(parent, {"stock_uom": None, "conversion_factors": {}, "uom_metadata": {}})
		context_map[parent]["conversion_factors"][uom] = flt(getattr(row, "conversion_factor", 0) or 0)

	for _item_code, context in context_map.items():
		stock_uom = _normalize_uom(context.get("stock_uom"))
		if stock_uom:
			context["conversion_factors"].setdefault(stock_uom, 1.0)

	uom_names = sorted(
		{
			uom
			for context in context_map.values()
			for uom in context.get("conversion_factors", {})
			if uom
		}
	)
	uom_rows = frappe.get_all(
		"UOM",
		filters={"name": ["in", uom_names]},
		fields=["name", "uom_name", "symbol", "must_be_whole_number"],
	) if uom_names else []
	metadata_map = {}
	for row in uom_rows:
		name = _normalize_uom(getattr(row, "name", None))
		if not name:
			continue
		uom_name = _normalize_uom(getattr(row, "uom_name", None))
		symbol = _normalize_uom(getattr(row, "symbol", None))
		metadata_map[name] = {
			"uom_name": uom_name,
			"symbol": symbol,
			"uom_display": resolve_uom_display_name(name, uom_name=uom_name, symbol=symbol),
			"must_be_whole_number": bool(getattr(row, "must_be_whole_number", 0)),
			"aliases": build_uom_input_aliases(name, uom_name=uom_name, symbol=symbol),
		}

	for context in context_map.values():
		context["uom_metadata"] = {
			uom: metadata_map.get(
				uom,
				{
					"uom_name": uom,
					"symbol": None,
					"uom_display": resolve_uom_display_name(uom),
					"must_be_whole_number": False,
					"aliases": build_uom_input_aliases(uom),
				},
			)
			for uom in context.get("conversion_factors", {})
		}

	return context_map


def resolve_item_uom(
	*,
	item_code: str,
	uom: str | None = None,
	uom_context_map: dict[str, dict] | None = None,
) -> dict:
	context_map = uom_context_map or build_item_uom_context_map([item_code])
	context = context_map.get(item_code)
	if not context:
		frappe.throw(_("找不到商品 {0} 的单位配置。").format(item_code))

	stock_uom = _normalize_uom(context.get("stock_uom"))
	if not stock_uom:
		frappe.throw(_("商品 {0} 缺少库存基准单位，请先补全商品单位配置。").format(item_code))

	requested_uom = _normalize_uom(uom) or stock_uom
	conversion_factors = context.get("conversion_factors", {})
	resolved_uom = requested_uom if requested_uom in conversion_factors else None
	if not resolved_uom:
		lookup = _normalize_uom_lookup(requested_uom)
		matches = []
		for candidate_uom, metadata in context.get("uom_metadata", {}).items():
			aliases = metadata.get("aliases") or build_uom_input_aliases(candidate_uom)
			if lookup and lookup in {_normalize_uom_lookup(alias) for alias in aliases}:
				matches.append(candidate_uom)
		if len(matches) == 1:
			resolved_uom = matches[0]
		elif len(matches) > 1:
			frappe.throw(
				_("商品 {0} 的单位输入 {1} 存在多个匹配：{2}，请明确选择。").format(
					item_code,
					requested_uom,
					"、".join(matches),
				)
			)
		else:
			frappe.throw(_("商品 {0} 未配置单位 {1} 的换算关系。").format(item_code, requested_uom))

	metadata = context.get("uom_metadata", {}).get(resolved_uom, {})
	return {
		"uom": resolved_uom,
		"uom_display": metadata.get("uom_display") or resolve_uom_display_name(resolved_uom),
		"stock_uom": stock_uom,
		"conversion_factor": flt(conversion_factors.get(resolved_uom) or 0),
		"must_be_whole_number": bool(metadata.get("must_be_whole_number")),
	}


def resolve_item_quantity_to_stock(
	*,
	item_code: str,
	qty,
	uom: str | None = None,
	uom_context_map: dict[str, dict] | None = None,
) -> dict:
	resolved = resolve_item_uom(
		item_code=item_code,
		uom=uom,
		uom_context_map=uom_context_map,
	)
	resolved_uom = resolved["uom"]
	stock_uom = resolved["stock_uom"]
	conversion_factor = flt(resolved["conversion_factor"] or 0)
	if conversion_factor <= 0:
		frappe.throw(_("商品 {0} 未配置单位 {1} 的换算系数。").format(item_code, resolved_uom))

	resolved_qty = flt(qty or 0)
	if resolved.get("must_be_whole_number") and abs(resolved_qty - round(resolved_qty)) > 1e-9:
		frappe.throw(_("单位 {0} 只允许录入整数数量。").format(resolved.get("uom_display") or resolved_uom))
	return {
		"uom": resolved_uom,
		"uom_display": resolved.get("uom_display"),
		"stock_uom": stock_uom,
		"conversion_factor": conversion_factor,
		"qty": resolved_qty,
		"stock_qty": flt(resolved_qty * conversion_factor),
	}
