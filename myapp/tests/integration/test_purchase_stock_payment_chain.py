import os
import time
import unittest

import frappe
from frappe.utils import flt

from myapp.services.purchase_service import (
	create_purchase_invoice_from_receipt,
	create_purchase_order,
	get_purchase_order_detail_v2,
	record_supplier_payment,
	receive_purchase_order,
)
from myapp.services.wholesale_service import create_product_and_stock


SITE_NAME = os.environ.get("MYAPP_TEST_SITE", "localhost").strip() or "localhost"
SITES_PATH = os.environ.get("MYAPP_TEST_SITES_PATH", "/home/frappe/frappe-bench/sites").strip()
WAREHOUSE = os.environ.get("MYAPP_TEST_WAREHOUSE", "Stores - RD").strip() or "Stores - RD"
COMPANY = os.environ.get("MYAPP_TEST_COMPANY", "rgc (Demo)").strip() or "rgc (Demo)"
SUPPLIER = os.environ.get("MYAPP_TEST_SUPPLIER", "MA Inc.").strip() or "MA Inc."


class PurchaseStockPaymentChainTestCase(unittest.TestCase):
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

	def _create_test_item(self, label: str, *, opening_boxes: float = 0, standard_rate: float = 100):
		suffix = self._unique_suffix()[-8:]
		response = create_product_and_stock(
			item_name=f"采购链路-{label}-{suffix}",
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
			request_id=f"purchase-stock-item-{label}-{self._unique_suffix()}",
		)
		frappe.db.commit()
		return response["data"]["item_code"]

	def _get_bin_qty(self, item_code: str):
		return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": WAREHOUSE}, "actual_qty") or 0)

	def _get_purchase_order_row(self, order_name: str):
		return frappe.get_doc("Purchase Order", order_name).items[0]

	def _get_purchase_invoice_amounts(self, invoice_name: str):
		invoice_doc = frappe.get_doc("Purchase Invoice", invoice_name)
		return {
			"grand_total": flt(invoice_doc.grand_total),
			"outstanding_amount": flt(invoice_doc.outstanding_amount),
		}

	def _get_sle_rows(self, voucher_no: str, item_code: str):
		rows = frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": voucher_no, "warehouse": WAREHOUSE, "item_code": item_code},
			fields=["actual_qty", "qty_after_transaction", "stock_uom", "voucher_type"],
			order_by="creation asc",
		)
		return list(rows)

	def _create_purchase_order(self, *, item_code: str, qty: float, uom: str, price: float):
		result = create_purchase_order(
			supplier=SUPPLIER,
			items=[
				{
					"item_code": item_code,
					"qty": qty,
					"uom": uom,
					"warehouse": WAREHOUSE,
					"price": price,
				}
			],
			company=COMPANY,
			request_id=f"purchase-stock-order-{self._unique_suffix()}",
			remarks=f"purchase stock chain {item_code}",
		)
		frappe.db.commit()
		return result["purchase_order"]

	def _receive_purchase_order(self, order_name: str):
		result = receive_purchase_order(
			order_name,
			kwargs={"request_id": f"purchase-stock-receipt-{self._unique_suffix()}"},
		)
		frappe.db.commit()
		return result["purchase_receipt"]

	def _create_purchase_invoice_from_receipt(self, receipt_name: str):
		result = create_purchase_invoice_from_receipt(
			receipt_name,
			kwargs={"request_id": f"purchase-stock-invoice-{self._unique_suffix()}"},
		)
		frappe.db.commit()
		return result["purchase_invoice"]

	def _record_supplier_payment(self, invoice_name: str, paid_amount: float):
		result = record_supplier_payment(
			invoice_name,
			paid_amount=paid_amount,
			request_id=f"purchase-stock-payment-{self._unique_suffix()}",
		)
		frappe.db.commit()
		return result["payment_entry"]

	def test_purchase_receipt_increases_stock_by_converted_stock_qty(self):
		item_code = self._create_test_item("RECEIPT", opening_boxes=0)
		before_qty = self._get_bin_qty(item_code)

		order_name = self._create_purchase_order(
			item_code=item_code,
			qty=2,
			uom="Box",
			price=850,
		)
		order_row = self._get_purchase_order_row(order_name)
		receipt_name = self._receive_purchase_order(order_name)
		after_qty = self._get_bin_qty(item_code)
		sle_rows = self._get_sle_rows(receipt_name, item_code)

		self.assertEqual(order_row.uom, "Box")
		self.assertEqual(flt(order_row.conversion_factor), 12.0)
		self.assertEqual(flt(order_row.stock_qty), 24.0)
		self.assertEqual(order_row.stock_uom, "Nos")
		self.assertEqual(after_qty - before_qty, 24.0)
		self.assertEqual(len(sle_rows), 1)
		self.assertEqual(flt(sle_rows[0].actual_qty), 24.0)
		self.assertEqual(flt(sle_rows[0].qty_after_transaction), after_qty)
		self.assertEqual(sle_rows[0].stock_uom, "Nos")

	def test_purchase_invoice_and_payment_keep_order_settlement_in_sync(self):
		item_code = self._create_test_item("PAYMENT", opening_boxes=0, standard_rate=500)
		order_name = self._create_purchase_order(
			item_code=item_code,
			qty=3,
			uom="Box",
			price=500,
		)
		receipt_name = self._receive_purchase_order(order_name)
		invoice_name = self._create_purchase_invoice_from_receipt(receipt_name)
		invoice_amounts_before = self._get_purchase_invoice_amounts(invoice_name)

		detail_before = get_purchase_order_detail_v2(order_name)["data"]
		expected_partial_payment = round(invoice_amounts_before["grand_total"] / 2, 2)
		payment_entry = self._record_supplier_payment(invoice_name, expected_partial_payment)

		invoice_amounts_after = self._get_purchase_invoice_amounts(invoice_name)
		detail_after = get_purchase_order_detail_v2(order_name)["data"]

		self.assertEqual(detail_before["payment"]["paid_amount"], 0)
		self.assertEqual(detail_before["payment"]["outstanding_amount"], invoice_amounts_before["outstanding_amount"])
		self.assertEqual(invoice_amounts_before["grand_total"], detail_before["payment"]["receivable_amount"])

		self.assertEqual(detail_after["payment"]["latest_payment_entry"], payment_entry)
		self.assertEqual(detail_after["payment"]["status"], "partial")
		self.assertEqual(detail_after["payment"]["paid_amount"], expected_partial_payment)
		self.assertEqual(detail_after["payment"]["actual_paid_amount"], expected_partial_payment)
		self.assertEqual(detail_after["payment"]["outstanding_amount"], invoice_amounts_after["outstanding_amount"])
		self.assertEqual(invoice_amounts_after["outstanding_amount"], invoice_amounts_before["grand_total"] - expected_partial_payment)


if __name__ == "__main__":
	unittest.main()
