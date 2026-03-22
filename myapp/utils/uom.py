import frappe
from frappe import _
from frappe.utils import flt


def _normalize_uom(value: str | None) -> str | None:
	normalized = (value or "").strip()
	return normalized or None


def build_item_uom_context_map(item_codes: list[str]) -> dict[str, dict]:
	item_codes = [code for code in {(_normalize_uom(item_code) or "") for item_code in item_codes} if code]
	if not item_codes:
		return {}

	item_rows = frappe.get_all("Item", filters={"name": ["in", item_codes]}, fields=["name", "stock_uom"])
	context_map = {
		row.name: {
			"stock_uom": _normalize_uom(row.stock_uom),
			"conversion_factors": {},
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
		context_map.setdefault(parent, {"stock_uom": None, "conversion_factors": {}})
		context_map[parent]["conversion_factors"][uom] = flt(getattr(row, "conversion_factor", 0) or 0)

	for item_code, context in context_map.items():
		stock_uom = _normalize_uom(context.get("stock_uom"))
		if stock_uom:
			context["conversion_factors"].setdefault(stock_uom, 1.0)

	return context_map


def resolve_item_quantity_to_stock(
	*,
	item_code: str,
	qty,
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

	resolved_uom = _normalize_uom(uom) or stock_uom
	conversion_factor = flt(context.get("conversion_factors", {}).get(resolved_uom) or 0)
	if resolved_uom == stock_uom:
		conversion_factor = 1.0
	if conversion_factor <= 0:
		frappe.throw(_("商品 {0} 未配置单位 {1} 的换算系数。").format(item_code, resolved_uom))

	resolved_qty = flt(qty or 0)
	return {
		"uom": resolved_uom,
		"stock_uom": stock_uom,
		"conversion_factor": conversion_factor,
		"qty": resolved_qty,
		"stock_qty": flt(resolved_qty * conversion_factor),
	}
