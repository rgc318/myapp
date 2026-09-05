import frappe


TABLE = "tabMyApp AI Model Registry"
HEALTH_INDEX = "idx_myapp_ai_model_health"


def execute():
	if not frappe.db.table_exists("MyApp AI Model Registry"):
		return
	columns = (
		("health_expires_at", "datetime(6) DEFAULT NULL", "last_health_at"),
		("health_failure_count", "int NOT NULL DEFAULT 0", "last_health_status"),
		("last_health_trigger", "varchar(40) DEFAULT NULL", "health_failure_count"),
	)
	for fieldname, definition, after in columns:
		if not frappe.db.has_column("MyApp AI Model Registry", fieldname):
			frappe.db.sql(
				f"ALTER TABLE `{TABLE}` "
				f"ADD COLUMN `{fieldname}` {definition} AFTER `{after}`"
			)
	index_rows = frappe.db.sql(
		f"SHOW INDEX FROM `{TABLE}` WHERE Key_name = %s",
		(HEALTH_INDEX,),
		as_dict=True,
	)
	index_columns = [row.Column_name for row in sorted(index_rows, key=lambda row: row.Seq_in_index)]
	if index_columns != ["last_health_status", "health_expires_at"]:
		if index_rows:
			frappe.db.sql(f"ALTER TABLE `{TABLE}` DROP INDEX `{HEALTH_INDEX}`")
		frappe.db.sql(
			f"ALTER TABLE `{TABLE}` ADD INDEX `{HEALTH_INDEX}` "
			"(`last_health_status`, `health_expires_at`)"
		)
