import frappe


def execute():
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Vector Release` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`release_code` varchar(140) NOT NULL,
			`alias_name` varchar(140) NOT NULL,
			`collection_name` varchar(140) NOT NULL,
			`embedding_model` varchar(140) NOT NULL,
			`index_version` varchar(40) NOT NULL,
			`environment` varchar(30) NOT NULL,
			`status` varchar(30) NOT NULL DEFAULT 'building',
			`total_items` int(11) NOT NULL DEFAULT 0,
			`indexed_count` int(11) NOT NULL DEFAULT 0,
			`failed_count` int(11) NOT NULL DEFAULT 0,
			`vector_size` int(11) DEFAULT NULL,
			`previous_collection` varchar(140) DEFAULT NULL,
			`validation_json` longtext DEFAULT NULL,
			`created_by` varchar(140) NOT NULL,
			`approved_by` varchar(140) DEFAULT NULL,
			`approved_at` datetime(6) DEFAULT NULL,
			`published_by` varchar(140) DEFAULT NULL,
			`published_at` datetime(6) DEFAULT NULL,
			`rollback_from_release` varchar(140) DEFAULT NULL,
			`change_reason` text DEFAULT NULL,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_ai_vector_release_code` (`release_code`),
			KEY `idx_myapp_ai_vector_release_alias_status` (`alias_name`, `status`, `creation`),
			KEY `idx_myapp_ai_vector_release_collection` (`collection_name`, `status`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Vector Build Item` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`release_code` varchar(140) NOT NULL,
			`item_code` varchar(140) NOT NULL,
			`content_hash` varchar(64) DEFAULT NULL,
			`status` varchar(20) NOT NULL DEFAULT 'pending',
			`last_error` varchar(500) DEFAULT NULL,
			`last_attempt_at` datetime(6) DEFAULT NULL,
			`indexed_at` datetime(6) DEFAULT NULL,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_ai_vector_build_item` (`release_code`, `item_code`),
			KEY `idx_myapp_ai_vector_build_status` (`release_code`, `status`, `modified`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.commit()
