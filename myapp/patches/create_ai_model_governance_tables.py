import frappe


GOVERNANCE_ROLES = ("AI Model Manager", "AI Model Approver", "AI Auditor")


def _ensure_roles():
	for role_name in GOVERNANCE_ROLES:
		if frappe.db.exists("Role", role_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 1,
			}
		).insert(ignore_permissions=True)


def _ensure_run_policy_columns():
	table = "tabMyApp AI Run"
	alter_statements = []
	if not frappe.db.has_column("MyApp AI Run", "policy_code"):
		alter_statements.append("ADD COLUMN `policy_code` varchar(140) DEFAULT NULL")
	if not frappe.db.has_column("MyApp AI Run", "policy_version"):
		alter_statements.append("ADD COLUMN `policy_version` int(8) DEFAULT NULL")
	if not frappe.db.has_column("MyApp AI Run", "fallback_reason"):
		alter_statements.append("ADD COLUMN `fallback_reason` varchar(255) DEFAULT NULL")
	if not frappe.db.has_column("MyApp AI Run", "estimated_cost"):
		alter_statements.append("ADD COLUMN `estimated_cost` decimal(21,9) NOT NULL DEFAULT 0")
	if not frappe.db.has_column("MyApp AI Run", "cost_currency"):
		alter_statements.append("ADD COLUMN `cost_currency` varchar(10) DEFAULT NULL")
	if alter_statements:
		frappe.db.sql(f"ALTER TABLE `{table}` {', '.join(alter_statements)}")


