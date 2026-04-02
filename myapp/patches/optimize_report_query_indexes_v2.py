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
		"idx_myapp_so_company_docstatus_date_customer",
		("company", "docstatus", "transaction_date", "customer"),
	)
	_ensure_index(
		"tabPurchase Order",
		"idx_myapp_po_company_docstatus_date_supplier",
		("company", "docstatus", "transaction_date", "supplier"),
	)
	_ensure_index(
		"tabSales Invoice",
		"idx_myapp_sinv_company_docstatus_return_date_customer",
		("company", "docstatus", "is_return", "posting_date", "customer"),
	)
	_ensure_index(
		"tabPurchase Invoice",
		"idx_myapp_pinv_company_docstatus_return_date_supplier",
		("company", "docstatus", "is_return", "posting_date", "supplier"),
	)
	_ensure_index(
		"tabPayment Entry",
		"idx_myapp_pe_company_docstatus_date_type",
		("company", "docstatus", "posting_date", "payment_type"),
	)
	frappe.db.commit()
