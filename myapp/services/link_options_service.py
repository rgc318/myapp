import frappe
from frappe import _


ALLOWED_LINK_DOCTYPES = {
	"Company": ("name",),
	"Customer": ("name", "customer_name"),
	"Mode of Payment": ("name",),
	"Purchase Invoice": ("name", "supplier", "company"),
	"Purchase Order": ("name", "supplier", "company"),
	"Purchase Receipt": ("name", "supplier", "company"),
	"Sales Invoice": ("name", "customer", "company"),
	"Supplier": ("name", "supplier_name"),
	"Warehouse": ("name", "company"),
}


def _coerce_extra_fields(value):
	if isinstance(value, str):
		value = frappe.parse_json(value) if value.strip().startswith("[") else [value]
	if not isinstance(value, (list, tuple)):
		return []
	return [field for field in value if isinstance(field, str) and field.strip()]


def search_link_options_v1(
	doctype: str,
	query: str | None = None,
	extra_fields=None,
	limit: int = 8,
):
	if doctype not in ALLOWED_LINK_DOCTYPES:
		frappe.throw(_("不允许搜索此类型：{0}").format(doctype))

	allowed_fields = ALLOWED_LINK_DOCTYPES[doctype]
	fields = ["name"]
	for field in _coerce_extra_fields(extra_fields):
		if field in allowed_fields and field not in fields:
			fields.append(field)

	filters = []
	trimmed_query = (query or "").strip()
	if trimmed_query:
		filters.append(["name", "like", f"%{trimmed_query}%"])

	rows = frappe.get_list(
		doctype,
		fields=fields,
		filters=filters,
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
