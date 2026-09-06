"""Gateway→adapter→job API smoke; no ERP fixture creation or model probes by default."""
import json
import os
import time
import unittest
import urllib.request
import urllib.error
from http.cookiejar import CookieJar

from .test_ai_gateway_http import _load_env_file


class ModelCheckHttpTest(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		_load_env_file()
		username, password = os.getenv("MYAPP_HTTP_USERNAME"), os.getenv("MYAPP_HTTP_PASSWORD")
		if not username or not password:
			raise unittest.SkipTest("HTTP test credentials are required")
		cls.base = os.getenv("MYAPP_HTTP_BASE_URL", "http://localhost:8080")
		cls.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
		request = urllib.request.Request(cls.base + "/api/method/login",
			data=json.dumps({"usr": username, "pwd": password}).encode(),
			headers={"Content-Type": "application/json"})
		with cls.opener.open(request, timeout=15) as response:
			assert json.load(response)["message"] == "Logged In"

	def call(self, method, payload):
		request = urllib.request.Request(self.base + "/api/method/myapp.api.gateway." + method,
			data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
		with self.opener.open(request, timeout=15) as response:
			result = json.load(response)["message"]
		self.assertTrue(result["ok"], result.get("code"))
		return result["data"]

	def test_progress_route(self):
		result = self.call("get_ai_model_check_v1", {})
		if result:
			self.assertIn("job_id", result)
			self.assertIn("model_aliases", result)

	def test_delete_intent_is_rejected_before_draft_generation(self):
		alias = os.getenv("MYAPP_HTTP_ACTION_TEST_MODEL")
		if not alias:
			self.skipTest("Set MYAPP_HTTP_ACTION_TEST_MODEL to permit a read-only billable intent test")
		request = urllib.request.Request(self.base + "/api/method/myapp.api.gateway.resolve_ai_scenario_v1",
			data=json.dumps({"content": "删除百事可乐2和3，只保留一个百事可乐", "model_alias": alias}).encode(),
			headers={"Content-Type": "application/json"})
		try:
			response = self.opener.open(request, timeout=60)
		except urllib.error.HTTPError as error:
			response = error
		with response:
			result = json.load(response)["message"]
		self.assertFalse(result["ok"])
		self.assertEqual(result["code"], "VALIDATION_ERROR")
		self.assertIn("当前 AI 不支持执行该动作", json.dumps(result, ensure_ascii=False))

	def test_single_model_background_job(self):
		alias = os.getenv("MYAPP_HTTP_MODEL_CHECK_ALIAS")
		if not alias:
			self.skipTest("Set MYAPP_HTTP_MODEL_CHECK_ALIAS to permit one billable basic probe")
		payload = {"model_aliases": [alias], "mode": "basic", "request_id": f"check-http-{time.time_ns()}"}
		job = self.call("start_ai_model_check_v1", payload)
		try:
			self.assertEqual(job["total"], 1)
			self.assertEqual(self.call("start_ai_model_check_v1", payload)["job_id"], job["job_id"])
			deadline = time.monotonic() + 60
			while time.monotonic() < deadline:
				result = self.call("get_ai_model_check_v1", {"job_id": job["job_id"]})
				if result["status"] not in {"queued", "running"}:
					self.assertEqual(result["status"], "completed", result["status"])
					self.assertEqual(result["completed"], 1)
					self.assertEqual(result["items"][0]["check_status"], "completed")
					return
				time.sleep(2)
			self.fail("Worker did not finish within 60 seconds")
		finally:
			self.call("cancel_ai_model_check_v1", {"job_id": job["job_id"], "request_id": payload["request_id"] + "-cancel"})
