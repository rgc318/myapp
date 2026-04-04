import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate


MAX_REPORT_LIMIT = 50
DEFAULT_REPORT_LIMIT = 10
MAX_REPORT_RANGE_DAYS = 366
DEFAULT_CASHFLOW_ENTRY_PAGE_SIZE = 20
MAX_CASHFLOW_ENTRY_PAGE_SIZE = 100
REPORT_INDEX_HINTS = {
	"tabSales Order": "idx_myapp_so_company_docstatus_date_customer",
	"tabPurchase Order": "idx_myapp_po_company_docstatus_date_supplier",
	"tabSales Invoice": "idx_myapp_sinv_company_docstatus_return_date_customer",
	"tabPurchase Invoice": "idx_myapp_pinv_company_docstatus_return_date_supplier",
	"tabPayment Entry": "idx_myapp_pe_company_docstatus_date_type",
}


def _resolve_report_limit(limit: int | str | None):
	value = cint(limit) if str(limit).strip() else DEFAULT_REPORT_LIMIT
	return max(1, min(MAX_REPORT_LIMIT, value))


def _resolve_report_date_range(date_from: str | None = None, date_to: str | None = None):
	end = getdate(date_to or nowdate())
	start = getdate(date_from or add_days(end, -29))
	if start > end:
		frappe.throw(_("date_from 不能晚于 date_to。"))
	if (end - start).days + 1 > MAX_REPORT_RANGE_DAYS:
		frappe.throw(_("报表时间范围不能超过 366 天。"))
	return str(start), str(end)


def _normalize_company(company: str | None):
	resolved = (company or "").strip()
	return resolved or None


def _resolve_positive_int(value: int | str | None, *, default: int, minimum: int = 1, maximum: int | None = None):
	resolved = cint(value) if str(value).strip() else default
	if maximum is not None:
		resolved = min(maximum, resolved)
	return max(minimum, resolved)


def _build_where_clause(*, date_field: str, company: str | None, date_from: str, date_to: str, extra_sql: str | None = None):
	clauses = [
		"docstatus = 1",
		f"`{date_field}` between %s and %s",
	]
	params = [date_from, date_to]
	if company:
		clauses.append("company = %s")
		params.append(company)
	if extra_sql:
		clauses.append(extra_sql)
	return " AND ".join(clauses), params


def _get_report_table_sql(table_name: str):
	index_name = REPORT_INDEX_HINTS.get(table_name)
	if not index_name:
		return f"`{table_name}`"
	return f"`{table_name}` FORCE INDEX (`{index_name}`)"


def _make_grouped_rows(
	table_name: str,
	*,
	party_field: str,
	date_field: str,
	company: str | None,
	date_from: str,
	date_to: str,
	limit: int,
	amount_expr: str,
	extra_filters: dict | None = None,
	select_fields: tuple[str, ...] | None = None,
	order_by: str | None = None,
):
	extra_sql = None
	if extra_filters:
		extra_sql = " AND ".join(f"`{key}` = %s" for key in extra_filters)
	where_sql, params = _build_where_clause(
		date_field=date_field,
		company=company,
		date_from=date_from,
		date_to=date_to,
		extra_sql=extra_sql,
	)
	if extra_filters:
		params.extend(extra_filters.values())

	select_sql = ", ".join(select_fields or ())
	if select_sql:
		select_sql = f"{select_sql}, "

	return frappe.db.sql(
		f"""
		SELECT
			{select_sql}
			`{party_field}` AS name,
			COUNT(name) AS count,
			SUM({amount_expr}) AS amount
		FROM {_get_report_table_sql(table_name)}
		WHERE {where_sql}
		GROUP BY `{party_field}`
		ORDER BY {order_by or "amount desc"}
		LIMIT %s
		""",
		(*params, limit),
		as_dict=True,
	)


