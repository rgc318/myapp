import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from myapp.services.return_service import build_return_submission_payload
from myapp.utils.idempotency import run_idempotent
from myapp.services.data_permission_service import require_document_permission


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


def _apply_payment_entry_writeoff(pe, *, paid_amount: float, writeoff_reason: str | None = None):
	paid_from_currency = getattr(pe, "paid_from_account_currency", None)
	paid_to_currency = getattr(pe, "paid_to_account_currency", None)
	paid_from_currency = paid_from_currency.strip() if isinstance(paid_from_currency, str) else ""
	paid_to_currency = paid_to_currency.strip() if isinstance(paid_to_currency, str) else ""
	if paid_from_currency and paid_to_currency and paid_from_currency != paid_to_currency:
		frappe.throw(_("当前暂不支持多币种差额核销，请使用标准 Payment Entry 完成处理。"))

	# ERPNext 的同币种 Payment Entry 会让 received_amount 跟随 paid_amount。
	# 保留来源发票的完整 allocated_amount，仅把实际现金收付金额设置到付款单，
	# 再由 deductions 抵销 difference_amount。
	pe.paid_amount = paid_amount
	pe.received_amount = paid_amount
	pe.set_amounts()

	difference_amount = flt(pe.difference_amount)
	if abs(difference_amount) <= 0.0001:
		frappe.throw(_("当前无需执行差额核销。"))

	account_details = _get_payment_entry_writeoff_defaults(pe.company)
	account_details["description"] = writeoff_reason or _("移动端优惠/抹零结清")
	pe.set_gain_or_loss(account_details=account_details)
	return abs(difference_amount)


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
			_validate_payment_reference_can_receive(reference_doctype, reference_name)
			reference_outstanding = _get_payment_reference_outstanding(reference_doctype, reference_name)
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

			payment_type = (getattr(pe, "payment_type", None) or "").strip()
			writeoff_amount = 0
			unallocated_amount = 0
			if settlement_mode == "writeoff":
				writeoff_amount = _apply_payment_entry_writeoff(
					pe,
					paid_amount=paid_amount,
					writeoff_reason=kwargs.get("writeoff_reason"),
				)
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
				"message": _("成功为单据 {0} 录入{1} {2}。").format(
					reference_name,
					_("付款") if payment_type == "Pay" else _("收款"),
					paid_amount,
				),
			}

		return run_idempotent("update_payment_status", request_id, _update_payment_status)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("收款录入失败"))
		raise


def _get_sales_invoice_full_return_hint(reference_doctype: str, reference_name: str):
	if reference_doctype != "Sales Invoice":
		return None

	invoice = frappe.db.get_value(
		"Sales Invoice",
		reference_name,
		["name", "is_return", "docstatus", "rounded_total", "grand_total"],
		as_dict=True,
	)
	if not isinstance(invoice, dict):
		return None
	if cint(invoice.get("is_return")):
		return _("销售退货发票应通过客户退款流程处理，不能登记客户收款。")
	if cint(invoice.get("docstatus")) != 1:
		return None

	invoice_amount = abs(flt(invoice.get("rounded_total") or invoice.get("grand_total") or 0))
	if invoice_amount <= 0:
		return None

	return_rows = frappe.get_all(
		"Sales Invoice",
		filters={
			"return_against": reference_name,
			"is_return": 1,
			"docstatus": 1,
		},
		fields=["name", "rounded_total", "grand_total"],
		limit_page_length=0,
	)
	returned_amount = sum(abs(flt(row.get("rounded_total") or row.get("grand_total") or 0)) for row in return_rows)
	if returned_amount + 0.0001 >= invoice_amount:
		return _("来源销售发票已被退货发票全额冲回，不能继续登记客户收款；如需重新销售，请重新发货并开票。")
	return None


def _validate_payment_reference_can_receive(reference_doctype: str, reference_name: str):
	hint = _get_sales_invoice_full_return_hint(reference_doctype, reference_name)
	if hint:
		frappe.throw(hint)


