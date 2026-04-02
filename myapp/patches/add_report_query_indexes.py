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
		"tabSales Invoice",
		"idx_myapp_sinv_company_posting_customer",
		("company", "posting_date", "customer", "docstatus"),
	)
	_ensure_index(
		"tabPurchase Invoice",
		"idx_myapp_pinv_company_posting_supplier",
		("company", "posting_date", "supplier", "docstatus"),
	)
	_ensure_index(
		"tabPayment Entry",
		"idx_myapp_pe_company_posting_type",
		("company", "posting_date", "payment_type", "docstatus"),
	)
	frappe.db.commit()
