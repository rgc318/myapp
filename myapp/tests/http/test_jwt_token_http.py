import json
import os
import pathlib
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
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
USERNAME = os.environ.get("MYAPP_HTTP_USERNAME", "").strip()
PASSWORD = os.environ.get("MYAPP_HTTP_PASSWORD", "").strip()
HTTP_TIMEOUT = int(os.environ.get("MYAPP_HTTP_TIMEOUT", "60"))


class JwtTokenHttpTestCase(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not USERNAME or not PASSWORD:
			raise cls.skipTest("JWT HTTP tests require MYAPP_HTTP_USERNAME/MYAPP_HTTP_PASSWORD.")

	@classmethod
	def _post(cls, method_path: str, payload: dict | None = None, *, bearer_token: str | None = None):
		headers = {"Content-Type": "application/json", "Accept": "application/json"}
		if bearer_token:
			headers["Authorization"] = f"Bearer {bearer_token}"

		request = urllib.request.Request(
			f"{BASE_URL}/api/method/{method_path}",
			data=json.dumps(payload or {}).encode(),
			headers=headers,
			method="POST",
		)
		try:
			with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
				return response.getcode(), json.loads(response.read().decode() or "{}")
		except urllib.error.HTTPError as exc:
			body = exc.read().decode()
			try:
				payload = json.loads(body or "{}")
			except json.JSONDecodeError:
				payload = {"raw_body": body}
			return exc.code, payload

	@classmethod
	def _login(cls):
		status_code, payload = cls._post(
			"myapp.auth.token_api.login_v1",
			{"username": USERNAME, "password": PASSWORD},
		)
		if status_code != HTTPStatus.OK or payload["message"]["code"] != "JWT_TOKEN_ISSUED":
			raise AssertionError(f"JWT login failed: HTTP {status_code}, payload={payload}")
		return payload["message"]["data"]

	def _assert_success_payload(self, status_code: int, payload: dict, code: str):
		self.assertEqual(status_code, HTTPStatus.OK, payload)
		self.assertTrue(payload["message"]["ok"], payload)
		self.assertEqual(payload["message"]["code"], code, payload)

	def test_login_me_refresh_and_logout_lifecycle(self):
		tokens = self._login()

		me_status, me_payload = self._post(
			"myapp.auth.token_api.me_v1",
			bearer_token=tokens["access_token"],
		)
		self._assert_success_payload(me_status, me_payload, "JWT_CURRENT_USER_FETCHED")
		self.assertEqual(me_payload["message"]["data"]["user"], USERNAME)

		refresh_status, refresh_payload = self._post(
			"myapp.auth.token_api.refresh_v1",
			{"refresh_token": tokens["refresh_token"]},
		)
		self._assert_success_payload(refresh_status, refresh_payload, "JWT_TOKEN_REFRESHED")
		rotated_tokens = refresh_payload["message"]["data"]
		self.assertNotEqual(tokens["access_token"], rotated_tokens["access_token"])
		self.assertNotEqual(tokens["refresh_token"], rotated_tokens["refresh_token"])

		reuse_status, reuse_payload = self._post(
			"myapp.auth.token_api.refresh_v1",
			{"refresh_token": tokens["refresh_token"]},
		)
		self.assertEqual(reuse_status, HTTPStatus.UNAUTHORIZED, reuse_payload)
		self.assertEqual(reuse_payload["exc_type"], "AuthenticationError")

		logout_status, logout_payload = self._post(
			"myapp.auth.token_api.logout_v1",
			{"refresh_token": rotated_tokens["refresh_token"]},
			bearer_token=rotated_tokens["access_token"],
		)
		self._assert_success_payload(logout_status, logout_payload, "JWT_TOKEN_REVOKED")

		revoked_status, revoked_payload = self._post(
			"myapp.auth.token_api.me_v1",
			bearer_token=rotated_tokens["access_token"],
		)
		self.assertEqual(revoked_status, HTTPStatus.UNAUTHORIZED, revoked_payload)
		self.assertEqual(revoked_payload["exc_type"], "AuthenticationError")

		deleted_refresh_status, deleted_refresh_payload = self._post(
			"myapp.auth.token_api.refresh_v1",
			{"refresh_token": rotated_tokens["refresh_token"]},
		)
		self.assertEqual(deleted_refresh_status, HTTPStatus.UNAUTHORIZED, deleted_refresh_payload)
		self.assertEqual(deleted_refresh_payload["exc_type"], "AuthenticationError")

	def test_invalid_bearer_token_is_rejected(self):
		status_code, payload = self._post(
			"myapp.auth.token_api.me_v1",
			bearer_token="invalid.jwt.token",
		)

		self.assertEqual(status_code, HTTPStatus.UNAUTHORIZED, payload)
		self.assertEqual(payload["exc_type"], "AuthenticationError")

	def test_session_login_does_not_issue_jwt_cookies(self):
		cookies = CookieJar()
		opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
		request = urllib.request.Request(
			f"{BASE_URL}/api/method/login",
			data=urllib.parse.urlencode({"usr": USERNAME, "pwd": PASSWORD}).encode(),
			headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
			method="POST",
		)

		with opener.open(request, timeout=HTTP_TIMEOUT) as response:
			payload = json.loads(response.read().decode() or "{}")

		self.assertEqual(payload["message"], "Logged In")
		self.assertFalse(any("jwt" in cookie.name.lower() for cookie in cookies))
