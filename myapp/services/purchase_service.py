import frappe
import heapq
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from myapp.services.order_service import (
	_build_payment_summary,
	_document_status_label,
	_extract_first_non_empty,
	_get_doc_if_exists,
	_get_linked_parent_names,
	_serialize_address_doc,
	_serialize_contact_doc,
	_sum_row_values,
)
from myapp.services.wholesale_service import _get_item_specification_field
from myapp.services.return_service import build_return_submission_payload
from myapp.services.settlement_service import cancel_payment_entry
from myapp.utils.idempotency import run_idempotent
from myapp.utils.uom import resolve_item_quantity_to_stock


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


def _new_doc(doctype: str):
	return frappe.new_doc(doctype)


def _normalize_text(value: str | None):
	return (value or "").strip()


def _normalize_limit(limit: int | None):
	return max(1, min(int(limit or 20), 100))


def _normalize_start(start: int | None):
	return max(0, int(start or 0))


def _normalize_disabled(value):
	if value in (None, ""):
		return None
	return cint(value)


def _normalize_master_date_range(date_from: str | None = None, date_to: str | None = None):
	resolved_date_from = _normalize_text(date_from) or None
	resolved_date_to = _normalize_text(date_to) or None
	if not resolved_date_from and not resolved_date_to:
		return None, None
	if resolved_date_from and resolved_date_to and getdate(resolved_date_from) > getdate(resolved_date_to):
		frappe.throw(_("date_from 不能晚于 date_to。"))
	return resolved_date_from, resolved_date_to


def _normalize_purchase_date_range(date_from: str | None = None, date_to: str | None = None):
	resolved_date_from = _normalize_text(date_from) or None
	resolved_date_to = _normalize_text(date_to) or None
	if not resolved_date_from and not resolved_date_to:
		return None, None
	if resolved_date_from and resolved_date_to and getdate(resolved_date_from) > getdate(resolved_date_to):
		frappe.throw(_("date_from 不能晚于 date_to。"))
	return resolved_date_from, resolved_date_to


def _normalize_payload(payload):
	if payload in (None, "", {}):
		return {}
	if isinstance(payload, str):
		try:
			payload = frappe.parse_json(payload)
		except Exception:
			return {}
	return dict(payload or {})


def _normalize_contact_payload(payload, kwargs=None):
	data = _normalize_payload(payload)
	kwargs = kwargs or {}
	display_name = _normalize_text(data.get("display_name") or data.get("full_name") or kwargs.get("contact_display_name"))
	first_name = _normalize_text(data.get("first_name"))
	last_name = _normalize_text(data.get("last_name"))
	if not first_name and display_name:
		parts = display_name.split()
		first_name = parts[0]
		last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
	return {
		"name": _normalize_text(data.get("name")),
		"display_name": display_name or _extract_first_non_empty(first_name, last_name),
		"first_name": first_name,
		"last_name": last_name,
		"phone": _normalize_text(data.get("phone") or data.get("mobile_no") or kwargs.get("contact_phone")),
		"email": _normalize_text(data.get("email") or data.get("email_id") or kwargs.get("contact_email")),
	}


def _normalize_address_payload(payload, kwargs=None):
	data = _normalize_payload(payload)
	kwargs = kwargs or {}
	return {
		"name": _normalize_text(data.get("name")),
		"address_line1": _normalize_text(data.get("address_line1") or kwargs.get("address_line1")),
		"address_line2": _normalize_text(data.get("address_line2") or kwargs.get("address_line2")),
		"city": _normalize_text(data.get("city") or kwargs.get("city")),
		"county": _normalize_text(data.get("county") or kwargs.get("county")),
		"state": _normalize_text(data.get("state") or kwargs.get("state")),
		"country": _normalize_text(data.get("country") or kwargs.get("country")),
		"pincode": _normalize_text(data.get("pincode") or kwargs.get("pincode")),
		"email": _normalize_text(data.get("email") or data.get("email_id") or kwargs.get("address_email")),
		"phone": _normalize_text(data.get("phone") or kwargs.get("address_phone")),
		"address_type": _normalize_text(data.get("address_type") or kwargs.get("address_type")) or "Billing",
		"address_title": _normalize_text(data.get("address_title")),
	}


def _has_meaningful_contact_payload(payload: dict):
	return any(
		payload.get(key)
		for key in ("name", "display_name", "first_name", "last_name", "phone", "email")
	)


def _has_meaningful_address_payload(payload: dict):
	required_fields = ("address_line1", "city", "country")
	return bool(payload.get("name")) or any(payload.get(key) for key in required_fields)


def _normalize_sort(sort_by: str | None, sort_order: str | None):
	allowed_sort_by = {"modified", "creation", "supplier_name", "name"}
	allowed_sort_order = {"asc", "desc"}
	resolved_sort_by = _normalize_text(sort_by) or "modified"
	resolved_sort_order = (_normalize_text(sort_order) or "desc").lower()
	if resolved_sort_by not in allowed_sort_by:
		resolved_sort_by = "modified"
	if resolved_sort_order not in allowed_sort_order:
		resolved_sort_order = "desc"
	return resolved_sort_by, resolved_sort_order


def _normalize_purchase_status_filter(status_filter: str | None):
	allowed_filters = {"all", "unfinished", "receiving", "paying", "completed", "cancelled"}
	resolved = (_normalize_text(status_filter) or "all").lower()
	if resolved not in allowed_filters:
		return "all"
	return resolved


def _normalize_purchase_desk_sort(sort_by: str | None):
	allowed_sorts = {"unfinished_first", "latest", "oldest", "amount_desc", "amount_asc"}
	resolved = (_normalize_text(sort_by) or "unfinished_first").lower()
	if resolved not in allowed_sorts:
		return "unfinished_first"
	return resolved


def _normalize_bool_flag(value, default: bool = False):
	if value in (None, ""):
		return default
	if isinstance(value, bool):
		return value
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes", "y", "on"}
	return bool(value)


def _include_detail_in_response(kwargs: dict | None, *, default: bool = False):
	return _normalize_bool_flag((kwargs or {}).get("include_detail"), default=default)


def _safe_doc_field(doctype: str, fieldname: str) -> bool:
	try:
		return bool(frappe.get_meta(doctype).has_field(fieldname))
	except Exception:
		return False


def _supplier_name_exists(supplier_name: str):
	return bool(frappe.db.exists("Supplier", {"supplier_name": supplier_name}))


def _ensure_supplier_link(doc, supplier_name: str):
	links = list(getattr(doc, "links", []) or [])
	for link in links:
		if getattr(link, "link_doctype", None) == "Supplier" and getattr(link, "link_name", None) == supplier_name:
			return
	doc.append("links", {"link_doctype": "Supplier", "link_name": supplier_name})


def _upsert_supplier_primary_contact(supplier_doc, payload: dict):
	if not _has_meaningful_contact_payload(payload):
		return _get_doc_if_exists("Contact", getattr(supplier_doc, "supplier_primary_contact", None))

	contact = _get_doc_if_exists("Contact", payload.get("name") or getattr(supplier_doc, "supplier_primary_contact", None))
	is_new = not contact
	if is_new:
		contact = _new_doc("Contact")

	contact.first_name = payload.get("first_name") or payload.get("display_name") or supplier_doc.supplier_name or supplier_doc.name
	contact.last_name = payload.get("last_name")
	contact.company_name = supplier_doc.supplier_name or supplier_doc.name
	contact.is_primary_contact = 1
	_ensure_supplier_link(contact, supplier_doc.name)
	contact.set("phone_nos", [])
	contact.set("email_ids", [])
	if payload.get("phone"):
		contact.add_phone(payload.get("phone"), is_primary_mobile_no=True)
	if payload.get("email"):
		contact.add_email(payload.get("email"), is_primary=True)

	if is_new:
		contact.insert()
	else:
		contact.save()
	return contact


def _upsert_supplier_primary_address(supplier_doc, payload: dict):
	if not _has_meaningful_address_payload(payload):
		return _get_doc_if_exists("Address", getattr(supplier_doc, "supplier_primary_address", None))

	address = _get_doc_if_exists("Address", payload.get("name") or getattr(supplier_doc, "supplier_primary_address", None))
	is_new = not address
	if is_new:
		address = _new_doc("Address")

	address.address_title = payload.get("address_title") or supplier_doc.supplier_name or supplier_doc.name
	address.address_type = payload.get("address_type") or "Billing"
	address.address_line1 = payload.get("address_line1")
	address.address_line2 = payload.get("address_line2")
	address.city = payload.get("city")
	address.county = payload.get("county")
	address.state = payload.get("state")
	address.country = payload.get("country")
	address.pincode = payload.get("pincode")
	address.email_id = payload.get("email")
	address.phone = payload.get("phone")
	address.is_primary_address = 1
	_ensure_supplier_link(address, supplier_doc.name)

	if is_new:
		address.insert()
	else:
		address.save()
	return address


