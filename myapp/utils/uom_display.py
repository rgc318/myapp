from __future__ import annotations

import re

import frappe

from myapp.utils.standard_uoms import STANDARD_UOM_DISPLAY_ALIASES


_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")
_COMMON_UOM_DISPLAY_NAMES = {
	"NOS": "件",
	"NO": "件",
	"PCS": "件",
	"PC": "件",
	"PIECE": "件",
	"PIECES": "件",
	"BOX": "箱",
	"BOXES": "箱",
	"CASE": "箱",
	"CASES": "箱",
	"BOTTLE": "瓶",
	"BOTTLES": "瓶",
	"BAG": "袋",
	"BAGS": "袋",
	"KG": "千克",
	"KGS": "千克",
	"G": "克",
	"GRAM": "克",
	"GRAMS": "克",
	"L": "升",
	"LTR": "升",
	"LITER": "升",
	"LITRE": "升",
	"ML": "毫升",
	"M": "米",
	"METER": "米",
	"METRE": "米",
	"YARD": "码",
	"YD": "码",
	"YDS": "码",
	"CM": "厘米",
	"MM": "毫米",
	"SET": "套",
	"SETS": "套",
	"PACK": "包",
	"PACKS": "包",
	"ROLL": "卷",
	"ROLLS": "卷",
}
_COMMON_UOM_DISPLAY_NAMES.update(STANDARD_UOM_DISPLAY_ALIASES)


def normalize_uom_text(value: str | None) -> str | None:
	normalized = (value or "").strip()
	return normalized or None


def looks_like_chinese(value: str | None) -> bool:
	normalized = normalize_uom_text(value)
	return bool(normalized and _CJK_PATTERN.search(normalized))


def resolve_uom_display_name(
	uom: str | None,
	*,
	uom_name: str | None = None,
	symbol: str | None = None,
) -> str | None:
	candidates = [normalize_uom_text(symbol), normalize_uom_text(uom_name), normalize_uom_text(uom)]
	for candidate in candidates:
		if looks_like_chinese(candidate):
			return candidate

	normalized_uom = normalize_uom_text(uom)
	if normalized_uom:
		mapped = _COMMON_UOM_DISPLAY_NAMES.get(normalized_uom.upper())
		if mapped:
			return mapped

	return normalize_uom_text(uom_name) or normalized_uom


def build_uom_display_map(uom_names: list[str] | tuple[str, ...]) -> dict[str, str]:
	normalized_names = [name for name in {normalize_uom_text(row) for row in uom_names or []} if name]
	if not normalized_names:
		return {}

	try:
		rows = frappe.get_all(
			"UOM",
			filters={"name": ["in", normalized_names]},
			fields=["name", "uom_name", "symbol"],
			limit_page_length=0,
		)
	except Exception:
		rows = []
	meta_map = {row.name: row for row in rows}
	return {
		name: resolve_uom_display_name(
			name,
			uom_name=getattr(meta_map.get(name), "uom_name", None),
			symbol=getattr(meta_map.get(name), "symbol", None),
		)
		or name
		for name in normalized_names
	}