def _make_invoice_grouped_rows(
	table_name: str,
	*,
	party_field: str,
	date_field: str,
	company: str | None,
	date_from: str,
	date_to: str,
	limit: int,
):
	total_expr = "ifnull(rounded_total, ifnull(grand_total, 0))"
	outstanding_expr = "ifnull(outstanding_amount, 0)"
	paid_expr = f"greatest(({total_expr}) - ({outstanding_expr}), 0)"
	where_sql, params = _build_where_clause(
		date_field=date_field,
		company=company,
		date_from=date_from,
		date_to=date_to,
		extra_sql="is_return = 0",
	)
	return frappe.db.sql(
		f"""
		SELECT
			`{party_field}` AS name,
			COUNT(name) AS count,
			SUM({total_expr}) AS total_amount,
			SUM({paid_expr}) AS paid_amount,
			SUM({outstanding_expr}) AS outstanding_amount
		FROM {_get_report_table_sql(table_name)}
		WHERE {where_sql}
		GROUP BY `{party_field}`
		ORDER BY outstanding_amount DESC
		LIMIT %s
		""",
		(*params, limit),
		as_dict=True,
	)


def _make_scalar_aggregate(
	table_name: str,
	*,
	date_field: str,
	aggregate_field_sql: str,
	company: str | None,
	date_from: str,
	date_to: str,
	extra_sql: str | None = None,
):
	where_sql, params = _build_where_clause(
		date_field=date_field,
		company=company,
		date_from=date_from,
		date_to=date_to,
		extra_sql=extra_sql,
	)
	rows = frappe.db.sql(
		f"""
		SELECT SUM({aggregate_field_sql}) AS total_amount
		FROM {_get_report_table_sql(table_name)}
		WHERE {where_sql}
		""",
		params,
		as_dict=True,
	)
	if not rows:
		return 0.0
	return flt(getattr(rows[0], "total_amount", 0) or 0)


def _make_recent_cashflow_rows(*, company: str | None, date_from: str, date_to: str, limit: int):
	return _make_cashflow_entry_rows(
		company=company,
		date_from=date_from,
		date_to=date_to,
		limit=limit,
		offset=0,
	)


def _make_cashflow_entry_rows(*, company: str | None, date_from: str, date_to: str, limit: int, offset: int):
	where_sql, params = _build_where_clause(
		date_field="posting_date",
		company=company,
		date_from=date_from,
		date_to=date_to,
	)
	return frappe.db.sql(
		f"""
		SELECT
			name,
			posting_date,
			payment_type,
			party_type,
			party,
			mode_of_payment,
			paid_amount,
			received_amount,
			reference_no
		FROM {_get_report_table_sql("tabPayment Entry")}
		WHERE {where_sql}
		ORDER BY posting_date DESC, modified DESC
		LIMIT %s OFFSET %s
		""",
		(*params, limit, offset),
		as_dict=True,
	)


def _count_cashflow_entries(*, company: str | None, date_from: str, date_to: str):
	where_sql, params = _build_where_clause(
		date_field="posting_date",
		company=company,
		date_from=date_from,
		date_to=date_to,
	)
	rows = frappe.db.sql(
		f"""
		SELECT COUNT(name) AS total_count
		FROM {_get_report_table_sql("tabPayment Entry")}
		WHERE {where_sql}
		""",
		params,
		as_dict=True,
	)
	if not rows:
		return 0
	return cint(getattr(rows[0], "total_count", 0) or 0)


def _make_cashflow_trend_rows(*, company: str | None, date_from: str, date_to: str):
	where_sql, params = _build_where_clause(
		date_field="posting_date",
		company=company,
		date_from=date_from,
		date_to=date_to,
	)
	return frappe.db.sql(
		f"""
		SELECT
			posting_date AS trend_date,
			COUNT(name) AS count,
			SUM(
				CASE
					WHEN payment_type = 'Receive' THEN IFNULL(received_amount, IFNULL(paid_amount, 0))
					ELSE 0
				END
			) AS in_amount,
			SUM(
				CASE
					WHEN payment_type = 'Pay' THEN IFNULL(paid_amount, IFNULL(received_amount, 0))
					ELSE 0
				END
			) AS out_amount
		FROM {_get_report_table_sql("tabPayment Entry")}
		WHERE {where_sql}
		GROUP BY posting_date
		ORDER BY posting_date ASC
		""",
		params,
		as_dict=True,
	)


