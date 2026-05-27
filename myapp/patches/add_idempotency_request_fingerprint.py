import frappe


TABLE_NAME = "tabMyApp Idempotency Key"
DOCTYPE_NAME = "MyApp Idempotency Key"


def _column_exists(column_name: str) -> bool:
	return bool(frappe.db.has_column(DOCTYPE_NAME, column_name))


def execute():
	if not frappe.db.table_exists(DOCTYPE_NAME):
		return

	alter_statements = []
	if not _column_exists("request_hash"):
		alter_statements.append("ADD COLUMN `request_hash` varchar(64) DEFAULT NULL AFTER `request_id`")
	if not _column_exists("request_json"):
		alter_statements.append("ADD COLUMN `request_json` longtext DEFAULT NULL AFTER `request_hash`")

	if alter_statements:
		frappe.db.sql(f"ALTER TABLE `{TABLE_NAME}` {', '.join(alter_statements)}")
		frappe.db.commit()
