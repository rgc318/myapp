import frappe


def execute():
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Agent Approval` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`run_id` varchar(140) NOT NULL,
			`call_id` varchar(140) NOT NULL,
			`tool_name` varchar(140) NOT NULL,
			`risk_level` varchar(30) NOT NULL,
			`arguments_hash` varchar(64) NOT NULL,
			`arguments_summary_json` longtext DEFAULT NULL,
			`status` varchar(20) NOT NULL DEFAULT 'pending',
			`requested_by` varchar(140) NOT NULL,
			`requested_at` datetime(6) NOT NULL,
			`reviewed_by` varchar(140) DEFAULT NULL,
			`reviewed_at` datetime(6) DEFAULT NULL,
			`decision_reason` text DEFAULT NULL,
			`expires_at` datetime(6) NOT NULL,
			`executed_at` datetime(6) DEFAULT NULL,
			`result_hash` varchar(64) DEFAULT NULL,
			`version` int(11) NOT NULL DEFAULT 1,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_ai_agent_approval_call` (`run_id`, `call_id`),
			KEY `idx_myapp_ai_agent_approval_owner` (`requested_by`, `status`, `requested_at`),
			KEY `idx_myapp_ai_agent_approval_expiry` (`status`, `expires_at`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.commit()