def execute():
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Model Registry` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`model_alias` varchar(140) NOT NULL,
			`capability` varchar(30) NOT NULL,
			`status` varchar(20) NOT NULL DEFAULT 'discovered',
			`provider_family` varchar(80) DEFAULT NULL,
			`provider_model_display` varchar(255) DEFAULT NULL,
			`supports_streaming` int(1) NOT NULL DEFAULT 0,
			`supports_json_schema` int(1) NOT NULL DEFAULT 0,
			`supports_vision` int(1) NOT NULL DEFAULT 0,
			`embedding_dimensions` int(11) DEFAULT NULL,
			`embedding_space_version` varchar(140) DEFAULT NULL,
			`data_region` varchar(80) DEFAULT NULL,
			`retention_policy` varchar(140) DEFAULT NULL,
			`sensitive_data_allowed` int(1) NOT NULL DEFAULT 0,
			`input_cost` decimal(21,9) NOT NULL DEFAULT 0,
			`output_cost` decimal(21,9) NOT NULL DEFAULT 0,
			`currency` varchar(10) DEFAULT NULL,
			`last_health_at` datetime(6) DEFAULT NULL,
			`last_health_status` varchar(20) DEFAULT NULL,
			`last_error_code` varchar(140) DEFAULT NULL,
			`registry_version` int(8) NOT NULL DEFAULT 1,
			`source_hash` varchar(64) NOT NULL,
			`source_json` longtext DEFAULT NULL,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_ai_model_alias` (`model_alias`),
			KEY `idx_myapp_ai_model_capability_status` (`capability`, `status`),
			KEY `idx_myapp_ai_model_health` (`last_health_status`, `last_health_at`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Model Policy` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`policy_code` varchar(140) NOT NULL,
			`policy_name` varchar(255) NOT NULL,
			`scenario` varchar(80) NOT NULL,
			`capability` varchar(30) NOT NULL,
			`company_scope_json` longtext DEFAULT NULL,
			`role_scope_json` longtext DEFAULT NULL,
			`environment` varchar(30) NOT NULL DEFAULT 'development',
			`primary_model_alias` varchar(140) NOT NULL,
			`fallback_model_aliases_json` longtext DEFAULT NULL,
			`reasoning_effort` varchar(20) DEFAULT NULL,
			`max_completion_tokens` int(11) NOT NULL DEFAULT 0,
			`timeout_seconds` int(11) NOT NULL DEFAULT 60,
			`max_concurrency` int(11) NOT NULL DEFAULT 0,
			`requests_per_minute` int(11) NOT NULL DEFAULT 0,
			`tokens_per_minute` int(11) NOT NULL DEFAULT 0,
			`daily_budget` decimal(21,9) NOT NULL DEFAULT 0,
			`monthly_budget` decimal(21,9) NOT NULL DEFAULT 0,
			`budget_currency` varchar(10) DEFAULT NULL,
			`budget_action` varchar(40) NOT NULL DEFAULT 'warn',
			`rollout_percentage` decimal(7,4) NOT NULL DEFAULT 100,
			`rollout_seed` varchar(140) DEFAULT NULL,
			`effective_from` datetime(6) DEFAULT NULL,
			`effective_to` datetime(6) DEFAULT NULL,
			`status` varchar(30) NOT NULL DEFAULT 'draft',
			`current_version` int(8) NOT NULL DEFAULT 1,
			`published_version` int(8) DEFAULT NULL,
			`last_validated_at` datetime(6) DEFAULT NULL,
			`last_validation_json` longtext DEFAULT NULL,
			`approved_by` varchar(140) DEFAULT NULL,
			`approved_at` datetime(6) DEFAULT NULL,
			`published_at` datetime(6) DEFAULT NULL,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_ai_policy_code` (`policy_code`),
			KEY `idx_myapp_ai_policy_resolution` (`scenario`, `environment`, `status`),
			KEY `idx_myapp_ai_policy_model` (`primary_model_alias`, `status`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Model Policy Version` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`policy_code` varchar(140) NOT NULL,
			`version_no` int(8) NOT NULL,
			`status` varchar(30) NOT NULL,
			`snapshot_json` longtext NOT NULL,
			`content_hash` varchar(64) NOT NULL,
			`evaluation_report_json` longtext DEFAULT NULL,
			`validation_json` longtext DEFAULT NULL,
			`created_by` varchar(140) NOT NULL,
			`approved_by` varchar(140) DEFAULT NULL,
			`approved_at` datetime(6) DEFAULT NULL,
			`published_by` varchar(140) DEFAULT NULL,
			`published_at` datetime(6) DEFAULT NULL,
			`rollback_from_version` int(8) DEFAULT NULL,
			`change_reason` text DEFAULT NULL,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_ai_policy_version` (`policy_code`, `version_no`),
			KEY `idx_myapp_ai_policy_version_status` (`policy_code`, `status`, `version_no`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Model Usage Daily` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`usage_date` date NOT NULL,
			`environment` varchar(30) NOT NULL,
			`company` varchar(140) NOT NULL DEFAULT '',
			`scenario` varchar(80) NOT NULL,
			`policy_code` varchar(140) NOT NULL DEFAULT '',
			`policy_version` int(8) NOT NULL DEFAULT 0,
			`model_alias` varchar(140) NOT NULL,
			`request_count` int(11) NOT NULL DEFAULT 0,
			`success_count` int(11) NOT NULL DEFAULT 0,
			`error_count` int(11) NOT NULL DEFAULT 0,
			`prompt_tokens` bigint(20) NOT NULL DEFAULT 0,
			`completion_tokens` bigint(20) NOT NULL DEFAULT 0,
			`total_tokens` bigint(20) NOT NULL DEFAULT 0,
			`estimated_cost` decimal(21,9) NOT NULL DEFAULT 0,
			`cost_currency` varchar(10) DEFAULT NULL,
			`latency_total_ms` bigint(20) NOT NULL DEFAULT 0,
			`latency_sample_count` int(11) NOT NULL DEFAULT 0,
			`latency_p50_ms` int(11) DEFAULT NULL,
			`latency_p95_ms` int(11) DEFAULT NULL,
			`first_token_total_ms` bigint(20) NOT NULL DEFAULT 0,
			`first_token_sample_count` int(11) NOT NULL DEFAULT 0,
			`first_token_p50_ms` int(11) DEFAULT NULL,
			`first_token_p95_ms` int(11) DEFAULT NULL,
			`positive_feedback_count` int(11) NOT NULL DEFAULT 0,
			`negative_feedback_count` int(11) NOT NULL DEFAULT 0,
			`fallback_count` int(11) NOT NULL DEFAULT 0,
			PRIMARY KEY (`name`),
			UNIQUE KEY `uniq_myapp_ai_usage_daily` (`usage_date`, `environment`, `company`, `scenario`, `policy_code`, `policy_version`, `model_alias`),
			KEY `idx_myapp_ai_usage_date_model` (`usage_date`, `model_alias`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	frappe.db.sql(
		"""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Audit Event` (
			`name` varchar(140) NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) DEFAULT NULL,
			`owner` varchar(140) DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`actor` varchar(140) NOT NULL,
			`action` varchar(80) NOT NULL,
			`object_type` varchar(80) NOT NULL,
			`object_name` varchar(140) NOT NULL,
			`reason` text DEFAULT NULL,
			`parameter_hash` varchar(64) NOT NULL,
			`result_hash` varchar(64) NOT NULL,
			`metadata_json` longtext DEFAULT NULL,
			`priority` varchar(20) NOT NULL DEFAULT 'normal',
			PRIMARY KEY (`name`),
			KEY `idx_myapp_ai_audit_object` (`object_type`, `object_name`, `creation`),
			KEY `idx_myapp_ai_audit_actor` (`actor`, `creation`),
			KEY `idx_myapp_ai_audit_action` (`action`, `creation`)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
		"""
	)
	_ensure_run_policy_columns()
	_ensure_roles()
	frappe.db.commit()
