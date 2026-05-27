from unittest import TestCase
from unittest.mock import Mock, patch

import frappe
from rgc_backend_kit.security import InvalidTokenError

from myapp.auth import token_api


class TestTokenApi(TestCase):
	@patch("myapp.auth.token_api._find_user_by_credentials", return_value="user@example.com")
	@patch("myapp.auth.token_api.frappe.get_roles", return_value=["System Manager"])
	@patch("myapp.auth.token_api._current_user_payload", return_value={"user": "user@example.com"})
	@patch("myapp.auth.token_api.issue_token_pair")
	def test_login_v1_issues_jwt_pair(self, mock_issue_token_pair, mock_current_user_payload, mock_get_roles, mock_find_user):
		mock_issue_token_pair.return_value = Mock(
			access_token="access-token",
			refresh_token="refresh-token",
			token_type="bearer",
			access_expires_in=3600,
			refresh_expires_in=604800,
			access_jti="access-jti",
			refresh_jti="refresh-jti",
		)

		result = token_api.login_v1(username="user@example.com", password="password", remember_me=1)

		self.assertTrue(result["ok"])
		self.assertEqual(result["code"], "JWT_TOKEN_ISSUED")
		self.assertEqual(result["data"]["access_token"], "access-token")
		self.assertEqual(result["data"]["refresh_token"], "refresh-token")
		self.assertEqual(result["data"]["user"], {"user": "user@example.com"})
		mock_find_user.assert_called_once_with("user@example.com", "password")
		mock_issue_token_pair.assert_called_once_with("user@example.com", {"roles": ["System Manager"]}, remember_me=True)

	@patch("myapp.auth.token_api.rotate_refresh_token")
	def test_refresh_v1_rotates_refresh_token(self, mock_rotate_refresh_token):
		mock_rotate_refresh_token.return_value = Mock(
			access_token="new-access-token",
			refresh_token="new-refresh-token",
			token_type="bearer",
			access_expires_in=3600,
			refresh_expires_in=604800,
			access_jti="new-access-jti",
			refresh_jti="new-refresh-jti",
		)

		result = token_api.refresh_v1("old-refresh-token")

		self.assertTrue(result["ok"])
		self.assertEqual(result["code"], "JWT_TOKEN_REFRESHED")
		self.assertEqual(result["data"]["access_token"], "new-access-token")
		mock_rotate_refresh_token.assert_called_once_with("old-refresh-token")

	@patch.object(frappe, "get_request_header", return_value="Bearer access-token")
	@patch("myapp.auth.token_api.delete_refresh_token")
	@patch("myapp.auth.token_api.revoke_access_token")
	def test_logout_v1_revokes_header_access_token_and_refresh_token(
		self,
		mock_revoke_access_token,
		mock_delete_refresh_token,
		mock_get_request_header,
	):
		result = token_api.logout_v1(refresh_token="refresh-token")

		self.assertTrue(result["ok"])
		self.assertEqual(result["code"], "JWT_TOKEN_REVOKED")
		mock_revoke_access_token.assert_called_once_with("access-token")
		mock_delete_refresh_token.assert_called_once_with("refresh-token")

	def test_login_v1_requires_credentials(self):
		with self.assertRaises(frappe.AuthenticationError):
			token_api.login_v1(username="", password="")

	@patch("myapp.auth.token_api.rotate_refresh_token")
	def test_refresh_v1_maps_invalid_refresh_token_to_authentication_error(self, mock_rotate_refresh_token):
		mock_rotate_refresh_token.side_effect = InvalidTokenError("invalid refresh token")

		with self.assertRaises(frappe.AuthenticationError):
			token_api.refresh_v1("invalid-refresh-token")
