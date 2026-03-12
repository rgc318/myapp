import json
import os
import pathlib
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from unittest import TestCase


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
TOKEN_KEY = os.environ.get("MYAPP_HTTP_API_KEY", "").strip()
TOKEN_SECRET = os.environ.get("MYAPP_HTTP_API_SECRET", "").strip()
USERNAME = os.environ.get("MYAPP_HTTP_USERNAME", "").strip()
PASSWORD = os.environ.get("MYAPP_HTTP_PASSWORD", "").strip()
PRINT_RESPONSES = os.environ.get("MYAPP_HTTP_PRINT_RESPONSES", "1").strip() not in {"0", "false", "False"}
SAVE_RESPONSES = os.environ.get("MYAPP_HTTP_SAVE_RESPONSES", "1").strip() not in {"0", "false", "False"}
RESULTS_FILE = pathlib.Path(
	os.environ.get("MYAPP_HTTP_RESULTS_FILE", str(DEFAULT_ENV_FILE.with_name("http-test-results.json")))
).expanduser()
CHAIN_TEST_ENABLED = os.environ.get("MYAPP_HTTP_ENABLE_CHAIN_TESTS", "0").strip() in {"1", "true", "True"}
SALES_CUSTOMER = os.environ.get("MYAPP_TEST_CUSTOMER", "Palmer Productions Ltd.").strip()
SALES_ITEM_CODE = os.environ.get("MYAPP_TEST_ITEM_CODE", "SKU010").strip()
SALES_WAREHOUSE = os.environ.get("MYAPP_TEST_WAREHOUSE", "Stores - RD").strip()
SALES_COMPANY = os.environ.get("MYAPP_TEST_COMPANY", "rgc (Demo)").strip()
SALES_QTY = float(os.environ.get("MYAPP_TEST_QTY", "1").strip() or "1")
SALES_PAID_AMOUNT = float(os.environ.get("MYAPP_TEST_PAID_AMOUNT", "900").strip() or "900")
PURCHASE_SUPPLIER = os.environ.get("MYAPP_TEST_SUPPLIER", "MA Inc.").strip()
PURCHASE_ITEM_CODE = os.environ.get("MYAPP_TEST_PURCHASE_ITEM_CODE", SALES_ITEM_CODE).strip()
PURCHASE_WAREHOUSE = os.environ.get("MYAPP_TEST_PURCHASE_WAREHOUSE", SALES_WAREHOUSE).strip()
PURCHASE_COMPANY = os.environ.get("MYAPP_TEST_PURCHASE_COMPANY", SALES_COMPANY).strip()
PURCHASE_QTY = float(os.environ.get("MYAPP_TEST_PURCHASE_QTY", "5").strip() or "5")
PURCHASE_PAID_AMOUNT = float(os.environ.get("MYAPP_TEST_PURCHASE_PAID_AMOUNT", "10").strip() or "10")


