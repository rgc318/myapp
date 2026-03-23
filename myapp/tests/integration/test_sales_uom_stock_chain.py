import os
import time
import unittest

import frappe
from frappe.utils import flt

from myapp.services.order_service import create_order_v2, submit_delivery, update_order_items_v2
from myapp.services.wholesale_service import create_product_and_stock


SITE_NAME = os.environ.get("MYAPP_TEST_SITE", "localhost").strip() or "localhost"
SITES_PATH = os.environ.get("MYAPP_TEST_SITES_PATH", "/home/frappe/frappe-bench/sites").strip()
WAREHOUSE = os.environ.get("MYAPP_TEST_WAREHOUSE", "Stores - RD").strip() or "Stores - RD"
COMPANY = os.environ.get("MYAPP_TEST_COMPANY", "rgc (Demo)").strip() or "rgc (Demo)"
CUSTOMER = os.environ.get("MYAPP_TEST_CUSTOMER", "Palmer Productions Ltd.").strip() or "Palmer Productions Ltd."


class SalesUomStockChainTestCase(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.init(site=SITE_NAME, sites_path=SITES_PATH)
		frappe.connect()

	@classmethod
	def tearDownClass(cls):
		frappe.destroy()
		super().tearDownClass()

	def _unique_suffix(self):
		return str(time.time_ns())

	def _create_test_item(self, label: str, *, opening_boxes: float = 10, standard_rate: float = 100):
		suffix = self._unique_suffix()[-8:]
		response = create_product_and_stock(
			item_name=f"链路-{label}-{suffix}",
			warehouse=WAREHOUSE,
			opening_qty=opening_boxes,
			opening_uom="Box",
			stock_uom="Nos",
			uom_conversions=[
				{"uom": "Nos", "conversion_factor": 1},
				{"uom": "Box", "conversion_factor": 12},
			],
			wholesale_default_uom="Box",
			retail_default_uom="Nos",
			standard_rate=standard_rate,
			request_id=f"sales-uom-stock-item-{label}-{self._unique_suffix()}",
		)
		frappe.db.commit()
		return response["data"]["item_code"]

	def _get_bin_qty(self, item_code: str):
		return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": WAREHOUSE}, "actual_qty") or 0)

	def _get_order_row(self, order_name: str):
		return frappe.get_doc("Sales Order", order_name).items[0]

	def _get_sle_rows(self, voucher_no: str, item_code: str):
		rows = frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": voucher_no, "warehouse": WAREHOUSE, "item_code": item_code},
			fields=["actual_qty", "qty_after_transaction", "stock_uom", "voucher_type"],
			order_by="creation asc",
		)
		return list(rows)

	def _create_order(self, *, item_code: str, qty: float, uom: str, price: float, sales_mode: str | None = None):
		result = create_order_v2(
			customer=CUSTOMER,
			items=[
				{
					"item_code": item_code,
					"qty": qty,
					"uom": uom,
					"warehouse": WAREHOUSE,
					"price": price,
					**({"sales_mode": sales_mode} if sales_mode else {}),
				}
			],
			company=COMPANY,
			immediate=0,
			request_id=f"sales-uom-stock-order-{self._unique_suffix()}",
			remarks=f"sales uom stock chain {item_code}",
		)
		frappe.db.commit()
		return result["order"]

	def _update_order_items(
		self, *, order_name: str, item_code: str, qty: float, uom: str, price: float, sales_mode: str | None = None
	):
		result = update_order_items_v2(
			order_name=order_name,
			items=[
				{
					"item_code": item_code,
					"qty": qty,
					"uom": uom,
					"warehouse": WAREHOUSE,
					"price": price,
					**({"sales_mode": sales_mode} if sales_mode else {}),
				}
			],
			request_id=f"sales-uom-stock-update-{self._unique_suffix()}",
		)
		frappe.db.commit()
		return result

	def _submit_delivery(self, order_name: str):
		result = submit_delivery(order_name, kwargs={"request_id": f"sales-uom-stock-delivery-{self._unique_suffix()}"})
		frappe.db.commit()
		return result["delivery_note"]

	def test_wholesale_uom_delivery_reduces_stock_by_converted_stock_qty(self):
		item_code = self._create_test_item("WHOLESALE")
		before_qty = self._get_bin_qty(item_code)

		order_name = self._create_order(
			item_code=item_code,
			qty=2,
			uom="Box",
			price=1200,
			sales_mode="wholesale",
		)
		order_row = self._get_order_row(order_name)
		delivery_note = self._submit_delivery(order_name)
		after_qty = self._get_bin_qty(item_code)
		sle_rows = self._get_sle_rows(delivery_note, item_code)

		self.assertEqual(order_row.uom, "Box")
		self.assertEqual(flt(order_row.conversion_factor), 12.0)
		self.assertEqual(flt(order_row.stock_qty), 24.0)
		self.assertEqual(order_row.stock_uom, "Nos")
		self.assertEqual(before_qty - after_qty, 24.0)
		self.assertEqual(len(sle_rows), 1)
		self.assertEqual(flt(sle_rows[0].actual_qty), -24.0)
		self.assertEqual(flt(sle_rows[0].qty_after_transaction), after_qty)
		self.assertEqual(sle_rows[0].stock_uom, "Nos")

	def test_retail_uom_delivery_reduces_stock_by_retail_qty(self):
		item_code = self._create_test_item("RETAIL")
		before_qty = self._get_bin_qty(item_code)

		order_name = self._create_order(
			item_code=item_code,
			qty=5,
			uom="Nos",
			price=150,
			sales_mode="retail",
		)
		order_row = self._get_order_row(order_name)
		delivery_note = self._submit_delivery(order_name)
		after_qty = self._get_bin_qty(item_code)
		sle_rows = self._get_sle_rows(delivery_note, item_code)

		self.assertEqual(order_row.uom, "Nos")
		self.assertEqual(flt(order_row.conversion_factor), 1.0)
		self.assertEqual(flt(order_row.stock_qty), 5.0)
		self.assertEqual(order_row.stock_uom, "Nos")
		self.assertEqual(before_qty - after_qty, 5.0)
		self.assertEqual(len(sle_rows), 1)
		self.assertEqual(flt(sle_rows[0].actual_qty), -5.0)
		self.assertEqual(flt(sle_rows[0].qty_after_transaction), after_qty)

	def test_updating_order_uom_recomputes_stock_qty_before_delivery(self):
		item_code = self._create_test_item("UPDATE")
		before_qty = self._get_bin_qty(item_code)

		order_name = self._create_order(
			item_code=item_code,
			qty=1,
			uom="Box",
			price=1100,
			sales_mode="wholesale",
		)
		before_update_row = self._get_order_row(order_name)

		update_result = self._update_order_items(
			order_name=order_name,
			item_code=item_code,
			qty=7,
			uom="Nos",
			price=90,
			sales_mode="retail",
		)
		amended_order_name = update_result["order"]
		after_update_row = self._get_order_row(amended_order_name)
		delivery_note = self._submit_delivery(amended_order_name)
		after_qty = self._get_bin_qty(item_code)
		sle_rows = self._get_sle_rows(delivery_note, item_code)

		self.assertEqual(update_result["source_order"], order_name)
		self.assertEqual(flt(before_update_row.stock_qty), 12.0)
		self.assertEqual(before_update_row.uom, "Box")
		self.assertEqual(after_update_row.uom, "Nos")
		self.assertEqual(flt(after_update_row.conversion_factor), 1.0)
		self.assertEqual(flt(after_update_row.stock_qty), 7.0)
		self.assertEqual(before_qty - after_qty, 7.0)
		self.assertEqual(len(sle_rows), 1)
		self.assertEqual(flt(sle_rows[0].actual_qty), -7.0)

	def test_wholesale_delivery_rejects_when_converted_stock_qty_exceeds_available_stock(self):
		item_code = self._create_test_item("INSUFFICIENT", opening_boxes=10)
		before_qty = self._get_bin_qty(item_code)

		order_name = self._create_order(
			item_code=item_code,
			qty=11,
			uom="Box",
			price=1000,
			sales_mode="wholesale",
		)
		order_row = self._get_order_row(order_name)

		with self.assertRaises(frappe.ValidationError) as exc_info:
			self._submit_delivery(order_name)

		frappe.db.rollback()
		after_qty = self._get_bin_qty(item_code)

		self.assertEqual(flt(order_row.stock_qty), 132.0)
		self.assertEqual(before_qty, 120.0)
		self.assertEqual(after_qty, before_qty)
		self.assertIn("库存不足", str(exc_info.exception))


if __name__ == "__main__":
	unittest.main()
