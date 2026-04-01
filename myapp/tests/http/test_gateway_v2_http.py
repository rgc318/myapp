import time
from concurrent.futures import ThreadPoolExecutor

from .test_gateway_http import (
	BASE_URL,
	GatewayHttpTestCase,
	SALES_COMPANY,
	SALES_CUSTOMER,
	SALES_WAREHOUSE,
)


class GatewayV2HttpTestCase(GatewayHttpTestCase):
	def _build_product_payload(
		self,
		*,
		item_name: str | None = None,
		opening_qty: float = 1,
		standard_rate: float = 9,
		warehouse: str | None = None,
		barcode: str | None = None,
		request_id: str | None = None,
		description: str = "HTTP v2 test product",
		nickname: str | None = None,
	):
		unique_suffix = str(time.time_ns())
		payload = {
			"item_name": item_name or f"HTTP-V2-商品-{unique_suffix}",
			"default_warehouse": warehouse or SALES_WAREHOUSE,
			"opening_qty": opening_qty,
			"standard_rate": standard_rate,
			"barcode": barcode or f"HTTPV2{unique_suffix[-10:]}",
			"description": description,
			"image": "/files/test-product.png",
			"request_id": request_id or self._unique_request_id("http-v2-product"),
		}
		if nickname is not None:
			payload["nickname"] = nickname
		return payload

	def _post_create_product_and_stock(self, payload: dict):
		status_code, response = self._post_method("myapp.api.gateway.create_product_and_stock", payload)
		self._record_response(
			test_name=self._testMethodName,
			method_path="myapp.api.gateway.create_product_and_stock",
			request_payload=payload,
			status_code=status_code,
			payload=response,
		)
		return status_code, response

	def _create_sales_order_v2(
		self,
		*,
		item_code=None,
		qty: float = 1,
		price: float = 900,
		request_id: str | None = None,
	):
		payload = {
			"customer": SALES_CUSTOMER,
			"items": [
				{
					"item_code": item_code or "SKU010",
					"qty": qty,
					"warehouse": SALES_WAREHOUSE,
					"price": price,
				}
			],
			"company": SALES_COMPANY,
			"immediate": 0,
			"request_id": request_id or self._unique_request_id("http-v2-create-order"),
			"customer_info": {
				"contact_display_name": "张三",
				"contact_phone": "13800138000",
				"contact_email": "zhangsan@example.com",
			},
			"shipping_info": {
				"receiver_name": "李四",
				"receiver_phone": "13900139000",
				"shipping_address_text": "上海市浦东新区测试路 88 号 5 楼",
			},
			"remarks": "v2 HTTP test order",
		}
		status_code, response = self._call_gateway("myapp.api.gateway.create_order_v2", payload)
		self._assert_success(status_code, response, code="ORDER_V2_CREATED")
		return payload, response

	def _update_sales_order_v2(self, order_name: str, **kwargs):
		payload = {
			"order_name": order_name,
			"request_id": kwargs.pop("request_id", self._unique_request_id("http-v2-update-order")),
		}
		payload.update(kwargs)
		status_code, response = self._call_gateway("myapp.api.gateway.update_order_v2", payload)
		self._assert_success(status_code, response, code="ORDER_V2_UPDATED")
		return payload, response

	def _update_sales_order_items_v2(self, order_name: str, items: list[dict], **kwargs):
		payload = {
			"order_name": order_name,
			"items": items,
			"request_id": kwargs.pop("request_id", self._unique_request_id("http-v2-update-order-items")),
		}
		payload.update(kwargs)
		status_code, response = self._call_gateway("myapp.api.gateway.update_order_items_v2", payload)
		self._assert_success(status_code, response, code="ORDER_ITEMS_V2_UPDATED")
		return payload, response

	def _cancel_sales_order_v2(self, order_name: str, **kwargs):
		payload = {
			"order_name": order_name,
			"request_id": kwargs.pop("request_id", self._unique_request_id("http-v2-cancel-order")),
		}
		payload.update(kwargs)
		status_code, response = self._call_gateway("myapp.api.gateway.cancel_order_v2", payload)
		self._assert_success(status_code, response, code="ORDER_V2_CANCELLED")
		return payload, response

	def _create_product_and_stock(
		self,
		*,
		item_name: str | None = None,
		opening_qty: float = 1,
		standard_rate: float = 9,
		warehouse: str | None = None,
	):
		payload = self._build_product_payload(
			item_name=item_name,
			opening_qty=opening_qty,
			standard_rate=standard_rate,
			warehouse=warehouse,
		)
		status_code, response = self._post_create_product_and_stock(payload)
		self._assert_success(status_code, response, code="PRODUCT_CREATED")
		return payload, response

	def _get_product_detail_v2(self, item_code: str, **kwargs):
		payload = {"item_code": item_code}
		payload.update(kwargs)
		status_code, response = self._call_gateway("myapp.api.gateway.get_product_detail_v2", payload)
		self._assert_success(status_code, response, code="PRODUCT_DETAIL_FETCHED")
		return payload, response

	def _update_product_v2(self, item_code: str, **kwargs):
		payload = {
			"item_code": item_code,
			"request_id": kwargs.pop("request_id", self._unique_request_id("http-v2-update-product")),
		}
		payload.update(kwargs)
		status_code, response = self._call_gateway("myapp.api.gateway.update_product_v2", payload)
		self._assert_success(status_code, response, code="PRODUCT_UPDATED")
		return payload, response

	def test_search_product_v2_success(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.search_product_v2",
			{
				"search_key": "SKU",
				"search_fields": ["item_code", "item_name"],
				"sort_by": "name",
				"sort_order": "asc",
				"limit": 5,
			},
		)

		self._assert_success(status_code, payload, code="PRODUCTS_FETCHED")
		self.assertIn("data", payload["message"])
		self.assertIn("meta", payload["message"])
		self.assertIn("filters", payload["message"]["meta"])

	def test_create_product_and_stock_success(self):
		_request, payload = self._create_product_and_stock()
		data = payload["message"]["data"]

		self.assertTrue(data["item_code"])
		self.assertEqual(data["warehouse"], SALES_WAREHOUSE)
		self.assertGreaterEqual(data["qty"], 1)

	def test_create_product_and_stock_then_search_product_v2_finds_new_item(self):
		create_request, create_payload = self._create_product_and_stock(standard_rate=15)
		item_code = create_payload["message"]["data"]["item_code"]

		status_code, payload = self._call_gateway(
			"myapp.api.gateway.search_product_v2",
			{
				"search_key": item_code,
				"search_fields": ["item_code"],
				"in_stock_only": 1,
				"sort_by": "price",
				"sort_order": "desc",
				"limit": 5,
			},
		)

		self._assert_success(status_code, payload, code="PRODUCTS_FETCHED")
		items = payload["message"]["data"]
		self.assertTrue(any(row["item_code"] == item_code for row in items), create_request)

	def test_search_product_v2_supports_barcode_and_nickname(self):
		create_request, create_payload = self._create_product_and_stock()
		item_code = create_payload["message"]["data"]["item_code"]
		barcode = create_request["barcode"]

		barcode_status, barcode_payload = self._call_gateway(
			"myapp.api.gateway.search_product_v2",
			{
				"search_key": barcode,
				"search_fields": ["barcode"],
				"limit": 5,
			},
		)
		self._assert_success(barcode_status, barcode_payload, code="PRODUCTS_FETCHED")
		self.assertTrue(any(row["item_code"] == item_code for row in barcode_payload["message"]["data"]))

		nickname = f"HTTP 昵称 {time.time_ns()}"
		nickname_create_request = self._build_product_payload(nickname=nickname)
		nickname_create_status, nickname_create_payload = self._post_create_product_and_stock(nickname_create_request)
		self._assert_success(nickname_create_status, nickname_create_payload, code="PRODUCT_CREATED")
		nickname_item_code = nickname_create_payload["message"]["data"]["item_code"]
		self.assertEqual(nickname_create_payload["message"]["data"]["nickname"], nickname)

		nickname_status, nickname_payload = self._call_gateway(
			"myapp.api.gateway.search_product_v2",
			{
				"search_key": nickname,
				"search_fields": ["nickname"],
				"in_stock_only": 1,
				"sort_by": "modified",
				"sort_order": "desc",
				"limit": 10,
			},
		)
		self._assert_success(nickname_status, nickname_payload, code="PRODUCTS_FETCHED")
		self.assertTrue(any(row["item_code"] == nickname_item_code for row in nickname_payload["message"]["data"]))

	def test_get_product_detail_v2_success(self):
		create_request = self._build_product_payload(nickname=f"详情昵称 {time.time_ns()}", standard_rate=16)
		create_status, create_payload = self._post_create_product_and_stock(create_request)
		self._assert_success(create_status, create_payload, code="PRODUCT_CREATED")
		item_code = create_payload["message"]["data"]["item_code"]

		_detail_request, detail_payload = self._get_product_detail_v2(item_code, warehouse=SALES_WAREHOUSE)
		data = detail_payload["message"]["data"]
		self.assertEqual(data["item_code"], item_code)
		self.assertEqual(data["nickname"], create_request["nickname"])
		self.assertEqual(data["image"], "/files/test-product.png")
		self.assertEqual(data["warehouse"], SALES_WAREHOUSE)
		self.assertGreaterEqual(float(data["price"]), 0)

	def test_update_product_v2_success(self):
		create_request, create_payload = self._create_product_and_stock(
			item_name=f"HTTP-V2-更新商品-{time.time_ns()}",
			standard_rate=12,
		)
		item_code = create_payload["message"]["data"]["item_code"]

		new_nickname = f"更新昵称 {time.time_ns()}"
		_update_request, update_payload = self._update_product_v2(
			item_code,
			item_name=f"{item_code}-已更新",
			description="更新后的商品描述",
			nickname=new_nickname,
			image="/files/test-product.png",
			standard_rate=19,
			warehouse=SALES_WAREHOUSE,
		)

		update_data = update_payload["message"]["data"]
		self.assertEqual(update_data["item_code"], item_code)
		self.assertEqual(update_data["nickname"], new_nickname)
		self.assertEqual(update_data["description"], "更新后的商品描述")
		self.assertEqual(update_data["price"], 19.0)

		_detail_request, detail_payload = self._get_product_detail_v2(item_code, warehouse=SALES_WAREHOUSE)
		detail_data = detail_payload["message"]["data"]
		self.assertEqual(detail_data["nickname"], new_nickname)
		self.assertEqual(detail_data["description"], "更新后的商品描述")
		self.assertEqual(detail_data["price"], 19.0)

	def test_get_sales_order_detail_success(self):
		_order_request, order_payload = self._create_sales_order()
		order_name = order_payload["message"]["data"]["order"]

		status_code, payload = self._call_gateway(
			"myapp.api.gateway.get_sales_order_detail",
			{"order_name": order_name},
		)

		self._assert_success(status_code, payload, code="ORDER_DETAIL_FETCHED")
		data = payload["message"]["data"]
		self.assertEqual(data["order_name"], order_name)
		self.assertIn("customer", data)
		self.assertIn("shipping", data)
		self.assertIn("fulfillment", data)
		self.assertIn("payment", data)
		self.assertIn("completion", data)
		self.assertIn("actions", data)

	def test_create_order_v2_success(self):
		_request, payload = self._create_sales_order_v2()
		self.assertIn("order", payload["message"]["data"])
		self.assertIn("snapshot", payload["message"]["data"])

	def test_create_order_v2_idempotent_replay(self):
		request_id = self._unique_request_id("http-v2-order-idem")
		payload, first_response = self._create_sales_order_v2(request_id=request_id)
		second_status, second_response = self._call_gateway(
			"myapp.api.gateway.create_order_v2",
			payload,
		)
		self._assert_success(second_status, second_response, code="ORDER_V2_CREATED")
		self.assertEqual(
			first_response["message"]["data"]["order"],
			second_response["message"]["data"]["order"],
		)

	def test_create_order_v2_detail_contains_snapshot(self):
		_request, order_payload = self._create_sales_order_v2()
		order_name = order_payload["message"]["data"]["order"]
		snapshot = order_payload["message"]["data"]["snapshot"]
		self.assertEqual(snapshot["customer"]["contact_phone"], "13800138000")
		self.assertEqual(snapshot["shipping"]["receiver_phone"], "13900139000")
		self.assertEqual(snapshot["shipping"]["shipping_address_text"], "上海市浦东新区测试路 88 号 5 楼")

		status_code, detail_payload = self._call_gateway(
			"myapp.api.gateway.get_sales_order_detail",
			{"order_name": order_name},
		)
		self._assert_success(status_code, detail_payload, code="ORDER_DETAIL_FETCHED")
		data = detail_payload["message"]["data"]
		self.assertEqual(data["shipping"]["shipping_address_text"], "上海市浦东新区测试路 88 号 5 楼")

	def test_update_order_v2_success(self):
		_order_request, order_payload = self._create_sales_order_v2()
		order_name = order_payload["message"]["data"]["order"]

		_update_request, update_payload = self._update_sales_order_v2(
			order_name,
			delivery_date="2026-03-25",
			remarks="updated via v2 http",
			customer_info={
				"contact_display_name": "王五",
				"contact_phone": "13600136000",
			},
			shipping_info={
				"receiver_name": "赵六",
				"receiver_phone": "13700137000",
				"shipping_address_text": "北京市朝阳区移动端更新路 66 号",
			},
		)

		self.assertEqual(update_payload["message"]["data"]["order"], order_name)
		self.assertEqual(update_payload["message"]["data"]["snapshot"]["applied"]["contact_display"], "王五")

		detail_status, detail_payload = self._call_gateway(
			"myapp.api.gateway.get_sales_order_detail",
			{"order_name": order_name},
		)
		self._assert_success(detail_status, detail_payload, code="ORDER_DETAIL_FETCHED")
		data = detail_payload["message"]["data"]
		self.assertEqual(data["meta"]["delivery_date"], "2026-03-25")
		self.assertEqual(data["shipping"]["shipping_address_text"], "北京市朝阳区移动端更新路 66 号")

	def test_update_order_items_v2_success(self):
		_order_request, order_payload = self._create_sales_order_v2()
		order_name = order_payload["message"]["data"]["order"]

		_update_request, update_payload = self._update_sales_order_items_v2(
			order_name,
			items=[
				{
					"item_code": "SKU010",
					"qty": 2,
					"warehouse": SALES_WAREHOUSE,
					"price": 300,
				}
			],
		)

		updated_order_name = update_payload["message"]["data"]["order"]
		self.assertNotEqual(updated_order_name, "")
		self.assertEqual(update_payload["message"]["data"]["source_order"], order_name)
		self.assertEqual(len(update_payload["message"]["data"]["items"]), 1)
		self.assertEqual(update_payload["message"]["data"]["items"][0]["item_code"], "SKU010")

		detail_status, detail_payload = self._call_gateway(
			"myapp.api.gateway.get_sales_order_detail",
			{"order_name": updated_order_name},
		)
		self._assert_success(detail_status, detail_payload, code="ORDER_DETAIL_FETCHED")
		data = detail_payload["message"]["data"]
		self.assertEqual(len(data["items"]), 1)
		self.assertEqual(data["items"][0]["item_code"], "SKU010")
		self.assertEqual(data["items"][0]["qty"], 2.0)

	def test_cancel_order_v2_success(self):
		_order_request, order_payload = self._create_sales_order_v2()
		order_name = order_payload["message"]["data"]["order"]

		_cancel_request, cancel_payload = self._cancel_sales_order_v2(order_name)
		data = cancel_payload["message"]["data"]
		self.assertEqual(data["order"], order_name)
		self.assertEqual(data["document_status"], "cancelled")
		self.assertEqual(data["detail"]["order_name"], order_name)
		self.assertEqual(data["detail"]["document_status"], "cancelled")

	def test_get_customer_sales_context_success(self):
		status_code, payload = self._call_gateway(
			"myapp.api.gateway.get_customer_sales_context",
			{"customer": SALES_CUSTOMER},
		)

		self._assert_success(status_code, payload, code="CUSTOMER_SALES_CONTEXT_FETCHED")
		data = payload["message"]["data"]
		self.assertEqual(data["customer"]["name"], SALES_CUSTOMER)
		self.assertIn("default_contact", data)
		self.assertIn("default_address", data)
		self.assertIn("recent_addresses", data)
		self.assertIn("suggestions", data)
		self.assertIsInstance(data["recent_addresses"], list)

	def test_get_sales_order_status_summary_success(self):
		self._create_sales_order()

		status_code, payload = self._call_gateway(
			"myapp.api.gateway.get_sales_order_status_summary",
			{
				"customer": SALES_CUSTOMER,
				"company": SALES_COMPANY,
				"limit": 5,
			},
		)

		self._assert_success(status_code, payload, code="ORDER_SUMMARY_FETCHED")
		data = payload["message"]["data"]
		self.assertIsInstance(data, list)
		self.assertTrue(data)
		self.assertIn("order_name", data[0])
		self.assertIn("payment", data[0])
		self.assertIn("completion", data[0])

	def test_search_sales_orders_v2_hides_cancelled_order_by_default(self):
		_request, order_payload = self._create_sales_order_v2()
		order_name = order_payload["message"]["data"]["order"]
		self._cancel_sales_order_v2(order_name)

		status_code, payload = self._call_gateway(
			"myapp.api.gateway.search_sales_orders_v2",
			{
				"search_key": order_name,
				"company": SALES_COMPANY,
				"status_filter": "all",
				"exclude_cancelled": 1,
				"limit": 20,
			},
		)

		self._assert_success(status_code, payload, code="SALES_ORDER_SEARCHED")
		data = payload["message"]["data"]
		self.assertEqual(data["items"], [])
		self.assertGreaterEqual(data["summary"]["cancelled_count"], 1)

	def test_search_sales_orders_v2_can_query_cancelled_orders(self):
		_request, order_payload = self._create_sales_order_v2()
		order_name = order_payload["message"]["data"]["order"]
		self._cancel_sales_order_v2(order_name)

		status_code, payload = self._call_gateway(
			"myapp.api.gateway.search_sales_orders_v2",
			{
				"search_key": order_name,
				"company": SALES_COMPANY,
				"status_filter": "cancelled",
				"exclude_cancelled": 0,
				"limit": 20,
			},
		)

		self._assert_success(status_code, payload, code="SALES_ORDER_SEARCHED")
		items = payload["message"]["data"]["items"]
		self.assertTrue(any(row["order_name"] == order_name for row in items))

	def test_search_sales_orders_v2_finds_order_by_exact_name_keyword(self):
		_request, order_payload = self._create_sales_order_v2()
		order_name = order_payload["message"]["data"]["order"]

		status_code, payload = self._call_gateway(
			"myapp.api.gateway.search_sales_orders_v2",
			{
				"search_key": order_name,
				"company": SALES_COMPANY,
				"status_filter": "unfinished",
				"exclude_cancelled": 1,
				"limit": 20,
			},
		)

		self._assert_success(status_code, payload, code="SALES_ORDER_SEARCHED")
		items = payload["message"]["data"]["items"]
		self.assertTrue(any(row["order_name"] == order_name for row in items))

	def test_create_product_and_stock_idempotent_replay(self):
		request_id = self._unique_request_id("http-v2-product-idem")
		payload = self._build_product_payload(request_id=request_id)

		first_status, first_payload = self._post_create_product_and_stock(payload)
		self._assert_success(first_status, first_payload, code="PRODUCT_CREATED")

		second_status, second_payload = self._call_gateway(
			"myapp.api.gateway.create_product_and_stock",
			payload,
		)
		self._assert_success(second_status, second_payload, code="PRODUCT_CREATED")
		self.assertEqual(
			first_payload["message"]["data"]["item_code"],
			second_payload["message"]["data"]["item_code"],
		)
		self.assertEqual(
			first_payload["message"]["data"]["stock_entry"],
			second_payload["message"]["data"]["stock_entry"],
		)

	def test_create_product_and_stock_same_request_id_with_different_data_returns_first_result(self):
		request_id = self._unique_request_id("http-v2-product-diffdata")
		first_payload = self._build_product_payload(
			item_name=f"HTTP-V2-幂等A-{time.time_ns()}",
			opening_qty=2,
			standard_rate=11,
			request_id=request_id,
		)
		second_payload = self._build_product_payload(
			item_name=f"HTTP-V2-幂等B-{time.time_ns()}",
			opening_qty=8,
			standard_rate=29,
			request_id=request_id,
		)

		first_status, first_response = self._post_create_product_and_stock(first_payload)
		self._assert_success(first_status, first_response, code="PRODUCT_CREATED")

		second_status, second_response = self._call_gateway(
			"myapp.api.gateway.create_product_and_stock",
			second_payload,
		)
		self._assert_success(second_status, second_response, code="PRODUCT_CREATED")
		self.assertEqual(
			first_response["message"]["data"]["item_code"],
			second_response["message"]["data"]["item_code"],
		)
		self.assertEqual(
			first_response["message"]["data"]["stock_entry"],
			second_response["message"]["data"]["stock_entry"],
		)

	def test_create_product_and_stock_concurrent_same_request_id_returns_single_item(self):
		request_id = self._unique_request_id("http-v2-product-concurrent")
		payload = self._build_product_payload(
			item_name=f"HTTP-V2-并发-{time.time_ns()}",
			request_id=request_id,
		)

		def worker(index: int):
			status_code, response_payload = self._post_method(
				"myapp.api.gateway.create_product_and_stock",
				payload,
			)
			self._record_response(
				test_name=f"{self._testMethodName}_worker_{index}",
				method_path="myapp.api.gateway.create_product_and_stock",
				request_payload=payload,
				status_code=status_code,
				payload=response_payload,
			)
			return (
				status_code,
				response_payload["message"]["data"]["item_code"],
				response_payload["message"]["data"]["stock_entry"],
			)

		with ThreadPoolExecutor(max_workers=4) as executor:
			results = list(executor.map(worker, range(4)))

		for status_code, _item_code, _stock_entry in results:
			self.assertEqual(status_code, 200)

		self.assertEqual(len({item_code for _status, item_code, _stock_entry in results}), 1)
		self.assertEqual(len({stock_entry for _status, _item_code, stock_entry in results}), 1)

	def test_create_product_and_stock_negative_qty_validation_error(self):
		payload = self._build_product_payload(opening_qty=-1)
		status_code, response = self._post_create_product_and_stock(payload)
		self._assert_validation_error(status_code, response)

	def test_create_product_and_stock_duplicate_barcode_validation_error(self):
		created_request, _created_payload = self._create_product_and_stock()
		payload = self._build_product_payload(
			item_name=f"HTTP-V2-重复条码-{time.time_ns()}",
			barcode=created_request["barcode"],
		)
		status_code, response = self._post_create_product_and_stock(payload)
		self._assert_validation_error(status_code, response)

	def test_v2_sales_flow_chain_smoke(self):
		product_request, product_payload = self._create_product_and_stock(opening_qty=3, standard_rate=12)
		item_code = product_payload["message"]["data"]["item_code"]

		search_status, search_payload = self._call_gateway(
			"myapp.api.gateway.search_product_v2",
			{
				"search_key": item_code,
				"search_fields": ["item_code", "barcode"],
				"in_stock_only": 1,
				"limit": 5,
			},
		)
		self._assert_success(search_status, search_payload, code="PRODUCTS_FETCHED")
		self.assertTrue(any(row["item_code"] == item_code for row in search_payload["message"]["data"]), product_request)

		order_status, order_payload = self._call_gateway(
			"myapp.api.gateway.create_order",
			{
				"customer": SALES_CUSTOMER,
				"items": [
					{
						"item_code": item_code,
						"qty": 1,
						"warehouse": SALES_WAREHOUSE,
						"price": 12,
					}
				],
				"company": SALES_COMPANY,
				"immediate": 0,
				"request_id": self._unique_request_id("http-v2-sales-order"),
			},
		)
		self._assert_success(order_status, order_payload, code="ORDER_CREATED")
		order_name = order_payload["message"]["data"]["order"]

		detail_status, detail_payload = self._call_gateway(
			"myapp.api.gateway.get_sales_order_detail",
			{"order_name": order_name},
		)
		self._assert_success(detail_status, detail_payload, code="ORDER_DETAIL_FETCHED")
		self.assertEqual(detail_payload["message"]["data"]["order_name"], order_name)

		summary_status, summary_payload = self._call_gateway(
			"myapp.api.gateway.get_sales_order_status_summary",
			{
				"customer": SALES_CUSTOMER,
				"company": SALES_COMPANY,
				"limit": 10,
			},
		)
		self._assert_success(summary_status, summary_payload, code="ORDER_SUMMARY_FETCHED")
		self.assertTrue(
			any(row["order_name"] == order_name for row in summary_payload["message"]["data"]),
			BASE_URL,
		)
