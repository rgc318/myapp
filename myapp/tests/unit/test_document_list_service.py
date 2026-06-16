from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.services.document_list_service import list_business_documents_v1


class TestDocumentListService(TestCase):
	@patch("myapp.services.document_list_service.frappe.get_all")
	def test_list_business_documents_v1_returns_sales_invoice_rows(self, mock_get_all):
		mock_get_all.side_effect = [
			[
				frappe._dict(
					{
						"name": "SI-0001",
						"customer": "CUST-0001",
						"customer_name": "客户 A",
						"company": "rgc (Demo)",
						"posting_date": "2026-06-01",
						"docstatus": 1,
						"status": "Paid",
						"grand_total": 120,
						"rounded_total": 0,
						"outstanding_amount": 0,
						"paid_amount": 120,
						"due_date": "2026-06-08",
						"is_return": 0,
						"return_against": None,
						"modified": "2026-06-01 10:00:00",
					}
				)
			],
			[frappe._dict({"name": "SI-0001"})],
		]

		result = list_business_documents_v1(
			"Sales Invoice",
			company="rgc (Demo)",
			party="CUST-0001",
			docstatus="submitted",
			limit=20,
			start=0,
		)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["data"]["items"][0]["name"], "SI-0001")
		self.assertEqual(result["data"]["items"][0]["party_name"], "客户 A")
		self.assertEqual(result["data"]["items"][0]["document_status"], "Submitted")
		self.assertEqual(result["data"]["items"][0]["amount"], 120)
		self.assertEqual(result["data"]["pagination"]["total_count"], 1)
		self.assertEqual(mock_get_all.call_args_list[0].kwargs["filters"]["docstatus"], 1)

	@patch("myapp.services.document_list_service.frappe.throw")
	def test_list_business_documents_v1_rejects_unlisted_doctype(self, mock_throw):
		mock_throw.side_effect = RuntimeError("not allowed")

		with self.assertRaisesRegex(RuntimeError, "not allowed"):
			list_business_documents_v1("User")
