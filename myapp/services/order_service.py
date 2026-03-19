import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from myapp.utils.idempotency import run_idempotent


ORDER_REMARK_FIELD = "custom_order_remark"


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


def _set_doc_field_if_present(doc, fieldname: str, value):
	if value in (None, ""):
		return

	if doc.meta.has_field(fieldname):
		doc.set(fieldname, value)


def _set_doc_field(doc, fieldname: str, value):
	if not doc.meta.has_field(fieldname):
		return
	doc.set(fieldname, value)


def _has_sales_order_field(fieldname: str) -> bool:
	try:
		return bool(frappe.get_meta("Sales Order").has_field(fieldname))
	except Exception:
		return False


def _get_sales_order_remark_field() -> str | None:
	if _has_sales_order_field(ORDER_REMARK_FIELD):
		return ORDER_REMARK_FIELD
	if _has_sales_order_field("remarks"):
		return "remarks"
	return None


def _set_sales_order_remark(doc, value):
	fieldname = _get_sales_order_remark_field()
	if not fieldname:
		return
	doc.set(fieldname, value)


def _get_sales_order_remark(doc):
	fieldname = _get_sales_order_remark_field()
	if not fieldname:
		return None
	return doc.get(fieldname)


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


def _normalize_snapshot_payload(snapshot):
	if snapshot in (None, ""):
		return {}
	return _coerce_json_value(snapshot, {}) or {}


def _apply_sales_order_v2_snapshot(so, *, customer_info=None, shipping_info=None, kwargs=None, overwrite: bool = False):
	customer_info = _normalize_snapshot_payload(customer_info)
	shipping_info = _normalize_snapshot_payload(shipping_info)
	kwargs = kwargs or {}

	contact_person = (
		customer_info.get("contact_person")
		or shipping_info.get("contact_person")
		or kwargs.get("contact_person")
	)
	contact_display = (
		customer_info.get("contact_display_name")
		or customer_info.get("contact_display")
		or shipping_info.get("contact_display")
		or shipping_info.get("receiver_name")
		or kwargs.get("contact_display")
		or kwargs.get("contact_display_name")
	)
	contact_phone = (
		customer_info.get("contact_phone")
		or shipping_info.get("contact_phone")
		or shipping_info.get("receiver_phone")
		or kwargs.get("contact_phone")
		or kwargs.get("receiver_phone")
	)
	contact_email = (
		customer_info.get("contact_email")
		or shipping_info.get("contact_email")
		or kwargs.get("contact_email")
	)
	shipping_address_name = (
		shipping_info.get("shipping_address_name")
		or kwargs.get("shipping_address_name")
	)
	shipping_address_text = (
		shipping_info.get("shipping_address_text")
		or shipping_info.get("address_display")
		or kwargs.get("shipping_address_text")
		or kwargs.get("address_display")
	)

	field_setter = _set_doc_field if overwrite else _set_doc_field_if_present
	field_setter(so, "contact_person", contact_person)
	field_setter(so, "contact_display", contact_display)
	field_setter(so, "contact_mobile", contact_phone)
	field_setter(so, "contact_phone", contact_phone)
	field_setter(so, "contact_email", contact_email)
	field_setter(so, "shipping_address_name", shipping_address_name)
	field_setter(so, "customer_address", shipping_address_name)
	field_setter(so, "address_display", shipping_address_text)

	return {
		"customer": {
			"contact_person": contact_person,
			"contact_display_name": customer_info.get("contact_display_name") or customer_info.get("contact_display"),
			"contact_phone": customer_info.get("contact_phone"),
			"contact_email": customer_info.get("contact_email"),
		},
		"shipping": {
			"receiver_name": shipping_info.get("receiver_name"),
			"receiver_phone": shipping_info.get("receiver_phone"),
			"contact_display": shipping_info.get("contact_display"),
			"contact_phone": shipping_info.get("contact_phone"),
			"contact_email": shipping_info.get("contact_email"),
			"shipping_address_name": shipping_address_name,
			"shipping_address_text": shipping_address_text,
		},
		"applied": {
			"contact_person": contact_person,
			"contact_display": contact_display,
			"contact_phone": contact_phone,
			"contact_email": contact_email,
			"shipping_address_name": shipping_address_name,
			"shipping_address_text": shipping_address_text,
		},
	}


def _insert_and_submit(doc):
	doc.insert()
	doc.submit()
	return doc


def _insert_and_submit_with_temporary_negative_stock(doc):
	item_codes = []
	original_flags = {}

	for item in doc.get("items") or []:
		item_code = getattr(item, "item_code", None)
		if not item_code or item_code in original_flags:
			continue
		original_flags[item_code] = cint(frappe.db.get_value("Item", item_code, "allow_negative_stock") or 0)
		item_codes.append(item_code)

	try:
		for item_code in item_codes:
			if not original_flags[item_code]:
				frappe.db.set_value("Item", item_code, "allow_negative_stock", 1, update_modified=False)
		if item_codes:
			frappe.clear_cache()
		doc.insert()
		doc.submit()
		return doc
	finally:
		for item_code in item_codes:
			frappe.db.set_value(
				"Item",
				item_code,
				"allow_negative_stock",
				original_flags[item_code],
				update_modified=False,
			)
		if item_codes:
			frappe.clear_cache()


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


def _apply_item_overrides(target_items, item_overrides: dict, *, detail_attrs: tuple[str, ...] = ()):
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
			item.qty = flt(override["qty"])
		if override.get("price") is not None:
			item.rate = flt(override["price"])
		filtered_items.append(item)

	return filtered_items


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


def _sum_row_values(rows, fieldname: str):
	return sum(flt(getattr(row, fieldname, 0) or 0) for row in rows or [])


def _build_fulfillment_summary(order_items):
	total_qty = _sum_row_values(order_items, "qty")
	delivered_qty = _sum_row_values(order_items, "delivered_qty")
	remaining_qty = max(total_qty - delivered_qty, 0)

	if delivered_qty <= 0:
		status = "pending"
	elif delivered_qty < total_qty:
		status = "partial"
	else:
		status = "shipped"

	return {
		"total_qty": total_qty,
		"delivered_qty": delivered_qty,
		"remaining_qty": remaining_qty,
		"status": status,
		"is_fully_delivered": total_qty > 0 and remaining_qty <= 0,
	}


