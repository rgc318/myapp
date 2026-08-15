import frappe


def execute():
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Conversation` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`status` varchar(20) NOT NULL DEFAULT 'active',
			`title` varchar(255) DEFAULT NULL,
			`company_scope` varchar(140) DEFAULT NULL,
			`message_count` int(8) NOT NULL DEFAULT 0,
			`last_message_at` datetime(6) DEFAULT NULL,
			`retention_until` datetime(6) DEFAULT NULL,
			`state_version` int(11) NOT NULL DEFAULT 0,
			`working_state_json` longtext DEFAULT NULL,
			`state_updated_at` datetime(6) DEFAULT NULL,
			`context_start_sequence` int(11) NOT NULL DEFAULT 1,
			PRIMARY KEY (`name`),
			KEY `idx_myapp_ai_conversation_owner_status` (`owner`, `status`, `last_message_at`),
			KEY `idx_myapp_ai_conversation_retention` (`retention_until`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Message` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`conversation` varchar(140) NOT NULL,
			`sequence_no` int(8) NOT NULL,
			`role` varchar(20) NOT NULL,
			`content` longtext DEFAULT NULL,
			`content_hash` varchar(64) DEFAULT NULL,
			`scenario` varchar(40) DEFAULT NULL,
			`run_id` varchar(140) DEFAULT NULL,
			`citations_json` longtext DEFAULT NULL,
			`attachments_json` longtext DEFAULT NULL,
			`prompt_version` varchar(40) DEFAULT NULL,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_ai_message_sequence` (`conversation`, `sequence_no`),
			KEY `idx_myapp_ai_message_run` (`run_id`),
			KEY `idx_myapp_ai_message_creation` (`conversation`, `creation`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Run` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`conversation` varchar(140) NOT NULL,
			`requested_by` varchar(140) NOT NULL,
			`scenario` varchar(40) NOT NULL,
			`status` varchar(20) NOT NULL,
			`requested_model_alias` varchar(140) DEFAULT NULL,
			`retry_of_run_id` varchar(140) DEFAULT NULL,
			`model_alias` varchar(140) DEFAULT NULL,
			`model` varchar(140) DEFAULT NULL,
			`trace_id` varchar(140) DEFAULT NULL,
			`prompt_tokens` int(11) NOT NULL DEFAULT 0,
			`completion_tokens` int(11) NOT NULL DEFAULT 0,
			`total_tokens` int(11) NOT NULL DEFAULT 0,
			`reasoning_tokens` int(11) NOT NULL DEFAULT 0,
			`latency_ms` int(11) NOT NULL DEFAULT 0,
			`tool_calls_json` longtext DEFAULT NULL,
			`error_code` varchar(140) DEFAULT NULL,
			`error` text DEFAULT NULL,
			`started_at` datetime(6) DEFAULT NULL,
			`completed_at` datetime(6) DEFAULT NULL,
			PRIMARY KEY (`name`),
			KEY `idx_myapp_ai_run_owner_status` (`requested_by`, `status`, `started_at`),
			KEY `idx_myapp_ai_run_conversation` (`conversation`, `started_at`),
			KEY `idx_myapp_ai_run_retry_of` (`retry_of_run_id`),
			KEY `idx_myapp_ai_run_trace` (`trace_id`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.commit()
