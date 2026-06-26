import frappe
from frappe import _


ALLOWED_LINK_DOCTYPES = {
	"Company": ("name",),
	"Customer": ("name", "customer_name"),
	"Delivery Note": ("name", "customer", "company"),
	"Brand": ("name",),
	"Item Group": ("name",),
	"Mode of Payment": ("name",),
	"Purchase Invoice": ("name", "supplier", "company"),
	"Purchase Order": ("name", "supplier", "company"),
	"Purchase Receipt": ("name", "supplier", "company"),
	"Sales Invoice": ("name", "customer", "company"),
	"Supplier": ("name", "supplier_name"),
	"Warehouse": ("name", "company"),
}

ALLOWED_LINK_FILTERS = {
	"Company": (),
	"Customer": ("disabled",),
	"Delivery Note": ("company", "customer", "docstatus"),
	"Brand": (),
	"Item Group": ("is_group",),
	"Mode of Payment": ("enabled",),
	"Purchase Invoice": ("company", "docstatus", "supplier"),
	"Purchase Order": ("company", "docstatus", "supplier"),
	"Purchase Receipt": ("company", "docstatus", "supplier"),
	"Sales Invoice": ("company", "customer", "docstatus"),
	"Supplier": ("disabled",),
	"Warehouse": ("company", "disabled", "is_group"),
}


def _coerce_extra_fields(value):
	if isinstance(value, str):
		value = frappe.parse_json(value) if value.strip().startswith("[") else [value]
	if not isinstance(value, (list, tuple)):
		return []
	return [field for field in value if isinstance(field, str) and field.strip()]


def _coerce_filters(value):
	if isinstance(value, str):
		value = frappe.parse_json(value) if value.strip().startswith("{") else {}
	if not isinstance(value, dict):
		return {}
	return {field: field_value for field, field_value in value.items() if isinstance(field, str)}


def _build_allowed_filters(doctype: str, value):
	allowed_fields = ALLOWED_LINK_FILTERS.get(doctype, ())
	filter_map = _coerce_filters(value)
	filters = []

	for field, field_value in filter_map.items():
		if field not in allowed_fields:
			continue
		if field_value in (None, ""):
			continue
		if isinstance(field_value, (list, tuple, dict)):
			continue
		filters.append([field, "=", field_value])

	return filters


def search_link_options_v1(
	doctype: str,
	query: str | None = None,
	extra_fields=None,
	filters=None,
	limit: int = 8,
):
	if doctype not in ALLOWED_LINK_DOCTYPES:
		frappe.throw(_("不允许搜索此类型：{0}").format(doctype))

	allowed_fields = ALLOWED_LINK_DOCTYPES[doctype]
	fields = ["name"]
	for field in _coerce_extra_fields(extra_fields):
		if field in allowed_fields and field not in fields:
			fields.append(field)

	resolved_filters = []
	trimmed_query = (query or "").strip()
	if trimmed_query:
		resolved_filters.append(["name", "like", f"%{trimmed_query}%"])
	resolved_filters.extend(_build_allowed_filters(doctype, filters))

	rows = frappe.get_list(
		doctype,
		fields=fields,
		filters=resolved_filters,
		limit_page_length=max(min(int(limit or 8), 50), 1),
		order_by="modified desc",
	)

	options = []
	for row in rows:
		value = row.get("name")
		if not value:
			continue

		description = None
		for field in fields:
			if field == "name":
				continue
			field_value = row.get(field)
			if field_value and field_value != value:
				description = str(field_value)
				break

		options.append(
			{
				"description": description,
				"label": str(value),
				"value": str(value),
			}
		)

	return {
		"data": options,
		"meta": {
			"doctype": doctype,
			"limit": max(min(int(limit or 8), 50), 1),
			"query": trimmed_query,
		},
		"status": "success",
	}
