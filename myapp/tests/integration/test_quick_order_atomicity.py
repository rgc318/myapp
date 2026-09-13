"""Real ERP documents through Gateway, with every commit/cache write intercepted."""

import os
import secrets
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import patch

import frappe

from myapp.api import gateway
from myapp.services import order_service


@skipUnless(os.getenv("MYAPP_QUICK_ORDER_TEST_SITE"), "Requires explicit quick-order test site")
class QuickOrderAtomicityTests(TestCase):
	def setUp(self):
		frappe.init(site=os.environ["MYAPP_QUICK_ORDER_TEST_SITE"], sites_path="/home/frappe/frappe-bench/sites")
		frappe.connect()
		frappe.set_user("Administrator")
		self.commit = self.enterContext(patch.object(frappe.local.db, "commit"))
		self.enterContext(patch("myapp.utils.idempotency.store_idempotent_result", side_effect=lambda namespace, key, result, **kwargs: result))
		self.addCleanup(self._cleanup)
		self.key = "atomic-order-" + secrets.token_hex(10)
		self.code = "ATOMIC-ORDER-" + secrets.token_hex(10)
		self.warehouse = os.getenv("MYAPP_QUICK_ORDER_TEST_WAREHOUSE", "Stores - RD")
		self.company = frappe.db.get_value("Warehouse", self.warehouse, "company")
		self.customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
		group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		self.assertTrue(self.company and self.customer and group, "Requires warehouse/company, customer and Item Group")
		frappe.get_doc({"doctype": "Item", "item_code": self.code, "item_name": self.code,
			"stock_uom": "Nos", "item_group": group, "is_stock_item": 1,
			"include_item_in_manufacturing": 0}).insert()
		receipt = frappe.new_doc("Stock Entry")
		receipt.stock_entry_type = "Material Receipt"
		receipt.purpose = "Material Receipt"
		receipt.company = self.company
		receipt.append("items", {"item_code": self.code, "qty": 10, "t_warehouse": self.warehouse, "basic_rate": 2})
		receipt.insert()
		receipt.submit()
		self.commit.assert_not_called()
		frappe.local.request = SimpleNamespace(method="POST", headers={"Idempotency-Key": self.key})
		frappe.local.response = frappe._dict()
		frappe.local.form_dict = frappe._dict()
		self.documents = []

	def _cleanup(self):
		try:
			frappe.db.rollback()
			if hasattr(self, "code"):
				self.assertFalse(frappe.db.exists("Item", self.code))
		finally:
			frappe.db.rollback()
			frappe.destroy()

	def _execute(self, *, fail_invoice):
		original_submit = order_service._insert_and_submit

		def submit(doc):
			result = original_submit(doc)
			self.documents.append((doc.doctype, doc.name))
			self.assertEqual(doc.docstatus, 1)
			self.assertEqual(self.commit.call_count, 1, "Only the outer processing claim may have committed")
			if doc.doctype == "Sales Invoice" and fail_invoice:
				self.assertTrue(frappe.db.exists("GL Entry", {"voucher_type": doc.doctype, "voucher_no": doc.name}))
				raise frappe.ValidationError("Synthetic failure after invoice submission")
			return result

		with patch.object(order_service, "_insert_and_submit", side_effect=submit):
			return gateway.quick_create_order_v2(
				customer=self.customer,
				items=[{"item_code": self.code, "qty": 1, "price": 5, "uom": "Nos", "conversion_factor": 1, "warehouse": self.warehouse}],
				company=self.company, default_warehouse=self.warehouse, request_id=self.key, include_detail=0,
			)

	def test_failed_invoice_rolls_back_all_documents_and_ledgers(self):
		result = self._execute(fail_invoice=True)
		self.assertFalse(result["ok"])
		self.assertEqual(frappe.local.response.http_status_code, 422)
		self.assertEqual([doctype for doctype, _ in self.documents], ["Sales Order", "Delivery Note", "Sales Invoice"])
		self.assertEqual(self.commit.call_count, 2)
		for doctype, name in self.documents:
			self.assertFalse(frappe.db.exists(doctype, name))
			self.assertFalse(frappe.db.exists("GL Entry", {"voucher_type": doctype, "voucher_no": name}))
			self.assertFalse(frappe.db.exists("Stock Ledger Entry", {"voucher_type": doctype, "voucher_no": name}))
		self.assertFalse(frappe.db.exists("Bin", {"item_code": self.code}))
		self.assertFalse(frappe.db.exists("Item", self.code))

	def test_success_uses_only_outer_receipt_and_one_business_commit(self):
		result = self._execute(fail_invoice=False)
		self.assertTrue(result["ok"], result.get("message"))
		self.assertEqual([doctype for doctype, _ in self.documents], ["Sales Order", "Delivery Note", "Sales Invoice"])
		self.assertEqual(self.commit.call_count, 2)
		self.assertEqual(frappe.db.get_value("Bin", {"item_code": self.code, "warehouse": self.warehouse}, "actual_qty"), 9)
		rows = frappe.db.sql("SELECT namespace, status FROM `tabMyApp Idempotency Key` WHERE request_id=%s", (self.key,), as_dict=True)
		self.assertEqual([(row.namespace, row.status) for row in rows], [("quick_create_order_v2", "succeeded")])

	def test_missing_idempotency_table_rejects_before_business_execution(self):
		original = frappe.db.table_exists
		with patch.object(frappe.local.db, "table_exists", side_effect=lambda name: False if name == "MyApp Idempotency Key" else original(name)):
			result = self._execute(fail_invoice=False)
		self.assertFalse(result["ok"])
		self.assertEqual(result["code"], "IDEMPOTENCY_STORE_UNAVAILABLE")
		self.assertEqual(frappe.local.response.http_status_code, 503)
		self.assertEqual(self.documents, [])
		self.commit.assert_not_called()
		self.assertFalse(frappe.db.exists("Item", self.code))