def _build_payment_summary(invoice_rows):
	receivable_amount = sum(
		flt(
			getattr(row, "rounded_total", None)
			or getattr(row, "grand_total", None)
			or getattr(row, "base_rounded_total", None)
			or 0
		)
		for row in invoice_rows
	)
	outstanding_amount = sum(flt(getattr(row, "outstanding_amount", 0) or 0) for row in invoice_rows)
	paid_amount = receivable_amount - outstanding_amount

	if receivable_amount <= 0:
		status = "unpaid"
	elif outstanding_amount <= 0:
		status = "paid"
	elif paid_amount <= 0:
		status = "unpaid"
	else:
		status = "partial"

	return {
		"receivable_amount": receivable_amount,
		"paid_amount": max(paid_amount, 0),
		"outstanding_amount": max(outstanding_amount, 0),
		"status": status,
		"is_fully_paid": receivable_amount > 0 and outstanding_amount <= 0,
	}


def _get_latest_payment_entry_summary(invoice_names: list[str]):
	if not invoice_names:
		return {
			"payment_entry": None,
			"invoice_name": None,
			"allocated_amount": 0,
			"unallocated_amount": 0,
			"writeoff_amount": 0,
			"actual_paid_amount": 0,
			"total_actual_paid_amount": 0,
			"total_writeoff_amount": 0,
		}

	reference_rows = frappe.get_all(
		"Payment Entry Reference",
		filters={
			"reference_doctype": "Sales Invoice",
			"reference_name": ["in", invoice_names],
			"parenttype": "Payment Entry",
			"parentfield": "references",
		},
		fields=["parent", "reference_name", "allocated_amount", "modified"],
		order_by="modified desc",
		limit_page_length=50,
	)
	if not reference_rows:
		return {
			"payment_entry": None,
			"invoice_name": None,
			"allocated_amount": 0,
			"unallocated_amount": 0,
			"writeoff_amount": 0,
			"actual_paid_amount": 0,
			"total_actual_paid_amount": 0,
			"total_writeoff_amount": 0,
		}

	parent_names = []
	for row in reference_rows:
		parent = getattr(row, "parent", None)
		if parent and parent not in parent_names:
			parent_names.append(parent)

	if not parent_names:
		return {
			"payment_entry": None,
			"invoice_name": None,
			"allocated_amount": 0,
			"unallocated_amount": 0,
			"writeoff_amount": 0,
			"actual_paid_amount": 0,
			"total_actual_paid_amount": 0,
			"total_writeoff_amount": 0,
		}

	payment_entry_rows = frappe.get_all(
		"Payment Entry",
		filters={"name": ["in", parent_names], "docstatus": 1},
		fields=["name", "paid_amount", "received_amount", "unallocated_amount", "difference_amount", "modified"],
		order_by="modified desc",
		limit_page_length=len(parent_names),
	)
	if not payment_entry_rows:
		return {
			"payment_entry": None,
			"invoice_name": None,
			"allocated_amount": 0,
			"unallocated_amount": 0,
			"writeoff_amount": 0,
			"actual_paid_amount": 0,
			"total_actual_paid_amount": 0,
			"total_writeoff_amount": 0,
		}

	payment_entry_map = {getattr(row, "name", None): row for row in payment_entry_rows}
	total_allocated_by_parent = {}
	for row in reference_rows:
		parent = getattr(row, "parent", None)
		if not parent:
			continue
		total_allocated_by_parent[parent] = total_allocated_by_parent.get(parent, 0) + flt(
			getattr(row, "allocated_amount", 0) or 0
		)

	total_actual_paid_amount = 0
	total_writeoff_amount = 0
	for row in reference_rows:
		parent = getattr(row, "parent", None)
		payment_entry = payment_entry_map.get(parent)
		if not payment_entry:
			continue
		allocated_amount = flt(getattr(row, "allocated_amount", 0) or 0)
		parent_total_allocated = flt(total_allocated_by_parent.get(parent, 0) or 0)
		parent_paid_amount = flt(
			getattr(payment_entry, "paid_amount", None)
			or getattr(payment_entry, "received_amount", None)
			or 0
		)
		parent_effective_paid_amount = min(parent_paid_amount, parent_total_allocated)
		attributed_actual_paid = (
			parent_effective_paid_amount * allocated_amount / parent_total_allocated
			if parent_total_allocated > 0
			else 0
		)
		attributed_writeoff = max(allocated_amount - attributed_actual_paid, 0)
		total_writeoff_amount += attributed_writeoff
		total_actual_paid_amount += max(attributed_actual_paid, 0)

	latest_payment_entry = payment_entry_rows[0]
	latest_payment_entry_name = getattr(latest_payment_entry, "name", None)
	latest_reference = next(
		(row for row in reference_rows if getattr(row, "parent", None) == latest_payment_entry_name),
		None,
	)
	allocated_amount = flt(getattr(latest_reference, "allocated_amount", 0) or 0)
	paid_amount = flt(
		getattr(latest_payment_entry, "paid_amount", None)
		or getattr(latest_payment_entry, "received_amount", None)
		or 0
	)
	unallocated_amount = flt(getattr(latest_payment_entry, "unallocated_amount", 0) or 0)
	parent_total_allocated = flt(total_allocated_by_parent.get(latest_payment_entry_name, 0) or 0)
	parent_effective_paid_amount = min(paid_amount, parent_total_allocated)
	actual_paid_amount = (
		parent_effective_paid_amount * allocated_amount / parent_total_allocated
		if parent_total_allocated > 0
		else 0
	)
	writeoff_amount = max(allocated_amount - actual_paid_amount, 0)

	return {
		"payment_entry": latest_payment_entry_name,
		"invoice_name": getattr(latest_reference, "reference_name", None) if latest_reference else None,
		"allocated_amount": allocated_amount,
		"unallocated_amount": unallocated_amount,
		"writeoff_amount": writeoff_amount,
		"actual_paid_amount": actual_paid_amount,
		"total_actual_paid_amount": total_actual_paid_amount,
		"total_writeoff_amount": total_writeoff_amount,
	}


def _build_completion_summary(fulfillment: dict, payment: dict, *, docstatus: int):
	if cint(docstatus) == 2:
		return {"status": "closed", "is_completed": False}

	is_completed = bool(fulfillment.get("is_fully_delivered") and payment.get("is_fully_paid"))
	return {
		"status": "completed" if is_completed else "open",
		"is_completed": is_completed,
	}


def _build_delivery_summary(fulfillment: dict, *, delivery_note_names: list[str], docstatus: int):
	if cint(docstatus) == 2:
		return {
			"status": "cancelled",
			"delivered_at": None,
			"delivery_confirmed_by": None,
		}

	if not delivery_note_names:
		return {
			"status": "pending",
			"delivered_at": None,
			"delivery_confirmed_by": None,
		}

	if fulfillment.get("is_fully_delivered"):
		status = "shipped"
	elif flt(fulfillment.get("delivered_qty")) > 0:
		status = "partial"
	else:
		status = "pending"

	return {
		"status": status,
		"delivered_at": None,
		"delivery_confirmed_by": None,
	}


