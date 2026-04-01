import json
import os
import pathlib
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar


DEFAULT_ENV_FILE = pathlib.Path(__file__).resolve().parents[3] / ".env.http-test"


def _load_env_file():
	env_file_value = os.environ.get("MYAPP_HTTP_ENV_FILE", "").strip()
	env_file = pathlib.Path(env_file_value).expanduser() if env_file_value else DEFAULT_ENV_FILE

	if not env_file.exists():
		return

	for raw_line in env_file.read_text(encoding="utf-8").splitlines():
		line = raw_line.strip()
		if not line or line.startswith("#") or "=" not in line:
			continue

		key, value = line.split("=", 1)
		key = key.strip()
		value = value.strip().strip("'\"")
		if key and key not in os.environ:
			os.environ[key] = value


_load_env_file()

BASE_URL = os.environ.get("MYAPP_HTTP_BASE_URL", "http://localhost:8080").rstrip("/")
USERNAME = os.environ.get("MYAPP_HTTP_USERNAME", "").strip()
PASSWORD = os.environ.get("MYAPP_HTTP_PASSWORD", "").strip()
PRINT_RESPONSES = os.environ.get("MYAPP_HTTP_PRINT_RESPONSES", "1").strip() not in {"0", "false", "False"}
PURCHASE_SUPPLIER = os.environ.get("MYAPP_TEST_SUPPLIER", "MA Inc.").strip()
PURCHASE_ITEM_CODE = os.environ.get("MYAPP_TEST_PURCHASE_ITEM_CODE", "SKU010").strip()
PURCHASE_WAREHOUSE = os.environ.get("MYAPP_TEST_PURCHASE_WAREHOUSE", "Stores - RD").strip()
PURCHASE_COMPANY = os.environ.get("MYAPP_TEST_PURCHASE_COMPANY", "rgc (Demo)").strip()
PURCHASE_QTY = float(os.environ.get("MYAPP_TEST_PURCHASE_QTY", "5").strip() or "5")
PURCHASE_PAID_AMOUNT = float(os.environ.get("MYAPP_TEST_PURCHASE_PAID_AMOUNT", "10").strip() or "10")


