import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from myapp.utils.pagination import build_offset_pagination
from myapp.services.data_permission_service import require_doctype_permission


DOCUMENT_LIST_CONFIG = {
	"Delivery Note": {
		"party_field": "customer",
		"party_name_field": "customer_name",
		"party_filter": "customer",
		"date_field": "posting_date",
		"amount_fields": ("rounded_total", "grand_total"),
		"detail_path": "/sales/delivery-notes",
		"extra_fields": ["status", "total_qty", "is_return", "return_against"],
	},
	"Sales Invoice": {
		"party_field": "customer",
		"party_name_field": "customer_name",
		"party_filter": "customer",
		"date_field": "posting_date",
		"amount_fields": ("rounded_total", "grand_total"),
		"detail_path": "/sales/invoices",
		"extra_fields": ["status", "outstanding_amount", "paid_amount", "due_date", "is_return", "return_against"],
	},
	"Purchase Receipt": {
		"party_field": "supplier",
		"party_name_field": "supplier_name",
		"party_filter": "supplier",
		"date_field": "posting_date",
		"amount_fields": ("rounded_total", "grand_total"),
		"detail_path": "/purchase/receipts",
		"extra_fields": ["status", "total_qty", "is_return", "return_against"],
	},
	"Purchase Invoice": {
		"party_field": "supplier",
		"party_name_field": "supplier_name",
		"party_filter": "supplier",
		"date_field": "posting_date",
		"amount_fields": ("rounded_total", "grand_total"),
		"detail_path": "/purchase/invoices",
		"extra_fields": ["status", "outstanding_amount", "paid_amount", "due_date", "is_return", "return_against"],
	},
}

ALLOWED_SORTS = {
	"latest": "modified desc",
	"oldest": "{date_field} asc, modified asc",
	"amount_desc": "grand_total desc, modified desc",
	"amount_asc": "grand_total asc, modified desc",
}


def _normalize_text(value):
	return (value or "").strip()


def _normalize_limit(limit):
	return max(1, min(cint(limit or 20), 100))


def _normalize_start(start):
	return max(0, cint(start or 0))


def _normalize_date_range(date_from=None, date_to=None):
	resolved_date_from = _normalize_text(date_from) or None
	resolved_date_to = _normalize_text(date_to) or None
	if resolved_date_from and resolved_date_to and getdate(resolved_date_from) > getdate(resolved_date_to):
		frappe.throw(_("date_from 不能晚于 date_to。"))
	return resolved_date_from, resolved_date_to


def _normalize_docstatus(docstatus):
	if docstatus in (None, "", "all"):
		return None
	if str(docstatus).lower() == "draft":
		return 0
	if str(docstatus).lower() == "submitted":
		return 1
	if str(docstatus).lower() == "cancelled":
		return 2
	resolved = cint(docstatus)
	return resolved if resolved in (0, 1, 2) else None


def _normalize_sort(sort_by):
	resolved = (_normalize_text(sort_by) or "latest").lower()
	return resolved if resolved in ALLOWED_SORTS else "latest"


def _amount_value(row, fields):
	for fieldname in fields:
		value = flt(row.get(fieldname) or 0)
		if value:
			return value
	return flt(row.get(fields[-1]) or 0)


def _build_filters(config, *, company=None, party=None, date_from=None, date_to=None, docstatus=None):
	filters = {}
	if company:
		filters["company"] = company
	if party:
		filters[config["party_filter"]] = party
	if docstatus is not None:
		filters["docstatus"] = docstatus
	if date_from and date_to:
		filters[config["date_field"]] = ["between", [date_from, date_to]]
	elif date_from:
		filters[config["date_field"]] = [">=", date_from]
	elif date_to:
		filters[config["date_field"]] = ["<=", date_to]
	return filters


