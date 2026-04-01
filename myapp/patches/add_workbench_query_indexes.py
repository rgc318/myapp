import frappe


def _index_exists(table_name: str, index_name: str) -> bool:
	rows = frappe.db.sql(
		f"SHOW INDEX FROM `{table_name}` WHERE Key_name = %s",
		(index_name,),
	)
	return bool(rows)


def _ensure_index(table_name: str, index_name: str, columns: tuple[str, ...]):
	if _index_exists(table_name, index_name):
		return

	column_sql = ", ".join(f"`{column}`" for column in columns)
	frappe.db.sql(
		f"ALTER TABLE `{table_name}` ADD INDEX `{index_name}` ({column_sql})"
	)


def execute():
	_ensure_index(
		"tabSales Order",
		"idx_myapp_so_company_modified",
		("company", "modified"),
	)
	_ensure_index(
		"tabSales Order",
		"idx_myapp_so_customer_modified",
		("customer", "modified"),
	)
	_ensure_index(
		"tabPurchase Order",
		"idx_myapp_po_company_modified",
		("company", "modified"),
	)
	_ensure_index(
		"tabPurchase Order",
		"idx_myapp_po_supplier_modified",
		("supplier", "modified"),
	)
	_ensure_index(
		"tabPayment Entry Reference",
		"idx_myapp_per_reference_lookup",
		("reference_doctype", "reference_name", "parenttype", "parentfield", "modified"),
	)
	frappe.db.commit()
