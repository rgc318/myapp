import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


ITEM_NICKNAME_FIELD = "custom_nickname"


def execute():
	if frappe.db.exists("Custom Field", {"dt": "Item", "fieldname": ITEM_NICKNAME_FIELD}):
		return

	create_custom_fields(
		{
			"Item": [
				{
					"fieldname": ITEM_NICKNAME_FIELD,
					"label": "Nickname",
					"fieldtype": "Data",
					"insert_after": "item_name",
					"translatable": 0,
					"unique": 0,
					"reqd": 0,
					"read_only": 0,
				}
			]
		},
		update=True,
	)
