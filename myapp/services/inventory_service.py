import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate

from myapp.utils.idempotency import run_idempotent
from myapp.utils.uom import resolve_item_quantity_to_stock
from myapp.services.data_permission_service import (
	ensure_warehouse_access,
	get_permitted_warehouse_names,
	require_doctype_permission,
)
from myapp.utils.warehouse import validate_transaction_warehouse


DEFAULT_STOCK_LEDGER_PAGE_SIZE = 20
MAX_STOCK_LEDGER_PAGE_SIZE = 100
MAX_STOCK_LEDGER_RANGE_DAYS = 366
DEFAULT_STOCK_SUMMARY_PAGE_SIZE = 20
MAX_STOCK_SUMMARY_PAGE_SIZE = 100
DEFAULT_LOW_STOCK_THRESHOLD = 10
MAX_STOCK_COUNT_ITEMS = 200


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
	rows = frappe.get_list(
		"Item",
		filters={"name": ["in", unique_item_codes]},
		fields=["name", "item_name"],
	)
	return {row.name: row.item_name for row in rows}


def _get_item_snapshot_map(item_codes: list[str]):
	unique_item_codes = sorted({item_code for item_code in item_codes if item_code})
	if not unique_item_codes:
		return {}
	rows = frappe.get_list(
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

	rows = frappe.get_list(
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

	rows = frappe.get_list(
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
	rows = frappe.get_list(
		"Warehouse",
		filters={"company": resolved_company, "disabled": 0, "is_group": 0},
		fields=["name", "company"],
	)
	return [row.name for row in rows]


def _get_warehouse_company_map(warehouses: list[str]):
	unique_warehouses = sorted({warehouse for warehouse in warehouses if warehouse})
	if not unique_warehouses:
		return {}
	rows = frappe.get_list(
		"Warehouse",
		filters={"name": ["in", unique_warehouses]},
		fields=["name", "company"],
	)
	return {row.name: row.company for row in rows}


def _get_item_stock_context(item_code: str):
	item = frappe.db.get_value(
		"Item",
		item_code,
		["name", "item_name", "stock_uom", "disabled", "is_stock_item"],
		as_dict=True,
	)
	if not item:
		frappe.throw(_("商品 {0} 不存在。").format(item_code))
	if cint(item.disabled):
		frappe.throw(_("商品 {0} 已停用，不能进行库存操作。").format(item_code))
	if not cint(item.is_stock_item):
		frappe.throw(_("商品 {0} 不是库存商品。").format(item_code))
	return item


def _resolve_warehouse_company(warehouse: str):
	return validate_transaction_warehouse(warehouse).company


def _get_bin_actual_qty(item_code: str, warehouse: str):
	return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty") or 0)


def _serialize_inventory_stock_entry(stock_entry, *, item, quantity_context: dict, extra: dict | None = None):
	data = {
		"stock_entry": stock_entry.name,
		"item_code": item.name,
		"item_name": item.item_name,
		"stock_uom": quantity_context["stock_uom"],
		"input_qty": quantity_context["qty"],
		"input_uom": quantity_context["uom"],
		"stock_qty": quantity_context["stock_qty"],
		"conversion_factor": quantity_context["conversion_factor"],
	}
	data.update(extra or {})
	return data


def _create_inventory_transfer_entry(
	*,
	item_code: str,
	source_warehouse: str,
	target_warehouse: str,
	stock_qty: float,
	company: str,
	posting_date: str | None,
	remarks: str | None,
):
	stock_entry = frappe.new_doc("Stock Entry")
	stock_entry.stock_entry_type = "Material Transfer"
	stock_entry.purpose = "Material Transfer"
	stock_entry.company = company
	if posting_date:
		stock_entry.posting_date = posting_date
	if remarks:
		stock_entry.remarks = remarks
	stock_entry.append(
		"items",
		{
			"item_code": item_code,
			"qty": stock_qty,
			"s_warehouse": source_warehouse,
			"t_warehouse": target_warehouse,
			"allow_zero_valuation_rate": 1,
		},
	)
	stock_entry.insert()
	stock_entry.submit()
	return stock_entry


def _create_inventory_adjustment_entry(
	*,
	item_code: str,
	warehouse: str,
	qty_delta: float,
	company: str,
	valuation_rate: float,
	posting_date: str | None,
	remarks: str | None,
):
	stock_entry = frappe.new_doc("Stock Entry")
	is_receipt = qty_delta > 0
	stock_entry.stock_entry_type = "Material Receipt" if is_receipt else "Material Issue"
	stock_entry.purpose = "Material Receipt" if is_receipt else "Material Issue"
	stock_entry.company = company
	if posting_date:
		stock_entry.posting_date = posting_date
	if remarks:
		stock_entry.remarks = remarks

	item_row = {
		"item_code": item_code,
		"qty": abs(qty_delta),
		"basic_rate": valuation_rate,
		"valuation_rate": valuation_rate,
		"allow_zero_valuation_rate": 1,
	}
	if is_receipt:
		item_row["t_warehouse"] = warehouse
	else:
		item_row["s_warehouse"] = warehouse

	stock_entry.append("items", item_row)
	stock_entry.insert()
	stock_entry.submit()
	return stock_entry


def _create_stock_reconciliation(
	*,
	company: str,
	items: list[dict],
	posting_date: str | None,
	remarks: str | None,
):
	reconciliation = frappe.new_doc("Stock Reconciliation")
	reconciliation.company = company
	reconciliation.purpose = "Stock Reconciliation"
	if posting_date:
		reconciliation.posting_date = posting_date
	if remarks:
		reconciliation.remarks = remarks

	for item in items:
		reconciliation.append("items", item)

	reconciliation.insert()
	reconciliation.submit()
	return reconciliation


def _serialize_stock_count_row(
	*,
	item,
	warehouse: str,
	company: str,
	quantity_context: dict,
	current_stock_qty: float,
	valuation_rate: float,
):
	counted_stock_qty = flt(quantity_context["stock_qty"])
	qty_delta = flt(counted_stock_qty - current_stock_qty)
	return {
		"item_code": item.name,
		"item_name": item.item_name,
		"warehouse": warehouse,
		"company": company,
		"stock_uom": quantity_context["stock_uom"],
		"input_qty": quantity_context["qty"],
		"input_uom": quantity_context["uom"],
		"counted_stock_qty": counted_stock_qty,
		"current_stock_qty": current_stock_qty,
		"qty_delta": qty_delta,
		"conversion_factor": quantity_context["conversion_factor"],
		"valuation_rate": valuation_rate,
		"has_difference": bool(qty_delta),
	}


def _normalize_stock_count_items(items):
	if isinstance(items, str):
		try:
			items = frappe.parse_json(items)
		except Exception:
			frappe.throw(_("盘点明细格式无效。"))
	if not isinstance(items, list):
		frappe.throw(_("盘点明细必须是数组。"))
	if not items:
		frappe.throw(_("盘点明细不能为空。"))
	if len(items) > MAX_STOCK_COUNT_ITEMS:
		frappe.throw(_("单次盘点明细不能超过 {0} 行。").format(MAX_STOCK_COUNT_ITEMS))
	return items


def _build_stock_summary_filters(
	*,
	company: str | None,
	item_codes: list[str] | None,
	warehouse: str | None,
):
	filters = {}
	if warehouse:
		filters["warehouse"] = ensure_warehouse_access(
			warehouse,
			company=company,
			applicable_for="Bin",
		)
	else:
		warehouses = get_permitted_warehouse_names(company=company, applicable_for="Bin")
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
	require_doctype_permission("Bin", "read")
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
	bin_rows = frappe.get_list(
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


def transfer_inventory_stock_v1(
	item_code: str,
	source_warehouse: str,
	target_warehouse: str,
	qty,
	uom: str | None = None,
	posting_date: str | None = None,
	remarks: str | None = None,
	request_id: str | None = None,
):
	resolved_item_code = _normalize_text(item_code)
	resolved_source_warehouse = _normalize_text(source_warehouse)
	resolved_target_warehouse = _normalize_text(target_warehouse)
	if not resolved_item_code:
		frappe.throw(_("商品编码不能为空。"))
	if not resolved_source_warehouse:
		frappe.throw(_("转出仓库不能为空。"))
	if not resolved_target_warehouse:
		frappe.throw(_("转入仓库不能为空。"))
	if resolved_source_warehouse == resolved_target_warehouse:
		frappe.throw(_("转出仓库和转入仓库不能相同。"))

	def _transfer_inventory_stock():
		item = _get_item_stock_context(resolved_item_code)
		source_company = _resolve_warehouse_company(resolved_source_warehouse)
		target_company = _resolve_warehouse_company(resolved_target_warehouse)
		if source_company != target_company:
			frappe.throw(_("转仓只能在同一公司仓库之间进行。"))

		quantity_context = resolve_item_quantity_to_stock(
			item_code=item.name,
			qty=qty,
			uom=uom,
		)
		stock_qty = flt(quantity_context["stock_qty"])
		if stock_qty <= 0:
			frappe.throw(_("转仓数量必须大于 0。"))

		current_qty = _get_bin_actual_qty(item.name, resolved_source_warehouse)
		if current_qty < stock_qty:
			frappe.throw(_("转出仓库库存不足，当前库存为 {0}。").format(current_qty))

		stock_entry = _create_inventory_transfer_entry(
			item_code=item.name,
			source_warehouse=resolved_source_warehouse,
			target_warehouse=resolved_target_warehouse,
			stock_qty=stock_qty,
			company=source_company,
			posting_date=_normalize_text(posting_date) or None,
			remarks=_normalize_text(remarks) or None,
		)
		return {
			"status": "success",
			"message": _("库存转仓成功。"),
			"data": _serialize_inventory_stock_entry(
				stock_entry,
				item=item,
				quantity_context=quantity_context,
				extra={
					"company": source_company,
					"source_warehouse": resolved_source_warehouse,
					"target_warehouse": resolved_target_warehouse,
					"source_qty_before": current_qty,
					"source_qty_after": flt(current_qty - stock_qty),
				},
			),
		}

	return run_idempotent("transfer_inventory_stock_v1", request_id, _transfer_inventory_stock)


def reconcile_inventory_stock_v1(
	item_code: str,
	warehouse: str,
	target_qty,
	uom: str | None = None,
	valuation_rate: float | int | str | None = None,
	posting_date: str | None = None,
	remarks: str | None = None,
	request_id: str | None = None,
):
	resolved_item_code = _normalize_text(item_code)
	resolved_warehouse = _normalize_text(warehouse)
	if not resolved_item_code:
		frappe.throw(_("商品编码不能为空。"))
	if not resolved_warehouse:
		frappe.throw(_("仓库不能为空。"))

	def _reconcile_inventory_stock():
		item = _get_item_stock_context(resolved_item_code)
		company = _resolve_warehouse_company(resolved_warehouse)
		quantity_context = resolve_item_quantity_to_stock(
			item_code=item.name,
			qty=target_qty,
			uom=uom,
		)
		target_stock_qty = flt(quantity_context["stock_qty"])
		if target_stock_qty < 0:
			frappe.throw(_("盘点目标库存不能为负数。"))

		current_qty = _get_bin_actual_qty(item.name, resolved_warehouse)
		qty_delta = flt(target_stock_qty - current_qty)
		if not qty_delta:
			return {
				"status": "success",
				"message": _("库存数量无变化。"),
				"data": {
					"stock_entry": None,
					"item_code": item.name,
					"item_name": item.item_name,
					"warehouse": resolved_warehouse,
					"company": company,
					"stock_uom": quantity_context["stock_uom"],
					"input_qty": quantity_context["qty"],
					"input_uom": quantity_context["uom"],
					"target_stock_qty": target_stock_qty,
					"current_stock_qty": current_qty,
					"qty_delta": 0,
					"conversion_factor": quantity_context["conversion_factor"],
				},
			}

		stock_entry = _create_inventory_adjustment_entry(
			item_code=item.name,
			warehouse=resolved_warehouse,
			qty_delta=qty_delta,
			company=company,
			valuation_rate=flt(valuation_rate or 0),
			posting_date=_normalize_text(posting_date) or None,
			remarks=_normalize_text(remarks) or None,
		)
		return {
			"status": "success",
			"message": _("库存盘点调整成功。"),
			"data": _serialize_inventory_stock_entry(
				stock_entry,
				item=item,
				quantity_context=quantity_context,
				extra={
					"warehouse": resolved_warehouse,
					"company": company,
					"target_stock_qty": target_stock_qty,
					"current_stock_qty": current_qty,
					"qty_delta": qty_delta,
				},
			),
		}

	return run_idempotent("reconcile_inventory_stock_v1", request_id, _reconcile_inventory_stock)


def submit_inventory_stock_count_v1(
	items,
	company: str | None = None,
	posting_date: str | None = None,
	remarks: str | None = None,
	request_id: str | None = None,
):
	normalized_items = _normalize_stock_count_items(items)
	resolved_company = _normalize_text(company)
	resolved_posting_date = _normalize_text(posting_date) or None
	resolved_remarks = _normalize_text(remarks) or None

	def _submit_inventory_stock_count():
		serialized_rows = []
		reconciliation_items = []
		row_keys = set()
		count_company = resolved_company

		for index, row in enumerate(normalized_items, start=1):
			if not isinstance(row, dict):
				frappe.throw(_("第 {0} 行盘点明细格式无效。").format(index))
			item_code = _normalize_text(row.get("item_code"))
			warehouse = _normalize_text(row.get("warehouse"))
			if not item_code:
				frappe.throw(_("第 {0} 行商品编码不能为空。").format(index))
			if not warehouse:
				frappe.throw(_("第 {0} 行仓库不能为空。").format(index))

			row_key = (item_code, warehouse)
			if row_key in row_keys:
				frappe.throw(_("盘点明细存在重复商品和仓库：{0} / {1}。").format(item_code, warehouse))
			row_keys.add(row_key)

			item = _get_item_stock_context(item_code)
			row_company = _resolve_warehouse_company(warehouse)
			if count_company and row_company != count_company:
				frappe.throw(_("盘点明细必须属于同一公司。"))
			count_company = count_company or row_company

			quantity_context = resolve_item_quantity_to_stock(
				item_code=item.name,
				qty=row.get("counted_qty"),
				uom=row.get("uom"),
			)
			counted_stock_qty = flt(quantity_context["stock_qty"])
			if counted_stock_qty < 0:
				frappe.throw(_("第 {0} 行盘点数量不能为负数。").format(index))

			current_qty = _get_bin_actual_qty(item.name, warehouse)
			valuation_rate = flt(row.get("valuation_rate") or 0)
			serialized_row = _serialize_stock_count_row(
				item=item,
				warehouse=warehouse,
				company=row_company,
				quantity_context=quantity_context,
				current_stock_qty=current_qty,
				valuation_rate=valuation_rate,
			)
			serialized_rows.append(serialized_row)
			if serialized_row["has_difference"]:
				reconciliation_items.append(
					{
						"item_code": item.name,
						"warehouse": warehouse,
						"qty": counted_stock_qty,
						"valuation_rate": valuation_rate,
					}
				)

		if not reconciliation_items:
			return {
				"status": "success",
				"message": _("盘点数量无变化。"),
				"data": {
					"stock_reconciliation": None,
					"company": count_company,
					"posting_date": resolved_posting_date,
					"rows": serialized_rows,
					"difference_count": 0,
				},
			}

		reconciliation = _create_stock_reconciliation(
			company=count_company,
			items=reconciliation_items,
			posting_date=resolved_posting_date,
			remarks=resolved_remarks,
		)
		return {
			"status": "success",
			"message": _("库存批量盘点已提交。"),
			"data": {
				"stock_reconciliation": reconciliation.name,
				"company": count_company,
				"posting_date": resolved_posting_date,
				"rows": serialized_rows,
				"difference_count": len(reconciliation_items),
			},
		}

	return run_idempotent("submit_inventory_stock_count_v1", request_id, _submit_inventory_stock_count)


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
	require_doctype_permission("Stock Ledger Entry", "read")
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
	total_count = len(
		frappe.get_list(
			"Stock Ledger Entry",
			filters=filters,
			pluck="name",
			limit_page_length=0,
		)
	)
	rows = frappe.get_list(
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
