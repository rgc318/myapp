import os
import time
import unittest

import frappe
from frappe.utils import cint, flt

from myapp.services.order_service import (
	cancel_order_v2,
	cancel_sales_invoice,
	create_order_v2,
	create_sales_invoice,
	get_sales_invoice_detail,
	get_sales_order_detail,
)
from myapp.services.settlement_service import cancel_payment_entry, update_payment_status
from myapp.services.wholesale_service import create_product_and_stock


SITE_NAME = os.environ.get("MYAPP_TEST_SITE", "localhost").strip() or "localhost"
SITES_PATH = os.environ.get("MYAPP_TEST_SITES_PATH", "/home/frappe/frappe-bench/sites").strip()
WAREHOUSE = os.environ.get("MYAPP_TEST_WAREHOUSE", "Stores - RD").strip() or "Stores - RD"
COMPANY = os.environ.get("MYAPP_TEST_COMPANY", "rgc (Demo)").strip() or "rgc (Demo)"
CUSTOMER = os.environ.get("MYAPP_TEST_CUSTOMER", "Palmer Productions Ltd.").strip() or "Palmer Productions Ltd."


class SalesBillingPaymentLifecycleTestCase(unittest.TestCase):
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

	def _create_test_item(self, label: str, *, opening_qty: float = 10, standard_rate: float = 100):
		suffix = self._unique_suffix()[-8:]
		result = create_product_and_stock(
			item_name=f"销售结算链路-{label}-{suffix}",
			warehouse=WAREHOUSE,
			opening_qty=opening_qty,
			stock_uom="Nos",
			standard_rate=standard_rate,
			request_id=f"sales-billing-payment-item-{label}-{self._unique_suffix()}",
		)
		frappe.db.commit()
		return result["data"]["item_code"]

	def _create_order(self, *, item_code: str, qty: float, price: float):
		result = create_order_v2(
			customer=CUSTOMER,
			items=[
				{
					"item_code": item_code,
					"qty": qty,
					"uom": "Nos",
					"warehouse": WAREHOUSE,
					"price": price,
				}
			],
			company=COMPANY,
			immediate=0,
			request_id=f"sales-billing-payment-order-{self._unique_suffix()}",
			remarks=f"sales billing payment lifecycle {item_code}",
		)
		frappe.db.commit()
		return result["order"]

	def _create_invoice(self, order_name: str):
		result = create_sales_invoice(
			order_name,
			kwargs={"request_id": f"sales-billing-payment-invoice-{self._unique_suffix()}"},
		)
		frappe.db.commit()
		return result["sales_invoice"]

	def _record_payment(self, invoice_name: str, paid_amount: float):
		result = update_payment_status(
			"Sales Invoice",
			invoice_name,
			paid_amount=paid_amount,
			mode_of_payment="Cash",
			request_id=f"sales-billing-payment-payment-{self._unique_suffix()}",
		)
		frappe.db.commit()
		return result["payment_entry"]

	def _cancel_payment(self, payment_entry: str):
		result = cancel_payment_entry(
			payment_entry,
			request_id=f"sales-billing-payment-cancel-payment-{self._unique_suffix()}",
		)
		frappe.db.commit()
		return result

	def _cancel_invoice(self, invoice_name: str):
		result = cancel_sales_invoice(
			invoice_name,
			request_id=f"sales-billing-payment-cancel-invoice-{self._unique_suffix()}",
		)
		frappe.db.commit()
		return result

	def _cancel_order(self, order_name: str):
		result = cancel_order_v2(
			order_name,
			request_id=f"sales-billing-payment-cancel-order-{self._unique_suffix()}",
		)
		frappe.db.commit()
		return result

	def _invoice_amounts(self, invoice_name: str):
		invoice = frappe.get_doc("Sales Invoice", invoice_name)
		return {
			"docstatus": cint(invoice.docstatus),
			"grand_total": flt(invoice.grand_total),
			"outstanding_amount": flt(invoice.outstanding_amount),
		}

	def test_invoice_payment_and_cancellations_keep_sales_status_in_sync(self):
		item_code = self._create_test_item("ROLLBACK", standard_rate=321)
		order_name = self._create_order(item_code=item_code, qty=2, price=321)
		invoice_name = self._create_invoice(order_name)
		invoice_before_payment = self._invoice_amounts(invoice_name)
		order_after_invoice = get_sales_order_detail(order_name)["data"]
		invoice_detail_before_payment = get_sales_invoice_detail(invoice_name)["data"]

		self.assertEqual(invoice_before_payment["grand_total"], 642.0)
		self.assertEqual(invoice_before_payment["outstanding_amount"], 642.0)
		self.assertEqual(order_after_invoice["amounts"]["receivable_amount"], 642.0)
		self.assertEqual(order_after_invoice["amounts"]["outstanding_amount"], 642.0)
		self.assertEqual(order_after_invoice["payment"]["status"], "unpaid")
		self.assertTrue(order_after_invoice["actions"]["can_record_payment"])
		self.assertTrue(invoice_detail_before_payment["actions"]["can_record_payment"])

		payment_entry = self._record_payment(invoice_name, 321)
		invoice_after_payment = self._invoice_amounts(invoice_name)
		order_after_payment = get_sales_order_detail(order_name)["data"]
		invoice_detail_after_payment = get_sales_invoice_detail(invoice_name)["data"]

		self.assertEqual(invoice_after_payment["outstanding_amount"], 321.0)
		self.assertEqual(order_after_payment["payment"]["latest_payment_entry"], payment_entry)
		self.assertEqual(order_after_payment["payment"]["status"], "partial")
		self.assertEqual(order_after_payment["payment"]["paid_amount"], 321.0)
		self.assertEqual(order_after_payment["payment"]["outstanding_amount"], 321.0)
		self.assertEqual(invoice_detail_after_payment["payment"]["status"], "partial")
		self.assertEqual(invoice_detail_after_payment["amounts"]["paid_amount"], 321.0)
		self.assertEqual(invoice_detail_after_payment["amounts"]["outstanding_amount"], 321.0)

		cancel_payment_result = self._cancel_payment(payment_entry)
		invoice_after_payment_cancel = self._invoice_amounts(invoice_name)
		order_after_payment_cancel = get_sales_order_detail(order_name)["data"]
		payment_doc = frappe.get_doc("Payment Entry", payment_entry)

		self.assertEqual(cancel_payment_result["document_status"], "cancelled")
		self.assertEqual(cint(payment_doc.docstatus), 2)
		self.assertEqual(invoice_after_payment_cancel["outstanding_amount"], 642.0)
		self.assertEqual(order_after_payment_cancel["payment"]["status"], "unpaid")
		self.assertEqual(order_after_payment_cancel["payment"]["paid_amount"], 0.0)
		self.assertEqual(order_after_payment_cancel["payment"]["outstanding_amount"], 642.0)

		cancel_invoice_result = self._cancel_invoice(invoice_name)
		invoice_after_cancel = self._invoice_amounts(invoice_name)
		order_after_invoice_cancel = get_sales_order_detail(order_name)["data"]

		self.assertEqual(cancel_invoice_result["document_status"], "cancelled")
		self.assertEqual(invoice_after_cancel["docstatus"], 2)
		self.assertEqual(order_after_invoice_cancel["amounts"]["receivable_amount"], 0)
		self.assertEqual(order_after_invoice_cancel["amounts"]["outstanding_amount"], 0)
		self.assertEqual(order_after_invoice_cancel["payment"]["status"], "unpaid")
		self.assertTrue(order_after_invoice_cancel["actions"]["can_create_sales_invoice"])
		self.assertTrue(order_after_invoice_cancel["actions"]["can_cancel_sales_order"])

		cancel_order_result = self._cancel_order(order_name)
		order_after_cancel = get_sales_order_detail(order_name)["data"]
		order_doc = frappe.get_doc("Sales Order", order_name)

		self.assertEqual(cancel_order_result["document_status"], "cancelled")
		self.assertEqual(cint(order_doc.docstatus), 2)
		self.assertEqual(order_after_cancel["document_status"], "cancelled")
		self.assertFalse(order_after_cancel["actions"]["can_create_sales_invoice"])
		self.assertFalse(order_after_cancel["actions"]["can_record_payment"])


if __name__ == "__main__":
	unittest.main()
