import frappe

from myapp.utils.standard_uoms import BUSINESS_SELECTABLE_UOM_FIELD, STANDARD_UOM_MAP


_AMBIGUOUS_PACKAGING_UOMS = ("Case", "Carton")


def execute():
	for uom_name in _AMBIGUOUS_PACKAGING_UOMS:
		if not frappe.db.exists("UOM", uom_name):
			continue
		frappe.db.set_value(
			"UOM",
			uom_name,
			{
				BUSINESS_SELECTABLE_UOM_FIELD: 0,
				"symbol": STANDARD_UOM_MAP[uom_name]["symbol"],
			},
			update_modified=False,
		)
