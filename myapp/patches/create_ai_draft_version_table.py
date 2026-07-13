import frappe


def execute():
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Draft Version` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`draft` varchar(140) NOT NULL,
			`version_no` int(8) NOT NULL,
			`change_source` varchar(40) NOT NULL DEFAULT 'generated',
			`payload_json` longtext DEFAULT NULL,
			`validation_json` longtext DEFAULT NULL,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_ai_draft_version` (`draft`, `version_no`),
			KEY `idx_myapp_ai_draft_version_creation` (`draft`, `creation`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	# Existing drafts predate immutable snapshots; preserve their current state as the baseline version.
	frappe.db.sql(
		"""
		INSERT IGNORE INTO `tabMyApp AI Draft Version`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 draft, version_no, change_source, payload_json, validation_json)
		SELECT CONCAT('AI-DRAFT-VERSION-', REPLACE(UUID(), '-', '')), creation, modified,
			modified_by, owner, 0, version_no, name, version_no, 'migration', payload_json, validation_json
		FROM `tabMyApp AI Draft`
		"""
	)
	frappe.db.commit()