def _get_payment_reference_outstanding(reference_doctype: str, reference_name: str):
	if reference_doctype != "Sales Invoice":
		return flt(frappe.db.get_value(reference_doctype, reference_name, "outstanding_amount"))

	invoice = frappe.db.get_value(
		"Sales Invoice",
		reference_name,
		["name", "is_return", "rounded_total", "grand_total", "base_rounded_total", "outstanding_amount"],
		as_dict=True,
	)
	if not isinstance(invoice, dict):
		return flt(invoice)
	if cint(invoice.get("is_return")):
		return flt(invoice.get("outstanding_amount") or 0)

	invoice_amount = abs(
		flt(
			invoice.get("rounded_total")
			or invoice.get("grand_total")
			or invoice.get("base_rounded_total")
			or 0
		)
	)
	raw_outstanding = flt(invoice.get("outstanding_amount") or 0)
	if invoice_amount <= 0:
		return raw_outstanding

	return_rows = frappe.get_all(
		"Sales Invoice",
		filters={
			"return_against": reference_name,
			"is_return": 1,
			"docstatus": 1,
		},
		fields=["name", "rounded_total", "grand_total", "base_rounded_total"],
		limit_page_length=0,
	)
	returned_amount = sum(
		abs(
			flt(
				row.get("rounded_total")
				or row.get("grand_total")
				or row.get("base_rounded_total")
				or 0
			)
		)
		for row in return_rows
	)
	if returned_amount <= 0:
		return raw_outstanding

	paid_amount = max(invoice_amount - raw_outstanding, 0)
	net_invoice_amount = max(invoice_amount - returned_amount, 0)
	return max(net_invoice_amount - paid_amount, 0)


def cancel_payment_entry(payment_entry_name: str, **kwargs):
	if not payment_entry_name:
		frappe.throw(_("payment_entry_name 不能为空。"))

	request_id = kwargs.get("request_id")

	try:
		def _cancel_payment_entry():
			pe = frappe.get_doc("Payment Entry", payment_entry_name)
			references = [
				{
					"reference_doctype": getattr(row, "reference_doctype", None),
					"reference_name": getattr(row, "reference_name", None),
					"allocated_amount": flt(getattr(row, "allocated_amount", 0) or 0),
					**_get_invoice_reference_meta(
						getattr(row, "reference_doctype", None),
						getattr(row, "reference_name", None),
					),
				}
				for row in (pe.get("references") or [])
				if getattr(row, "reference_name", None)
			]

			if cint(pe.docstatus) == 2:
				return {
					"status": "success",
					"payment_entry": pe.name,
					"document_status": "cancelled",
					"references": references,
					"message": _("收款单 {0} 已处于作废状态。").format(pe.name),
				}

			if cint(pe.docstatus) != 1:
				frappe.throw(_("只有已提交的收款单才能作废。"))

			_ensure_customer_receipt_cancel_allowed(pe, references)
			pe.cancel()

			return {
				"status": "success",
				"payment_entry": pe.name,
				"document_status": "cancelled",
				"references": references,
				"message": _("收款单 {0} 已作废。").format(pe.name),
			}

		return run_idempotent("cancel_payment_entry", request_id, _cancel_payment_entry)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("收款单作废失败"))
		raise


def _payment_entry_document_status(docstatus: int):
	if cint(docstatus) == 2:
		return "cancelled"
	if cint(docstatus) == 1:
		return "submitted"
	return "draft"


def _payment_entry_direction(payment_type: str | None):
	if payment_type == "Receive":
		return "in"
	if payment_type == "Pay":
		return "out"
	return "transfer"


def _payment_entry_amount(payment_entry):
	payment_type = payment_entry.get("payment_type")
	if payment_type == "Receive":
		return flt(payment_entry.get("received_amount") or payment_entry.get("paid_amount") or 0)
	if payment_type == "Pay":
		return flt(payment_entry.get("paid_amount") or payment_entry.get("received_amount") or 0)
	return flt(payment_entry.get("paid_amount") or payment_entry.get("received_amount") or 0)


def _payment_entry_currency(payment_entry):
	if payment_entry.get("payment_type") == "Receive":
		return payment_entry.get("paid_to_account_currency") or payment_entry.get("paid_from_account_currency")
	return payment_entry.get("paid_from_account_currency") or payment_entry.get("paid_to_account_currency")


