import frappe
from frappe import _
from frappe.utils import cint

from myapp.services.order_service import (
	_extract_first_non_empty,
	_get_doc_if_exists,
	_get_linked_parent_names,
	_get_recent_sales_order_shipping_addresses,
	_serialize_address_doc,
	_serialize_contact_doc,
)
from myapp.utils.idempotency import run_idempotent


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


def _new_doc(doctype: str):
	return frappe.new_doc(doctype)


def _customer_name_exists(customer_name: str):
	return bool(frappe.db.exists("Customer", {"customer_name": customer_name}))


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
		"address_type": _normalize_text(data.get("address_type") or kwargs.get("address_type")) or "Shipping",
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


def _ensure_customer_link(doc, customer_name: str):
	links = list(getattr(doc, "links", []) or [])
	for link in links:
		if getattr(link, "link_doctype", None) == "Customer" and getattr(link, "link_name", None) == customer_name:
			return
	doc.append("links", {"link_doctype": "Customer", "link_name": customer_name})


def _upsert_primary_contact(customer_doc, payload: dict):
	if not _has_meaningful_contact_payload(payload):
		return _get_doc_if_exists("Contact", getattr(customer_doc, "customer_primary_contact", None))

	contact = _get_doc_if_exists("Contact", payload.get("name") or getattr(customer_doc, "customer_primary_contact", None))
	is_new = not contact
	if is_new:
		contact = _new_doc("Contact")

	contact.first_name = payload.get("first_name") or payload.get("display_name") or customer_doc.customer_name or customer_doc.name
	contact.last_name = payload.get("last_name")
	contact.mobile_no = payload.get("phone")
	contact.phone = payload.get("phone")
	contact.email_id = payload.get("email")
	contact.is_primary_contact = 1
	_ensure_customer_link(contact, customer_doc.name)

	if is_new:
		contact.insert()
	else:
		contact.save()

	customer_doc.customer_primary_contact = contact.name
	return contact


def _upsert_primary_address(customer_doc, payload: dict):
	if not _has_meaningful_address_payload(payload):
		return _get_doc_if_exists("Address", getattr(customer_doc, "customer_primary_address", None))

	address = _get_doc_if_exists("Address", payload.get("name") or getattr(customer_doc, "customer_primary_address", None))
	is_new = not address
	if is_new:
		address = _new_doc("Address")

	address.address_title = payload.get("address_title") or customer_doc.customer_name or customer_doc.name
	address.address_type = payload.get("address_type") or "Shipping"
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
	address.is_shipping_address = 1
	_ensure_customer_link(address, customer_doc.name)

	if is_new:
		address.insert()
	else:
		address.save()

	customer_doc.customer_primary_address = address.name
	return address


def _build_customer_payload(customer_doc, *, include_recent_addresses: bool = False):
	default_contact = _serialize_contact_doc(_get_doc_if_exists("Contact", getattr(customer_doc, "customer_primary_contact", None)))
	default_address = _serialize_address_doc(_get_doc_if_exists("Address", getattr(customer_doc, "customer_primary_address", None)))
	data = {
		"name": customer_doc.name,
		"display_name": customer_doc.customer_name or customer_doc.name,
		"customer_name": customer_doc.customer_name or customer_doc.name,
		"customer_type": getattr(customer_doc, "customer_type", None),
		"customer_group": getattr(customer_doc, "customer_group", None),
		"territory": getattr(customer_doc, "territory", None),
		"default_currency": getattr(customer_doc, "default_currency", None),
		"default_price_list": getattr(customer_doc, "default_price_list", None),
		"disabled": cint(getattr(customer_doc, "disabled", 0)),
		"remarks": getattr(customer_doc, "customer_details", None),
		"default_contact": default_contact,
		"default_address": default_address,
		"mobile_no": _extract_first_non_empty(getattr(customer_doc, "mobile_no", None), (default_contact or {}).get("phone")),
		"email_id": _extract_first_non_empty(getattr(customer_doc, "email_id", None), (default_contact or {}).get("email")),
		"modified": getattr(customer_doc, "modified", None),
		"creation": getattr(customer_doc, "creation", None),
	}
	if include_recent_addresses:
		data["recent_addresses"] = _get_recent_sales_order_shipping_addresses(customer_doc.name, limit=5)
	return data