def _make_payment_type_totals(*, company: str | None, date_from: str, date_to: str):
	where_sql, params = _build_where_clause(
		date_field="posting_date",
		company=company,
		date_from=date_from,
		date_to=date_to,
	)
	return frappe.db.sql(
		f"""
		SELECT
			payment_type,
			SUM(IFNULL(received_amount, 0)) AS total_received_amount,
			SUM(IFNULL(paid_amount, 0)) AS total_paid_amount
		FROM {_get_report_table_sql("tabPayment Entry")}
		WHERE {where_sql}
		GROUP BY payment_type
		""",
		params,
		as_dict=True,
	)


def _make_sales_trend_rows(*, company: str | None, date_from: str, date_to: str, limit: int):
	where_sql, params = _build_where_clause(
		date_field="transaction_date",
		company=company,
		date_from=date_from,
		date_to=date_to,
	)
	return frappe.db.sql(
		f"""
		SELECT
			transaction_date AS trend_date,
			COUNT(name) AS count,
			SUM(ifnull(rounded_total, ifnull(grand_total, 0))) AS amount
		FROM {_get_report_table_sql("tabSales Order")}
		WHERE {where_sql}
		GROUP BY transaction_date
		ORDER BY transaction_date ASC
		LIMIT %s
		""",
		(*params, max(7, limit * 4)),
		as_dict=True,
	)


def _make_sales_product_rows(*, company: str | None, date_from: str, date_to: str, limit: int):
	params = [date_from, date_to]
	company_sql = ""
	if company:
		company_sql = " AND so.company = %s"
		params.append(company)
	return frappe.db.sql(
		f"""
		SELECT
			COALESCE(soi.item_code, soi.item_name) AS item_key,
			MAX(COALESCE(soi.item_name, soi.item_code, "未命名商品")) AS item_name,
			SUM(ifnull(soi.qty, 0)) AS qty,
			SUM(ifnull(soi.base_amount, ifnull(soi.amount, 0))) AS amount
		FROM `tabSales Order Item` soi
		INNER JOIN `tabSales Order` so FORCE INDEX (`idx_myapp_so_company_docstatus_date_customer`) ON so.name = soi.parent
		WHERE so.docstatus = 1
			AND so.transaction_date between %s and %s
			{company_sql}
		GROUP BY COALESCE(soi.item_code, soi.item_name)
		ORDER BY amount DESC
		LIMIT %s
		""",
		(*params, limit),
		as_dict=True,
	)


def _make_purchase_trend_rows(*, company: str | None, date_from: str, date_to: str, limit: int):
	where_sql, params = _build_where_clause(
		date_field="transaction_date",
		company=company,
		date_from=date_from,
		date_to=date_to,
	)
	return frappe.db.sql(
		f"""
		SELECT
			transaction_date AS trend_date,
			COUNT(name) AS count,
			SUM(ifnull(rounded_total, ifnull(grand_total, 0))) AS amount
		FROM {_get_report_table_sql("tabPurchase Order")}
		WHERE {where_sql}
		GROUP BY transaction_date
		ORDER BY transaction_date ASC
		LIMIT %s
		""",
		(*params, max(7, limit * 4)),
		as_dict=True,
	)


def _make_purchase_product_rows(*, company: str | None, date_from: str, date_to: str, limit: int):
	params = [date_from, date_to]
	company_sql = ""
	if company:
		company_sql = " AND po.company = %s"
		params.append(company)
	return frappe.db.sql(
		f"""
		SELECT
			COALESCE(poi.item_code, poi.item_name) AS item_key,
			MAX(COALESCE(poi.item_name, poi.item_code, "未命名商品")) AS item_name,
			SUM(ifnull(poi.qty, 0)) AS qty,
			SUM(ifnull(poi.base_amount, ifnull(poi.amount, 0))) AS amount
		FROM `tabPurchase Order Item` poi
		INNER JOIN `tabPurchase Order` po FORCE INDEX (`idx_myapp_po_company_docstatus_date_supplier`) ON po.name = poi.parent
		WHERE po.docstatus = 1
			AND po.transaction_date between %s and %s
			{company_sql}
		GROUP BY COALESCE(poi.item_code, poi.item_name)
		ORDER BY amount DESC
		LIMIT %s
		""",
		(*params, limit),
		as_dict=True,
	)