def _build_action_flags(fulfillment: dict, payment: dict, *, invoice_names: list[str], delivery_note_names: list[str], docstatus: int):
	is_submitted = cint(docstatus) == 1
	return {
		"can_submit_delivery": is_submitted and not fulfillment.get("is_fully_delivered"),
		"can_create_sales_invoice": is_submitted and not invoice_names and not payment.get("is_fully_paid"),
		"can_record_payment": is_submitted and payment.get("outstanding_amount", 0) > 0,
		"can_process_return": bool(is_submitted and (invoice_names or delivery_note_names)),
	}


def _serialize_order_items(order_items):
	item_image_map = _get_item_image_map(order_items)
	return [
		{
			"sales_order_item": getattr(item, "name", None),
			"item_code": getattr(item, "item_code", None),
			"item_name": getattr(item, "item_name", None),
			"uom": getattr(item, "uom", None),
			"warehouse": getattr(item, "warehouse", None),
			"qty": flt(getattr(item, "qty", 0) or 0),
			"delivered_qty": flt(getattr(item, "delivered_qty", 0) or 0),
			"rate": flt(getattr(item, "rate", 0) or 0),
			"amount": flt(getattr(item, "amount", 0) or 0),
			"image": item_image_map.get(getattr(item, "item_code", None)),
		}
		for item in order_items or []
	]


def _get_item_image_map(items):
	item_codes = []
	for item in items or []:
		item_code = getattr(item, "item_code", None)
		if isinstance(item_code, str) and item_code and item_code not in item_codes:
			item_codes.append(item_code)

	item_image_map = {}
	if item_codes:
		for row in frappe.get_all(
			"Item",
			filters={"name": ["in", item_codes]},
			fields=["name", "image"],
			limit_page_length=len(item_codes),
		):
			item_name = getattr(row, "name", None)
			if item_name:
				item_image_map[item_name] = getattr(row, "image", None)
	return item_image_map


def _serialize_delivery_note_items(delivery_items):
	item_image_map = _get_item_image_map(delivery_items)
	return [
		{
			"delivery_note_item": getattr(item, "name", None),
			"item_code": getattr(item, "item_code", None),
			"item_name": getattr(item, "item_name", None),
			"uom": getattr(item, "uom", None),
			"warehouse": getattr(item, "warehouse", None),
			"qty": flt(getattr(item, "qty", 0) or 0),
			"rate": flt(getattr(item, "rate", 0) or 0),
			"amount": flt(getattr(item, "amount", 0) or 0),
			"image": item_image_map.get(getattr(item, "item_code", None)),
			"sales_order": getattr(item, "against_sales_order", None),
			"sales_order_item": getattr(item, "so_detail", None),
		}
		for item in delivery_items or []
	]


def _serialize_sales_invoice_items(invoice_items):
	item_image_map = _get_item_image_map(invoice_items)
	return [
		{
			"sales_invoice_item": getattr(item, "name", None),
			"item_code": getattr(item, "item_code", None),
			"item_name": getattr(item, "item_name", None),
			"uom": getattr(item, "uom", None),
			"warehouse": getattr(item, "warehouse", None),
			"qty": flt(getattr(item, "qty", 0) or 0),
			"rate": flt(getattr(item, "rate", 0) or 0),
			"amount": flt(getattr(item, "amount", 0) or 0),
			"image": item_image_map.get(getattr(item, "item_code", None)),
			"sales_order": getattr(item, "sales_order", None),
			"sales_order_item": getattr(item, "so_detail", None),
			"delivery_note": getattr(item, "delivery_note", None),
			"delivery_note_item": getattr(item, "dn_detail", None),
		}
		for item in invoice_items or []
	]


def _build_customer_snapshot_for_doc(doc):
	contact_doc = _get_doc_if_exists("Contact", doc.get("contact_person"))
	address_doc = _get_doc_if_exists("Address", doc.get("shipping_address_name"))

	contact_phone = _extract_first_non_empty(
		doc.get("contact_mobile"),
		doc.get("contact_phone"),
		getattr(contact_doc, "mobile_no", None) if contact_doc else None,
		getattr(contact_doc, "phone", None) if contact_doc else None,
	)
	contact_email = _extract_first_non_empty(
		doc.get("contact_email"),
		getattr(contact_doc, "email_id", None) if contact_doc else None,
	)

	return {
		"name": doc.get("customer"),
		"display_name": doc.get("customer_name") or doc.get("customer"),
		"contact_person": doc.get("contact_person"),
		"contact_display_name": _extract_first_non_empty(
			getattr(contact_doc, "full_name", None) if contact_doc else None,
			getattr(contact_doc, "first_name", None) if contact_doc else None,
			doc.get("contact_display"),
		),
		"contact_phone": contact_phone,
		"contact_email": contact_email,
		"shipping_address_name": doc.get("shipping_address_name"),
		"shipping_address_text": _extract_first_non_empty(
			doc.get("address_display"),
			getattr(address_doc, "address_display", None) if address_doc else None,
			getattr(address_doc, "address_line1", None) if address_doc else None,
		),
	}


def _build_shipping_snapshot_for_doc(doc):
	address_doc = _get_doc_if_exists("Address", doc.get("shipping_address_name"))
	contact_doc = _get_doc_if_exists("Contact", doc.get("contact_person"))

	return {
		"shipping_address_name": doc.get("shipping_address_name"),
		"shipping_address_text": _extract_first_non_empty(
			doc.get("address_display"),
			getattr(address_doc, "address_display", None) if address_doc else None,
			getattr(address_doc, "address_line1", None) if address_doc else None,
		),
		"address_line1": _extract_first_non_empty(
			getattr(address_doc, "address_line1", None) if address_doc else None,
		),
		"address_line2": _extract_first_non_empty(
			getattr(address_doc, "address_line2", None) if address_doc else None,
		),
		"city": _extract_first_non_empty(getattr(address_doc, "city", None) if address_doc else None),
		"county": _extract_first_non_empty(getattr(address_doc, "county", None) if address_doc else None),
		"state": _extract_first_non_empty(getattr(address_doc, "state", None) if address_doc else None),
		"country": _extract_first_non_empty(getattr(address_doc, "country", None) if address_doc else None),
		"pincode": _extract_first_non_empty(getattr(address_doc, "pincode", None) if address_doc else None),
		"contact_person": doc.get("contact_person"),
		"contact_display": _extract_first_non_empty(
			doc.get("contact_display"),
			getattr(contact_doc, "full_name", None) if contact_doc else None,
			getattr(contact_doc, "first_name", None) if contact_doc else None,
		),
		"contact_phone": _extract_first_non_empty(
			doc.get("contact_mobile"),
			doc.get("contact_phone"),
			getattr(contact_doc, "mobile_no", None) if contact_doc else None,
			getattr(contact_doc, "phone", None) if contact_doc else None,
		),
		"contact_email": _extract_first_non_empty(
			doc.get("contact_email"),
			getattr(contact_doc, "email_id", None) if contact_doc else None,
		),
	}


