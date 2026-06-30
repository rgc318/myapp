import frappe
from frappe import _
from frappe.utils import cint, getdate

from myapp.utils.idempotency import run_idempotent
from myapp.utils.pagination import build_offset_pagination


def _normalize_text(value: str | None):
	return (value or "").strip()


def _normalize_limit(limit):
	return max(1, min(int(limit or 20), 100))


def _normalize_start(start):
	return max(0, int(start or 0))


def _normalize_disabled(value):
	if value in (None, "", "all"):
		return None
	return cint(value)


def _normalize_bool(value, *, default=0):
	if value in (None, ""):
		return cint(default)
	return cint(value)


def _normalize_creation_date_range(date_from: str | None = None, date_to: str | None = None):
	resolved_date_from = _normalize_text(date_from) or None
	resolved_date_to = _normalize_text(date_to) or None
	if not resolved_date_from and not resolved_date_to:
		return None, None
	if resolved_date_from and resolved_date_to and getdate(resolved_date_from) > getdate(resolved_date_to):
		frappe.throw(_("date_from 不能晚于 date_to。"))
	return resolved_date_from, resolved_date_to


def _normalize_sort(sort_by: str | None, sort_order: str | None):
	allowed_sort_by = {"modified", "creation", "name", "warehouse_name"}
	allowed_sort_order = {"asc", "desc"}
	resolved_sort_by = _normalize_text(sort_by) or "modified"
	resolved_sort_order = (_normalize_text(sort_order) or "desc").lower()
	if resolved_sort_by not in allowed_sort_by:
		resolved_sort_by = "modified"
	if resolved_sort_order not in allowed_sort_order:
		resolved_sort_order = "desc"
	return resolved_sort_by, resolved_sort_order


def _build_warehouse_payload(doc):
	return {
		"name": doc.name,
		"warehouse_name": getattr(doc, "warehouse_name", None) or doc.name,
		"company": getattr(doc, "company", None),
		"parent_warehouse": getattr(doc, "parent_warehouse", None),
		"is_group": cint(getattr(doc, "is_group", 0)),
		"disabled": cint(getattr(doc, "disabled", 0)),
		"address_line_1": getattr(doc, "address_line_1", None),
		"address_line_2": getattr(doc, "address_line_2", None),
		"city": getattr(doc, "city", None),
		"state": getattr(doc, "state", None),
		"pin": getattr(doc, "pin", None),
		"modified": getattr(doc, "modified", None),
		"creation": getattr(doc, "creation", None),
	}


def _ensure_company_exists(company: str):
	if not company:
		frappe.throw(_("公司不能为空。"))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("公司 {0} 不存在。").format(company))


def _ensure_parent_warehouse_valid(parent_warehouse: str | None, company: str):
	parent_warehouse = _normalize_text(parent_warehouse)
	if not parent_warehouse:
		return None
	parent = frappe.db.get_value("Warehouse", parent_warehouse, ["name", "company", "is_group"], as_dict=True)
	if not parent:
		frappe.throw(_("父仓库 {0} 不存在。").format(parent_warehouse))
	if parent.company and parent.company != company:
		frappe.throw(_("父仓库必须属于同一公司。"))
	if not cint(parent.is_group):
		frappe.throw(_("父仓库必须是分组仓库。"))
	return parent_warehouse