def _payment_entry_business_type(payment_entry, references: list[dict]):
	payment_type = payment_entry.get("payment_type")
	party_type = payment_entry.get("party_type")
	reference_doctypes = {row.get("reference_doctype") for row in references}
	has_return_invoice = any(row.get("is_return") for row in references)

	if payment_type == "Internal Transfer":
		return "internal_transfer"
	if party_type == "Customer" and payment_type == "Receive":
		return "customer_refund" if has_return_invoice else "customer_receipt"
	if party_type == "Customer" and payment_type == "Pay":
		return "customer_refund"
	if party_type == "Supplier" and payment_type == "Pay":
		return "supplier_refund" if has_return_invoice else "supplier_payment"
	if party_type == "Supplier" and payment_type == "Receive":
		return "supplier_refund"
	if "Sales Invoice" in reference_doctypes:
		return "customer_settlement"
	if "Purchase Invoice" in reference_doctypes:
		return "supplier_settlement"
	return "other"


def _get_invoice_reference_meta(reference_doctype: str | None, reference_name: str | None):
	if reference_doctype not in {"Sales Invoice", "Purchase Invoice"} or not reference_name:
		return {}
	values = frappe.db.get_value(
		reference_doctype,
		reference_name,
		["is_return", "return_against"],
		as_dict=True,
	)
	if not values:
		return {}
	return {
		"is_return": bool(cint(values.get("is_return"))),
		"return_against": values.get("return_against"),
	}


def _build_payment_entry_references(payment_entry):
	references = []
	for row in payment_entry.get("references") or []:
		reference_doctype = getattr(row, "reference_doctype", None)
		reference_name = getattr(row, "reference_name", None)
		meta = _get_invoice_reference_meta(reference_doctype, reference_name)
		references.append(
			{
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"total_amount": flt(getattr(row, "total_amount", 0) or 0),
				"outstanding_amount": flt(getattr(row, "outstanding_amount", 0) or 0),
				"allocated_amount": flt(getattr(row, "allocated_amount", 0) or 0),
				"exchange_rate": flt(getattr(row, "exchange_rate", 0) or 0),
				"due_date": getattr(row, "due_date", None),
				"account": getattr(row, "account", None),
				**meta,
			}
		)
	return references


def _build_payment_entry_deductions(payment_entry):
	return [
		{
			"account": getattr(row, "account", None),
			"cost_center": getattr(row, "cost_center", None),
			"amount": flt(getattr(row, "amount", 0) or 0),
			"description": getattr(row, "description", None),
		}
		for row in payment_entry.get("deductions") or []
	]


def _build_payment_entry_links(references: list[dict]):
	links = {
		"sales_orders": [],
		"sales_invoices": [],
		"purchase_orders": [],
		"purchase_invoices": [],
		"return_invoices": [],
	}
	seen = {key: set() for key in links}

	def add_link(key: str, value: str | None):
		if not value or value in seen[key]:
			return
		seen[key].add(value)
		links[key].append(value)

	for row in references:
		reference_doctype = row.get("reference_doctype")
		reference_name = row.get("reference_name")
		if reference_doctype == "Sales Order":
			add_link("sales_orders", reference_name)
		elif reference_doctype == "Purchase Order":
			add_link("purchase_orders", reference_name)
		elif reference_doctype == "Sales Invoice":
			if row.get("is_return"):
				add_link("return_invoices", reference_name)
			else:
				add_link("sales_invoices", reference_name)
			add_link("sales_invoices", row.get("return_against"))
		elif reference_doctype == "Purchase Invoice":
			if row.get("is_return"):
				add_link("return_invoices", reference_name)
			else:
				add_link("purchase_invoices", reference_name)
			add_link("purchase_invoices", row.get("return_against"))

	return links


def _build_payment_entry_cancel_hint(payment_entry):
	if cint(payment_entry.get("docstatus")) == 1:
		return ""
	if cint(payment_entry.get("docstatus")) == 2:
		return _("当前收付款单已经作废。")
	return _("只有已提交的收付款单才能作废。")