def _make_sales_hourly_rows(*, company: str | None, trend_date: str):
	params = [trend_date]
	company_sql = ""
	if company:
		company_sql = " AND company = %s"
		params.append(company)
	return frappe.db.sql(
		f"""
		SELECT
			HOUR(creation) AS trend_hour,
			COUNT(name) AS count,
			SUM(ifnull(rounded_total, ifnull(grand_total, 0))) AS amount
		FROM {_get_report_table_sql("tabSales Order")}
		WHERE docstatus = 1
			AND DATE(creation) = %s
			{company_sql}
		GROUP BY HOUR(creation)
		ORDER BY trend_hour ASC
		""",
		params,
		as_dict=True,
	)


def _make_purchase_hourly_rows(*, company: str | None, trend_date: str):
	params = [trend_date]
	company_sql = ""
	if company:
		company_sql = " AND company = %s"
		params.append(company)
	return frappe.db.sql(
		f"""
		SELECT
			HOUR(creation) AS trend_hour,
			COUNT(name) AS count,
			SUM(ifnull(rounded_total, ifnull(grand_total, 0))) AS amount
		FROM {_get_report_table_sql("tabPurchase Order")}
		WHERE docstatus = 1
			AND DATE(creation) = %s
			{company_sql}
		GROUP BY HOUR(creation)
		ORDER BY trend_hour ASC
		""",
		params,
		as_dict=True,
	)


def _serialize_amount_group_rows(rows):
	serialized = []
	for row in rows or []:
		name = getattr(row, "name", None)
		if not name:
			continue
		serialized.append(
			{
				"name": name,
				"count": cint(getattr(row, "count", 0) or 0),
				"amount": flt(getattr(row, "amount", 0) or 0),
			}
		)
	return serialized


def _serialize_sales_trend_rows(rows):
	serialized = []
	for row in rows or []:
		trend_date = getattr(row, "trend_date", None)
		if not trend_date:
			continue
		serialized.append(
			{
				"trend_date": str(trend_date),
				"count": cint(getattr(row, "count", 0) or 0),
				"amount": flt(getattr(row, "amount", 0) or 0),
			}
		)
	return serialized


def _serialize_sales_product_rows(rows):
	serialized = []
	for row in rows or []:
		item_key = getattr(row, "item_key", None)
		if not item_key:
			continue
		serialized.append(
			{
				"item_key": item_key,
				"item_name": getattr(row, "item_name", item_key),
				"qty": flt(getattr(row, "qty", 0) or 0),
				"amount": flt(getattr(row, "amount", 0) or 0),
			}
		)
	return serialized


def _serialize_purchase_trend_rows(rows):
	return _serialize_sales_trend_rows(rows)


def _serialize_purchase_product_rows(rows):
	return _serialize_sales_product_rows(rows)


def _serialize_hourly_rows(rows):
	serialized = []
	for row in rows or []:
		hour = getattr(row, "trend_hour", None)
		if hour is None:
			continue
		serialized.append(
			{
				"trend_hour": cint(hour),
				"count": cint(getattr(row, "count", 0) or 0),
				"amount": flt(getattr(row, "amount", 0) or 0),
			}
		)
	return serialized


def _serialize_cashflow_trend_rows(rows):
	serialized = []
	for row in rows or []:
		trend_date = getattr(row, "trend_date", None)
		if not trend_date:
			continue
		serialized.append(
			{
				"trend_date": str(trend_date),
				"count": cint(getattr(row, "count", 0) or 0),
				"in_amount": flt(getattr(row, "in_amount", 0) or 0),
				"out_amount": flt(getattr(row, "out_amount", 0) or 0),
			}
		)
	return serialized


