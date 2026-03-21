import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


WHOLESALE_DEFAULT_UOM_FIELD = "custom_wholesale_default_uom"
RETAIL_DEFAULT_UOM_FIELD = "custom_retail_default_uom"


def execute():
	fieldnames = [WHOLESALE_DEFAULT_UOM_FIELD, RETAIL_DEFAULT_UOM_FIELD]
	existing = {
		row.fieldname
		for row in frappe.get_all(
			"Custom Field",
			filters={"dt": "Item", "fieldname": ["in", fieldnames]},
			fields=["fieldname"],
		)
	}
	if len(existing) == len(fieldnames):
		return

	create_custom_fields(
		{
			"Item": [
				{
					"fieldname": WHOLESALE_DEFAULT_UOM_FIELD,
					"label": "Wholesale Default UOM",
					"fieldtype": "Link",
					"options": "UOM",
					"insert_after": "stock_uom",
					"translatable": 0,
					"reqd": 0,
					"read_only": 0,
				},
				{
					"fieldname": RETAIL_DEFAULT_UOM_FIELD,
					"label": "Retail Default UOM",
					"fieldtype": "Link",
					"options": "UOM",
					"insert_after": WHOLESALE_DEFAULT_UOM_FIELD,
					"translatable": 0,
					"reqd": 0,
					"read_only": 0,
				},
			]
		},
		update=True,
	)
