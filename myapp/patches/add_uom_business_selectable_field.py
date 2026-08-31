import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from myapp.utils.standard_uoms import BUSINESS_SELECTABLE_UOM_FIELD, STANDARD_UOM_NAMES


def execute():
	if not frappe.db.exists(
		"Custom Field",
		{"dt": "UOM", "fieldname": BUSINESS_SELECTABLE_UOM_FIELD},
	):
		create_custom_fields(
			{
				"UOM": [
					{
						"fieldname": BUSINESS_SELECTABLE_UOM_FIELD,
						"label": "Business Selectable",
						"fieldtype": "Check",
						"insert_after": "enabled",
						"default": "0",
						"description": "Allow this UOM in normal product and transaction selectors.",
						"translatable": 0,
						"reqd": 0,
						"read_only": 0,
					},
				]
			},
			update=True,
		)
		frappe.clear_cache(doctype="UOM")

	existing_standard_uoms = frappe.get_all(
		"UOM",
		filters={"name": ["in", sorted(STANDARD_UOM_NAMES)]},
		pluck="name",
		limit_page_length=0,
	)
	for uom_name in existing_standard_uoms:
		if not frappe.db.get_value("UOM", uom_name, BUSINESS_SELECTABLE_UOM_FIELD):
			frappe.db.set_value(
				"UOM",
				uom_name,
				BUSINESS_SELECTABLE_UOM_FIELD,
				1,
				update_modified=False,
			)
