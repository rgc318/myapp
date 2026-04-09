from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.services.mobile_release_service import _detect_has_update, get_mobile_release_info


class TestMobileReleaseService(TestCase):
	def test_detect_has_update_when_latest_semver_is_higher(self):
		self.assertTrue(_detect_has_update(current_version="1.0.0", latest_version="1.0.1"))

	def test_detect_has_update_when_semver_matches_but_build_number_is_higher(self):
		self.assertTrue(
			_detect_has_update(
				current_version="1.0.0",
				current_build_number=12,
				latest_version="1.0.0",
				latest_build_number=15,
			)
		)

	def test_get_mobile_release_info_returns_disabled_payload_without_release_source(self):
		with patch.object(frappe, "conf", {}):
			result = get_mobile_release_info(current_version="1.0.0")

		self.assertEqual(result["code"], "MOBILE_RELEASE_SOURCE_NOT_CONFIGURED")
		self.assertFalse(result["data"]["enabled"])
		self.assertFalse(result["data"]["has_update"])

	@patch("myapp.services.mobile_release_service._fetch_release_payload")
	def test_get_mobile_release_info_maps_github_latest_release(self, mock_fetch_release_payload):
		mock_fetch_release_payload.return_value = {
			"tag_name": "mobile-v1.0.3+build.42",
			"name": "myapp-mobile v1.0.3 build 42",
			"body": "修复登录问题\n优化订单提交",
			"published_at": "2026-04-10T12:00:00Z",
			"html_url": "https://github.com/example/repo/releases/tag/mobile-v1.0.3+build.42",
			"prerelease": False,
			"assets": [
				{
					"name": "myapp-mobile-release-v1.0.3.apk",
					"browser_download_url": "https://github.com/example/repo/releases/download/mobile-v1.0.3%2Bbuild.42/app.apk",
					"size": 123456,
				}
			],
		}

		with patch.object(
			frappe,
			"conf",
			{
				"myapp_mobile_release_repo": "example/repo",
			},
		):
			result = get_mobile_release_info(current_version="1.0.0")

		self.assertEqual(result["code"], "MOBILE_RELEASE_INFO_FETCHED")
		self.assertTrue(result["data"]["enabled"])
		self.assertTrue(result["data"]["has_update"])
		self.assertEqual(result["data"]["latest_version"], "1.0.3+build.42")
		self.assertEqual(result["data"]["latest_build_number"], 42)
		self.assertEqual(result["data"]["asset_name"], "myapp-mobile-release-v1.0.3.apk")

	@patch("myapp.services.mobile_release_service._fetch_release_payload")
	def test_get_mobile_release_info_raises_when_no_apk_asset_found(self, mock_fetch_release_payload):
		mock_fetch_release_payload.return_value = {
			"tag_name": "mobile-v1.0.3+build.42",
			"assets": [{"name": "notes.txt", "browser_download_url": "https://example.com/notes.txt"}],
		}

		with patch.object(frappe, "conf", {"myapp_mobile_release_repo": "example/repo"}):
			with self.assertRaises(frappe.ValidationError):
				get_mobile_release_info(current_version="1.0.0")
