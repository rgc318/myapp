import frappe


def execute():
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Draft` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`conversation` varchar(140) NOT NULL,
			`source_run` varchar(140) NOT NULL,
			`draft_type` varchar(40) NOT NULL,
			`status` varchar(30) NOT NULL DEFAULT 'draft',
			`company` varchar(140) DEFAULT NULL,
			`title` varchar(255) DEFAULT NULL,
			`version_no` int(8) NOT NULL DEFAULT 1,
			`payload_json` longtext DEFAULT NULL,
			`validation_json` longtext DEFAULT NULL,
			`retention_until` datetime(6) DEFAULT NULL,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_ai_draft_source` (`source_run`, `draft_type`),
			KEY `idx_myapp_ai_draft_owner_status` (`owner`, `status`, `modified`),
			KEY `idx_myapp_ai_draft_conversation` (`conversation`, `creation`),
			KEY `idx_myapp_ai_draft_retention` (`retention_until`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Draft Line` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`draft` varchar(140) NOT NULL,
			`line_no` int(8) NOT NULL,
			`item_query` varchar(255) DEFAULT NULL,
			`item_code` varchar(140) DEFAULT NULL,
			`item_name` varchar(255) DEFAULT NULL,
			`uom` varchar(140) DEFAULT NULL,
			`uom_display` varchar(255) DEFAULT NULL,
			`qty` decimal(21,9) NOT NULL DEFAULT 0,
			`rate` decimal(21,9) DEFAULT NULL,
			`warehouse` varchar(140) DEFAULT NULL,
			`conversion_factor` decimal(21,9) DEFAULT NULL,
			`candidates_json` longtext DEFAULT NULL,
			`warnings_json` longtext DEFAULT NULL,
			`user_overrides_json` longtext DEFAULT NULL,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_ai_draft_line` (`draft`, `line_no`),
			KEY `idx_myapp_ai_draft_line_item` (`item_code`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.commit()