def _build_supplier_snapshot_for_doc(doc):
	contact_doc = _get_doc_if_exists("Contact", doc.get("contact_person"))
	address_doc = _get_doc_if_exists("Address", doc.get("supplier_address"))

	return {
		"name": doc.get("supplier"),
		"display_name": doc.get("supplier_name") or doc.get("supplier"),
		"contact_person": doc.get("contact_person"),
		"contact_display_name": _extract_first_non_empty(
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
		"supplier_address_name": doc.get("supplier_address"),
		"supplier_address_text": _extract_first_non_empty(
			doc.get("address_display"),
			getattr(address_doc, "address_display", None) if address_doc else None,
			getattr(address_doc, "address_line1", None) if address_doc else None,
		),
	}


def _get_purchase_default_warehouse_for_company(company: str | None):
	company = _normalize_text(company)
	if not company:
		return None

	user_warehouse = _extract_first_non_empty(frappe.defaults.get_user_default("warehouse"))
	if user_warehouse:
		warehouse_company = frappe.db.get_value("Warehouse", user_warehouse, "company")
		if warehouse_company == company:
			return user_warehouse

	return frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")


def _is_purchase_summary_cancelled(summary_row: dict):
	return summary_row.get("document_status") == "cancelled"


def _is_purchase_summary_completed(summary_row: dict):
	return (summary_row.get("completion") or {}).get("status") == "completed"


def _is_purchase_summary_unfinished(summary_row: dict):
	return not _is_purchase_summary_cancelled(summary_row) and not _is_purchase_summary_completed(summary_row)


def _is_purchase_summary_receiving_pending(summary_row: dict):
	return summary_row.get("document_status") == "submitted" and not bool(
		(summary_row.get("receiving") or {}).get("is_fully_received")
	)


def _is_purchase_summary_payment_pending(summary_row: dict):
	return summary_row.get("document_status") == "submitted" and (summary_row.get("payment") or {}).get("status") != "paid"


def _purchase_summary_matches_filter(summary_row: dict, status_filter: str, exclude_cancelled: bool = False):
	if exclude_cancelled and _is_purchase_summary_cancelled(summary_row):
		return False

	if status_filter == "unfinished":
		return _is_purchase_summary_unfinished(summary_row)
	if status_filter == "receiving":
		return _is_purchase_summary_receiving_pending(summary_row)
	if status_filter == "paying":
		return _is_purchase_summary_payment_pending(summary_row)
	if status_filter == "completed":
		return _is_purchase_summary_completed(summary_row)
	if status_filter == "cancelled":
		return _is_purchase_summary_cancelled(summary_row)
	return True


def _purchase_summary_sort_weight(summary_row: dict):
	if _is_purchase_summary_cancelled(summary_row):
		return 4
	if _is_purchase_summary_completed(summary_row):
		return 3
	if (summary_row.get("payment") or {}).get("status") == "paid":
		return 2
	if (summary_row.get("receiving") or {}).get("is_fully_received"):
		return 1
	return 0


def _get_purchase_summary_modified_time(summary_row: dict):
	value = summary_row.get("modified")
	try:
		return frappe.utils.get_datetime(value)
	except Exception:
		return frappe.utils.get_datetime("1900-01-01")


def _get_purchase_summary_transaction_time(summary_row: dict):
	value = summary_row.get("transaction_date")
	try:
		return frappe.utils.get_datetime(value)
	except Exception:
		return frappe.utils.get_datetime("1900-01-01")


def _sort_purchase_summary_rows(rows: list[dict], sort_by: str):
	resolved_sort = _normalize_purchase_desk_sort(sort_by)
	if resolved_sort == "amount_asc":
		return sorted(
			rows,
			key=lambda row: (flt(row.get("order_amount_estimate") or 0), _get_purchase_summary_modified_time(row)),
		)
	if resolved_sort == "amount_desc":
		return sorted(
			rows,
			key=lambda row: (flt(row.get("order_amount_estimate") or 0), _get_purchase_summary_modified_time(row)),
			reverse=True,
		)
	if resolved_sort == "oldest":
		return sorted(rows, key=lambda row: (_get_purchase_summary_transaction_time(row), _get_purchase_summary_modified_time(row)))
	if resolved_sort == "latest":
		return sorted(rows, key=_get_purchase_summary_modified_time, reverse=True)

	return sorted(
		rows,
		key=lambda row: (_purchase_summary_sort_weight(row), -_get_purchase_summary_modified_time(row).timestamp()),
	)


def _purchase_search_batch_size(limit: int, start: int):
	return max(100, min(max(limit + start, 0) + 40, 300))


def _purchase_summary_rank(summary_row: dict, sort_by: str):
	resolved_sort = _normalize_purchase_desk_sort(sort_by)
	modified_ts = _get_purchase_summary_modified_time(summary_row).timestamp()
	if resolved_sort == "amount_asc":
		return (-flt(summary_row.get("order_amount_estimate") or 0), -modified_ts)
	if resolved_sort == "amount_desc":
		return (flt(summary_row.get("order_amount_estimate") or 0), modified_ts)
	if resolved_sort == "unfinished_first":
		return (-_purchase_summary_sort_weight(summary_row), modified_ts)
	return None


def _finalize_purchase_ranked_page(heap_rows: list[tuple], sort_by: str, start: int, limit: int):
	if not heap_rows:
		return []

	resolved_sort = _normalize_purchase_desk_sort(sort_by)
	if resolved_sort == "amount_asc":
		sorted_rows = sorted(
			[row for _, _, row in heap_rows],
			key=lambda row: (flt(row.get("order_amount_estimate") or 0), _get_purchase_summary_modified_time(row)),
		)
	elif resolved_sort == "amount_desc":
		sorted_rows = sorted(
			[row for _, _, row in heap_rows],
			key=lambda row: (flt(row.get("order_amount_estimate") or 0), _get_purchase_summary_modified_time(row)),
			reverse=True,
		)
	else:
		sorted_rows = sorted(
			[row for _, _, row in heap_rows],
			key=lambda row: (_purchase_summary_sort_weight(row), -_get_purchase_summary_modified_time(row).timestamp()),
		)
	return sorted_rows[start : start + limit]


def _build_empty_purchase_payment_summary():
	return {
		"receivable_amount": 0,
		"paid_amount": 0,
		"outstanding_amount": 0,
		"status": "unpaid",
		"is_fully_paid": False,
		"actual_paid_amount": 0,
		"total_writeoff_amount": 0,
		"latest_payment_entry": None,
		"latest_payment_invoice": None,
		"latest_unallocated_amount": 0,
		"latest_writeoff_amount": 0,
		"latest_actual_paid_amount": 0,
	}


def _build_purchase_latest_payment_summary_map(order_invoice_names_map: dict[str, list[str]]):
	order_names = list(order_invoice_names_map.keys())
	summary_map = {order_name: _build_empty_purchase_payment_summary() for order_name in order_names}
	all_invoice_names = sorted({invoice_name for invoice_names in order_invoice_names_map.values() for invoice_name in invoice_names})
	if not all_invoice_names:
		return summary_map

	reference_rows = frappe.get_all(
		"Payment Entry Reference",
		filters={
			"reference_doctype": "Purchase Invoice",
			"reference_name": ["in", all_invoice_names],
			"parenttype": "Payment Entry",
			"parentfield": "references",
		},
		fields=["parent", "reference_name", "allocated_amount", "modified"],
		limit_page_length=0,
	)
	if not reference_rows:
		return summary_map

	invoice_to_orders = {}
	for order_name, invoice_names in order_invoice_names_map.items():
		for invoice_name in invoice_names:
			invoice_to_orders.setdefault(invoice_name, set()).add(order_name)

	parent_names = []
	order_reference_map = {order_name: [] for order_name in order_names}
	for row in reference_rows:
		reference_name = getattr(row, "reference_name", None)
		parent = getattr(row, "parent", None)
		if parent and parent not in parent_names:
			parent_names.append(parent)
		for order_name in invoice_to_orders.get(reference_name, ()):
			order_reference_map[order_name].append(row)

	if not parent_names:
		return summary_map

	payment_entry_rows = frappe.get_all(
		"Payment Entry",
		filters={"name": ["in", parent_names], "docstatus": 1},
		fields=["name", "paid_amount", "received_amount", "unallocated_amount", "difference_amount", "modified"],
		order_by="modified desc",
		limit_page_length=0,
	)
	if not payment_entry_rows:
		return summary_map

	payment_entry_map = {getattr(row, "name", None): row for row in payment_entry_rows}

	for order_name, order_reference_rows in order_reference_map.items():
		if not order_reference_rows:
			continue

		total_allocated_by_parent = {}
		for row in order_reference_rows:
			parent = getattr(row, "parent", None)
			if not parent:
				continue
			total_allocated_by_parent[parent] = total_allocated_by_parent.get(parent, 0) + flt(
				getattr(row, "allocated_amount", 0) or 0
			)

		total_actual_paid_amount = 0
		total_writeoff_amount = 0
		for row in order_reference_rows:
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

		latest_payment_entry = next(
			(row for row in payment_entry_rows if getattr(row, "name", None) in total_allocated_by_parent),
			None,
		)
		latest_payment_entry_name = getattr(latest_payment_entry, "name", None) if latest_payment_entry else None
		latest_reference = max(
			(row for row in order_reference_rows if getattr(row, "parent", None) == latest_payment_entry_name),
			key=lambda row: str(getattr(row, "modified", "") or ""),
			default=None,
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

		summary_map[order_name] = {
			"payment_entry": latest_payment_entry_name,
			"invoice_name": getattr(latest_reference, "reference_name", None) if latest_reference else None,
			"allocated_amount": allocated_amount,
			"unallocated_amount": unallocated_amount,
			"writeoff_amount": writeoff_amount,
			"actual_paid_amount": actual_paid_amount,
			"total_actual_paid_amount": total_actual_paid_amount,
			"total_writeoff_amount": total_writeoff_amount,
		}

	return summary_map


def _build_purchase_order_summary_rows(order_rows):
	if not order_rows:
		return []

	order_names = [row.name for row in order_rows if getattr(row, "name", None)]
	item_rows = frappe.get_all(
		"Purchase Order Item",
		filters={"parent": ["in", order_names]},
		fields=["parent", "qty", "received_qty"],
		limit_page_length=0,
	)
	item_rows_by_order = {}
	for row in item_rows:
		parent = getattr(row, "parent", None)
		if not parent:
			continue
		item_rows_by_order.setdefault(parent, []).append(row)

	invoice_link_rows = frappe.get_all(
		"Purchase Invoice Item",
		filters={"purchase_order": ["in", order_names], "docstatus": 1},
		fields=["purchase_order", "parent"],
		limit_page_length=0,
	)
	order_invoice_names_map = {order_name: [] for order_name in order_names}
	for row in invoice_link_rows:
		order_name = getattr(row, "purchase_order", None)
		invoice_name = getattr(row, "parent", None)
		if not order_name or not invoice_name:
			continue
		if invoice_name not in order_invoice_names_map.setdefault(order_name, []):
			order_invoice_names_map[order_name].append(invoice_name)

	all_invoice_names = sorted({invoice_name for invoice_names in order_invoice_names_map.values() for invoice_name in invoice_names})
	invoice_row_map = {}
	if all_invoice_names:
		invoice_rows = frappe.get_all(
			"Purchase Invoice",
			filters={"name": ["in", all_invoice_names], "docstatus": 1, "is_return": 0},
			fields=["name", "grand_total", "rounded_total", "base_rounded_total", "outstanding_amount"],
			limit_page_length=0,
		)
		invoice_row_map = {getattr(row, "name", None): row for row in invoice_rows}

	latest_payment_summary_map = _build_purchase_latest_payment_summary_map(order_invoice_names_map)
	summaries = []
	for row in order_rows:
		receiving = _build_purchase_receiving_summary(item_rows_by_order.get(row.name, []))
		invoice_rows_for_order = [
			invoice_row_map[invoice_name]
			for invoice_name in order_invoice_names_map.get(row.name, [])
			if invoice_name in invoice_row_map
		]
		payment = _build_payment_summary(invoice_rows_for_order)
		latest_payment = latest_payment_summary_map.get(row.name, {})
		_apply_purchase_latest_payment_metrics(
			payment,
			{
				"total_actual_paid_amount": latest_payment.get("total_actual_paid_amount", 0),
				"total_writeoff_amount": latest_payment.get("total_writeoff_amount", 0),
				"payment_entry": latest_payment.get("payment_entry"),
				"invoice_name": latest_payment.get("invoice_name"),
				"unallocated_amount": latest_payment.get("unallocated_amount", 0),
				"writeoff_amount": latest_payment.get("writeoff_amount", 0),
				"actual_paid_amount": latest_payment.get("actual_paid_amount", 0),
			},
		)
		completion = _build_purchase_completion_summary(receiving, payment, docstatus=row.docstatus)
		summaries.append(
			{
				"purchase_order_name": row.name,
				"supplier_name": row.supplier_name or row.supplier,
				"supplier": row.supplier,
				"company": row.company,
				"transaction_date": row.transaction_date,
				"document_status": _document_status_label(row.docstatus),
				"order_amount_estimate": flt(row.rounded_total or row.grand_total or 0),
				"receiving": receiving,
				"payment": payment,
				"completion": completion,
				"outstanding_amount": flt(payment.get("outstanding_amount", 0) or 0),
				"modified": row.modified,
			}
		)

	return summaries


def _build_supplier_address_snapshot_for_doc(doc):
	address_doc = _get_doc_if_exists("Address", doc.get("supplier_address"))
	contact_doc = _get_doc_if_exists("Contact", doc.get("contact_person"))

	return {
		"supplier_address_name": doc.get("supplier_address"),
		"supplier_address_text": _extract_first_non_empty(
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


def _build_purchase_receiving_summary(order_items):
	total_qty = _sum_row_values(order_items, "qty")
	received_qty = _sum_row_values(order_items, "received_qty")
	remaining_qty = max(total_qty - received_qty, 0)

	if received_qty <= 0:
		status = "pending"
	elif received_qty < total_qty:
		status = "partial"
	else:
		status = "received"

	return {
		"total_qty": total_qty,
		"received_qty": received_qty,
		"remaining_qty": remaining_qty,
		"status": status,
		"is_fully_received": total_qty > 0 and remaining_qty <= 0,
	}


def _apply_purchase_latest_payment_metrics(payment: dict, latest_payment_entry: dict):
	payment["actual_paid_amount"] = latest_payment_entry.get("total_actual_paid_amount")
	payment["total_writeoff_amount"] = latest_payment_entry.get("total_writeoff_amount")
	payment["latest_payment_entry"] = latest_payment_entry.get("payment_entry")
	payment["latest_payment_invoice"] = latest_payment_entry.get("invoice_name")
	payment["latest_unallocated_amount"] = latest_payment_entry.get("unallocated_amount")
	payment["latest_writeoff_amount"] = latest_payment_entry.get("writeoff_amount") or 0
	payment["latest_actual_paid_amount"] = latest_payment_entry.get("actual_paid_amount") or 0
	return payment


def _build_purchase_completion_summary(receiving: dict, payment: dict, *, docstatus: int):
	if cint(docstatus) == 2:
		return {"status": "closed", "is_completed": False}

	is_completed = bool(receiving.get("is_fully_received") and payment.get("is_fully_paid"))
	return {
		"status": "completed" if is_completed else "open",
		"is_completed": is_completed,
	}


def _build_purchase_order_financial_summary(order_items, invoice_names: list[str], *, docstatus: int):
	invoice_rows = _load_purchase_invoice_rows(invoice_names)
	receiving = _build_purchase_receiving_summary(order_items)
	payment = _build_payment_summary(invoice_rows)
	latest_payment_entry = _get_latest_purchase_payment_entry_summary(invoice_names)
	_apply_purchase_latest_payment_metrics(payment, latest_payment_entry)
	completion = _build_purchase_completion_summary(receiving, payment, docstatus=docstatus)
	return receiving, payment, completion, latest_payment_entry


def _build_purchase_order_action_flags(receiving: dict, payment: dict, *, invoice_names: list[str], receipt_names: list[str], docstatus: int):
	is_submitted = cint(docstatus) == 1
	can_cancel_purchase_order = is_submitted and not invoice_names and not receipt_names
	cancel_purchase_order_hint = None
	if is_submitted and not can_cancel_purchase_order:
		cancel_purchase_order_hint = _("当前采购订单已存在收货或开票记录，请先回退下游单据后再作废订单。")
	elif cint(docstatus) == 0:
		cancel_purchase_order_hint = _("只有已提交的采购订单才允许作废。")

	return {
		"can_receive_purchase_order": is_submitted and not receiving.get("is_fully_received"),
		"can_create_purchase_invoice": is_submitted and not payment.get("is_fully_paid"),
		"can_record_supplier_payment": is_submitted and payment.get("outstanding_amount", 0) > 0,
		"can_process_purchase_return": bool(is_submitted and (invoice_names or receipt_names)),
		"can_cancel_purchase_order": can_cancel_purchase_order,
		"cancel_purchase_order_hint": cancel_purchase_order_hint,
	}


def _build_purchase_receipt_action_flags(*, docstatus: int, purchase_invoices: list[str]):
	is_submitted = cint(docstatus) == 1
	can_cancel = is_submitted and not purchase_invoices
	can_create_invoice = is_submitted and not purchase_invoices
	return {
		"can_cancel_purchase_receipt": can_cancel,
		"can_create_purchase_invoice": can_create_invoice,
		"cancel_purchase_receipt_hint": (
			_("当前收货单已关联采购发票，请先作废采购发票，再回退收货单。")
			if is_submitted and purchase_invoices
			else None
		),
	}


def _build_purchase_invoice_action_flags(*, docstatus: int, latest_payment_entry: str | None, paid_amount: float):
	is_submitted = cint(docstatus) == 1
	has_payment = bool(latest_payment_entry) or flt(paid_amount) > 0
	return {
		"can_cancel_purchase_invoice": is_submitted,
		"cancel_purchase_invoice_hint": (
			_("当前采购发票已经存在付款记录；若系统未启用作废时自动解绑付款，将需要先处理付款后才能作废。")
			if is_submitted and has_payment
			else None
		),
	}


def _serialize_purchase_order_items(order_items):
	item_specification_map = _get_item_specification_map(order_items)
	return [
		{
			"purchase_order_item": getattr(item, "name", None),
			"item_code": getattr(item, "item_code", None),
			"item_name": getattr(item, "item_name", None),
			"specification": item_specification_map.get(getattr(item, "item_code", None)),
			"uom": getattr(item, "uom", None),
			"warehouse": getattr(item, "warehouse", None),
			"qty": flt(getattr(item, "qty", 0) or 0),
			"received_qty": flt(getattr(item, "received_qty", 0) or 0),
			"billed_amt": flt(getattr(item, "billed_amt", 0) or 0),
			"rate": flt(getattr(item, "rate", 0) or 0),
			"amount": flt(getattr(item, "amount", 0) or 0),
			"schedule_date": getattr(item, "schedule_date", None),
		}
		for item in order_items or []
	]


def _serialize_purchase_receipt_items(receipt_items):
	item_specification_map = _get_item_specification_map(receipt_items)
	return [
		{
			"purchase_receipt_item": getattr(item, "name", None),
			"item_code": getattr(item, "item_code", None),
			"item_name": getattr(item, "item_name", None),
			"specification": item_specification_map.get(getattr(item, "item_code", None)),
			"uom": getattr(item, "uom", None),
			"warehouse": getattr(item, "warehouse", None),
			"qty": flt(getattr(item, "qty", 0) or 0),
			"rate": flt(getattr(item, "rate", 0) or 0),
			"amount": flt(getattr(item, "amount", 0) or 0),
			"purchase_order": getattr(item, "purchase_order", None),
			"purchase_order_item": getattr(item, "purchase_order_item", None),
		}
		for item in receipt_items or []
	]


def _serialize_purchase_invoice_items(invoice_items):
	item_specification_map = _get_item_specification_map(invoice_items)
	return [
		{
			"purchase_invoice_item": getattr(item, "name", None),
			"item_code": getattr(item, "item_code", None),
			"item_name": getattr(item, "item_name", None),
			"specification": item_specification_map.get(getattr(item, "item_code", None)),
			"uom": getattr(item, "uom", None),
			"warehouse": getattr(item, "warehouse", None),
			"qty": flt(getattr(item, "qty", 0) or 0),
			"rate": flt(getattr(item, "rate", 0) or 0),
			"amount": flt(getattr(item, "amount", 0) or 0),
			"purchase_order": getattr(item, "purchase_order", None),
			"purchase_order_item": getattr(item, "po_detail", None),
			"purchase_receipt": getattr(item, "purchase_receipt", None),
			"purchase_receipt_item": getattr(item, "pr_detail", None),
		}
		for item in invoice_items or []
	]


def _get_item_specification_map(items):
	item_codes = []
	for item in items or []:
		item_code = getattr(item, "item_code", None)
		if isinstance(item_code, str) and item_code and item_code not in item_codes:
			item_codes.append(item_code)

	specification_map = {}
	specification_field = _get_item_specification_field()
	if not item_codes or not specification_field:
		return specification_map

	for row in frappe.get_all(
		"Item",
		filters={"name": ["in", item_codes]},
		fields=["name", specification_field],
		limit_page_length=len(item_codes),
	):
		item_code = getattr(row, "name", None)
		if item_code:
			specification_map[item_code] = getattr(row, specification_field, None)
	return specification_map


def _collect_purchase_order_reference_names(order_name: str):
	receipt_rows = frappe.get_all(
		"Purchase Receipt Item",
		filters={"purchase_order": order_name, "docstatus": 1},
		fields=["parent"],
	)
	receipt_names = sorted({row.parent for row in receipt_rows if getattr(row, "parent", None)})

	invoice_rows = frappe.get_all(
		"Purchase Invoice Item",
		filters={"purchase_order": order_name, "docstatus": 1},
		fields=["parent"],
	)
	invoice_names = sorted({row.parent for row in invoice_rows if getattr(row, "parent", None)})
	return receipt_names, invoice_names


def _load_purchase_invoice_rows(invoice_names: list[str]):
	if not invoice_names:
		return []

	return frappe.get_all(
		"Purchase Invoice",
		filters={"name": ["in", invoice_names], "docstatus": 1, "is_return": 0},
		fields=["name", "grand_total", "rounded_total", "base_rounded_total", "outstanding_amount"],
	)


def _get_latest_purchase_payment_entry_summary(invoice_names: list[str]):
	return _build_purchase_latest_payment_summary_map({"__single__": invoice_names}).get(
		"__single__",
		_build_empty_purchase_payment_summary(),
	)


def _build_purchase_receipt_references(receipt_name: str, receipt_items):
	purchase_orders = []
	for item in receipt_items or []:
		order_name = getattr(item, "purchase_order", None)
		if order_name and order_name not in purchase_orders:
			purchase_orders.append(order_name)

	invoice_rows = frappe.get_all(
		"Purchase Invoice Item",
		filters={
			"purchase_receipt": receipt_name,
			"docstatus": 1,
		},
		fields=["parent"],
		limit_page_length=100,
	)
	purchase_invoices = []
	for row in invoice_rows:
		parent = getattr(row, "parent", None)
		if parent and parent not in purchase_invoices:
			purchase_invoices.append(parent)

	return {
		"purchase_orders": purchase_orders,
		"purchase_invoices": purchase_invoices,
	}


def _build_purchase_invoice_references(invoice_items):
	purchase_orders = []
	purchase_receipts = []
	for item in invoice_items or []:
		order_name = getattr(item, "purchase_order", None)
		if order_name and order_name not in purchase_orders:
			purchase_orders.append(order_name)

		receipt_name = getattr(item, "purchase_receipt", None)
		if receipt_name and receipt_name not in purchase_receipts:
			purchase_receipts.append(receipt_name)

	return {
		"purchase_orders": purchase_orders,
		"purchase_receipts": purchase_receipts,
	}


def get_purchase_order_detail_v2(order_name: str):
	if not order_name:
		frappe.throw(_("order_name 不能为空。"))

	try:
		po = frappe.get_doc("Purchase Order", order_name)
		order_items = list(po.get("items") or [])
		receipt_names, invoice_names = _collect_purchase_order_reference_names(order_name)
		receiving, payment, completion, latest_payment_entry = _build_purchase_order_financial_summary(
			order_items,
			invoice_names,
			docstatus=po.docstatus,
		)

		return {
			"status": "success",
			"data": {
				"purchase_order_name": po.name,
				"document_status": _document_status_label(po.docstatus),
				"supplier": _build_supplier_snapshot_for_doc(po),
				"address": _build_supplier_address_snapshot_for_doc(po),
				"amounts": {
					"order_amount_estimate": flt(po.get("rounded_total") or po.get("grand_total") or 0),
					"receivable_amount": payment["receivable_amount"],
					"paid_amount": payment["paid_amount"],
					"outstanding_amount": payment["outstanding_amount"],
				},
				"receiving": receiving,
				"payment": payment,
				"completion": completion,
				"actions": _build_purchase_order_action_flags(
					receiving,
					payment,
					invoice_names=invoice_names,
					receipt_names=receipt_names,
					docstatus=po.docstatus,
				),
				"items": _serialize_purchase_order_items(order_items),
				"references": {
					"purchase_receipts": receipt_names,
					"purchase_invoices": invoice_names,
					"latest_payment_entry": latest_payment_entry.get("payment_entry"),
				},
				"meta": {
					"company": po.company,
					"currency": po.get("currency"),
					"transaction_date": po.get("transaction_date"),
					"schedule_date": po.get("schedule_date"),
					"remarks": po.get("remarks"),
					"supplier_ref": po.get("supplier_ref"),
				},
			},
			"message": _("采购订单 {0} 详情获取成功。").format(po.name),
		}
	except frappe.DoesNotExistError:
		raise
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("采购订单详情获取失败"))
		raise


def get_purchase_receipt_detail_v2(receipt_name: str):
	if not receipt_name:
		frappe.throw(_("receipt_name 不能为空。"))

	try:
		pr = frappe.get_doc("Purchase Receipt", receipt_name)
		receipt_items = list(pr.get("items") or [])
		references = _build_purchase_receipt_references(receipt_name, receipt_items)
		total_qty = _sum_row_values(receipt_items, "qty")

		return {
			"status": "success",
			"data": {
				"purchase_receipt_name": pr.name,
				"document_status": _document_status_label(pr.docstatus),
				"supplier": _build_supplier_snapshot_for_doc(pr),
				"address": _build_supplier_address_snapshot_for_doc(pr),
				"amounts": {
					"receipt_amount_estimate": flt(pr.get("rounded_total") or pr.get("grand_total") or 0),
				},
				"receiving": {
					"total_qty": total_qty,
					"status": "received" if cint(pr.docstatus) == 1 else "draft",
				},
				"actions": _build_purchase_receipt_action_flags(
					docstatus=pr.docstatus,
					purchase_invoices=references.get("purchase_invoices", []),
				),
				"references": references,
				"items": _serialize_purchase_receipt_items(receipt_items),
				"meta": {
					"company": pr.company,
					"currency": pr.get("currency"),
					"posting_date": pr.get("posting_date"),
					"posting_time": pr.get("posting_time"),
					"remarks": pr.get("remarks"),
				},
			},
			"message": _("采购收货单 {0} 详情获取成功。").format(pr.name),
		}
	except frappe.DoesNotExistError:
		raise
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("采购收货单详情获取失败"))
		raise


def get_purchase_invoice_detail_v2(invoice_name: str):
	if not invoice_name:
		frappe.throw(_("invoice_name 不能为空。"))

	try:
		pi = frappe.get_doc("Purchase Invoice", invoice_name)
		invoice_items = list(pi.get("items") or [])
		references = _build_purchase_invoice_references(invoice_items)
		payment = _build_payment_summary([pi])
		latest_payment_entry = _get_latest_purchase_payment_entry_summary([pi.name])
		_apply_purchase_latest_payment_metrics(payment, latest_payment_entry)

		return {
			"status": "success",
			"data": {
				"purchase_invoice_name": pi.name,
				"document_status": _document_status_label(pi.docstatus),
				"supplier": _build_supplier_snapshot_for_doc(pi),
				"address": _build_supplier_address_snapshot_for_doc(pi),
				"amounts": {
					"invoice_amount_estimate": flt(pi.get("rounded_total") or pi.get("grand_total") or 0),
					"receivable_amount": payment["receivable_amount"],
					"paid_amount": payment["paid_amount"],
					"outstanding_amount": payment["outstanding_amount"],
				},
				"payment": payment,
				"actions": _build_purchase_invoice_action_flags(
					docstatus=pi.docstatus,
					latest_payment_entry=latest_payment_entry.get("payment_entry"),
					paid_amount=flt(payment.get("paid_amount") or 0),
				),
				"references": {
					**references,
					"latest_payment_entry": latest_payment_entry.get("payment_entry"),
				},
				"items": _serialize_purchase_invoice_items(invoice_items),
				"meta": {
					"company": pi.company,
					"currency": pi.get("currency"),
					"posting_date": pi.get("posting_date"),
					"due_date": pi.get("due_date"),
					"remarks": pi.get("remarks"),
				},
			},
			"message": _("采购发票 {0} 详情获取成功。").format(pi.name),
		}
	except frappe.DoesNotExistError:
		raise
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("采购发票详情获取失败"))
		raise


def get_purchase_order_status_summary(
	supplier: str | None = None,
	company: str | None = None,
	limit: int = 20,
	date_from: str | None = None,
	date_to: str | None = None,
):
	limit = _normalize_limit(limit)
	resolved_date_from, resolved_date_to = _normalize_purchase_date_range(date_from, date_to)
	filters = {}
	if supplier:
		filters["supplier"] = supplier
	if company:
		filters["company"] = company
	if resolved_date_from and resolved_date_to:
		filters["transaction_date"] = ["between", [resolved_date_from, resolved_date_to]]
	elif resolved_date_from:
		filters["transaction_date"] = [">=", resolved_date_from]
	elif resolved_date_to:
		filters["transaction_date"] = ["<=", resolved_date_to]

	try:
		order_rows = frappe.get_all(
			"Purchase Order",
			filters=filters,
			fields=[
				"name",
				"supplier",
				"supplier_name",
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

		summaries = _build_purchase_order_summary_rows(order_rows)

		return {
			"status": "success",
			"data": summaries,
			"meta": {
				"filters": {
					"supplier": supplier,
					"company": company,
					"date_from": resolved_date_from,
					"date_to": resolved_date_to,
					"limit": limit,
				}
			},
			"message": _("采购订单状态摘要获取成功。"),
		}
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("采购订单状态摘要获取失败"))
		raise


def search_purchase_orders_v2(
	search_key: str | None = None,
	supplier: str | None = None,
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	status_filter: str | None = None,
	exclude_cancelled=None,
	sort_by: str | None = None,
	limit: int = 20,
	start: int = 0,
):
	limit = _normalize_limit(limit)
	start = _normalize_start(start)
	resolved_status_filter = _normalize_purchase_status_filter(status_filter)
	resolved_sort = _normalize_purchase_desk_sort(sort_by)
	resolved_search_key = _normalize_text(search_key)
	resolved_exclude_cancelled = _normalize_bool_flag(exclude_cancelled, default=False)
	resolved_date_from, resolved_date_to = _normalize_purchase_date_range(date_from, date_to)

	filters = {}
	if supplier:
		filters["supplier"] = supplier
	if company:
		filters["company"] = company
	if resolved_date_from and resolved_date_to:
		filters["transaction_date"] = ["between", [resolved_date_from, resolved_date_to]]
	elif resolved_date_from:
		filters["transaction_date"] = [">=", resolved_date_from]
	elif resolved_date_to:
		filters["transaction_date"] = ["<=", resolved_date_to]

	or_filters = None
	if resolved_search_key:
		like_pattern = f"%{resolved_search_key}%"
		or_filters = [
			["Purchase Order", "name", "like", like_pattern],
			["Purchase Order", "supplier", "like", like_pattern],
			["Purchase Order", "supplier_name", "like", like_pattern],
			["Purchase Order", "company", "like", like_pattern],
			["Purchase Order", "transaction_date", "like", like_pattern],
		]

	try:
		fields = [
			"name",
			"supplier",
			"supplier_name",
			"transaction_date",
			"company",
			"docstatus",
			"rounded_total",
			"grand_total",
			"modified",
		]
		order_by = "modified desc"
		if resolved_sort == "oldest":
			order_by = "transaction_date asc, modified asc"

		total_count = 0
		visible_count = 0
		unfinished_count = 0
		receiving_count = 0
		payment_count = 0
		completed_count = 0
		cancelled_count = 0
		paged_rows = []
		visible_cursor = 0
		page_target = start + limit
		ranked_rows = []
		sequence = 0
		chunk_start = 0
		batch_size = _purchase_search_batch_size(limit, start)

		while True:
			order_rows = frappe.get_all(
				"Purchase Order",
				filters=filters,
				or_filters=or_filters,
				fields=fields,
				order_by=order_by,
				limit_start=chunk_start,
				limit_page_length=batch_size,
			)
			if not order_rows:
				break

			summaries = _build_purchase_order_summary_rows(order_rows)
			for row in summaries:
				sequence += 1
				if _is_purchase_summary_cancelled(row):
					cancelled_count += 1

				if not _purchase_summary_matches_filter(row, "all", exclude_cancelled=resolved_exclude_cancelled):
					continue

				total_count += 1
				if _is_purchase_summary_unfinished(row):
					unfinished_count += 1
				if _is_purchase_summary_receiving_pending(row):
					receiving_count += 1
				if _is_purchase_summary_payment_pending(row):
					payment_count += 1
				if _is_purchase_summary_completed(row):
					completed_count += 1

				if not _purchase_summary_matches_filter(row, resolved_status_filter, exclude_cancelled=False):
					continue

				visible_count += 1
				if resolved_sort in {"latest", "oldest"}:
					if visible_cursor >= start and len(paged_rows) < limit:
						paged_rows.append(row)
					visible_cursor += 1
					continue

				rank = _purchase_summary_rank(row, resolved_sort)
				if rank is None:
					continue
				entry = (rank, -sequence, row)
				if len(ranked_rows) < page_target:
					heapq.heappush(ranked_rows, entry)
				elif entry > ranked_rows[0]:
					heapq.heapreplace(ranked_rows, entry)

			chunk_start += len(order_rows)
			if len(order_rows) < batch_size:
				break

		if resolved_sort in {"amount_asc", "amount_desc", "unfinished_first"}:
			paged_rows = _finalize_purchase_ranked_page(ranked_rows, resolved_sort, start, limit)

		return {
			"status": "success",
			"data": {
				"items": paged_rows,
				"summary": {
					"total_count": total_count,
					"visible_count": visible_count,
					"unfinished_count": unfinished_count,
					"receiving_count": receiving_count,
					"payment_count": payment_count,
					"completed_count": completed_count,
					"cancelled_count": cancelled_count,
				},
				"meta": {
					"filters": {
						"search_key": resolved_search_key or None,
						"supplier": supplier,
						"company": company,
						"date_from": resolved_date_from,
						"date_to": resolved_date_to,
						"status_filter": resolved_status_filter,
						"exclude_cancelled": resolved_exclude_cancelled,
						"sort_by": resolved_sort,
						"limit": limit,
						"start": start,
					}
				},
			},
			"message": _("采购订单工作台查询成功。"),
		}
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("采购订单工作台查询失败"))
		raise


def _get_recent_purchase_order_addresses(supplier: str, limit: int = 5):
	rows = frappe.get_all(
		"Purchase Order",
		filters={"supplier": supplier, "docstatus": 1},
		fields=["supplier_address", "address_display"],
		order_by="modified desc",
		limit_page_length=max(limit * 3, 10),
	)

	seen = set()
	result = []
	for row in rows:
		address_name = _extract_first_non_empty(getattr(row, "supplier_address", None))
		address_text = _extract_first_non_empty(getattr(row, "address_display", None))
		key = address_name or address_text
		if not key or key in seen:
			continue
		seen.add(key)
		result.append({"name": address_name, "address_display": address_text})
		if len(result) >= limit:
			break
	return result


def _build_supplier_payload(supplier_doc, *, include_recent_addresses: bool = False):
	default_contact = _serialize_contact_doc(
		_get_doc_if_exists("Contact", getattr(supplier_doc, "supplier_primary_contact", None))
	)
	default_address = _serialize_address_doc(
		_get_doc_if_exists("Address", getattr(supplier_doc, "supplier_primary_address", None))
	)
	data = {
		"name": supplier_doc.name,
		"display_name": getattr(supplier_doc, "supplier_name", None) or supplier_doc.name,
		"supplier_name": getattr(supplier_doc, "supplier_name", None) or supplier_doc.name,
		"supplier_type": getattr(supplier_doc, "supplier_type", None),
		"supplier_group": getattr(supplier_doc, "supplier_group", None),
		"default_currency": getattr(supplier_doc, "default_currency", None),
		"disabled": cint(getattr(supplier_doc, "disabled", 0)),
		"remarks": getattr(supplier_doc, "supplier_details", None) if _safe_doc_field("Supplier", "supplier_details") else None,
		"default_contact": default_contact,
		"default_address": default_address,
		"mobile_no": _extract_first_non_empty(getattr(supplier_doc, "mobile_no", None), (default_contact or {}).get("phone")),
		"email_id": _extract_first_non_empty(getattr(supplier_doc, "email_id", None), (default_contact or {}).get("email")),
		"modified": getattr(supplier_doc, "modified", None),
		"creation": getattr(supplier_doc, "creation", None),
	}
	if include_recent_addresses:
		data["recent_addresses"] = _get_recent_purchase_order_addresses(supplier_doc.name, limit=5)
	return data


def get_purchase_company_context(company: str | None = None):
	resolved_company = _normalize_text(company) or _extract_first_non_empty(frappe.defaults.get_user_default("company"))
	warehouse = _get_purchase_default_warehouse_for_company(resolved_company)

	return {
		"status": "success",
		"message": _("采购公司上下文获取成功。"),
		"data": {
			"company": resolved_company,
			"warehouse": warehouse,
		},
	}


def get_supplier_purchase_context(supplier: str, company: str | None = None):
	supplier = _normalize_text(supplier)
	if not supplier:
		frappe.throw(_("supplier 不能为空。"))

	supplier_doc = frappe.get_doc("Supplier", supplier)
	default_contact_name = _extract_first_non_empty(getattr(supplier_doc, "supplier_primary_contact", None))
	default_address_name = _extract_first_non_empty(getattr(supplier_doc, "supplier_primary_address", None))

	contact_names = [default_contact_name] if default_contact_name else []
	for name in _get_linked_parent_names(supplier, parenttype="Contact", limit=5):
		if name not in contact_names:
			contact_names.append(name)

	address_names = [default_address_name] if default_address_name else []
	for name in _get_linked_parent_names(supplier, parenttype="Address", limit=5):
		if name not in address_names:
			address_names.append(name)

	default_contact = _serialize_contact_doc(_get_doc_if_exists("Contact", contact_names[0] if contact_names else None))
	default_address = _serialize_address_doc(_get_doc_if_exists("Address", address_names[0] if address_names else None))
	resolved_company = _normalize_text(company) or _extract_first_non_empty(frappe.defaults.get_user_default("company"))
	warehouse = _get_purchase_default_warehouse_for_company(resolved_company)

	return {
		"status": "success",
		"message": _("供应商 {0} 采购上下文获取成功。").format(
			getattr(supplier_doc, "supplier_name", None) or supplier_doc.name
		),
		"data": {
			"supplier": {
				"name": supplier_doc.name,
				"display_name": getattr(supplier_doc, "supplier_name", None) or supplier_doc.name,
				"supplier_group": getattr(supplier_doc, "supplier_group", None),
				"supplier_type": getattr(supplier_doc, "supplier_type", None),
				"default_currency": getattr(supplier_doc, "default_currency", None),
			},
			"default_contact": default_contact,
			"default_address": default_address,
			"recent_addresses": _get_recent_purchase_order_addresses(supplier_doc.name, limit=5),
			"suggestions": {
				"company": resolved_company,
				"warehouse": warehouse,
				"currency": getattr(supplier_doc, "default_currency", None),
			},
		},
	}


def list_suppliers_v2(
	search_key: str | None = None,
	supplier_group: str | None = None,
	disabled: int | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 20,
	start: int = 0,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	limit = _normalize_limit(limit)
	start = _normalize_start(start)
	sort_by, sort_order = _normalize_sort(sort_by, sort_order)
	resolved_date_from, resolved_date_to = _normalize_master_date_range(date_from, date_to)

	filters = {}
	if _normalize_text(supplier_group):
		filters["supplier_group"] = _normalize_text(supplier_group)
	if _normalize_disabled(disabled) is not None and _safe_doc_field("Supplier", "disabled"):
		filters["disabled"] = _normalize_disabled(disabled)
	if resolved_date_from and resolved_date_to:
		filters["creation"] = ["between", [f"{resolved_date_from} 00:00:00", f"{resolved_date_to} 23:59:59"]]
	elif resolved_date_from:
		filters["creation"] = [">=", f"{resolved_date_from} 00:00:00"]
	elif resolved_date_to:
		filters["creation"] = ["<=", f"{resolved_date_to} 23:59:59"]

	search_key = _normalize_text(search_key)
	or_filters = None
	if search_key:
		or_filters = {
			"name": ["like", f"%{search_key}%"],
			"supplier_name": ["like", f"%{search_key}%"],
		}
		if _safe_doc_field("Supplier", "mobile_no"):
			or_filters["mobile_no"] = ["like", f"%{search_key}%"]
		if _safe_doc_field("Supplier", "email_id"):
			or_filters["email_id"] = ["like", f"%{search_key}%"]

	fields = ["name", "supplier_name", "supplier_type", "supplier_group", "modified", "creation"]
	for optional_field in [
		"default_currency",
		"disabled",
		"supplier_primary_contact",
		"supplier_primary_address",
		"mobile_no",
		"email_id",
		"supplier_details",
	]:
		if _safe_doc_field("Supplier", optional_field):
			fields.append(optional_field)

	rows = frappe.get_all(
		"Supplier",
		filters=filters,
		or_filters=or_filters,
		fields=fields,
		order_by=f"{sort_by} {sort_order}",
		start=start,
		limit_page_length=limit,
	)
	total_count = len(
		frappe.get_all(
			"Supplier",
			filters=filters,
			or_filters=or_filters,
			pluck="name",
			limit_page_length=0,
		)
	)

	return {
		"status": "success",
		"message": _("供应商列表获取成功。"),
		"data": [_build_supplier_payload(row) for row in rows],
		"meta": {
			"total": total_count,
			"start": start,
			"limit": limit,
			"has_more": start + len(rows) < total_count,
			"filters": {
				"search_key": search_key or None,
				"supplier_group": _normalize_text(supplier_group) or None,
				"disabled": _normalize_disabled(disabled),
				"date_from": resolved_date_from,
				"date_to": resolved_date_to,
				"sort_by": sort_by,
				"sort_order": sort_order,
			},
		},
	}


def get_supplier_detail_v2(supplier: str):
	supplier = _normalize_text(supplier)
	if not supplier:
		frappe.throw(_("supplier 不能为空。"))

	supplier_doc = frappe.get_doc("Supplier", supplier)
	return {
		"status": "success",
		"message": _("供应商 {0} 详情获取成功。").format(
			getattr(supplier_doc, "supplier_name", None) or supplier_doc.name
		),
		"data": _build_supplier_payload(supplier_doc, include_recent_addresses=True),
	}


def create_supplier_v2(supplier_name: str, **kwargs):
	supplier_name = _normalize_text(supplier_name)
	if not supplier_name:
		frappe.throw(_("供应商名称不能为空。"))

	request_id = kwargs.get("request_id")

	def _create_supplier():
		if _supplier_name_exists(supplier_name):
			frappe.throw(_("供应商 {0} 已存在。").format(supplier_name))

		supplier = _new_doc("Supplier")
		supplier.supplier_name = supplier_name
		supplier.supplier_type = _normalize_text(kwargs.get("supplier_type")) or "Company"
		supplier.supplier_group = _normalize_text(kwargs.get("supplier_group"))
		if _safe_doc_field("Supplier", "default_currency"):
			supplier.default_currency = _normalize_text(kwargs.get("default_currency"))
		if _safe_doc_field("Supplier", "disabled"):
			supplier.disabled = cint(kwargs.get("disabled", 0))
		if _safe_doc_field("Supplier", "mobile_no"):
			supplier.mobile_no = _normalize_text(kwargs.get("mobile_no"))
		if _safe_doc_field("Supplier", "email_id"):
			supplier.email_id = _normalize_text(kwargs.get("email_id"))
		if _safe_doc_field("Supplier", "supplier_details"):
			supplier.supplier_details = kwargs.get("remarks")
		if _normalize_text(kwargs.get("naming_series")) and supplier.meta.has_field("naming_series"):
			supplier.naming_series = _normalize_text(kwargs.get("naming_series"))
		supplier.insert()

		contact_doc = _upsert_supplier_primary_contact(supplier, _normalize_contact_payload(kwargs.get("default_contact"), kwargs))
		address_doc = _upsert_supplier_primary_address(supplier, _normalize_address_payload(kwargs.get("default_address"), kwargs))
		supplier.reload()
		if contact_doc and supplier.meta.has_field("supplier_primary_contact"):
			supplier.supplier_primary_contact = contact_doc.name
		if address_doc and supplier.meta.has_field("supplier_primary_address"):
			supplier.supplier_primary_address = address_doc.name
		supplier.save()
		supplier.reload()

		return {
			"status": "success",
			"message": _("供应商 {0} 已创建。").format(supplier.supplier_name or supplier.name),
			"data": _build_supplier_payload(supplier, include_recent_addresses=True),
			"meta": {
				"created_contact": getattr(contact_doc, "name", None),
				"created_address": getattr(address_doc, "name", None),
			},
		}

	return run_idempotent("create_supplier_v2", request_id, _create_supplier)


def update_supplier_v2(supplier: str, **kwargs):
	supplier = _normalize_text(supplier)
	if not supplier:
		frappe.throw(_("供应商不能为空。"))

	request_id = kwargs.get("request_id")

	def _update_supplier():
		supplier_doc = frappe.get_doc("Supplier", supplier)
		if kwargs.get("supplier_name") is not None:
			supplier_doc.supplier_name = _normalize_text(kwargs.get("supplier_name")) or supplier_doc.supplier_name
		if kwargs.get("supplier_type") is not None:
			supplier_doc.supplier_type = _normalize_text(kwargs.get("supplier_type")) or supplier_doc.supplier_type
		if kwargs.get("supplier_group") is not None:
			supplier_doc.supplier_group = _normalize_text(kwargs.get("supplier_group"))
		if kwargs.get("default_currency") is not None and _safe_doc_field("Supplier", "default_currency"):
			supplier_doc.default_currency = _normalize_text(kwargs.get("default_currency"))
		if kwargs.get("disabled") is not None and _safe_doc_field("Supplier", "disabled"):
			supplier_doc.disabled = cint(kwargs.get("disabled"))
		if kwargs.get("mobile_no") is not None and _safe_doc_field("Supplier", "mobile_no"):
			supplier_doc.mobile_no = _normalize_text(kwargs.get("mobile_no"))
		if kwargs.get("email_id") is not None and _safe_doc_field("Supplier", "email_id"):
			supplier_doc.email_id = _normalize_text(kwargs.get("email_id"))
		if kwargs.get("remarks") is not None and _safe_doc_field("Supplier", "supplier_details"):
			supplier_doc.supplier_details = kwargs.get("remarks")
		supplier_doc.save()
		supplier_doc.reload()

		contact_doc = _upsert_supplier_primary_contact(supplier_doc, _normalize_contact_payload(kwargs.get("default_contact"), kwargs))
		address_doc = _upsert_supplier_primary_address(supplier_doc, _normalize_address_payload(kwargs.get("default_address"), kwargs))
		supplier_doc.reload()
		if contact_doc and supplier_doc.meta.has_field("supplier_primary_contact"):
			supplier_doc.supplier_primary_contact = contact_doc.name
		if address_doc and supplier_doc.meta.has_field("supplier_primary_address"):
			supplier_doc.supplier_primary_address = address_doc.name
		supplier_doc.save()
		supplier_doc.reload()

		return {
			"status": "success",
			"message": _("供应商 {0} 已更新。").format(supplier_doc.supplier_name or supplier_doc.name),
			"data": _build_supplier_payload(supplier_doc, include_recent_addresses=True),
			"meta": {
				"updated_contact": getattr(contact_doc, "name", None),
				"updated_address": getattr(address_doc, "name", None),
			},
		}

	return run_idempotent("update_supplier_v2", request_id, _update_supplier)


def disable_supplier_v2(supplier: str, disabled: bool | int = True, **kwargs):
	supplier = _normalize_text(supplier)
	if not supplier:
		frappe.throw(_("供应商不能为空。"))

	request_id = kwargs.get("request_id")

	def _disable_supplier():
		supplier_doc = frappe.get_doc("Supplier", supplier)
		if _safe_doc_field("Supplier", "disabled"):
			supplier_doc.disabled = cint(disabled)
		supplier_doc.save()
		supplier_doc.reload()
		return {
			"status": "success",
			"message": _("供应商 {0} 已{1}。").format(
				supplier_doc.supplier_name or supplier_doc.name,
				_("停用") if cint(disabled) else _("启用"),
			),
			"data": _build_supplier_payload(supplier_doc, include_recent_addresses=True),
		}

	return run_idempotent("disable_supplier_v2", request_id, _disable_supplier)


def _get_purchase_order_doc_for_update(order_name: str, *, allow_cancelled: bool = False):
	if not order_name:
		frappe.throw(_("order_name 不能为空。"))

	po = frappe.get_doc("Purchase Order", order_name)
	if cint(po.docstatus) == 2 and not allow_cancelled:
		frappe.throw(_("已取消的采购订单不允许继续修改。"))
	return po


def _ensure_purchase_order_cancellable(po):
	if cint(po.docstatus) == 2:
		return
	if cint(po.docstatus) != 1:
		frappe.throw(_("只有已提交的采购订单才允许作废。"))

	receipt_names, invoice_names = _collect_purchase_order_reference_names(po.name)
	if receipt_names or invoice_names:
		frappe.throw(_("采购订单 {0} 已存在收货或开票记录，当前不允许作废。").format(po.name))


def _ensure_purchase_order_items_editable(po):
	if cint(po.docstatus) == 2:
		frappe.throw(_("已取消的采购订单不允许修改商品明细。"))

	receipt_names, invoice_names = _collect_purchase_order_reference_names(po.name)
	if receipt_names or invoice_names:
		frappe.throw(_("采购订单 {0} 已存在收货或开票记录，当前不允许修改商品明细。").format(po.name))

	receiving = _build_purchase_receiving_summary(list(po.get("items") or []))
	if receiving.get("received_qty", 0) > 0:
		frappe.throw(_("采购订单 {0} 已存在收货记录，当前不允许修改商品明细。").format(po.name))


def _prepare_purchase_order_for_item_replacement(po):
	if cint(po.docstatus) != 1:
		return po, po.name

	original_name = po.name
	po.cancel()
	amended = frappe.copy_doc(po)
	amended.amended_from = original_name
	amended.docstatus = 0
	amended.name = None
	return amended, original_name


def update_purchase_order_v2(order_name: str, **kwargs):
	request_id = kwargs.get("request_id")

	try:
		def _update_purchase_order_v2():
			po = _get_purchase_order_doc_for_update(order_name)
			if kwargs.get("transaction_date") is not None:
				po.transaction_date = kwargs.get("transaction_date") or None
			if kwargs.get("schedule_date") is not None:
				po.schedule_date = kwargs.get("schedule_date") or None
			if kwargs.get("remarks") is not None:
				po.remarks = kwargs.get("remarks") or None
			if kwargs.get("supplier_ref") is not None and po.meta.has_field("supplier_ref"):
				po.supplier_ref = kwargs.get("supplier_ref") or None

			if cint(po.docstatus) == 1:
				po.db_set("transaction_date", po.get("transaction_date"), update_modified=True)
				po.db_set("schedule_date", po.get("schedule_date"), update_modified=True)
				if po.meta.has_field("remarks"):
					po.db_set("remarks", po.get("remarks"), update_modified=True)
				if po.meta.has_field("supplier_ref"):
					po.db_set("supplier_ref", po.get("supplier_ref"), update_modified=True)
				po.reload()
			else:
				po.save()
				po.reload()

			return {
				"status": "success",
				"purchase_order": po.name,
				"message": _("采购订单 {0} 已按 v2 模型更新。").format(po.name),
				"meta": {
					"transaction_date": po.get("transaction_date"),
					"schedule_date": po.get("schedule_date"),
					"remarks": po.get("remarks"),
					"supplier_ref": po.get("supplier_ref"),
				},
			}

		return run_idempotent("update_purchase_order_v2", request_id, _update_purchase_order_v2)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("v2 采购订单更新失败"))
		raise


def update_purchase_order_items_v2(order_name: str, items, **kwargs):
	items = _coerce_json_value(items, [])
	request_id = kwargs.get("request_id")

	try:
		def _update_purchase_order_items_v2():
			po = _get_purchase_order_doc_for_update(order_name)
			_ensure_purchase_order_items_editable(po)
			target_po, source_order_name = _prepare_purchase_order_for_item_replacement(po)

			company = kwargs.get("company") or target_po.company
			schedule_date = kwargs.get("schedule_date") or target_po.get("schedule_date") or nowdate()
			default_warehouse = kwargs.get("default_warehouse")

			if not items:
				frappe.throw(_("无法将采购订单更新为空商品明细。"))

			normalized_items = [
				_build_purchase_order_item(item, schedule_date, default_warehouse, company)
				for item in items
			]

			target_po.set("items", [])
			for row in normalized_items:
				target_po.append("items", row)

			if kwargs.get("schedule_date") is not None:
				target_po.schedule_date = kwargs.get("schedule_date") or None

			_insert_and_submit(target_po)

			return {
				"status": "success",
				"purchase_order": target_po.name,
				"source_purchase_order": source_order_name,
				"message": _("采购订单 {0} 商品明细已按 v2 模型更新。").format(target_po.name),
				"items": _serialize_purchase_order_items(list(target_po.get("items") or [])),
				"meta": {
					"schedule_date": target_po.get("schedule_date"),
					"company": target_po.company,
				},
			}

		return run_idempotent("update_purchase_order_items_v2", request_id, _update_purchase_order_items_v2)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("v2 采购订单商品明细更新失败"))
		raise


