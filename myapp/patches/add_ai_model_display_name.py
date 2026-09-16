import frappe


def execute():
	if not frappe.db.table_exists("MyApp AI Model Registry"):
		return
	if frappe.db.has_column("MyApp AI Model Registry", "display_name"):
		return
	frappe.db.sql(
		"ALTER TABLE `tabMyApp AI Model Registry` "
		"ADD COLUMN `display_name` varchar(255) DEFAULT NULL AFTER `provider_model_display`"
	)
