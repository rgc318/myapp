import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate


DEFAULT_STOCK_LEDGER_PAGE_SIZE = 20
MAX_STOCK_LEDGER_PAGE_SIZE = 100
MAX_STOCK_LEDGER_RANGE_DAYS = 366
DEFAULT_STOCK_SUMMARY_PAGE_SIZE = 20
MAX_STOCK_SUMMARY_PAGE_SIZE = 100
DEFAULT_LOW_STOCK_THRESHOLD = 10


def _normalize_text(value: str | None):
	resolved = (value or "").strip()
	return resolved or None


def _resolve_positive_int(value: int | str | None, *, default: int, minimum: int = 1, maximum: int | None = None):
	resolved = cint(value) if str(value).strip() else default
	if maximum is not None:
		resolved = min(maximum, resolved)
	return max(minimum, resolved)


def _resolve_stock_ledger_date_range(date_from: str | None = None, date_to: str | None = None):
	end = getdate(date_to or nowdate())
	start = getdate(date_from or add_days(end, -29))
	if start > end:
		frappe.throw(_("date_from 不能晚于 date_to。"))
	if (end - start).days + 1 > MAX_STOCK_LEDGER_RANGE_DAYS:
		frappe.throw(_("库存流水时间范围不能超过 366 天。"))
	return str(start), str(end)


def _build_stock_ledger_filters(
	*,
	company: str | None,
	date_from: str,
	date_to: str,
	item_code: str | None,
	warehouse: str | None,
	voucher_type: str | None,
	voucher_no: str | None,
):
	filters: list[list[str]] = [
		["posting_date", "between", [date_from, date_to]],
	]
	if company:
		filters.append(["company", "=", company])
	if item_code:
		filters.append(["item_code", "=", item_code])
	if warehouse:
		filters.append(["warehouse", "=", warehouse])
	if voucher_type:
		filters.append(["voucher_type", "=", voucher_type])
	if voucher_no:
		filters.append(["voucher_no", "=", voucher_no])
	return filters


def _get_item_name_map(item_codes: list[str]):
	unique_item_codes = sorted({item_code for item_code in item_codes if item_code})
	if not unique_item_codes:
		return {}
	rows = frappe.get_all(
		"Item",
		filters={"name": ["in", unique_item_codes]},
		fields=["name", "item_name"],
	)
	return {row.name: row.item_name for row in rows}


def _get_item_snapshot_map(item_codes: list[str]):
	unique_item_codes = sorted({item_code for item_code in item_codes if item_code})
	if not unique_item_codes:
		return {}
	rows = frappe.get_all(
		"Item",
		filters={"name": ["in", unique_item_codes]},
		fields=["name", "item_name", "stock_uom", "disabled"],
	)
	return {
		row.name: {
			"item_name": row.item_name,
			"stock_uom": row.stock_uom,
			"disabled": cint(row.disabled),
		}
		for row in rows
	}


def _search_inventory_item_codes(search_key: str | None):
	resolved = _normalize_text(search_key)
	if not resolved:
		return None

	rows = frappe.get_all(
		"Item",
		filters=[
			["disabled", "=", 0],
			[
				"name",
				"like",
				f"%{resolved}%",
			],
		],
		fields=["name"],
		limit_page_length=100,
	)
	if rows:
		return [row.name for row in rows]

	rows = frappe.get_all(
		"Item",
		filters=[
			["disabled", "=", 0],
			[
				"item_name",
				"like",
				f"%{resolved}%",
			],
		],
		fields=["name"],
		limit_page_length=100,
	)
	return [row.name for row in rows]


def _get_company_warehouses(company: str | None):
	resolved_company = _normalize_text(company)
	if not resolved_company:
		return None
	rows = frappe.get_all(
		"Warehouse",
		filters={"company": resolved_company, "disabled": 0},
		fields=["name", "company"],
	)
	return [row.name for row in rows]


def _get_warehouse_company_map(warehouses: list[str]):
	unique_warehouses = sorted({warehouse for warehouse in warehouses if warehouse})
	if not unique_warehouses:
		return {}
	rows = frappe.get_all(
		"Warehouse",
		filters={"name": ["in", unique_warehouses]},
		fields=["name", "company"],
	)
	return {row.name: row.company for row in rows}


