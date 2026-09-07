import frappe


def execute():
	frappe.db.sql("""
		CREATE TABLE IF NOT EXISTS `tabMyApp Product Lifecycle Plan` (
			name varchar(140) NOT NULL,
			owner varchar(140) NOT NULL,
			creation datetime(6) NOT NULL,
			expires_at datetime(6) NOT NULL,
			status varchar(20) NOT NULL DEFAULT 'pending',
			version_no int NOT NULL DEFAULT 1,
			preview_json longtext NOT NULL,
			request_id varchar(140) DEFAULT NULL,
			receipt_json longtext DEFAULT NULL,
			executed_at datetime(6) DEFAULT NULL,
			PRIMARY KEY (name),
			KEY owner_status (owner, status, creation),
			UNIQUE KEY owner_request (owner, request_id)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
	""")
	frappe.db.commit()
