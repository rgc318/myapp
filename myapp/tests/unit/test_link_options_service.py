from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.services.link_options_service import search_link_options_v1


class TestLinkOptionsService(TestCase):
	@patch("myapp.services.link_options_service.frappe.get_list")
	def test_search_link_options_v1_returns_allowed_options(self, mock_get_list):
		mock_get_list.return_value = [
			frappe._dict({"name": "Cash"}),
			frappe._dict({"name": "Bank"}),
		]

		result = search_link_options_v1("Mode of Payment", query="Ca", limit=8)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"][0], {"description": None, "label": "Cash", "value": "Cash"})
		mock_get_list.assert_called_once_with(
			"Mode of Payment",
			fields=["name"],
			filters=[["name", "like", "%Ca%"]],
			limit_page_length=8,
			order_by="modified desc",
		)

	@patch("myapp.services.link_options_service.frappe.get_list")
	def test_search_link_options_v1_allows_whitelisted_extra_fields(self, mock_get_list):
		mock_get_list.return_value = [
			frappe._dict({"name": "SUP-0001", "supplier_name": "供应商 A"}),
		]

		result = search_link_options_v1("Supplier", extra_fields=["supplier_name", "owner"])

		self.assertEqual(result["data"][0]["description"], "供应商 A")
		self.assertEqual(mock_get_list.call_args.kwargs["fields"], ["name", "supplier_name"])

	@patch("myapp.services.link_options_service.frappe.throw")
	def test_search_link_options_v1_rejects_unlisted_doctype(self, mock_throw):
		mock_throw.side_effect = RuntimeError("not allowed")

		with self.assertRaisesRegex(RuntimeError, "not allowed"):
			search_link_options_v1("User")