def list_warehouses_v2(
	search_key: str | None = None,
	company: str | None = None,
	disabled=None,
	is_group=None,
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
	resolved_date_from, resolved_date_to = _normalize_creation_date_range(date_from, date_to)
	search_key = _normalize_text(search_key)
	company = _normalize_text(company)

	filters = {}
	if company:
		filters["company"] = company
	resolved_disabled = _normalize_disabled(disabled)
	if resolved_disabled is not None:
		filters["disabled"] = resolved_disabled
	if is_group not in (None, "", "all"):
		filters["is_group"] = cint(is_group)
	if resolved_date_from and resolved_date_to:
		filters["creation"] = ["between", [f"{resolved_date_from} 00:00:00", f"{resolved_date_to} 23:59:59"]]
	elif resolved_date_from:
		filters["creation"] = [">=", f"{resolved_date_from} 00:00:00"]
	elif resolved_date_to:
		filters["creation"] = ["<=", f"{resolved_date_to} 23:59:59"]

	or_filters = None
	if search_key:
		or_filters = [
			["Warehouse", "name", "like", f"%{search_key}%"],
			["Warehouse", "warehouse_name", "like", f"%{search_key}%"],
			["Warehouse", "company", "like", f"%{search_key}%"],
			["Warehouse", "parent_warehouse", "like", f"%{search_key}%"],
		]

	fields = [
		"name",
		"warehouse_name",
		"company",
		"parent_warehouse",
		"is_group",
		"disabled",
		"address_line_1",
		"address_line_2",
		"city",
		"state",
		"pin",
		"modified",
		"creation",
	]
	rows = frappe.get_all(
		"Warehouse",
		filters=filters,
		or_filters=or_filters,
		fields=fields,
		order_by=f"{sort_by} {sort_order}",
		start=start,
		limit_page_length=limit,
	)
	total = len(
		frappe.get_all(
			"Warehouse",
			filters=filters,
			or_filters=or_filters,
			pluck="name",
			limit_page_length=0,
		)
	)
	pagination = build_offset_pagination(
		start=start,
		limit=limit,
		total_count=total,
		row_count=len(rows),
	)

	return {
		"status": "success",
		"message": _("仓库列表获取成功。"),
		"data": [_build_warehouse_payload(row) for row in rows],
		"meta": {
			"total": total,
			"total_count": total,
			"start": start,
			"limit": limit,
			"has_more": pagination["has_more"],
			"pagination": pagination,
			"filters": {
				"search_key": search_key or None,
				"company": company or None,
				"disabled": resolved_disabled,
				"is_group": cint(is_group) if is_group not in (None, "", "all") else None,
				"date_from": resolved_date_from,
				"date_to": resolved_date_to,
				"sort_by": sort_by,
				"sort_order": sort_order,
			},
		},
		"pagination": pagination,
	}


def get_warehouse_detail_v2(warehouse: str):
	warehouse = _normalize_text(warehouse)
	if not warehouse:
		frappe.throw(_("仓库不能为空。"))
	doc = frappe.get_doc("Warehouse", warehouse)
	return {
		"status": "success",
		"message": _("仓库 {0} 详情获取成功。").format(doc.name),
		"data": _build_warehouse_payload(doc),
	}


def create_warehouse_v2(warehouse_name: str, company: str, **kwargs):
	warehouse_name = _normalize_text(warehouse_name)
	company = _normalize_text(company)
	if not warehouse_name:
		frappe.throw(_("仓库名称不能为空。"))
	_ensure_company_exists(company)

	request_id = kwargs.get("request_id")

	def _create_warehouse():
		parent_warehouse = _ensure_parent_warehouse_valid(kwargs.get("parent_warehouse"), company)
		doc = frappe.new_doc("Warehouse")
		doc.warehouse_name = warehouse_name
		doc.company = company
		doc.parent_warehouse = parent_warehouse
		doc.is_group = _normalize_bool(kwargs.get("is_group"), default=0)
		doc.disabled = _normalize_bool(kwargs.get("disabled"), default=0)
		for fieldname in ("address_line_1", "address_line_2", "city", "state", "pin"):
			if kwargs.get(fieldname) is not None:
				setattr(doc, fieldname, _normalize_text(kwargs.get(fieldname)))
		doc.insert()
		doc.reload()
		return {
			"status": "success",
			"message": _("仓库 {0} 已创建。").format(doc.name),
			"data": _build_warehouse_payload(doc),
		}

	return run_idempotent("create_warehouse_v2", request_id, _create_warehouse)


def update_warehouse_v2(warehouse: str, **kwargs):
	warehouse = _normalize_text(warehouse)
	if not warehouse:
		frappe.throw(_("仓库不能为空。"))

	request_id = kwargs.get("request_id")

	def _update_warehouse():
		doc = frappe.get_doc("Warehouse", warehouse)
		company = _normalize_text(kwargs.get("company")) or doc.company
		if kwargs.get("company") is not None:
			_ensure_company_exists(company)
			doc.company = company
		if kwargs.get("parent_warehouse") is not None:
			doc.parent_warehouse = _ensure_parent_warehouse_valid(kwargs.get("parent_warehouse"), company)
		if kwargs.get("warehouse_name") is not None:
			resolved_name = _normalize_text(kwargs.get("warehouse_name"))
			if not resolved_name:
				frappe.throw(_("仓库名称不能为空。"))
			doc.warehouse_name = resolved_name
		if kwargs.get("is_group") is not None:
			doc.is_group = _normalize_bool(kwargs.get("is_group"), default=getattr(doc, "is_group", 0))
		if kwargs.get("disabled") is not None:
			doc.disabled = _normalize_bool(kwargs.get("disabled"), default=getattr(doc, "disabled", 0))
		for fieldname in ("address_line_1", "address_line_2", "city", "state", "pin"):
			if kwargs.get(fieldname) is not None:
				setattr(doc, fieldname, _normalize_text(kwargs.get(fieldname)))
		doc.save()
		doc.reload()
		return {
			"status": "success",
			"message": _("仓库 {0} 已更新。").format(doc.name),
			"data": _build_warehouse_payload(doc),
		}

	return run_idempotent("update_warehouse_v2", request_id, _update_warehouse)


def disable_warehouse_v2(warehouse: str, disabled: bool | int = True, **kwargs):
	warehouse = _normalize_text(warehouse)
	if not warehouse:
		frappe.throw(_("仓库不能为空。"))

	request_id = kwargs.get("request_id")

	def _disable_warehouse():
		doc = frappe.get_doc("Warehouse", warehouse)
		doc.disabled = 1 if cint(disabled) else 0
		doc.save()
		doc.reload()
		return {
			"status": "success",
			"message": _("仓库 {0} 已{1}。").format(doc.name, _("停用") if cint(disabled) else _("启用")),
			"data": _build_warehouse_payload(doc),
		}

	return run_idempotent("disable_warehouse_v2", request_id, _disable_warehouse)
