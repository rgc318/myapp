import frappe


TABLE_NAME = "tabMyApp Print Setting"


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
			`default_template` varchar(140) NOT NULL,
			`enabled` int(1) NOT NULL DEFAULT 1,
			`metadata_json` longtext DEFAULT NULL,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_print_setting_doctype` (`reference_doctype`),
			KEY `idx_myapp_print_setting_enabled` (`enabled`, `reference_doctype`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.commit()