def _build_stock_summary_filters(
	*,
	company: str | None,
	item_codes: list[str] | None,
	warehouse: str | None,
):
	filters = {}
	if warehouse:
		filters["warehouse"] = warehouse
	elif company:
		warehouses = _get_company_warehouses(company)
		if warehouses is not None:
			filters["warehouse"] = ["in", warehouses or ["__no_warehouse__"]]
	if item_codes is not None:
		filters["item_code"] = ["in", item_codes or ["__no_item__"]]
	return filters


def _stock_status_matches(row: dict, *, stock_status: str, low_stock_threshold: float):
	actual_qty = flt(row.get("actual_qty"))
	if stock_status == "in_stock":
		return actual_qty > 0
	if stock_status == "low_stock":
		return 0 < actual_qty <= low_stock_threshold
	if stock_status == "out_of_stock":
		return actual_qty == 0
	if stock_status == "negative":
		return actual_qty < 0
	return True


def _serialize_stock_summary_rows(rows, *, item_map: dict, warehouse_company_map: dict):
	serialized = []
	for row in rows:
		item = item_map.get(row.item_code, {})
		serialized.append(
			{
				"item_code": row.item_code,
				"item_name": item.get("item_name") or row.item_code,
				"stock_uom": item.get("stock_uom"),
				"disabled": cint(item.get("disabled")),
				"warehouse": row.warehouse,
				"company": warehouse_company_map.get(row.warehouse),
				"actual_qty": flt(row.actual_qty),
				"reserved_qty": flt(getattr(row, "reserved_qty", 0)),
				"ordered_qty": flt(getattr(row, "ordered_qty", 0)),
				"indented_qty": flt(getattr(row, "indented_qty", 0)),
				"projected_qty": flt(getattr(row, "projected_qty", 0)),
				"valuation_rate": flt(getattr(row, "valuation_rate", 0)),
				"stock_value": flt(getattr(row, "stock_value", 0)),
			}
		)
	return serialized


def _build_stock_summary_totals(rows):
	return {
		"actual_qty_total": sum(flt(row.get("actual_qty")) for row in rows),
		"reserved_qty_total": sum(flt(row.get("reserved_qty")) for row in rows),
		"projected_qty_total": sum(flt(row.get("projected_qty")) for row in rows),
		"stock_value_total": sum(flt(row.get("stock_value")) for row in rows),
		"negative_count": len([row for row in rows if flt(row.get("actual_qty")) < 0]),
		"out_of_stock_count": len([row for row in rows if flt(row.get("actual_qty")) == 0]),
	}


def list_inventory_stock_summary_v1(
	company: str | None = None,
	warehouse: str | None = None,
	search_key: str | None = None,
	stock_status: str | None = "all",
	low_stock_threshold: float | int | str | None = DEFAULT_LOW_STOCK_THRESHOLD,
	page: int | str | None = 1,
	page_size: int | str | None = DEFAULT_STOCK_SUMMARY_PAGE_SIZE,
):
	resolved_company = _normalize_text(company)
	resolved_warehouse = _normalize_text(warehouse)
	resolved_stock_status = (_normalize_text(stock_status) or "all").lower()
	if resolved_stock_status not in {"all", "in_stock", "low_stock", "out_of_stock", "negative"}:
		frappe.throw(_("stock_status 参数无效。"))
	resolved_threshold = flt(low_stock_threshold)
	if resolved_threshold <= 0:
		resolved_threshold = DEFAULT_LOW_STOCK_THRESHOLD
	resolved_page = _resolve_positive_int(page, default=1, minimum=1)
	resolved_page_size = _resolve_positive_int(
		page_size,
		default=DEFAULT_STOCK_SUMMARY_PAGE_SIZE,
		minimum=1,
		maximum=MAX_STOCK_SUMMARY_PAGE_SIZE,
	)

	item_codes = _search_inventory_item_codes(search_key)
	filters = _build_stock_summary_filters(
		company=resolved_company,
		item_codes=item_codes,
		warehouse=resolved_warehouse,
	)
	bin_rows = frappe.get_all(
		"Bin",
		filters=filters,
		fields=[
			"item_code",
			"warehouse",
			"actual_qty",
			"reserved_qty",
			"ordered_qty",
			"indented_qty",
			"projected_qty",
			"valuation_rate",
			"stock_value",
		],
		order_by="item_code asc, warehouse asc",
		limit_page_length=0,
	)
	item_map = _get_item_snapshot_map([row.item_code for row in bin_rows])
	warehouse_company_map = _get_warehouse_company_map([row.warehouse for row in bin_rows])
	serialized_rows = _serialize_stock_summary_rows(
		bin_rows,
		item_map=item_map,
		warehouse_company_map=warehouse_company_map,
	)
	serialized_rows = [
		row
		for row in serialized_rows
		if not cint(row.get("disabled"))
		and _stock_status_matches(
			row,
			stock_status=resolved_stock_status,
			low_stock_threshold=resolved_threshold,
		)
	]
	total_count = len(serialized_rows)
	start = (resolved_page - 1) * resolved_page_size
	page_rows = serialized_rows[start : start + resolved_page_size]

	return {
		"status": "success",
		"message": _("库存汇总获取成功。"),
		"data": {
			"rows": page_rows,
			"summary": _build_stock_summary_totals(serialized_rows),
			"pagination": {
				"page": resolved_page,
				"page_size": resolved_page_size,
				"total_count": total_count,
				"has_more": start + len(page_rows) < total_count,
			},
			"meta": {
				"company": resolved_company,
				"warehouse": resolved_warehouse,
				"search_key": _normalize_text(search_key),
				"stock_status": resolved_stock_status,
				"low_stock_threshold": resolved_threshold,
			},
		},
	}


