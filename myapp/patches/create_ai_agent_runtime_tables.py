import frappe


def execute():
	if not frappe.db.table_exists("MyApp AI Run"):
		return
	columns = {
		"allowed_tools_json": "longtext DEFAULT NULL",
		"capability_token_hash": "varchar(64) DEFAULT NULL",
		"capability_expires_at": "datetime(6) DEFAULT NULL",
		"agent_state_json": "longtext DEFAULT NULL",
		"cancellation_requested": "int(1) NOT NULL DEFAULT 0",
		"last_step_no": "int(11) NOT NULL DEFAULT 0",
	}
	for fieldname, definition in columns.items():
		if not frappe.db.has_column("MyApp AI Run", fieldname):
			frappe.db.sql(
				f"ALTER TABLE `tabMyApp AI Run` ADD COLUMN `{fieldname}` {definition}"
			)

	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Agent Step` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`run_id` varchar(140) NOT NULL,
			`sequence_no` int(11) NOT NULL,
			`call_id` varchar(140) DEFAULT NULL,
			`step_type` varchar(40) NOT NULL,
			`status` varchar(30) NOT NULL,
			`tool_name` varchar(140) DEFAULT NULL,
			`arguments_json` longtext DEFAULT NULL,
			`result_json` longtext DEFAULT NULL,
			`error_code` varchar(140) DEFAULT NULL,
			`span_id` varchar(64) DEFAULT NULL,
			`started_at` datetime(6) DEFAULT NULL,
			`completed_at` datetime(6) DEFAULT NULL,
			`latency_ms` int(11) NOT NULL DEFAULT 0,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_ai_agent_step_sequence` (`run_id`, `sequence_no`),
			UNIQUE KEY `uniq_myapp_ai_agent_step_call` (`run_id`, `call_id`),
			KEY `idx_myapp_ai_agent_step_status` (`run_id`, `status`, `started_at`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.commit()
