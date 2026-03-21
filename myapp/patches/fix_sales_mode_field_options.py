from __future__ import annotations

import frappe


TARGET_FIELDS = (
    ("Sales Order", "custom_default_sales_mode"),
    ("Sales Order Item", "custom_sales_mode"),
)


def execute() -> None:
    for dt, fieldname in TARGET_FIELDS:
        name = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fieldname}, "name")
        if not name:
            continue

        options = frappe.db.get_value("Custom Field", name, "options")
        if options in {"\\nwholesale\\nretail", "wholesale\\nretail", "\nwholesale\nretail"}:
            frappe.db.set_value("Custom Field", name, "options", "wholesale\nretail", update_modified=False)

    frappe.clear_cache()