def _serialize_invoice_group_rows(rows):
	serialized = []
	for row in rows or []:
		name = getattr(row, "name", None)
		if not name:
			continue
		serialized.append(
			{
				"name": name,
				"count": cint(getattr(row, "count", 0) or 0),
				"total_amount": flt(getattr(row, "total_amount", 0) or 0),
				"paid_amount": flt(getattr(row, "paid_amount", 0) or 0),
				"outstanding_amount": flt(getattr(row, "outstanding_amount", 0) or 0),
			}
		)
	return serialized


def _serialize_cashflow_rows(rows):
	serialized = []
	for row in rows or []:
		payment_type = getattr(row, "payment_type", None) or "Unknown"
		if payment_type == "Receive":
			direction = "in"
			amount = flt(getattr(row, "received_amount", 0) or getattr(row, "paid_amount", 0) or 0)
		elif payment_type == "Pay":
			direction = "out"
			amount = flt(getattr(row, "paid_amount", 0) or getattr(row, "received_amount", 0) or 0)
		else:
			direction = "transfer"
			amount = flt(getattr(row, "paid_amount", 0) or getattr(row, "received_amount", 0) or 0)

		serialized.append(
			{
				"name": getattr(row, "name", None),
				"posting_date": getattr(row, "posting_date", None),
				"direction": direction,
				"party_type": getattr(row, "party_type", None),
				"party": getattr(row, "party", None),
				"mode_of_payment": getattr(row, "mode_of_payment", None),
				"amount": amount,
				"reference_no": getattr(row, "reference_no", None),
			}
		)
	return serialized


def _extract_cashflow_overview(rows):
	received_amount_total = 0.0
	paid_amount_total = 0.0
	for row in rows or []:
		payment_type = getattr(row, "payment_type", None)
		if payment_type == "Receive":
			received_amount_total += flt(getattr(row, "total_received_amount", 0) or getattr(row, "total_paid_amount", 0) or 0)
		elif payment_type == "Pay":
			paid_amount_total += flt(getattr(row, "total_paid_amount", 0) or getattr(row, "total_received_amount", 0) or 0)
	return received_amount_total, paid_amount_total


def _build_cashflow_overview(*, company: str | None, date_from: str, date_to: str):
	received_amount_total, paid_amount_total = _extract_cashflow_overview(
		_make_payment_type_totals(
			company=company,
			date_from=date_from,
			date_to=date_to,
		)
	)
	return {
		"received_amount_total": received_amount_total,
		"paid_amount_total": paid_amount_total,
		"net_cashflow_total": received_amount_total - paid_amount_total,
	}


def _build_sales_report_v1_data(*, company: str | None, date_from: str, date_to: str, limit: int):
	order_amount_expr = "ifnull(rounded_total, ifnull(grand_total, 0))"
	invoice_outstanding_expr = "ifnull(outstanding_amount, 0)"
	cashflow_overview = _build_cashflow_overview(
		company=company,
		date_from=date_from,
		date_to=date_to,
	)

	sales_rows = _serialize_amount_group_rows(
		_make_grouped_rows(
			"tabSales Order",
			party_field="customer",
			date_field="transaction_date",
			company=company,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
			amount_expr=order_amount_expr,
		)
	)
	sales_trend_rows = _serialize_sales_trend_rows(
		_make_sales_trend_rows(
			company=company,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
		)
	)
	sales_product_rows = _serialize_sales_product_rows(
		_make_sales_product_rows(
			company=company,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
		)
	)
	sales_hourly_rows = _serialize_hourly_rows(
		_make_sales_hourly_rows(
			company=company,
			trend_date=date_to,
		)
	)

	return {
		"overview": {
			"sales_amount_total": _make_scalar_aggregate(
				"tabSales Order",
				date_field="transaction_date",
				aggregate_field_sql=order_amount_expr,
				company=company,
				date_from=date_from,
				date_to=date_to,
			),
			"received_amount_total": cashflow_overview["received_amount_total"],
			"receivable_outstanding_total": _make_scalar_aggregate(
				"tabSales Invoice",
				date_field="posting_date",
				aggregate_field_sql=invoice_outstanding_expr,
				company=company,
				date_from=date_from,
				date_to=date_to,
				extra_sql="is_return = 0",
			),
		},
		"tables": {
			"sales_summary": sales_rows,
			"sales_trend": sales_trend_rows,
			"sales_trend_hourly": sales_hourly_rows,
			"sales_product_summary": sales_product_rows,
		},
	}


