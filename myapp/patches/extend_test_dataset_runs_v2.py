import frappe


DOCTYPE_NAME = "MyApp Test Dataset Run"


def _add_column(column: str, definition: str) -> None:
	if frappe.db.table_exists(DOCTYPE_NAME) and not frappe.db.has_column(DOCTYPE_NAME, column):
		frappe.db.sql(f"ALTER TABLE `tab{DOCTYPE_NAME}` ADD COLUMN `{column}` {definition}")


def execute():
	for column, definition in (
		("scenario_keys_json", "longtext DEFAULT NULL AFTER `config_hash`"),
		("progress_current", "int NOT NULL DEFAULT 0 AFTER `scenario_keys_json`"),
		("progress_total", "int NOT NULL DEFAULT 0 AFTER `progress_current`"),
		("progress_message", "varchar(255) DEFAULT NULL AFTER `progress_total`"),
	):
		_add_column(column, definition)
	frappe.db.commit()