def cancel_purchase_order_v2(order_name: str, **kwargs):
	request_id = kwargs.get("request_id")

	try:
		def _cancel_purchase_order_v2():
			po = _get_purchase_order_doc_for_update(order_name, allow_cancelled=True)
			receipt_names, invoice_names = _collect_purchase_order_reference_names(po.name)

			if cint(po.docstatus) == 2:
				detail = get_purchase_order_detail_v2(po.name)
				return {
					"status": "success",
					"purchase_order": po.name,
					"document_status": "cancelled",
					"message": _("采购订单 {0} 已处于作废状态。").format(po.name),
					"references": {
						"purchase_receipts": receipt_names,
						"purchase_invoices": invoice_names,
					},
					"detail": detail.get("data", {}),
				}

			_ensure_purchase_order_cancellable(po)
			po.cancel()
			detail = get_purchase_order_detail_v2(po.name)
			return {
				"status": "success",
				"purchase_order": po.name,
				"document_status": "cancelled",
				"message": _("采购订单 {0} 已按 v2 模型作废。").format(po.name),
				"references": {
					"purchase_receipts": receipt_names,
					"purchase_invoices": invoice_names,
				},
				"detail": detail.get("data", {}),
			}

		return run_idempotent("cancel_purchase_order_v2", request_id, _cancel_purchase_order_v2)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("v2 采购订单作废失败"))
		raise


