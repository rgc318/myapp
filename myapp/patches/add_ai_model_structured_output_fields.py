import frappe


def execute():
	if not frappe.db.table_exists("MyApp AI Model Registry"):
		return
	columns = (
		(
			"supports_structured_output",
			"int(1) NOT NULL DEFAULT 0",
			"supports_json_schema",
		),
		(
			"last_structured_error_code",
			"varchar(140) DEFAULT NULL",
			"last_tool_error_code",
		),
	)
	for fieldname, definition, after in columns:
		if not frappe.db.has_column("MyApp AI Model Registry", fieldname):
			frappe.db.sql(
				"ALTER TABLE `tabMyApp AI Model Registry` "
				f"ADD COLUMN `{fieldname}` {definition} AFTER `{after}`"
			)
