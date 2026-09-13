"""Opt-in real gateway rollback check, with all commits intercepted."""

import os
import secrets
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

import frappe
from frappe.app import sync_database

from myapp.api import gateway


@skipUnless(os.getenv("MYAPP_GATEWAY_ROLLBACK_TEST_SITE"), "Requires explicit rollback test site")
class GatewayRollbackTransactions(TestCase):
	def test_invalid_initial_stock_leaves_no_item_or_after_commit_callback(self):
		frappe.init(site=os.environ["MYAPP_GATEWAY_ROLLBACK_TEST_SITE"], sites_path="/home/frappe/frappe-bench/sites")
		frappe.connect()
		frappe.set_user("Administrator")
		frappe.local.request = SimpleNamespace(method="POST", headers={})
		frappe.local.response = frappe._dict()
		frappe.local.form_dict = frappe._dict()
		code = "GATEWAY-ROLLBACK-" + secrets.token_hex(8)
		try:
			group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
			warehouse = frappe.db.get_value("Warehouse", {"is_group": 0, "disabled": 0}, "name")
			self.assertTrue(group and warehouse, "Requires an Item Group and Warehouse")
			after_commit = Mock()
			frappe.db.after_commit.add(after_commit)
			with patch.object(frappe.db, "commit") as commit:
				result = gateway.create_product_v2(
					item_name=code, item_code=code, stock_uom="Nos", item_group=group,
					warehouse=warehouse, warehouse_stock_qty=-1,
				)
				self.assertFalse(result["ok"])
				self.assertEqual(frappe.local.response.http_status_code, 422)
				commit.assert_not_called()
				self.assertFalse(frappe.db.exists("Item", code))
				self.assertEqual(len(frappe.db.after_commit._functions), 0)
				sync_database()
				commit.assert_called_once()
				after_commit.assert_not_called()
		finally:
			frappe.db.rollback()
			frappe.destroy()