def get_payment_entry_detail(payment_entry_name: str):
	if not payment_entry_name:
		frappe.throw(_("payment_entry_name 不能为空。"))

	try:
		payment_entry = require_document_permission("Payment Entry", payment_entry_name, "read")
		references = _build_payment_entry_references(payment_entry)
		deductions = _build_payment_entry_deductions(payment_entry)
		cancel_hint = _build_payment_entry_cancel_hint(payment_entry)

		return {
			"status": "success",
			"message": _("收付款单详情获取成功。"),
			"data": {
				"name": payment_entry.name,
				"company": payment_entry.get("company"),
				"posting_date": payment_entry.get("posting_date"),
				"docstatus": cint(payment_entry.get("docstatus")),
				"document_status": _payment_entry_document_status(payment_entry.get("docstatus")),
				"payment_type": payment_entry.get("payment_type"),
				"direction": _payment_entry_direction(payment_entry.get("payment_type")),
				"business_type": _payment_entry_business_type(payment_entry, references),
				"party_type": payment_entry.get("party_type"),
				"party": payment_entry.get("party"),
				"party_name": payment_entry.get("party_name") or payment_entry.get("party"),
				"mode_of_payment": payment_entry.get("mode_of_payment"),
				"paid_from": payment_entry.get("paid_from"),
				"paid_to": payment_entry.get("paid_to"),
				"paid_amount": flt(payment_entry.get("paid_amount") or 0),
				"received_amount": flt(payment_entry.get("received_amount") or 0),
				"amount": _payment_entry_amount(payment_entry),
				"unallocated_amount": flt(payment_entry.get("unallocated_amount") or 0),
				"difference_amount": flt(payment_entry.get("difference_amount") or 0),
				"currency": _payment_entry_currency(payment_entry),
				"reference_no": payment_entry.get("reference_no"),
				"reference_date": payment_entry.get("reference_date"),
				"remarks": payment_entry.get("remarks"),
				"references": references,
				"deductions": deductions,
				"links": _build_payment_entry_links(references),
				"actions": {
					"can_cancel": not cancel_hint,
					"cancel_hint": cancel_hint,
				},
			},
		}
	except frappe.DoesNotExistError:
		raise
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("收付款单详情获取失败"))
		raise


def _build_refund_invoice_snapshot(invoice):
	if not invoice:
		return None

	return {
		"name": invoice.name,
		"document_status": "cancelled" if cint(invoice.docstatus) == 2 else "submitted" if cint(invoice.docstatus) == 1 else "draft",
		"docstatus": cint(invoice.docstatus),
		"is_return": bool(cint(invoice.get("is_return"))),
			"return_against": invoice.get("return_against"),
			"customer": invoice.get("customer"),
			"customer_name": invoice.get("customer_name") or invoice.get("customer"),
			"supplier": invoice.get("supplier"),
			"supplier_name": invoice.get("supplier_name") or invoice.get("supplier"),
			"company": invoice.get("company"),
		"currency": invoice.get("currency"),
		"posting_date": invoice.get("posting_date"),
		"grand_total": flt(invoice.get("rounded_total") or invoice.get("grand_total") or 0),
		"outstanding_amount": flt(invoice.get("outstanding_amount") or 0),
	}


def _build_customer_refund_action_hint(*, return_invoice, refundable_amount: float):
	if cint(return_invoice.docstatus) != 1:
		return _("只有已提交的销售退货发票才能登记退款。")
	if not cint(return_invoice.get("is_return")):
		return _("只能基于销售退货发票登记客户退款。")
	if refundable_amount <= 0:
		return _("当前退货发票没有可退金额。")
	return ""


def _build_supplier_refund_action_hint(*, return_invoice, refundable_amount: float):
	if cint(return_invoice.docstatus) != 1:
		return _("只有已提交的采购退货发票才能登记退款。")
	if not cint(return_invoice.get("is_return")):
		return _("只能基于采购退货发票登记供应商退款。")
	if refundable_amount <= 0:
		return _("当前采购退货发票没有可退金额。")
	return ""


def _sum_abs_allocated_amount(entries: list[dict]):
	return sum(abs(flt(entry.get("allocated_amount") or 0)) for entry in entries or [])


