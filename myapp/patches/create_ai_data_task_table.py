import frappe


DATA_ROLES = ("AI Data Steward", "AI Data Approver")


def _ensure_roles():
	for role_name in DATA_ROLES:
		if frappe.db.exists("Role", role_name):
			continue
		frappe.get_doc({
			"doctype": "Role", "role_name": role_name, "desk_access": 1,
		}).insert(ignore_permissions=True)


def execute():
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Data Task` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`task_type` varchar(80) NOT NULL,
			`target_doctype` varchar(80) NOT NULL,
			`target_name` varchar(140) NOT NULL,
			`company` varchar(140) DEFAULT NULL,
			`status` varchar(30) NOT NULL DEFAULT 'queued',
			`risk_level` varchar(20) NOT NULL DEFAULT 'low',
			`before_value_json` longtext NOT NULL,
			`proposed_value_json` longtext NOT NULL,
			`evidence_json` longtext NOT NULL,
			`analysis_json` longtext DEFAULT NULL,
			`proposal_hash` varchar(64) NOT NULL,
			`model_alias` varchar(140) DEFAULT NULL,
			`prompt_version` varchar(140) DEFAULT NULL,
			`policy_code` varchar(140) DEFAULT NULL,
			`policy_version` int(8) DEFAULT NULL,
			`source_run` varchar(140) DEFAULT NULL,
			`requested_by` varchar(140) NOT NULL,
			`analyzed_by` varchar(140) DEFAULT NULL,
			`analyzed_at` datetime(6) DEFAULT NULL,
			`reviewer` varchar(140) DEFAULT NULL,
			`reviewed_at` datetime(6) DEFAULT NULL,
			`review_reason` text DEFAULT NULL,
			`executed_by` varchar(140) DEFAULT NULL,
			`executed_at` datetime(6) DEFAULT NULL,
			`execution_result_json` longtext DEFAULT NULL,
			`rollback_by` varchar(140) DEFAULT NULL,
			`rollback_at` datetime(6) DEFAULT NULL,
			`rollback_reason` text DEFAULT NULL,
			`rollback_result_json` longtext DEFAULT NULL,
			`version_no` int(8) NOT NULL DEFAULT 1,
			PRIMARY KEY (`name`),
			KEY `idx_myapp_ai_data_task_status` (`status`, `modified`),
			KEY `idx_myapp_ai_data_task_target` (`target_doctype`, `target_name`, `status`),
			KEY `idx_myapp_ai_data_task_proposal` (`proposal_hash`, `status`),
			KEY `idx_myapp_ai_data_task_requester` (`requested_by`, `creation`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	_ensure_roles()
	frappe.db.commit()