def cancel_purchase_receipt_v2(receipt_name: str, **kwargs):
	request_id = kwargs.get("request_id")

	try:
		def _cancel_purchase_receipt_v2():
			pr = frappe.get_doc("Purchase Receipt", receipt_name)
			references = _build_purchase_receipt_references(receipt_name, list(pr.get("items") or []))

			if cint(pr.docstatus) == 2:
				detail = get_purchase_receipt_detail_v2(pr.name)
				return {
					"status": "success",
					"purchase_receipt": pr.name,
					"document_status": "cancelled",
					"references": references,
					"message": _("采购收货单 {0} 已处于作废状态。").format(pr.name),
					"detail": detail.get("data", {}),
				}

			if cint(pr.docstatus) != 1:
				frappe.throw(_("只有已提交的采购收货单才能作废。"))
			if references.get("purchase_invoices"):
				frappe.throw(_("当前采购收货单已关联采购发票，请先作废采购发票，再回退收货单。"))

			pr.cancel()
			detail = get_purchase_receipt_detail_v2(pr.name)
			return {
				"status": "success",
				"purchase_receipt": pr.name,
				"document_status": "cancelled",
				"references": references,
				"message": _("采购收货单 {0} 已作废。").format(pr.name),
				"detail": detail.get("data", {}),
			}

		return run_idempotent("cancel_purchase_receipt_v2", request_id, _cancel_purchase_receipt_v2)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("采购收货单作废失败"))
		raise