def _sum_actual_paid_amount(entries: list[dict]):
	return sum(max(flt(entry.get("actual_paid_amount") or entry.get("allocated_amount") or 0), 0) for entry in entries or [])


def _get_customer_refund_entries_for_source_invoice(source_invoice_name: str):
	if not source_invoice_name:
		return []

	from myapp.services.order_service import _collect_sales_invoice_payment_entries

	return_invoice_names = _get_return_invoice_names_for_source("Sales Invoice", source_invoice_name)
	if not return_invoice_names:
		return []

	return _collect_sales_invoice_payment_entries(return_invoice_names)


def _ensure_customer_receipt_cancel_allowed(payment_entry, references: list[dict]):
	blocked_sources = []
	for row in references or []:
		if row.get("reference_doctype") != "Sales Invoice":
			continue
		if row.get("is_return"):
			continue

		source_invoice_name = row.get("reference_name")
		refund_entries = _get_customer_refund_entries_for_source_invoice(source_invoice_name)
		if refund_entries:
			blocked_sources.append(
				{
					"source_invoice": source_invoice_name,
					"refund_entries": refund_entries,
				}
			)

	if not blocked_sources:
		return

	first = blocked_sources[0]
	refund_names = [
		entry.get("payment_entry")
		for entry in first.get("refund_entries") or []
		if entry.get("payment_entry")
	]
	frappe.throw(
		_("销售发票 {0} 已存在客户退款 {1}，请先取消客户退款后再取消原客户收款。").format(
			first.get("source_invoice"),
			"、".join(refund_names) if refund_names else "",
		)
	)


def _collect_purchase_invoice_payment_entries(invoice_names: list[str]):
	if not invoice_names:
		return []

	reference_rows = frappe.get_all(
		"Payment Entry Reference",
		filters={
			"reference_doctype": "Purchase Invoice",
			"reference_name": ["in", invoice_names],
			"parenttype": "Payment Entry",
			"parentfield": "references",
		},
		fields=["parent", "reference_name", "allocated_amount"],
		limit_page_length=0,
	)
	parent_names = sorted({row.parent for row in reference_rows if getattr(row, "parent", None)})
	if not parent_names:
		return []

	payment_entry_rows = frappe.get_all(
		"Payment Entry",
		filters={"name": ["in", parent_names], "docstatus": 1},
		fields=["name", "posting_date", "mode_of_payment", "paid_amount", "received_amount", "modified"],
		order_by="modified desc",
		limit_page_length=0,
	)
	payment_entry_map = {getattr(row, "name", None): row for row in payment_entry_rows}
	entries = []
	for row in reference_rows:
		payment_entry = payment_entry_map.get(getattr(row, "parent", None))
		if not payment_entry:
			continue
		entries.append(
			{
				"allocated_amount": flt(getattr(row, "allocated_amount", 0) or 0),
				"mode_of_payment": getattr(payment_entry, "mode_of_payment", None),
				"paid_amount": flt(getattr(payment_entry, "paid_amount", 0) or 0),
				"payment_entry": getattr(payment_entry, "name", None),
				"posting_date": getattr(payment_entry, "posting_date", None),
				"received_amount": flt(getattr(payment_entry, "received_amount", 0) or 0),
				"reference_name": getattr(row, "reference_name", None),
			}
		)
	return entries


