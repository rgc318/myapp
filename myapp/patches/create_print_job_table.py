import frappe


TABLE_NAME = "tabMyApp Print Job"


def execute():
	frappe.db.sql(
		f"""
		CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`reference_doctype` varchar(140) NOT NULL,
			`reference_name` varchar(140) NOT NULL,
			`template` varchar(140) DEFAULT NULL,
			`template_label` varchar(140) DEFAULT NULL,
			`print_format` varchar(140) DEFAULT NULL,
			`action` varchar(40) NOT NULL,
			`output` varchar(20) NOT NULL,
			`status` varchar(20) NOT NULL,
			`filename` varchar(255) DEFAULT NULL,
			`file_url` text DEFAULT NULL,
			`printed_by` varchar(140) DEFAULT NULL,
			`printed_at` datetime(6) DEFAULT NULL,
			`user_agent` text DEFAULT NULL,
			`ip_address` varchar(140) DEFAULT NULL,
			`error` text DEFAULT NULL,
			`metadata_json` longtext DEFAULT NULL,
			PRIMARY KEY (`name`),
			KEY `idx_myapp_print_job_reference` (`reference_doctype`, `reference_name`, `printed_at`),
			KEY `idx_myapp_print_job_user` (`printed_by`, `printed_at`),
			KEY `idx_myapp_print_job_action_status` (`action`, `status`, `printed_at`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.commit()
