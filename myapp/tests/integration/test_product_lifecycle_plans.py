"""Opt-in local transaction tests; all test Items/plans are rolled back."""
import os
import secrets
from unittest import TestCase, skipUnless
from unittest.mock import patch

import frappe

from myapp.services.product_lifecycle_plan_service import (
	create_product_lifecycle_plan, execute_product_lifecycle_plan, get_product_lifecycle_plan,
)


@skipUnless(os.getenv("MYAPP_LIFECYCLE_TEST_SITE"), "Set MYAPP_LIFECYCLE_TEST_SITE for isolated transaction tests")
class LifecyclePlanTransactions(TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.init(site=os.environ["MYAPP_LIFECYCLE_TEST_SITE"], sites_path="/home/frappe/frappe-bench/sites")
		frappe.connect()
		frappe.set_user("Administrator")

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		frappe.destroy()

	def tearDown(self):
		frappe.db.rollback()

	def make_item(self):
		code = "LIFECYCLE-TEST-" + secrets.token_hex(8)
		item = frappe.get_doc({"doctype": "Item", "item_code": code, "item_name": code,
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
			"stock_uom": "Nos", "is_stock_item": 0})
		item.insert()
		return item

	def execute(self, plan, request="lifecycle-test-request"):
		return execute_product_lifecycle_plan(plan["name"], plan["version"], confirmed=True,
			shared_scope_confirmed=True, request_id=request)

	def test_disable_and_replay_have_same_receipt(self):
		item = self.make_item()
		plan = create_product_lifecycle_plan("disable", [item.name], "隔离事务测试")
		first = self.execute(plan)
		self.assertEqual(frappe.db.get_value("Item", item.name, "disabled"), 1)
		second = self.execute(plan)
		self.assertTrue(second["replayed"])
		self.assertEqual(first["receipt"], second["receipt"])
		self.assertEqual(get_product_lifecycle_plan(plan["name"])["status"], "completed")
		enable_plan = create_product_lifecycle_plan("enable", [item.name], "隔离事务恢复启用")
		self.execute(enable_plan, request="lifecycle-enable-request")
		self.assertEqual(frappe.db.get_value("Item", item.name, "disabled"), 0)
		self.assertTrue(self.execute(plan)["replayed"])
		self.assertEqual(frappe.db.get_value("Item", item.name, "disabled"), 0)
		frappe.db.rollback()
		self.assertFalse(frappe.db.exists("Item", item.name))

	def test_native_delete_and_replay_record_deleted_document(self):
		item = self.make_item()
		plan = create_product_lifecycle_plan("delete", [item.name], "隔离删除事务测试")
		self.assertTrue(plan["preview"]["execution_available"])
		def execute():
			return execute_product_lifecycle_plan(plan["name"], plan["version"], confirmed=True,
				shared_scope_confirmed=True, deletion_confirmed=True, request_id="isolated-delete")
		first = execute()
		self.assertFalse(frappe.db.exists("Item", item.name))
		self.assertTrue(frappe.db.exists("Deleted Document", {"deleted_doctype": "Item", "deleted_name": item.name}))
		self.assertTrue(first["receipt"]["targets"][0]["deleted"])
		self.assertEqual(execute()["receipt"], first["receipt"])
		self.assertTrue(execute()["replayed"])

	def test_second_delete_failure_clears_after_commit_callbacks(self):
		first, second = self.make_item(), self.make_item()
		plan = create_product_lifecycle_plan("delete", [first.name, second.name], "隔离删除回滚测试")
		original_delete = frappe.delete_doc
		deleted = []
		def delete(doctype, name, **kwargs):
			if name == second.name:
				raise RuntimeError("injected deletion failure")
			result = original_delete(doctype, name, **kwargs)
			deleted.append(name)
			return result
		with patch.object(frappe, "delete_doc", side_effect=delete), self.assertRaises(RuntimeError):
			execute_product_lifecycle_plan(plan["name"], plan["version"], confirmed=True,
				shared_scope_confirmed=True, deletion_confirmed=True, request_id="isolated-delete-fail")
		self.assertEqual(deleted, [first.name])
		self.assertFalse(frappe.db.exists("Deleted Document", {"deleted_doctype": "Item", "deleted_name": first.name}))
		self.assertFalse(frappe.db.exists("MyApp Product Lifecycle Plan", plan["name"]))
		self.assertEqual(len(frappe.db.after_commit._functions), 0)

	def test_gateway_adapter_executes_isolated_native_delete(self):
		from myapp.api import gateway
		item = self.make_item()
		created = gateway.create_product_lifecycle_plan_v1("delete", [item.name], "Gateway 隔离事务删除")
		self.assertTrue(created["ok"])
		plan = created["data"]
		result = gateway.execute_product_lifecycle_plan_v1(plan["name"], 1,
			confirmed=True, shared_scope_confirmed=True, deletion_confirmed=True,
			request_id="isolated-gateway-delete")
		self.assertTrue(result["ok"], result.get("message"))
		self.assertTrue(result["data"]["receipt"]["targets"][0]["deleted"])
		self.assertFalse(frappe.db.exists("Item", item.name))

	def test_other_user_cannot_read_or_execute_administrator_plan(self):
		other_user = frappe.db.get_value("User", {"enabled": 1, "name": ["not in", ["Administrator", "Guest"]]}, "name")
		if not other_user:
			self.skipTest("A second enabled local user is needed for owner isolation")
		item = self.make_item()
		plan = create_product_lifecycle_plan("disable", [item.name], "隔离权限测试")
		try:
			frappe.set_user(other_user)
			with self.assertRaises(frappe.PermissionError):
				get_product_lifecycle_plan(plan["name"])
			with self.assertRaises(frappe.PermissionError):
				self.execute(plan)
		finally:
			frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists("Item", item.name))

	def test_reference_added_after_preview_blocks_entire_batch(self):
		first, second = self.make_item(), self.make_item()
		plan = create_product_lifecycle_plan("delete", [first.name, second.name], "执行前新增引用")
		# A real price dependency must not be silently removed by Item.on_trash.
		price_list = frappe.db.get_value("Price List", {"enabled": 1}, "name")
		if not price_list:
			self.skipTest("An enabled local Price List is needed")
		frappe.get_doc({"doctype": "Item Price", "item_code": second.name,
			"price_list": price_list, "price_list_rate": 1}).insert()
		with patch.object(frappe, "delete_doc", wraps=frappe.delete_doc) as delete, self.assertRaises(frappe.ValidationError):
			execute_product_lifecycle_plan(plan["name"], 1, confirmed=True,
				shared_scope_confirmed=True, deletion_confirmed=True, request_id="new-price-block")
		delete.assert_not_called()

	def test_stale_plan_refuses_write(self):
		item = self.make_item()
		plan = create_product_lifecycle_plan("disable", [item.name], "隔离事务测试")
		item.description = "changed after preview"
		item.save()
		with self.assertRaises(frappe.ValidationError):
			self.execute(plan)
		# Executor rolls back the entire transaction, including our uncommitted fixtures.
		self.assertFalse(frappe.db.exists("Item", item.name))
		self.assertFalse(frappe.db.exists("MyApp Product Lifecycle Plan", plan["name"]))

	def test_second_save_failure_rolls_back_first_save_and_receipt(self):
		first, second = self.make_item(), self.make_item()
		plan = create_product_lifecycle_plan("disable", [first.name, second.name], "隔离事务测试")
		item_class = type(first)
		original_save = item_class.save
		saved = []

		def save(document, *args, **kwargs):
			if document.name == second.name:
				raise RuntimeError("injected second-item failure")
			saved.append(document.name)
			return original_save(document, *args, **kwargs)

		with patch.object(item_class, "save", save), self.assertRaises(RuntimeError):
			self.execute(plan)
		self.assertEqual(saved, [first.name])
		self.assertFalse(frappe.db.exists("Item", first.name))
		self.assertFalse(frappe.db.exists("Item", second.name))
		self.assertFalse(frappe.db.exists("MyApp Product Lifecycle Plan", plan["name"]))
