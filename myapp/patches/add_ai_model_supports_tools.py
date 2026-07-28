import frappe


def execute():
	if not frappe.db.has_column("MyApp AI Model Registry", "supports_tools"):
		frappe.db.sql(
			"ALTER TABLE `tabMyApp AI Model Registry` "
			"ADD COLUMN `supports_tools` int(1) NOT NULL DEFAULT 0 "
			"AFTER `supports_streaming`"
		)
