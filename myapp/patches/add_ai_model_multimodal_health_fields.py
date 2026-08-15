import frappe


def execute():
	columns = (
		("last_tool_error_code", "varchar(140) DEFAULT NULL", "last_error_code"),
		("last_vision_error_code", "varchar(140) DEFAULT NULL", "last_tool_error_code"),
	)
	for fieldname, definition, after in columns:
		if not frappe.db.has_column("MyApp AI Model Registry", fieldname):
			frappe.db.sql(
				f"ALTER TABLE `tabMyApp AI Model Registry` "
				f"ADD COLUMN `{fieldname}` {definition} AFTER `{after}`"
			)
