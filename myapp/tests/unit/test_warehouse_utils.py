from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.utils.warehouse import validate_transaction_warehouse


class TestWarehouseUtils(TestCase):
	@patch("myapp.utils.warehouse.frappe.throw", side_effect=frappe.ValidationError("group warehouse"))
	@patch("myapp.utils.warehouse.frappe.db", new_callable=MagicMock)
	def test_validate_transaction_warehouse_rejects_group_warehouse(self, mock_db, mock_throw):
		mock_db.get_value.return_value = frappe._dict(
			{
				"name": "All Warehouses - TC",
				"company": "Test Company",
				"disabled": 0,
				"is_group": 1,
			}
		)

		with self.assertRaises(frappe.ValidationError):
			validate_transaction_warehouse("All Warehouses - TC", company="Test Company")

		mock_throw.assert_called_once()

	@patch("myapp.utils.warehouse.frappe.throw", side_effect=frappe.ValidationError("disabled warehouse"))
	@patch("myapp.utils.warehouse.frappe.db", new_callable=MagicMock)
	def test_validate_transaction_warehouse_rejects_disabled_warehouse(self, mock_db, mock_throw):
		mock_db.get_value.return_value = frappe._dict(
			{
				"name": "Stores - TC",
				"company": "Test Company",
				"disabled": 1,
				"is_group": 0,
			}
		)

		with self.assertRaises(frappe.ValidationError):
			validate_transaction_warehouse("Stores - TC", company="Test Company")

		mock_throw.assert_called_once()

	@patch("myapp.utils.warehouse.frappe.throw", side_effect=frappe.ValidationError("company mismatch"))
	@patch("myapp.utils.warehouse.frappe.db", new_callable=MagicMock)
	def test_validate_transaction_warehouse_rejects_company_mismatch(self, mock_db, mock_throw):
		mock_db.get_value.return_value = frappe._dict(
			{
				"name": "Stores - OC",
				"company": "Other Company",
				"disabled": 0,
				"is_group": 0,
			}
		)

		with self.assertRaises(frappe.ValidationError):
			validate_transaction_warehouse("Stores - OC", company="Test Company")

		mock_throw.assert_called_once()
