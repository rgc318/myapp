"""Read-only lifecycle preflight. A preview is not authorization to execute."""

import frappe
from frappe.model.delete_doc import check_if_doc_is_dynamically_linked, check_if_doc_is_linked

from myapp.services.data_permission_service import require_document_permission

MAX_LIFECYCLE_TARGETS = 20
LIFECYCLE_OPERATIONS = {"enable", "disable", "delete"}


def normalize_lifecycle_request(operation, item_codes, reason):
	if not isinstance(operation, str) or operation not in LIFECYCLE_OPERATIONS:
		raise frappe.ValidationError("不支持的商品生命周期操作。")
	if not isinstance(item_codes, list) or not 1 <= len(item_codes) <= MAX_LIFECYCLE_TARGETS:
		raise frappe.ValidationError("请选择 1 至 20 个明确商品编码。")
	if any(not isinstance(code, str) or not code.strip() for code in item_codes):
		raise frappe.ValidationError("商品编码不能为空。")
	codes = [code.strip() for code in item_codes]
	if len(set(codes)) != len(codes):
		raise frappe.ValidationError("目标商品重复，请重新确认完整目标集合。")
	if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
		raise frappe.ValidationError("请填写 1 至 500 字操作原因。")
	return operation, codes, reason.strip()


def _deletion_blockers(item):
	blockers = []
	# Do not run Item.on_trash: it deletes Bin/Item Price and variants.
	for doctype, filters, code, message in (
		("Stock Ledger Entry", {"item_code": item.name}, "PRODUCT_HAS_STOCK_HISTORY", "商品存在库存流水，不能删除。"),
		("Bin", {"item_code": item.name}, "PRODUCT_HAS_STOCK_RECORD", "商品存在库存记录，即使数量为零也不能直接删除。"),
		("Item Price", {"item_code": item.name}, "PRODUCT_HAS_PRICES", "商品存在价格记录，不能隐式连带删除。"),
		("Item", {"variant_of": item.name}, "PRODUCT_HAS_VARIANTS", "商品存在变体，不能隐式连带删除。"),
		("File", {"attached_to_doctype": "Item", "attached_to_name": item.name}, "PRODUCT_HAS_ATTACHMENTS", "商品存在附件，请先在商品资料中明确处理附件。"),
	):
		if frappe.db.exists(doctype, filters):
			blockers.append({"code": code, "message": message})
	if item.get("image"):
		blockers.append({"code": "PRODUCT_HAS_IMAGE", "message": "商品存在封面引用，请先明确处理图片。"})
	try:
		check_if_doc_is_linked(item)
		check_if_doc_is_dynamically_linked(item)
	except frappe.LinkExistsError:
		# Never return the framework exception: it may name a hidden company document.
		frappe.clear_last_message()
		blockers.append({"code": "PRODUCT_HAS_REFERENCES", "message": "商品存在关联引用，不能删除。"})
	return blockers


def preview_product_lifecycle(operation, item_codes, reason):
	"""Internal, non-whitelisted preview; no plan token or execution capability."""
	operation, codes, reason = normalize_lifecycle_request(operation, item_codes, reason)
	items = []
	# Authorize the full target set before reading global reference evidence.
	for code in codes:
		require_document_permission("Item", code, "read")
		items.append(require_document_permission("Item", code, "delete" if operation == "delete" else "write"))
	rows = []
	for item in items:
		blockers = _deletion_blockers(item) if operation == "delete" else []
		disabled = bool(item.get("disabled"))
		rows.append({
			"item_code": item.name,
			"item_name": item.get("item_name"),
			"item_modified": str(item.modified),
			"disabled": disabled,
			"already_in_requested_state": operation != "delete" and disabled == (operation == "disable"),
			"blockers": blockers,
		})
	return {
		"schema_version": "product-lifecycle-preview-v1",
		"operation": operation, "reason": reason, "targets": rows,
		"scope": "shared_item_master",
		"scope_warning": "此操作影响共享商品主档及所有使用该商品的公司，不仅限于当前会话公司。",
		"preflight_passed": not any(row["blockers"] for row in rows),
		"execution_available": False,
	}
