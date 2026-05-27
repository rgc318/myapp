from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from myapp.auth import jwt_auth
from myapp.auth.token_store import FrappeCacheTokenStore


class TestJwtAuthHook(TestCase):
	@patch.object(frappe, "get_request_header")
	@patch.object(frappe, "set_user")
	def test_validate_ignores_requests_without_authorization_header(self, mock_set_user, mock_get_request_header):
		mock_get_request_header.return_value = ""

		jwt_auth.validate()

		mock_set_user.assert_not_called()

	@patch.object(frappe, "get_request_header")
	@patch.object(frappe, "set_user")
	def test_validate_ignores_non_bearer_authorization_header(self, mock_set_user, mock_get_request_header):
		mock_get_request_header.return_value = "token api-key:api-secret"

		jwt_auth.validate()

		mock_set_user.assert_not_called()

	@patch.object(frappe, "get_request_header")
	@patch.object(frappe, "set_user")
	@patch("myapp.auth.jwt_auth._is_enabled_user", return_value=True)
	@patch("myapp.auth.jwt_auth.decode_access_token")
	def test_validate_sets_user_for_valid_bearer_token(
		self,
		mock_decode_access_token,
		mock_is_enabled_user,
		mock_set_user,
		mock_get_request_header,
	):
		mock_get_request_header.return_value = "Bearer access-token"
		mock_decode_access_token.return_value = Mock(subject="user@example.com")
		original_form_dict = Mock()
		frappe.local.form_dict = original_form_dict

		jwt_auth.validate()

		mock_decode_access_token.assert_called_once_with("access-token")
		mock_is_enabled_user.assert_called_once_with("user@example.com")
		mock_set_user.assert_called_once_with("user@example.com")
		self.assertIs(frappe.local.form_dict, original_form_dict)

	@patch.object(frappe, "get_request_header")
	@patch.object(frappe, "set_user")
	@patch("myapp.auth.jwt_auth._is_enabled_user", return_value=False)
	@patch("myapp.auth.jwt_auth.decode_access_token")
	def test_validate_rejects_disabled_or_missing_user(
		self,
		mock_decode_access_token,
		mock_is_enabled_user,
		mock_set_user,
		mock_get_request_header,
	):
		mock_get_request_header.return_value = "Bearer access-token"
		mock_decode_access_token.return_value = Mock(subject="user@example.com")

		with self.assertRaises(frappe.AuthenticationError):
			jwt_auth.validate()

		mock_is_enabled_user.assert_called_once_with("user@example.com")
		mock_set_user.assert_not_called()

	@patch.object(frappe, "get_request_header")
	@patch("myapp.auth.jwt_auth.decode_access_token")
	def test_validate_rejects_invalid_bearer_token(self, mock_decode_access_token, mock_get_request_header):
		mock_get_request_header.return_value = "Bearer invalid-token"
		mock_decode_access_token.side_effect = Exception("invalid")

		with self.assertRaises(frappe.AuthenticationError):
			jwt_auth.validate()


class TestFrappeCacheTokenStore(TestCase):
	def test_store_uses_frappe_cache_keys_and_ttls(self):
		cache = Mock()
		cache.get_value.side_effect = ["refresh-token", "1"]

		with patch.object(frappe, "cache", return_value=cache):
			store = FrappeCacheTokenStore(refresh_prefix="refresh", revoked_prefix="revoked")

			import asyncio

			asyncio.run(store.set_refresh_token("user@example.com", "refresh-jti", "refresh-token", 60))
			self.assertTrue(asyncio.run(store.refresh_token_exists("user@example.com", "refresh-jti")))
			asyncio.run(store.revoke_token("access-jti", 30))
			self.assertTrue(asyncio.run(store.is_token_revoked("access-jti")))
			asyncio.run(store.delete_refresh_token("user@example.com", "refresh-jti"))

		cache.set_value.assert_any_call("refresh:user@example.com:refresh-jti", "refresh-token", expires_in_sec=60)
		cache.set_value.assert_any_call("revoked:access-jti", "1", expires_in_sec=30)
		cache.delete_value.assert_called_once_with("refresh:user@example.com:refresh-jti")