def _serialize_stock_ledger_rows(rows):
	item_name_map = _get_item_name_map([row.item_code for row in rows])
	serialized = []
	for row in rows:
		serialized.append(
			{
				"name": row.name,
				"posting_date": str(row.posting_date) if row.posting_date else None,
				"posting_time": str(row.posting_time) if row.posting_time else None,
				"company": row.company,
				"item_code": row.item_code,
				"item_name": item_name_map.get(row.item_code) or row.item_code,
				"warehouse": row.warehouse,
				"actual_qty": flt(row.actual_qty),
				"qty_after_transaction": flt(row.qty_after_transaction),
				"incoming_rate": flt(row.incoming_rate),
				"stock_value_difference": flt(row.stock_value_difference),
				"voucher_type": row.voucher_type,
				"voucher_no": row.voucher_no,
			}
		)
	return serialized


def list_stock_ledger_entries_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	item_code: str | None = None,
	warehouse: str | None = None,
	voucher_type: str | None = None,
	voucher_no: str | None = None,
	page: int | str | None = 1,
	page_size: int | str | None = DEFAULT_STOCK_LEDGER_PAGE_SIZE,
):
	resolved_company = _normalize_text(company)
	resolved_item_code = _normalize_text(item_code)
	resolved_warehouse = _normalize_text(warehouse)
	resolved_voucher_type = _normalize_text(voucher_type)
	resolved_voucher_no = _normalize_text(voucher_no)
	resolved_date_from, resolved_date_to = _resolve_stock_ledger_date_range(date_from, date_to)
	resolved_page = _resolve_positive_int(page, default=1, minimum=1)
	resolved_page_size = _resolve_positive_int(
		page_size,
		default=DEFAULT_STOCK_LEDGER_PAGE_SIZE,
		minimum=1,
		maximum=MAX_STOCK_LEDGER_PAGE_SIZE,
	)
	start = (resolved_page - 1) * resolved_page_size
	filters = _build_stock_ledger_filters(
		company=resolved_company,
		date_from=resolved_date_from,
		date_to=resolved_date_to,
		item_code=resolved_item_code,
		warehouse=resolved_warehouse,
		voucher_type=resolved_voucher_type,
		voucher_no=resolved_voucher_no,
	)
	total_count = frappe.db.count("Stock Ledger Entry", filters=filters)
	rows = frappe.get_all(
		"Stock Ledger Entry",
		filters=filters,
		fields=[
			"name",
			"posting_date",
			"posting_time",
			"company",
			"item_code",
			"warehouse",
			"actual_qty",
			"qty_after_transaction",
			"incoming_rate",
			"stock_value_difference",
			"voucher_type",
			"voucher_no",
		],
		order_by="posting_date desc, posting_time desc, creation desc",
		limit_start=start,
		limit_page_length=resolved_page_size,
	)

	return {
		"status": "success",
		"message": _("库存流水列表获取成功。"),
		"data": {
			"rows": _serialize_stock_ledger_rows(rows),
			"pagination": {
				"page": resolved_page,
				"page_size": resolved_page_size,
				"total_count": total_count,
				"has_more": start + len(rows) < total_count,
			},
			"meta": {
				"company": resolved_company,
				"date_from": resolved_date_from,
				"date_to": resolved_date_to,
				"item_code": resolved_item_code,
				"warehouse": resolved_warehouse,
				"voucher_type": resolved_voucher_type,
				"voucher_no": resolved_voucher_no,
			},
		},
	}