def _build_delivery_note_references(delivery_items):
	sales_orders = []
	for item in delivery_items or []:
		order_name = getattr(item, "against_sales_order", None)
		if order_name and order_name not in sales_orders:
			sales_orders.append(order_name)

	invoice_rows = []
	delivery_item_names = [getattr(item, "name", None) for item in delivery_items or [] if getattr(item, "name", None)]
	if delivery_item_names:
		invoice_rows.extend(
			frappe.get_all(
				"Sales Invoice Item",
				filters={
					"dn_detail": ["in", delivery_item_names],
					"docstatus": 1,
				},
				fields=["parent"],
				limit_page_length=100,
			)
		)

	# 兼容“先出货，再基于订单开票”的链路：这类发票明细通常只有 sales_order / so_detail，
	# 不会回写 delivery_note / dn_detail，因此需要按来源订单兜底关联。
	if sales_orders:
		invoice_rows.extend(
			frappe.get_all(
				"Sales Invoice Item",
				filters={
					"sales_order": ["in", sales_orders],
					"docstatus": 1,
				},
				fields=["parent"],
				limit_page_length=100,
			)
		)

	sales_invoices = []
	for row in invoice_rows:
		parent = getattr(row, "parent", None)
		if parent and parent not in sales_invoices:
			sales_invoices.append(parent)

	return {
		"sales_orders": sales_orders,
		"sales_invoices": sales_invoices,
	}


def _build_sales_invoice_references(invoice_items):
	sales_orders = []
	delivery_notes = []
	for item in invoice_items or []:
		order_name = getattr(item, "sales_order", None)
		if order_name and order_name not in sales_orders:
			sales_orders.append(order_name)

		delivery_note = getattr(item, "delivery_note", None)
		if delivery_note and delivery_note not in delivery_notes:
			delivery_notes.append(delivery_note)

	# 兼容“发票直接从订单生成”的链路：此时销售发票明细通常没有 delivery_note，
	# 需要按来源订单兜底查找已存在的发货单。
	if sales_orders:
		delivery_note_rows = frappe.get_all(
			"Delivery Note Item",
			filters={
				"against_sales_order": ["in", sales_orders],
				"docstatus": 1,
			},
			fields=["parent"],
			limit_page_length=100,
		)
		for row in delivery_note_rows:
			parent = getattr(row, "parent", None)
			if parent and parent not in delivery_notes:
				delivery_notes.append(parent)

	return {
		"sales_orders": sales_orders,
		"delivery_notes": delivery_notes,
	}


def _document_status_label(docstatus: int):
	if cint(docstatus) == 2:
		return "cancelled"
	if cint(docstatus) == 1:
		return "submitted"
	return "draft"


def _extract_first_non_empty(*values):
	for value in values:
		if isinstance(value, str) and value.strip():
			return value.strip()
	return None


def _get_doc_if_exists(doctype: str, name: str | None):
	normalized = (name or "").strip() if isinstance(name, str) else ""
	if not normalized:
		return None
	try:
		return frappe.get_doc(doctype, normalized)
	except frappe.DoesNotExistError:
		return None


def _serialize_contact_doc(contact_doc):
	if not contact_doc:
		return None

	return {
		"name": getattr(contact_doc, "name", None),
		"display_name": _extract_first_non_empty(
			getattr(contact_doc, "full_name", None),
			getattr(contact_doc, "first_name", None),
		),
		"phone": _extract_first_non_empty(getattr(contact_doc, "mobile_no", None), getattr(contact_doc, "phone", None)),
		"email": _extract_first_non_empty(getattr(contact_doc, "email_id", None)),
	}


def _serialize_address_doc(address_doc):
	if not address_doc:
		return None

	return {
		"name": getattr(address_doc, "name", None),
		"address_display": _extract_first_non_empty(getattr(address_doc, "address_display", None)),
		"address_line1": _extract_first_non_empty(getattr(address_doc, "address_line1", None)),
		"address_line2": _extract_first_non_empty(getattr(address_doc, "address_line2", None)),
		"city": _extract_first_non_empty(getattr(address_doc, "city", None)),
		"county": _extract_first_non_empty(getattr(address_doc, "county", None)),
		"state": _extract_first_non_empty(getattr(address_doc, "state", None)),
		"country": _extract_first_non_empty(getattr(address_doc, "country", None)),
		"pincode": _extract_first_non_empty(getattr(address_doc, "pincode", None)),
	}


def _get_linked_parent_names(link_name: str, *, parenttype: str, limit: int = 5):
	if not link_name:
		return []

	rows = frappe.get_all(
		"Dynamic Link",
		filters={
			"link_doctype": "Customer",
			"link_name": link_name,
			"parenttype": parenttype,
		},
		fields=["parent"],
		order_by="modified desc",
		limit_page_length=limit,
	)

	seen = set()
	result = []
	for row in rows:
		parent = getattr(row, "parent", None)
		if parent and parent not in seen:
			seen.add(parent)
			result.append(parent)
	return result


def _get_recent_sales_order_shipping_addresses(customer: str, limit: int = 5):
	rows = frappe.get_all(
		"Sales Order",
		filters={"customer": customer, "docstatus": 1},
		fields=["shipping_address_name", "address_display"],
		order_by="modified desc",
		limit_page_length=max(limit * 3, 10),
	)

	seen = set()
	result = []
	for row in rows:
		address_name = _extract_first_non_empty(getattr(row, "shipping_address_name", None))
		address_text = _extract_first_non_empty(getattr(row, "address_display", None))
		key = address_name or address_text
		if not key or key in seen:
			continue
		seen.add(key)
		result.append(
			{
				"name": address_name,
				"address_display": address_text,
			}
		)
		if len(result) >= limit:
			break
	return result


def _get_default_warehouse_for_context(company: str | None):
	warehouse = _extract_first_non_empty(frappe.defaults.get_user_default("warehouse"))
	if warehouse:
		return warehouse

	if not company:
		return None

	return frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")


