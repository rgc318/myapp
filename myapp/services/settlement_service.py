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


def _get_payment_entry_writeoff_defaults(company: str):
	values = frappe.get_cached_value("Company", company, ["write_off_account", "cost_center"], as_dict=True)
	write_off_account = values.get("write_off_account") if values else None
	cost_center = values.get("cost_center") if values else None

	if not write_off_account:
		frappe.throw(_("公司 {0} 尚未配置 Write Off Account。").format(company))

	return {
		"account": write_off_account,
		"cost_center": cost_center,
	}


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


def _apply_return_item_overrides(target_items, item_overrides: dict, *, detail_attrs: tuple[str, ...] = ()):
	filtered_items = []

	for item in target_items:
		override = next(
			(item_overrides.get(getattr(item, attr, None)) for attr in detail_attrs if getattr(item, attr, None)),
			None,
		)
		if not override:
			override = item_overrides.get(item.item_code)
		if not override:
			continue

		if override.get("qty") is not None:
			item.qty = -abs(flt(override["qty"]))
		filtered_items.append(item)

	return filtered_items


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

	settlement_mode = (kwargs.get("settlement_mode") or "partial").strip().lower()
	if settlement_mode not in {"partial", "writeoff"}:
		frappe.throw(_("settlement_mode 只支持 partial 或 writeoff。"))

	request_id = kwargs.get("request_id")

	try:
		def _update_payment_status():
			reference_outstanding = flt(frappe.db.get_value(reference_doctype, reference_name, "outstanding_amount"))
			if reference_outstanding <= 0:
				frappe.throw(_("单据 {0} 当前没有可核销的未收金额。").format(reference_name))

			seed_amount = paid_amount
			if settlement_mode == "writeoff":
				if paid_amount > reference_outstanding:
					frappe.throw(_("writeoff 模式下，paid_amount 不能大于当前未收金额。"))
				seed_amount = reference_outstanding
			elif paid_amount > reference_outstanding:
				# ERPNext 标准 Payment Entry 支持未分配金额：
				# 当前发票只按未收金额核销，超出部分挂为 unallocated amount。
				seed_amount = reference_outstanding

			pe = get_payment_entry(reference_doctype, reference_name, party_amount=seed_amount)
			pe.mode_of_payment = kwargs.get("mode_of_payment") or pe.mode_of_payment or "Cash"
			pe.reference_no = kwargs.get("reference_no") or _("移动端收款")
			pe.reference_date = kwargs.get("reference_date") or nowdate()

			writeoff_amount = 0
			unallocated_amount = 0
			if settlement_mode == "writeoff":
				pe.paid_amount = paid_amount
				pe.received_amount = paid_amount
				pe.set_amounts()

				if pe.difference_amount <= 0:
					frappe.throw(_("当前无需执行差额核销。"))

				writeoff_amount = flt(pe.difference_amount)
				account_details = _get_payment_entry_writeoff_defaults(pe.company)
				account_details["description"] = kwargs.get("writeoff_reason") or _("移动端优惠/抹零结清")
				pe.set_gain_or_loss(account_details=account_details)
			elif paid_amount > seed_amount:
				pe.paid_amount = paid_amount
				pe.received_amount = paid_amount
				pe.set_amounts()
				unallocated_amount = flt(pe.unallocated_amount)

			pe.insert()
			pe.submit()

			return {
				"status": "success",
				"payment_entry": pe.name,
				"settlement_mode": settlement_mode,
				"writeoff_amount": writeoff_amount,
				"unallocated_amount": unallocated_amount,
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
	request_id = kwargs.get("request_id")

	make_return_map = {
		"Sales Invoice": "erpnext.accounts.doctype.sales_invoice.sales_invoice.make_sales_return",
		"Delivery Note": "erpnext.stock.doctype.delivery_note.delivery_note.make_sales_return",
	}
	make_return_path = make_return_map.get(source_doctype)
	if not make_return_path:
		frappe.throw(_("暂不支持对 {0} 执行退货。").format(source_doctype))

	try:
		def _process_sales_return():
			return_doc = frappe.get_attr(make_return_path)(source_name)

			if return_items:
				detail_keys = {
					"Sales Invoice": ("sales_invoice_item", "si_detail"),
					"Delivery Note": ("delivery_note_item", "dn_detail"),
				}[source_doctype]
				detail_attrs = {
					"Sales Invoice": ("sales_invoice_item", "si_detail"),
					"Delivery Note": ("delivery_note_item", "dn_detail"),
				}[source_doctype]
				item_overrides = _build_item_override_map(return_items, detail_keys=detail_keys)
				return_doc.items = _apply_return_item_overrides(
					return_doc.items,
					item_overrides,
					detail_attrs=detail_attrs,
				)
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

		return run_idempotent("process_sales_return", request_id, _process_sales_return)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("退货处理失败"))
		raise