def _build_purchase_report_v1_data(*, company: str | None, date_from: str, date_to: str, limit: int):
	order_amount_expr = "ifnull(rounded_total, ifnull(grand_total, 0))"
	invoice_outstanding_expr = "ifnull(outstanding_amount, 0)"
	cashflow_overview = _build_cashflow_overview(
		company=company,
		date_from=date_from,
		date_to=date_to,
	)

	purchase_rows = _serialize_amount_group_rows(
		_make_grouped_rows(
			"tabPurchase Order",
			party_field="supplier",
			date_field="transaction_date",
			company=company,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
			amount_expr=order_amount_expr,
		)
	)
	purchase_trend_rows = _serialize_purchase_trend_rows(
		_make_purchase_trend_rows(
			company=company,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
		)
	)
	purchase_product_rows = _serialize_purchase_product_rows(
		_make_purchase_product_rows(
			company=company,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
		)
	)
	purchase_hourly_rows = _serialize_hourly_rows(
		_make_purchase_hourly_rows(
			company=company,
			trend_date=date_to,
		)
	)

	return {
		"overview": {
			"purchase_amount_total": _make_scalar_aggregate(
				"tabPurchase Order",
				date_field="transaction_date",
				aggregate_field_sql=order_amount_expr,
				company=company,
				date_from=date_from,
				date_to=date_to,
			),
			"paid_amount_total": cashflow_overview["paid_amount_total"],
			"payable_outstanding_total": _make_scalar_aggregate(
				"tabPurchase Invoice",
				date_field="posting_date",
				aggregate_field_sql=invoice_outstanding_expr,
				company=company,
				date_from=date_from,
				date_to=date_to,
				extra_sql="is_return = 0",
			),
		},
		"tables": {
			"purchase_summary": purchase_rows,
			"purchase_trend": purchase_trend_rows,
			"purchase_trend_hourly": purchase_hourly_rows,
			"purchase_product_summary": purchase_product_rows,
		},
	}


def get_cashflow_report_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
):
	resolved_company = _normalize_company(company)
	resolved_date_from, resolved_date_to = _resolve_report_date_range(date_from, date_to)
	cashflow_trend_rows = _serialize_cashflow_trend_rows(
		_make_cashflow_trend_rows(
			company=resolved_company,
			date_from=resolved_date_from,
			date_to=resolved_date_to,
		)
	)

	return {
		"status": "success",
		"message": _("资金报表获取成功。"),
		"data": {
			"overview": _build_cashflow_overview(
				company=resolved_company,
				date_from=resolved_date_from,
				date_to=resolved_date_to,
			),
			"trend": cashflow_trend_rows,
			"meta": {
				"company": resolved_company,
				"date_from": resolved_date_from,
				"date_to": resolved_date_to,
			},
		},
	}


def get_sales_report_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = DEFAULT_REPORT_LIMIT,
):
	resolved_limit = _resolve_report_limit(limit)
	resolved_company = _normalize_company(company)
	resolved_date_from, resolved_date_to = _resolve_report_date_range(date_from, date_to)
	report_data = _build_sales_report_v1_data(
		company=resolved_company,
		date_from=resolved_date_from,
		date_to=resolved_date_to,
		limit=resolved_limit,
	)
	return {
		"status": "success",
		"message": _("销售分析报表获取成功。"),
		"data": {
			**report_data,
			"meta": {
				"company": resolved_company,
				"date_from": resolved_date_from,
				"date_to": resolved_date_to,
				"limit": resolved_limit,
			},
		},
	}