def get_customer_sales_context(customer: str):
	if not customer:
		frappe.throw(_("customer 不能为空。"))

	customer_doc = frappe.get_doc("Customer", customer)
	default_contact_name = _extract_first_non_empty(getattr(customer_doc, "customer_primary_contact", None))
	default_address_name = _extract_first_non_empty(getattr(customer_doc, "customer_primary_address", None))

	contact_names = [default_contact_name] if default_contact_name else []
	for name in _get_linked_parent_names(customer, parenttype="Contact", limit=5):
		if name not in contact_names:
			contact_names.append(name)

	address_names = [default_address_name] if default_address_name else []
	for name in _get_linked_parent_names(customer, parenttype="Address", limit=5):
		if name not in address_names:
			address_names.append(name)

	default_contact = _serialize_contact_doc(_get_doc_if_exists("Contact", contact_names[0] if contact_names else None))
	default_address = _serialize_address_doc(_get_doc_if_exists("Address", address_names[0] if address_names else None))
	recent_addresses = _get_recent_sales_order_shipping_addresses(customer, limit=5)

	company = _extract_first_non_empty(frappe.defaults.get_user_default("company"))
	warehouse = _get_default_warehouse_for_context(company)

	return {
		"status": "success",
		"message": _("客户 {0} 销售上下文获取成功。").format(customer_doc.customer_name or customer_doc.name),
		"data": {
			"customer": {
				"name": customer_doc.name,
				"display_name": customer_doc.customer_name or customer_doc.name,
				"customer_group": getattr(customer_doc, "customer_group", None),
				"territory": getattr(customer_doc, "territory", None),
				"default_currency": getattr(customer_doc, "default_currency", None),
			},
			"default_contact": default_contact,
			"default_address": default_address,
			"recent_addresses": recent_addresses,
			"suggestions": {
				"company": company,
				"warehouse": warehouse,
			},
		},
	}


def _build_customer_snapshot(so):
	contact_doc = _get_doc_if_exists("Contact", so.get("contact_person"))
	address_doc = _get_doc_if_exists("Address", so.get("shipping_address_name"))

	contact_phone = _extract_first_non_empty(
		so.get("contact_mobile"),
		so.get("contact_phone"),
		getattr(contact_doc, "mobile_no", None) if contact_doc else None,
		getattr(contact_doc, "phone", None) if contact_doc else None,
	)
	contact_email = _extract_first_non_empty(
		so.get("contact_email"),
		getattr(contact_doc, "email_id", None) if contact_doc else None,
	)

	return {
		"name": so.customer,
		"display_name": so.get("customer_name") or so.customer,
		"contact_person": so.get("contact_person"),
		"contact_display_name": _extract_first_non_empty(
			getattr(contact_doc, "full_name", None) if contact_doc else None,
			getattr(contact_doc, "first_name", None) if contact_doc else None,
			so.get("contact_display"),
		),
		"contact_phone": contact_phone,
		"contact_email": contact_email,
		"shipping_address_name": so.get("shipping_address_name"),
		"shipping_address_text": _extract_first_non_empty(
			so.get("address_display"),
			getattr(address_doc, "address_display", None) if address_doc else None,
		),
	}


def _build_shipping_snapshot(so):
	address_doc = _get_doc_if_exists("Address", so.get("shipping_address_name"))
	contact_doc = _get_doc_if_exists("Contact", so.get("contact_person"))

	return {
		"shipping_address_name": so.get("shipping_address_name"),
		"shipping_address_text": _extract_first_non_empty(
			so.get("address_display"),
			getattr(address_doc, "address_display", None) if address_doc else None,
		),
		"address_line1": _extract_first_non_empty(
			getattr(address_doc, "address_line1", None) if address_doc else None,
		),
		"address_line2": _extract_first_non_empty(
			getattr(address_doc, "address_line2", None) if address_doc else None,
		),
		"city": _extract_first_non_empty(getattr(address_doc, "city", None) if address_doc else None),
		"county": _extract_first_non_empty(getattr(address_doc, "county", None) if address_doc else None),
		"state": _extract_first_non_empty(getattr(address_doc, "state", None) if address_doc else None),
		"country": _extract_first_non_empty(getattr(address_doc, "country", None) if address_doc else None),
		"pincode": _extract_first_non_empty(getattr(address_doc, "pincode", None) if address_doc else None),
		"contact_person": so.get("contact_person"),
		"contact_display": _extract_first_non_empty(
			so.get("contact_display"),
			getattr(contact_doc, "full_name", None) if contact_doc else None,
		),
		"contact_phone": _extract_first_non_empty(
			so.get("contact_mobile"),
			so.get("contact_phone"),
			getattr(contact_doc, "mobile_no", None) if contact_doc else None,
			getattr(contact_doc, "phone", None) if contact_doc else None,
		),
		"contact_email": _extract_first_non_empty(
			so.get("contact_email"),
			getattr(contact_doc, "email_id", None) if contact_doc else None,
		),
	}


def _collect_sales_order_reference_names(order_name: str):
	delivery_note_rows = frappe.get_all(
		"Delivery Note Item",
		filters={"against_sales_order": order_name, "docstatus": 1},
		fields=["parent"],
	)
	delivery_note_names = sorted({row.parent for row in delivery_note_rows if getattr(row, "parent", None)})

	invoice_item_rows = frappe.get_all(
		"Sales Invoice Item",
		filters={"sales_order": order_name, "docstatus": 1},
		fields=["parent"],
	)
	invoice_names = sorted({row.parent for row in invoice_item_rows if getattr(row, "parent", None)})
	return delivery_note_names, invoice_names


def _load_sales_invoice_rows(invoice_names: list[str]):
	if not invoice_names:
		return []

	return frappe.get_all(
		"Sales Invoice",
		filters={"name": ["in", invoice_names], "docstatus": 1, "is_return": 0},
		fields=["name", "grand_total", "rounded_total", "base_rounded_total", "outstanding_amount"],
	)


def _get_sales_order_doc_for_update(order_name: str, *, allow_cancelled: bool = False):
	if not order_name:
		frappe.throw(_("order_name 不能为空。"))

	so = frappe.get_doc("Sales Order", order_name)
	if cint(so.docstatus) == 2 and not allow_cancelled:
		frappe.throw(_("已取消的销售订单不允许继续修改。"))
	return so


def _ensure_sales_order_items_editable(so):
	if cint(so.docstatus) == 2:
		frappe.throw(_("已取消的销售订单不允许修改商品明细。"))

	delivery_note_names, invoice_names = _collect_sales_order_reference_names(so.name)
	if delivery_note_names or invoice_names:
		frappe.throw(_("销售订单 {0} 已存在发货或开票记录，当前不允许修改商品明细。").format(so.name))

	fulfillment = _build_fulfillment_summary(list(so.get("items") or []))
	if fulfillment.get("delivered_qty", 0) > 0:
		frappe.throw(_("销售订单 {0} 已存在出货记录，当前不允许修改商品明细。").format(so.name))


