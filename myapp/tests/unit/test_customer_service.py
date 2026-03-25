from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from myapp.services.customer_service import (
	create_customer_v2,
	disable_customer_v2,
	get_customer_detail_v2,
	list_customers_v2,
	update_customer_v2,
)


class TestCustomerService(TestCase):
	@patch("myapp.services.customer_service._serialize_address_doc")
	@patch("myapp.services.customer_service._serialize_contact_doc")
	@patch("myapp.services.customer_service._get_doc_if_exists")
	@patch("myapp.services.customer_service.frappe.get_all")
	def test_list_customers_v2_returns_summaries_with_meta(
		self,
		mock_get_all,
		mock_get_doc_if_exists,
		mock_serialize_contact_doc,
		mock_serialize_address_doc,
	):
		mock_get_all.side_effect = [
			[
				frappe._dict(
					{
						"name": "CUST-0001",
						"customer_name": "Palmer Productions Ltd.",
						"customer_type": "Company",
						"customer_group": "Retail",
						"territory": "China",
						"default_currency": "CNY",
						"default_price_list": "Standard Selling",
						"mobile_no": None,
						"email_id": None,
						"disabled": 0,
						"modified": "2026-03-26 10:00:00",
						"creation": "2026-03-20 10:00:00",
						"customer_primary_contact": "CONT-001",
						"customer_primary_address": "ADDR-001",
						"customer_details": "测试备注",
					}
				)
			],
			["CUST-0001", "CUST-0002"],
		]
		mock_get_doc_if_exists.side_effect = [
			frappe._dict({"name": "CONT-001"}),
			frappe._dict({"name": "ADDR-001"}),
		]
		mock_serialize_contact_doc.return_value = {"name": "CONT-001", "display_name": "张三", "phone": "13800000000"}
		mock_serialize_address_doc.return_value = {"name": "ADDR-001", "address_line1": "测试路 100 号"}

		result = list_customers_v2(search_key="Palmer", limit=20, start=0)

		self.assertEqual(result["status"], "success")
		self.assertEqual(len(result["data"]), 1)
		self.assertEqual(result["data"][0]["name"], "CUST-0001")
		self.assertEqual(result["data"][0]["display_name"], "Palmer Productions Ltd.")
		self.assertEqual(result["data"][0]["default_contact"]["display_name"], "张三")
		self.assertEqual(result["meta"]["total"], 2)
		self.assertTrue(result["meta"]["has_more"])

	@patch("myapp.services.customer_service._get_recent_sales_order_shipping_addresses")
	@patch("myapp.services.customer_service._serialize_address_doc")
	@patch("myapp.services.customer_service._serialize_contact_doc")
	@patch("myapp.services.customer_service._get_doc_if_exists")
	@patch("myapp.services.customer_service.frappe.get_doc")
	def test_get_customer_detail_v2_includes_recent_addresses(
		self,
		mock_get_doc,
		mock_get_doc_if_exists,
		mock_serialize_contact_doc,
		mock_serialize_address_doc,
		mock_get_recent_sales_order_shipping_addresses,
	):
		mock_get_doc.return_value = frappe._dict(
			{
				"name": "CUST-0001",
				"customer_name": "Palmer Productions Ltd.",
				"customer_type": "Company",
				"customer_group": "Retail",
				"territory": "China",
				"default_currency": "CNY",
				"default_price_list": "Standard Selling",
				"mobile_no": None,
				"email_id": None,
				"disabled": 0,
				"customer_primary_contact": "CONT-001",
				"customer_primary_address": "ADDR-001",
				"customer_details": "测试备注",
			}
		)
		mock_get_doc_if_exists.side_effect = [
			frappe._dict({"name": "CONT-001"}),
			frappe._dict({"name": "ADDR-001"}),
		]
		mock_serialize_contact_doc.return_value = {"name": "CONT-001", "display_name": "张三"}
		mock_serialize_address_doc.return_value = {"name": "ADDR-001", "address_line1": "测试路 100 号"}
		mock_get_recent_sales_order_shipping_addresses.return_value = [{"name": "ADDR-001", "address_display": "测试地址"}]

		result = get_customer_detail_v2("CUST-0001")

		self.assertEqual(result["data"]["name"], "CUST-0001")
		self.assertEqual(result["data"]["recent_addresses"][0]["name"], "ADDR-001")

	@patch("myapp.services.customer_service.run_idempotent")
	def test_create_customer_v2_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {"status": "success", "data": {"name": "CUST-0001"}}

		result = create_customer_v2(customer_name="Palmer Productions Ltd.", request_id="cust-create-001")

		self.assertEqual(result["status"], "success")
		mock_run_idempotent.assert_called_once()

	@patch("myapp.services.customer_service._build_customer_payload")
	@patch("myapp.services.customer_service._upsert_primary_address")
	@patch("myapp.services.customer_service._upsert_primary_contact")
	@patch("myapp.services.customer_service._customer_name_exists")
	@patch("myapp.services.customer_service._new_doc")
	def test_create_customer_v2_creates_customer_contact_and_address(
		self,
		mock_new_doc,
		mock_exists,
		mock_upsert_primary_contact,
		mock_upsert_primary_address,
		mock_build_customer_payload,
	):
		customer_doc = MagicMock()
		customer_doc.name = "CUST-0001"
		customer_doc.customer_name = "Palmer Productions Ltd."
		customer_doc.mobile_no = None
		customer_doc.email_id = None
		customer_doc.disabled = 0
		customer_doc.customer_primary_contact = None
		customer_doc.customer_primary_address = None
		mock_new_doc.return_value = customer_doc
		mock_exists.return_value = False
		mock_upsert_primary_contact.return_value = frappe._dict({"name": "CONT-001"})
		mock_upsert_primary_address.return_value = frappe._dict({"name": "ADDR-001"})
		mock_build_customer_payload.return_value = {"name": "CUST-0001"}

		result = create_customer_v2(
			customer_name="Palmer Productions Ltd.",
			customer_group="Retail",
			default_contact={"display_name": "张三", "phone": "13800000000", "email": "a@test.com"},
			default_address={"address_line1": "测试路 100 号", "city": "北京", "country": "China"},
		)

		self.assertEqual(result["status"], "success")
		customer_doc.insert.assert_called_once()
		customer_doc.save.assert_called_once()
		mock_upsert_primary_contact.assert_called_once()
		mock_upsert_primary_address.assert_called_once()
		self.assertEqual(result["meta"]["created_contact"], "CONT-001")
		self.assertEqual(result["meta"]["created_address"], "ADDR-001")

	@patch("myapp.services.customer_service._build_customer_payload")
	@patch("myapp.services.customer_service._upsert_primary_address")
	@patch("myapp.services.customer_service._upsert_primary_contact")
	@patch("myapp.services.customer_service.frappe.get_doc")
	def test_update_customer_v2_updates_customer_and_primary_links(
		self,
		mock_get_doc,
		mock_upsert_primary_contact,
		mock_upsert_primary_address,
		mock_build_customer_payload,
	):
		customer_doc = MagicMock()
		customer_doc.name = "CUST-0001"
		customer_doc.customer_name = "旧客户"
		customer_doc.mobile_no = None
		customer_doc.email_id = None
		customer_doc.disabled = 0
		customer_doc.customer_primary_contact = "CONT-001"
		customer_doc.customer_primary_address = "ADDR-001"
		mock_get_doc.return_value = customer_doc
		mock_upsert_primary_contact.return_value = frappe._dict({"name": "CONT-001"})
		mock_upsert_primary_address.return_value = frappe._dict({"name": "ADDR-001"})
		mock_build_customer_payload.return_value = {"name": "CUST-0001"}

		result = update_customer_v2(
			customer="CUST-0001",
			customer_name="新客户",
			default_contact={"name": "CONT-001", "display_name": "李四"},
			default_address={"name": "ADDR-001", "address_line1": "新地址", "city": "上海", "country": "China"},
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(customer_doc.customer_name, "新客户")
		self.assertEqual(customer_doc.save.call_count, 2)
		mock_upsert_primary_contact.assert_called_once()
		mock_upsert_primary_address.assert_called_once()

	@patch("myapp.services.customer_service.run_idempotent")
	def test_disable_customer_v2_uses_idempotent_runner(self, mock_run_idempotent):
		mock_run_idempotent.return_value = {"status": "success", "data": {"name": "CUST-0001"}}

		result = disable_customer_v2(customer="CUST-0001", request_id="cust-disable-001")

		self.assertEqual(result["status"], "success")
		mock_run_idempotent.assert_called_once()