def get_purchase_report_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = DEFAULT_REPORT_LIMIT,
):
	resolved_limit = _resolve_report_limit(limit)
	resolved_company = _normalize_company(company)
	resolved_date_from, resolved_date_to = _resolve_report_date_range(date_from, date_to)
	report_data = _build_purchase_report_v1_data(
		company=resolved_company,
		date_from=resolved_date_from,
		date_to=resolved_date_to,
		limit=resolved_limit,
	)
	return {
		"status": "success",
		"message": _("采购分析报表获取成功。"),
		"data": {
			**report_data,
			"meta": {
				"company": resolved_company,
				"date_from": resolved_date_from,
				"date_to": resolved_date_to,
				"limit": resolved_limit,
			},
		},
	}


def list_cashflow_entries_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	page: int | str | None = 1,
	page_size: int | str | None = DEFAULT_CASHFLOW_ENTRY_PAGE_SIZE,
):
	resolved_company = _normalize_company(company)
	resolved_date_from, resolved_date_to = _resolve_report_date_range(date_from, date_to)
	resolved_page = _resolve_positive_int(page, default=1, minimum=1)
	resolved_page_size = _resolve_positive_int(
		page_size,
		default=DEFAULT_CASHFLOW_ENTRY_PAGE_SIZE,
		minimum=1,
		maximum=MAX_CASHFLOW_ENTRY_PAGE_SIZE,
	)
	offset = (resolved_page - 1) * resolved_page_size
	total_count = _count_cashflow_entries(
		company=resolved_company,
		date_from=resolved_date_from,
		date_to=resolved_date_to,
	)
	rows = _serialize_cashflow_rows(
		_make_cashflow_entry_rows(
			company=resolved_company,
			date_from=resolved_date_from,
			date_to=resolved_date_to,
			limit=resolved_page_size,
			offset=offset,
		)
	)

	return {
		"status": "success",
		"message": _("资金流水列表获取成功。"),
		"data": {
			"rows": rows,
			"pagination": {
				"page": resolved_page,
				"page_size": resolved_page_size,
				"total_count": total_count,
				"has_more": offset + len(rows) < total_count,
			},
			"meta": {
				"company": resolved_company,
				"date_from": resolved_date_from,
				"date_to": resolved_date_to,
			},
		},
	}