def get_customer_refund_context(return_invoice_name: str):
	from myapp.services.order_service import _collect_sales_invoice_payment_entries

	if not return_invoice_name:
		frappe.throw(_("return_invoice_name 不能为空。"))

	try:
		return_invoice = frappe.get_doc("Sales Invoice", return_invoice_name)
		source_invoice = None
		source_invoice_name = return_invoice.get("return_against")
		if source_invoice_name:
			source_invoice = frappe.get_doc("Sales Invoice", source_invoice_name)

		refund_entries = _collect_sales_invoice_payment_entries([return_invoice.name])
		return_amount = abs(flt(return_invoice.get("rounded_total") or return_invoice.get("grand_total") or 0))
		refunded_amount = _sum_abs_allocated_amount(refund_entries)
		refundable_amount = _get_customer_refundable_amount(
			return_invoice,
			return_amount=return_amount,
			refunded_amount=refunded_amount,
			collect_entries=_collect_sales_invoice_payment_entries,
		)
		action_hint = _build_customer_refund_action_hint(
			return_invoice=return_invoice,
			refundable_amount=refundable_amount,
		)
		can_create_refund = not action_hint

		if cint(return_invoice.docstatus) == 1 and cint(return_invoice.get("is_return")) and refundable_amount <= 0:
			refund_status = "refunded"
		elif action_hint:
			refund_status = "unavailable"
		elif refunded_amount > 0:
			refund_status = "partial_refunded"
		else:
			refund_status = "not_refunded"

		return {
			"status": "success",
			"data": {
				"return_invoice": _build_refund_invoice_snapshot(return_invoice),
				"source_invoice": _build_refund_invoice_snapshot(source_invoice),
				"refund": {
					"currency": return_invoice.get("currency"),
					"return_amount": return_amount,
					"refunded_amount": refunded_amount,
					"refundable_amount": refundable_amount,
					"suggested_refund_amount": refundable_amount if can_create_refund else 0,
					"status": refund_status,
				},
				"entries": refund_entries,
				"actions": {
					"can_create_refund": can_create_refund,
					"create_refund_hint": action_hint,
				},
			},
			"message": _("客户退款上下文获取成功。"),
		}
	except frappe.DoesNotExistError:
		raise
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("客户退款上下文获取失败"))
		raise


def get_supplier_refund_context(return_invoice_name: str):
	if not return_invoice_name:
		frappe.throw(_("return_invoice_name 不能为空。"))

	try:
		return_invoice = frappe.get_doc("Purchase Invoice", return_invoice_name)
		source_invoice = None
		source_invoice_name = return_invoice.get("return_against")
		if source_invoice_name:
			source_invoice = frappe.get_doc("Purchase Invoice", source_invoice_name)

		refund_entries = _collect_purchase_invoice_payment_entries([return_invoice.name])
		return_amount = abs(flt(return_invoice.get("rounded_total") or return_invoice.get("grand_total") or 0))
		refunded_amount = _sum_abs_allocated_amount(refund_entries)
		refundable_amount = _get_supplier_refundable_amount(
			return_invoice,
			return_amount=return_amount,
			refunded_amount=refunded_amount,
		)
		action_hint = _build_supplier_refund_action_hint(
			return_invoice=return_invoice,
			refundable_amount=refundable_amount,
		)
		can_create_refund = not action_hint

		if cint(return_invoice.docstatus) == 1 and cint(return_invoice.get("is_return")) and refundable_amount <= 0:
			refund_status = "refunded"
		elif action_hint:
			refund_status = "unavailable"
		elif refunded_amount > 0:
			refund_status = "partial_refunded"
		else:
			refund_status = "not_refunded"

		return {
			"status": "success",
			"data": {
				"return_invoice": _build_refund_invoice_snapshot(return_invoice),
				"source_invoice": _build_refund_invoice_snapshot(source_invoice),
				"refund": {
					"currency": return_invoice.get("currency"),
					"return_amount": return_amount,
					"refunded_amount": refunded_amount,
					"refundable_amount": refundable_amount,
					"suggested_refund_amount": refundable_amount if can_create_refund else 0,
					"status": refund_status,
				},
				"entries": refund_entries,
				"actions": {
					"can_create_refund": can_create_refund,
					"create_refund_hint": action_hint,
				},
			},
			"message": _("供应商退款上下文获取成功。"),
		}
	except frappe.DoesNotExistError:
		raise
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("供应商退款上下文获取失败"))
		raise


