import frappe


def _add_column(table: str, doctype: str, column: str, definition: str):
	if frappe.db.table_exists(doctype) and not frappe.db.has_column(doctype, column):
		frappe.db.sql(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")


def execute():
	_add_column(
		"tabMyApp AI Run", "MyApp AI Run", "environment",
		"varchar(30) NOT NULL DEFAULT 'development' AFTER `scenario`",
	)
	_add_column(
		"tabMyApp AI Run", "MyApp AI Run", "first_token_ms",
		"int(11) DEFAULT NULL AFTER `latency_ms`",
	)
	for column, definition in (
		("latency_p50_ms", "int(11) DEFAULT NULL AFTER `latency_sample_count`"),
		("latency_p95_ms", "int(11) DEFAULT NULL AFTER `latency_p50_ms`"),
		("first_token_p50_ms", "int(11) DEFAULT NULL AFTER `first_token_sample_count`"),
		("first_token_p95_ms", "int(11) DEFAULT NULL AFTER `first_token_p50_ms`"),
	):
		_add_column("tabMyApp AI Model Usage Daily", "MyApp AI Model Usage Daily", column, definition)
	frappe.db.commit()
