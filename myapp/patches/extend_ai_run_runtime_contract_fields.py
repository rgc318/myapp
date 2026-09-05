import frappe


def execute():
	if not frappe.db.table_exists("MyApp AI Run"):
		return
	columns = {
		"protocol_version": "varchar(80) DEFAULT NULL",
		"schema_version": "varchar(80) DEFAULT NULL",
		"prompt_version": "varchar(80) DEFAULT NULL",
		"runtime_revision": "varchar(140) DEFAULT NULL",
		"release_id": "varchar(140) DEFAULT NULL",
		"runtime_capabilities_json": "longtext DEFAULT NULL",
	}
	for fieldname, definition in columns.items():
		if not frappe.db.has_column("MyApp AI Run", fieldname):
			frappe.db.sql(
				f"ALTER TABLE `tabMyApp AI Run` ADD COLUMN `{fieldname}` {definition}"
			)
