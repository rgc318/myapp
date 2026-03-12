import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from myapp.utils.idempotency import run_idempotent


def _coerce_json_value(value, default):
	if value in (None, ""):
		return default
	if isinstance(value, str):
		return frappe.parse_json(value)
	return value


def _insert_and_submit(doc):
	doc.insert()
	doc.submit()
	return doc


def _ensure_target_has_items(doc, message: str):
	if not doc.get("items"):
		frappe.throw(message)


def _build_item_override_map(items, *, detail_keys: tuple[str, ...]):
	override_map = {}

	for row in items or []:
		if not isinstance(row, dict):
			continue

		detail_key = next((row.get(key) for key in detail_keys if row.get(key)), None)
		lookup_key = detail_key or row.get("item_code")
		if not lookup_key:
			continue

		override_map[lookup_key] = row

	return override_map


def _apply_item_overrides(target_items, item_overrides: dict, *, detail_attr: str | None = None):
	filtered_items = []

	for item in target_items:
		lookup_key = getattr(item, detail_attr, None) if detail_attr else None
		override = item_overrides.get(lookup_key) if lookup_key else None
		if not override:
			override = item_overrides.get(item.item_code)
		if not override:
			continue

		if override.get("qty") is not None:
			item.qty = flt(override["qty"])
		if override.get("price") is not None:
			item.rate = flt(override["price"])
		filtered_items.append(item)

	return filtered_items


def _validate_purchase_inputs(supplier: str, items: list[dict], company: str | None):
	if not supplier:
		frappe.throw(_("供应商不能为空。"))

	if not items:
		frappe.throw(_("无法创建空采购订单，请至少选择一个商品。"))

	if not company:
		frappe.throw(_("请先提供公司，或在当前用户默认值中配置 company。"))


def _validate_warehouse_company(warehouse: str, company: str, item_code: str):
	warehouse_company = frappe.db.get_value("Warehouse", warehouse, "company")
	if not warehouse_company:
		frappe.throw(_("仓库 {0} 不存在。").format(warehouse))

	if warehouse_company != company:
		frappe.throw(
			_("商品 {0} 的仓库 {1} 属于公司 {2}，与采购单公司 {3} 不一致。").format(
				item_code, warehouse, warehouse_company, company
			)
		)


def _build_purchase_order_item(item: dict, schedule_date: str, default_warehouse: str | None, company: str):
	item_code = item.get("item_code")
	qty = flt(item.get("qty"))
	warehouse = item.get("warehouse") or default_warehouse

	if not item_code:
		frappe.throw(_("采购明细缺少 item_code。"))

	if qty <= 0:
		frappe.throw(_("商品 {0} 的数量必须大于 0。").format(item_code))

	if not warehouse:
		frappe.throw(_("商品 {0} 缺少仓库，请传入 warehouse 或 default_warehouse。").format(item_code))

	_validate_warehouse_company(warehouse, company, item_code)

	row = {
		"item_code": item_code,
		"qty": qty,
		"warehouse": warehouse,
		"schedule_date": item.get("schedule_date") or schedule_date,
	}

	if item.get("uom"):
		row["uom"] = item["uom"]
	if item.get("price") is not None:
		row["rate"] = flt(item["price"])

	return row


def create_purchase_order(supplier: str, items, **kwargs):
	items = _coerce_json_value(items, [])
	company = kwargs.get("company") or frappe.defaults.get_user_default("company")
	schedule_date = kwargs.get("schedule_date") or nowdate()
	default_warehouse = kwargs.get("default_warehouse")
	request_id = kwargs.get("request_id")

	_validate_purchase_inputs(supplier, items, company)

	try:
		def _create_purchase_order():
			po = frappe.new_doc("Purchase Order")
			po.supplier = supplier
			po.transaction_date = kwargs.get("transaction_date") or nowdate()
			po.schedule_date = schedule_date
			po.company = company
			if kwargs.get("currency"):
				po.currency = kwargs["currency"]
			if kwargs.get("buying_price_list"):
				po.buying_price_list = kwargs["buying_price_list"]
			if kwargs.get("supplier_ref"):
				po.supplier_ref = kwargs["supplier_ref"]
			if kwargs.get("remarks"):
				po.remarks = kwargs["remarks"]

			for item in items:
				po.append("items", _build_purchase_order_item(item, schedule_date, default_warehouse, company))

			_insert_and_submit(po)

			return {
				"status": "success",
				"purchase_order": po.name,
				"message": _("采购订单 {0} 已创建并提交。").format(po.name),
			}

		return run_idempotent("create_purchase_order", request_id, _create_purchase_order)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("采购订单创建失败"))
		raise