def _save_sales_order_after_update(so):
	so.flags.ignore_validate_update_after_submit = True
	so.flags.ignore_permissions = True
	so.save()
	return so


def _commit_sales_order_context_update(so, fieldnames: list[str]):
	if cint(so.docstatus) == 1:
		for fieldname in fieldnames:
			if so.meta.has_field(fieldname):
				so.db_set(fieldname, so.get(fieldname), update_modified=True)
		so.reload()
		return so

	return _save_sales_order_after_update(so)


def _prepare_sales_order_for_item_replacement(so):
	if cint(so.docstatus) != 1:
		return so, so.name

	original_name = so.name
	so.cancel()
	amended = frappe.copy_doc(so)
	amended.amended_from = original_name
	amended.docstatus = 0
	amended.name = None
	return amended, original_name


def _ensure_sales_order_cancellable(so):
	if cint(so.docstatus) == 2:
		return
	if cint(so.docstatus) != 1:
		frappe.throw(_("只有已提交的销售订单才允许作废。"))

	delivery_note_names, invoice_names = _collect_sales_order_reference_names(so.name)
	if delivery_note_names or invoice_names:
		frappe.throw(_("销售订单 {0} 已存在发货或开票记录，当前不允许作废。").format(so.name))


def get_sales_order_detail(order_name: str):
	if not order_name:
		frappe.throw(_("order_name 不能为空。"))

	try:
		so = frappe.get_doc("Sales Order", order_name)
		order_items = list(so.get("items") or [])
		delivery_note_names, invoice_names = _collect_sales_order_reference_names(order_name)
		invoice_rows = _load_sales_invoice_rows(invoice_names)

		fulfillment = _build_fulfillment_summary(order_items)
		payment = _build_payment_summary(invoice_rows)
		latest_payment_entry = _get_latest_payment_entry_summary(invoice_names)
		payment["actual_paid_amount"] = latest_payment_entry.get("total_actual_paid_amount")
		payment["total_writeoff_amount"] = latest_payment_entry.get("total_writeoff_amount")
		completion = _build_completion_summary(fulfillment, payment, docstatus=so.docstatus)
		amount_estimate = flt(so.get("rounded_total") or so.get("grand_total") or 0)
		delivery = _build_delivery_summary(
			fulfillment,
			delivery_note_names=delivery_note_names,
			docstatus=so.docstatus,
		)
		payment["latest_payment_entry"] = latest_payment_entry.get("payment_entry")
		payment["latest_payment_invoice"] = latest_payment_entry.get("invoice_name")
		payment["latest_unallocated_amount"] = latest_payment_entry.get("unallocated_amount")
		payment["latest_writeoff_amount"] = latest_payment_entry.get("writeoff_amount")
		payment["latest_actual_paid_amount"] = latest_payment_entry.get("actual_paid_amount")

		return {
			"status": "success",
			"data": {
				"order_name": so.name,
				"document_status": _document_status_label(so.docstatus),
				"customer": _build_customer_snapshot(so),
				"shipping": _build_shipping_snapshot(so),
				"amounts": {
					"order_amount_estimate": amount_estimate,
					"receivable_amount": payment["receivable_amount"],
					"paid_amount": payment["paid_amount"],
					"outstanding_amount": payment["outstanding_amount"],
				},
				"fulfillment": fulfillment,
				"delivery": delivery,
				"payment": payment,
				"completion": completion,
				"actions": _build_action_flags(
					fulfillment,
					payment,
					invoice_names=invoice_names,
					delivery_note_names=delivery_note_names,
					docstatus=so.docstatus,
				),
				"items": _serialize_order_items(order_items),
				"references": {
					"delivery_notes": delivery_note_names,
					"sales_invoices": invoice_names,
					"latest_payment_entry": latest_payment_entry.get("payment_entry"),
				},
				"meta": {
					"company": so.company,
					"currency": so.get("currency"),
					"transaction_date": so.get("transaction_date"),
					"delivery_date": so.get("delivery_date"),
					"remarks": _get_sales_order_remark(so),
				},
			},
			"message": _("销售订单 {0} 详情获取成功。").format(so.name),
		}
	except frappe.DoesNotExistError:
		raise
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("销售订单详情获取失败"))
		raise


def get_delivery_note_detail(delivery_note_name: str):
	if not delivery_note_name:
		frappe.throw(_("delivery_note_name 不能为空。"))

	try:
		dn = frappe.get_doc("Delivery Note", delivery_note_name)
		delivery_items = list(dn.get("items") or [])
		references = _build_delivery_note_references(delivery_items)
		total_qty = _sum_row_values(delivery_items, "qty")
		total_amount = flt(dn.get("rounded_total") or dn.get("grand_total") or 0)

		return {
			"status": "success",
			"data": {
				"delivery_note_name": dn.name,
				"document_status": _document_status_label(dn.docstatus),
				"customer": _build_customer_snapshot_for_doc(dn),
				"shipping": _build_shipping_snapshot_for_doc(dn),
				"amounts": {
					"delivery_amount_estimate": total_amount,
				},
				"fulfillment": {
					"total_qty": total_qty,
					"status": "shipped" if cint(dn.docstatus) == 1 else "draft",
				},
				"references": references,
				"items": _serialize_delivery_note_items(delivery_items),
				"meta": {
					"company": dn.company,
					"currency": dn.get("currency"),
					"posting_date": dn.get("posting_date"),
					"posting_time": dn.get("posting_time"),
					"remarks": dn.get("remarks"),
				},
			},
			"message": _("发货单 {0} 详情获取成功。").format(dn.name),
		}
	except frappe.DoesNotExistError:
		raise
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("发货单详情获取失败"))
		raise


