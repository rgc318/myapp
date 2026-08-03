import frappe


def execute():
	if not frappe.db.table_exists("MyApp AI Run"):
		return
	if not frappe.db.has_column("MyApp AI Run", "requested_model_alias"):
		frappe.db.sql(
			"ALTER TABLE `tabMyApp AI Run` "
			"ADD COLUMN `requested_model_alias` varchar(140) DEFAULT NULL AFTER `status`"
		)
	if not frappe.db.has_column("MyApp AI Run", "retry_of_run_id"):
		frappe.db.sql(
			"ALTER TABLE `tabMyApp AI Run` "
			"ADD COLUMN `retry_of_run_id` varchar(140) DEFAULT NULL AFTER `requested_model_alias`, "
			"ADD INDEX `idx_myapp_ai_run_retry_of` (`retry_of_run_id`)"
		)
	frappe.db.commit()