def get_business_report_v1(
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = DEFAULT_REPORT_LIMIT,
):
	resolved_limit = _resolve_report_limit(limit)
	resolved_company = _normalize_company(company)
	resolved_date_from, resolved_date_to = _resolve_report_date_range(date_from, date_to)

	order_amount_expr = "ifnull(rounded_total, ifnull(grand_total, 0))"
	invoice_outstanding_expr = "ifnull(outstanding_amount, 0)"

	sales_rows = _serialize_amount_group_rows(
		_make_grouped_rows(
			"tabSales Order",
			party_field="customer",
			date_field="transaction_date",
			company=resolved_company,
			date_from=resolved_date_from,
			date_to=resolved_date_to,
			limit=resolved_limit,
			amount_expr=order_amount_expr,
		)
	)
	purchase_rows = _serialize_amount_group_rows(
		_make_grouped_rows(
			"tabPurchase Order",
			party_field="supplier",
			date_field="transaction_date",
			company=resolved_company,
			date_from=resolved_date_from,
			date_to=resolved_date_to,
			limit=resolved_limit,
			amount_expr=order_amount_expr,
		)
	)
	receivable_rows = _serialize_invoice_group_rows(
		_make_invoice_grouped_rows(
			"tabSales Invoice",
			party_field="customer",
			date_field="posting_date",
			company=resolved_company,
			date_from=resolved_date_from,
			date_to=resolved_date_to,
			limit=resolved_limit,
		)
	)
	payable_rows = _serialize_invoice_group_rows(
		_make_invoice_grouped_rows(
			"tabPurchase Invoice",
			party_field="supplier",
			date_field="posting_date",
			company=resolved_company,
			date_from=resolved_date_from,
			date_to=resolved_date_to,
			limit=resolved_limit,
		)
	)
	sales_trend_rows = _serialize_sales_trend_rows(
		_make_sales_trend_rows(
			company=resolved_company,
			date_from=resolved_date_from,
			date_to=resolved_date_to,
			limit=resolved_limit,
		)
	)
	sales_product_rows = _serialize_sales_product_rows(
		_make_sales_product_rows(
			company=resolved_company,
			date_from=resolved_date_from,
			date_to=resolved_date_to,
			limit=resolved_limit,
		)
	)
	purchase_trend_rows = _serialize_purchase_trend_rows(
		_make_purchase_trend_rows(
			company=resolved_company,
			date_from=resolved_date_from,
			date_to=resolved_date_to,
			limit=resolved_limit,
		)
	)
	purchase_product_rows = _serialize_purchase_product_rows(
		_make_purchase_product_rows(
			company=resolved_company,
			date_from=resolved_date_from,
			date_to=resolved_date_to,
			limit=resolved_limit,
		)
	)
	sales_hourly_rows = _serialize_hourly_rows(
		_make_sales_hourly_rows(
			company=resolved_company,
			trend_date=resolved_date_to,
		)
	)
	purchase_hourly_rows = _serialize_hourly_rows(
		_make_purchase_hourly_rows(
			company=resolved_company,
			trend_date=resolved_date_to,
		)
	)
	cashflow_rows = _serialize_cashflow_rows(
		_make_recent_cashflow_rows(
			company=resolved_company,
			date_from=resolved_date_from,
			date_to=resolved_date_to,
			limit=resolved_limit,
		)
	)
	cashflow_trend_rows = _serialize_cashflow_trend_rows(
		_make_cashflow_trend_rows(
			company=resolved_company,
			date_from=resolved_date_from,
			date_to=resolved_date_to,
		)
	)

	sales_amount_total = _make_scalar_aggregate(
		"tabSales Order",
		date_field="transaction_date",
		aggregate_field_sql=order_amount_expr,
		company=resolved_company,
		date_from=resolved_date_from,
		date_to=resolved_date_to,
	)
	purchase_amount_total = _make_scalar_aggregate(
		"tabPurchase Order",
		date_field="transaction_date",
		aggregate_field_sql=order_amount_expr,
		company=resolved_company,
		date_from=resolved_date_from,
		date_to=resolved_date_to,
	)
	receivable_outstanding_total = _make_scalar_aggregate(
		"tabSales Invoice",
		date_field="posting_date",
		aggregate_field_sql=invoice_outstanding_expr,
		company=resolved_company,
		date_from=resolved_date_from,
		date_to=resolved_date_to,
		extra_sql="is_return = 0",
	)
	payable_outstanding_total = _make_scalar_aggregate(
		"tabPurchase Invoice",
		date_field="posting_date",
		aggregate_field_sql=invoice_outstanding_expr,
		company=resolved_company,
		date_from=resolved_date_from,
		date_to=resolved_date_to,
		extra_sql="is_return = 0",
	)
	cashflow_overview = _build_cashflow_overview(
		company=resolved_company,
		date_from=resolved_date_from,
		date_to=resolved_date_to,
	)

	return {
		"status": "success",
		"message": _("经营报表获取成功。"),
		"data": {
			"overview": {
				"sales_amount_total": sales_amount_total,
				"purchase_amount_total": purchase_amount_total,
				"received_amount_total": cashflow_overview["received_amount_total"],
				"paid_amount_total": cashflow_overview["paid_amount_total"],
				"net_cashflow_total": cashflow_overview["net_cashflow_total"],
				"receivable_outstanding_total": receivable_outstanding_total,
				"payable_outstanding_total": payable_outstanding_total,
			},
			"tables": {
				"sales_summary": sales_rows,
				"sales_trend": sales_trend_rows,
				"sales_trend_hourly": sales_hourly_rows,
				"sales_product_summary": sales_product_rows,
				"purchase_summary": purchase_rows,
				"purchase_trend": purchase_trend_rows,
				"purchase_trend_hourly": purchase_hourly_rows,
				"purchase_product_summary": purchase_product_rows,
				"receivable_summary": receivable_rows,
				"payable_summary": payable_rows,
				"cashflow_summary": cashflow_rows,
				"cashflow_trend": cashflow_trend_rows,
			},
			"meta": {
				"company": resolved_company,
				"date_from": resolved_date_from,
				"date_to": resolved_date_to,
				"limit": resolved_limit,
			},
		},
	}
