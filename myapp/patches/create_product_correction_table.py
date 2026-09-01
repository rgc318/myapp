import frappe


TABLE_NAME = "tabMyApp Product Correction"


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
			`source_item` varchar(140) NOT NULL,
			`target_item` varchar(140) DEFAULT NULL,
			`correction_type` varchar(30) NOT NULL,
			`status` varchar(20) NOT NULL DEFAULT 'completed',
			`reason` text DEFAULT NULL,
			`source_modified_before` datetime(6) DEFAULT NULL,
			`target_modified_after` datetime(6) DEFAULT NULL,
			`before_snapshot_json` longtext DEFAULT NULL,
			`after_snapshot_json` longtext DEFAULT NULL,
			`metadata_json` longtext DEFAULT NULL,
			`request_id` varchar(140) DEFAULT NULL,
			`executed_by` varchar(140) DEFAULT NULL,
			`executed_at` datetime(6) DEFAULT NULL,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_product_correction_request` (`request_id`),
			KEY `idx_myapp_product_correction_source` (`source_item`, `status`, `creation`),
			KEY `idx_myapp_product_correction_target` (`target_item`, `status`, `creation`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.commit()
