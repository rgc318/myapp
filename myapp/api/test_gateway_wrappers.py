from unittest import TestCase
from unittest.mock import patch

from myapp.api.gateway import create_sales_invoice, submit_delivery


class TestGatewayWrappers(TestCase):
	@patch("myapp.api.gateway.submit_delivery_service")
	def test_submit_delivery_passes_top_level_request_id_to_service(self, mock_submit_delivery_service):
		mock_submit_delivery_service.return_value = {
			"status": "success",
			"delivery_note": "DN-0001",
		}

		submit_delivery("SO-0001", request_id="dn-001")

		mock_submit_delivery_service.assert_called_once_with(
			order_name="SO-0001",
			delivery_items=None,
			kwargs={"request_id": "dn-001"},
		)

	@patch("myapp.api.gateway.create_sales_invoice_service")
	def test_create_sales_invoice_passes_top_level_request_id_to_service(
		self, mock_create_sales_invoice_service
	):
		mock_create_sales_invoice_service.return_value = {
			"status": "success",
			"sales_invoice": "SINV-0001",
		}

		create_sales_invoice("SO-0001", request_id="si-001")

		mock_create_sales_invoice_service.assert_called_once_with(
			source_name="SO-0001",
			invoice_items=None,
			kwargs={"request_id": "si-001"},
		)
