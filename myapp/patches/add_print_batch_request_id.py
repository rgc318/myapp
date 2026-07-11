import frappe


TABLE_NAME = "tabMyApp Print Batch"


def execute():
	if not frappe.db.table_exists("MyApp Print Batch"):
		return
	if not frappe.db.has_column("MyApp Print Batch", "request_id"):
		frappe.db.sql(f"ALTER TABLE `{TABLE_NAME}` ADD COLUMN `request_id` varchar(140) DEFAULT NULL AFTER `output`")
	indexes = frappe.db.sql(f"SHOW INDEX FROM `{TABLE_NAME}` WHERE Key_name = 'uniq_myapp_print_batch_request'", as_dict=True)
	if not indexes:
		frappe.db.sql(
			f"ALTER TABLE `{TABLE_NAME}` ADD UNIQUE KEY `uniq_myapp_print_batch_request` (`requested_by`, `request_id`)"
		)
	frappe.db.commit()