class PurchaseQuickHttpTestCase(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not USERNAME or not PASSWORD:
			raise cls.skipTest("HTTP gateway tests require MYAPP_HTTP_USERNAME/MYAPP_HTTP_PASSWORD.")

		cls._cookies = CookieJar()
		cls._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cls._cookies))
		cls._login()

	@classmethod
	def _login(cls):
		request = urllib.request.Request(
			f"{BASE_URL}/api/method/login",
			data=urllib.parse.urlencode({"usr": USERNAME, "pwd": PASSWORD}).encode(),
			headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
			method="POST",
		)
		with cls._opener.open(request, timeout=15) as response:
			payload = json.loads(response.read().decode() or "{}")
		if payload.get("message") != "Logged In":
			raise AssertionError(f"Login failed against {BASE_URL}: {payload}")

	@classmethod
	def _post_method(cls, method_path: str, payload: dict | None = None):
		request = urllib.request.Request(
			f"{BASE_URL}/api/method/{method_path}",
			data=json.dumps(payload or {}).encode(),
			headers={"Content-Type": "application/json", "Accept": "application/json"},
			method="POST",
		)
		try:
			with cls._opener.open(request, timeout=30) as response:
				return response.getcode(), json.loads(response.read().decode() or "{}")
		except urllib.error.HTTPError as exc:
			body = exc.read().decode()
			try:
				payload = json.loads(body or "{}")
			except json.JSONDecodeError:
				payload = {"raw_body": body}
			return exc.code, payload

	@classmethod
	def _get_resource(cls, doctype: str, name: str):
		request = urllib.request.Request(
			f"{BASE_URL}/api/resource/{urllib.parse.quote(doctype)}/{urllib.parse.quote(name)}",
			headers={"Accept": "application/json"},
			method="GET",
		)
		with cls._opener.open(request, timeout=15) as response:
			return json.loads(response.read().decode() or "{}")["data"]

	def _unique_request_id(self, prefix: str):
		return f"{prefix}-{self.id().rsplit('.', 1)[-1]}-{time.time_ns()}"

	def _assert_success(self, status_code: int, payload: dict, *, code: str):
		self.assertEqual(status_code, 200, payload)
		self.assertIn("message", payload)
		self.assertTrue(payload["message"]["ok"], payload)
		self.assertEqual(payload["message"]["code"], code)

	def _assert_validation_error(self, status_code: int, payload: dict, *, contains: str | None = None):
		self.assertEqual(status_code, 422, payload)
		self.assertIn("message", payload)
		self.assertFalse(payload["message"]["ok"], payload)
		self.assertEqual(payload["message"]["code"], "VALIDATION_ERROR")
		if contains:
			self.assertIn(contains, payload["message"]["message"])

	def _print_response(self, label: str, payload: dict):
		if PRINT_RESPONSES:
			print(f"\n[{label}]")
			print(json.dumps(payload, ensure_ascii=False, indent=2))

	def _create_purchase_order(self, *, qty: float | None = None):
		payload = {
			"supplier": PURCHASE_SUPPLIER,
			"items": [
				{
					"item_code": PURCHASE_ITEM_CODE,
					"qty": qty if qty is not None else PURCHASE_QTY,
					"warehouse": PURCHASE_WAREHOUSE,
				}
			],
			"company": PURCHASE_COMPANY,
			"request_id": self._unique_request_id("purchase-order"),
		}
		status_code, response = self._post_method("myapp.api.gateway.create_purchase_order", payload)
		self._assert_success(status_code, response, code="PURCHASE_ORDER_CREATED")
		return response["message"]["data"]["purchase_order"]

	def _receive_purchase_order(self, order_name: str, purchase_order_item: str, qty: float):
		payload = {
			"order_name": order_name,
			"receipt_items": [{"purchase_order_item": purchase_order_item, "qty": qty}],
			"request_id": self._unique_request_id(f"purchase-receipt-{qty}"),
		}
		status_code, response = self._post_method("myapp.api.gateway.receive_purchase_order", payload)
		self._assert_success(status_code, response, code="PURCHASE_RECEIPT_CREATED")
		return response["message"]["data"]["purchase_receipt"]

	def _create_purchase_invoice(self, order_name: str, purchase_order_item: str, qty: float):
		payload = {
			"source_name": order_name,
			"invoice_items": [{"purchase_order_item": purchase_order_item, "qty": qty}],
			"request_id": self._unique_request_id(f"purchase-invoice-{qty}"),
		}
		status_code, response = self._post_method("myapp.api.gateway.create_purchase_invoice", payload)
		self._assert_success(status_code, response, code="PURCHASE_INVOICE_CREATED")
		return response["message"]["data"]["purchase_invoice"]

	def _record_supplier_payment(self, invoice_name: str, paid_amount: float, suffix: str):
		payload = {
			"reference_name": invoice_name,
			"paid_amount": paid_amount,
			"request_id": self._unique_request_id(f"supplier-payment-{suffix}"),
		}
		status_code, response = self._post_method("myapp.api.gateway.record_supplier_payment", payload)
		self._assert_success(status_code, response, code="SUPPLIER_PAYMENT_RECORDED")
		return response["message"]["data"]["payment_entry"]

	def _quick_create_purchase_order(
		self,
		*,
		qty: float | None = None,
		immediate_receive: bool = True,
		immediate_invoice: bool = True,
		immediate_payment: bool = False,
		paid_amount: float | None = None,
		mode_of_payment: str | None = None,
	):
		payload = {
			"supplier": PURCHASE_SUPPLIER,
			"items": [
				{
					"item_code": PURCHASE_ITEM_CODE,
					"qty": qty if qty is not None else PURCHASE_QTY,
					"warehouse": PURCHASE_WAREHOUSE,
				}
			],
			"company": PURCHASE_COMPANY,
			"immediate_receive": 1 if immediate_receive else 0,
			"immediate_invoice": 1 if immediate_invoice else 0,
			"immediate_payment": 1 if immediate_payment else 0,
			"request_id": self._unique_request_id("purchase-quick-order"),
		}
		if paid_amount is not None:
			payload["paid_amount"] = paid_amount
		if mode_of_payment is not None:
			payload["mode_of_payment"] = mode_of_payment

		status_code, response = self._post_method("myapp.api.gateway.quick_create_purchase_order_v2", payload)
		self._print_response(self._testMethodName, response)
		self._assert_success(status_code, response, code="PURCHASE_ORDER_QUICK_CREATED")
		return response["message"]["data"]

	def _quick_cancel_purchase_order(self, order_name: str, *, rollback_payment: bool = True):
		payload = {
			"order_name": order_name,
			"rollback_payment": 1 if rollback_payment else 0,
			"request_id": self._unique_request_id("purchase-quick-cancel"),
		}
		status_code, response = self._post_method("myapp.api.gateway.quick_cancel_purchase_order_v2", payload)
		self._print_response(self._testMethodName, response)
		return status_code, response

	def _cancel_purchase_receipt(self, receipt_name: str):
		status_code, response = self._post_method(
			"myapp.api.gateway.cancel_purchase_receipt_v2",
			{"receipt_name": receipt_name, "request_id": self._unique_request_id("purchase-receipt-cancel")},
		)
		self._assert_success(status_code, response, code="PURCHASE_RECEIPT_CANCELLED")

	def _cancel_purchase_invoice(self, invoice_name: str):
		status_code, response = self._post_method(
			"myapp.api.gateway.cancel_purchase_invoice_v2",
			{"invoice_name": invoice_name, "request_id": self._unique_request_id("purchase-invoice-cancel")},
		)
		self._assert_success(status_code, response, code="PURCHASE_INVOICE_CANCELLED")

	def _cancel_supplier_payment(self, payment_entry_name: str):
		status_code, response = self._post_method(
			"myapp.api.gateway.cancel_supplier_payment",
			{"payment_entry_name": payment_entry_name, "request_id": self._unique_request_id("supplier-payment-cancel")},
		)
		self._assert_success(status_code, response, code="SUPPLIER_PAYMENT_CANCELLED")

	def _cancel_purchase_order(self, order_name: str):
		status_code, response = self._post_method(
			"myapp.api.gateway.cancel_purchase_order_v2",
			{"order_name": order_name, "request_id": self._unique_request_id("purchase-order-cancel")},
		)
		self._assert_success(status_code, response, code="PURCHASE_ORDER_CANCELLED")

	def test_quick_create_purchase_order_receipt_and_invoice_success(self):
		data = self._quick_create_purchase_order(immediate_payment=False)

		self.assertTrue(data["purchase_order"])
		self.assertTrue(data["purchase_receipt"])
		self.assertTrue(data["purchase_invoice"])
		self.assertEqual(
			data["completed_steps"],
			["purchase_order", "purchase_receipt", "purchase_invoice"],
		)

	def test_quick_cancel_purchase_order_after_partial_payment_restores_editable_order(self):
		data = self._quick_create_purchase_order(
			qty=3,
			immediate_payment=True,
			paid_amount=min(PURCHASE_PAID_AMOUNT, 10),
			mode_of_payment="微信支付",
		)
		order_name = data["purchase_order"]

		detail_status, detail_payload = self._post_method(
			"myapp.api.gateway.get_purchase_order_detail_v2",
			{"order_name": order_name},
		)
		self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
		self.assertGreater(detail_payload["message"]["data"]["payment"]["paid_amount"], 0)
		self.assertGreater(detail_payload["message"]["data"]["payment"]["outstanding_amount"], 0)

		cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name)
		self._assert_success(cancel_status, cancel_payload, code="PURCHASE_ORDER_QUICK_CANCELLED")
		cancel_data = cancel_payload["message"]["data"]
		self.assertEqual(
			cancel_data["completed_steps"],
			["payment_entry", "purchase_invoice", "purchase_receipt"],
		)
		self.assertEqual(cancel_data["detail"]["document_status"], "submitted")
		self.assertEqual(cancel_data["detail"]["references"]["purchase_receipts"], [])
		self.assertEqual(cancel_data["detail"]["references"]["purchase_invoices"], [])
		self.assertTrue(cancel_data["detail"]["actions"]["can_receive_purchase_order"])
		self.assertTrue(cancel_data["detail"]["actions"]["can_create_purchase_invoice"])

	def test_quick_cancel_purchase_order_rejects_multiple_receipts(self):
		order_name = self._create_purchase_order(qty=4)
		order_item = self._get_resource("Purchase Order", order_name)["items"][0]["name"]
		receipt_name_a = self._receive_purchase_order(order_name, order_item, 2)
		receipt_name_b = self._receive_purchase_order(order_name, order_item, 2)

		try:
			cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name)
			self._assert_validation_error(cancel_status, cancel_payload, contains="多张采购收货单")
		finally:
			self._cancel_purchase_receipt(receipt_name_b)
			self._cancel_purchase_receipt(receipt_name_a)
			self._cancel_purchase_order(order_name)

	def test_quick_cancel_purchase_order_rejects_multiple_invoices(self):
		order_name = self._create_purchase_order(qty=4)
		order_item = self._get_resource("Purchase Order", order_name)["items"][0]["name"]
		invoice_name_a = self._create_purchase_invoice(order_name, order_item, 2)
		invoice_name_b = self._create_purchase_invoice(order_name, order_item, 2)

		try:
			cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name)
			self._assert_validation_error(cancel_status, cancel_payload, contains="多张采购发票")
		finally:
			self._cancel_purchase_invoice(invoice_name_b)
			self._cancel_purchase_invoice(invoice_name_a)
			self._cancel_purchase_order(order_name)

	def test_quick_cancel_purchase_order_rejects_multiple_payments(self):
		order_name = self._create_purchase_order(qty=3)
		order_item = self._get_resource("Purchase Order", order_name)["items"][0]["name"]
		invoice_name = self._create_purchase_invoice(order_name, order_item, 3)
		payment_entry_a = self._record_supplier_payment(invoice_name, 5, "a")
		payment_entry_b = self._record_supplier_payment(invoice_name, 5, "b")

		try:
			cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name)
			self._assert_validation_error(cancel_status, cancel_payload, contains="多笔有效付款")
		finally:
			self._cancel_supplier_payment(payment_entry_b)
			self._cancel_supplier_payment(payment_entry_a)
			self._cancel_purchase_invoice(invoice_name)
			self._cancel_purchase_order(order_name)

	def test_quick_cancel_purchase_order_rejects_when_payment_rollback_disabled(self):
		data = self._quick_create_purchase_order(
			immediate_payment=True,
			mode_of_payment="微信支付",
		)
		order_name = data["purchase_order"]

		try:
			cancel_status, cancel_payload = self._quick_cancel_purchase_order(
				order_name,
				rollback_payment=False,
			)
			self._assert_validation_error(cancel_status, cancel_payload, contains="先回退付款")
		finally:
			self._cancel_supplier_payment(data["payment_entry"])
			self._cancel_purchase_invoice(data["purchase_invoice"])
			self._cancel_purchase_receipt(data["purchase_receipt"])
			self._cancel_purchase_order(order_name)
