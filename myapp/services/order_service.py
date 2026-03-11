import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from myapp.utils.idempotency import get_idempotent_result, store_idempotent_result


def _coerce_json_value(value, default):
	if value in (None, ""):
		return default
	if isinstance(value, str):
		return frappe.parse_json(value)
	return value


def _validate_order_inputs(customer: str, items: list[dict], company: str | None):
	if not customer:
		frappe.throw(_("客户不能为空。"))

	if not items:
		frappe.throw(_("无法创建空订单，请至少选择一个商品。"))

	if not company:
		frappe.throw(_("请先提供公司，或在当前用户默认值中配置 company。"))


def _validate_warehouse_company(warehouse: str, company: str, item_code: str):
	warehouse_company = frappe.db.get_value("Warehouse", warehouse, "company")
	if not warehouse_company:
		frappe.throw(_("仓库 {0} 不存在。").format(warehouse))

	if warehouse_company != company:
		frappe.throw(
			_("商品 {0} 的仓库 {1} 属于公司 {2}，与订单公司 {3} 不一致。").format(
				item_code, warehouse, warehouse_company, company
			)
		)


def _build_sales_order_item(item: dict, delivery_date: str, default_warehouse: str | None, company: str):
	item_code = item.get("item_code")
	qty = flt(item.get("qty"))
	warehouse = item.get("warehouse") or default_warehouse

	if not item_code:
		frappe.throw(_("订单明细缺少 item_code。"))

	if qty <= 0:
		frappe.throw(_("商品 {0} 的数量必须大于 0。").format(item_code))

	if not warehouse:
		frappe.throw(_("商品 {0} 缺少仓库，请传入 warehouse 或 default_warehouse。").format(item_code))

	_validate_warehouse_company(warehouse, company, item_code)

	row = {
		"item_code": item_code,
		"qty": qty,
		"warehouse": warehouse,
		"delivery_date": item.get("delivery_date") or delivery_date,
	}

	if item.get("uom"):
		row["uom"] = item["uom"]
	if item.get("price") is not None:
		row["rate"] = flt(item["price"])

	return row


def _insert_and_submit(doc):
	doc.insert()
	doc.submit()
	return doc


def _ensure_target_has_items(doc, message: str):
	if not doc.get("items"):
		frappe.throw(message)


def _validate_stock_for_immediate_delivery(items: list[dict]):
	for item in items:
		bin_rows = frappe.get_all(
			"Bin",
			fields=["actual_qty", "reserved_qty"],
			filters={"item_code": item["item_code"], "warehouse": item["warehouse"]},
			limit_page_length=1,
		)
		if not bin_rows:
			frappe.throw(
				_("商品 {0} 在仓库 {1} 没有库存记录，系统按可用库存 0 处理，本次需要 {2}。").format(
					item["item_code"], item["warehouse"], flt(item["qty"])
				)
			)

		bin_row = bin_rows[0]
		actual_qty = flt(bin_row.get("actual_qty"))
		reserved_qty = flt(bin_row.get("reserved_qty"))
		available_qty = actual_qty - reserved_qty

		if available_qty < flt(item["qty"]):
			frappe.throw(
				_(
					"商品 {0} 在仓库 {1} 的可用库存不足。当前库存 {2}，已预留 {3}，可用 {4}，本次需要 {5}。"
				).format(
					item["item_code"],
					item["warehouse"],
					actual_qty,
					reserved_qty,
					available_qty,
					flt(item["qty"]),
				)
			)