def cancel_purchase_invoice_v2(invoice_name: str, **kwargs):
	request_id = kwargs.get("request_id")

	try:
		def _cancel_purchase_invoice_v2():
			pi = frappe.get_doc("Purchase Invoice", invoice_name)
			detail_before = get_purchase_invoice_detail_v2(pi.name).get("data", {})

			if cint(pi.docstatus) == 2:
				return {
					"status": "success",
					"purchase_invoice": pi.name,
					"document_status": "cancelled",
					"references": detail_before.get("references", {}),
					"message": _("采购发票 {0} 已处于作废状态。").format(pi.name),
					"detail": detail_before,
				}

			if cint(pi.docstatus) != 1:
				frappe.throw(_("只有已提交的采购发票才能作废。"))

			pi.cancel()
			detail = get_purchase_invoice_detail_v2(pi.name)
			return {
				"status": "success",
				"purchase_invoice": pi.name,
				"document_status": "cancelled",
				"references": detail_before.get("references", {}),
				"message": _("采购发票 {0} 已作废。").format(pi.name),
				"detail": detail.get("data", {}),
			}

		return run_idempotent("cancel_purchase_invoice_v2", request_id, _cancel_purchase_invoice_v2)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("采购发票作废失败"))
		raise


def cancel_supplier_payment(payment_entry_name: str, **kwargs):
	result = cancel_payment_entry(payment_entry_name, **kwargs)
	return {
		"status": result.get("status"),
		"payment_entry": result.get("payment_entry"),
		"document_status": result.get("document_status"),
		"references": result.get("references", []),
		"message": (
			_("供应商付款单 {0} 已作废。").format(result.get("payment_entry"))
			if result.get("document_status") == "cancelled"
			else result.get("message")
		),
	}


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


