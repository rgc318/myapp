import frappe


def _add_column(column: str, definition: str):
	if frappe.db.table_exists("MyApp AI Draft") and not frappe.db.has_column("MyApp AI Draft", column):
		frappe.db.sql(f"ALTER TABLE `tabMyApp AI Draft` ADD COLUMN `{column}` {definition}")


def execute():
	for column, definition in (
		("execution_request_id", "varchar(140) DEFAULT NULL AFTER `validation_json`"),
		("executed_by", "varchar(140) DEFAULT NULL AFTER `execution_request_id`"),
		("executed_at", "datetime(6) DEFAULT NULL AFTER `executed_by`"),
		("target_doctype", "varchar(140) DEFAULT NULL AFTER `executed_at`"),
		("target_name", "varchar(140) DEFAULT NULL AFTER `target_doctype`"),
		("execution_result_json", "longtext DEFAULT NULL AFTER `target_name`"),
	):
		_add_column(column, definition)
	frappe.db.commit()
