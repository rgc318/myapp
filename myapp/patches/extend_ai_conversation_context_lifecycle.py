import frappe


def execute():
	if not frappe.db.table_exists("MyApp AI Conversation"):
		return
	if not frappe.db.has_column("MyApp AI Conversation", "context_start_sequence"):
		frappe.db.sql(
			"""
			ALTER TABLE `tabMyApp AI Conversation`
			ADD COLUMN `context_start_sequence` int(11) NOT NULL DEFAULT 1
			AFTER `state_updated_at`
			"""
		)
	frappe.db.commit()