def _apply_item_overrides(
	target_items,
	item_overrides: dict,
	*,
	detail_attr: str | None = None,
	detail_attrs: tuple[str, ...] | None = None,
	qty_transform=None,
):
	filtered_items = []

	for item in target_items:
		lookup_keys = []
		if detail_attr:
			lookup_keys.append(getattr(item, detail_attr, None))
		for attr in detail_attrs or ():
			lookup_keys.append(getattr(item, attr, None))

		override = next((item_overrides.get(key) for key in lookup_keys if key and item_overrides.get(key)), None)
		if not override:
			override = item_overrides.get(item.item_code)
		if not override:
			continue

		if override.get("qty") is not None:
			qty = flt(override["qty"])
			item.qty = qty_transform(qty) if qty_transform else qty
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


def _validate_purchase_rate_override_allowed(items, *, action_label: str):
	has_price_override = any(isinstance(row, dict) and row.get("price") is not None for row in (items or []))
	if not has_price_override:
		return

	if cint(frappe.db.get_single_value("Buying Settings", "maintain_same_rate")):
		frappe.throw(
			_(
				"{0}中检测到价格改写，但当前 ERPNext Buying Settings 启用了 maintain_same_rate。"
				"如需在收货或开票阶段直接改价，请先关闭该设置。"
			).format(action_label)
		)


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


