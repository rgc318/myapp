from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from myapp.utils.idempotency import run_idempotent


class TestIdempotency(TestCase):
	@patch("myapp.utils.idempotency.store_idempotent_result")
	@patch("myapp.utils.idempotency.get_idempotent_result")
	def test_run_idempotent_returns_cached_result(self, mock_get_idempotent_result, mock_store_idempotent_result):
		mock_get_idempotent_result.return_value = {"status": "success", "order": "SO-0001"}

		callback_called = False

		def callback():
			nonlocal callback_called
			callback_called = True
			return {"status": "success", "order": "SO-0002"}

		result = run_idempotent("create_order_immediate", "req-1", callback)

		self.assertEqual(result["order"], "SO-0001")
		self.assertFalse(callback_called)
		mock_store_idempotent_result.assert_not_called()

	@patch("myapp.utils.idempotency.store_idempotent_result")
	@patch("myapp.utils.idempotency.filelock")
	@patch("myapp.utils.idempotency.get_idempotent_result")
	def test_run_idempotent_rechecks_cache_inside_lock(
		self, mock_get_idempotent_result, mock_filelock, mock_store_idempotent_result
	):
		mock_get_idempotent_result.side_effect = [
			None,
			{"status": "success", "order": "SO-0009"},
		]
		mock_filelock.return_value = MagicMock()

		callback_called = False

		def callback():
			nonlocal callback_called
			callback_called = True
			return {"status": "success", "order": "SO-0010"}

		result = run_idempotent("create_order", "req-9", callback)

		self.assertEqual(result["order"], "SO-0009")
		self.assertFalse(callback_called)
		mock_store_idempotent_result.assert_not_called()
		mock_filelock.assert_called_once()

	@patch("myapp.utils.idempotency.store_idempotent_result")
	@patch("myapp.utils.idempotency.filelock")
	def test_run_idempotent_without_request_id_skips_lock(self, mock_filelock, mock_store_idempotent_result):
		mock_store_idempotent_result.return_value = {"status": "success", "order": "SO-0011"}

		result = run_idempotent("create_order", None, lambda: {"status": "success", "order": "SO-0011"})

		self.assertEqual(result["order"], "SO-0011")
		mock_filelock.assert_not_called()
