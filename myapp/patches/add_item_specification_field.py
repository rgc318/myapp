import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


ITEM_SPECIFICATION_FIELD = "custom_specification"


def execute():
	if frappe.db.exists("Custom Field", {"dt": "Item", "fieldname": ITEM_SPECIFICATION_FIELD}):
		return

	create_custom_fields(
		{
			"Item": [
				{
					"fieldname": ITEM_SPECIFICATION_FIELD,
					"label": "Specification",
					"fieldtype": "Data",
					"insert_after": "custom_nickname",
					"translatable": 0,
					"unique": 0,
					"reqd": 0,
					"read_only": 0,
				}
			]
		},
		update=True,
	)
