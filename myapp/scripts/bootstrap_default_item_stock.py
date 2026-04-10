from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import asdict, dataclass

import frappe

from myapp.services.wholesale_service import update_product_v2


@dataclass
class CandidateItem:
	item_code: str
	item_name: str
	stock_uom: str
	has_bin: bool


def _to_float(value: str | float | int | None, *, label: str) -> float:
	try:
		return float(value)
	except (TypeError, ValueError) as exc:
		raise ValueError(f"{label} 必须是数字。") from exc


def _get_candidate_items(*, include_disabled: bool) -> list[CandidateItem]:
	disabled_filter = "" if include_disabled else "WHERE IFNULL(item.disabled, 0) = 0"
	rows = frappe.db.sql(
		f"""
		SELECT
			item.name AS item_code,
			item.item_name AS item_name,
			item.stock_uom AS stock_uom,
			CASE WHEN bin.item_code IS NULL THEN 0 ELSE 1 END AS has_bin
		FROM `tabItem` item
		LEFT JOIN (
			SELECT DISTINCT item_code
			FROM `tabBin`
		) bin ON bin.item_code = item.name
		{disabled_filter}
		ORDER BY item.modified DESC
		""",
		as_dict=True,
	)
	return [
		CandidateItem(
			item_code=(row.get("item_code") or "").strip(),
			item_name=(row.get("item_name") or row.get("item_code") or "").strip(),
			stock_uom=(row.get("stock_uom") or "").strip(),
			has_bin=bool(int(row.get("has_bin") or 0)),
		)
		for row in rows
		if (row.get("item_code") or "").strip() and (row.get("stock_uom") or "").strip()
	]


def _apply_target_qty(
	*,
	item: CandidateItem,
	warehouse: str,
	target_qty: float,
	valuation_rate: float | None,
	request_prefix: str,
):
	update_kwargs = {
		"warehouse": warehouse,
		"warehouse_stock_qty": target_qty,
		"warehouse_stock_uom": item.stock_uom,
		"request_id": f"{request_prefix}-{item.item_code}-{uuid.uuid4().hex[:8]}",
	}
	if valuation_rate is not None:
		update_kwargs["valuation_rate"] = valuation_rate
	update_product_v2(item_code=item.item_code, **update_kwargs)


def run(
	*,
	warehouse: str,
	final_qty: float = 0,
	seed_qty: float = 1,
	commit: bool = False,
	only_missing_records: bool = True,
	include_disabled: bool = False,
	limit: int | None = None,
	valuation_rate: float | None = None,
):
	warehouse = (warehouse or "").strip()
	if not warehouse:
		raise ValueError("warehouse 不能为空。")

	final_qty = _to_float(final_qty, label="final_qty")
	seed_qty = _to_float(seed_qty, label="seed_qty")
	if seed_qty <= 0:
		raise ValueError("seed_qty 必须大于 0。")

	items = _get_candidate_items(include_disabled=include_disabled)
	if only_missing_records:
		items = [item for item in items if not item.has_bin]
	if limit is not None and limit > 0:
		items = items[:limit]

	summary: dict[str, object] = {
		"warehouse": warehouse,
		"final_qty": final_qty,
		"seed_qty": seed_qty,
		"commit": commit,
		"only_missing_records": only_missing_records,
		"include_disabled": include_disabled,
		"candidate_count": len(items),
		"updated_count": 0,
		"seeded_to_create_record_count": 0,
		"skipped_count": 0,
		"updated_items": [],
	}

	for item in items:
		item_summary = {
			"item_code": item.item_code,
			"item_name": item.item_name,
			"stock_uom": item.stock_uom,
			"had_bin": item.has_bin,
			"final_qty": final_qty,
			"steps": [],
		}

		if not commit:
			if not item.has_bin and final_qty == 0:
				item_summary["steps"].append(
					{
						"action": "seed_then_zero",
						"seed_qty": seed_qty,
						"note": "当前商品没有库存记录，若目标为 0，需要先建一笔正库存再回调到 0。",
					}
				)
				summary["seeded_to_create_record_count"] = int(summary["seeded_to_create_record_count"]) + 1
			else:
				item_summary["steps"].append({"action": "set_target_qty", "target_qty": final_qty})
			cast_updated_items = summary["updated_items"]
			assert isinstance(cast_updated_items, list)
			cast_updated_items.append(item_summary)
			continue

		if not item.has_bin and final_qty == 0:
			_apply_target_qty(
				item=item,
				warehouse=warehouse,
				target_qty=seed_qty,
				valuation_rate=valuation_rate,
				request_prefix="bootstrap-stock-seed",
			)
			item_summary["steps"].append({"action": "seed", "target_qty": seed_qty})
			_apply_target_qty(
				item=item,
				warehouse=warehouse,
				target_qty=0,
				valuation_rate=valuation_rate,
				request_prefix="bootstrap-stock-zero",
			)
			item_summary["steps"].append({"action": "set_target_qty", "target_qty": 0})
			summary["seeded_to_create_record_count"] = int(summary["seeded_to_create_record_count"]) + 1
		else:
			_apply_target_qty(
				item=item,
				warehouse=warehouse,
				target_qty=final_qty,
				valuation_rate=valuation_rate,
				request_prefix="bootstrap-stock",
			)
			item_summary["steps"].append({"action": "set_target_qty", "target_qty": final_qty})

		frappe.db.commit()
		summary["updated_count"] = int(summary["updated_count"]) + 1
		cast_updated_items = summary["updated_items"]
		assert isinstance(cast_updated_items, list)
		cast_updated_items.append(item_summary)

	return summary


def main():
	parser = argparse.ArgumentParser(description="Bootstrap default warehouse stock records for items.")
	parser.add_argument("--site", default="localhost", help="Frappe site name.")
	parser.add_argument("--warehouse", required=True, help="Target warehouse for bootstrap stock records.")
	parser.add_argument("--final-qty", type=float, default=0, help="Final target qty after bootstrap. Default: 0.")
	parser.add_argument(
		"--seed-qty",
		type=float,
		default=1,
		help="Temporary positive qty used to materialize missing stock records when final qty is 0. Default: 1.",
	)
	parser.add_argument("--valuation-rate", type=float, default=None, help="Optional valuation rate for generated stock entries.")
	parser.add_argument("--limit", type=int, default=None, help="Optional max item count to process.")
	parser.add_argument("--include-disabled", action="store_true", help="Include disabled items.")
	parser.add_argument(
		"--all-items",
		action="store_true",
		help="Process all items, not just those missing stock records.",
	)
	parser.add_argument("--commit", action="store_true", help="Persist changes to the database.")
	args = parser.parse_args()

	frappe.init(site=args.site, sites_path="/home/frappe/frappe-bench/sites")
	frappe.connect()
	try:
		result = run(
			warehouse=args.warehouse,
			final_qty=args.final_qty,
			seed_qty=args.seed_qty,
			commit=args.commit,
			only_missing_records=not args.all_items,
			include_disabled=args.include_disabled,
			limit=args.limit,
			valuation_rate=args.valuation_rate,
		)
		print(json.dumps(result, ensure_ascii=False, indent=2))
	finally:
		frappe.destroy()


if __name__ == "__main__":
	main()
