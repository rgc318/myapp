import frappe


def execute():
	if not frappe.db.table_exists("MyApp AI Conversation"):
		return
	for column, definition in (
		("state_version", "int(11) NOT NULL DEFAULT 0 AFTER `retention_until`"),
		("working_state_json", "longtext DEFAULT NULL AFTER `state_version`"),
		("state_updated_at", "datetime(6) DEFAULT NULL AFTER `working_state_json`"),
	):
		if not frappe.db.has_column("MyApp AI Conversation", column):
			frappe.db.sql(
				f"ALTER TABLE `tabMyApp AI Conversation` ADD COLUMN `{column}` {definition}"
			)
	frappe.db.commit()
