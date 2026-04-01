import json
import os
import pathlib
import threading
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

	@classmethod
	def _get_list(cls, doctype: str, *, filters: list | None = None, fields: list | None = None, order_by: str | None = None):
		payload = {"doctype": doctype}
		if filters is not None:
			payload["filters"] = filters
		if fields is not None:
			payload["fields"] = fields
		if order_by is not None:
			payload["order_by"] = order_by
		status_code, response = cls._post_method("frappe.client.get_list", payload)
		if status_code != 200:
			raise AssertionError(f"Failed to get list for {doctype}: {response}")
		return response["message"]

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

	def _post_method_with_retry(self, method_path: str, payload: dict, *, retry_on: str | None = None, attempts: int = 2):
		last_status = None
		last_response = None
		for attempt in range(attempts):
			status_code, response = self._post_method(method_path, payload)
			last_status = status_code
			last_response = response
			if retry_on:
				message = (((response or {}).get("message") or {}).get("message")) or ""
				if retry_on in message and attempt < attempts - 1:
					time.sleep(0.2)
					continue
			return status_code, response
		return last_status, last_response

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
		status_code, response = self._post_method_with_retry(
			"myapp.api.gateway.create_purchase_order",
			payload,
			retry_on="Record has changed since last read in table 'tabBin'",
		)
		self._assert_success(status_code, response, code="PURCHASE_ORDER_CREATED")
		return response["message"]["data"]["purchase_order"]

	def _receive_purchase_order(self, order_name: str, purchase_order_item: str, qty: float):
		payload = {
			"order_name": order_name,
			"receipt_items": [{"purchase_order_item": purchase_order_item, "qty": qty}],
			"request_id": self._unique_request_id(f"purchase-receipt-{qty}"),
		}
		status_code, response = self._post_method_with_retry(
			"myapp.api.gateway.receive_purchase_order",
			payload,
			retry_on="Record has changed since last read in table 'tabBin'",
		)
		self._assert_success(status_code, response, code="PURCHASE_RECEIPT_CREATED")
		return response["message"]["data"]["purchase_receipt"]

	def _receive_purchase_order_raw(self, payload: dict):
		status_code, response = self._post_method_with_retry(
			"myapp.api.gateway.receive_purchase_order",
			payload,
			retry_on="Record has changed since last read in table 'tabBin'",
		)
		self._print_response(self._testMethodName, response)
		return status_code, response

	def _create_purchase_invoice(self, order_name: str, purchase_order_item: str, qty: float):
		payload = {
			"source_name": order_name,
			"invoice_items": [{"purchase_order_item": purchase_order_item, "qty": qty}],
			"request_id": self._unique_request_id(f"purchase-invoice-{qty}"),
		}
		status_code, response = self._post_method_with_retry(
			"myapp.api.gateway.create_purchase_invoice",
			payload,
			retry_on="Record has changed since last read in table 'tabBin'",
		)
		self._assert_success(status_code, response, code="PURCHASE_INVOICE_CREATED")
		return response["message"]["data"]["purchase_invoice"]

	def _create_purchase_invoice_raw(self, payload: dict):
		status_code, response = self._post_method_with_retry(
			"myapp.api.gateway.create_purchase_invoice",
			payload,
			retry_on="Record has changed since last read in table 'tabBin'",
		)
		self._print_response(self._testMethodName, response)
		return status_code, response

	def _record_supplier_payment(self, invoice_name: str, paid_amount: float, suffix: str):
		payload = {
			"reference_name": invoice_name,
			"paid_amount": paid_amount,
			"request_id": self._unique_request_id(f"supplier-payment-{suffix}"),
		}
		status_code, response = self._post_method("myapp.api.gateway.record_supplier_payment", payload)
		self._assert_success(status_code, response, code="SUPPLIER_PAYMENT_RECORDED")
		return response["message"]["data"]["payment_entry"]

	def _record_supplier_payment_raw(self, payload: dict):
		status_code, response = self._post_method("myapp.api.gateway.record_supplier_payment", payload)
		self._print_response(self._testMethodName, response)
		return status_code, response

	def _run_concurrent_calls(self, callables: list):
		results = [None] * len(callables)
		errors = [None] * len(callables)
		start_barrier = threading.Barrier(len(callables))

		def _runner(index: int, callback):
			try:
				start_barrier.wait()
				results[index] = callback()
			except BaseException as exc:  # pragma: no cover - test helper
				errors[index] = exc

		threads = [threading.Thread(target=_runner, args=(index, callback)) for index, callback in enumerate(callables)]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join()

		if any(errors):
			raise AssertionError(f"Concurrent call failed: {errors}")
		return results

	def _update_purchase_payment_status(
		self,
		invoice_name: str,
		*,
		paid_amount: float,
		request_id: str | None = None,
		settlement_mode: str | None = None,
		writeoff_reason: str | None = None,
	):
		payload = {
			"reference_doctype": "Purchase Invoice",
			"reference_name": invoice_name,
			"paid_amount": paid_amount,
			"request_id": request_id or self._unique_request_id("purchase-payment-status"),
		}
		if settlement_mode is not None:
			payload["settlement_mode"] = settlement_mode
		if writeoff_reason is not None:
			payload["writeoff_reason"] = writeoff_reason
		status_code, response = self._post_method("myapp.api.gateway.update_payment_status", payload)
		self._print_response(self._testMethodName, response)
		return status_code, response

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

		status_code, response = self._post_method_with_retry(
			"myapp.api.gateway.quick_create_purchase_order_v2",
			payload,
			retry_on="Record has changed since last read in table 'tabBin'",
		)
		self._print_response(self._testMethodName, response)
		self._assert_success(status_code, response, code="PURCHASE_ORDER_QUICK_CREATED")
		return response["message"]["data"]

	def _quick_create_purchase_order_raw(self, payload: dict):
		status_code, response = self._post_method_with_retry(
			"myapp.api.gateway.quick_create_purchase_order_v2",
			payload,
			retry_on="Record has changed since last read in table 'tabBin'",
		)
		self._print_response(self._testMethodName, response)
		return status_code, response

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
		for attempt in range(2):
			status_code, response = self._post_method(
				"myapp.api.gateway.cancel_purchase_invoice_v2",
				{"invoice_name": invoice_name, "request_id": self._unique_request_id("purchase-invoice-cancel")},
			)
			if status_code == 200:
				self._assert_success(status_code, response, code="PURCHASE_INVOICE_CANCELLED")
				return
			message = (((response or {}).get("message") or {}).get("message")) or ""
			if "Record has changed since last read" in message and attempt == 0:
				time.sleep(0.2)
				continue
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

	def _process_purchase_return(self, source_doctype: str, source_name: str):
		status_code, response = self._post_method(
			"myapp.api.gateway.process_purchase_return",
			{
				"source_doctype": source_doctype,
				"source_name": source_name,
				"request_id": self._unique_request_id("purchase-return"),
			},
		)
		self._assert_success(status_code, response, code="PURCHASE_RETURN_CREATED")
		return response["message"]["data"]["return_document"], response["message"]["data"]["return_doctype"]

	def _cancel_doc_via_client(self, doctype: str, name: str):
		status_code, response = self._post_method(
			"frappe.client.cancel",
			{"doctype": doctype, "name": name},
		)
		if status_code != 200:
			self.fail(f"Failed to cancel {doctype} {name}: {response}")

	def test_quick_create_purchase_order_receipt_and_invoice_success(self):
		data = self._quick_create_purchase_order(immediate_payment=False)
		try:
			self.assertTrue(data["purchase_order"])
			self.assertTrue(data["purchase_receipt"])
			self.assertTrue(data["purchase_invoice"])
			self.assertEqual(
				data["completed_steps"],
				["purchase_order", "purchase_receipt", "purchase_invoice"],
			)
		finally:
			self._cancel_purchase_invoice(data["purchase_invoice"])
			self._cancel_purchase_receipt(data["purchase_receipt"])
			self._cancel_purchase_order(data["purchase_order"])

	def test_quick_cancel_purchase_order_after_partial_payment_restores_editable_order(self):
		data = self._quick_create_purchase_order(
			qty=3,
			immediate_payment=True,
			paid_amount=min(PURCHASE_PAID_AMOUNT, 10),
			mode_of_payment="微信支付",
		)
		order_name = data["purchase_order"]

		try:
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
		finally:
			self._cancel_purchase_order(order_name)

	def test_quick_create_purchase_order_idempotent_replay_returns_same_documents(self):
		request_id = self._unique_request_id("purchase-quick-order-replay")
		payload = {
			"supplier": PURCHASE_SUPPLIER,
			"items": [
				{
					"item_code": PURCHASE_ITEM_CODE,
					"qty": PURCHASE_QTY,
					"warehouse": PURCHASE_WAREHOUSE,
				}
			],
			"company": PURCHASE_COMPANY,
			"immediate_receive": 1,
			"immediate_invoice": 1,
			"immediate_payment": 0,
			"request_id": request_id,
		}
		status_code_a, response_a = self._post_method("myapp.api.gateway.quick_create_purchase_order_v2", payload)
		status_code_b, response_b = self._post_method("myapp.api.gateway.quick_create_purchase_order_v2", payload)
		self._assert_success(status_code_a, response_a, code="PURCHASE_ORDER_QUICK_CREATED")
		self._assert_success(status_code_b, response_b, code="PURCHASE_ORDER_QUICK_CREATED")

		data_a = response_a["message"]["data"]
		data_b = response_b["message"]["data"]
		self.assertEqual(data_a["purchase_order"], data_b["purchase_order"])
		self.assertEqual(data_a["purchase_receipt"], data_b["purchase_receipt"])
		self.assertEqual(data_a["purchase_invoice"], data_b["purchase_invoice"])
		self.assertEqual(data_a["completed_steps"], data_b["completed_steps"])

		self._cancel_purchase_invoice(data_a["purchase_invoice"])
		self._cancel_purchase_receipt(data_a["purchase_receipt"])
		self._cancel_purchase_order(data_a["purchase_order"])

	def test_receive_purchase_order_idempotent_replay_returns_same_receipt(self):
		order_name = self._create_purchase_order(qty=3)
		order_item = self._get_resource("Purchase Order", order_name)["items"][0]["name"]
		request_id = self._unique_request_id("purchase-receipt-replay")
		payload = {
			"order_name": order_name,
			"receipt_items": [{"purchase_order_item": order_item, "qty": 3}],
			"request_id": request_id,
		}

		try:
			status_code_a, response_a = self._receive_purchase_order_raw(payload)
			status_code_b, response_b = self._receive_purchase_order_raw(payload)
			self._assert_success(status_code_a, response_a, code="PURCHASE_RECEIPT_CREATED")
			self._assert_success(status_code_b, response_b, code="PURCHASE_RECEIPT_CREATED")

			data_a = response_a["message"]["data"]
			data_b = response_b["message"]["data"]
			self.assertEqual(data_a["purchase_receipt"], data_b["purchase_receipt"])
		finally:
			detail_status, detail_payload = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
			receipt_names = detail_payload["message"]["data"]["references"]["purchase_receipts"]
			for receipt_name in reversed(receipt_names):
				self._cancel_purchase_receipt(receipt_name)
			self._cancel_purchase_order(order_name)

	def test_create_purchase_invoice_idempotent_replay_returns_same_invoice(self):
		order_name = self._create_purchase_order(qty=3)
		order_item = self._get_resource("Purchase Order", order_name)["items"][0]["name"]
		request_id = self._unique_request_id("purchase-invoice-replay")
		payload = {
			"source_name": order_name,
			"invoice_items": [{"purchase_order_item": order_item, "qty": 3}],
			"request_id": request_id,
		}

		try:
			status_code_a, response_a = self._create_purchase_invoice_raw(payload)
			status_code_b, response_b = self._create_purchase_invoice_raw(payload)
			self._assert_success(status_code_a, response_a, code="PURCHASE_INVOICE_CREATED")
			self._assert_success(status_code_b, response_b, code="PURCHASE_INVOICE_CREATED")

			data_a = response_a["message"]["data"]
			data_b = response_b["message"]["data"]
			self.assertEqual(data_a["purchase_invoice"], data_b["purchase_invoice"])
		finally:
			detail_status, detail_payload = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
			invoice_names = detail_payload["message"]["data"]["references"]["purchase_invoices"]
			for invoice_name in reversed(invoice_names):
				self._cancel_purchase_invoice(invoice_name)
			self._cancel_purchase_order(order_name)

	def test_record_supplier_payment_idempotent_replay_returns_same_payment(self):
		data = self._quick_create_purchase_order(immediate_payment=False)
		order_name = data["purchase_order"]
		invoice_name = data["purchase_invoice"]
		request_id = self._unique_request_id("supplier-payment-replay")
		payload = {
			"reference_name": invoice_name,
			"paid_amount": min(PURCHASE_PAID_AMOUNT, 10),
			"request_id": request_id,
		}

		try:
			status_code_a, response_a = self._record_supplier_payment_raw(payload)
			status_code_b, response_b = self._record_supplier_payment_raw(payload)
			self._assert_success(status_code_a, response_a, code="SUPPLIER_PAYMENT_RECORDED")
			self._assert_success(status_code_b, response_b, code="SUPPLIER_PAYMENT_RECORDED")

			data_a = response_a["message"]["data"]
			data_b = response_b["message"]["data"]
			self.assertEqual(data_a["payment_entry"], data_b["payment_entry"])
		finally:
			detail_status, detail_payload = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
			payment_entry = detail_payload["message"]["data"]["payment"]["latest_payment_entry"]
			if payment_entry:
				self._cancel_supplier_payment(payment_entry)
			self._cancel_purchase_invoice(invoice_name)
			self._cancel_purchase_receipt(data["purchase_receipt"])
			self._cancel_purchase_order(order_name)

	def test_record_supplier_payment_concurrent_same_request_id_returns_single_payment(self):
		data = self._quick_create_purchase_order(immediate_payment=False)
		order_name = data["purchase_order"]
		invoice_name = data["purchase_invoice"]
		request_id = self._unique_request_id("supplier-payment-concurrent")
		payload = {
			"reference_name": invoice_name,
			"paid_amount": min(PURCHASE_PAID_AMOUNT, 10),
			"request_id": request_id,
		}

		try:
			results = self._run_concurrent_calls(
				[
					lambda: self._record_supplier_payment_raw(dict(payload)),
					lambda: self._record_supplier_payment_raw(dict(payload)),
				]
			)
			for status_code, response in results:
				self._assert_success(status_code, response, code="SUPPLIER_PAYMENT_RECORDED")

			payment_entries = [response["message"]["data"]["payment_entry"] for _, response in results]
			self.assertEqual(len(set(payment_entries)), 1)

			detail_status, detail_payload = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
			detail_data = detail_payload["message"]["data"]
			self.assertEqual(detail_data["payment"]["latest_payment_entry"], payment_entries[0])
			self.assertEqual(detail_data["payment"]["status"], "partial")
			self.assertEqual(detail_data["payment"]["paid_amount"], min(PURCHASE_PAID_AMOUNT, 10))
		finally:
			detail_status, detail_payload = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
			payment_entry = detail_payload["message"]["data"]["payment"]["latest_payment_entry"]
			if payment_entry:
				self._cancel_supplier_payment(payment_entry)
			self._cancel_purchase_invoice(invoice_name)
			self._cancel_purchase_receipt(data["purchase_receipt"])
			self._cancel_purchase_order(order_name)

	def test_quick_cancel_purchase_order_idempotent_replay_returns_same_result(self):
		data = self._quick_create_purchase_order(
			immediate_payment=True,
			paid_amount=min(PURCHASE_PAID_AMOUNT, 10),
			mode_of_payment="微信支付",
		)
		order_name = data["purchase_order"]
		request_id = self._unique_request_id("purchase-quick-cancel-replay")
		payload = {
			"order_name": order_name,
			"rollback_payment": 1,
			"request_id": request_id,
		}

		try:
			status_code_a, response_a = self._post_method("myapp.api.gateway.quick_cancel_purchase_order_v2", payload)
			status_code_b, response_b = self._post_method("myapp.api.gateway.quick_cancel_purchase_order_v2", payload)
			self._assert_success(status_code_a, response_a, code="PURCHASE_ORDER_QUICK_CANCELLED")
			self._assert_success(status_code_b, response_b, code="PURCHASE_ORDER_QUICK_CANCELLED")

			data_a = response_a["message"]["data"]
			data_b = response_b["message"]["data"]
			self.assertEqual(data_a["cancelled_payment_entries"], data_b["cancelled_payment_entries"])
			self.assertEqual(data_a["cancelled_purchase_invoice"], data_b["cancelled_purchase_invoice"])
			self.assertEqual(data_a["cancelled_purchase_receipt"], data_b["cancelled_purchase_receipt"])
			self.assertEqual(data_a["completed_steps"], data_b["completed_steps"])
			self.assertEqual(data_b["detail"]["references"]["purchase_receipts"], [])
			self.assertEqual(data_b["detail"]["references"]["purchase_invoices"], [])
			self.assertTrue(data_b["detail"]["actions"]["can_receive_purchase_order"])
		finally:
			self._cancel_purchase_order(order_name)

	def test_quick_cancel_purchase_order_allows_stepwise_flow_after_rollback(self):
		data = self._quick_create_purchase_order(immediate_payment=False)
		order_name = data["purchase_order"]

		try:
			cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name)
			self._assert_success(cancel_status, cancel_payload, code="PURCHASE_ORDER_QUICK_CANCELLED")

			order_doc = self._get_resource("Purchase Order", order_name)
			order_item = order_doc["items"][0]["name"]
			receipt_name = self._receive_purchase_order(order_name, order_item, PURCHASE_QTY)
			invoice_name = self._create_purchase_invoice(order_name, order_item, PURCHASE_QTY)
			payment_entry = self._record_supplier_payment(invoice_name, PURCHASE_PAID_AMOUNT, "recreated")

			detail_status, detail_payload = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
			detail_data = detail_payload["message"]["data"]
			self.assertEqual(detail_data["references"]["purchase_receipts"], [receipt_name])
			self.assertEqual(detail_data["references"]["purchase_invoices"], [invoice_name])
			self.assertEqual(detail_data["payment"]["latest_payment_entry"], payment_entry)
			self.assertGreater(detail_data["payment"]["paid_amount"], 0)

			self._cancel_supplier_payment(payment_entry)
			self._cancel_purchase_invoice(invoice_name)
			self._cancel_purchase_receipt(receipt_name)
		finally:
			self._cancel_purchase_order(order_name)

	def test_quick_cancel_purchase_order_without_downstream_is_noop(self):
		order_name = self._create_purchase_order(qty=2)

		try:
			cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name)
			self._assert_success(cancel_status, cancel_payload, code="PURCHASE_ORDER_QUICK_CANCELLED")
			cancel_data = cancel_payload["message"]["data"]
			self.assertEqual(cancel_data["completed_steps"], [])
			self.assertEqual(cancel_data["cancelled_payment_entries"], [])
			self.assertIsNone(cancel_data["cancelled_purchase_invoice"])
			self.assertIsNone(cancel_data["cancelled_purchase_receipt"])
			self.assertEqual(cancel_data["detail"]["document_status"], "submitted")
			self.assertTrue(cancel_data["detail"]["actions"]["can_receive_purchase_order"])
			self.assertTrue(cancel_data["detail"]["actions"]["can_create_purchase_invoice"])
		finally:
			self._cancel_purchase_order(order_name)

	def test_quick_cancel_purchase_order_after_manual_payment_cancel_finishes_remaining_steps(self):
		data = self._quick_create_purchase_order(
			immediate_payment=True,
			paid_amount=min(PURCHASE_PAID_AMOUNT, 10),
			mode_of_payment="微信支付",
		)
		order_name = data["purchase_order"]
		self._cancel_supplier_payment(data["payment_entry"])

		try:
			cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name)
			self._assert_success(cancel_status, cancel_payload, code="PURCHASE_ORDER_QUICK_CANCELLED")
			cancel_data = cancel_payload["message"]["data"]
			self.assertEqual(cancel_data["cancelled_payment_entries"], [])
			self.assertEqual(cancel_data["completed_steps"], ["purchase_invoice", "purchase_receipt"])
			self.assertEqual(cancel_data["cancelled_purchase_invoice"], data["purchase_invoice"])
			self.assertEqual(cancel_data["cancelled_purchase_receipt"], data["purchase_receipt"])
			self.assertTrue(cancel_data["detail"]["actions"]["can_receive_purchase_order"])
		finally:
			self._cancel_purchase_order(order_name)

	def test_quick_cancel_purchase_order_after_manual_invoice_cancel_finishes_remaining_receipt(self):
		data = self._quick_create_purchase_order(immediate_payment=False)
		order_name = data["purchase_order"]
		self._cancel_purchase_invoice(data["purchase_invoice"])

		try:
			cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name)
			self._assert_success(cancel_status, cancel_payload, code="PURCHASE_ORDER_QUICK_CANCELLED")
			cancel_data = cancel_payload["message"]["data"]
			self.assertIsNone(cancel_data["cancelled_purchase_invoice"])
			self.assertEqual(cancel_data["cancelled_purchase_receipt"], data["purchase_receipt"])
			self.assertEqual(cancel_data["completed_steps"], ["purchase_receipt"])
			self.assertEqual(cancel_data["detail"]["references"]["purchase_invoices"], [])
			self.assertEqual(cancel_data["detail"]["references"]["purchase_receipts"], [])
		finally:
			self._cancel_purchase_order(order_name)

	def test_quick_cancel_purchase_order_after_manual_receipt_cancel_is_noop(self):
		order_name = self._create_purchase_order(qty=3)
		order_item = self._get_resource("Purchase Order", order_name)["items"][0]["name"]
		receipt_name = self._receive_purchase_order(order_name, order_item, 3)
		self._cancel_purchase_receipt(receipt_name)

		try:
			cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name)
			self._assert_success(cancel_status, cancel_payload, code="PURCHASE_ORDER_QUICK_CANCELLED")
			cancel_data = cancel_payload["message"]["data"]
			self.assertEqual(cancel_data["completed_steps"], [])
			self.assertIsNone(cancel_data["cancelled_purchase_invoice"])
			self.assertIsNone(cancel_data["cancelled_purchase_receipt"])
			self.assertEqual(cancel_data["detail"]["references"]["purchase_receipts"], [])
			self.assertTrue(cancel_data["detail"]["actions"]["can_receive_purchase_order"])
		finally:
			self._cancel_purchase_order(order_name)

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

	def test_quick_cancel_purchase_order_rejects_multiple_receipts_before_invoice_cleanup(self):
		order_name = self._create_purchase_order(qty=4)
		order_item = self._get_resource("Purchase Order", order_name)["items"][0]["name"]
		receipt_name_a = self._receive_purchase_order(order_name, order_item, 2)
		receipt_name_b = self._receive_purchase_order(order_name, order_item, 2)
		invoice_name = self._create_purchase_invoice(order_name, order_item, 4)

		try:
			cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name)
			self._assert_validation_error(cancel_status, cancel_payload, contains="多张采购收货单")
		finally:
			self._cancel_purchase_invoice(invoice_name)
			self._cancel_purchase_receipt(receipt_name_b)
			self._cancel_purchase_receipt(receipt_name_a)
			self._cancel_purchase_order(order_name)

	def test_quick_cancel_purchase_order_fails_without_mutation_when_receipt_return_exists(self):
		order_name = self._create_purchase_order(qty=3)
		order_item = self._get_resource("Purchase Order", order_name)["items"][0]["name"]
		receipt_name = self._receive_purchase_order(order_name, order_item, 3)
		return_name, return_doctype = self._process_purchase_return("Purchase Receipt", receipt_name)

		try:
			cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name)
			self.assertNotEqual(cancel_status, 200, cancel_payload)

			detail_status, detail_payload = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
			detail_data = detail_payload["message"]["data"]
			self.assertIn(receipt_name, detail_data["references"]["purchase_receipts"])
			self.assertEqual(len(detail_data["references"]["purchase_receipts"]), 2)
			self.assertEqual(detail_data["receiving"]["status"], "pending")
		finally:
			self._cancel_doc_via_client(return_doctype, return_name)
			self._cancel_purchase_receipt(receipt_name)
			self._cancel_purchase_order(order_name)

	def test_cancel_purchase_receipt_requires_clearing_return_first(self):
		order_name = self._create_purchase_order(qty=3)
		order_item = self._get_resource("Purchase Order", order_name)["items"][0]["name"]
		receipt_name = self._receive_purchase_order(order_name, order_item, 3)
		return_name, return_doctype = self._process_purchase_return("Purchase Receipt", receipt_name)

		try:
			cancel_status, cancel_payload = self._post_method(
				"myapp.api.gateway.cancel_purchase_receipt_v2",
				{"receipt_name": receipt_name, "request_id": self._unique_request_id("purchase-receipt-cancel-blocked")},
			)
			self.assertNotEqual(cancel_status, 200, cancel_payload)

			detail_status, detail_payload = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
			detail_data = detail_payload["message"]["data"]
			self.assertEqual(len(detail_data["references"]["purchase_receipts"]), 1)

			self._cancel_doc_via_client(return_doctype, return_name)
		finally:
			return_doc = self._get_resource(return_doctype, return_name)
			if return_doc.get("docstatus") == 1:
				self._cancel_doc_via_client(return_doctype, return_name)
			receipt_doc = self._get_resource("Purchase Receipt", receipt_name)
			if receipt_doc.get("docstatus") == 1:
				self._cancel_purchase_receipt(receipt_name)
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

	def test_quick_cancel_purchase_order_rejects_multiple_invoices_even_with_payment(self):
		order_name = self._create_purchase_order(qty=4)
		order_item = self._get_resource("Purchase Order", order_name)["items"][0]["name"]
		invoice_name_a = self._create_purchase_invoice(order_name, order_item, 2)
		invoice_name_b = self._create_purchase_invoice(order_name, order_item, 2)
		payment_entry = self._record_supplier_payment(invoice_name_a, 5, "invoice-mix")

		try:
			cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name)
			self._assert_validation_error(cancel_status, cancel_payload, contains="多张采购发票")
		finally:
			self._cancel_supplier_payment(payment_entry)
			self._cancel_purchase_invoice(invoice_name_b)
			self._cancel_purchase_invoice(invoice_name_a)
			self._cancel_purchase_order(order_name)

	def test_quick_cancel_purchase_order_succeeds_after_disabling_payment_rollback_then_retrying(self):
		data = self._quick_create_purchase_order(
			immediate_payment=True,
			paid_amount=min(PURCHASE_PAID_AMOUNT, 10),
			mode_of_payment="微信支付",
		)
		order_name = data["purchase_order"]

		try:
			reject_status, reject_payload = self._quick_cancel_purchase_order(order_name, rollback_payment=False)
			self._assert_validation_error(reject_status, reject_payload, contains="先回退付款")

			cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name, rollback_payment=True)
			self._assert_success(cancel_status, cancel_payload, code="PURCHASE_ORDER_QUICK_CANCELLED")
			cancel_data = cancel_payload["message"]["data"]
			self.assertEqual(
				cancel_data["completed_steps"],
				["payment_entry", "purchase_invoice", "purchase_receipt"],
			)
			self.assertTrue(cancel_data["detail"]["actions"]["can_receive_purchase_order"])
		finally:
			self._cancel_purchase_order(order_name)

	def test_quick_cancel_purchase_order_succeeds_after_manual_cleanup_of_extra_invoice(self):
		order_name = self._create_purchase_order(qty=4)
		order_item = self._get_resource("Purchase Order", order_name)["items"][0]["name"]
		invoice_name_a = self._create_purchase_invoice(order_name, order_item, 2)
		invoice_name_b = self._create_purchase_invoice(order_name, order_item, 2)

		try:
			reject_status, reject_payload = self._quick_cancel_purchase_order(order_name)
			self._assert_validation_error(reject_status, reject_payload, contains="多张采购发票")

			self._cancel_purchase_invoice(invoice_name_b)

			cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name)
			self._assert_success(cancel_status, cancel_payload, code="PURCHASE_ORDER_QUICK_CANCELLED")
			cancel_data = cancel_payload["message"]["data"]
			self.assertEqual(cancel_data["completed_steps"], ["purchase_invoice"])
			self.assertEqual(cancel_data["cancelled_purchase_invoice"], invoice_name_a)
			self.assertEqual(cancel_data["detail"]["references"]["purchase_invoices"], [])
		finally:
			self._cancel_purchase_order(order_name)

	def test_quick_create_purchase_order_recovers_after_payment_step_failure(self):
		request_id = self._unique_request_id("purchase-quick-order-payment-recovery")
		transaction_date = time.strftime("%Y-%m-%d")
		before_rows = self._get_list(
			"Purchase Order",
			filters=[
				["supplier", "=", PURCHASE_SUPPLIER],
				["company", "=", PURCHASE_COMPANY],
				["transaction_date", "=", transaction_date],
			],
			fields=["name"],
			order_by="creation desc",
		)
		before_names = {row["name"] for row in before_rows}
		base_payload = {
			"supplier": PURCHASE_SUPPLIER,
			"items": [
				{
					"item_code": PURCHASE_ITEM_CODE,
					"qty": PURCHASE_QTY,
					"warehouse": PURCHASE_WAREHOUSE,
				}
			],
			"company": PURCHASE_COMPANY,
			"immediate_receive": 1,
			"immediate_invoice": 1,
			"immediate_payment": 1,
			"paid_amount": min(PURCHASE_PAID_AMOUNT, 10),
			"request_id": request_id,
		}

		fail_status, fail_payload = self._quick_create_purchase_order_raw(
			{**base_payload, "mode_of_payment": "不存在的付款方式"}
		)
		self._assert_validation_error(fail_status, fail_payload)

		order_rows = self._get_list(
			"Purchase Order",
			filters=[
				["supplier", "=", PURCHASE_SUPPLIER],
				["company", "=", PURCHASE_COMPANY],
				["transaction_date", "=", transaction_date],
			],
			fields=["name"],
			order_by="creation desc",
		)
		new_order_names = [row["name"] for row in order_rows if row["name"] not in before_names]
		self.assertEqual(len(new_order_names), 1, order_rows)
		order_name = new_order_names[0]

		try:
			detail_status, detail_payload = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
			detail_before = detail_payload["message"]["data"]
			self.assertEqual(len(detail_before["references"]["purchase_receipts"]), 1)
			self.assertEqual(len(detail_before["references"]["purchase_invoices"]), 1)
			self.assertEqual(detail_before["payment"]["latest_payment_entry"], None)
			self.assertEqual(detail_before["payment"]["status"], "unpaid")

			retry_status, retry_payload = self._quick_create_purchase_order_raw(
				{**base_payload, "mode_of_payment": "微信支付"}
			)
			self._assert_success(retry_status, retry_payload, code="PURCHASE_ORDER_QUICK_CREATED")
			retry_data = retry_payload["message"]["data"]
			self.assertEqual(retry_data["purchase_order"], order_name)
			self.assertEqual(
				retry_data["completed_steps"],
				["purchase_order", "purchase_receipt", "purchase_invoice", "payment_entry"],
			)
			self.assertTrue(retry_data["payment_entry"])

			detail_status_after, detail_payload_after = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status_after, detail_payload_after, code="PURCHASE_ORDER_DETAIL_FETCHED")
			detail_after = detail_payload_after["message"]["data"]
			self.assertEqual(detail_after["payment"]["latest_payment_entry"], retry_data["payment_entry"])
			self.assertGreater(detail_after["payment"]["paid_amount"], 0)
		finally:
			cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name)
			self._assert_success(cancel_status, cancel_payload, code="PURCHASE_ORDER_QUICK_CANCELLED")
			self._cancel_purchase_order(order_name)

	def test_quick_cancel_purchase_order_fails_without_mutation_when_invoice_return_exists(self):
		order_name = self._create_purchase_order(qty=3)
		order_item = self._get_resource("Purchase Order", order_name)["items"][0]["name"]
		invoice_name = self._create_purchase_invoice(order_name, order_item, 3)
		return_name, return_doctype = self._process_purchase_return("Purchase Invoice", invoice_name)

		try:
			cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name)
			self.assertNotEqual(cancel_status, 200, cancel_payload)

			detail_status, detail_payload = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
			detail_data = detail_payload["message"]["data"]
			self.assertIn(invoice_name, detail_data["references"]["purchase_invoices"])
			self.assertEqual(len(detail_data["references"]["purchase_invoices"]), 2)
			self.assertIn(detail_data["payment"]["status"], {"unpaid", "partial", "paid"})
		finally:
			self._cancel_doc_via_client(return_doctype, return_name)
			self._cancel_purchase_invoice(invoice_name)
			self._cancel_purchase_order(order_name)

	def test_cancel_purchase_invoice_requires_clearing_return_first(self):
		order_name = self._create_purchase_order(qty=3)
		order_item = self._get_resource("Purchase Order", order_name)["items"][0]["name"]
		invoice_name = self._create_purchase_invoice(order_name, order_item, 3)
		return_name, return_doctype = self._process_purchase_return("Purchase Invoice", invoice_name)

		try:
			cancel_status, cancel_payload = self._post_method(
				"myapp.api.gateway.cancel_purchase_invoice_v2",
				{"invoice_name": invoice_name, "request_id": self._unique_request_id("purchase-invoice-cancel-blocked")},
			)
			self.assertNotEqual(cancel_status, 200, cancel_payload)

			detail_status, detail_payload = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
			detail_data = detail_payload["message"]["data"]
			self.assertEqual(len(detail_data["references"]["purchase_invoices"]), 1)

			self._cancel_doc_via_client(return_doctype, return_name)
		finally:
			return_doc = self._get_resource(return_doctype, return_name)
			if return_doc.get("docstatus") == 1:
				self._cancel_doc_via_client(return_doctype, return_name)
			invoice_doc = self._get_resource("Purchase Invoice", invoice_name)
			if invoice_doc.get("docstatus") == 1:
				self._cancel_purchase_invoice(invoice_name)
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

	def test_quick_cancel_purchase_order_rejects_after_additional_partial_payment(self):
		data = self._quick_create_purchase_order(
			immediate_payment=True,
			paid_amount=min(PURCHASE_PAID_AMOUNT, 10),
			mode_of_payment="微信支付",
		)
		order_name = data["purchase_order"]
		invoice_name = data["purchase_invoice"]
		payment_entry_b = self._record_supplier_payment(invoice_name, 5, "follow-up")

		try:
			detail_status, detail_payload = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
			detail_data = detail_payload["message"]["data"]
			self.assertEqual(detail_data["payment"]["status"], "partial")
			self.assertGreater(detail_data["payment"]["paid_amount"], PURCHASE_PAID_AMOUNT)
			self.assertGreater(detail_data["payment"]["outstanding_amount"], 0)
			self.assertEqual(detail_data["payment"]["latest_payment_entry"], payment_entry_b)

			cancel_status, cancel_payload = self._quick_cancel_purchase_order(order_name)
			self._assert_validation_error(cancel_status, cancel_payload, contains="多笔有效付款")
		finally:
			self._cancel_supplier_payment(payment_entry_b)
			self._cancel_supplier_payment(data["payment_entry"])
			self._cancel_purchase_invoice(invoice_name)
			self._cancel_purchase_receipt(data["purchase_receipt"])
			self._cancel_purchase_order(order_name)

	def test_record_supplier_payment_rejects_overpayment(self):
		data = self._quick_create_purchase_order(immediate_payment=False)
		order_name = data["purchase_order"]
		invoice_name = data["purchase_invoice"]

		try:
			detail_status, detail_payload = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
			outstanding_amount = detail_payload["message"]["data"]["payment"]["outstanding_amount"]
			self.assertGreater(outstanding_amount, 0)

			overpay_status, overpay_payload = self._post_method(
				"myapp.api.gateway.record_supplier_payment",
				{
					"reference_name": invoice_name,
					"paid_amount": outstanding_amount + 5,
					"request_id": self._unique_request_id("supplier-payment-overpay"),
				},
			)
			self._assert_validation_error(overpay_status, overpay_payload, contains="已分配金额不能大于未付金额")

			detail_status_after, detail_payload_after = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status_after, detail_payload_after, code="PURCHASE_ORDER_DETAIL_FETCHED")
			payment_data = detail_payload_after["message"]["data"]["payment"]
			self.assertEqual(payment_data["status"], "unpaid")
			self.assertEqual(payment_data["paid_amount"], 0)
			self.assertEqual(payment_data["outstanding_amount"], outstanding_amount)
			self.assertIsNone(payment_data["latest_payment_entry"])
		finally:
			self._cancel_purchase_invoice(invoice_name)
			self._cancel_purchase_receipt(data["purchase_receipt"])
			self._cancel_purchase_order(order_name)

	def test_record_supplier_payment_rejects_non_positive_amount(self):
		data = self._quick_create_purchase_order(immediate_payment=False)
		order_name = data["purchase_order"]
		invoice_name = data["purchase_invoice"]

		try:
			for paid_amount in (0, -5):
				status_code, payload = self._post_method(
					"myapp.api.gateway.record_supplier_payment",
					{
						"reference_name": invoice_name,
						"paid_amount": paid_amount,
						"request_id": self._unique_request_id(f"supplier-payment-invalid-{paid_amount}"),
					},
				)
				self._assert_validation_error(status_code, payload, contains="paid_amount 必须大于 0")

			detail_status, detail_payload = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
			payment_data = detail_payload["message"]["data"]["payment"]
			self.assertEqual(payment_data["status"], "unpaid")
			self.assertEqual(payment_data["paid_amount"], 0)
			self.assertIsNone(payment_data["latest_payment_entry"])
		finally:
			self._cancel_purchase_invoice(invoice_name)
			self._cancel_purchase_receipt(data["purchase_receipt"])
			self._cancel_purchase_order(order_name)

	def test_update_purchase_payment_status_writeoff_currently_rejected_for_purchase_invoice(self):
		data = self._quick_create_purchase_order(immediate_payment=False)
		order_name = data["purchase_order"]
		invoice_name = data["purchase_invoice"]

		try:
			status_code, payload = self._update_purchase_payment_status(
				invoice_name,
				paid_amount=4500,
				settlement_mode="writeoff",
				writeoff_reason="采购测试抹零结清",
			)
			self._assert_validation_error(status_code, payload, contains="当前无需执行差额核销")

			detail_status, detail_payload = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
			payment_data = detail_payload["message"]["data"]["payment"]
			self.assertEqual(payment_data["status"], "unpaid")
			self.assertEqual(payment_data["paid_amount"], 0)
			self.assertEqual(payment_data["outstanding_amount"], 4600.0)
			self.assertEqual(payment_data["latest_writeoff_amount"], 0)
			self.assertEqual(payment_data["total_writeoff_amount"], 0)
			self.assertIsNone(payment_data["latest_payment_entry"])
		finally:
			self._cancel_purchase_invoice(invoice_name)
			self._cancel_purchase_receipt(data["purchase_receipt"])
			self._cancel_purchase_order(order_name)

	def test_update_purchase_payment_status_rejects_writeoff_over_outstanding(self):
		data = self._quick_create_purchase_order(immediate_payment=False)
		order_name = data["purchase_order"]
		invoice_name = data["purchase_invoice"]

		try:
			status_code, payload = self._update_purchase_payment_status(
				invoice_name,
				paid_amount=4601,
				settlement_mode="writeoff",
				writeoff_reason="采购测试超额抹零",
			)
			self._assert_validation_error(status_code, payload, contains="writeoff 模式下，paid_amount 不能大于当前未收金额")

			detail_status, detail_payload = self._post_method(
				"myapp.api.gateway.get_purchase_order_detail_v2",
				{"order_name": order_name},
			)
			self._assert_success(detail_status, detail_payload, code="PURCHASE_ORDER_DETAIL_FETCHED")
			payment_data = detail_payload["message"]["data"]["payment"]
			self.assertEqual(payment_data["status"], "unpaid")
			self.assertEqual(payment_data["paid_amount"], 0)
			self.assertEqual(payment_data["total_writeoff_amount"], 0)
			self.assertIsNone(payment_data["latest_payment_entry"])
		finally:
			self._cancel_purchase_invoice(invoice_name)
			self._cancel_purchase_receipt(data["purchase_receipt"])
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