def _normalize_sort(sort_by: str | None, sort_order: str | None):
	allowed_sort_by = {"modified", "creation", "customer_name", "name"}
	allowed_sort_order = {"asc", "desc"}
	resolved_sort_by = _normalize_text(sort_by) or "modified"
	resolved_sort_order = (_normalize_text(sort_order) or "desc").lower()
	if resolved_sort_by not in allowed_sort_by:
		resolved_sort_by = "modified"
	if resolved_sort_order not in allowed_sort_order:
		resolved_sort_order = "desc"
	return resolved_sort_by, resolved_sort_order


def list_customers_v2(
	search_key: str | None = None,
	customer_group: str | None = None,
	disabled: int | None = None,
	limit: int = 20,
	start: int = 0,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	limit = _normalize_limit(limit)
	start = _normalize_start(start)
	sort_by, sort_order = _normalize_sort(sort_by, sort_order)

	filters = {}
	if _normalize_text(customer_group):
		filters["customer_group"] = _normalize_text(customer_group)
	if _normalize_disabled(disabled) is not None:
		filters["disabled"] = _normalize_disabled(disabled)

	search_key = _normalize_text(search_key)
	or_filters = None
	if search_key:
		or_filters = {
			"name": ["like", f"%{search_key}%"],
			"customer_name": ["like", f"%{search_key}%"],
			"mobile_no": ["like", f"%{search_key}%"],
			"email_id": ["like", f"%{search_key}%"],
		}

	fields = [
		"name",
		"customer_name",
		"customer_type",
		"customer_group",
		"territory",
		"default_currency",
		"default_price_list",
		"mobile_no",
		"email_id",
		"disabled",
		"modified",
		"creation",
		"customer_primary_contact",
		"customer_primary_address",
		"customer_details",
	]
	rows = frappe.get_all(
		"Customer",
		filters=filters,
		or_filters=or_filters,
		fields=fields,
		order_by=f"{sort_by} {sort_order}",
		start=start,
		limit_page_length=limit,
	)

	total_count = len(
		frappe.get_all(
			"Customer",
			filters=filters,
			or_filters=or_filters,
			pluck="name",
			limit_page_length=0,
		)
	)

	return {
		"status": "success",
		"message": _("客户列表获取成功。"),
		"data": [_build_customer_payload(row) for row in rows],
		"meta": {
			"total": total_count,
			"start": start,
			"limit": limit,
			"has_more": start + len(rows) < total_count,
		},
	}


def get_customer_detail_v2(customer: str):
	customer = _normalize_text(customer)
	if not customer:
		frappe.throw(_("客户不能为空。"))

	customer_doc = frappe.get_doc("Customer", customer)
	return {
		"status": "success",
		"message": _("客户 {0} 详情获取成功。").format(customer_doc.customer_name or customer_doc.name),
		"data": _build_customer_payload(customer_doc, include_recent_addresses=True),
	}


def create_customer_v2(customer_name: str, **kwargs):
	customer_name = _normalize_text(customer_name)
	if not customer_name:
		frappe.throw(_("客户名称不能为空。"))

	request_id = kwargs.get("request_id")

	def _create_customer():
		if _customer_name_exists(customer_name):
			frappe.throw(_("客户 {0} 已存在。").format(customer_name))

		customer = _new_doc("Customer")
		customer.customer_name = customer_name
		customer.customer_type = _normalize_text(kwargs.get("customer_type")) or "Company"
		customer.customer_group = _normalize_text(kwargs.get("customer_group"))
		customer.territory = _normalize_text(kwargs.get("territory"))
		customer.default_currency = _normalize_text(kwargs.get("default_currency"))
		customer.default_price_list = _normalize_text(kwargs.get("default_price_list"))
		customer.disabled = cint(kwargs.get("disabled", 0))
		customer.customer_details = kwargs.get("remarks")
		if _normalize_text(kwargs.get("naming_series")):
			customer.naming_series = _normalize_text(kwargs.get("naming_series"))
		customer.insert()

		contact_doc = _upsert_primary_contact(customer, _normalize_contact_payload(kwargs.get("default_contact"), kwargs))
		address_doc = _upsert_primary_address(customer, _normalize_address_payload(kwargs.get("default_address"), kwargs))
		customer.save()
		customer.reload()

		return {
			"status": "success",
			"message": _("客户 {0} 已创建。").format(customer.customer_name or customer.name),
			"data": _build_customer_payload(customer, include_recent_addresses=True),
			"meta": {
				"created_contact": getattr(contact_doc, "name", None),
				"created_address": getattr(address_doc, "name", None),
			},
		}

	return run_idempotent("create_customer_v2", request_id, _create_customer)


def update_customer_v2(customer: str, **kwargs):
	customer = _normalize_text(customer)
	if not customer:
		frappe.throw(_("客户不能为空。"))

	request_id = kwargs.get("request_id")

	def _update_customer():
		customer_doc = frappe.get_doc("Customer", customer)
		if kwargs.get("customer_name") is not None:
			customer_doc.customer_name = _normalize_text(kwargs.get("customer_name")) or customer_doc.customer_name
		if kwargs.get("customer_type") is not None:
			customer_doc.customer_type = _normalize_text(kwargs.get("customer_type")) or customer_doc.customer_type
		if kwargs.get("customer_group") is not None:
			customer_doc.customer_group = _normalize_text(kwargs.get("customer_group"))
		if kwargs.get("territory") is not None:
			customer_doc.territory = _normalize_text(kwargs.get("territory"))
		if kwargs.get("default_currency") is not None:
			customer_doc.default_currency = _normalize_text(kwargs.get("default_currency"))
		if kwargs.get("default_price_list") is not None:
			customer_doc.default_price_list = _normalize_text(kwargs.get("default_price_list"))
		if kwargs.get("disabled") is not None:
			customer_doc.disabled = cint(kwargs.get("disabled"))
		if kwargs.get("remarks") is not None:
			customer_doc.customer_details = kwargs.get("remarks")

		contact_payload = _normalize_contact_payload(kwargs.get("default_contact"), kwargs)
		address_payload = _normalize_address_payload(kwargs.get("default_address"), kwargs)
		contact_doc = _upsert_primary_contact(customer_doc, contact_payload)
		address_doc = _upsert_primary_address(customer_doc, address_payload)
		customer_doc.save()
		customer_doc.reload()

		return {
			"status": "success",
			"message": _("客户 {0} 已更新。").format(customer_doc.customer_name or customer_doc.name),
			"data": _build_customer_payload(customer_doc, include_recent_addresses=True),
			"meta": {
				"updated_contact": getattr(contact_doc, "name", None),
				"updated_address": getattr(address_doc, "name", None),
			},
		}

	return run_idempotent("update_customer_v2", request_id, _update_customer)


def disable_customer_v2(customer: str, disabled: bool | int = True, **kwargs):
	customer = _normalize_text(customer)
	if not customer:
		frappe.throw(_("客户不能为空。"))

	request_id = kwargs.get("request_id")

	def _disable_customer():
		customer_doc = frappe.get_doc("Customer", customer)
		customer_doc.disabled = cint(disabled)
		customer_doc.save()
		customer_doc.reload()
		return {
			"status": "success",
			"message": _("客户 {0} 已{1}。").format(
				customer_doc.customer_name or customer_doc.name,
				_("停用") if cint(disabled) else _("启用"),
			),
			"data": _build_customer_payload(customer_doc, include_recent_addresses=True),
		}

	return run_idempotent("disable_customer_v2", request_id, _disable_customer)
