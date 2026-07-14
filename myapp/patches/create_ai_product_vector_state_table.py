import frappe


def execute():
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Product Vector State` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`item_code` varchar(140) NOT NULL,
			`content_hash` varchar(64) DEFAULT NULL,
			`index_version` varchar(40) DEFAULT NULL,
			`embedding_model` varchar(140) DEFAULT NULL,
			`vector_collection` varchar(140) DEFAULT NULL,
			`source_modified` datetime(6) DEFAULT NULL,
			`status` varchar(20) NOT NULL DEFAULT 'pending',
			`last_error` varchar(500) DEFAULT NULL,
			`last_attempt_at` datetime(6) DEFAULT NULL,
			`indexed_at` datetime(6) DEFAULT NULL,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_ai_vector_item` (`item_code`),
			KEY `idx_myapp_ai_vector_status_modified` (`status`, `source_modified`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.commit()
