import frappe
from frappe import _
from frappe.utils import cint

from myapp.utils.idempotency import run_idempotent


def _normalize_text(value: str | None):
	return (value or "").strip()


def _normalize_limit(limit: int | None):
	return max(1, min(int(limit or 20), 100))


def _normalize_start(start: int | None):
	return max(0, int(start or 0))


def _normalize_enabled(value):
	if value in (None, ""):
		return None
	return cint(value)


def _normalize_bool(value, *, default=0):
	if value in (None, ""):
		return cint(default)
	return cint(value)


def _normalize_sort(sort_by: str | None, sort_order: str | None):
	allowed_sort_by = {"modified", "creation", "uom_name", "name"}
	allowed_sort_order = {"asc", "desc"}
	resolved_sort_by = _normalize_text(sort_by) or "modified"
	resolved_sort_order = (_normalize_text(sort_order) or "desc").lower()
	if resolved_sort_by not in allowed_sort_by:
		resolved_sort_by = "modified"
	if resolved_sort_order not in allowed_sort_order:
		resolved_sort_order = "desc"
	return resolved_sort_by, resolved_sort_order


def _build_uom_payload(doc, *, usage_summary=None):
	data = {
		"name": doc.name,
		"uom_name": doc.uom_name or doc.name,
		"symbol": getattr(doc, "symbol", None),
		"description": getattr(doc, "description", None),
		"enabled": cint(getattr(doc, "enabled", 0)),
		"must_be_whole_number": cint(getattr(doc, "must_be_whole_number", 0)),
		"modified": getattr(doc, "modified", None),
		"creation": getattr(doc, "creation", None),
	}
	if usage_summary is not None:
		data["usage_summary"] = usage_summary
	return data


def _new_doc(doctype: str):
	return frappe.new_doc(doctype)


def _uom_exists(uom_name: str):
	return bool(frappe.db.exists("UOM", uom_name))


def _list_uom_link_fields():
	fields = []
	for doctype in ("DocField", "Custom Field"):
		rows = frappe.get_all(
			doctype,
			filters={"fieldtype": "Link", "options": "UOM"},
			fields=["dt as parent", "fieldname"] if doctype == "Custom Field" else ["parent", "fieldname"],
			limit_page_length=0,
		)
		for row in rows:
			fields.append((row.parent, row.fieldname))
	return sorted(set(fields))


def _collect_uom_references(uom_name: str, *, max_doctypes: int = 12, max_examples: int = 3):
	uom_name = _normalize_text(uom_name)
	if not uom_name:
		return {"total_references": 0, "doctypes": []}

	results = []
	total_references = 0

	for parent, fieldname in _list_uom_link_fields():
		try:
			meta = frappe.get_meta(parent)
		except Exception:
			continue

		if meta.issingle:
			try:
				value = frappe.db.get_single_value(parent, fieldname)
			except Exception:
				continue
			if value != uom_name:
				continue
			results.append(
				{
					"doctype": parent,
					"fieldname": fieldname,
					"count": 1,
					"examples": [parent],
				}
			)
			total_references += 1
			if len(results) >= max_doctypes:
				break
			continue

		try:
			count = frappe.db.count(parent, {fieldname: uom_name})
		except Exception:
			continue
		if not count:
			continue

		try:
			examples = frappe.get_all(
				parent,
				filters={fieldname: uom_name},
				pluck="name",
				limit_page_length=max_examples,
			)
		except Exception:
			examples = []

		results.append(
			{
				"doctype": parent,
				"fieldname": fieldname,
				"count": count,
				"examples": examples,
			}
		)
		total_references += count
		if len(results) >= max_doctypes:
			break

	return {"total_references": total_references, "doctypes": results}


def _format_reference_summary(usage_summary: dict):
	parts = []
	for row in usage_summary.get("doctypes", [])[:3]:
		label = _("{0}.{1}").format(row.get("doctype"), row.get("fieldname"))
		parts.append(_("{0}（{1} 条）").format(label, row.get("count") or 0))
	return "，".join(parts)


def _ensure_uom_can_be_deleted(uom_name: str):
	usage_summary = _collect_uom_references(uom_name)
	if usage_summary.get("total_references"):
		frappe.throw(
			_(
				"单位 {0} 已被系统引用，不能直接删除。请先停用，或解除这些引用后再删除：{1}"
			).format(uom_name, _format_reference_summary(usage_summary))
		)
	return usage_summary


def _ensure_whole_number_rule_editable(uom_name: str, old_value, new_value):
	if cint(old_value) == cint(new_value):
		return
	usage_summary = _collect_uom_references(uom_name)
	if usage_summary.get("total_references"):
		frappe.throw(
			_(
				"单位 {0} 已存在引用记录，不能直接修改“必须为整数”规则。请创建新单位，或先解除这些引用：{1}"
			).format(uom_name, _format_reference_summary(usage_summary))
		)