def create_customer_refund(return_invoice_name: str, refund_amount: float, **kwargs):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	if not return_invoice_name:
		frappe.throw(_("return_invoice_name 不能为空。"))

	refund_amount = flt(refund_amount)
	if refund_amount <= 0:
		frappe.throw(_("refund_amount 必须大于 0。"))

	request_id = kwargs.get("request_id")

	try:
		def _create_customer_refund():
			return_invoice = frappe.get_doc("Sales Invoice", return_invoice_name)
			if cint(return_invoice.docstatus) != 1:
				frappe.throw(_("只有已提交的销售退货发票才能登记退款。"))
			if not cint(return_invoice.get("is_return")):
				frappe.throw(_("只能基于销售退货发票登记客户退款。"))

			refundable_amount = _get_customer_refundable_amount(return_invoice)
			if refundable_amount <= 0:
				frappe.throw(_("销售退货发票 {0} 当前没有可退金额。").format(return_invoice.name))
			if refund_amount > refundable_amount:
				frappe.throw(
					_("退款金额不能大于当前可退金额 {0}。").format(refundable_amount)
				)

			pe = get_payment_entry("Sales Invoice", return_invoice.name, party_amount=refund_amount)
			pe.mode_of_payment = kwargs.get("mode_of_payment") or pe.mode_of_payment or "Cash"
			pe.reference_no = kwargs.get("reference_no") or _("客户退款")
			pe.reference_date = kwargs.get("reference_date") or nowdate()
			_normalize_return_invoice_payment_reference_amounts(pe, return_invoice, refund_amount)
			if kwargs.get("remarks"):
				pe.remarks = kwargs["remarks"]

			pe.insert()
			pe.submit()

			return {
				"status": "success",
				"payment_entry": pe.name,
				"refund_amount": refund_amount,
				"refundable_amount_before_refund": refundable_amount,
				"return_invoice": return_invoice.name,
				"source_invoice": return_invoice.get("return_against"),
				"mode_of_payment": pe.mode_of_payment,
				"reference_no": pe.reference_no,
				"reference_date": pe.reference_date,
				"message": _("成功为销售退货发票 {0} 登记客户退款 {1}。").format(
					return_invoice.name,
					refund_amount,
				),
			}

		return run_idempotent("create_customer_refund", request_id, _create_customer_refund)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("客户退款登记失败"))
		raise


def _normalize_return_invoice_payment_reference_amounts(payment_entry, return_invoice, allocated_amount: float):
	outstanding_amount = flt(return_invoice.get("outstanding_amount") or 0)
	if outstanding_amount >= 0:
		return

	total_amount = flt(
		return_invoice.get("rounded_total")
		or return_invoice.get("grand_total")
		or return_invoice.get("base_rounded_total")
		or outstanding_amount
	)
	if total_amount > 0:
		total_amount = -total_amount

	for row in getattr(payment_entry, "references", None) or []:
		if (
			getattr(row, "reference_name", None) == return_invoice.name
			and getattr(row, "reference_doctype", None) in {"Sales Invoice", "Purchase Invoice"}
		):
			row.total_amount = total_amount
			row.outstanding_amount = outstanding_amount
			row.allocated_amount = -abs(flt(allocated_amount))


def _get_return_invoice_names_for_source(doctype: str, source_invoice_name: str | None):
	if not source_invoice_name:
		return []
	rows = frappe.get_all(
		doctype,
		filters={"return_against": source_invoice_name, "is_return": 1, "docstatus": 1},
		fields=["name"],
		limit_page_length=0,
	)
	return [row.name for row in rows if getattr(row, "name", None)]


def _get_customer_refundable_amount(
	return_invoice,
	*,
	return_amount: float | None = None,
	refunded_amount: float | None = None,
	collect_entries=None,
):
	from myapp.services.order_service import _collect_sales_invoice_payment_entries

	collect_entries = collect_entries or _collect_sales_invoice_payment_entries
	source_invoice_name = return_invoice.get("return_against")
	current_return_amount = (
		flt(return_amount)
		if return_amount is not None
		else abs(flt(return_invoice.get("rounded_total") or return_invoice.get("grand_total") or 0))
	)
	current_refunded_amount = (
		flt(refunded_amount)
		if refunded_amount is not None
		else _sum_abs_allocated_amount(collect_entries([return_invoice.name]))
	)
	current_return_remaining = max(
		min(abs(flt(return_invoice.get("outstanding_amount") or 0)), current_return_amount - current_refunded_amount),
		0,
	)
	if not source_invoice_name:
		return current_return_remaining

	source_paid_amount = _sum_actual_paid_amount(collect_entries([source_invoice_name]))
	return_invoice_names = _get_return_invoice_names_for_source("Sales Invoice", source_invoice_name)
	refunded_for_source = _sum_abs_allocated_amount(collect_entries(return_invoice_names))
	return max(min(current_return_remaining, source_paid_amount - refunded_for_source), 0)


