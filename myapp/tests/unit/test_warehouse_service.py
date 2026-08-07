from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.warehouse_service import (
	create_warehouse_v2,
	disable_warehouse_v2,
	list_warehouses_v2,
	update_warehouse_v2,
)


class TestWarehouseService(TestCase):
	@patch("myapp.services.warehouse_service.frappe.get_list")
	def test_list_warehouses_v2_returns_rows_with_meta(self, mock_get_list):
		mock_get_list.side_effect = [
			[
				frappe._dict(
					{
						"name": "Stores - TC",
						"warehouse_name": "Stores",
						"company": "Test Company",
						"parent_warehouse": "All Warehouses - TC",
						"is_group": 0,
						"disabled": 0,
						"account": "Stock In Hand - TC",
						"warehouse_type": "Stores",
						"default_in_transit_warehouse": "Transit - TC",
						"is_rejected_warehouse": 0,
						"customer": "CUST-0001",
						"email_id": "store@example.test",
						"phone_no": "021-12345678",
						"mobile_no": "13800000000",
						"address_line_1": "A1",
						"address_line_2": None,
						"city": "Shanghai",
						"state": None,
						"pin": None,
						"modified": "2026-06-30 10:00:00",
						"creation": "2026-06-01 10:00:00",
					}
				)
			],
			["Stores - TC", "Transit - TC"],
		]

		result = list_warehouses_v2(
			search_key="Store",
			company="Test Company",
			disabled=0,
			is_group=0,
			date_from="2026-06-01",
			date_to="2026-06-30",
			limit=20,
			start=0,
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"][0]["name"], "Stores - TC")
		self.assertEqual(result["data"][0]["warehouse_name"], "Stores")
		self.assertEqual(result["data"][0]["account"], "Stock In Hand - TC")
		self.assertEqual(result["data"][0]["warehouse_type"], "Stores")
		self.assertEqual(result["data"][0]["customer"], "CUST-0001")
		self.assertEqual(result["meta"]["total"], 2)
		self.assertEqual(result["pagination"]["total_count"], 2)
		self.assertEqual(result["meta"]["filters"]["company"], "Test Company")
		self.assertEqual(result["meta"]["filters"]["disabled"], 0)
		self.assertEqual(result["meta"]["filters"]["is_group"], 0)

	@patch("myapp.services.warehouse_service.run_idempotent")
	@patch("myapp.services.warehouse_service.frappe.db", new_callable=MagicMock)
	def test_create_warehouse_v2_uses_idempotent_runner(self, mock_db, mock_run_idempotent):
		mock_db.exists.return_value = True
		mock_run_idempotent.return_value = {"status": "success", "data": {"name": "Stores - TC"}}

		result = create_warehouse_v2(
			warehouse_name="Stores",
			company="Test Company",
			request_id="wh-create-001",
		)

		self.assertEqual(result["status"], "success")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.warehouse_service.frappe.new_doc")
	@patch("myapp.services.warehouse_service.frappe.db", new_callable=MagicMock)
	def test_create_warehouse_v2_creates_warehouse(self, mock_db, mock_new_doc):
		mock_db.exists.return_value = True
		mock_db.get_value.return_value = frappe._dict(
			{"name": "All Warehouses - TC", "company": "Test Company", "is_group": 1}
		)
		doc = MagicMock()
		doc.name = "Stores - TC"
		doc.warehouse_name = "Stores"
		doc.company = "Test Company"
		doc.parent_warehouse = "All Warehouses - TC"
		doc.is_group = 0
		doc.disabled = 0
		doc.account = "Stock In Hand - TC"
		doc.warehouse_type = "Stores"
		doc.default_in_transit_warehouse = "Transit - TC"
		doc.is_rejected_warehouse = 1
		doc.customer = "CUST-0001"
		doc.email_id = "store@example.test"
		doc.phone_no = "021-12345678"
		doc.mobile_no = "13800000000"
		mock_new_doc.return_value = doc

		result = create_warehouse_v2(
			warehouse_name="Stores",
			company="Test Company",
			parent_warehouse="All Warehouses - TC",
			account="Stock In Hand - TC",
			warehouse_type="Stores",
			default_in_transit_warehouse="Transit - TC",
			is_rejected_warehouse=1,
			customer="CUST-0001",
			email_id="store@example.test",
			phone_no="021-12345678",
			mobile_no="13800000000",
			city="Shanghai",
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(doc.warehouse_name, "Stores")
		self.assertEqual(doc.company, "Test Company")
		self.assertEqual(doc.parent_warehouse, "All Warehouses - TC")
		self.assertEqual(doc.account, "Stock In Hand - TC")
		self.assertEqual(doc.warehouse_type, "Stores")
		self.assertEqual(doc.default_in_transit_warehouse, "Transit - TC")
		self.assertEqual(doc.is_rejected_warehouse, 1)
		self.assertEqual(doc.customer, "CUST-0001")
		self.assertEqual(doc.city, "Shanghai")
		doc.insert.assert_called_once()

	@patch("myapp.services.warehouse_service.frappe.get_doc")
	@patch("myapp.services.warehouse_service.frappe.db", new_callable=MagicMock)
	def test_update_warehouse_v2_updates_allowed_fields(self, mock_db, mock_get_doc):
		mock_db.exists.return_value = True
		mock_db.get_value.return_value = frappe._dict(
			{"name": "All Warehouses - TC", "company": "Test Company", "is_group": 1}
		)
		doc = MagicMock()
		doc.name = "Stores - TC"
		doc.warehouse_name = "Stores"
		doc.company = "Test Company"
		doc.parent_warehouse = None
		doc.is_group = 0
		doc.disabled = 0
		doc.is_rejected_warehouse = 0
		mock_get_doc.return_value = doc

		result = update_warehouse_v2(
			warehouse="Stores - TC",
			warehouse_name="Main Stores",
			parent_warehouse="All Warehouses - TC",
			account="Stock In Hand - TC",
			warehouse_type="Stores",
			default_in_transit_warehouse="Transit - TC",
			is_rejected_warehouse=1,
			customer="CUST-0001",
			email_id="store@example.test",
			phone_no="021-12345678",
			disabled=1,
			address_line_1="A1",
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(doc.warehouse_name, "Main Stores")
		self.assertEqual(doc.parent_warehouse, "All Warehouses - TC")
		self.assertEqual(doc.account, "Stock In Hand - TC")
		self.assertEqual(doc.warehouse_type, "Stores")
		self.assertEqual(doc.default_in_transit_warehouse, "Transit - TC")
		self.assertEqual(doc.is_rejected_warehouse, 1)
		self.assertEqual(doc.customer, "CUST-0001")
		self.assertEqual(doc.email_id, "store@example.test")
		self.assertEqual(doc.phone_no, "021-12345678")
		self.assertEqual(doc.disabled, 1)
		self.assertEqual(doc.address_line_1, "A1")
		doc.save.assert_called_once()

	@patch("myapp.services.warehouse_service.run_idempotent")
	def test_disable_warehouse_v2_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {"status": "success", "data": {"name": "Stores - TC"}}

		result = disable_warehouse_v2("Stores - TC", disabled=True, request_id="wh-disable-001")

		self.assertEqual(result["status"], "success")
		mock_run_idempotent.assert_called_once()