class GatewayHttpTestCase(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._results = {}

		if TOKEN_KEY and TOKEN_SECRET:
			cls._auth_mode = "token"
			cls._opener = urllib.request.build_opener()
			return

		if USERNAME and PASSWORD:
			cls._auth_mode = "session"
			cls._cookies = CookieJar()
			cls._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cls._cookies))
			cls._login()
			return

		raise cls.skipTest(
			"HTTP gateway tests require MYAPP_HTTP_API_KEY/MYAPP_HTTP_API_SECRET "
			"or MYAPP_HTTP_USERNAME/MYAPP_HTTP_PASSWORD."
		)

	@classmethod
	def _headers(cls):
		headers = {"Accept": "application/json"}
		if cls._auth_mode == "token":
			headers["Authorization"] = f"token {TOKEN_KEY}:{TOKEN_SECRET}"
		return headers

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
		payload = payload or {}
		request = urllib.request.Request(
			f"{BASE_URL}/api/method/{method_path}",
			data=json.dumps(payload).encode(),
			headers={**cls._headers(), "Content-Type": "application/json"},
			method="POST",
		)
		try:
			with cls._opener.open(request, timeout=15) as response:
				return response.getcode(), json.loads(response.read().decode() or "{}")
		except urllib.error.HTTPError as exc:
			body = exc.read().decode()
			try:
				payload = json.loads(body or "{}")
			except json.JSONDecodeError:
				payload = {"raw_body": body}
			return exc.code, payload

	@classmethod
	def _record_response(cls, *, test_name: str, method_path: str, request_payload: dict, status_code: int, payload: dict):
		record = {
			"method": method_path,
			"request": request_payload,
			"http_status": status_code,
			"response": payload,
		}
		cls._results[test_name] = record

		if SAVE_RESPONSES:
			merged_results = cls._load_saved_results()
			merged_results.update(cls._results)
			RESULTS_FILE.write_text(
				json.dumps(merged_results, ensure_ascii=False, indent=2),
				encoding="utf-8",
			)

		if PRINT_RESPONSES:
			print(f"\n[{test_name}] {method_path} -> HTTP {status_code}", file=sys.stderr)
			print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)

	@classmethod
	def _load_saved_results(cls):
		if not RESULTS_FILE.exists():
			return {}
		return json.loads(RESULTS_FILE.read_text(encoding="utf-8") or "{}")

	@classmethod
	def _get_saved_result(cls, test_name: str):
		return cls._load_saved_results().get(test_name)

	@classmethod
	def _get_saved_value(cls, test_name: str, path: str):
		record = cls._get_saved_result(test_name)
		if record is None:
			raise KeyError(f"No saved result found for test '{test_name}'.")

		current = record
		for part in path.split("."):
			if isinstance(current, dict) and part in current:
				current = current[part]
				continue
			raise KeyError(f"Path '{path}' not found in saved result '{test_name}'.")
		return current

	def _call_gateway(self, method_path: str, payload: dict | None = None):
		request_payload = payload or {}
		status_code, response_payload = self._post_method(method_path, request_payload)
		self._record_response(
			test_name=self._testMethodName,
			method_path=method_path,
			request_payload=request_payload,
			status_code=status_code,
			payload=response_payload,
		)
		return status_code, response_payload

	def _unique_request_id(self, prefix: str):
		return f"{prefix}-{time.time_ns()}"

	def _assert_success(self, status_code: int, payload: dict, *, code: str):
		self.assertEqual(status_code, 200)
		self.assertIn("message", payload)
		self.assertTrue(payload["message"]["ok"])
		self.assertEqual(payload["message"]["code"], code)

	def _assert_validation_error(self, status_code: int, payload: dict):
		self.assertEqual(status_code, 422)
		self.assertIn("message", payload)
		self.assertFalse(payload["message"]["ok"])
		self.assertEqual(payload["message"]["code"], "VALIDATION_ERROR")

	def _assert_same_saved_value(self, first_test: str, second_test: str, path: str):
		first_value = self._get_saved_value(first_test, path)
		second_value = self._get_saved_value(second_test, path)
		self.assertEqual(first_value, second_value)

	def test_test_remote_debug_returns_success(self):
		status_code, payload = self._call_gateway("myapp.api.gateway.test_remote_debug")

		self._assert_success(status_code, payload, code="REMOTE_DEBUG_OK")
		self.assertEqual(payload["message"]["data"]["magic_number"], 34)

	def test_search_product_with_empty_query_returns_success_shape(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.search_product",
			{"search_key": "", "limit": 5},
		)

		self._assert_success(status_code, payload, code="PRODUCTS_FETCHED")
		self.assertEqual(payload["message"]["data"], [])

	def test_search_product_success(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.search_product",
			{"search_key": SALES_ITEM_CODE, "limit": 5},
		)

		self._assert_success(status_code, payload, code="PRODUCTS_FETCHED")
		self.assertTrue(payload["message"]["data"])
		self.assertEqual(payload["message"]["data"][0]["item_code"], SALES_ITEM_CODE)

	def test_create_order_success(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_order",
			{
				"customer": SALES_CUSTOMER,
				"items": [
					{
						"item_code": SALES_ITEM_CODE,
						"qty": SALES_QTY,
						"warehouse": SALES_WAREHOUSE,
					}
				],
				"company": SALES_COMPANY,
				"immediate": 0,
				"request_id": "http-chain-order-001",
			},
		)

		self._assert_success(status_code, payload, code="ORDER_CREATED")
		self.assertIn("order", payload["message"]["data"])

	def test_create_order_idempotent_replay(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_order",
			{
				"customer": SALES_CUSTOMER,
				"items": [
					{
						"item_code": SALES_ITEM_CODE,
						"qty": SALES_QTY,
						"warehouse": SALES_WAREHOUSE,
					}
				],
				"company": SALES_COMPANY,
				"immediate": 0,
				"request_id": "http-chain-order-001",
			},
		)

		self._assert_success(status_code, payload, code="ORDER_CREATED")
		self._assert_same_saved_value(
			"test_create_order_success",
			"test_create_order_idempotent_replay",
			"response.message.data.order",
		)

	def test_create_order_same_request_id_with_different_data_returns_first_result(self):
		request_id = self._unique_request_id("http-diffdata")
		first_payload = {
			"customer": SALES_CUSTOMER,
			"items": [
				{
					"item_code": SALES_ITEM_CODE,
					"qty": SALES_QTY,
					"warehouse": SALES_WAREHOUSE,
				}
			],
			"company": SALES_COMPANY,
			"immediate": 0,
			"request_id": request_id,
		}
		second_payload = {
			"customer": SALES_CUSTOMER,
			"items": [
				{
					"item_code": SALES_ITEM_CODE,
					"qty": SALES_QTY + 1,
					"warehouse": SALES_WAREHOUSE,
				}
			],
			"company": SALES_COMPANY,
			"immediate": 0,
			"request_id": request_id,
		}

		first_status, first_response = self._call_gateway("myapp.api.gateway.create_order", first_payload)
		self._assert_success(first_status, first_response, code="ORDER_CREATED")

		second_status, second_response = self._call_gateway("myapp.api.gateway.create_order", second_payload)
		self._assert_success(second_status, second_response, code="ORDER_CREATED")

		self.assertEqual(
			first_response["message"]["data"]["order"],
			second_response["message"]["data"]["order"],
		)

	def test_create_order_new_request_id_with_different_data_creates_new_order(self):
		first_status, first_response = self._call_gateway(
			"myapp.api.gateway.create_order",
			{
				"customer": SALES_CUSTOMER,
				"items": [
					{
						"item_code": SALES_ITEM_CODE,
						"qty": SALES_QTY,
						"warehouse": SALES_WAREHOUSE,
					}
				],
				"company": SALES_COMPANY,
				"immediate": 0,
				"request_id": self._unique_request_id("http-newdata-a"),
			},
		)
		self._assert_success(first_status, first_response, code="ORDER_CREATED")

		second_status, second_response = self._call_gateway(
			"myapp.api.gateway.create_order",
			{
				"customer": SALES_CUSTOMER,
				"items": [
					{
						"item_code": SALES_ITEM_CODE,
						"qty": SALES_QTY + 1,
						"warehouse": SALES_WAREHOUSE,
					}
				],
				"company": SALES_COMPANY,
				"immediate": 0,
				"request_id": self._unique_request_id("http-newdata-b"),
			},
		)
		self._assert_success(second_status, second_response, code="ORDER_CREATED")

		self.assertNotEqual(
			first_response["message"]["data"]["order"],
			second_response["message"]["data"]["order"],
		)

	def test_create_order_validation_error_shape(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_order",
			{"customer": "", "items": []},
		)

		self._assert_validation_error(status_code, payload)

	def test_create_purchase_order_validation_error_shape(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_purchase_order",
			{"supplier": "", "items": []},
		)

		self._assert_validation_error(status_code, payload)

	def test_create_purchase_order_success(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_purchase_order",
			{
				"supplier": PURCHASE_SUPPLIER,
				"items": [
					{
						"item_code": PURCHASE_ITEM_CODE,
						"qty": PURCHASE_QTY,
						"warehouse": PURCHASE_WAREHOUSE,
					}
				],
				"company": PURCHASE_COMPANY,
				"request_id": "http-chain-purchase-order-001",
			},
		)

		self._assert_success(status_code, payload, code="PURCHASE_ORDER_CREATED")
		self.assertIn("purchase_order", payload["message"]["data"])

	def test_create_purchase_order_idempotent_replay(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_purchase_order",
			{
				"supplier": PURCHASE_SUPPLIER,
				"items": [
					{
						"item_code": PURCHASE_ITEM_CODE,
						"qty": PURCHASE_QTY,
						"warehouse": PURCHASE_WAREHOUSE,
					}
				],
				"company": PURCHASE_COMPANY,
				"request_id": "http-chain-purchase-order-001",
			},
		)

		self._assert_success(status_code, payload, code="PURCHASE_ORDER_CREATED")
		self._assert_same_saved_value(
			"test_create_purchase_order_success",
			"test_create_purchase_order_idempotent_replay",
			"response.message.data.purchase_order",
		)

	def test_create_purchase_order_same_request_id_with_different_data_returns_first_result(self):
		request_id = self._unique_request_id("http-purchase-diffdata")
		first_payload = {
			"supplier": PURCHASE_SUPPLIER,
			"items": [
				{
					"item_code": PURCHASE_ITEM_CODE,
					"qty": PURCHASE_QTY,
					"warehouse": PURCHASE_WAREHOUSE,
				}
			],
			"company": PURCHASE_COMPANY,
			"request_id": request_id,
		}
		second_payload = {
			"supplier": PURCHASE_SUPPLIER,
			"items": [
				{
					"item_code": PURCHASE_ITEM_CODE,
					"qty": PURCHASE_QTY + 1,
					"warehouse": PURCHASE_WAREHOUSE,
				}
			],
			"company": PURCHASE_COMPANY,
			"request_id": request_id,
		}

		first_status, first_response = self._call_gateway(
			"myapp.api.gateway.create_purchase_order",
			first_payload,
		)
		self._assert_success(first_status, first_response, code="PURCHASE_ORDER_CREATED")

		second_status, second_response = self._call_gateway(
			"myapp.api.gateway.create_purchase_order",
			second_payload,
		)
		self._assert_success(second_status, second_response, code="PURCHASE_ORDER_CREATED")

		self.assertEqual(
			first_response["message"]["data"]["purchase_order"],
			second_response["message"]["data"]["purchase_order"],
		)

	def test_create_purchase_order_new_request_id_with_different_data_creates_new_order(self):
		first_status, first_response = self._call_gateway(
			"myapp.api.gateway.create_purchase_order",
			{
				"supplier": PURCHASE_SUPPLIER,
				"items": [
					{
						"item_code": PURCHASE_ITEM_CODE,
						"qty": PURCHASE_QTY,
						"warehouse": PURCHASE_WAREHOUSE,
					}
				],
				"company": PURCHASE_COMPANY,
				"request_id": self._unique_request_id("http-purchase-newdata-a"),
			},
		)
		self._assert_success(first_status, first_response, code="PURCHASE_ORDER_CREATED")

		second_status, second_response = self._call_gateway(
			"myapp.api.gateway.create_purchase_order",
			{
				"supplier": PURCHASE_SUPPLIER,
				"items": [
					{
						"item_code": PURCHASE_ITEM_CODE,
						"qty": PURCHASE_QTY + 1,
						"warehouse": PURCHASE_WAREHOUSE,
					}
				],
				"company": PURCHASE_COMPANY,
				"request_id": self._unique_request_id("http-purchase-newdata-b"),
			},
		)
		self._assert_success(second_status, second_response, code="PURCHASE_ORDER_CREATED")

		self.assertNotEqual(
			first_response["message"]["data"]["purchase_order"],
			second_response["message"]["data"]["purchase_order"],
		)

	def test_submit_delivery_validation_error_shape(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.submit_delivery",
			{"order_name": ""},
		)

		self._assert_validation_error(status_code, payload)

	def test_create_sales_invoice_validation_error_shape(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_sales_invoice",
			{"source_name": ""},
		)

		self._assert_validation_error(status_code, payload)

	def test_receive_purchase_order_validation_error_shape(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.receive_purchase_order",
			{"order_name": ""},
		)

		self._assert_validation_error(status_code, payload)

	def test_receive_purchase_order_success(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.receive_purchase_order",
			{
				"order_name": self._get_saved_value(
					"test_create_purchase_order_success",
					"response.message.data.purchase_order",
				),
				"request_id": "http-chain-purchase-receipt-001",
			},
		)

		self._assert_success(status_code, payload, code="PURCHASE_RECEIPT_CREATED")
		self.assertIn("purchase_receipt", payload["message"]["data"])

	def test_receive_purchase_order_idempotent_replay(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.receive_purchase_order",
			{
				"order_name": self._get_saved_value(
					"test_create_purchase_order_success",
					"response.message.data.purchase_order",
				),
				"request_id": "http-chain-purchase-receipt-001",
			},
		)

		self._assert_success(status_code, payload, code="PURCHASE_RECEIPT_CREATED")
		self._assert_same_saved_value(
			"test_receive_purchase_order_success",
			"test_receive_purchase_order_idempotent_replay",
			"response.message.data.purchase_receipt",
		)

	def test_create_purchase_invoice_validation_error_shape(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_purchase_invoice",
			{"source_name": ""},
		)

		self._assert_validation_error(status_code, payload)

	def test_create_purchase_invoice_success(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_purchase_invoice",
			{
				"source_name": self._get_saved_value(
					"test_create_purchase_order_success",
					"response.message.data.purchase_order",
				),
				"request_id": "http-chain-purchase-invoice-001",
			},
		)

		self._assert_success(status_code, payload, code="PURCHASE_INVOICE_CREATED")
		self.assertIn("purchase_invoice", payload["message"]["data"])

	def test_create_purchase_invoice_idempotent_replay(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_purchase_invoice",
			{
				"source_name": self._get_saved_value(
					"test_create_purchase_order_success",
					"response.message.data.purchase_order",
				),
				"request_id": "http-chain-purchase-invoice-001",
			},
		)

		self._assert_success(status_code, payload, code="PURCHASE_INVOICE_CREATED")
		self._assert_same_saved_value(
			"test_create_purchase_invoice_success",
			"test_create_purchase_invoice_idempotent_replay",
			"response.message.data.purchase_invoice",
		)

	def test_create_purchase_invoice_from_receipt_success(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_purchase_invoice_from_receipt",
			{
				"receipt_name": self._get_saved_value(
					"test_receive_purchase_order_success",
					"response.message.data.purchase_receipt",
				),
				"request_id": "http-chain-purchase-invoice-from-receipt-001",
			},
		)

		self._assert_success(status_code, payload, code="PURCHASE_INVOICE_CREATED")
		self.assertIn("purchase_invoice", payload["message"]["data"])

	def test_create_purchase_invoice_from_receipt_idempotent_replay(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_purchase_invoice_from_receipt",
			{
				"receipt_name": self._get_saved_value(
					"test_receive_purchase_order_success",
					"response.message.data.purchase_receipt",
				),
				"request_id": "http-chain-purchase-invoice-from-receipt-001",
			},
		)

		self._assert_success(status_code, payload, code="PURCHASE_INVOICE_CREATED")
		self._assert_same_saved_value(
			"test_create_purchase_invoice_from_receipt_success",
			"test_create_purchase_invoice_from_receipt_idempotent_replay",
			"response.message.data.purchase_invoice",
		)

	def test_confirm_pending_document_validation_error_shape(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.confirm_pending_document",
			{"doctype": "", "docname": ""},
		)

		self._assert_validation_error(status_code, payload)

	def test_update_payment_status_validation_error_shape(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.update_payment_status",
			{
				"reference_doctype": "",
				"reference_name": "",
				"paid_amount": 0,
			},
		)

		self._assert_validation_error(status_code, payload)

	def test_record_supplier_payment_validation_error_shape(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.record_supplier_payment",
			{
				"reference_name": "",
				"paid_amount": 0,
			},
		)

		self._assert_validation_error(status_code, payload)

	def test_record_supplier_payment_success(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.record_supplier_payment",
			{
				"reference_name": self._get_saved_value(
					"test_create_purchase_invoice_success",
					"response.message.data.purchase_invoice",
				),
				"paid_amount": PURCHASE_PAID_AMOUNT,
				"request_id": "http-chain-supplier-payment-001",
			},
		)

		self._assert_success(status_code, payload, code="SUPPLIER_PAYMENT_RECORDED")
		self.assertIn("payment_entry", payload["message"]["data"])

	def test_record_supplier_payment_idempotent_replay(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.record_supplier_payment",
			{
				"reference_name": self._get_saved_value(
					"test_create_purchase_invoice_success",
					"response.message.data.purchase_invoice",
				),
				"paid_amount": PURCHASE_PAID_AMOUNT,
				"request_id": "http-chain-supplier-payment-001",
			},
		)

		self._assert_success(status_code, payload, code="SUPPLIER_PAYMENT_RECORDED")
		self._assert_same_saved_value(
			"test_record_supplier_payment_success",
			"test_record_supplier_payment_idempotent_replay",
			"response.message.data.payment_entry",
		)

	def test_process_sales_return_validation_error_shape(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.process_sales_return",
			{
				"source_doctype": "Sales Order",
				"source_name": "SO-INVALID",
			},
		)

		self._assert_validation_error(status_code, payload)

	def test_process_purchase_return_validation_error_shape(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.process_purchase_return",
			{
				"source_doctype": "Purchase Order",
				"source_name": "PO-INVALID",
			},
		)

		self._assert_validation_error(status_code, payload)

	def test_process_purchase_return_success(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.process_purchase_return",
			{
				"source_doctype": "Purchase Invoice",
				"source_name": self._get_saved_value(
					"test_create_purchase_invoice_success",
					"response.message.data.purchase_invoice",
				),
				"request_id": "http-chain-purchase-return-001",
			},
		)

		self._assert_success(status_code, payload, code="PURCHASE_RETURN_CREATED")
		self.assertIn("return_document", payload["message"]["data"])

	def test_process_purchase_return_idempotent_replay(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.process_purchase_return",
			{
				"source_doctype": "Purchase Invoice",
				"source_name": self._get_saved_value(
					"test_create_purchase_invoice_success",
					"response.message.data.purchase_invoice",
				),
				"request_id": "http-chain-purchase-return-001",
			},
		)

		self._assert_success(status_code, payload, code="PURCHASE_RETURN_CREATED")
		self._assert_same_saved_value(
			"test_process_purchase_return_success",
			"test_process_purchase_return_idempotent_replay",
			"response.message.data.return_document",
		)

	def test_create_purchase_order_concurrent_same_request_id_returns_single_order(self):
		request_id = self._unique_request_id("http-purchase-concurrent")
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
			"request_id": request_id,
		}

		def worker(index: int):
			status_code, response_payload = self._post_method(
				"myapp.api.gateway.create_purchase_order",
				payload,
			)
			self._record_response(
				test_name=f"{self._testMethodName}_worker_{index}",
				method_path="myapp.api.gateway.create_purchase_order",
				request_payload=payload,
				status_code=status_code,
				payload=response_payload,
			)
			return status_code, response_payload["message"]["data"]["purchase_order"]

		with ThreadPoolExecutor(max_workers=4) as executor:
			results = list(executor.map(worker, range(4)))

		for status_code, _purchase_order in results:
			self.assertEqual(status_code, 200)

		self.assertEqual(len({purchase_order for _status, purchase_order in results}), 1)

	def test_submit_delivery_success(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.submit_delivery",
			{
				"order_name": self._get_saved_value("test_create_order_success", "response.message.data.order"),
				"request_id": "http-chain-delivery-001",
			},
		)

		self._assert_success(status_code, payload, code="DELIVERY_SUBMITTED")

	def test_submit_delivery_idempotent_replay(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.submit_delivery",
			{
				"order_name": self._get_saved_value("test_create_order_success", "response.message.data.order"),
				"request_id": "http-chain-delivery-001",
			},
		)

		self._assert_success(status_code, payload, code="DELIVERY_SUBMITTED")
		self._assert_same_saved_value(
			"test_submit_delivery_success",
			"test_submit_delivery_idempotent_replay",
			"response.message.data.delivery_note",
		)

	def test_create_sales_invoice_success(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_sales_invoice",
			{
				"source_name": self._get_saved_value("test_create_order_success", "response.message.data.order"),
				"request_id": "http-chain-invoice-001",
			},
		)

		self._assert_success(status_code, payload, code="SALES_INVOICE_CREATED")
		self.assertIn("sales_invoice", payload["message"]["data"])

	def test_create_sales_invoice_idempotent_replay(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_sales_invoice",
			{
				"source_name": self._get_saved_value("test_create_order_success", "response.message.data.order"),
				"request_id": "http-chain-invoice-001",
			},
		)

		self._assert_success(status_code, payload, code="SALES_INVOICE_CREATED")
		self._assert_same_saved_value(
			"test_create_sales_invoice_success",
			"test_create_sales_invoice_idempotent_replay",
			"response.message.data.sales_invoice",
		)

	def test_update_payment_status_success(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.update_payment_status",
			{
				"reference_doctype": "Sales Invoice",
				"reference_name": self._get_saved_value(
					"test_create_sales_invoice_success",
					"response.message.data.sales_invoice",
				),
				"paid_amount": SALES_PAID_AMOUNT,
				"request_id": "http-chain-payment-001",
			},
		)

		self._assert_success(status_code, payload, code="PAYMENT_RECORDED")
		self.assertIn("payment_entry", payload["message"]["data"])

	def test_update_payment_status_idempotent_replay(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.update_payment_status",
			{
				"reference_doctype": "Sales Invoice",
				"reference_name": self._get_saved_value(
					"test_create_sales_invoice_success",
					"response.message.data.sales_invoice",
				),
				"paid_amount": SALES_PAID_AMOUNT,
				"request_id": "http-chain-payment-001",
			},
		)

		self._assert_success(status_code, payload, code="PAYMENT_RECORDED")
		self._assert_same_saved_value(
			"test_update_payment_status_success",
			"test_update_payment_status_idempotent_replay",
			"response.message.data.payment_entry",
		)

	def test_process_sales_return_success(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.process_sales_return",
			{
				"source_doctype": "Sales Invoice",
				"source_name": self._get_saved_value(
					"test_create_sales_invoice_success",
					"response.message.data.sales_invoice",
				),
				"request_id": "http-chain-return-001",
			},
		)

		self._assert_success(status_code, payload, code="SALES_RETURN_CREATED")
		self.assertIn("return_document", payload["message"]["data"])

	def test_process_sales_return_idempotent_replay(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.process_sales_return",
			{
				"source_doctype": "Sales Invoice",
				"source_name": self._get_saved_value(
					"test_create_sales_invoice_success",
					"response.message.data.sales_invoice",
				),
				"request_id": "http-chain-return-001",
			},
		)

		self._assert_success(status_code, payload, code="SALES_RETURN_CREATED")
		self._assert_same_saved_value(
			"test_process_sales_return_success",
			"test_process_sales_return_idempotent_replay",
			"response.message.data.return_document",
		)

	def test_create_order_concurrent_same_request_id_returns_single_order(self):
		request_id = self._unique_request_id("http-concurrent")
		payload = {
			"customer": SALES_CUSTOMER,
			"items": [
				{
					"item_code": SALES_ITEM_CODE,
					"qty": SALES_QTY,
					"warehouse": SALES_WAREHOUSE,
				}
			],
			"company": SALES_COMPANY,
			"immediate": 0,
			"request_id": request_id,
		}

		def worker(index: int):
			status_code, response_payload = self._post_method("myapp.api.gateway.create_order", payload)
			self._record_response(
				test_name=f"{self._testMethodName}_worker_{index}",
				method_path="myapp.api.gateway.create_order",
				request_payload=payload,
				status_code=status_code,
				payload=response_payload,
			)
			return status_code, response_payload["message"]["data"]["order"]

		with ThreadPoolExecutor(max_workers=4) as executor:
			results = list(executor.map(worker, range(4)))

		for status_code, _order in results:
			self.assertEqual(status_code, 200)

		self.assertEqual(len({order for _status, order in results}), 1)


if __name__ == "__main__":
	unittest.main()
