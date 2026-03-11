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


def confirm_pending_document(doctype: str, docname: str, **kwargs):
	from frappe.model.workflow import apply_workflow

	if not doctype or not docname:
		frappe.throw(_("doctype 和 docname 不能为空。"))

	action = kwargs.get("action")
	updates = _coerce_json_value(kwargs.get("updates"), {}) or {}
	submit_on_confirm = cint(kwargs.get("submit_on_confirm", 1))

	try:
		doc = frappe.get_doc(doctype, docname)

		for fieldname, value in updates.items():
			doc.set(fieldname, value)

		if action:
			confirmed_doc = apply_workflow(doc, action)
			return {
				"status": "success",
				"doctype": confirmed_doc.doctype,
				"docname": confirmed_doc.name,
				"docstatus": cint(confirmed_doc.docstatus),
				"workflow_state": confirmed_doc.get("workflow_state"),
				"message": _("单据 {0} 已执行工作流动作 {1}。").format(confirmed_doc.name, action),
			}

		if cint(doc.docstatus) == 0 and submit_on_confirm:
			doc.submit()
			action_name = "submit"
		else:
			doc.save()
			action_name = "save"

		return {
			"status": "success",
			"doctype": doc.doctype,
			"docname": doc.name,
			"docstatus": cint(doc.docstatus),
			"workflow_state": doc.get("workflow_state"),
			"message": _("单据 {0} 已确认，执行动作: {1}。").format(doc.name, action_name),
		}
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("待办单据确认失败"))
		raise


def update_payment_status(reference_doctype: str, reference_name: str, paid_amount: float, **kwargs):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	if not reference_doctype or not reference_name:
		frappe.throw(_("reference_doctype 和 reference_name 不能为空。"))

	paid_amount = flt(paid_amount)
	if paid_amount <= 0:
		frappe.throw(_("paid_amount 必须大于 0。"))

	request_id = kwargs.get("request_id")

	try:
		def _update_payment_status():
			pe = get_payment_entry(reference_doctype, reference_name, party_amount=paid_amount)
			pe.mode_of_payment = kwargs.get("mode_of_payment") or pe.mode_of_payment or "Cash"
			pe.reference_no = kwargs.get("reference_no") or _("移动端收款")
			pe.reference_date = kwargs.get("reference_date") or nowdate()
			pe.insert()
			pe.submit()

			return {
				"status": "success",
				"payment_entry": pe.name,
				"message": _("成功为单据 {0} 录入收款 {1}。").format(reference_name, paid_amount),
			}

		return run_idempotent("update_payment_status", request_id, _update_payment_status)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("收款录入失败"))
		raise


def process_sales_return(source_doctype: str, source_name: str, return_items: list[dict] | None = None, **kwargs):
	if not source_doctype or not source_name:
		frappe.throw(_("source_doctype 和 source_name 不能为空。"))

	return_items = _coerce_json_value(return_items, [])

	make_return_map = {
		"Sales Invoice": "erpnext.accounts.doctype.sales_invoice.sales_invoice.make_sales_return",
		"Delivery Note": "erpnext.stock.doctype.delivery_note.delivery_note.make_sales_return",
	}
	make_return_path = make_return_map.get(source_doctype)
	if not make_return_path:
		frappe.throw(_("暂不支持对 {0} 执行退货。").format(source_doctype))

	try:
		return_doc = frappe.get_attr(make_return_path)(source_name)

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
			"message": _("退货单 {0} 已创建并提交。").format(return_doc.name),
		}
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("退货处理失败"))
		raise
