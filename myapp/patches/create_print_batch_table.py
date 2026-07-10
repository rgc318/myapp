import frappe


TABLE_NAME = "tabMyApp Print Batch"


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
			`status` varchar(20) NOT NULL,
			`output` varchar(20) NOT NULL,
			`requested_by` varchar(140) DEFAULT NULL,
			`requested_at` datetime(6) DEFAULT NULL,
			`started_at` datetime(6) DEFAULT NULL,
			`completed_at` datetime(6) DEFAULT NULL,
			`enqueue_job_id` varchar(255) DEFAULT NULL,
			`total_count` int(8) NOT NULL DEFAULT 0,
			`success_count` int(8) NOT NULL DEFAULT 0,
			`failed_count` int(8) NOT NULL DEFAULT 0,
			`skipped_count` int(8) NOT NULL DEFAULT 0,
			`items_json` longtext DEFAULT NULL,
			`results_json` longtext DEFAULT NULL,
			`metadata_json` longtext DEFAULT NULL,
			`error` text DEFAULT NULL,
			PRIMARY KEY (`name`),
			KEY `idx_myapp_print_batch_status` (`status`, `requested_at`),
			KEY `idx_myapp_print_batch_user` (`requested_by`, `requested_at`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.commit()