def _build_purchase_order_item(
	item: dict,
	schedule_date: str,
	default_warehouse: str | None,
	company: str,
	uom_context_map: dict[str, dict] | None = None,
):
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
	qty_context = resolve_item_quantity_to_stock(
		item_code=item_code,
		qty=qty,
		uom=item.get("uom"),
		uom_context_map=uom_context_map,
	)

	row = {
		"item_code": item_code,
		"qty": qty,
		"warehouse": warehouse,
		"schedule_date": item.get("schedule_date") or schedule_date,
		"uom": qty_context["uom"],
		"stock_uom": qty_context["stock_uom"],
		"conversion_factor": qty_context["conversion_factor"],
		"stock_qty": qty_context["stock_qty"],
	}

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


def quick_create_purchase_order_v2(supplier: str, items, **kwargs):
	request_id = kwargs.get("request_id")
	include_detail = _include_detail_in_response(kwargs)

	try:
		def _quick_create_purchase_order_v2():
			result = create_purchase_order(supplier=supplier, items=items, **kwargs)
			order_name = result.get("purchase_order")
			receipt_name = None
			invoice_name = None
			payment_entry_name = None
			completed_steps = ["purchase_order"] if order_name else []

			if order_name and cint(kwargs.get("immediate_receive", 1)):
				receipt_result = receive_purchase_order(
					order_name,
					receipt_items=kwargs.get("receipt_items"),
					kwargs=kwargs,
				)
				receipt_name = receipt_result.get("purchase_receipt")
				if receipt_name:
					completed_steps.append("purchase_receipt")

			if cint(kwargs.get("immediate_invoice", 1)):
				if receipt_name:
					invoice_result = create_purchase_invoice_from_receipt(
						receipt_name,
						invoice_items=kwargs.get("invoice_items"),
						kwargs=kwargs,
					)
				elif order_name:
					invoice_result = create_purchase_invoice(
						order_name,
						invoice_items=kwargs.get("invoice_items"),
						kwargs=kwargs,
					)
				else:
					invoice_result = {}
				invoice_name = invoice_result.get("purchase_invoice")
				if invoice_name:
					completed_steps.append("purchase_invoice")

			if invoice_name and cint(kwargs.get("immediate_payment", 0)):
				paid_amount = kwargs.get("paid_amount")
				if paid_amount is None:
					detail_for_payment = get_purchase_invoice_detail_v2(invoice_name).get("data", {})
					paid_amount = flt(detail_for_payment.get("amounts", {}).get("outstanding_amount", 0) or 0)
				payment_result = record_supplier_payment(
					invoice_name,
					paid_amount=paid_amount,
					mode_of_payment=kwargs.get("mode_of_payment"),
					reference_no=kwargs.get("reference_no"),
					reference_date=kwargs.get("reference_date"),
					request_id=kwargs.get("request_id"),
				)
				payment_entry_name = payment_result.get("payment_entry")
				if payment_entry_name:
					completed_steps.append("payment_entry")

			detail = get_purchase_order_detail_v2(order_name).get("data", {}) if include_detail and order_name else None
			return {
				"status": "success",
				"purchase_order": order_name,
				"purchase_receipt": receipt_name,
				"purchase_invoice": invoice_name,
				"payment_entry": payment_entry_name,
				"completed_steps": completed_steps,
				"message": _("采购订单 {0} 已按快捷模式完成下单、收货、开票。").format(order_name),
				"detail": detail,
				"detail_included": bool(detail),
			}

		return run_idempotent("quick_create_purchase_order_v2", request_id, _quick_create_purchase_order_v2)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("快捷采购开单失败"))
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
				_validate_purchase_rate_override_allowed(receipt_items, action_label=_("采购收货"))
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
				_validate_purchase_rate_override_allowed(invoice_items, action_label=_("采购开票"))
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
				_validate_purchase_rate_override_allowed(invoice_items, action_label=_("基于收货单的采购开票"))
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