def receive_purchase_order(order_name: str, receipt_items=None, kwargs: dict | None = None):
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

	if not order_name:
		frappe.throw(_("order_name 不能为空。"))

	receipt_items = _coerce_json_value(receipt_items, [])
	kwargs = _coerce_json_value(kwargs, {}) or {}
	request_id = kwargs.get("request_id")

	try:
		def _receive_purchase_order():
			pr = make_purchase_receipt(order_name, args={"filtered_children": []})
			_ensure_target_has_items(pr, _("采购订单 {0} 当前没有可收货的商品明细。").format(order_name))

			if receipt_items:
				item_overrides = _build_item_override_map(
					receipt_items,
					detail_keys=("purchase_order_item", "po_detail"),
				)
				pr.items = _apply_item_overrides(pr.items, item_overrides, detail_attr="purchase_order_item")
				_ensure_target_has_items(pr, _("未找到可收货的商品明细。"))

			if kwargs.get("set_posting_time") is not None:
				pr.set_posting_time = cint(kwargs["set_posting_time"])
			if kwargs.get("posting_date"):
				pr.posting_date = kwargs["posting_date"]
			if kwargs.get("posting_time"):
				pr.posting_time = kwargs["posting_time"]
			if kwargs.get("remarks"):
				pr.remarks = kwargs["remarks"]

			_insert_and_submit(pr)

			return {
				"status": "success",
				"purchase_receipt": pr.name,
				"message": _("采购收货单 {0} 已创建并提交。").format(pr.name),
			}

		return run_idempotent("receive_purchase_order", request_id, _receive_purchase_order)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("采购收货处理失败"))
		raise


def create_purchase_invoice(source_name: str, invoice_items=None, kwargs: dict | None = None):
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

	if not source_name:
		frappe.throw(_("source_name 不能为空。"))

	invoice_items = _coerce_json_value(invoice_items, [])
	kwargs = _coerce_json_value(kwargs, {}) or {}
	request_id = kwargs.get("request_id")

	try:
		def _create_purchase_invoice():
			pi = make_purchase_invoice(source_name)
			_ensure_target_has_items(pi, _("采购订单 {0} 当前没有可开票的商品明细。").format(source_name))

			if invoice_items:
				item_overrides = _build_item_override_map(
					invoice_items,
					detail_keys=("purchase_order_item", "po_detail"),
				)
				pi.items = _apply_item_overrides(pi.items, item_overrides, detail_attr="po_detail")
				_ensure_target_has_items(pi, _("未找到可开票的商品明细。"))

			if kwargs.get("due_date"):
				pi.due_date = kwargs["due_date"]
			if kwargs.get("remarks"):
				pi.remarks = kwargs["remarks"]
			if kwargs.get("update_stock") is not None:
				pi.update_stock = cint(kwargs["update_stock"])

			_insert_and_submit(pi)

			return {
				"status": "success",
				"purchase_invoice": pi.name,
				"message": _("采购发票 {0} 已创建并提交。").format(pi.name),
			}

		return run_idempotent("create_purchase_invoice", request_id, _create_purchase_invoice)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("采购开票处理失败"))
		raise


