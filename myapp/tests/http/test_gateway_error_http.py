"""Read-only-input smoke for the public gateway error envelope."""

from .test_gateway_http import GatewayHttpTestCase


def load_tests(loader, tests, pattern):
	# Reuse the authentication harness, not its inherited sales test cases.
	return loader.loadTestsFromName(
		"test_invalid_product_returns_validation_envelope", GatewayErrorHttpTestCase
	)


class GatewayErrorHttpTestCase(GatewayHttpTestCase):
	@classmethod
	def _create_isolated_sales_test_item(cls):
		# This smoke only sends invalid input; it needs no committed fixture.
		return None

	def test_invalid_product_returns_validation_envelope(self):
		status, payload = self._post_method("myapp.api.gateway.create_product_v2", {"item_name": ""})
		self.assertEqual(status, 422)
		self.assertFalse(payload["message"]["ok"])
		self.assertEqual(payload["message"]["code"], "VALIDATION_ERROR")
