import frappe


TABLE_NAME = "tabMyApp Idempotency Key"


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
			`namespace` varchar(140) NOT NULL,
			`request_id` varchar(140) NOT NULL,
			`status` varchar(20) NOT NULL,
			`response_json` longtext DEFAULT NULL,
			`error` text DEFAULT NULL,
			`expires_at` datetime(6) DEFAULT NULL,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_idempotency_namespace_request` (`namespace`, `request_id`),
			KEY `idx_myapp_idempotency_expires_status` (`expires_at`, `status`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.commit()
