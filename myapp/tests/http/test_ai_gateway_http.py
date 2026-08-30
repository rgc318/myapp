import json
import os
import pathlib
import unittest
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

DEFAULT_ENV_FILE = pathlib.Path(__file__).resolve().parents[3] / ".env.http-test"


def _load_env_file():
	if not DEFAULT_ENV_FILE.exists():
		return
	for raw_line in DEFAULT_ENV_FILE.read_text(encoding="utf-8").splitlines():
		line = raw_line.strip()
		if not line or line.startswith("#") or "=" not in line:
			continue
		key, value = line.split("=", 1)
		os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_env_file()


class AiGatewayHttpTestCase(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if os.environ.get("MYAPP_HTTP_ENABLE_AI_TESTS", "0") not in {"1", "true", "True"}:
			raise unittest.SkipTest("Set MYAPP_HTTP_ENABLE_AI_TESTS=1 to run billable AI HTTP tests.")

		cls.base_url = os.environ.get("MYAPP_HTTP_BASE_URL", "http://localhost:8080").rstrip("/")
		cls.expected_model = os.environ.get("MYAPP_HTTP_AI_MODEL", "opencode-deepseek-v4-flash").strip()
		username = os.environ.get("MYAPP_HTTP_USERNAME", "").strip()
		password = os.environ.get("MYAPP_HTTP_PASSWORD", "").strip()
		if not username or not password:
			raise unittest.SkipTest("AI HTTP tests require MYAPP_HTTP_USERNAME/MYAPP_HTTP_PASSWORD.")

		cls.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
		request = urllib.request.Request(
			f"{cls.base_url}/api/method/login",
			data=urllib.parse.urlencode({"usr": username, "pwd": password}).encode(),
			headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
			method="POST",
		)
		with cls.opener.open(request, timeout=30) as response:
			payload = json.loads(response.read().decode() or "{}")
		if payload.get("message") != "Logged In":
			raise AssertionError(f"Login failed against {cls.base_url}")

	def _post_gateway(self, method: str, payload: dict):
		request = urllib.request.Request(
			f"{self.base_url}/api/method/myapp.api.gateway.{method}",
			data=json.dumps(payload).encode(),
			headers={"Content-Type": "application/json", "Accept": "application/json"},
			method="POST",
		)
		with self.opener.open(request, timeout=90) as response:
			return json.loads(response.read().decode() or "{}")["message"]

	def _archive_conversation(self, conversation_id: str):
		message = self._post_gateway(
			"archive_ai_conversation_v1",
			{"conversation_id": conversation_id},
		)
		self.assertTrue(message["ok"])

	def _stream_gateway(self, payload: dict):
		request = urllib.request.Request(
			f"{self.base_url}/api/method/myapp.api.gateway.stream_ai_message_v1",
			data=json.dumps(payload).encode(),
			headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
			method="POST",
		)
		events = []
		with self.opener.open(request, timeout=120) as response:
			self.assertEqual(response.headers.get_content_type(), "text/event-stream")
			for raw_line in response:
				line = raw_line.decode().strip()
				if line.startswith("data:"):
					events.append(json.loads(line[5:].strip()))
		return events

	def test_ai_chat_reaches_litellm_with_read_only_contract(self):
		message = self._post_gateway(
			"chat_ai_v1",
			{
				"content": "没有提供业务上下文时，你能确认真实订单或库存事实吗？",
				"scenario": "general",
				"company": "rgc (Demo)",
			},
		)
		self.assertTrue(message["ok"])
		self.assertEqual(message["code"], "AI_CHAT_COMPLETED")
		content = message["data"]["message"]["content"]
		self.assertTrue(any(term in content for term in ("不能", "无法")))
		self.assertTrue(any(term in content for term in ("上下文", "数据", "事实")))
		self.assertEqual(message["data"]["model"], self.expected_model)
		self.assertGreaterEqual(message["data"]["usage"]["reasoning_tokens"], 0)
		self.assertTrue(message["data"]["warnings"])
		self.assertTrue(message["data"]["conversation"].startswith("AI-CONV-"))
		self.assertTrue(message["data"]["run_id"].startswith("AI-RUN-"))
		self.assertEqual(message["data"]["events"][-1]["type"], "completed")

		conversation = self._post_gateway(
			"get_ai_conversation_v1",
			{"conversation_id": message["data"]["conversation"]},
		)
		self.assertEqual(len(conversation["data"]["messages"]), 2)
		self._archive_conversation(message["data"]["conversation"])

	def test_ai_auto_scenario_resolution_accepts_company_and_conversation(self):
		created = self._post_gateway(
			"create_ai_conversation_v1",
			{"title": "HTTP auto scenario contract", "company": "rgc (Demo)"},
		)
		self.assertTrue(created["ok"])
		conversation_id = created["data"]["name"]
		try:
			resolved = self._post_gateway(
				"resolve_ai_scenario_v1",
				{
					"content": "新增一个测试商品",
					"company": "rgc (Demo)",
					"conversation_id": conversation_id,
				},
			)
			self.assertTrue(resolved["ok"])
			self.assertEqual(resolved["code"], "AI_SCENARIO_RESOLVED")
			self.assertTrue(resolved["data"]["scenario"])
			self.assertTrue(resolved["data"]["resolution_id"])
		finally:
			self._archive_conversation(conversation_id)

	def test_ai_auto_scenario_resolution_is_reused_by_stream(self):
		created = self._post_gateway(
			"create_ai_conversation_v1",
			{"title": "HTTP auto scenario reuse", "company": "rgc (Demo)"},
		)
		conversation_id = created["data"]["name"]
		content = "仓里还剩迪莫吗"
		try:
			resolved = self._post_gateway(
				"resolve_ai_scenario_v1",
				{
					"content": content,
					"company": "rgc (Demo)",
					"conversation_id": conversation_id,
				},
			)
			events = self._stream_gateway(
				{
					"content": content,
					"scenario": "auto",
					"company": "rgc (Demo)",
					"conversation_id": conversation_id,
					"scenario_resolution_id": resolved["data"]["resolution_id"],
				},
			)
			self.assertEqual(events[0]["type"], "run_started")
			self.assertEqual(events[-1]["type"], "completed")
			self.assertEqual(events[-1]["conversation"], conversation_id)
		finally:
			self._archive_conversation(conversation_id)

	def test_ai_product_search_uses_controlled_backend_tool(self):
		message = self._post_gateway(
			"chat_ai_v1",
			{
				"content": "帮我找数码相机，只说明真实候选商品。",
				"scenario": "auto",
				"company": "rgc (Demo)",
			},
		)
		self.assertTrue(message["ok"])
		citations = message["data"]["message"]["citations"]
		self.assertTrue(citations)
		self.assertEqual(citations[0]["type"], "product")
		self.assertEqual(citations[0]["id"], "SKU010")
		self.assertEqual(message["data"]["model"], self.expected_model)
		self.assertIn("tool_started", [event["type"] for event in message["data"]["events"]])
		self.assertIn("tool_completed", [event["type"] for event in message["data"]["events"]])
		self._archive_conversation(message["data"]["conversation"])

	def test_ai_multi_turn_context_inherits_product_and_order_filters(self):
		product_first = self._post_gateway(
			"chat_ai_v1",
			{
				"content": "查询 Camera 的库存和售价。",
				"scenario": "auto",
				"company": "rgc (Demo)",
			},
		)
		product_conversation = product_first["data"]["conversation"]
		try:
			product_follow_up = self._post_gateway(
				"chat_ai_v1",
				{
					"content": "那它的售价呢？",
					"scenario": "auto",
					"conversation_id": product_conversation,
				},
			)
			citations = product_follow_up["data"]["message"]["citations"]
			self.assertTrue(citations)
			self.assertEqual(citations[0]["type"], "product")
			self.assertEqual(citations[0]["id"], "SKU010")
		finally:
			self._archive_conversation(product_conversation)

		order_first = self._post_gateway(
			"chat_ai_v1",
			{
				"content": "查询最近一个月的销售订单，前五条。",
				"scenario": "auto",
				"company": "rgc (Demo)",
			},
		)
		order_conversation = order_first["data"]["conversation"]
		try:
			order_follow_up = self._post_gateway(
				"chat_ai_v1",
				{
					"content": "只看未完成的，换成上个月。",
					"scenario": "auto",
					"conversation_id": order_conversation,
				},
			)
			result_set = order_follow_up["data"]["message"]["citations"][0]
			self.assertEqual(result_set["type"], "business_result_set")
			self.assertEqual(result_set["data"]["groups"][0]["entity"], "sales_order")
			self.assertEqual(result_set["data"]["scope"]["status_filter"], "unfinished")
			self.assertEqual(result_set["data"]["scope"]["date_range"], "last_month")
			self.assertEqual(result_set["data"]["scope"]["limit_per_group"], 5)
		finally:
			self._archive_conversation(order_conversation)

	def test_ai_inventory_adjustment_draft_handoff_is_draft_only(self):
		message = self._post_gateway(
			"generate_ai_inventory_adjustment_draft_v1",
			{
				"content": "把 Stores - RD 的 SKU010 库存调整到 8 个，原因是 AI 真实链路盘点验证。",
				"company": "rgc (Demo)",
			},
		)
		self.assertTrue(message["ok"])
		self.assertEqual(message["code"], "AI_INVENTORY_ADJUSTMENT_DRAFT_CREATED")
		draft = message["data"]["draft"]
		try:
			self.assertEqual(draft["draft_type"], "inventory_adjustment")
			self.assertEqual(draft["payload"]["warehouse"], "Stores - RD")
			self.assertEqual(draft["payload"]["items"][0]["item_code"], "SKU010")
			self.assertTrue(draft["validation"]["ready_for_handoff"])

			versions = self._post_gateway(
				"list_ai_draft_versions_v1",
				{"draft_id": draft["name"]},
			)
			self.assertTrue(versions["ok"])
			self.assertEqual(versions["data"]["items"][0]["change_source"], "generated")

			handoff = self._post_gateway(
				"prepare_ai_draft_handoff_v1",
				{"draft_id": draft["name"]},
			)
			self.assertTrue(handoff["ok"])
			self.assertEqual(handoff["data"]["draft_type"], "inventory_adjustment")
			self.assertEqual(handoff["data"]["payload"]["item_code"], "SKU010")
			self.assertEqual(handoff["data"]["payload"]["uom"], draft["payload"]["items"][0]["stock_uom"])
		finally:
			self._archive_conversation(message["data"]["conversation"])

	def test_ai_stream_order_query_and_feedback(self):
		events = self._stream_gateway(
			{
				"content": "查询近30天采购订单，按金额从高到低返回前5条。",
				"scenario": "auto",
				"company": "rgc (Demo)",
			}
		)
		event_types = [event.get("type") for event in events]
		self.assertEqual(event_types[0], "run_started")
		self.assertIn("tool_started", event_types)
		self.assertIn("message_delta", event_types)
		self.assertEqual(event_types[-1], "completed")
		citations = [event["citation"] for event in events if event.get("type") == "citation"]
		self.assertTrue(citations)
		result_set = citations[0]
		self.assertEqual(result_set["type"], "business_result_set")
		self.assertEqual(result_set["data"]["schema_version"], "business-result-set-v1")
		self.assertEqual(result_set["data"]["groups"][0]["entity"], "purchase_order")
		document_citations = citations[1:]
		self.assertTrue(document_citations)
		self.assertTrue(
			all(citation["type"] == "purchase_order" for citation in document_citations)
		)
		completed = events[-1]
		self.assertEqual(completed["model"], self.expected_model)

		feedback = self._post_gateway(
			"submit_ai_feedback_v1",
			{"run_id": completed["run_id"], "rating": "positive", "category": "helpful"},
		)
		self.assertTrue(feedback["ok"])
		self.assertEqual(feedback["data"]["rating"], "positive")
		self._archive_conversation(completed["conversation"])

	def test_ai_stream_report_summary_uses_controlled_report_tool(self):
		events = self._stream_gateway(
			{
				"content": "解释本月销售表现和主要客户，区分销售额、实收和应收未结。",
				"scenario": "auto",
				"company": "rgc (Demo)",
			}
		)
		completed = events[-1]
		try:
			event_types = [event.get("type") for event in events]
			self.assertEqual(event_types[0], "run_started")
			self.assertIn("tool_started", event_types)
			self.assertIn("message_delta", event_types)
			self.assertEqual(event_types[-1], "completed")
			citations = [event["citation"] for event in events if event.get("type") == "citation"]
			self.assertEqual(len(citations), 1)
			self.assertEqual(citations[0]["type"], "business_report")
			self.assertEqual(citations[0]["data"]["report_type"], "sales")
			self.assertIn("sales_amount_total", citations[0]["data"]["overview"])
			self.assertEqual(completed["model"], self.expected_model)
		finally:
			if completed.get("conversation"):
				self._archive_conversation(completed["conversation"])


if __name__ == "__main__":
	unittest.main(verbosity=2)