def create_order(customer: str, items: list[dict], immediate: bool = False, **kwargs):
	items = _coerce_json_value(items, [])
	company = kwargs.get("company") or frappe.defaults.get_user_default("company")
	delivery_date = kwargs.get("delivery_date") or nowdate()
	default_warehouse = kwargs.get("default_warehouse")
	request_id = kwargs.get("request_id")

	_validate_order_inputs(customer, items, company)

	if cint(immediate):
		if cached_result := get_idempotent_result("create_order_immediate", request_id):
			return cached_result

	try:
		so = frappe.new_doc("Sales Order")
		so.customer = customer
		so.transaction_date = kwargs.get("transaction_date") or nowdate()
		so.delivery_date = delivery_date
		so.company = company
		if kwargs.get("currency"):
			so.currency = kwargs["currency"]
		if kwargs.get("selling_price_list"):
			so.selling_price_list = kwargs["selling_price_list"]
		if kwargs.get("po_no"):
			so.po_no = kwargs["po_no"]
		if kwargs.get("remarks"):
			so.remarks = kwargs["remarks"]

		order_items = []
		for item in items:
			order_item = _build_sales_order_item(item, delivery_date, default_warehouse, company)
			order_items.append(order_item)
			so.append("items", order_item)

		if cint(immediate):
			_validate_stock_for_immediate_delivery(order_items)

			_insert_and_submit(so)

			result = {
				"status": "success",
				"order": so.name,
				"message": _("销售订单 {0} 已创建并提交。").format(so.name),
			}

			if cint(immediate):
				dn = submit_delivery(so.name, kwargs=kwargs)
				si = create_sales_invoice(so.name, kwargs=kwargs)
				result.update(
					{
						"delivery_note": dn["delivery_note"],
						"sales_invoice": si["sales_invoice"],
						"message": _("订单 {0} 已完成下单、发货和开票。").format(so.name),
					}
				)
				store_idempotent_result("create_order_immediate", request_id, result)

			return result
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("订单创建失败"))
		raise


def submit_delivery(order_name: str, delivery_items: list[dict] | None = None, kwargs: dict | None = None):
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

	if not order_name:
		frappe.throw(_("order_name 不能为空。"))

	delivery_items = _coerce_json_value(delivery_items, [])
	kwargs = _coerce_json_value(kwargs, {}) or {}

	try:
		dn = make_delivery_note(order_name, kwargs={"skip_item_mapping": 0})
		_ensure_target_has_items(dn, _("销售订单 {0} 当前没有可发货的商品明细。").format(order_name))

		if delivery_items:
			delivery_qty_map = {d["item_code"]: flt(d["qty"]) for d in delivery_items if d.get("item_code")}
			filtered_items = []
			for item in dn.items:
				if item.item_code not in delivery_qty_map:
					continue
				item.qty = delivery_qty_map[item.item_code]
				filtered_items.append(item)
			dn.items = filtered_items
			_ensure_target_has_items(dn, _("未找到可发货的商品明细。"))

		if kwargs.get("set_posting_time") is not None:
			dn.set_posting_time = cint(kwargs["set_posting_time"])
		if kwargs.get("posting_date"):
			dn.posting_date = kwargs["posting_date"]
		if kwargs.get("posting_time"):
			dn.posting_time = kwargs["posting_time"]
		if kwargs.get("remarks"):
			dn.remarks = kwargs["remarks"]

		_insert_and_submit(dn)

		return {
			"status": "success",
			"delivery_note": dn.name,
			"message": _("发货单 {0} 已创建并提交。").format(dn.name),
		}
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("发货处理失败"))
		raise


def create_sales_invoice(source_name: str, invoice_items: list[dict] | None = None, kwargs: dict | None = None):
	from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

	if not source_name:
		frappe.throw(_("source_name 不能为空。"))

	invoice_items = _coerce_json_value(invoice_items, [])
	kwargs = _coerce_json_value(kwargs, {}) or {}

	try:
		si = make_sales_invoice(source_name)
		_ensure_target_has_items(si, _("销售订单 {0} 当前没有可开票的商品明细。").format(source_name))

		if invoice_items:
			invoice_qty_map = {d["item_code"]: flt(d["qty"]) for d in invoice_items if d.get("item_code")}
			filtered_items = []
			for item in si.items:
				if item.item_code not in invoice_qty_map:
					continue
				item.qty = invoice_qty_map[item.item_code]
				filtered_items.append(item)
			si.items = filtered_items
			_ensure_target_has_items(si, _("未找到可开票的商品明细。"))

		if kwargs.get("due_date"):
			si.due_date = kwargs["due_date"]
		if kwargs.get("remarks"):
			si.remarks = kwargs["remarks"]
		if kwargs.get("update_stock") is not None:
			si.update_stock = cint(kwargs["update_stock"])

		_insert_and_submit(si)

		return {
			"status": "success",
			"sales_invoice": si.name,
			"message": _("销售发票 {0} 已创建并提交。").format(si.name),
		}
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("开票处理失败"))
		raise
