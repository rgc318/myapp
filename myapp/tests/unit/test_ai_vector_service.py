import hashlib
import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from myapp.services.ai_vector_service import (
	PRODUCT_VECTOR_INDEX_VERSION,
	build_product_vector_document,
	get_product_vector_index_status_v1,
	rebuild_product_vector_index_v1,
	search_products_semantic,
	sync_product_vector_index,
)


class TestAiVectorService(TestCase):
	def test_build_product_vector_document_contains_governed_master_data_only(self):
		item = SimpleNamespace(
			name="ITEM-001",
			item_name="蓝色包装饮料",
			custom_nickname="蓝瓶",
			custom_specification="500ml × 12",
			brand="测试品牌",
			item_group="饮料",
			description="<p>适合聚会整箱销售</p>",
			stock_uom="Nos",
			custom_wholesale_default_uom="Box",
			custom_retail_default_uom="Nos",
			barcodes=[SimpleNamespace(barcode="690000000001")],
			disabled=0,
			is_sales_item=1,
			is_purchase_item=1,
			is_stock_item=1,
			modified="2026-07-14 10:00:00",
		)

		document = build_product_vector_document(item)

		self.assertIn("适合聚会整箱销售", document["text"])
		self.assertNotIn("<p>", document["text"])
		self.assertIn("690000000001", document["text"])
		self.assertEqual(document["index_version"], PRODUCT_VECTOR_INDEX_VERSION)
		self.assertEqual(document["content_hash"], hashlib.sha256(document["text"].encode()).hexdigest())
		self.assertNotIn("price", document)
		self.assertNotIn("qty", document)

	@patch.dict(os.environ, {"MYAPP_AI_VECTOR_SEARCH_ENABLED": "1", "MYAPP_AI_EMBEDDING_MODEL": "erp-embedding"})
	@patch("myapp.services.ai_vector_service.search_product_v2")
	@patch("myapp.services.ai_vector_service.frappe.get_list")
	@patch("myapp.services.ai_vector_service._call_vector_orchestrator")
	def test_semantic_search_reapplies_frappe_permissions_and_business_search(
		self, mock_call, mock_get_list, mock_search_product,
	):
		mock_call.return_value = {
			"matches": [
				{"item_code": "ITEM-ALLOWED", "score": 0.93, "index_version": PRODUCT_VECTOR_INDEX_VERSION},
				{"item_code": "ITEM-HIDDEN", "score": 0.92, "index_version": PRODUCT_VECTOR_INDEX_VERSION},
			],
			"embedding_model": "erp-embedding",
			"collection": "myapp-products-v1",
		}
		mock_get_list.return_value = ["ITEM-ALLOWED"]
		mock_search_product.return_value = {
			"data": [{"item_code": "ITEM-ALLOWED", "item_name": "聚会分享装饮料", "uom": "Box"}]
		}

		result = search_products_semantic(
			"适合聚会整箱卖的饮料",
			company="Test Company",
			limit=8,
			item_context="sales",
		)

		self.assertTrue(result["available"])
		self.assertEqual([row["item_code"] for row in result["rows"]], ["ITEM-ALLOWED"])
		self.assertEqual(result["rows"][0]["semantic_score"], 0.93)
		mock_search_product.assert_called_once_with(
			search_key="ITEM-ALLOWED",
			company="Test Company",
			limit=1,
			disabled=0,
			item_context="sales",
		)

	@patch.dict(os.environ, {"MYAPP_AI_VECTOR_SEARCH_ENABLED": "1", "MYAPP_AI_EMBEDDING_MODEL": "erp-embedding"})
	@patch("myapp.services.ai_vector_service._record_state")
	@patch("myapp.services.ai_vector_service._call_vector_orchestrator")
	def test_sync_records_index_state_after_orchestrator_accepts_document(
		self, mock_call, mock_record_state,
	):
		mock_call.return_value = {"accepted": True, "indexed_count": 1, "embedding_model": "erp-embedding"}
		with patch("myapp.services.ai_vector_service.frappe") as mock_frappe:
			mock_frappe.db.exists.return_value = True
			mock_frappe.db.table_exists.return_value = False
			mock_frappe.get_doc.return_value = SimpleNamespace(
				name="ITEM-001", item_name="测试商品", barcodes=[], disabled=0,
				is_sales_item=1, is_purchase_item=1, modified="2026-07-14 10:00:00",
			)
			result = sync_product_vector_index("ITEM-001")

		self.assertEqual(result["status"], "indexed")
		self.assertEqual(mock_record_state.call_count, 2)
		self.assertEqual(mock_record_state.call_args.kwargs["status"], "indexed")

	@patch.dict(os.environ, {
		"MYAPP_AI_VECTOR_SEARCH_ENABLED": "1",
		"MYAPP_AI_EMBEDDING_MODEL": "erp-embedding",
		"MYAPP_AI_QDRANT_COLLECTION": "myapp-products-v1",
	})
	@patch("myapp.services.ai_vector_service._record_state")
	@patch("myapp.services.ai_vector_service._call_vector_orchestrator")
	def test_sync_skips_unchanged_document_for_same_model_and_collection(
		self, mock_call, mock_record_state,
	):
		item = SimpleNamespace(
			name="ITEM-001", item_name="测试商品", barcodes=[], disabled=0,
			is_sales_item=1, is_purchase_item=1, is_stock_item=1,
			modified="2026-07-14 10:00:00",
		)
		document = build_product_vector_document(item)
		with patch("myapp.services.ai_vector_service.frappe") as mock_frappe:
			mock_frappe.db.exists.return_value = True
			mock_frappe.db.table_exists.return_value = True
			mock_frappe.db.sql.return_value = [{
				"content_hash": document["content_hash"],
				"index_version": PRODUCT_VECTOR_INDEX_VERSION,
				"embedding_model": "erp-embedding",
				"vector_collection": "myapp-products-v1",
				"status": "indexed",
			}]
			mock_frappe.get_doc.return_value = item
			result = sync_product_vector_index("ITEM-001")

		self.assertEqual(result["status"], "unchanged")
		mock_call.assert_not_called()
		self.assertEqual(mock_record_state.call_args.kwargs["status"], "indexed")

	@patch("myapp.services.ai_vector_service._call_vector_orchestrator")
	def test_admin_status_reports_provider_and_index_counts(self, mock_call):
		mock_call.return_value = {
			"reachable": True, "collection_exists": True, "points_count": 8,
			"indexed_vectors_count": 8, "vector_size": 384,
		}
		with patch("myapp.services.ai_vector_service.frappe") as mock_frappe:
			mock_frappe.get_roles.return_value = ["System Manager"]
			mock_frappe.db.table_exists.return_value = True
			mock_frappe.db.count.return_value = 10
			mock_frappe.db.sql.side_effect = [
				[SimpleNamespace(status="indexed", count=8), SimpleNamespace(status="failed", count=1)],
				[(2,)],
				[SimpleNamespace(item_code="ITEM-FAILED", last_error="timeout", last_attempt_at="2026-07-14")],
			]
			result = get_product_vector_index_status_v1()

		self.assertEqual(result["data"]["counts"]["indexed"], 8)
		self.assertEqual(result["data"]["due_count"], 2)
		self.assertEqual(result["data"]["provider"]["points_count"], 8)

	@patch.dict(os.environ, {
		"MYAPP_AI_VECTOR_SEARCH_ENABLED": "1",
		"MYAPP_AI_EMBEDDING_MODEL": "erp-embedding",
	})
	def test_admin_rebuild_queues_only_existing_requested_items(self):
		with patch("myapp.services.ai_vector_service.frappe") as mock_frappe:
			mock_frappe.get_roles.return_value = ["System Manager"]
			mock_frappe.get_all.return_value = ["ITEM-001"]
			result = rebuild_product_vector_index_v1(item_codes=["ITEM-001", "ITEM-MISSING"])

		self.assertEqual(result["data"]["queued_count"], 1)
		self.assertEqual(result["data"]["item_codes"], ["ITEM-001"])
		mock_frappe.enqueue.assert_called_once()

	def test_vector_admin_endpoints_reject_non_system_managers(self):
		with patch("myapp.services.ai_vector_service.frappe") as mock_frappe:
			mock_frappe.get_roles.return_value = ["Sales User"]
			mock_frappe.PermissionError = PermissionError
			with self.assertRaises(PermissionError):
				get_product_vector_index_status_v1()
