from unittest import TestCase
from unittest.mock import Mock, patch

import frappe
from rgc_backend_kit.security import InvalidTokenError

from myapp.auth import token_api


class TestTokenApi(TestCase):
	def setUp(self):
		self.ip_tracker = Mock()
		self.user_tracker = Mock()
		self.ip_lookup = self.enterContext(patch.object(token_api, "_get_ip_login_tracker", return_value=self.ip_tracker))
		self.user_lookup = self.enterContext(patch.object(token_api, "get_login_attempt_tracker", return_value=self.user_tracker))

	def test_wrong_password_counts_canonical_user_and_ip(self):
		user = Mock(is_authenticated=False, enabled=True)
		user.name = "canonical@example.com"
		with patch("frappe.core.doctype.user.user.User.find_by_credentials", return_value=user):
			with self.assertRaises(frappe.AuthenticationError):
				token_api.login_v1(username="alias", password="wrong")
		self.user_lookup.assert_called_once_with("canonical@example.com")
		self.user_tracker.add_failure_attempt.assert_called_once()
		self.ip_tracker.add_failure_attempt.assert_called_once()
		self.user_tracker.add_success_attempt.assert_not_called()

	def test_unknown_account_counts_ip_failure(self):
		with patch("frappe.core.doctype.user.user.User.find_by_credentials", return_value=None):
			with self.assertRaises(frappe.AuthenticationError):
				token_api.login_v1(username="unknown", password="wrong")
		self.ip_tracker.add_failure_attempt.assert_called_once()
		self.user_lookup.assert_not_called()

	def test_locked_ip_stops_before_password_verification(self):
		self.ip_lookup.side_effect = frappe.SecurityException("locked")
		with patch.object(token_api, "_find_user_by_credentials") as find:
			with self.assertRaises(frappe.SecurityException):
				token_api.login_v1(username="alias", password="password")
		find.assert_not_called()

	def test_framework_lock_is_mapped_to_http_429(self):
		self.user_lookup.side_effect = frappe.SecurityException("locked")
		with self.assertRaises(frappe.SecurityException) as raised:
			token_api._get_login_tracker("synthetic-account")
		self.assertEqual(raised.exception.http_status_code, 429)

	def test_locked_canonical_user_cannot_request_otp(self):
		user = Mock(is_authenticated=True, enabled=True)
		user.name = "canonical@example.com"
		self.user_lookup.side_effect = frappe.SecurityException("locked")
		with (
			patch("frappe.core.doctype.user.user.User.find_by_credentials", return_value=user),
			patch.object(token_api, "_validate_two_factor") as otp,
		):
			with self.assertRaises(frappe.SecurityException):
				token_api.login_v1(username="alias", password="password")
		otp.assert_not_called()
		self.ip_tracker.add_failure_attempt.assert_called_once()

	def test_wrong_otp_counts_both_failures_without_reset(self):
		with (
			patch.object(token_api, "_find_user_by_credentials", return_value="user@example.com"),
			patch.object(token_api, "_validate_two_factor", side_effect=frappe.AuthenticationError("bad otp")),
			patch.object(token_api, "issue_token_pair") as issue,
		):
			with self.assertRaises(frappe.AuthenticationError):
				token_api.login_v1(username="alias", password="password", otp="wrong")
		issue.assert_not_called()
		for tracker in (self.ip_tracker, self.user_tracker):
			tracker.add_failure_attempt.assert_called_once()
			tracker.add_success_attempt.assert_not_called()

	def test_oversized_password_is_rejected_before_hashing(self):
		with patch.object(token_api, "_find_user_by_credentials") as find:
			with self.assertRaises(frappe.AuthenticationError):
				token_api.login_v1(username="alias", password="x" * (token_api.MAX_PASSWORD_SIZE + 1))
		find.assert_not_called()
		self.ip_tracker.add_failure_attempt.assert_called_once()

	def test_disabled_user_counts_failure(self):
		user = Mock(is_authenticated=True, enabled=False)
		user.name = "disabled@example.com"
		with patch("frappe.core.doctype.user.user.User.find_by_credentials", return_value=user):
			with self.assertRaises(frappe.AuthenticationError):
				token_api.login_v1(username="disabled", password="password")
		self.user_tracker.add_failure_attempt.assert_called_once()
		self.ip_tracker.add_failure_attempt.assert_called_once()

	@patch("myapp.auth.token_api._find_user_by_credentials", return_value="user@example.com")
	@patch("myapp.auth.token_api.frappe.get_roles", return_value=["System Manager"])
	@patch("myapp.auth.token_api._current_user_payload", return_value={"user": "user@example.com"})
	@patch("myapp.auth.token_api._validate_two_factor", return_value=None)
	@patch("myapp.auth.token_api.get_user_auth_generation", return_value=3)
	@patch("myapp.auth.token_api.issue_token_pair")
	def test_login_v1_issues_jwt_pair(self, mock_issue_token_pair, _mock_generation, _mock_two_factor, mock_current_user_payload, mock_get_roles, mock_find_user):
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
		self.user_tracker.add_success_attempt.assert_called_once()
		self.ip_tracker.add_success_attempt.assert_called_once()
		self.assertEqual(result["data"]["access_token"], "access-token")
		self.assertEqual(result["data"]["refresh_token"], "refresh-token")
		self.assertEqual(result["data"]["user"], {"user": "user@example.com"})
		mock_find_user.assert_called_once_with("user@example.com", "password")
		mock_issue_token_pair.assert_called_once_with(
			"user@example.com",
			{"auth_generation": 3, "roles": ["System Manager"]},
			remember_me=True,
		)

	@patch("myapp.auth.token_api._find_user_by_credentials", return_value="user@example.com")
	@patch(
		"myapp.auth.token_api._validate_two_factor",
		return_value={"requires_two_factor": True, "method": "OTP App", "prompt": "请输入验证码"},
	)
	def test_login_v1_returns_two_factor_challenge(self, _mock_two_factor, _mock_find_user):
		result = token_api.login_v1(username="user@example.com", password="password")

		self.assertEqual(result["code"], "JWT_TWO_FACTOR_REQUIRED")
		self.assertTrue(result["data"]["requires_two_factor"])
		self.user_tracker.add_success_attempt.assert_not_called()
		self.ip_tracker.add_success_attempt.assert_not_called()

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
