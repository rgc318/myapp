import frappe


def execute():
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Feedback` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`conversation` varchar(140) NOT NULL,
			`run_id` varchar(140) NOT NULL,
			`rating` varchar(20) NOT NULL,
			`category` varchar(40) DEFAULT NULL,
			`comment` text DEFAULT NULL,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_ai_feedback_run_owner` (`run_id`, `owner`),
			KEY `idx_myapp_ai_feedback_conversation` (`conversation`, `creation`),
			KEY `idx_myapp_ai_feedback_rating` (`rating`, `creation`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.commit()
