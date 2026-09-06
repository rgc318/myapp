import frappe


def execute():
	frappe.db.sql("""
		CREATE TABLE IF NOT EXISTS `tabMyApp AI Model Check Job` (
			name varchar(140) NOT NULL PRIMARY KEY,
			owner varchar(140) NOT NULL,
			creation datetime(6) NOT NULL,
			modified datetime(6) NOT NULL,
			status varchar(20) NOT NULL,
			active_key varchar(40) DEFAULT NULL,
			mode varchar(20) NOT NULL,
			aliases_json longtext NOT NULL,
			results_json longtext NOT NULL,
			cancel_requested int NOT NULL DEFAULT 0,
			UNIQUE KEY active_job (active_key),
			KEY owner_creation (owner, creation)
		) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
	""")