def _collect_submitted_supplier_payment_entry_summaries(invoice_names: list[str]):
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
	)
	parent_names = sorted({row.parent for row in reference_rows if getattr(row, "parent", None)})
	if not parent_names:
		return []

	payment_entry_rows = frappe.get_all(
		"Payment Entry",
		filters={"name": ["in", parent_names], "docstatus": 1},
		fields=["name", "modified"],
		order_by="modified desc",
	)
	active_parent_names = [row.name for row in payment_entry_rows if getattr(row, "name", None)]
	if not active_parent_names:
		return []

	all_reference_rows = frappe.get_all(
		"Payment Entry Reference",
		filters={"parent": ["in", active_parent_names]},
		fields=["parent", "reference_doctype", "reference_name", "allocated_amount"],
	)
	reference_rows_by_parent = {}
	for row in all_reference_rows:
		parent = getattr(row, "parent", None)
		if not parent:
			continue
		reference_rows_by_parent.setdefault(parent, []).append(row)

	return [
		{
			"payment_entry": row.name,
			"references": [
				{
					"reference_doctype": getattr(reference_row, "reference_doctype", None),
					"reference_name": getattr(reference_row, "reference_name", None),
					"allocated_amount": flt(getattr(reference_row, "allocated_amount", 0) or 0),
				}
				for reference_row in reference_rows_by_parent.get(row.name, [])
			],
		}
		for row in payment_entry_rows
	]


def _ensure_single_quick_purchase_reference(reference_names: list[str], *, label: str, order_name: str):
	if len(reference_names) > 1:
		frappe.throw(
			_("采购订单 {0} 当前存在多张{1}，暂不支持快捷回退，请改用分步回退流程。").format(
				order_name,
				label,
			)
		)


def quick_cancel_purchase_order_v2(order_name: str, rollback_payment: bool = True, **kwargs):
	request_id = kwargs.get("request_id")
	include_detail = _include_detail_in_response(kwargs)

	try:
		def _quick_cancel_purchase_order_v2():
			_get_purchase_order_doc_for_update(order_name)
			receipt_names, invoice_names = _collect_purchase_order_reference_names(order_name)
			_ensure_single_quick_purchase_reference(receipt_names, label=_("采购收货单"), order_name=order_name)
			_ensure_single_quick_purchase_reference(invoice_names, label=_("采购发票"), order_name=order_name)

			payment_entries = _collect_submitted_supplier_payment_entry_summaries(invoice_names)
			if len(payment_entries) > 1:
				frappe.throw(
					_("采购订单 {0} 当前存在多笔有效付款，暂不支持快捷回退，请改用分步回退流程。").format(
						order_name
					)
				)

			cancelled_payment_entries = []
			completed_steps = []
			for payment_entry in payment_entries:
				references = payment_entry.get("references") or []
				reference_names = {
					row.get("reference_name")
					for row in references
					if row.get("reference_doctype") == "Purchase Invoice" and row.get("reference_name")
				}
				if len(reference_names) > 1:
					frappe.throw(
						_("付款单 {0} 同时关联多张采购发票，暂不支持快捷回退，请改用分步回退流程。").format(
							payment_entry.get("payment_entry")
						)
					)
				if payment_entry.get("payment_entry") and not cint(rollback_payment):
					frappe.throw(_("采购订单 {0} 当前存在有效付款，快捷作废要求先回退付款。").format(order_name))
				payment_result = cancel_supplier_payment(payment_entry.get("payment_entry"))
				cancelled_payment_entries.append(payment_result.get("payment_entry"))
				completed_steps.append("payment_entry")

			cancelled_invoice = None
			if invoice_names:
				invoice_result = cancel_purchase_invoice_v2(invoice_names[0], **kwargs)
				cancelled_invoice = invoice_result.get("purchase_invoice")
				completed_steps.append("purchase_invoice")

			cancelled_receipt = None
			if receipt_names:
				receipt_result = cancel_purchase_receipt_v2(receipt_names[0], **kwargs)
				cancelled_receipt = receipt_result.get("purchase_receipt")
				completed_steps.append("purchase_receipt")

			detail = get_purchase_order_detail_v2(order_name).get("data", {}) if include_detail else None
			return {
				"status": "success",
				"purchase_order": order_name,
				"cancelled_payment_entries": cancelled_payment_entries,
				"cancelled_purchase_invoice": cancelled_invoice,
				"cancelled_purchase_receipt": cancelled_receipt,
				"completed_steps": completed_steps,
				"message": _("采购订单 {0} 已按快捷回退模式撤销下游单据，可返回订单继续修改。").format(order_name),
				"detail": detail,
				"detail_included": bool(detail),
			}

		return run_idempotent("quick_cancel_purchase_order_v2", request_id, _quick_cancel_purchase_order_v2)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("快捷采购回退失败"))
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
				detail_keys = {
					"Purchase Receipt": ("purchase_receipt_item", "pr_detail"),
					"Purchase Invoice": ("purchase_invoice_item", "pi_detail"),
				}[source_doctype]
				detail_attrs = {
					"Purchase Receipt": ("purchase_receipt_item", "pr_detail"),
					"Purchase Invoice": ("purchase_invoice_item", "pi_detail"),
				}[source_doctype]
				item_overrides = _build_item_override_map(return_items, detail_keys=detail_keys)
				return_doc.items = _apply_item_overrides(
					return_doc.items,
					item_overrides,
					detail_attrs=detail_attrs,
					qty_transform=lambda qty: -abs(qty),
				)
				_ensure_target_has_items(return_doc, _("未找到可退货的商品明细。"))

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
				business_type="purchase",
				is_partial_return=bool(return_items),
			)

		return run_idempotent("process_purchase_return", request_id, _process_purchase_return)
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("采购退货处理失败"))
		raise
