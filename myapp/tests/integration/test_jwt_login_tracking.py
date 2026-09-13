"""Real Redis tracker tests with synthetic identities, no account/settings writes."""

import os
import secrets
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import patch

import frappe
from frappe.auth import LoginAttemptTracker

from myapp.auth import token_api


@skipUnless(os.getenv("MYAPP_JWT_TRACKING_TEST_SITE"), "Requires explicit JWT tracker test site")
class JwtLoginTrackingTests(TestCase):
	def setUp(self):
		frappe.init(site=os.environ["MYAPP_JWT_TRACKING_TEST_SITE"], sites_path="/home/frappe/frappe-bench/sites")
		frappe.connect()
		self.user = "jwt-tracker-test-" + secrets.token_hex(12)
		self.ip = self.user + "-ip"
		frappe.local.request_ip = self.ip
		self.enterContext(patch("frappe.auth.frappe.get_doc", return_value=frappe._dict(
			allow_consecutive_login_attempts=2, allow_login_after_fail=300,
		)))
		self.account = SimpleNamespace(name=self.user, enabled=True, is_authenticated=True)
		self.enterContext(patch("frappe.core.doctype.user.user.User.find_by_credentials", return_value=self.account))
		self.issue = self.enterContext(patch.object(token_api, "issue_token_pair"))

	def tearDown(self):
		for key in (self.user, self.ip):
			LoginAttemptTracker(key).add_success_attempt()
		frappe.db.rollback()
		frappe.destroy()

	def test_wrong_otp_locks_account_even_when_password_is_correct(self):
		with patch.object(token_api, "_validate_two_factor", side_effect=frappe.AuthenticationError("wrong otp")):
			# Frappe locks when failures exceed (not equal) the configured limit.
			for _ in range(3):
				with self.assertRaises(frappe.AuthenticationError):
					token_api.login_v1(username=self.user, password="synthetic", otp="invalid")
		self.assertEqual(LoginAttemptTracker(self.user).login_failed_count, 3)
		# Clear only synthetic IP budget, proving the account itself stays locked.
		LoginAttemptTracker(self.ip).add_success_attempt()
		with self.assertRaises(frappe.SecurityException):
			token_api.login_v1(username=self.user, password="synthetic", otp="123456")
		self.issue.assert_not_called()

	def test_wrong_password_locks_ip_before_next_credential_lookup(self):
		self.account.is_authenticated = False
		for _ in range(3):
			with self.assertRaises(frappe.AuthenticationError):
				token_api.login_v1(username=self.user, password="synthetic-wrong")
		with patch.object(token_api, "_find_user_by_credentials") as find:
			with self.assertRaises(frappe.SecurityException):
				token_api.login_v1(username="another-alias", password="synthetic")
		find.assert_not_called()
		self.issue.assert_not_called()
