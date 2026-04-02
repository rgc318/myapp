import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate


MAX_REPORT_LIMIT = 50
DEFAULT_REPORT_LIMIT = 10
MAX_REPORT_RANGE_DAYS = 366
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
		LIMIT %s
		""",
		(*params, limit),
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
	cashflow_rows = _serialize_cashflow_rows(
		_make_recent_cashflow_rows(
			company=resolved_company,
			date_from=resolved_date_from,
			date_to=resolved_date_to,
			limit=resolved_limit,
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
	received_amount_total, paid_amount_total = _extract_cashflow_overview(
		_make_payment_type_totals(
			company=resolved_company,
			date_from=resolved_date_from,
			date_to=resolved_date_to,
		)
	)

	return {
		"status": "success",
		"message": _("经营报表获取成功。"),
		"data": {
			"overview": {
				"sales_amount_total": sales_amount_total,
				"purchase_amount_total": purchase_amount_total,
				"received_amount_total": received_amount_total,
				"paid_amount_total": paid_amount_total,
				"net_cashflow_total": received_amount_total - paid_amount_total,
				"receivable_outstanding_total": receivable_outstanding_total,
				"payable_outstanding_total": payable_outstanding_total,
			},
			"tables": {
				"sales_summary": sales_rows,
				"purchase_summary": purchase_rows,
				"receivable_summary": receivable_rows,
				"payable_summary": payable_rows,
				"cashflow_summary": cashflow_rows,
			},
			"meta": {
				"company": resolved_company,
				"date_from": resolved_date_from,
				"date_to": resolved_date_to,
				"limit": resolved_limit,
			},
		},
	}
