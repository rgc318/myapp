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
	def _get_resource(cls, doctype: str, name: str):
		request = urllib.request.Request(
			f"{BASE_URL}/api/resource/{urllib.parse.quote(doctype)}/{urllib.parse.quote(name)}",
			headers=cls._headers(),
			method="GET",
		)
		with cls._opener.open(request, timeout=15) as response:
			payload = json.loads(response.read().decode() or "{}")
		return payload["data"]

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
		try:
			return json.loads(RESULTS_FILE.read_text(encoding="utf-8") or "{}")
		except json.JSONDecodeError:
			return {}

	@classmethod
	def _get_saved_result(cls, test_name: str):
		if test_name in cls._results:
			return cls._results[test_name]
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

	def _get_first_item(self, doctype: str, name: str):
		doc = self._get_resource(doctype, name)
		self.assertTrue(doc.get("items"))
		return doc["items"][0]

	def _create_sales_order(
		self,
		*,
		item_code: str | None = None,
		qty: float | None = None,
		price: float | None = None,
		request_id: str | None = None,
	):
		payload = {
			"customer": SALES_CUSTOMER,
			"items": [
				{
					"item_code": item_code or SALES_ITEM_CODE,
					"qty": qty if qty is not None else SALES_QTY,
					"warehouse": SALES_WAREHOUSE,
				}
			],
			"company": SALES_COMPANY,
			"immediate": 0,
			"request_id": request_id or self._unique_request_id("http-sales-order"),
		}
		if price is not None:
			payload["items"][0]["price"] = price
		status_code, response = self._post_method("myapp.api.gateway.create_order", payload)
		self._assert_success(status_code, response, code="ORDER_CREATED")
		return payload, response

	def _submit_sales_delivery(
		self,
		order_name: str,
		*,
		request_id: str | None = None,
		delivery_items: list[dict] | None = None,
	):
		payload = {
			"order_name": order_name,
			"request_id": request_id or self._unique_request_id("http-delivery"),
		}
		if delivery_items is not None:
			payload["delivery_items"] = delivery_items
		status_code, response = self._post_method("myapp.api.gateway.submit_delivery", payload)
		self._assert_success(status_code, response, code="DELIVERY_SUBMITTED")
		return payload, response

	def _create_sales_invoice(
		self,
		source_name: str,
		*,
		request_id: str | None = None,
		invoice_items: list[dict] | None = None,
	):
		payload = {
			"source_name": source_name,
			"request_id": request_id or self._unique_request_id("http-sales-invoice"),
		}
		if invoice_items is not None:
			payload["invoice_items"] = invoice_items
		status_code, response = self._post_method("myapp.api.gateway.create_sales_invoice", payload)
		self._assert_success(status_code, response, code="SALES_INVOICE_CREATED")
		return payload, response

	def _record_sales_payment(
		self,
		invoice_name: str,
		*,
		paid_amount: float | None = None,
		request_id: str | None = None,
		settlement_mode: str | None = None,
		writeoff_reason: str | None = None,
	):
		payload = {
			"reference_doctype": "Sales Invoice",
			"reference_name": invoice_name,
			"paid_amount": paid_amount if paid_amount is not None else SALES_PAID_AMOUNT,
			"request_id": request_id or self._unique_request_id("http-sales-payment"),
		}
		if settlement_mode is not None:
			payload["settlement_mode"] = settlement_mode
		if writeoff_reason is not None:
			payload["writeoff_reason"] = writeoff_reason
		status_code, response = self._post_method("myapp.api.gateway.update_payment_status", payload)
		self._assert_success(status_code, response, code="PAYMENT_RECORDED")
		return payload, response

	def _create_sales_return(
		self,
		source_name: str,
		*,
		source_doctype: str = "Sales Invoice",
		request_id: str | None = None,
		return_items: list[dict] | None = None,
	):
		payload = {
			"source_doctype": source_doctype,
			"source_name": source_name,
			"request_id": request_id or self._unique_request_id("http-sales-return"),
		}
		if return_items is not None:
			payload["return_items"] = return_items
		status_code, response = self._post_method("myapp.api.gateway.process_sales_return", payload)
		self._assert_success(status_code, response, code="SALES_RETURN_CREATED")
		return payload, response

	def _create_purchase_order(
		self,
		*,
		item_code: str | None = None,
		qty: float | None = None,
		price: float | None = None,
		request_id: str | None = None,
	):
		payload = {
			"supplier": PURCHASE_SUPPLIER,
			"items": [
				{
					"item_code": item_code or PURCHASE_ITEM_CODE,
					"qty": qty if qty is not None else PURCHASE_QTY,
					"warehouse": PURCHASE_WAREHOUSE,
				}
			],
			"company": PURCHASE_COMPANY,
			"request_id": request_id or self._unique_request_id("http-purchase-order"),
		}
		if price is not None:
			payload["items"][0]["price"] = price
		status_code, response = self._post_method("myapp.api.gateway.create_purchase_order", payload)
		self._assert_success(status_code, response, code="PURCHASE_ORDER_CREATED")
		return payload, response

	def _receive_purchase_order(
		self,
		order_name: str,
		*,
		request_id: str | None = None,
		receipt_items: list[dict] | None = None,
	):
		payload = {
			"order_name": order_name,
			"request_id": request_id or self._unique_request_id("http-purchase-receipt"),
		}
		if receipt_items is not None:
			payload["receipt_items"] = receipt_items
		status_code, response = self._post_method("myapp.api.gateway.receive_purchase_order", payload)
		self._assert_success(status_code, response, code="PURCHASE_RECEIPT_CREATED")
		return payload, response

	def _create_purchase_invoice(
		self,
		source_name: str,
		*,
		request_id: str | None = None,
	):
		payload = {
			"source_name": source_name,
			"request_id": request_id or self._unique_request_id("http-purchase-invoice"),
		}
		status_code, response = self._post_method("myapp.api.gateway.create_purchase_invoice", payload)
		self._assert_success(status_code, response, code="PURCHASE_INVOICE_CREATED")
		return payload, response

	def _create_purchase_invoice_from_receipt(
		self,
		receipt_name: str,
		*,
		request_id: str | None = None,
		invoice_items: list[dict] | None = None,
	):
		payload = {
			"receipt_name": receipt_name,
			"request_id": request_id or self._unique_request_id("http-purchase-invoice-from-receipt"),
		}
		if invoice_items is not None:
			payload["invoice_items"] = invoice_items
		status_code, response = self._post_method("myapp.api.gateway.create_purchase_invoice_from_receipt", payload)
		self._assert_success(status_code, response, code="PURCHASE_INVOICE_CREATED")
		return payload, response

	def _record_supplier_payment(
		self,
		invoice_name: str,
		*,
		paid_amount: float | None = None,
		request_id: str | None = None,
	):
		payload = {
			"reference_name": invoice_name,
			"paid_amount": paid_amount if paid_amount is not None else PURCHASE_PAID_AMOUNT,
			"request_id": request_id or self._unique_request_id("http-supplier-payment"),
		}
		status_code, response = self._post_method("myapp.api.gateway.record_supplier_payment", payload)
		self._assert_success(status_code, response, code="SUPPLIER_PAYMENT_RECORDED")
		return payload, response

	def _get_supplier_seed_payload(self, *, suffix: str):
		template = self._get_resource("Supplier", PURCHASE_SUPPLIER)
		supplier_name = f"MyApp Supplier {suffix}"
		serial = "".join(ch for ch in suffix if ch.isdigit())[-8:].zfill(8)
		return {
			"supplier_name": supplier_name,
			"supplier_type": template.get("supplier_type") or "Company",
			"supplier_group": template.get("supplier_group"),
			"default_currency": template.get("default_currency") or "CNY",
			"mobile_no": f"139{serial}",
			"email_id": f"supplier-{suffix}@example.com",
			"remarks": "HTTP supplier management test",
			"default_contact": {
				"display_name": f"联系人{serial[-4:]}",
				"phone": f"138{serial}",
				"email": f"contact-{suffix}@example.com",
			},
			"default_address": {
				"address_line1": f"测试路 {serial[-4:]} 号",
				"city": "上海",
				"country": "China",
				"address_type": "Billing",
			},
		}

	def _create_purchase_return(
		self,
		source_name: str,
		*,
		source_doctype: str = "Purchase Invoice",
		request_id: str | None = None,
		return_items: list[dict] | None = None,
	):
		payload = {
			"source_doctype": source_doctype,
			"source_name": source_name,
			"request_id": request_id or self._unique_request_id("http-purchase-return"),
		}
		if return_items is not None:
			payload["return_items"] = return_items
		status_code, response = self._post_method("myapp.api.gateway.process_purchase_return", payload)
		self._assert_success(status_code, response, code="PURCHASE_RETURN_CREATED")
		return payload, response

	def _get_return_source_context(self, source_doctype: str, source_name: str):
		payload = {
			"source_doctype": source_doctype,
			"source_name": source_name,
		}
		status_code, response = self._post_method("myapp.api.gateway.get_return_source_context_v2", payload)
		self._assert_success(status_code, response, code="RETURN_SOURCE_CONTEXT_FETCHED")
		return payload, response

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

	def test_search_product_returns_specification_for_new_item(self):
		specification = f"老搜索规格-{time.time_ns()}"
		create_status, create_payload = self._post_method(
			"myapp.api.gateway.create_product_and_stock",
			{
				"item_name": f"HTTP-老搜索商品-{time.time_ns()}",
				"default_warehouse": SALES_WAREHOUSE,
				"opening_qty": 1,
				"standard_rate": 11,
				"barcode": f"LEGACY{time.time_ns()}"[-16:],
				"specification": specification,
				"request_id": self._unique_request_id("http-legacy-product-spec"),
			},
		)
		self._assert_success(create_status, create_payload, code="PRODUCT_CREATED")
		item_code = create_payload["message"]["data"]["item_code"]

		status_code, payload = self._call_gateway(
			"myapp.api.gateway.search_product",
			{"search_key": specification, "limit": 5},
		)

		self._assert_success(status_code, payload, code="PRODUCTS_FETCHED")
		rows = [row for row in payload["message"]["data"] if row["item_code"] == item_code]
		self.assertTrue(rows)
		self.assertEqual(rows[0]["specification"], specification)

	def test_create_order_success(self):
		_request, payload = self._create_sales_order()
		self.assertIn("order", payload["message"]["data"])

	def test_create_order_idempotent_replay(self):
		request_id = self._unique_request_id("http-chain-order")
		first_request, first_payload = self._create_sales_order(request_id=request_id)
		second_status, second_payload = self._call_gateway("myapp.api.gateway.create_order", first_request)
		self._assert_success(second_status, second_payload, code="ORDER_CREATED")
		self.assertEqual(
			first_payload["message"]["data"]["order"],
			second_payload["message"]["data"]["order"],
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
		_request, payload = self._create_purchase_order()
		self.assertIn("purchase_order", payload["message"]["data"])

	def test_create_purchase_order_idempotent_replay(self):
		request_id = self._unique_request_id("http-chain-purchase-order")
		first_request, first_payload = self._create_purchase_order(request_id=request_id)
		second_status, second_payload = self._call_gateway("myapp.api.gateway.create_purchase_order", first_request)
		self._assert_success(second_status, second_payload, code="PURCHASE_ORDER_CREATED")
		self.assertEqual(
			first_payload["message"]["data"]["purchase_order"],
			second_payload["message"]["data"]["purchase_order"],
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
		_order_request, order_payload = self._create_purchase_order()
		order_name = order_payload["message"]["data"]["purchase_order"]
		_request, payload = self._receive_purchase_order(order_name)
		self.assertIn("purchase_receipt", payload["message"]["data"])

	def test_receive_purchase_order_idempotent_replay(self):
		_order_request, order_payload = self._create_purchase_order()
		order_name = order_payload["message"]["data"]["purchase_order"]
		request_id = self._unique_request_id("http-chain-purchase-receipt")
		first_request, first_payload = self._receive_purchase_order(order_name, request_id=request_id)
		second_status, second_payload = self._call_gateway("myapp.api.gateway.receive_purchase_order", first_request)
		self._assert_success(second_status, second_payload, code="PURCHASE_RECEIPT_CREATED")
		self.assertEqual(
			first_payload["message"]["data"]["purchase_receipt"],
			second_payload["message"]["data"]["purchase_receipt"],
		)

	def test_receive_purchase_order_partial_success(self):
		order_status, order_payload = self._call_gateway(
			"myapp.api.gateway.create_purchase_order",
			{
				"supplier": PURCHASE_SUPPLIER,
				"items": [
					{
						"item_code": PURCHASE_ITEM_CODE,
						"qty": PURCHASE_QTY,
						"warehouse": PURCHASE_WAREHOUSE,
						"price": 500,
					}
				],
				"company": PURCHASE_COMPANY,
				"request_id": self._unique_request_id("http-partial-purchase-order"),
			},
		)
		self._assert_success(order_status, order_payload, code="PURCHASE_ORDER_CREATED")
		order_name = order_payload["message"]["data"]["purchase_order"]
		order_item = self._get_first_item("Purchase Order", order_name)

		status_code, payload = self._call_gateway(
			"myapp.api.gateway.receive_purchase_order",
			{
				"order_name": order_name,
				"receipt_items": [
					{
						"purchase_order_item": order_item["name"],
						"qty": 2,
						"price": 480,
					}
				],
				"request_id": self._unique_request_id("http-partial-purchase-receipt"),
			},
		)

		self._assert_success(status_code, payload, code="PURCHASE_RECEIPT_CREATED")
		receipt_name = payload["message"]["data"]["purchase_receipt"]
		receipt_item = self._get_first_item("Purchase Receipt", receipt_name)
		self.assertEqual(receipt_item["qty"], 2.0)
		self.assertEqual(receipt_item["rate"], 480.0)

	def test_create_purchase_invoice_validation_error_shape(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_purchase_invoice",
			{"source_name": ""},
		)

		self._assert_validation_error(status_code, payload)

	def test_create_purchase_invoice_success(self):
		_order_request, order_payload = self._create_purchase_order()
		order_name = order_payload["message"]["data"]["purchase_order"]
		_request, payload = self._create_purchase_invoice(order_name)
		self.assertIn("purchase_invoice", payload["message"]["data"])

	def test_create_purchase_invoice_idempotent_replay(self):
		_order_request, order_payload = self._create_purchase_order()
		order_name = order_payload["message"]["data"]["purchase_order"]
		request_id = self._unique_request_id("http-chain-purchase-invoice")
		first_request, first_payload = self._create_purchase_invoice(order_name, request_id=request_id)
		second_status, second_payload = self._call_gateway("myapp.api.gateway.create_purchase_invoice", first_request)
		self._assert_success(second_status, second_payload, code="PURCHASE_INVOICE_CREATED")
		self.assertEqual(
			first_payload["message"]["data"]["purchase_invoice"],
			second_payload["message"]["data"]["purchase_invoice"],
		)

	def test_create_purchase_invoice_from_receipt_success(self):
		_order_request, order_payload = self._create_purchase_order()
		order_name = order_payload["message"]["data"]["purchase_order"]
		_receipt_request, receipt_payload = self._receive_purchase_order(order_name)
		receipt_name = receipt_payload["message"]["data"]["purchase_receipt"]
		_request, payload = self._create_purchase_invoice_from_receipt(receipt_name)
		self.assertIn("purchase_invoice", payload["message"]["data"])

	def test_create_purchase_invoice_from_receipt_idempotent_replay(self):
		_order_request, order_payload = self._create_purchase_order()
		order_name = order_payload["message"]["data"]["purchase_order"]
		_receipt_request, receipt_payload = self._receive_purchase_order(order_name)
		receipt_name = receipt_payload["message"]["data"]["purchase_receipt"]
		request_id = self._unique_request_id("http-chain-purchase-invoice-from-receipt")
		first_request, first_payload = self._create_purchase_invoice_from_receipt(receipt_name, request_id=request_id)
		second_status, second_payload = self._call_gateway(
			"myapp.api.gateway.create_purchase_invoice_from_receipt",
			first_request,
		)
		self._assert_success(second_status, second_payload, code="PURCHASE_INVOICE_CREATED")
		self.assertEqual(
			first_payload["message"]["data"]["purchase_invoice"],
			second_payload["message"]["data"]["purchase_invoice"],
		)

	def test_create_purchase_invoice_from_receipt_partial_success(self):
		_order_request, order_payload = self._create_purchase_order(price=500)
		order_name = order_payload["message"]["data"]["purchase_order"]
		order_item = self._get_first_item("Purchase Order", order_name)
		_receipt_request, receipt_payload = self._receive_purchase_order(
			order_name,
			receipt_items=[
				{
					"purchase_order_item": order_item["name"],
					"qty": 2,
					"price": 480,
				}
			],
		)
		receipt_name = receipt_payload["message"]["data"]["purchase_receipt"]
		receipt_item = self._get_first_item("Purchase Receipt", receipt_name)

		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_purchase_invoice_from_receipt",
			{
				"receipt_name": receipt_name,
				"invoice_items": [
					{
						"purchase_receipt_item": receipt_item["name"],
						"qty": 1,
						"price": 470,
					}
				],
				"request_id": self._unique_request_id("http-partial-purchase-invoice-from-receipt"),
			},
		)

		self._assert_success(status_code, payload, code="PURCHASE_INVOICE_CREATED")
		invoice_name = payload["message"]["data"]["purchase_invoice"]
		invoice_item = self._get_first_item("Purchase Invoice", invoice_name)
		self.assertEqual(invoice_item["qty"], 1.0)
		self.assertEqual(invoice_item["rate"], 470.0)

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
		_order_request, order_payload = self._create_purchase_order()
		order_name = order_payload["message"]["data"]["purchase_order"]
		_invoice_request, invoice_payload = self._create_purchase_invoice(order_name)
		invoice_name = invoice_payload["message"]["data"]["purchase_invoice"]
		_request, payload = self._record_supplier_payment(invoice_name)
		self.assertIn("payment_entry", payload["message"]["data"])

	def test_record_supplier_payment_idempotent_replay(self):
		_order_request, order_payload = self._create_purchase_order()
		order_name = order_payload["message"]["data"]["purchase_order"]
		_invoice_request, invoice_payload = self._create_purchase_invoice(order_name)
		invoice_name = invoice_payload["message"]["data"]["purchase_invoice"]
		request_id = self._unique_request_id("http-chain-supplier-payment")
		first_request, first_payload = self._record_supplier_payment(invoice_name, request_id=request_id)
		second_status, second_payload = self._call_gateway("myapp.api.gateway.record_supplier_payment", first_request)
		self._assert_success(second_status, second_payload, code="SUPPLIER_PAYMENT_RECORDED")
		self.assertEqual(
			first_payload["message"]["data"]["payment_entry"],
			second_payload["message"]["data"]["payment_entry"],
		)

	def test_create_supplier_v2_success(self):
		suffix = str(time.time_ns())
		payload = self._get_supplier_seed_payload(suffix=suffix)
		payload["request_id"] = self._unique_request_id("http-create-supplier")

		status_code, response = self._call_gateway("myapp.api.gateway.create_supplier_v2", payload)

		self._assert_success(status_code, response, code="SUPPLIER_CREATED")
		data = response["message"]["data"]
		self.assertEqual(data["display_name"], payload["supplier_name"])
		self.assertEqual(data["default_contact"]["email"], payload["default_contact"]["email"])
		self.assertEqual(data["default_address"]["city"], payload["default_address"]["city"])

	def test_update_supplier_v2_success(self):
		suffix = str(time.time_ns())
		create_payload = self._get_supplier_seed_payload(suffix=suffix)
		create_payload["request_id"] = self._unique_request_id("http-update-supplier-create")
		create_status, create_response = self._call_gateway("myapp.api.gateway.create_supplier_v2", create_payload)
		self._assert_success(create_status, create_response, code="SUPPLIER_CREATED")
		supplier_name = create_response["message"]["data"]["name"]

		status_code, response = self._call_gateway(
			"myapp.api.gateway.update_supplier_v2",
			{
				"supplier": supplier_name,
				"supplier_name": f"{create_payload['supplier_name']} Updated",
				"remarks": "updated by http test",
				"default_contact": {
					"display_name": "更新联系人",
					"phone": "13800138000",
					"email": f"updated-{suffix}@example.com",
				},
				"default_address": {
					"address_line1": "更新地址 88 号",
					"city": "杭州",
					"country": "China",
					"address_type": "Billing",
				},
				"request_id": self._unique_request_id("http-update-supplier"),
			},
		)

		self._assert_success(status_code, response, code="SUPPLIER_UPDATED")
		data = response["message"]["data"]
		self.assertEqual(data["display_name"], f"{create_payload['supplier_name']} Updated")
		self.assertEqual(data["default_address"]["city"], "杭州")
		self.assertEqual(data["default_contact"]["email"], f"updated-{suffix}@example.com")

	def test_disable_supplier_v2_success(self):
		suffix = str(time.time_ns())
		create_payload = self._get_supplier_seed_payload(suffix=suffix)
		create_payload["request_id"] = self._unique_request_id("http-disable-supplier-create")
		create_status, create_response = self._call_gateway("myapp.api.gateway.create_supplier_v2", create_payload)
		self._assert_success(create_status, create_response, code="SUPPLIER_CREATED")
		supplier_name = create_response["message"]["data"]["name"]

		status_code, response = self._call_gateway(
			"myapp.api.gateway.disable_supplier_v2",
			{
				"supplier": supplier_name,
				"disabled": 1,
				"request_id": self._unique_request_id("http-disable-supplier"),
			},
		)

		self._assert_success(status_code, response, code="SUPPLIER_DISABLED")
		self.assertEqual(response["message"]["data"]["disabled"], 1)

	def test_list_and_detail_supplier_v2_include_created_supplier(self):
		suffix = str(time.time_ns())
		create_payload = self._get_supplier_seed_payload(suffix=suffix)
		create_payload["request_id"] = self._unique_request_id("http-list-supplier-create")
		create_status, create_response = self._call_gateway("myapp.api.gateway.create_supplier_v2", create_payload)
		self._assert_success(create_status, create_response, code="SUPPLIER_CREATED")
		supplier_name = create_response["message"]["data"]["name"]

		list_status, list_response = self._call_gateway(
			"myapp.api.gateway.list_suppliers_v2",
			{"search_key": create_payload["supplier_name"], "limit": 20, "start": 0},
		)
		self._assert_success(list_status, list_response, code="SUPPLIER_LIST_FETCHED")
		self.assertTrue(
			any(row["name"] == supplier_name for row in list_response["message"]["data"]),
			"newly created supplier should be discoverable in list_suppliers_v2",
		)

		detail_status, detail_response = self._call_gateway(
			"myapp.api.gateway.get_supplier_detail_v2",
			{"supplier": supplier_name},
		)
		self._assert_success(detail_status, detail_response, code="SUPPLIER_DETAIL_FETCHED")
		self.assertEqual(detail_response["message"]["data"]["name"], supplier_name)
		self.assertIn("recent_addresses", detail_response["message"]["data"])

	def test_create_supplier_v2_validation_error_shape(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_supplier_v2",
			{"supplier_name": "", "request_id": self._unique_request_id("http-create-supplier-invalid")},
		)

		self._assert_validation_error(status_code, payload)

	def test_create_supplier_v2_rejects_duplicate_name(self):
		suffix = str(time.time_ns())
		create_payload = self._get_supplier_seed_payload(suffix=suffix)
		create_payload["request_id"] = self._unique_request_id("http-duplicate-supplier-create-a")
		create_status, create_response = self._call_gateway("myapp.api.gateway.create_supplier_v2", create_payload)
		self._assert_success(create_status, create_response, code="SUPPLIER_CREATED")

		duplicate_payload = dict(create_payload)
		duplicate_payload["request_id"] = self._unique_request_id("http-duplicate-supplier-create-b")
		status_code, payload = self._call_gateway("myapp.api.gateway.create_supplier_v2", duplicate_payload)

		self._assert_validation_error(status_code, payload)

	def test_create_supplier_v2_idempotent_replay_returns_same_supplier(self):
		suffix = str(time.time_ns())
		request_payload = self._get_supplier_seed_payload(suffix=suffix)
		request_payload["request_id"] = self._unique_request_id("http-create-supplier-idempotent")

		first_status, first_response = self._call_gateway("myapp.api.gateway.create_supplier_v2", request_payload)
		second_status, second_response = self._call_gateway("myapp.api.gateway.create_supplier_v2", request_payload)

		self._assert_success(first_status, first_response, code="SUPPLIER_CREATED")
		self._assert_success(second_status, second_response, code="SUPPLIER_CREATED")
		self.assertEqual(
			first_response["message"]["data"]["name"],
			second_response["message"]["data"]["name"],
		)

	def test_update_supplier_v2_idempotent_replay_returns_same_payload(self):
		suffix = str(time.time_ns())
		create_payload = self._get_supplier_seed_payload(suffix=suffix)
		create_payload["request_id"] = self._unique_request_id("http-update-supplier-idempotent-create")
		create_status, create_response = self._call_gateway("myapp.api.gateway.create_supplier_v2", create_payload)
		self._assert_success(create_status, create_response, code="SUPPLIER_CREATED")
		supplier_name = create_response["message"]["data"]["name"]

		update_payload = {
			"supplier": supplier_name,
			"supplier_name": f"{create_payload['supplier_name']} Replay",
			"remarks": "replay update",
			"default_contact": {
				"display_name": "回放联系人",
				"phone": "13800990099",
				"email": f"replay-{suffix}@example.com",
			},
			"default_address": {
				"address_line1": "回放地址 66 号",
				"city": "苏州",
				"country": "China",
				"address_type": "Billing",
			},
			"request_id": self._unique_request_id("http-update-supplier-idempotent"),
		}

		first_status, first_response = self._call_gateway("myapp.api.gateway.update_supplier_v2", update_payload)
		second_status, second_response = self._call_gateway("myapp.api.gateway.update_supplier_v2", update_payload)

		self._assert_success(first_status, first_response, code="SUPPLIER_UPDATED")
		self._assert_success(second_status, second_response, code="SUPPLIER_UPDATED")
		self.assertEqual(
			first_response["message"]["data"]["default_contact"]["email"],
			second_response["message"]["data"]["default_contact"]["email"],
		)

	def test_disable_supplier_v2_idempotent_replay_returns_same_supplier(self):
		suffix = str(time.time_ns())
		create_payload = self._get_supplier_seed_payload(suffix=suffix)
		create_payload["request_id"] = self._unique_request_id("http-disable-supplier-idempotent-create")
		create_status, create_response = self._call_gateway("myapp.api.gateway.create_supplier_v2", create_payload)
		self._assert_success(create_status, create_response, code="SUPPLIER_CREATED")
		supplier_name = create_response["message"]["data"]["name"]

		disable_payload = {
			"supplier": supplier_name,
			"disabled": 1,
			"request_id": self._unique_request_id("http-disable-supplier-idempotent"),
		}
		first_status, first_response = self._call_gateway("myapp.api.gateway.disable_supplier_v2", disable_payload)
		second_status, second_response = self._call_gateway("myapp.api.gateway.disable_supplier_v2", disable_payload)

		self._assert_success(first_status, first_response, code="SUPPLIER_DISABLED")
		self._assert_success(second_status, second_response, code="SUPPLIER_DISABLED")
		self.assertEqual(
			first_response["message"]["data"]["name"],
			second_response["message"]["data"]["name"],
		)
		self.assertEqual(second_response["message"]["data"]["disabled"], 1)

	def test_list_suppliers_v2_supports_disabled_filter_and_paging(self):
		suffix_a = f"{time.time_ns()}a"
		suffix_b = f"{time.time_ns()}b"
		payload_a = self._get_supplier_seed_payload(suffix=suffix_a)
		payload_a["request_id"] = self._unique_request_id("http-list-supplier-filter-a")
		payload_b = self._get_supplier_seed_payload(suffix=suffix_b)
		payload_b["request_id"] = self._unique_request_id("http-list-supplier-filter-b")

		status_a, response_a = self._call_gateway("myapp.api.gateway.create_supplier_v2", payload_a)
		status_b, response_b = self._call_gateway("myapp.api.gateway.create_supplier_v2", payload_b)
		self._assert_success(status_a, response_a, code="SUPPLIER_CREATED")
		self._assert_success(status_b, response_b, code="SUPPLIER_CREATED")
		supplier_a = response_a["message"]["data"]["name"]
		supplier_b = response_b["message"]["data"]["name"]

		disable_status, disable_response = self._call_gateway(
			"myapp.api.gateway.disable_supplier_v2",
			{
				"supplier": supplier_b,
				"disabled": 1,
				"request_id": self._unique_request_id("http-list-supplier-filter-disable"),
			},
		)
		self._assert_success(disable_status, disable_response, code="SUPPLIER_DISABLED")

		active_status, active_response = self._call_gateway(
			"myapp.api.gateway.list_suppliers_v2",
			{
				"search_key": payload_a["supplier_name"],
				"disabled": 0,
				"limit": 1,
				"start": 0,
				"sort_by": "creation",
				"sort_order": "asc",
			},
		)
		self._assert_success(active_status, active_response, code="SUPPLIER_LIST_FETCHED")
		active_names = [row["name"] for row in active_response["message"]["data"]]
		self.assertIn(supplier_a, active_names)
		self.assertNotIn(supplier_b, active_names)
		self.assertEqual(active_response["message"]["meta"]["limit"], 1)
		self.assertEqual(active_response["message"]["meta"]["start"], 0)

		disabled_status, disabled_response = self._call_gateway(
			"myapp.api.gateway.list_suppliers_v2",
			{
				"search_key": payload_b["supplier_name"],
				"disabled": 1,
				"limit": 20,
				"start": 0,
			},
		)
		self._assert_success(disabled_status, disabled_response, code="SUPPLIER_LIST_FETCHED")
		disabled_names = [row["name"] for row in disabled_response["message"]["data"]]
		self.assertIn(supplier_b, disabled_names)

	def test_list_suppliers_v2_filters_by_group(self):
		suffix = str(time.time_ns())
		payload = self._get_supplier_seed_payload(suffix=suffix)
		payload["request_id"] = self._unique_request_id("http-list-supplier-group-create")
		create_status, create_response = self._call_gateway("myapp.api.gateway.create_supplier_v2", payload)
		self._assert_success(create_status, create_response, code="SUPPLIER_CREATED")
		supplier_name = create_response["message"]["data"]["name"]

		list_status, list_response = self._call_gateway(
			"myapp.api.gateway.list_suppliers_v2",
			{
				"search_key": payload["supplier_name"],
				"supplier_group": payload["supplier_group"],
				"limit": 20,
				"start": 0,
			},
		)
		self._assert_success(list_status, list_response, code="SUPPLIER_LIST_FETCHED")
		self.assertTrue(any(row["name"] == supplier_name for row in list_response["message"]["data"]))

	def test_get_business_report_v1_success(self):
		status_code, response = self._call_gateway(
			"myapp.api.gateway.get_business_report_v1",
			{
				"company": SALES_COMPANY,
				"date_from": "2026-03-01",
				"date_to": "2026-04-02",
				"limit": 5,
			},
		)

		self._assert_success(status_code, response, code="BUSINESS_REPORT_FETCHED")
		data = response["message"]["data"]
		self.assertIn("overview", data)
		self.assertIn("tables", data)
		self.assertIn("meta", data)
		self.assertEqual(data["meta"]["company"], SALES_COMPANY)
		self.assertEqual(data["meta"]["limit"], 5)
		self.assertIn("sales_summary", data["tables"])
		self.assertIn("purchase_summary", data["tables"])
		self.assertIn("receivable_summary", data["tables"])
		self.assertIn("payable_summary", data["tables"])
		self.assertIn("cashflow_summary", data["tables"])

	def test_get_business_report_v1_product_rows_include_specification(self):
		specification = f"报表规格-{time.time_ns()}"
		create_status, create_payload = self._post_method(
			"myapp.api.gateway.create_product_and_stock",
			{
				"item_name": f"HTTP-报表规格商品-{time.time_ns()}",
				"default_warehouse": SALES_WAREHOUSE,
				"opening_qty": 10,
				"standard_rate": 18,
				"barcode": f"REPORT{time.time_ns()}"[-16:],
				"specification": specification,
				"request_id": self._unique_request_id("http-report-product-spec"),
			},
		)
		self._assert_success(create_status, create_payload, code="PRODUCT_CREATED")
		item_code = create_payload["message"]["data"]["item_code"]

		self._create_sales_order(item_code=item_code, price=18)
		self._create_purchase_order(item_code=item_code, price=12)

		status_code, response = self._call_gateway(
			"myapp.api.gateway.get_business_report_v1",
			{
				"company": SALES_COMPANY,
				"date_from": "2026-04-05",
				"date_to": "2026-04-05",
				"limit": 10,
			},
		)

		self._assert_success(status_code, response, code="BUSINESS_REPORT_FETCHED")
		data = response["message"]["data"]["tables"]
		sales_rows = [row for row in data["sales_product_summary"] if row["item_key"] == item_code]
		purchase_rows = [row for row in data["purchase_product_summary"] if row["item_key"] == item_code]
		self.assertTrue(sales_rows)
		self.assertTrue(purchase_rows)
		self.assertEqual(sales_rows[0]["specification"], specification)
		self.assertEqual(purchase_rows[0]["specification"], specification)

	def test_get_business_report_v1_rejects_invalid_date_range(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.get_business_report_v1",
			{
				"company": SALES_COMPANY,
				"date_from": "2026-04-03",
				"date_to": "2026-04-02",
				"limit": 5,
			},
		)

		self._assert_validation_error(status_code, payload)

	def test_get_business_report_v1_rejects_too_large_date_range(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.get_business_report_v1",
			{
				"company": SALES_COMPANY,
				"date_from": "2024-01-01",
				"date_to": "2026-04-02",
				"limit": 5,
			},
		)

		self._assert_validation_error(status_code, payload)

	def test_get_cashflow_report_v1_matches_business_report_cashflow_totals(self):
		request_payload = {
			"company": SALES_COMPANY,
			"date_from": "2026-03-01",
			"date_to": "2026-04-02",
		}
		status_code, response = self._call_gateway("myapp.api.gateway.get_cashflow_report_v1", request_payload)
		self._assert_success(status_code, response, code="CASHFLOW_REPORT_FETCHED")

		business_status, business_response = self._call_gateway(
			"myapp.api.gateway.get_business_report_v1",
			{**request_payload, "limit": 5},
		)
		self._assert_success(business_status, business_response, code="BUSINESS_REPORT_FETCHED")

		cashflow_data = response["message"]["data"]
		business_data = business_response["message"]["data"]
		self.assertEqual(
			cashflow_data["overview"]["received_amount_total"],
			business_data["overview"]["received_amount_total"],
		)
		self.assertEqual(
			cashflow_data["overview"]["paid_amount_total"],
			business_data["overview"]["paid_amount_total"],
		)
		self.assertEqual(
			cashflow_data["overview"]["net_cashflow_total"],
			business_data["overview"]["net_cashflow_total"],
		)
		self.assertEqual(cashflow_data["trend"], business_data["tables"]["cashflow_trend"])

	def test_get_cashflow_report_v1_rejects_invalid_date_range(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.get_cashflow_report_v1",
			{
				"company": SALES_COMPANY,
				"date_from": "2026-04-03",
				"date_to": "2026-04-02",
			},
		)

		self._assert_validation_error(status_code, payload)

	def test_get_business_report_overview_v1_matches_business_report_overview(self):
		request_payload = {
			"company": SALES_COMPANY,
			"date_from": "2026-03-01",
			"date_to": "2026-04-02",
		}
		status_code, response = self._call_gateway("myapp.api.gateway.get_business_report_overview_v1", request_payload)
		self._assert_success(status_code, response, code="BUSINESS_REPORT_OVERVIEW_FETCHED")

		business_status, business_response = self._call_gateway(
			"myapp.api.gateway.get_business_report_v1",
			{**request_payload, "limit": 5},
		)
		self._assert_success(business_status, business_response, code="BUSINESS_REPORT_FETCHED")

		overview_data = response["message"]["data"]
		business_overview = business_response["message"]["data"]["overview"]
		self.assertEqual(overview_data["overview"], business_overview)

	def test_get_receivable_payable_report_v1_matches_business_report_tables(self):
		request_payload = {
			"company": SALES_COMPANY,
			"date_from": "2026-03-01",
			"date_to": "2026-04-02",
			"limit": 5,
		}
		status_code, response = self._call_gateway("myapp.api.gateway.get_receivable_payable_report_v1", request_payload)
		self._assert_success(status_code, response, code="RECEIVABLE_PAYABLE_REPORT_FETCHED")

		business_status, business_response = self._call_gateway(
			"myapp.api.gateway.get_business_report_v1",
			request_payload,
		)
		self._assert_success(business_status, business_response, code="BUSINESS_REPORT_FETCHED")

		report_data = response["message"]["data"]
		business_data = business_response["message"]["data"]
		self.assertEqual(
			report_data["overview"]["receivable_outstanding_total"],
			business_data["overview"]["receivable_outstanding_total"],
		)
		self.assertEqual(
			report_data["overview"]["payable_outstanding_total"],
			business_data["overview"]["payable_outstanding_total"],
		)
		self.assertEqual(
			sorted(report_data["tables"]["receivable_summary"], key=lambda row: (row["outstanding_amount"], row["name"])),
			sorted(business_data["tables"]["receivable_summary"], key=lambda row: (row["outstanding_amount"], row["name"])),
		)
		self.assertEqual(
			sorted(report_data["tables"]["payable_summary"], key=lambda row: (row["outstanding_amount"], row["name"])),
			sorted(business_data["tables"]["payable_summary"], key=lambda row: (row["outstanding_amount"], row["name"])),
		)

	def test_list_cashflow_entries_v1_returns_paginated_rows(self):
		status_code, response = self._call_gateway(
			"myapp.api.gateway.list_cashflow_entries_v1",
			{
				"company": SALES_COMPANY,
				"date_from": "2026-03-01",
				"date_to": "2026-04-02",
				"page": 1,
				"page_size": 3,
			},
		)

		self._assert_success(status_code, response, code="CASHFLOW_ENTRIES_FETCHED")
		data = response["message"]["data"]
		self.assertIn("rows", data)
		self.assertIn("pagination", data)
		self.assertLessEqual(len(data["rows"]), 3)
		self.assertEqual(data["pagination"]["page"], 1)
		self.assertEqual(data["pagination"]["page_size"], 3)
		self.assertGreaterEqual(data["pagination"]["total_count"], len(data["rows"]))
		for row in data["rows"]:
			self.assertIn(row["direction"], {"in", "out", "transfer"})
			if row.get("posting_date"):
				self.assertGreaterEqual(row["posting_date"], "2026-03-01")
				self.assertLessEqual(row["posting_date"], "2026-04-02")

	def test_list_cashflow_entries_v1_rejects_invalid_date_range(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.list_cashflow_entries_v1",
			{
				"company": SALES_COMPANY,
				"date_from": "2026-04-03",
				"date_to": "2026-04-02",
				"page": 1,
				"page_size": 5,
			},
		)

		self._assert_validation_error(status_code, payload)

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
		_order_request, order_payload = self._create_purchase_order()
		order_name = order_payload["message"]["data"]["purchase_order"]
		_invoice_request, invoice_payload = self._create_purchase_invoice(order_name)
		invoice_name = invoice_payload["message"]["data"]["purchase_invoice"]
		_request, payload = self._create_purchase_return(
			invoice_name,
			source_doctype="Purchase Invoice",
		)
		data = payload["message"]["data"]
		self.assertIn("return_document", data)
		self.assertEqual(data["source_doctype"], "Purchase Invoice")
		self.assertEqual(data["source_name"], invoice_name)
		self.assertEqual(data["business_type"], "purchase")
		self.assertIn("summary", data)
		self.assertIn("next_actions", data)

	def test_process_purchase_return_idempotent_replay(self):
		_order_request, order_payload = self._create_purchase_order()
		order_name = order_payload["message"]["data"]["purchase_order"]
		_invoice_request, invoice_payload = self._create_purchase_invoice(order_name)
		invoice_name = invoice_payload["message"]["data"]["purchase_invoice"]
		request_id = self._unique_request_id("http-chain-purchase-return")
		first_request, first_payload = self._create_purchase_return(
			invoice_name,
			source_doctype="Purchase Invoice",
			request_id=request_id,
		)
		second_status, second_payload = self._call_gateway("myapp.api.gateway.process_purchase_return", first_request)
		self._assert_success(second_status, second_payload, code="PURCHASE_RETURN_CREATED")
		self.assertEqual(
			first_payload["message"]["data"]["return_document"],
			second_payload["message"]["data"]["return_document"],
		)

	def test_process_purchase_return_from_receipt_partial_success(self):
		_order_request, order_payload = self._create_purchase_order(price=500)
		order_name = order_payload["message"]["data"]["purchase_order"]
		order_item = self._get_first_item("Purchase Order", order_name)
		_receipt_request, receipt_payload = self._receive_purchase_order(
			order_name,
			receipt_items=[
				{
					"purchase_order_item": order_item["name"],
					"qty": 2,
					"price": 480,
				}
			],
		)
		receipt_name = receipt_payload["message"]["data"]["purchase_receipt"]
		receipt_item = self._get_first_item("Purchase Receipt", receipt_name)

		status_code, payload = self._call_gateway(
			"myapp.api.gateway.process_purchase_return",
			{
				"source_doctype": "Purchase Receipt",
				"source_name": receipt_name,
				"return_items": [
					{
						"item_code": receipt_item["item_code"],
						"qty": 1,
					}
				],
				"request_id": self._unique_request_id("http-partial-purchase-return-from-receipt"),
			},
		)

		self._assert_success(status_code, payload, code="PURCHASE_RETURN_CREATED")
		message_data = payload["message"]["data"]
		self.assertTrue(message_data["summary"]["is_partial_return"])
		self.assertEqual(message_data["source_doctype"], "Purchase Receipt")
		return_name = message_data["return_document"]
		return_doc = self._get_resource(message_data["return_doctype"], return_name)
		self.assertEqual(return_doc["items"][0]["qty"], -1.0)

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
		_order_request, order_payload = self._create_sales_order()
		order_name = order_payload["message"]["data"]["order"]
		_request, payload = self._submit_sales_delivery(order_name)
		self.assertIn("delivery_note", payload["message"]["data"])

	def test_submit_delivery_idempotent_replay(self):
		_order_request, order_payload = self._create_sales_order()
		order_name = order_payload["message"]["data"]["order"]
		request_id = self._unique_request_id("http-chain-delivery")
		first_request, first_payload = self._submit_sales_delivery(order_name, request_id=request_id)
		second_status, second_payload = self._call_gateway("myapp.api.gateway.submit_delivery", first_request)
		self._assert_success(second_status, second_payload, code="DELIVERY_SUBMITTED")
		self.assertEqual(
			first_payload["message"]["data"]["delivery_note"],
			second_payload["message"]["data"]["delivery_note"],
		)

	def test_submit_delivery_partial_success(self):
		order_status, order_payload = self._call_gateway(
			"myapp.api.gateway.create_order",
			{
				"customer": SALES_CUSTOMER,
				"items": [
					{
						"item_code": SALES_ITEM_CODE,
						"qty": 3,
						"warehouse": SALES_WAREHOUSE,
						"price": 900,
					}
				],
				"company": SALES_COMPANY,
				"request_id": self._unique_request_id("http-partial-sales-order"),
			},
		)
		self._assert_success(order_status, order_payload, code="ORDER_CREATED")
		order_name = order_payload["message"]["data"]["order"]
		order_item = self._get_first_item("Sales Order", order_name)

		status_code, payload = self._call_gateway(
			"myapp.api.gateway.submit_delivery",
			{
				"order_name": order_name,
				"delivery_items": [
					{
						"sales_order_item": order_item["name"],
						"qty": 2,
						"price": 880,
					}
				],
				"request_id": self._unique_request_id("http-partial-delivery"),
			},
		)

		self._assert_success(status_code, payload, code="DELIVERY_SUBMITTED")
		delivery_name = payload["message"]["data"]["delivery_note"]
		delivery_item = self._get_first_item("Delivery Note", delivery_name)
		self.assertEqual(delivery_item["qty"], 2.0)
		self.assertEqual(delivery_item["rate"], 880.0)

	def test_create_sales_invoice_success(self):
		_order_request, order_payload = self._create_sales_order()
		order_name = order_payload["message"]["data"]["order"]
		_request, payload = self._create_sales_invoice(order_name)
		self.assertIn("sales_invoice", payload["message"]["data"])

	def test_create_sales_invoice_idempotent_replay(self):
		_order_request, order_payload = self._create_sales_order()
		order_name = order_payload["message"]["data"]["order"]
		request_id = self._unique_request_id("http-chain-sales-invoice")
		first_request, first_payload = self._create_sales_invoice(order_name, request_id=request_id)
		second_status, second_payload = self._call_gateway("myapp.api.gateway.create_sales_invoice", first_request)
		self._assert_success(second_status, second_payload, code="SALES_INVOICE_CREATED")
		self.assertEqual(
			first_payload["message"]["data"]["sales_invoice"],
			second_payload["message"]["data"]["sales_invoice"],
		)

	def test_create_sales_invoice_partial_success(self):
		_order_request, order_payload = self._create_sales_order(qty=3, price=900)
		order_name = order_payload["message"]["data"]["order"]
		order_item = self._get_first_item("Sales Order", order_name)

		status_code, payload = self._call_gateway(
			"myapp.api.gateway.create_sales_invoice",
			{
				"source_name": order_name,
				"invoice_items": [
					{
						"sales_order_item": order_item["name"],
						"qty": 1,
						"price": 870,
					}
				],
				"request_id": self._unique_request_id("http-partial-sales-invoice"),
			},
		)

		self._assert_success(status_code, payload, code="SALES_INVOICE_CREATED")
		invoice_name = payload["message"]["data"]["sales_invoice"]
		invoice_item = self._get_first_item("Sales Invoice", invoice_name)
		self.assertEqual(invoice_item["qty"], 1.0)
		self.assertEqual(invoice_item["rate"], 870.0)

	def test_update_payment_status_success(self):
		_order_request, order_payload = self._create_sales_order()
		order_name = order_payload["message"]["data"]["order"]
		_invoice_request, invoice_payload = self._create_sales_invoice(order_name)
		invoice_name = invoice_payload["message"]["data"]["sales_invoice"]
		_request, payload = self._record_sales_payment(invoice_name)
		self.assertIn("payment_entry", payload["message"]["data"])

	def test_update_payment_status_idempotent_replay(self):
		_order_request, order_payload = self._create_sales_order()
		order_name = order_payload["message"]["data"]["order"]
		_invoice_request, invoice_payload = self._create_sales_invoice(order_name)
		invoice_name = invoice_payload["message"]["data"]["sales_invoice"]
		request_id = self._unique_request_id("http-chain-payment")
		first_request, first_payload = self._record_sales_payment(invoice_name, request_id=request_id)
		second_status, second_payload = self._call_gateway("myapp.api.gateway.update_payment_status", first_request)
		self._assert_success(second_status, second_payload, code="PAYMENT_RECORDED")
		self.assertEqual(
			first_payload["message"]["data"]["payment_entry"],
			second_payload["message"]["data"]["payment_entry"],
		)

	def test_update_payment_status_writeoff_success(self):
		_order_request, order_payload = self._create_sales_order(price=1000)
		order_name = order_payload["message"]["data"]["order"]
		_invoice_request, invoice_payload = self._create_sales_invoice(order_name)
		invoice_name = invoice_payload["message"]["data"]["sales_invoice"]

		_request, payload = self._record_sales_payment(
			invoice_name,
			paid_amount=900,
			settlement_mode="writeoff",
			writeoff_reason="HTTP 测试优惠结清",
		)

		message_data = payload["message"]["data"]
		self.assertEqual(message_data["settlement_mode"], "writeoff")
		self.assertEqual(message_data["writeoff_amount"], 100.0)

		invoice_doc = self._get_resource("Sales Invoice", invoice_name)
		self.assertEqual(float(invoice_doc["outstanding_amount"]), 0.0)
		self.assertEqual(invoice_doc["status"], "Paid")

	def test_update_payment_status_overpayment_success(self):
		_order_request, order_payload = self._create_sales_order(price=1000)
		order_name = order_payload["message"]["data"]["order"]
		_invoice_request, invoice_payload = self._create_sales_invoice(order_name)
		invoice_name = invoice_payload["message"]["data"]["sales_invoice"]

		_request, payload = self._record_sales_payment(
			invoice_name,
			paid_amount=1100,
		)

		message_data = payload["message"]["data"]
		self.assertEqual(message_data["unallocated_amount"], 100.0)

		invoice_doc = self._get_resource("Sales Invoice", invoice_name)
		self.assertEqual(float(invoice_doc["outstanding_amount"]), 0.0)
		self.assertEqual(invoice_doc["status"], "Paid")

	def test_process_sales_return_success(self):
		_order_request, order_payload = self._create_sales_order()
		order_name = order_payload["message"]["data"]["order"]
		_invoice_request, invoice_payload = self._create_sales_invoice(order_name)
		invoice_name = invoice_payload["message"]["data"]["sales_invoice"]
		_request, payload = self._create_sales_return(
			invoice_name,
			source_doctype="Sales Invoice",
		)
		data = payload["message"]["data"]
		self.assertIn("return_document", data)
		self.assertEqual(data["source_doctype"], "Sales Invoice")
		self.assertEqual(data["source_name"], invoice_name)
		self.assertEqual(data["business_type"], "sales")
		self.assertIn("summary", data)
		self.assertIn("next_actions", data)
		self.assertEqual(data["next_actions"]["suggested_next_action"], "review_refund")

	def test_get_return_source_context_sales_invoice_success(self):
		_order_request, order_payload = self._create_sales_order()
		order_name = order_payload["message"]["data"]["order"]
		_invoice_request, invoice_payload = self._create_sales_invoice(order_name)
		invoice_name = invoice_payload["message"]["data"]["sales_invoice"]

		_request, payload = self._get_return_source_context("Sales Invoice", invoice_name)
		data = payload["message"]["data"]
		self.assertEqual(data["business_type"], "sales")
		self.assertEqual(data["source_doctype"], "Sales Invoice")
		self.assertEqual(data["source_name"], invoice_name)
		self.assertEqual(data["actions"]["detail_submit_key"], "sales_invoice_item")
		self.assertTrue(data["items"])

	def test_get_return_source_context_sales_invoice_includes_item_specification(self):
		specification = f"退货销售规格-{time.time_ns()}"
		create_status, create_payload = self._post_method(
			"myapp.api.gateway.create_product_and_stock",
			{
				"item_name": f"HTTP-退货销售商品-{time.time_ns()}",
				"default_warehouse": SALES_WAREHOUSE,
				"opening_qty": 2,
				"standard_rate": 16,
				"barcode": f"RETSALE{time.time_ns()}"[-16:],
				"specification": specification,
				"request_id": self._unique_request_id("http-return-sales-spec"),
			},
		)
		self._assert_success(create_status, create_payload, code="PRODUCT_CREATED")
		item_code = create_payload["message"]["data"]["item_code"]

		_order_request, order_payload = self._create_sales_order(item_code=item_code, price=16)
		order_name = order_payload["message"]["data"]["order"]
		_invoice_request, invoice_payload = self._create_sales_invoice(order_name)
		invoice_name = invoice_payload["message"]["data"]["sales_invoice"]

		_request, payload = self._get_return_source_context("Sales Invoice", invoice_name)
		rows = payload["message"]["data"]["items"]
		self.assertTrue(rows)
		self.assertEqual(rows[0]["specification"], specification)

	def test_get_return_source_context_delivery_note_success(self):
		_order_request, order_payload = self._create_sales_order()
		order_name = order_payload["message"]["data"]["order"]
		_delivery_request, delivery_payload = self._submit_sales_delivery(order_name)
		delivery_name = delivery_payload["message"]["data"]["delivery_note"]

		_request, payload = self._get_return_source_context("Delivery Note", delivery_name)
		data = payload["message"]["data"]
		self.assertEqual(data["business_type"], "sales")
		self.assertEqual(data["source_doctype"], "Delivery Note")
		self.assertEqual(data["source_name"], delivery_name)
		self.assertEqual(data["actions"]["detail_submit_key"], "delivery_note_item")
		self.assertTrue(data["items"])

	def test_get_return_source_context_purchase_invoice_success(self):
		_order_request, order_payload = self._create_purchase_order()
		order_name = order_payload["message"]["data"]["purchase_order"]
		_invoice_request, invoice_payload = self._create_purchase_invoice(order_name)
		invoice_name = invoice_payload["message"]["data"]["purchase_invoice"]

		_request, payload = self._get_return_source_context("Purchase Invoice", invoice_name)
		data = payload["message"]["data"]
		self.assertEqual(data["business_type"], "purchase")
		self.assertEqual(data["source_doctype"], "Purchase Invoice")
		self.assertEqual(data["source_name"], invoice_name)
		self.assertEqual(data["actions"]["detail_submit_key"], "purchase_invoice_item")
		self.assertTrue(data["items"])

	def test_get_return_source_context_purchase_receipt_success(self):
		_order_request, order_payload = self._create_purchase_order()
		order_name = order_payload["message"]["data"]["purchase_order"]
		_receipt_request, receipt_payload = self._receive_purchase_order(order_name)
		receipt_name = receipt_payload["message"]["data"]["purchase_receipt"]

		_request, payload = self._get_return_source_context("Purchase Receipt", receipt_name)
		data = payload["message"]["data"]
		self.assertEqual(data["business_type"], "purchase")
		self.assertEqual(data["source_doctype"], "Purchase Receipt")
		self.assertEqual(data["source_name"], receipt_name)
		self.assertEqual(data["actions"]["detail_submit_key"], "purchase_receipt_item")
		self.assertTrue(data["items"])

	def test_get_return_source_context_purchase_receipt_includes_item_specification(self):
		specification = f"退货采购规格-{time.time_ns()}"
		create_status, create_payload = self._post_method(
			"myapp.api.gateway.create_product_and_stock",
			{
				"item_name": f"HTTP-退货采购商品-{time.time_ns()}",
				"default_warehouse": PURCHASE_WAREHOUSE,
				"opening_qty": 1,
				"standard_rate": 12,
				"barcode": f"RETPUR{time.time_ns()}"[-16:],
				"specification": specification,
				"request_id": self._unique_request_id("http-return-purchase-spec"),
			},
		)
		self._assert_success(create_status, create_payload, code="PRODUCT_CREATED")
		item_code = create_payload["message"]["data"]["item_code"]

		_order_request, order_payload = self._create_purchase_order(item_code=item_code, price=12)
		order_name = order_payload["message"]["data"]["purchase_order"]
		_receipt_request, receipt_payload = self._receive_purchase_order(order_name)
		receipt_name = receipt_payload["message"]["data"]["purchase_receipt"]

		_request, payload = self._get_return_source_context("Purchase Receipt", receipt_name)
		rows = payload["message"]["data"]["items"]
		self.assertTrue(rows)
		self.assertEqual(rows[0]["specification"], specification)

	def test_process_sales_return_after_paid_invoice_requires_followup_refund(self):
		_order_request, order_payload = self._create_sales_order(price=900)
		order_name = order_payload["message"]["data"]["order"]
		_invoice_request, invoice_payload = self._create_sales_invoice(order_name)
		invoice_name = invoice_payload["message"]["data"]["sales_invoice"]
		self._record_sales_payment(invoice_name, paid_amount=900)

		_request, payload = self._create_sales_return(invoice_name, source_doctype="Sales Invoice")
		data = payload["message"]["data"]
		self.assertEqual(data["next_actions"]["suggested_next_action"], "review_refund")

		invoice_doc = self._get_resource("Sales Invoice", invoice_name)
		self.assertEqual(float(invoice_doc["outstanding_amount"]), 0.0)
		self.assertEqual(invoice_doc["status"], "Paid")

	def test_process_purchase_return_after_paid_invoice_requires_followup_supplier_refund(self):
		_order_request, order_payload = self._create_purchase_order(price=10)
		order_name = order_payload["message"]["data"]["purchase_order"]
		_invoice_request, invoice_payload = self._create_purchase_invoice(order_name)
		invoice_name = invoice_payload["message"]["data"]["purchase_invoice"]
		self._record_supplier_payment(invoice_name, paid_amount=50)

		_request, payload = self._create_purchase_return(invoice_name, source_doctype="Purchase Invoice")
		data = payload["message"]["data"]
		self.assertEqual(data["next_actions"]["suggested_next_action"], "review_supplier_refund")

		invoice_doc = self._get_resource("Purchase Invoice", invoice_name)
		self.assertEqual(float(invoice_doc["outstanding_amount"]), 0.0)
		self.assertEqual(invoice_doc["status"], "Paid")

	def test_process_sales_return_idempotent_replay(self):
		_order_request, order_payload = self._create_sales_order()
		order_name = order_payload["message"]["data"]["order"]
		_invoice_request, invoice_payload = self._create_sales_invoice(order_name)
		invoice_name = invoice_payload["message"]["data"]["sales_invoice"]
		request_id = self._unique_request_id("http-chain-sales-return")
		first_request, first_payload = self._create_sales_return(
			invoice_name,
			source_doctype="Sales Invoice",
			request_id=request_id,
		)
		second_status, second_payload = self._call_gateway("myapp.api.gateway.process_sales_return", first_request)
		self._assert_success(second_status, second_payload, code="SALES_RETURN_CREATED")
		self.assertEqual(
			first_payload["message"]["data"]["return_document"],
			second_payload["message"]["data"]["return_document"],
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
