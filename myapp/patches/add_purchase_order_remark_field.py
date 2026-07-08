import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


ORDER_REMARK_FIELD = "custom_order_remark"


def execute():
	if frappe.db.exists("Custom Field", {"dt": "Purchase Order", "fieldname": ORDER_REMARK_FIELD}):
		return

	create_custom_fields(
		{
			"Purchase Order": [
				{
					"fieldname": ORDER_REMARK_FIELD,
					"label": "Order Remark",
					"fieldtype": "Small Text",
					"insert_after": "supplier_ref",
					"translatable": 0,
					"unique": 0,
					"reqd": 0,
					"read_only": 0,
				}
			]
		},
		update=True,
	)