def _build_or_filters(doctype, config, search_key):
	if not search_key:
		return None
	like_pattern = f"%{search_key}%"
	return [
		[doctype, "name", "like", like_pattern],
		[doctype, config["party_field"], "like", like_pattern],
		[doctype, config["party_name_field"], "like", like_pattern],
		[doctype, "company", "like", like_pattern],
	]


def _serialize_row(row, doctype, config):
	return {
		"doctype": doctype,
		"name": row.get("name"),
		"company": row.get("company"),
		"party": row.get(config["party_field"]),
		"party_name": row.get(config["party_name_field"]) or row.get(config["party_field"]),
		"posting_date": row.get(config["date_field"]),
		"due_date": row.get("due_date"),
		"document_status": {0: "Draft", 1: "Submitted", 2: "Cancelled"}.get(cint(row.get("docstatus")), str(row.get("docstatus"))),
		"docstatus": cint(row.get("docstatus")),
		"business_status": row.get("status"),
		"amount": _amount_value(row, config["amount_fields"]),
		"outstanding_amount": flt(row.get("outstanding_amount") or 0) if "outstanding_amount" in row else None,
		"paid_amount": flt(row.get("paid_amount") or 0) if "paid_amount" in row else None,
		"total_qty": flt(row.get("total_qty") or 0) if "total_qty" in row else None,
		"is_return": cint(row.get("is_return") or 0),
		"return_against": row.get("return_against"),
		"modified": row.get("modified"),
		"detail_path": config["detail_path"],
	}


def list_business_documents_v1(
	doctype: str,
	search_key: str | None = None,
	company: str | None = None,
	party: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	docstatus=None,
	sort_by: str | None = None,
	limit: int = 20,
	start: int = 0,
):
	if doctype not in DOCUMENT_LIST_CONFIG:
		frappe.throw(_("暂不支持该单据类型列表。"))
	require_doctype_permission(doctype, "read")

	config = DOCUMENT_LIST_CONFIG[doctype]
	limit = _normalize_limit(limit)
	start = _normalize_start(start)
	search_key = _normalize_text(search_key)
	company = _normalize_text(company)
	party = _normalize_text(party)
	date_from, date_to = _normalize_date_range(date_from, date_to)
	resolved_docstatus = _normalize_docstatus(docstatus)
	sort_by = _normalize_sort(sort_by)
	order_by = ALLOWED_SORTS[sort_by].format(date_field=config["date_field"])

	filters = _build_filters(
		config,
		company=company,
		party=party,
		date_from=date_from,
		date_to=date_to,
		docstatus=resolved_docstatus,
	)
	or_filters = _build_or_filters(doctype, config, search_key)
	fields = [
		"name",
		config["party_field"],
		config["party_name_field"],
		"company",
		config["date_field"],
		"docstatus",
		"grand_total",
		"rounded_total",
		"modified",
		*config["extra_fields"],
	]

	rows = frappe.get_list(
		doctype,
		filters=filters,
		or_filters=or_filters,
		fields=fields,
		order_by=order_by,
		limit_start=start,
		limit_page_length=limit,
	)
	count_rows = frappe.get_list(
		doctype,
		filters=filters,
		or_filters=or_filters,
		fields=["name"],
		limit_page_length=0,
	)
	total_count = len(count_rows)
	pagination = build_offset_pagination(
		start=start,
		limit=limit,
		total_count=total_count,
		row_count=len(rows),
	)

	return {
		"status": "success",
		"data": {
			"items": [_serialize_row(row, doctype, config) for row in rows],
			"pagination": pagination,
			"summary": {
				"total_count": total_count,
				"visible_count": total_count,
			},
			"meta": {
				"doctype": doctype,
				"filters": {
					"search_key": search_key or None,
					"company": company or None,
					"party": party or None,
					"date_from": date_from,
					"date_to": date_to,
					"docstatus": resolved_docstatus,
					"sort_by": sort_by,
				},
			},
		},
		"message": _("单据列表获取成功。"),
	}
