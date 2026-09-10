"""Opt-in real Stock Entry/Repack verification; every fixture is rolled back."""

import os
import secrets
from unittest import TestCase, skipUnless

import frappe
from frappe.utils import flt

from myapp.services.wholesale_service import _create_product_uom_repack_entries


@skipUnless(
	os.getenv("MYAPP_UOM_REPACK_TEST_SITE"),
	"Set MYAPP_UOM_REPACK_TEST_SITE for isolated Repack transaction tests",
)
class ProductUomMigrationRepackTransactions(TestCase):
	@classmethod
	def setUpClass(cls):
		cls._original_cwd = os.getcwd()
		frappe.init(
			site=os.environ["MYAPP_UOM_REPACK_TEST_SITE"],
			sites_path="/home/frappe/frappe-bench/sites",
		)
		os.chdir("/home/frappe/frappe-bench/sites")
		frappe.connect()
		frappe.set_user("Administrator")

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		frappe.destroy()
		os.chdir(cls._original_cwd)

	def tearDown(self):
		frappe.db.rollback()

	def _make_stock_item(self, item_code: str, stock_uom: str):
		item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"item_group": item_group,
				"stock_uom": stock_uom,
				"is_stock_item": 1,
				"include_item_in_manufacturing": 0,
			}
		)
		item.insert()
		return item

	def _receive_stock(self, *, item_code: str, warehouse: str, company: str, qty: float, rate: float):
		entry = frappe.new_doc("Stock Entry")
		entry.stock_entry_type = "Material Receipt"
		entry.purpose = "Material Receipt"
		entry.company = company
		entry.append(
			"items",
			{
				"item_code": item_code,
				"qty": qty,
				"t_warehouse": warehouse,
				"basic_rate": rate,
				"valuation_rate": rate,
			},
		)
		entry.insert()
		entry.submit()

	def _get_bin(self, item_code: str, warehouse: str):
		return frappe.db.get_value(
			"Bin",
			{"item_code": item_code, "warehouse": warehouse},
			["actual_qty", "valuation_rate", "stock_value"],
			as_dict=True,
		)

	def test_repack_moves_quantity_and_preserves_total_stock_value(self):
		warehouse = os.getenv("MYAPP_UOM_REPACK_TEST_WAREHOUSE", "Stores - RD")
		company = frappe.db.get_value("Warehouse", warehouse, "company")
		self.assertTrue(company, f"Warehouse {warehouse} must belong to a company")

		suffix = secrets.token_hex(5).upper()
		source = self._make_stock_item(f"UOM-REPACK-SRC-{suffix}", "Nos")
		target = self._make_stock_item(f"UOM-REPACK-DST-{suffix}", "Bottle")
		self._receive_stock(
			item_code=source.name,
			warehouse=warehouse,
			company=company,
			qty=24,
			rate=2,
		)
		before = self._get_bin(source.name, warehouse)

		entries = _create_product_uom_repack_entries(
			source_item=source,
			target_item=target,
			inventory_mappings=[
				{
					"company": company,
					"warehouse": warehouse,
					"source_qty": 24,
					"target_qty": 240,
				}
			],
			reason="isolated rollback verification",
		)

		after_source = self._get_bin(source.name, warehouse)
		after_target = self._get_bin(target.name, warehouse)
		self.assertEqual(flt(after_source.actual_qty), 0)
		self.assertEqual(flt(after_target.actual_qty), 240)
		self.assertAlmostEqual(flt(after_target.stock_value), flt(before.stock_value), places=6)
		self.assertAlmostEqual(flt(after_target.valuation_rate), 0.2, places=6)

		ledger_rows = frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_type": "Stock Entry", "voucher_no": entries[0]["name"]},
			fields=["item_code", "actual_qty", "stock_value_difference"],
		)
		self.assertEqual({row.item_code for row in ledger_rows}, {source.name, target.name})
		self.assertAlmostEqual(sum(flt(row.stock_value_difference) for row in ledger_rows), 0, places=6)

		frappe.db.rollback()
		self.assertFalse(frappe.db.exists("Item", source.name))
		self.assertFalse(frappe.db.exists("Item", target.name))


if __name__ == "__main__":
	import unittest

	unittest.main()