def get_sales_invoice_detail(sales_invoice_name: str):
	if not sales_invoice_name:
		frappe.throw(_("sales_invoice_name 不能为空。"))

	try:
		si = frappe.get_doc("Sales Invoice", sales_invoice_name)
		invoice_items = list(si.get("items") or [])
		references = _build_sales_invoice_references(invoice_items)
		payment = _build_payment_summary([si])
		latest_payment_entry = _get_latest_payment_entry_summary([si.name])
		payment["actual_paid_amount"] = latest_payment_entry.get("total_actual_paid_amount")
		payment["total_writeoff_amount"] = latest_payment_entry.get("total_writeoff_amount")
		payment["latest_payment_entry"] = latest_payment_entry.get("payment_entry")
		payment["latest_payment_invoice"] = latest_payment_entry.get("invoice_name")
		payment["latest_unallocated_amount"] = latest_payment_entry.get("unallocated_amount")
		payment["latest_writeoff_amount"] = latest_payment_entry.get("writeoff_amount")
		payment["latest_actual_paid_amount"] = latest_payment_entry.get("actual_paid_amount")

		return {
			"status": "success",
			"data": {
				"sales_invoice_name": si.name,
				"document_status": _document_status_label(si.docstatus),
				"customer": _build_customer_snapshot_for_doc(si),
				"shipping": _build_shipping_snapshot_for_doc(si),
				"amounts": {
					"invoice_amount_estimate": flt(si.get("rounded_total") or si.get("grand_total") or 0),
					"receivable_amount": payment["receivable_amount"],
					"paid_amount": payment["paid_amount"],
					"outstanding_amount": payment["outstanding_amount"],
				},
				"payment": payment,
				"references": {
					**references,
					"latest_payment_entry": latest_payment_entry.get("payment_entry"),
				},
				"items": _serialize_sales_invoice_items(invoice_items),
				"meta": {
					"company": si.company,
					"currency": si.get("currency"),
					"posting_date": si.get("posting_date"),
					"due_date": si.get("due_date"),
					"remarks": si.get("remarks"),
				},
			},
			"message": _("销售发票 {0} 详情获取成功。").format(si.name),
		}
	except frappe.DoesNotExistError:
		raise
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("销售发票详情获取失败"))
		raise


def get_sales_order_status_summary(customer: str | None = None, company: str | None = None, limit: int = 20):
	limit = max(1, min(int(limit or 20), 100))
	filters = {}
	if customer:
		filters["customer"] = customer
	if company:
		filters["company"] = company

	try:
		order_rows = frappe.get_all(
			"Sales Order",
			filters=filters,
			fields=[
				"name",
				"customer",
				"customer_name",
				"transaction_date",
				"company",
				"docstatus",
				"rounded_total",
				"grand_total",
				"modified",
			],
			order_by="modified desc",
			limit_page_length=limit,
		)

		summaries = []
		for row in order_rows:
			detail = get_sales_order_detail(row.name)
			data = detail.get("data", {})
			summaries.append(
				{
					"order_name": row.name,
					"customer_name": row.customer_name or row.customer,
					"customer": row.customer,
					"company": row.company,
					"transaction_date": row.transaction_date,
					"document_status": _document_status_label(row.docstatus),
					"order_amount_estimate": flt(row.rounded_total or row.grand_total or 0),
					"fulfillment": data.get("fulfillment", {}),
					"payment": data.get("payment", {}),
					"completion": data.get("completion", {}),
					"outstanding_amount": flt(data.get("payment", {}).get("outstanding_amount", 0) or 0),
					"modified": row.modified,
				}
			)

		return {
			"status": "success",
			"data": summaries,
			"meta": {
				"filters": {
					"customer": customer,
					"company": company,
					"limit": limit,
				}
			},
			"message": _("销售订单状态摘要获取成功。"),
		}
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("销售订单状态摘要获取失败"))
		raise


def create_order(customer: str, items: list[dict], immediate: bool = False, **kwargs):
	items = _coerce_json_value(items, [])
	company = kwargs.get("company") or frappe.defaults.get_user_default("company")
	delivery_date = kwargs.get("delivery_date") or nowdate()
	default_warehouse = kwargs.get("default_warehouse")
	request_id = kwargs.get("request_id")

	_validate_order_inputs(customer, items, company)

	try:
		def _create_order():
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
				_set_sales_order_remark(so, kwargs["remarks"])

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

			return result

		return run_idempotent("create_order", request_id, _create_order)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("订单创建失败"))
		raise


def create_order_v2(customer: str, items: list[dict], immediate: bool = False, **kwargs):
	items = _coerce_json_value(items, [])
	company = kwargs.get("company") or frappe.defaults.get_user_default("company")
	delivery_date = kwargs.get("delivery_date") or nowdate()
	default_warehouse = kwargs.get("default_warehouse")
	request_id = kwargs.get("request_id")
	customer_info = kwargs.get("customer_info")
	shipping_info = kwargs.get("shipping_info")

	_validate_order_inputs(customer, items, company)

	try:
		def _create_order_v2():
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
				_set_sales_order_remark(so, kwargs["remarks"])

			snapshot = _apply_sales_order_v2_snapshot(
				so,
				customer_info=customer_info,
				shipping_info=shipping_info,
				kwargs=kwargs,
			)

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
				"message": _("销售订单 {0} 已按 v2 模型创建并提交。").format(so.name),
				"snapshot": snapshot,
			}

			if cint(immediate):
				dn = submit_delivery(so.name, kwargs=kwargs)
				si = create_sales_invoice(so.name, kwargs=kwargs)
				result.update(
					{
						"delivery_note": dn["delivery_note"],
						"sales_invoice": si["sales_invoice"],
						"message": _("订单 {0} 已按 v2 模型完成下单、发货和开票。").format(so.name),
					}
				)

			return result

		return run_idempotent("create_order_v2", request_id, _create_order_v2)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("v2 订单创建失败"))
		raise


def update_order_v2(order_name: str, **kwargs):
	request_id = kwargs.get("request_id")
	customer_info = kwargs.get("customer_info")
	shipping_info = kwargs.get("shipping_info")

	try:
		def _update_order_v2():
			so = _get_sales_order_doc_for_update(order_name)
			if kwargs.get("delivery_date") is not None:
				so.delivery_date = kwargs.get("delivery_date") or None
			if kwargs.get("transaction_date") is not None:
				so.transaction_date = kwargs.get("transaction_date") or None
			if kwargs.get("remarks") is not None:
				_set_sales_order_remark(so, kwargs.get("remarks") or None)
			if kwargs.get("po_no") is not None and so.meta.has_field("po_no"):
				so.po_no = kwargs.get("po_no") or None

			snapshot = _apply_sales_order_v2_snapshot(
				so,
				customer_info=customer_info,
				shipping_info=shipping_info,
				kwargs=kwargs,
				overwrite=True,
			)

			_commit_sales_order_context_update(
				so,
				[
					"transaction_date",
					"delivery_date",
					"po_no",
					"contact_person",
					"contact_display",
					"contact_mobile",
					"contact_phone",
					"contact_email",
					"shipping_address_name",
					"customer_address",
					"address_display",
				] + ([_get_sales_order_remark_field()] if _get_sales_order_remark_field() else []),
			)

			return {
				"status": "success",
				"order": so.name,
				"message": _("销售订单 {0} 已按 v2 模型更新。").format(so.name),
				"snapshot": snapshot,
				"meta": {
					"transaction_date": so.get("transaction_date"),
					"delivery_date": so.get("delivery_date"),
					"remarks": _get_sales_order_remark(so),
				},
			}

		return run_idempotent("update_order_v2", request_id, _update_order_v2)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("v2 订单更新失败"))
		raise