def _get_supplier_refundable_amount(return_invoice, *, return_amount: float | None = None, refunded_amount: float | None = None):
	source_invoice_name = return_invoice.get("return_against")
	current_return_amount = (
		flt(return_amount)
		if return_amount is not None
		else abs(flt(return_invoice.get("rounded_total") or return_invoice.get("grand_total") or 0))
	)
	current_refunded_amount = (
		flt(refunded_amount)
		if refunded_amount is not None
		else _sum_abs_allocated_amount(_collect_purchase_invoice_payment_entries([return_invoice.name]))
	)
	current_return_remaining = max(
		min(abs(flt(return_invoice.get("outstanding_amount") or 0)), current_return_amount - current_refunded_amount),
		0,
	)
	if not source_invoice_name:
		return current_return_remaining

	source_paid_amount = _sum_abs_allocated_amount(_collect_purchase_invoice_payment_entries([source_invoice_name]))
	return_invoice_names = _get_return_invoice_names_for_source("Purchase Invoice", source_invoice_name)
	refunded_for_source = _sum_abs_allocated_amount(_collect_purchase_invoice_payment_entries(return_invoice_names))
	return max(min(current_return_remaining, source_paid_amount - refunded_for_source), 0)


def create_supplier_refund(return_invoice_name: str, refund_amount: float, **kwargs):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	if not return_invoice_name:
		frappe.throw(_("return_invoice_name 不能为空。"))

	refund_amount = flt(refund_amount)
	if refund_amount <= 0:
		frappe.throw(_("refund_amount 必须大于 0。"))

	request_id = kwargs.get("request_id")

	try:
		def _create_supplier_refund():
			return_invoice = frappe.get_doc("Purchase Invoice", return_invoice_name)
			if cint(return_invoice.docstatus) != 1:
				frappe.throw(_("只有已提交的采购退货发票才能登记退款。"))
			if not cint(return_invoice.get("is_return")):
				frappe.throw(_("只能基于采购退货发票登记供应商退款。"))

			refundable_amount = _get_supplier_refundable_amount(return_invoice)
			if refundable_amount <= 0:
				frappe.throw(_("采购退货发票 {0} 当前没有可退金额。").format(return_invoice.name))
			if refund_amount > refundable_amount:
				frappe.throw(
					_("退款金额不能大于当前可退金额 {0}。").format(refundable_amount)
				)

			pe = get_payment_entry("Purchase Invoice", return_invoice.name, party_amount=refund_amount)
			pe.mode_of_payment = kwargs.get("mode_of_payment") or pe.mode_of_payment or "Cash"
			pe.reference_no = kwargs.get("reference_no") or _("供应商退款")
			pe.reference_date = kwargs.get("reference_date") or nowdate()
			_normalize_return_invoice_payment_reference_amounts(pe, return_invoice, refund_amount)
			if kwargs.get("remarks"):
				pe.remarks = kwargs["remarks"]

			pe.insert()
			pe.submit()

			return {
				"status": "success",
				"payment_entry": pe.name,
				"refund_amount": refund_amount,
				"refundable_amount_before_refund": refundable_amount,
				"return_invoice": return_invoice.name,
				"source_invoice": return_invoice.get("return_against"),
				"mode_of_payment": pe.mode_of_payment,
				"reference_no": pe.reference_no,
				"reference_date": pe.reference_date,
				"message": _("成功为采购退货发票 {0} 登记供应商退款 {1}。").format(
					return_invoice.name,
					refund_amount,
				),
			}

		return run_idempotent("create_supplier_refund", request_id, _create_supplier_refund)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("供应商退款登记失败"))
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

			return build_return_submission_payload(
				return_doc,
				source_doctype=source_doctype,
				source_name=source_name,
				business_type="sales",
				is_partial_return=bool(return_items),
			)

		return run_idempotent("process_sales_return", request_id, _process_sales_return)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("退货处理失败"))
		raise
