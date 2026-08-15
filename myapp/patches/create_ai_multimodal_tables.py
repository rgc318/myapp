import frappe


def execute():
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Attachment` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`status` varchar(20) NOT NULL DEFAULT 'uploaded',
			`purpose` varchar(40) NOT NULL DEFAULT 'vision_input',
			`file_id` varchar(140) NOT NULL,
			`file_url` text NOT NULL,
			`file_name` varchar(255) DEFAULT NULL,
			`content_type` varchar(80) NOT NULL,
			`file_size` int(11) NOT NULL DEFAULT 0,
			`width` int(11) NOT NULL DEFAULT 0,
			`height` int(11) NOT NULL DEFAULT 0,
			`content_sha256` varchar(64) NOT NULL,
			`conversation` varchar(140) DEFAULT NULL,
			`message_id` varchar(140) DEFAULT NULL,
			`source_run` varchar(140) DEFAULT NULL,
			`derived_item_image_url` text DEFAULT NULL,
			`retention_until` datetime(6) DEFAULT NULL,
			PRIMARY KEY (`name`),
			KEY `idx_myapp_ai_attachment_owner_status` (`owner`, `status`, `creation`),
			KEY `idx_myapp_ai_attachment_conversation` (`conversation`, `message_id`),
			KEY `idx_myapp_ai_attachment_retention` (`retention_until`, `status`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	if not frappe.db.has_column("MyApp AI Message", "attachments_json"):
		frappe.db.sql(
			"ALTER TABLE `tabMyApp AI Message` "
			"ADD COLUMN `attachments_json` longtext DEFAULT NULL AFTER `citations_json`"
		)