def update_order_items_v2(order_name: str, items: list[dict], **kwargs):
	items = _coerce_json_value(items, [])
	request_id = kwargs.get("request_id")

	try:
		def _update_order_items_v2():
			so = _get_sales_order_doc_for_update(order_name)
			_ensure_sales_order_items_editable(so)
			target_so, source_order_name = _prepare_sales_order_for_item_replacement(so)

			company = kwargs.get("company") or target_so.company
			delivery_date = kwargs.get("delivery_date") or target_so.get("delivery_date") or nowdate()
			default_warehouse = kwargs.get("default_warehouse")

			if not items:
				frappe.throw(_("无法将销售订单更新为空商品明细。"))

			normalized_items = [
				_build_sales_order_item(item, delivery_date, default_warehouse, company)
				for item in items
			]

			target_so.set("items", [])
			for row in normalized_items:
				target_so.append("items", row)

			if kwargs.get("delivery_date") is not None:
				target_so.delivery_date = kwargs.get("delivery_date") or None

			_insert_and_submit(target_so)

			return {
				"status": "success",
				"order": target_so.name,
				"source_order": source_order_name,
				"message": _("销售订单 {0} 商品明细已按 v2 模型更新。").format(target_so.name),
				"items": _serialize_order_items(list(target_so.get("items") or [])),
				"meta": {
					"delivery_date": target_so.get("delivery_date"),
					"company": target_so.company,
				},
			}

		return run_idempotent("update_order_items_v2", request_id, _update_order_items_v2)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("v2 订单商品明细更新失败"))
		raise


def cancel_order_v2(order_name: str, **kwargs):
	request_id = kwargs.get("request_id")

	try:
		def _cancel_order_v2():
			so = _get_sales_order_doc_for_update(order_name, allow_cancelled=True)
			delivery_note_names, invoice_names = _collect_sales_order_reference_names(so.name)

			if cint(so.docstatus) == 2:
				detail = get_sales_order_detail(so.name)
				return {
					"status": "success",
					"order": so.name,
					"document_status": "cancelled",
					"message": _("销售订单 {0} 已处于作废状态。").format(so.name),
					"references": {
						"delivery_notes": delivery_note_names,
						"sales_invoices": invoice_names,
					},
					"detail": detail.get("data", {}),
				}

			_ensure_sales_order_cancellable(so)
			so.cancel()
			detail = get_sales_order_detail(so.name)
			return {
				"status": "success",
				"order": so.name,
				"document_status": "cancelled",
				"message": _("销售订单 {0} 已按 v2 模型作废。").format(so.name),
				"references": {
					"delivery_notes": delivery_note_names,
					"sales_invoices": invoice_names,
				},
				"detail": detail.get("data", {}),
			}

		return run_idempotent("cancel_order_v2", request_id, _cancel_order_v2)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("v2 订单作废失败"))
		raise


def submit_delivery(order_name: str, delivery_items: list[dict] | None = None, kwargs: dict | None = None):
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

	if not order_name:
		frappe.throw(_("order_name 不能为空。"))

	delivery_items = _coerce_json_value(delivery_items, [])
	kwargs = _coerce_json_value(kwargs, {}) or {}
	request_id = kwargs.get("request_id")
	force_delivery = cint(kwargs.get("force_delivery"))

	try:
		def _submit_delivery():
			dn = make_delivery_note(order_name, kwargs={"skip_item_mapping": 0})
			_ensure_target_has_items(dn, _("销售订单 {0} 当前没有可发货的商品明细。").format(order_name))

			if delivery_items:
				item_overrides = _build_item_override_map(
					delivery_items,
					detail_keys=("sales_order_item", "so_detail"),
				)
				dn.items = _apply_item_overrides(
					dn.items,
					item_overrides,
					detail_attrs=("so_detail", "sales_order_item"),
				)
				_ensure_target_has_items(dn, _("未找到可发货的商品明细。"))

			if kwargs.get("set_posting_time") is not None:
				dn.set_posting_time = cint(kwargs["set_posting_time"])
			if kwargs.get("posting_date"):
				dn.posting_date = kwargs["posting_date"]
			if kwargs.get("posting_time"):
				dn.posting_time = kwargs["posting_time"]
			if kwargs.get("remarks"):
				dn.remarks = kwargs["remarks"]

			if not force_delivery:
				_validate_stock_for_immediate_delivery(
					[
						{
							"item_code": getattr(item, "item_code", None),
							"warehouse": getattr(item, "warehouse", None),
							"qty": flt(getattr(item, "qty", 0) or 0),
						}
						for item in dn.items or []
					]
				)

			try:
				if force_delivery:
					_insert_and_submit_with_temporary_negative_stock(dn)
				else:
					_insert_and_submit(dn)
			except Exception:
				dn_name = getattr(dn, "name", None)
				if dn_name and frappe.db.exists("Delivery Note", dn_name):
					docstatus = cint(frappe.db.get_value("Delivery Note", dn_name, "docstatus") or 0)
					if docstatus == 0:
						frappe.delete_doc("Delivery Note", dn_name, ignore_permissions=True, force=1)
				raise

			return {
				"status": "success",
				"delivery_note": dn.name,
				"message": (
					_("发货单 {0} 已强制创建并提交。").format(dn.name)
					if force_delivery
					else _("发货单 {0} 已创建并提交。").format(dn.name)
				),
				"force_delivery": bool(force_delivery),
			}

		return run_idempotent("submit_delivery", request_id, _submit_delivery)
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
	request_id = kwargs.get("request_id")

	try:
		def _create_sales_invoice():
			si = make_sales_invoice(source_name)
			_ensure_target_has_items(si, _("销售订单 {0} 当前没有可开票的商品明细。").format(source_name))

			if invoice_items:
				item_overrides = _build_item_override_map(
					invoice_items,
					detail_keys=("sales_order_item", "so_detail"),
				)
				si.items = _apply_item_overrides(
					si.items,
					item_overrides,
					detail_attrs=("so_detail", "sales_order_item"),
				)
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

		return run_idempotent("create_sales_invoice", request_id, _create_sales_invoice)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("开票处理失败"))
		raise
