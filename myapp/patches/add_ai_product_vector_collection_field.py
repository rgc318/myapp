import frappe


def execute():
	if not frappe.db.table_exists("MyApp AI Product Vector State"):
		return
	columns = {row[0] for row in frappe.db.sql("SHOW COLUMNS FROM `tabMyApp AI Product Vector State`")}
	if "vector_collection" not in columns:
		frappe.db.sql(
			"ALTER TABLE `tabMyApp AI Product Vector State` "
			"ADD COLUMN `vector_collection` varchar(140) DEFAULT NULL AFTER `embedding_model`"
		)
	frappe.db.commit()
