import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


ORDER_DEFAULT_SALES_MODE_FIELD = "custom_default_sales_mode"
ORDER_ITEM_SALES_MODE_FIELD = "custom_sales_mode"


def execute():
	def _existing(dt: str, fieldname: str) -> bool:
		return bool(frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fieldname}))

	if _existing("Sales Order", ORDER_DEFAULT_SALES_MODE_FIELD) and _existing(
		"Sales Order Item", ORDER_ITEM_SALES_MODE_FIELD
	):
		return

	create_custom_fields(
		{
			"Sales Order": [
				{
					"fieldname": ORDER_DEFAULT_SALES_MODE_FIELD,
					"label": "Default Sales Mode",
					"fieldtype": "Select",
                "options": "wholesale\nretail",
					"insert_after": "po_no",
					"translatable": 0,
					"reqd": 0,
					"read_only": 0,
				}
			],
			"Sales Order Item": [
				{
					"fieldname": ORDER_ITEM_SALES_MODE_FIELD,
					"label": "Sales Mode",
					"fieldtype": "Select",
                "options": "wholesale\nretail",
					"insert_after": "uom",
					"translatable": 0,
					"reqd": 0,
					"read_only": 0,
				}
			],
		},
		update=True,
	)
