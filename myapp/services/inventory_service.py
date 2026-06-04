import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate


DEFAULT_STOCK_LEDGER_PAGE_SIZE = 20
MAX_STOCK_LEDGER_PAGE_SIZE = 100
MAX_STOCK_LEDGER_RANGE_DAYS = 366


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