def list_uoms_v2(
	search_key: str | None = None,
	enabled: int | None = None,
	must_be_whole_number: int | None = None,
	limit: int = 20,
	start: int = 0,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	limit = _normalize_limit(limit)
	start = _normalize_start(start)
	sort_by, sort_order = _normalize_sort(sort_by, sort_order)

	filters = {}
	if _normalize_enabled(enabled) is not None:
		filters["enabled"] = _normalize_enabled(enabled)
	if _normalize_enabled(must_be_whole_number) is not None:
		filters["must_be_whole_number"] = _normalize_enabled(must_be_whole_number)

	search_key = _normalize_text(search_key)
	or_filters = None
	if search_key:
		or_filters = [
			["UOM", "name", "like", f"%{search_key}%"],
			["UOM", "uom_name", "like", f"%{search_key}%"],
			["UOM", "symbol", "like", f"%{search_key}%"],
			["UOM", "description", "like", f"%{search_key}%"],
		]

	rows = frappe.get_all(
		"UOM",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "uom_name", "symbol", "description", "enabled", "must_be_whole_number", "modified", "creation"],
		order_by=f"{sort_by} {sort_order}",
		start=start,
		limit_page_length=limit,
	)
	total = len(
		frappe.get_all(
			"UOM",
			filters=filters,
			or_filters=or_filters,
			pluck="name",
			limit_page_length=0,
		)
	)
	return {
		"status": "success",
		"message": _("单位列表获取成功。"),
		"data": [_build_uom_payload(row) for row in rows],
		"meta": {
			"total": total,
			"start": start,
			"limit": limit,
			"has_more": start + len(rows) < total,
		},
	}


def get_uom_detail_v2(uom: str):
	uom = _normalize_text(uom)
	if not uom:
		frappe.throw(_("单位不能为空。"))
	doc = frappe.get_doc("UOM", uom)
	return {
		"status": "success",
		"message": _("单位 {0} 详情获取成功。").format(doc.uom_name or doc.name),
		"data": _build_uom_payload(doc, usage_summary=_collect_uom_references(doc.name)),
	}


def create_uom_v2(uom_name: str, **kwargs):
	uom_name = _normalize_text(uom_name)
	if not uom_name:
		frappe.throw(_("单位名称不能为空。"))

	request_id = kwargs.get("request_id")

	def _create_uom():
		if _uom_exists(uom_name):
			frappe.throw(_("单位 {0} 已存在。").format(uom_name))

		doc = _new_doc("UOM")
		doc.uom_name = uom_name
		doc.enabled = _normalize_bool(kwargs.get("enabled"), default=1)
		doc.must_be_whole_number = _normalize_bool(kwargs.get("must_be_whole_number"), default=0)
		doc.symbol = _normalize_text(kwargs.get("symbol"))
		doc.description = kwargs.get("description")
		doc.insert()
		doc.reload()
		return {
			"status": "success",
			"message": _("单位 {0} 已创建。").format(doc.uom_name or doc.name),
			"data": _build_uom_payload(doc),
		}

	return run_idempotent("create_uom_v2", request_id, _create_uom)


def update_uom_v2(uom: str, **kwargs):
	uom = _normalize_text(uom)
	if not uom:
		frappe.throw(_("单位不能为空。"))

	request_id = kwargs.get("request_id")

	def _update_uom():
		doc = frappe.get_doc("UOM", uom)
		next_uom_name = _normalize_text(kwargs.get("uom_name"))
		if next_uom_name and next_uom_name != doc.name:
			frappe.throw(
				_("单位 {0} 已存在业务引用，不支持直接改名。若需新名称，请创建一个新单位。").format(doc.name)
			)

		if kwargs.get("must_be_whole_number") is not None:
			_ensure_whole_number_rule_editable(
				doc.name,
				getattr(doc, "must_be_whole_number", 0),
				kwargs.get("must_be_whole_number"),
			)
			doc.must_be_whole_number = _normalize_bool(kwargs.get("must_be_whole_number"))

		if kwargs.get("enabled") is not None:
			doc.enabled = _normalize_bool(kwargs.get("enabled"), default=getattr(doc, "enabled", 1))
		if kwargs.get("symbol") is not None:
			doc.symbol = _normalize_text(kwargs.get("symbol"))
		if kwargs.get("description") is not None:
			doc.description = kwargs.get("description")

		doc.save()
		doc.reload()
		return {
			"status": "success",
			"message": _("单位 {0} 已更新。").format(doc.uom_name or doc.name),
			"data": _build_uom_payload(doc, usage_summary=_collect_uom_references(doc.name)),
		}

	return run_idempotent("update_uom_v2", request_id, _update_uom)


def disable_uom_v2(uom: str, disabled: bool | int = True, **kwargs):
	uom = _normalize_text(uom)
	if not uom:
		frappe.throw(_("单位不能为空。"))

	request_id = kwargs.get("request_id")

	def _disable_uom():
		doc = frappe.get_doc("UOM", uom)
		doc.enabled = 0 if cint(disabled) else 1
		doc.save()
		doc.reload()
		return {
			"status": "success",
			"message": _("单位 {0} 已{1}。").format(
				doc.uom_name or doc.name,
				_("停用") if cint(disabled) else _("启用"),
			),
			"data": _build_uom_payload(doc),
		}

	return run_idempotent("disable_uom_v2", request_id, _disable_uom)


def delete_uom_v2(uom: str, **kwargs):
	uom = _normalize_text(uom)
	if not uom:
		frappe.throw(_("单位不能为空。"))

	request_id = kwargs.get("request_id")

	def _delete_uom():
		doc = frappe.get_doc("UOM", uom)
		_ensure_uom_can_be_deleted(doc.name)
		display_name = doc.uom_name or doc.name
		doc.delete()
		return {
			"status": "success",
			"message": _("单位 {0} 已删除。").format(display_name),
			"data": {"name": doc.name, "uom_name": display_name},
		}

	return run_idempotent("delete_uom_v2", request_id, _delete_uom)