def create_purchase_invoice_from_receipt(
	receipt_name: str, invoice_items=None, kwargs: dict | None = None
):
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

	if not receipt_name:
		frappe.throw(_("receipt_name 不能为空。"))

	invoice_items = _coerce_json_value(invoice_items, [])
	kwargs = _coerce_json_value(kwargs, {}) or {}
	request_id = kwargs.get("request_id")

	try:
		def _create_purchase_invoice_from_receipt():
			pi = make_purchase_invoice(receipt_name)
			_ensure_target_has_items(pi, _("采购收货单 {0} 当前没有可开票的商品明细。").format(receipt_name))

			if invoice_items:
				item_overrides = _build_item_override_map(
					invoice_items,
					detail_keys=("purchase_receipt_item", "pr_detail"),
				)
				pi.items = _apply_item_overrides(pi.items, item_overrides, detail_attr="pr_detail")
				_ensure_target_has_items(pi, _("未找到可开票的采购收货明细。"))

			if kwargs.get("due_date"):
				pi.due_date = kwargs["due_date"]
			if kwargs.get("remarks"):
				pi.remarks = kwargs["remarks"]
			if kwargs.get("update_stock") is not None:
				pi.update_stock = cint(kwargs["update_stock"])

			_insert_and_submit(pi)

			return {
				"status": "success",
				"purchase_invoice": pi.name,
				"message": _("采购发票 {0} 已根据收货单创建并提交。").format(pi.name),
			}

		return run_idempotent(
			"create_purchase_invoice_from_receipt",
			request_id,
			_create_purchase_invoice_from_receipt,
		)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("基于采购收货单开票失败"))
		raise


def record_supplier_payment(reference_name: str, paid_amount: float, **kwargs):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	if not reference_name:
		frappe.throw(_("reference_name 不能为空。"))

	paid_amount = flt(paid_amount)
	if paid_amount <= 0:
		frappe.throw(_("paid_amount 必须大于 0。"))

	request_id = kwargs.get("request_id")

	try:
		def _record_supplier_payment():
			pe = get_payment_entry("Purchase Invoice", reference_name, party_amount=paid_amount)
			pe.mode_of_payment = kwargs.get("mode_of_payment") or pe.mode_of_payment or "Cash"
			pe.reference_no = kwargs.get("reference_no") or _("采购付款")
			pe.reference_date = kwargs.get("reference_date") or nowdate()
			pe.insert()
			pe.submit()

			return {
				"status": "success",
				"payment_entry": pe.name,
				"message": _("成功为采购发票 {0} 录入付款 {1}。").format(reference_name, paid_amount),
			}

		return run_idempotent("record_supplier_payment", request_id, _record_supplier_payment)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("采购付款录入失败"))
		raise


def process_purchase_return(source_doctype: str, source_name: str, return_items=None, **kwargs):
	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	if not source_doctype or not source_name:
		frappe.throw(_("source_doctype 和 source_name 不能为空。"))

	return_items = _coerce_json_value(return_items, [])
	request_id = kwargs.get("request_id")

	if source_doctype not in {"Purchase Receipt", "Purchase Invoice"}:
		frappe.throw(_("暂不支持对 {0} 执行采购退货。").format(source_doctype))

	try:
		def _process_purchase_return():
			return_doc = make_return_doc(source_doctype, source_name)

			if return_items:
				item_qty_map = {d["item_code"]: flt(d["qty"]) for d in return_items if d.get("item_code")}
				filtered_items = []
				for item in return_doc.items:
					if item.item_code not in item_qty_map:
						continue
					item.qty = -abs(item_qty_map[item.item_code])
					filtered_items.append(item)
				return_doc.items = filtered_items
				if not return_doc.items:
					frappe.throw(_("未找到可退货的商品明细。"))

			if kwargs.get("posting_date"):
				return_doc.posting_date = kwargs["posting_date"]
			if kwargs.get("posting_time"):
				return_doc.posting_time = kwargs["posting_time"]
			if kwargs.get("set_posting_time") is not None:
				return_doc.set_posting_time = kwargs["set_posting_time"]
			if kwargs.get("remarks"):
				return_doc.remarks = kwargs["remarks"]

			return_doc.insert()
			return_doc.submit()

			return {
				"status": "success",
				"return_document": return_doc.name,
				"return_doctype": return_doc.doctype,
				"message": _("采购退货单 {0} 已创建并提交。").format(return_doc.name),
			}

		return run_idempotent("process_purchase_return", request_id, _process_purchase_return)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("采购退货处理失败"))
		raise
