import frappe


RUN_TABLE = "tabMyApp Test Dataset Run"
OBJECT_TABLE = "tabMyApp Test Dataset Object"


def execute():
	frappe.db.sql(
		f"""
		CREATE TABLE IF NOT EXISTS `{RUN_TABLE}` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`status` varchar(32) NOT NULL,
			`action` varchar(32) NOT NULL,
			`dataset_code` varchar(140) NOT NULL,
			`dataset_version` varchar(64) NOT NULL,
			`scale` varchar(32) NOT NULL,
			`company` varchar(140) NOT NULL,
			`warehouse` varchar(140) NOT NULL,
			`seed` bigint NOT NULL DEFAULT 1,
			`base_date` date NOT NULL,
			`requested_by` varchar(140) NOT NULL,
			`started_at` datetime(6) DEFAULT NULL,
			`completed_at` datetime(6) DEFAULT NULL,
			`previous_run` varchar(140) DEFAULT NULL,
			`config_hash` varchar(64) DEFAULT NULL,
			`result_json` longtext DEFAULT NULL,
			`error_text` longtext DEFAULT NULL,
			PRIMARY KEY (`name`),
			KEY `idx_myapp_tdm_run_status` (`status`, `modified`),
			KEY `idx_myapp_tdm_run_scope` (`company`, `dataset_code`, `creation`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.sql(
		f"""
		CREATE TABLE IF NOT EXISTS `{OBJECT_TABLE}` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`run_name` varchar(140) NOT NULL,
			`scenario_key` varchar(140) NOT NULL,
			`doctype_name` varchar(140) NOT NULL,
			`document_name` varchar(140) NOT NULL,
			`document_order` int NOT NULL DEFAULT 0,
			`metadata_json` longtext DEFAULT NULL,
			`deleted` int(1) NOT NULL DEFAULT 0,
			`deleted_at` datetime(6) DEFAULT NULL,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_tdm_run_object` (`run_name`, `doctype_name`, `document_name`),
			KEY `idx_myapp_tdm_object_active` (`run_name`, `deleted`, `document_order`),
			KEY `idx_myapp_tdm_object_document` (`doctype_name`, `document_name`, `deleted`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.commit()
