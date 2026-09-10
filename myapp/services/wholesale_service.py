from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import add_days, cint, flt, getdate, nowdate

from myapp.services.media_service import (
	bind_uploaded_item_image,
	cleanup_replaced_item_image,
	cleanup_temporary_item_image,
)
from myapp.services.data_permission_service import (
	current_user,
	ensure_warehouse_access,
	get_permitted_warehouse_names,
	has_document_permission,
	require_document_permission,
	require_doctype_permission,
)
from myapp.services.product_correction_service import (
	list_product_corrections_for_history,
	record_product_correction,
)
from myapp.utils.idempotency import get_current_request_id, run_idempotent
from myapp.utils.concurrency import OptimisticLockConflictError
from myapp.utils.pagination import build_offset_pagination
from myapp.utils.uom_display import build_uom_display_map, sort_uom_rows
from myapp.utils.uom import resolve_item_quantity_to_stock
from myapp.utils.standard_uoms import BUSINESS_SELECTABLE_UOM_FIELD
from myapp.utils.warehouse import validate_transaction_warehouse

ITEM_NICKNAME_FIELD = "custom_nickname"
ITEM_SPECIFICATION_FIELD = "custom_specification"
WHOLESALE_DEFAULT_UOM_FIELD = "custom_wholesale_default_uom"
RETAIL_DEFAULT_UOM_FIELD = "custom_retail_default_uom"
DEFAULT_SELLING_PRICE_LISTS = ("Standard Selling", "Wholesale", "Retail")
DEFAULT_BUYING_PRICE_LISTS = ("Standard Buying",)
PRODUCT_UOM_MIGRATION_MANAGER_ROLE = "System Manager"
PRODUCT_UOM_MIGRATION_COMMITTED_BIN_FIELDS = (
	"reserved_qty",
	"reserved_stock",
	"reserved_qty_for_production",
	"reserved_qty_for_sub_contract",
	"reserved_qty_for_production_plan",
	"ordered_qty",
	"planned_qty",
	"indented_qty",
)
PRODUCT_HISTORY_FIELD_LABELS = {
	"item_name": _("商品名称"),
	"item_group": _("商品分类"),
	"brand": _("品牌"),
	"description": _("描述"),
	"image": _("商品图片"),
	"disabled": _("停用状态"),
	"stock_uom": _("库存基准单位"),
	"valuation_rate": _("库存估值成本"),
	"barcodes": _("条码"),
	"uoms": _("单位换算"),
	WHOLESALE_DEFAULT_UOM_FIELD: _("批发默认单位"),
	RETAIL_DEFAULT_UOM_FIELD: _("零售默认单位"),
	"price_list_rate": _("价格金额"),
	"price_list": _("价格表"),
	"currency": _("币种"),
	"uom": _("计价单位"),
	"valid_from": _("生效日期"),
	"valid_upto": _("失效日期"),
}


def _normalize_text(value: str | None):
	return (value or "").strip()


def _require_current_document_version(doc, expected_modified, *, message: str):
	expected = _normalize_text(expected_modified)
	if not expected:
		return
	current = str(getattr(doc, "modified", None) or "")
	if expected == current:
		return
	raise OptimisticLockConflictError(
		message,
		doctype=doc.doctype,
		name=doc.name,
		expected_modified=expected,
		current_modified=current,
	)


def _normalize_currency(value: str | None):
	if _normalize_text(value):
		return _normalize_text(value)
	try:
		return _normalize_text(frappe.defaults.get_user_default("currency")) or None
	except Exception:
		return None


def _normalize_limit(limit: int | None):
	return max(1, min(int(limit or 20), 100))


def _normalize_start(start: int | None):
	return max(0, int(start or 0))


def _normalize_master_date_range(date_from: str | None = None, date_to: str | None = None):
	resolved_date_from = _normalize_text(date_from) or None
	resolved_date_to = _normalize_text(date_to) or None
	if not resolved_date_from and not resolved_date_to:
		return None, None
	if resolved_date_from and resolved_date_to and getdate(resolved_date_from) > getdate(resolved_date_to):
		frappe.throw(_("date_from 不能晚于 date_to。"))
	return resolved_date_from, resolved_date_to


def _normalize_search_fields(search_fields):
	default_fields = ["barcode", "item_code", "item_name"]

	if search_fields in (None, "", []):
		return default_fields

	parsed = search_fields
	if isinstance(search_fields, str):
		try:
			parsed = frappe.parse_json(search_fields)
		except Exception:
			parsed = [part.strip() for part in search_fields.split(",") if part.strip()]

	allowed = {
		"barcode": "barcode",
		"item_code": "item_code",
		"code": "item_code",
		"item_name": "item_name",
		"name": "item_name",
		"nickname": "nickname",
		"alias": "nickname",
		"specification": "specification",
		"spec": "specification",
	}

	normalized = []
	for field in parsed or []:
		key = allowed.get(_normalize_text(str(field)).lower())
		if key and key not in normalized:
			normalized.append(key)

	return normalized or default_fields


def _normalize_price_list_names(value, *, defaults: tuple[str, ...]):
	if value in (None, "", []):
		return list(defaults)

	parsed = value
	if isinstance(value, str):
		try:
			parsed = frappe.parse_json(value)
		except Exception:
			parsed = [part.strip() for part in value.split(",") if part.strip()]

	names = []
	for row in parsed or []:
		name = _normalize_text(str(row))
		if name and name not in names:
			names.append(name)

	return names or list(defaults)


def _normalize_item_context(value: str | None):
	context = _normalize_text(value).lower()
	if not context:
		return "sales"
	if context not in {"any", "inventory", "purchase", "sales"}:
		frappe.throw(_("item_context 只支持 sales、purchase、inventory 或 any。"))
	return context


def _get_item_filters(item_context: str | None = "sales", disabled: int | None = 0):
	filters = {}
	if disabled is not None:
		filters["disabled"] = cint(disabled)

	context = _normalize_item_context(item_context)
	if context == "sales":
		filters["is_sales_item"] = 1
	elif context == "purchase":
		filters["is_purchase_item"] = 1
	elif context == "inventory":
		filters["is_stock_item"] = 1
	return filters


def _has_item_field(fieldname: str):
	try:
		return bool(frappe.get_meta("Item").has_field(fieldname))
	except Exception:
		return False


def _get_item_nickname_field():
	return ITEM_NICKNAME_FIELD if _has_item_field(ITEM_NICKNAME_FIELD) else None


def _get_item_specification_field():
	return ITEM_SPECIFICATION_FIELD if _has_item_field(ITEM_SPECIFICATION_FIELD) else None


def _get_item_mode_default_uom_field(mode: str):
	mode_key = _normalize_text(mode).lower()
	mapping = {
		"wholesale": WHOLESALE_DEFAULT_UOM_FIELD,
		"retail": RETAIL_DEFAULT_UOM_FIELD,
	}
	fieldname = mapping.get(mode_key)
	if not fieldname:
		return None
	return fieldname if _has_item_field(fieldname) else None


def _extract_mode_default_uoms(item):
	result = {
		"wholesale_default_uom": None,
		"retail_default_uom": None,
	}
	fallback_fields = {
		"wholesale": WHOLESALE_DEFAULT_UOM_FIELD,
		"retail": RETAIL_DEFAULT_UOM_FIELD,
	}
	for mode in ("wholesale", "retail"):
		fieldname = _get_item_mode_default_uom_field(mode) or fallback_fields[mode]
		raw_value = getattr(item, fieldname, None)
		result[f"{mode}_default_uom"] = _normalize_text(raw_value) if isinstance(raw_value, str) else None
	return result


def _build_sales_profiles(item):
	default_uoms = _extract_mode_default_uoms(item)
	return [
		{
			"mode_code": "wholesale",
			"price_list": "Wholesale",
			"default_uom": default_uoms["wholesale_default_uom"],
		},
		{
			"mode_code": "retail",
			"price_list": "Retail",
			"default_uom": default_uoms["retail_default_uom"],
		},
	]


def _collect_item_uom_names(*, item=None, all_uoms=None):
	names = []
	for value in (
		getattr(item, "stock_uom", None) if item is not None else None,
		(_extract_mode_default_uoms(item).get("wholesale_default_uom") if item is not None else None),
		(_extract_mode_default_uoms(item).get("retail_default_uom") if item is not None else None),
	):
		name = _normalize_text(value) if isinstance(value, str) else None
		if name and name not in names:
			names.append(name)

	for row in all_uoms or []:
		name = _normalize_text(getattr(row, "uom", None) if hasattr(row, "uom") else row.get("uom") if isinstance(row, dict) else None)
		if name and name not in names:
			names.append(name)

	return names


def _build_sales_profiles_with_display(item, uom_display_map: dict[str, str]):
	profiles = _build_sales_profiles(item)
	for row in profiles:
		default_uom = _normalize_text(row.get("default_uom"))
		row["default_uom_display"] = uom_display_map.get(default_uom) if default_uom else None
	return profiles


def _decorate_uom_rows_with_display(rows, uom_display_map: dict[str, str]):
	decorated = []
	for row in rows or []:
		uom = _normalize_text(row.get("uom") if isinstance(row, dict) else getattr(row, "uom", None))
		next_row = dict(row)
		next_row["uom_display"] = uom_display_map.get(uom) if uom else None
		decorated.append(next_row)
	return sort_uom_rows(decorated)


def _search_item_codes(
	search_key: str,
	*,
	search_fields: list[str],
	limit: int,
	item_context: str | None = "sales",
	disabled: int | None = 0,
	item_group: str | None = None,
	brand: str | None = None,
):
	item_filters = _get_item_filters(item_context=item_context, disabled=disabled)
	if item_group:
		item_filters["item_group"] = item_group
	if brand:
		item_filters["brand"] = brand
	matched_codes = []
	seen = set()

	def _extend(codes):
		for code in codes:
			if code and code not in seen:
				seen.add(code)
				matched_codes.append(code)
				if len(matched_codes) >= limit:
					return True
		return False

	if "barcode" in search_fields:
		barcode_parent = frappe.db.get_value("Item Barcode", {"barcode": search_key}, "parent")
		if barcode_parent and _extend([barcode_parent]):
			return matched_codes

	if "item_code" in search_fields:
		codes = frappe.get_list(
			"Item",
			filters={**item_filters, "name": ["like", f"%{search_key}%"]},
			pluck="name",
			limit_page_length=limit,
			order_by="modified desc",
		)
		if _extend(codes):
			return matched_codes

	if "item_name" in search_fields:
		codes = frappe.get_list(
			"Item",
			filters={**item_filters, "item_name": ["like", f"%{search_key}%"]},
			pluck="name",
			limit_page_length=limit,
			order_by="modified desc",
		)
		if _extend(codes):
			return matched_codes

	if "nickname" in search_fields:
		nickname_field = _get_item_nickname_field()
		or_filters = {
			"description": ["like", f"%{search_key}%"],
			"item_name": ["like", f"%{search_key}%"],
		}
		if nickname_field:
			or_filters[nickname_field] = ["like", f"%{search_key}%"]
		codes = frappe.get_list(
			"Item",
			filters=item_filters,
			or_filters=or_filters,
			pluck="name",
			limit_page_length=limit,
			order_by="modified desc",
		)
		_extend(codes)

	if "specification" in search_fields:
		specification_field = _get_item_specification_field()
		if specification_field:
			codes = frappe.get_list(
				"Item",
				filters={**item_filters, specification_field: ["like", f"%{search_key}%"]},
				pluck="name",
				limit_page_length=limit,
				order_by="modified desc",
			)
			_extend(codes)

	return matched_codes[:limit]


def _list_item_codes_by_filters(
	*,
	limit: int,
	item_context: str | None = "sales",
	disabled: int | None = 0,
	item_group: str | None = None,
	brand: str | None = None,
):
	item_filters = _get_item_filters(item_context=item_context, disabled=disabled)
	if item_group:
		item_filters["item_group"] = item_group
	if brand:
		item_filters["brand"] = brand

	return frappe.get_list(
		"Item",
		filters=item_filters,
		pluck="name",
		limit_page_length=limit,
		order_by="modified desc",
	)


def _get_item_data_map(
	item_codes: list[str],
	*,
	item_context: str | None = "sales",
	disabled: int | None = 0,
	item_group: str | None = None,
	brand: str | None = None,
):
	if not item_codes:
		return {}

	fields = [
		"name",
		"item_name",
		"item_group",
		"brand",
		"stock_uom",
		"image",
		"description",
		"creation",
		"modified",
		"disabled",
		"is_sales_item",
		"is_purchase_item",
	]
	nickname_field = _get_item_nickname_field()
	if nickname_field:
		fields.append(nickname_field)
	specification_field = _get_item_specification_field()
	if specification_field:
		fields.append(specification_field)
	for fieldname in (WHOLESALE_DEFAULT_UOM_FIELD, RETAIL_DEFAULT_UOM_FIELD):
		if _has_item_field(fieldname):
			fields.append(fieldname)

	item_filters = _get_item_filters(
		item_context=item_context,
		disabled=disabled,
	)
	if item_group:
		item_filters["item_group"] = item_group
	if brand:
		item_filters["brand"] = brand

	return {
		d.name: d
		for d in frappe.get_list(
			"Item",
			filters={
				**item_filters,
				"name": ["in", item_codes],
			},
			fields=fields,
		)
	}


def _get_item_rows(
	*,
	search_key: str | None = None,
	item_group: str | None = None,
	brand: str | None = None,
	disabled: int | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 20,
	start: int = 0,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	fields = [
		"name",
		"item_name",
		"item_group",
		"brand",
		"stock_uom",
		"image",
		"description",
		"creation",
		"modified",
		"disabled",
		"is_sales_item",
		"is_purchase_item",
		"valuation_rate",
		"standard_rate",
	]
	nickname_field = _get_item_nickname_field()
	if nickname_field:
		fields.append(nickname_field)
	specification_field = _get_item_specification_field()
	if specification_field:
		fields.append(specification_field)
	for fieldname in (WHOLESALE_DEFAULT_UOM_FIELD, RETAIL_DEFAULT_UOM_FIELD):
		if _has_item_field(fieldname):
			fields.append(fieldname)

	filters = {}
	if item_group:
		filters["item_group"] = item_group
	if brand:
		filters["brand"] = brand
	if disabled is not None:
		filters["disabled"] = cint(disabled)
	resolved_date_from, resolved_date_to = _normalize_master_date_range(date_from, date_to)
	if resolved_date_from and resolved_date_to:
		filters["creation"] = ["between", [f"{resolved_date_from} 00:00:00", f"{resolved_date_to} 23:59:59"]]
	elif resolved_date_from:
		filters["creation"] = [">=", f"{resolved_date_from} 00:00:00"]
	elif resolved_date_to:
		filters["creation"] = ["<=", f"{resolved_date_to} 23:59:59"]

	or_filters = None
	barcode_codes = []
	search_key = _normalize_text(search_key)
	if search_key:
		barcode_parent = frappe.db.get_value("Item Barcode", {"barcode": search_key}, "parent")
		if barcode_parent:
			barcode_codes = [barcode_parent]
		or_filters = {
			"name": ["like", f"%{search_key}%"],
			"item_name": ["like", f"%{search_key}%"],
			"description": ["like", f"%{search_key}%"],
		}
		if nickname_field:
			or_filters[nickname_field] = ["like", f"%{search_key}%"]
		if specification_field:
			or_filters[specification_field] = ["like", f"%{search_key}%"]

	rows = frappe.get_list(
		"Item",
		filters=filters,
		or_filters=or_filters,
		fields=fields,
		start=start,
		limit_page_length=limit,
		order_by=f"{sort_by} {sort_order}",
	)

	if barcode_codes:
		existing = {row.name for row in rows}
		missing = [code for code in barcode_codes if code not in existing]
		if missing:
			rows = (
				frappe.get_list("Item", filters={"name": ["in", missing]}, fields=fields, limit_page_length=len(missing))
				+ rows
			)[:limit]

	return rows


def _count_item_rows(
	*,
	search_key: str | None = None,
	item_group: str | None = None,
	brand: str | None = None,
	disabled: int | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
):
	filters = {}
	if item_group:
		filters["item_group"] = item_group
	if brand:
		filters["brand"] = brand
	if disabled is not None:
		filters["disabled"] = cint(disabled)
	resolved_date_from, resolved_date_to = _normalize_master_date_range(date_from, date_to)
	if resolved_date_from and resolved_date_to:
		filters["creation"] = ["between", [f"{resolved_date_from} 00:00:00", f"{resolved_date_to} 23:59:59"]]
	elif resolved_date_from:
		filters["creation"] = [">=", f"{resolved_date_from} 00:00:00"]
	elif resolved_date_to:
		filters["creation"] = ["<=", f"{resolved_date_to} 23:59:59"]

	or_filters = None
	search_key = _normalize_text(search_key)
	if search_key:
		nickname_field = _get_item_nickname_field()
		specification_field = _get_item_specification_field()
		or_filters = {
			"name": ["like", f"%{search_key}%"],
			"item_name": ["like", f"%{search_key}%"],
			"description": ["like", f"%{search_key}%"],
		}
		if nickname_field:
			or_filters[nickname_field] = ["like", f"%{search_key}%"]
		if specification_field:
			or_filters[specification_field] = ["like", f"%{search_key}%"]

	total = len(
		frappe.get_list(
			"Item",
			filters=filters,
			or_filters=or_filters,
			pluck="name",
			limit_page_length=0,
		)
	)
	if search_key and frappe.db.get_value("Item Barcode", {"barcode": search_key}, "parent"):
		return max(total, 1)
	return total


def _get_price_map(item_codes: list[str], *, price_list: str, currency: str | None):
	if not item_codes:
		return {}
	permitted_price_lists = _get_permitted_price_list_names([price_list])
	if price_list not in permitted_price_lists:
		return {}

	price_filters = {"item_code": ["in", item_codes], "price_list": price_list}
	if currency:
		price_filters["currency"] = currency
	# ERPNext transaction users consume Item Price through pricing services even though the
	# raw Item Price DocType is not readable by standard Sales/Purchase roles. The requested
	# Price List is permission-filtered above, and item_codes already came from Item.get_list.
	price_data = frappe.get_all(
		"Item Price",
		filters=price_filters,
		fields=["item_code", "price_list", "price_list_rate", "uom", "modified"],
		order_by="modified desc",
	)
	item_fields = ["name", "stock_uom"]
	mode_field = None
	if price_list == "Wholesale":
		mode_field = _get_item_mode_default_uom_field("wholesale")
	elif price_list == "Retail":
		mode_field = _get_item_mode_default_uom_field("retail")
	if mode_field:
		item_fields.append(mode_field)
	item_rows = frappe.get_all(
		"Item",
		filters={"name": ["in", item_codes]},
		fields=item_fields,
		limit_page_length=0,
	)
	preferred_uoms = {
		row.name: (
			(_normalize_text(getattr(row, mode_field, None)) if mode_field else None)
			or _normalize_text(row.stock_uom)
		)
		for row in item_rows
	}
	grouped = {}
	for row in price_data:
		grouped.setdefault(row.item_code, []).append(
			{
				"price_list": row.price_list,
				"rate": flt(row.price_list_rate or 0),
				"uom": _normalize_text(row.uom) or None,
			}
		)
	result = {}
	for item_code, entries in grouped.items():
		selected = _select_price_entry(entries, price_list=price_list, preferred_uom=preferred_uoms.get(item_code))
		if selected:
			result[item_code] = selected["rate"]
	return result


def _get_multi_price_map(item_codes: list[str], *, price_lists: list[str], currency: str | None):
	if not item_codes or not price_lists:
		return {}
	permitted_price_lists = _get_permitted_price_list_names(price_lists)
	if not permitted_price_lists:
		return {}

	price_filters = {"item_code": ["in", item_codes], "price_list": ["in", permitted_price_lists]}
	if currency:
		price_filters["currency"] = currency
	price_rows = frappe.get_all(
		"Item Price",
		filters=price_filters,
		fields=["item_code", "price_list", "price_list_rate", "currency", "uom"],
	)

	result = {}
	for row in price_rows:
		item_prices = result.setdefault(row.item_code, {})
		entry_key = row.price_list
		if entry_key in item_prices:
			entry_key = f"{row.price_list}\x1f{_normalize_text(row.uom)}"
		item_prices[entry_key] = {
			"price_list": row.price_list,
			"rate": flt(row.price_list_rate or 0),
			"currency": row.currency or currency,
			"uom": _normalize_text(row.uom) or None,
		}
	return result


def _get_permitted_price_list_names(price_lists: list[str]) -> list[str]:
	resolved = list(dict.fromkeys(_normalize_text(name) for name in price_lists if _normalize_text(name)))
	if not resolved:
		return []
	try:
		return list(
			frappe.get_list(
				"Price List",
				filters={"name": ["in", resolved]},
				pluck="name",
				limit_page_length=0,
			)
		)
	except frappe.PermissionError:
		return []


def _get_uom_map(item_codes: list[str]):
	if not item_codes:
		return {}

	try:
		uom_data = frappe.get_all(
			"UOM Conversion Detail",
			filters={"parent": ["in", item_codes]},
			fields=["parent", "uom", "conversion_factor"],
		)
	except Exception:
		uom_data = []
	uom_map = {}
	for u in uom_data:
		uom_map.setdefault(u.parent, []).append({"uom": u.uom, "conversion_factor": u.conversion_factor})
	return uom_map


def _get_qty_map(item_codes: list[str], *, warehouse: str | None, company: str | None):
	if not item_codes:
		return {}
	if warehouse:
		permitted_warehouses = [
			ensure_warehouse_access(warehouse, company=company, applicable_for="Bin")
		]
	else:
		permitted_warehouses = get_permitted_warehouse_names(company=company, applicable_for="Bin")
	if not permitted_warehouses:
		return {item_code: 0 for item_code in item_codes}

	bin_dt = frappe.qb.DocType("Bin")
	query = (
		frappe.qb.from_(bin_dt)
		.select(bin_dt.item_code, Sum(bin_dt.actual_qty).as_("total_qty"))
		.where(bin_dt.item_code.isin(item_codes))
		.where(bin_dt.warehouse.isin(permitted_warehouses))
	)

	inventory_data = query.groupby(bin_dt.item_code).run(as_dict=True)
	return {d.item_code: d.total_qty or 0 for d in inventory_data}


def _get_warehouse_stock_detail_map(item_codes: list[str], *, company: str | None):
	if not item_codes:
		return {}
	permitted_warehouses = get_permitted_warehouse_names(company=company, applicable_for="Bin")
	if not permitted_warehouses:
		return {}

	bin_dt = frappe.qb.DocType("Bin")
	warehouse_dt = frappe.qb.DocType("Warehouse")
	query = (
		frappe.qb.from_(bin_dt)
		.inner_join(warehouse_dt)
		.on(bin_dt.warehouse == warehouse_dt.name)
		.select(
			bin_dt.item_code,
			bin_dt.warehouse,
			warehouse_dt.company,
			Sum(bin_dt.actual_qty).as_("total_qty"),
		)
		.where(bin_dt.item_code.isin(item_codes))
		.where(bin_dt.warehouse.isin(permitted_warehouses))
	)

	rows = query.groupby(bin_dt.item_code, bin_dt.warehouse, warehouse_dt.company).run(as_dict=True)
	result = {}
	for row in rows:
		result.setdefault(row.item_code, []).append(
			{
				"warehouse": row.warehouse,
				"company": row.company,
				"qty": flt(row.total_qty or 0),
			}
		)

	for item_code, details in result.items():
		result[item_code] = sorted(
			details,
			key=lambda detail: (-flt(detail.get("qty") or 0), _normalize_text(detail.get("warehouse")).lower()),
		)

	return result


def _resolve_stock_company_scope(warehouse: str | None, company: str | None):
	normalized_company = _normalize_text(company) or None
	if normalized_company:
		return normalized_company

	normalized_warehouse = _normalize_text(warehouse) or None
	if not normalized_warehouse:
		return None

	return _resolve_company_from_warehouse(normalized_warehouse)


def _sort_search_results(results: list[dict], *, sort_by: str, sort_order: str, item_code_order: list[str]):
	reverse = sort_order == "desc"
	order_index = {code: index for index, code in enumerate(item_code_order)}

	def _sort_key(row):
		if sort_by == "name":
			return (_normalize_text(row.get("item_name")).lower(), _normalize_text(row.get("item_code")).lower())
		if sort_by == "created":
			return (_normalize_text(str(row.get("creation") or "")), _normalize_text(row.get("item_code")).lower())
		if sort_by == "modified":
			return (_normalize_text(str(row.get("modified") or "")), _normalize_text(row.get("item_code")).lower())
		if sort_by == "qty":
			return (flt(row.get("qty") or 0), _normalize_text(row.get("item_name")).lower())
		if sort_by == "price":
			return (flt(row.get("price") or 0), _normalize_text(row.get("item_name")).lower())
		return (order_index.get(row.get("item_code"), 999999),)

	return sorted(results, key=_sort_key, reverse=reverse)


def _extract_item_nickname(item):
	nickname_field = _get_item_nickname_field()
	if nickname_field:
		nickname = _normalize_text(getattr(item, nickname_field, None))
		if nickname:
			return nickname
	return _normalize_text(getattr(item, "description", None)) or None


def _extract_item_specification(item):
	specification_field = _get_item_specification_field()
	if specification_field:
		specification = _normalize_text(getattr(item, specification_field, None))
		if specification:
			return specification
	return None


def _build_price_summary(
	item,
	*,
	current_price_list: str,
	current_rate: float | int | None,
	selling_price_map: dict[str, dict] | None = None,
	buying_price_map: dict[str, dict] | None = None,
):
	selling_price_map = selling_price_map or {}
	buying_price_map = buying_price_map or {}
	selling_entries = list(selling_price_map.values())
	buying_entries = list(buying_price_map.values())
	mode_default_uoms = _extract_mode_default_uoms(item)
	standard_selling = _select_price_entry(
		selling_entries,
		price_list="Standard Selling",
		preferred_uom=_normalize_text(getattr(item, "stock_uom", None)),
	)
	wholesale = _select_price_entry(
		selling_entries,
		price_list="Wholesale",
		preferred_uom=mode_default_uoms.get("wholesale_default_uom") or getattr(item, "stock_uom", None),
	)
	retail = _select_price_entry(
		selling_entries,
		price_list="Retail",
		preferred_uom=mode_default_uoms.get("retail_default_uom") or getattr(item, "stock_uom", None),
	)
	standard_buying = _select_price_entry(
		buying_entries,
		price_list="Standard Buying",
		preferred_uom=_normalize_text(getattr(item, "stock_uom", None)),
	)
	return {
		"current_price_list": current_price_list,
		"current_rate": flt(current_rate or 0),
		"standard_selling_rate": flt(
			(standard_selling or {}).get("rate")
			or getattr(item, "standard_rate", 0)
			or 0
		),
		"wholesale_rate": flt((wholesale or {}).get("rate") or 0),
		"retail_rate": flt((retail or {}).get("rate") or 0),
		"standard_buying_rate": flt((standard_buying or {}).get("rate") or 0),
		"valuation_rate": flt(getattr(item, "valuation_rate", 0) or 0),
		"selling_prices": selling_entries,
		"buying_prices": buying_entries,
	}


def _select_price_entry(entries, *, price_list: str, preferred_uom: str | None):
	candidates = [entry for entry in entries or [] if entry.get("price_list") == price_list]
	if not candidates:
		return None
	resolved_preferred_uom = _normalize_text(preferred_uom)
	if resolved_preferred_uom:
		for entry in candidates:
			if _normalize_text(entry.get("uom")) == resolved_preferred_uom:
				return entry
	for entry in candidates:
		if not _normalize_text(entry.get("uom")):
			return entry
	return candidates[0]


def _normalize_mode_default_uom(value):
	normalized = _normalize_text(value)
	if not normalized:
		return None
	return _resolve_default_uom(normalized)


def _build_item_uom_conversion_map(*, item=None, stock_uom=None, uom_conversions=None):
	resolved_stock_uom = _resolve_default_uom(stock_uom or getattr(item, "stock_uom", None))
	conversion_map = {}
	if resolved_stock_uom:
		conversion_map[resolved_stock_uom] = 1.0

	parsed_conversions = _coerce_uom_conversion_entries(uom_conversions) if uom_conversions is not None else None
	if parsed_conversions is not None:
		for row in parsed_conversions:
			conversion_map[row["uom"]] = row["conversion_factor"]
		return resolved_stock_uom, conversion_map

	existing_rows = getattr(item, "uoms", None)
	if isinstance(existing_rows, (list, tuple)):
		for row in existing_rows:
			uom = _normalize_text(getattr(row, "uom", None) if not isinstance(row, dict) else row.get("uom"))
			if not uom:
				continue
			conversion_factor = (
				getattr(row, "conversion_factor", None) if not isinstance(row, dict) else row.get("conversion_factor")
			)
			factor = flt(conversion_factor or 0)
			if factor > 0:
				conversion_map[_resolve_default_uom(uom)] = factor

	return resolved_stock_uom, conversion_map


def _validate_mode_default_uoms_against_stock_uom(*, item=None, stock_uom=None, uom_conversions=None, overrides=None):
	resolved_stock_uom, conversion_map = _build_item_uom_conversion_map(
		item=item,
		stock_uom=stock_uom,
		uom_conversions=uom_conversions,
	)
	if not resolved_stock_uom:
		frappe.throw(_("商品缺少库存基准单位，请先补全 stock_uom。"))

	default_uoms = _extract_mode_default_uoms(item) if item else {
		"wholesale_default_uom": None,
		"retail_default_uom": None,
	}
	for key, value in (overrides or {}).items():
		if key in default_uoms:
			default_uoms[key] = _normalize_mode_default_uom(value)

	for mode_key, default_uom in default_uoms.items():
		if not default_uom:
			continue
		if default_uom not in conversion_map:
			label = _("批发默认单位") if mode_key == "wholesale_default_uom" else _("零售默认单位")
			frappe.throw(
				_("{0} {1} 未配置到库存基准单位 {2} 的换算关系，请先补全 uom_conversions。").format(
					label,
					default_uom,
					resolved_stock_uom,
				)
			)


def _get_primary_barcode(item_code: str):
	rows = frappe.get_all(
		"Item Barcode",
		filters={"parent": item_code},
		fields=["barcode"],
		order_by="idx asc",
		limit=1,
	)
	return rows[0].barcode if rows else None


def _get_item_barcodes(item):
	rows = []
	for index, row in enumerate(list(getattr(item, "barcodes", []) or []), start=1):
		barcode = _normalize_text(getattr(row, "barcode", None))
		if not barcode:
			continue
		rows.append(
			{
				"name": getattr(row, "name", None),
				"barcode": barcode,
				"idx": cint(getattr(row, "idx", 0)) or index,
				"is_primary": index == 1,
				"uom": _normalize_text(getattr(row, "uom", None)) or None,
			}
		)
	return rows


def _get_item_barcode_map(item_codes: list[str]):
	normalized_codes = [code for code in (_normalize_text(value) for value in item_codes) if code]
	result = {code: [] for code in normalized_codes}
	if not normalized_codes:
		return result

	rows = frappe.get_all(
		"Item Barcode",
		filters={"parent": ["in", normalized_codes]},
		fields=["name", "parent", "barcode", "uom", "idx"],
		order_by="parent asc, idx asc",
	)
	for row in rows:
		parent = _normalize_text(getattr(row, "parent", None))
		barcode = _normalize_text(getattr(row, "barcode", None))
		if not parent or parent not in result or not barcode:
			continue
		entries = result[parent]
		entries.append(
			{
				"name": getattr(row, "name", None),
				"barcode": barcode,
				"idx": cint(getattr(row, "idx", 0)) or len(entries) + 1,
				"is_primary": len(entries) == 0,
				"uom": _normalize_text(getattr(row, "uom", None)) or None,
			}
		)
	return result


def _update_primary_barcode(item, barcode: str | None):
	if barcode is None:
		return

	normalized = _normalize_text(barcode)
	if normalized:
		existing_parent = frappe.db.get_value("Item Barcode", {"barcode": normalized}, "parent")
		if existing_parent and existing_parent != item.name:
			frappe.throw(_("条码 {0} 已存在。").format(normalized))

	barcodes = list(getattr(item, "barcodes", []) or [])
	if normalized:
		if barcodes:
			barcodes[0].barcode = normalized
			if not _normalize_text(getattr(barcodes[0], "uom", None)):
				barcodes[0].uom = item.stock_uom
		else:
			item.append("barcodes", {"barcode": normalized, "uom": item.stock_uom})


def _build_product_detail_payload(
	item,
	*,
	warehouse: str | None = None,
	company: str | None = None,
	price_list: str = "Standard Selling",
	currency: str | None = None,
):
	stock_company = _resolve_stock_company_scope(warehouse, company)
	qty_map = _get_qty_map([item.name], warehouse=warehouse, company=company)
	total_qty_map = _get_qty_map([item.name], warehouse=None, company=stock_company)
	warehouse_stock_map = _get_warehouse_stock_detail_map([item.name], company=stock_company)
	global_total_qty_map = _get_qty_map([item.name], warehouse=None, company=None)
	global_warehouse_stock_map = _get_warehouse_stock_detail_map([item.name], company=None)
	price_map = _get_price_map([item.name], price_list=price_list, currency=currency)
	selling_prices = _get_multi_price_map(
		[item.name],
		price_lists=list(DEFAULT_SELLING_PRICE_LISTS),
		currency=currency,
	).get(item.name, {})
	buying_prices = _get_multi_price_map(
		[item.name],
		price_lists=list(DEFAULT_BUYING_PRICE_LISTS),
		currency=currency,
	).get(item.name, {})
	uom_rows = _get_uom_map([item.name]).get(item.name, [])
	current_rate = flt(price_map.get(item.name, 0) or 0)
	mode_default_uoms = _extract_mode_default_uoms(item)
	uom_display_map = build_uom_display_map(_collect_item_uom_names(item=item, all_uoms=uom_rows))

	return {
		"item_code": item.name,
		"item_name": item.item_name,
		"item_group": item.item_group,
		"brand": getattr(item, "brand", None),
		"stock_uom": item.stock_uom,
		"stock_uom_display": uom_display_map.get(_normalize_text(item.stock_uom)),
		"uom": item.stock_uom,
		"uom_display": uom_display_map.get(_normalize_text(item.stock_uom)),
		"all_uoms": _decorate_uom_rows_with_display(uom_rows, uom_display_map),
		"image": item.image,
		"nickname": _extract_item_nickname(item),
		"specification": _extract_item_specification(item),
		"description": item.description,
		"disabled": cint(item.disabled),
		"is_sales_item": cint(getattr(item, "is_sales_item", 0)),
		"is_purchase_item": cint(getattr(item, "is_purchase_item", 0)),
		"barcode": _get_primary_barcode(item.name),
		"barcodes": _get_item_barcodes(item),
		"qty": flt(qty_map.get(item.name, 0)),
		"total_qty": flt(total_qty_map.get(item.name, 0)),
		"warehouse_stock_details": warehouse_stock_map.get(item.name, []),
		"global_total_qty": flt(global_total_qty_map.get(item.name, 0)),
		"global_warehouse_stock_details": global_warehouse_stock_map.get(item.name, []),
		"price": current_rate,
		"price_list": price_list,
		"currency": currency,
		"standard_rate": flt(getattr(item, "standard_rate", 0) or 0),
		"valuation_rate": flt(getattr(item, "valuation_rate", 0) or 0),
		"price_summary": _build_price_summary(
			item,
			current_price_list=price_list,
			current_rate=current_rate,
			selling_price_map=selling_prices,
			buying_price_map=buying_prices,
		),
		"wholesale_default_uom": mode_default_uoms["wholesale_default_uom"],
		"wholesale_default_uom_display": uom_display_map.get(_normalize_text(mode_default_uoms["wholesale_default_uom"])),
		"retail_default_uom": mode_default_uoms["retail_default_uom"],
		"retail_default_uom_display": uom_display_map.get(_normalize_text(mode_default_uoms["retail_default_uom"])),
		"sales_profiles": _build_sales_profiles_with_display(item, uom_display_map),
		"warehouse": warehouse,
		"company": company,
		"creation": getattr(item, "creation", None),
		"modified": getattr(item, "modified", None),
		"permissions": {
			"can_write": has_document_permission("Item", item, "write"),
		},
	}


def list_products_v2(
	search_key: str | None = None,
	warehouse: str | None = None,
	company: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	limit: int = 20,
	start: int = 0,
	item_group: str | None = None,
	brand: str | None = None,
	disabled: int | None = None,
	in_stock_only: bool | int = False,
	price_list: str = "Standard Selling",
	currency: str | None = None,
	selling_price_lists=None,
	buying_price_lists=None,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	require_doctype_permission("Item", "read")
	limit = _normalize_limit(limit)
	start = _normalize_start(start)
	warehouse = _normalize_text(warehouse) or None
	company = _normalize_text(company) or None
	price_list = _normalize_text(price_list) or "Standard Selling"
	currency = _normalize_currency(currency)
	selling_price_lists = _normalize_price_list_names(selling_price_lists, defaults=DEFAULT_SELLING_PRICE_LISTS)
	buying_price_lists = _normalize_price_list_names(buying_price_lists, defaults=DEFAULT_BUYING_PRICE_LISTS)
	item_group = _normalize_text(item_group) or None
	brand = _normalize_text(brand) or None
	in_stock_only = bool(cint(in_stock_only))
	sort_by = _normalize_text(sort_by).lower() or "modified"
	if sort_by not in {"modified", "creation", "item_name", "name"}:
		sort_by = "modified"
	sort_order = "asc" if _normalize_text(sort_order).lower() == "asc" else "desc"

	stock_company = _resolve_stock_company_scope(warehouse, company)
	if in_stock_only:
		all_rows = _get_item_rows(
			search_key=search_key,
			item_group=item_group,
			brand=brand,
			disabled=disabled,
			date_from=date_from,
			date_to=date_to,
			limit=0,
			start=0,
			sort_by=sort_by,
			sort_order=sort_order,
		)
		all_item_codes = [row.name for row in all_rows]
		all_qty_map = _get_qty_map(all_item_codes, warehouse=warehouse, company=company)
		filtered_rows = [row for row in all_rows if flt(all_qty_map.get(row.name, 0) or 0) > 0]
		total_count = len(filtered_rows)
		rows = filtered_rows[start : start + limit]
		qty_map = {row.name: all_qty_map.get(row.name, 0) for row in rows}
	else:
		rows = _get_item_rows(
			search_key=search_key,
			item_group=item_group,
			brand=brand,
			disabled=disabled,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
			start=start,
			sort_by=sort_by,
			sort_order=sort_order,
		)
		total_count = _count_item_rows(
			search_key=search_key,
			item_group=item_group,
			brand=brand,
			disabled=disabled,
			date_from=date_from,
			date_to=date_to,
		)
		item_codes = [row.name for row in rows]
		qty_map = _get_qty_map(item_codes, warehouse=warehouse, company=company)
	pagination = build_offset_pagination(
		start=start,
		limit=limit,
		total_count=total_count,
		row_count=len(rows),
	)
	item_codes = [row.name for row in rows]
	barcode_map = _get_item_barcode_map(item_codes)
	total_qty_map = _get_qty_map(item_codes, warehouse=None, company=stock_company)
	warehouse_stock_map = _get_warehouse_stock_detail_map(item_codes, company=stock_company)
	global_total_qty_map = _get_qty_map(item_codes, warehouse=None, company=None)
	global_warehouse_stock_map = _get_warehouse_stock_detail_map(item_codes, company=None)
	current_price_map = _get_price_map(item_codes, price_list=price_list, currency=currency)
	selling_price_map = _get_multi_price_map(item_codes, price_lists=selling_price_lists, currency=currency)
	buying_price_map = _get_multi_price_map(item_codes, price_lists=buying_price_lists, currency=currency)
	uom_map = _get_uom_map(item_codes)
	uom_names = []
	for row in rows:
		for name in _collect_item_uom_names(item=row, all_uoms=uom_map.get(row.name, [])):
			if name not in uom_names:
				uom_names.append(name)
	uom_display_map = build_uom_display_map(uom_names)

	items = []
	for row in rows:
		current_rate = flt(current_price_map.get(row.name, 0) or 0)
		mode_default_uoms = _extract_mode_default_uoms(row)
		row_uoms = uom_map.get(row.name, [])
		barcodes = barcode_map.get(row.name, [])
		items.append(
			{
				"item_code": row.name,
				"item_name": row.item_name,
				"item_group": row.item_group,
				"brand": getattr(row, "brand", None),
				"stock_uom": row.stock_uom,
				"stock_uom_display": uom_display_map.get(_normalize_text(row.stock_uom)),
				"image": row.image,
				"nickname": _extract_item_nickname(row),
				"specification": _extract_item_specification(row),
				"description": row.description,
				"barcode": barcodes[0]["barcode"] if barcodes else None,
				"barcodes": barcodes,
				"disabled": cint(row.disabled),
				"is_sales_item": cint(getattr(row, "is_sales_item", 0)),
				"is_purchase_item": cint(getattr(row, "is_purchase_item", 0)),
				"qty": flt(qty_map.get(row.name, 0) or 0),
				"total_qty": flt(total_qty_map.get(row.name, 0) or 0),
				"warehouse_stock_details": warehouse_stock_map.get(row.name, []),
				"global_total_qty": flt(global_total_qty_map.get(row.name, 0) or 0),
				"global_warehouse_stock_details": global_warehouse_stock_map.get(row.name, []),
				"price": current_rate,
				"price_list": price_list,
				"uom": row.stock_uom,
				"uom_display": uom_display_map.get(_normalize_text(row.stock_uom)),
				"all_uoms": _decorate_uom_rows_with_display(row_uoms, uom_display_map),
				"standard_rate": flt(getattr(row, "standard_rate", 0) or 0),
				"valuation_rate": flt(getattr(row, "valuation_rate", 0) or 0),
				"price_summary": _build_price_summary(
					row,
					current_price_list=price_list,
					current_rate=current_rate,
					selling_price_map=selling_price_map.get(row.name, {}),
					buying_price_map=buying_price_map.get(row.name, {}),
				),
				"wholesale_default_uom": mode_default_uoms["wholesale_default_uom"],
				"wholesale_default_uom_display": uom_display_map.get(_normalize_text(mode_default_uoms["wholesale_default_uom"])),
				"retail_default_uom": mode_default_uoms["retail_default_uom"],
				"retail_default_uom_display": uom_display_map.get(_normalize_text(mode_default_uoms["retail_default_uom"])),
				"sales_profiles": _build_sales_profiles_with_display(row, uom_display_map),
				"creation": row.creation,
				"modified": row.modified,
			}
		)

	return {
		"status": "success",
		"data": items,
		"meta": {
			"total": total_count,
			"total_count": total_count,
			"start": start,
			"limit": limit,
			"has_more": pagination["has_more"],
			"pagination": pagination,
		},
		"pagination": pagination,
		"filters": {
			"search_key": _normalize_text(search_key) or None,
			"warehouse": warehouse,
			"company": company,
			"date_from": _normalize_text(date_from) or None,
			"date_to": _normalize_text(date_to) or None,
			"limit": limit,
			"start": start,
			"item_group": _normalize_text(item_group) or None,
			"brand": brand,
			"disabled": disabled,
			"in_stock_only": in_stock_only,
			"price_list": price_list,
			"currency": currency,
			"selling_price_lists": selling_price_lists,
			"buying_price_lists": buying_price_lists,
			"sort_by": sort_by,
			"sort_order": sort_order,
		},
	}


def search_product(
	search_key: str,
	price_list: str = "Standard Selling",
	currency: str | None = None,
	warehouse: str | None = None,
	company: str | None = None,
	limit: int = 20,
):
	"""
	搜索商品，并返回基础信息、价格、单位与库存。

	库存口径：
	- 传入 warehouse 时，返回该仓库库存
	- 未传 warehouse、传入 company 时，汇总该公司下所有仓库库存
	- warehouse 和 company 都不传时，汇总全仓库存
	"""
	require_doctype_permission("Item", "read")
	search_key = _normalize_text(search_key)
	if not search_key:
		return {"status": "success", "data": []}

	limit = _normalize_limit(limit)
	price_list = _normalize_text(price_list) or "Standard Selling"
	currency = _normalize_currency(currency)
	warehouse = _normalize_text(warehouse) or None
	company = _normalize_text(company) or None

	item_codes = _search_item_codes(
		search_key,
		search_fields=["barcode", "item_code", "item_name", "specification"],
		limit=limit,
	)

	if not item_codes:
		return {"status": "success", "data": [], "message": _("未找到匹配商品")}

	items_data = _get_item_data_map(item_codes)
	price_map = _get_price_map(item_codes, price_list=price_list, currency=currency)
	uom_map = _get_uom_map(item_codes)
	qty_map = _get_qty_map(item_codes, warehouse=warehouse, company=company)
	uom_names = []
	for code in item_codes:
		for name in _collect_item_uom_names(item=items_data.get(code), all_uoms=uom_map.get(code, [])):
			if name not in uom_names:
				uom_names.append(name)
	uom_display_map = build_uom_display_map(uom_names)

	results = []
	specification_field = _get_item_specification_field()
	for code in item_codes:
		item = items_data.get(code)
		if not item:
			continue

		results.append(
			{
				"item_code": item.name,
				"item_name": item.item_name,
				"uom": item.stock_uom,
				"uom_display": uom_display_map.get(_normalize_text(item.stock_uom)),
				"all_uoms": _decorate_uom_rows_with_display(uom_map.get(code, []), uom_display_map),
				"qty": qty_map.get(code, 0),
				"price": price_map.get(code, 0),
				"image": item.image,
				"specification": getattr(item, specification_field, None) if specification_field else None,
			}
		)

	return {
		"status": "success",
		"data": results,
		"filters": {
			"price_list": price_list,
			"currency": currency,
			"warehouse": warehouse,
			"company": company,
			"limit": limit,
		},
	}


def get_product_detail_v2(
	item_code: str,
	warehouse: str | None = None,
	company: str | None = None,
	price_list: str = "Standard Selling",
	currency: str | None = None,
):
	item_code = _normalize_text(item_code)
	if not item_code:
		frappe.throw(_("商品编码不能为空。"))

	warehouse = _normalize_text(warehouse) or None
	company = _normalize_text(company) or None
	price_list = _normalize_text(price_list) or "Standard Selling"
	currency = _normalize_currency(currency)

	item = require_document_permission("Item", item_code, "read")
	return {
		"status": "success",
		"data": _build_product_detail_payload(
			item,
			warehouse=warehouse,
			company=company,
			price_list=price_list,
			currency=currency,
		),
	}


def _serialize_product_price(price, *, price_list_type: str | None = None):
	return {
		"name": price.name,
		"item_code": price.item_code,
		"price_list": price.price_list,
		"price_list_type": price_list_type,
		"currency": price.currency,
		"uom": _normalize_text(price.uom) or None,
		"rate": flt(price.price_list_rate or 0),
		"valid_from": str(price.valid_from) if price.valid_from else None,
		"valid_upto": str(price.valid_upto) if price.valid_upto else None,
		"modified": str(price.modified) if price.modified else None,
	}


def _resolve_price_list_type(price_list):
	if cint(getattr(price_list, "selling", 0)) and cint(getattr(price_list, "buying", 0)):
		return "both"
	return "buying" if cint(getattr(price_list, "buying", 0)) else "selling"


def _get_permitted_product_price_lists():
	rows = frappe.get_list(
		"Price List",
		filters={"enabled": 1},
		fields=["name", "selling", "buying", "currency"],
		order_by="selling desc, buying desc, name asc",
		limit_page_length=0,
	)
	return {
		row.name: {
			"buying": bool(cint(row.buying)),
			"currency": _normalize_text(row.currency) or None,
			"selling": bool(cint(row.selling)),
		}
		for row in rows
	}


def list_product_prices_v1(item_code: str):
	item_code = _normalize_text(item_code)
	if not item_code:
		frappe.throw(_("商品编码不能为空。"))
	item = require_document_permission("Item", item_code, "read")
	price_lists = _get_permitted_product_price_lists()
	if not price_lists:
		return {
			"status": "success",
			"data": {
				"item_code": item.name,
				"item_modified": str(item.modified),
				"permissions": {
					"can_create": bool(frappe.has_permission("Item Price", ptype="create")),
					"can_write": bool(frappe.has_permission("Item Price", ptype="write")),
				},
				"prices": [],
				"price_lists": [],
			},
		}

	rows = frappe.get_all(
		"Item Price",
		filters={"item_code": item.name, "price_list": ["in", list(price_lists)]},
		fields=[
			"name",
			"item_code",
			"price_list",
			"currency",
			"uom",
			"price_list_rate",
			"valid_from",
			"valid_upto",
			"modified",
		],
		order_by="price_list asc, currency asc, uom asc, valid_from desc, modified desc",
	)
	prices = []
	for row in rows:
		config = price_lists.get(row.price_list) or {}
		price_list_type = (
			"both"
			if config.get("selling") and config.get("buying")
			else ("buying" if config.get("buying") else "selling")
		)
		prices.append(_serialize_product_price(row, price_list_type=price_list_type))
	return {
		"status": "success",
		"data": {
			"item_code": item.name,
			"item_modified": str(item.modified),
			"permissions": {
				"can_create": bool(frappe.has_permission("Item Price", ptype="create")),
				"can_write": bool(frappe.has_permission("Item Price", ptype="write")),
			},
			"prices": prices,
			"price_lists": [
				{
					"name": name,
					"buying": config["buying"],
					"selling": config["selling"],
					"currency": config["currency"],
				}
				for name, config in price_lists.items()
			],
		},
	}


def _product_history_value(value):
	if isinstance(value, str):
		return value if len(value) <= 500 else f"{value[:500]}…"
	if isinstance(value, dict):
		return {
			str(key): _product_history_value(nested)
			for key, nested in value.items()
			if str(key).lower() not in {"password", "secret", "token"}
		}
	if isinstance(value, (list, tuple)):
		return [_product_history_value(nested) for nested in list(value)[:50]]
	return value


def _product_history_label(fieldname):
	resolved = _normalize_text(fieldname)
	if "." in resolved:
		parent, child = resolved.split(".", 1)
		return f"{PRODUCT_HISTORY_FIELD_LABELS.get(parent, parent)} · {PRODUCT_HISTORY_FIELD_LABELS.get(child, child)}"
	return PRODUCT_HISTORY_FIELD_LABELS.get(resolved, resolved or _("未知字段"))


def _parse_product_version_changes(raw_data):
	if isinstance(raw_data, str):
		try:
			payload = frappe.parse_json(raw_data) or {}
		except Exception:
			payload = {}
	elif isinstance(raw_data, dict):
		payload = raw_data
	else:
		payload = {}
	changes = []
	for row in payload.get("changed") or []:
		if not isinstance(row, (list, tuple)) or len(row) < 3:
			continue
		fieldname = _normalize_text(row[0])
		changes.append(
			{
				"field": fieldname,
				"label": _product_history_label(fieldname),
				"old_value": _product_history_value(row[1]),
				"new_value": _product_history_value(row[2]),
			}
		)
	for key, action in (("added", "added"), ("removed", "removed")):
		for row in payload.get(key) or []:
			if not isinstance(row, (list, tuple)) or len(row) < 2:
				continue
			fieldname = _normalize_text(row[0])
			value = _product_history_value(row[1])
			changes.append(
				{
					"field": fieldname,
					"label": _product_history_label(fieldname),
					"old_value": value if action == "removed" else None,
					"new_value": value if action == "added" else None,
					"row_action": action,
				}
			)
	for row in payload.get("row_changed") or []:
		if not isinstance(row, (list, tuple)) or len(row) < 4:
			continue
		parent_field = _normalize_text(row[0])
		for child_change in row[3] or []:
			if not isinstance(child_change, (list, tuple)) or len(child_change) < 3:
				continue
			fieldname = f"{parent_field}.{_normalize_text(child_change[0])}"
			changes.append(
				{
					"field": fieldname,
					"label": _product_history_label(fieldname),
					"old_value": _product_history_value(child_change[1]),
					"new_value": _product_history_value(child_change[2]),
				}
			)
	return changes


def _product_history_category(changes):
	fields = {_normalize_text(change.get("field")) for change in changes}
	if any(field == "barcodes" or field.startswith("barcodes.") for field in fields):
		return "barcode"
	if any(
		field in {"stock_uom", "uoms", WHOLESALE_DEFAULT_UOM_FIELD, RETAIL_DEFAULT_UOM_FIELD}
		or field.startswith("uoms.")
		for field in fields
	):
		return "uom"
	if fields == {"valuation_rate"}:
		return "valuation"
	return "product"


def _product_history_event_from_version(row, *, category, title, summary, source_doctype):
	changes = _parse_product_version_changes(row.data)
	resolved_category = category(changes) if callable(category) else category
	resolved_title = {
		"barcode": _("更新条码"),
		"uom": _("更新单位配置"),
		"valuation": _("更新库存估值"),
	}.get(resolved_category, title)
	return {
		"id": f"Version:{row.name}",
		"occurred_at": str(row.creation),
		"actor": _normalize_text(row.owner) or _normalize_text(getattr(row, "modified_by", None)) or None,
		"category": resolved_category,
		"action": "updated",
		"title": resolved_title,
		"summary": summary,
		"source_doctype": source_doctype,
		"source_name": row.docname,
		"changes": changes,
	}


def list_product_change_history_v1(item_code: str, start: int = 0, limit: int = 50):
	item_code = _normalize_text(item_code)
	if not item_code:
		frappe.throw(_("商品编码不能为空。"))
	item = require_document_permission("Item", item_code, "read")
	resolved_start = _normalize_start(start)
	resolved_limit = max(1, min(int(limit or 50), 200))
	fetch_limit = resolved_start + resolved_limit + 1
	price_lists = _get_permitted_product_price_lists()
	price_rows = []
	if price_lists:
		price_rows = frappe.get_all(
			"Item Price",
			filters={"item_code": item.name, "price_list": ["in", list(price_lists)]},
			fields=[
				"name",
				"creation",
				"owner",
				"price_list",
				"currency",
				"uom",
				"price_list_rate",
				"valid_from",
				"valid_upto",
			],
			order_by="creation desc",
			limit_page_length=fetch_limit,
		)
	price_by_name = {row.name: row for row in price_rows}
	item_versions = frappe.get_all(
		"Version",
		filters={"ref_doctype": "Item", "docname": item.name},
		fields=["name", "creation", "owner", "modified_by", "docname", "data"],
		order_by="creation desc",
		limit_page_length=fetch_limit,
	)
	price_versions = []
	if price_by_name:
		price_versions = frappe.get_all(
			"Version",
			filters={"ref_doctype": "Item Price", "docname": ["in", list(price_by_name)]},
			fields=["name", "creation", "owner", "modified_by", "docname", "data"],
			order_by="creation desc",
			limit_page_length=fetch_limit,
		)
	initial_price_rates = {
		name: flt(row.price_list_rate or 0) for name, row in price_by_name.items()
	}
	for row in price_versions:
		for change in _parse_product_version_changes(row.data):
			if change.get("field") == "price_list_rate":
				initial_price_rates[row.docname] = flt(change.get("old_value") or 0)
	events = []
	if getattr(item, "creation", None):
		events.append(
			{
				"id": f"Item:{item.name}:created",
				"occurred_at": str(item.creation),
				"actor": _normalize_text(getattr(item, "owner", None)) or None,
				"category": "product",
				"action": "created",
				"title": _("创建商品"),
				"summary": item.name,
				"source_doctype": "Item",
				"source_name": item.name,
				"changes": [],
			}
		)
	for row in item_versions:
		events.append(
			_product_history_event_from_version(
				row,
				category=_product_history_category,
				title=_("更新商品资料"),
				summary=item.name,
				source_doctype="Item",
			)
		)
	for row in price_rows:
		events.append(
			{
				"id": f"Item Price:{row.name}:created",
				"occurred_at": str(row.creation),
				"actor": _normalize_text(row.owner) or None,
				"category": "price",
				"action": "created",
				"title": _("新增价格"),
				"summary": f"{row.price_list} · {_normalize_text(row.uom) or _('未指定单位')}",
				"source_doctype": "Item Price",
				"source_name": row.name,
				"changes": [
					{
						"field": "price_list_rate",
						"label": _product_history_label("price_list_rate"),
						"old_value": None,
						"new_value": initial_price_rates.get(row.name, flt(row.price_list_rate or 0)),
					}
				],
			}
		)
	for row in price_versions:
		price = price_by_name.get(row.docname)
		changes = _parse_product_version_changes(row.data)
		terminated = False
		for change in changes:
			if change.get("field") != "valid_upto" or change.get("new_value") in (None, ""):
				continue
			try:
				terminated = getdate(change.get("new_value")) <= getdate(row.creation)
			except Exception:
				terminated = False
			if terminated:
				break
		events.append(
			{
				"id": f"Version:{row.name}",
				"occurred_at": str(row.creation),
				"actor": _normalize_text(row.owner) or _normalize_text(getattr(row, "modified_by", None)) or None,
				"category": "price",
				"action": "terminated" if terminated else "updated",
				"title": _("终止价格") if terminated else _("更新价格"),
				"summary": (
					f"{price.price_list} · {_normalize_text(price.uom) or _('未指定单位')}"
					if price
					else row.docname
				),
				"source_doctype": "Item Price",
				"source_name": row.docname,
				"changes": changes,
			}
		)
	for row in list_product_corrections_for_history(item.name, limit=fetch_limit):
		correction_type = _normalize_text(row.correction_type)
		events.append(
			{
				"id": f"MyApp Product Correction:{row.name}",
				"occurred_at": str(row.executed_at or row.creation),
				"actor": _normalize_text(row.executed_by or row.modified_by or row.owner) or None,
				"category": "uom",
				"action": "corrected",
				"title": _("创建继任商品") if correction_type == "replacement" else _("原地纠正单位"),
				"summary": _normalize_text(row.reason) or _("库存基准单位纠正"),
				"source_doctype": "MyApp Product Correction",
				"source_name": row.name,
				"changes": [
					{
						"field": "target_item",
						"label": _("目标商品"),
						"old_value": row.source_item,
						"new_value": row.target_item,
					}
				],
			}
		)
	events.sort(key=lambda event: (event.get("occurred_at") or "", event.get("id") or ""), reverse=True)
	page = events[resolved_start : resolved_start + resolved_limit]
	return {
		"status": "success",
		"data": {
			"item_code": item.name,
			"events": page,
			"pagination": {
				"start": resolved_start,
				"limit": resolved_limit,
				"returned_count": len(page),
				"has_more": len(events) > resolved_start + resolved_limit,
			},
		},
	}


def _validate_product_price_dates(valid_from, valid_upto):
	resolved_from = getdate(valid_from) if valid_from not in (None, "") else None
	resolved_upto = getdate(valid_upto) if valid_upto not in (None, "") else None
	if resolved_from and resolved_upto and resolved_from > resolved_upto:
		frappe.throw(_("价格生效日期不能晚于失效日期。"))
	return resolved_from, resolved_upto


def upsert_product_price_v1(item_code: str, price_list: str, rate, **kwargs):
	item_code = _normalize_text(item_code)
	price_list = _normalize_text(price_list)
	if not item_code or not price_list:
		frappe.throw(_("商品编码和价格表不能为空。"))
	request_id = get_current_request_id(kwargs.get("request_id"))

	def _upsert_price():
		item = require_document_permission("Item", item_code, "read")
		expected_item_modified = _normalize_text(kwargs.get("item_modified"))
		if expected_item_modified and expected_item_modified != str(item.modified):
			frappe.throw(_("商品资料已被其他人修改，请刷新后重新维护价格。"))
		price_list_doc = require_document_permission("Price List", price_list, "read")
		resolved_rate = _normalize_product_uom_migration_price_rate(rate, field_label=_("价格"))
		resolved_uom = _resolve_item_price_uom(item, kwargs.get("uom"), price_list_doc.name)
		resolved_currency = _normalize_text(kwargs.get("currency")) or price_list_doc.currency or _normalize_currency(None)
		valid_from, valid_upto = _validate_product_price_dates(
			kwargs.get("valid_from"), kwargs.get("valid_upto")
		)

		price_name = _normalize_text(kwargs.get("price_name"))
		if price_name:
			price = require_document_permission("Item Price", price_name, "write")
			if price.item_code != item.name:
				frappe.throw(_("价格记录不属于当前商品。"))
			if (
				price.price_list != price_list_doc.name
				or _normalize_text(price.currency) != _normalize_text(resolved_currency)
				or _normalize_text(price.uom) != _normalize_text(resolved_uom)
			):
				frappe.throw(_("现有价格的价格表、币种和单位不能直接改写；请新增正确价格并终止旧记录。"))
			expected_price_modified = _normalize_text(kwargs.get("price_modified"))
			if expected_price_modified and expected_price_modified != str(price.modified):
				frappe.throw(_("价格记录已被其他人修改，请刷新后重试。"))
			price.price_list = price_list_doc.name
			price.currency = resolved_currency
			price.uom = resolved_uom
			price.price_list_rate = resolved_rate
			price.valid_from = valid_from
			price.valid_upto = valid_upto
			price.save()
		else:
			require_doctype_permission("Item Price", "create")
			price = frappe.new_doc("Item Price")
			price.item_code = item.name
			price.price_list = price_list_doc.name
			price.currency = resolved_currency
			price.uom = resolved_uom
			price.price_list_rate = resolved_rate
			price.valid_from = valid_from
			price.valid_upto = valid_upto
			price.insert()

		price.reload()
		return {
			"status": "success",
			"data": _serialize_product_price(
				price,
				price_list_type=_resolve_price_list_type(price_list_doc),
			),
		}

	return run_idempotent("upsert_product_price_v1", request_id, _upsert_price)


def terminate_product_price_v1(item_code: str, price_name: str, **kwargs):
	item_code = _normalize_text(item_code)
	price_name = _normalize_text(price_name)
	if not item_code or not price_name:
		frappe.throw(_("商品编码和价格记录不能为空。"))
	request_id = get_current_request_id(kwargs.get("request_id"))

	def _terminate_price():
		require_document_permission("Item", item_code, "read")
		price = require_document_permission("Item Price", price_name, "write")
		if price.item_code != item_code:
			frappe.throw(_("价格记录不属于当前商品。"))
		expected_price_modified = _normalize_text(kwargs.get("price_modified"))
		if expected_price_modified and expected_price_modified != str(price.modified):
			frappe.throw(_("价格记录已被其他人修改，请刷新后重试。"))
		_valid_from, valid_upto = _validate_product_price_dates(
			getattr(price, "valid_from", None),
			kwargs.get("valid_upto") or nowdate(),
		)
		price.valid_upto = valid_upto
		price.save()
		price.reload()
		price_list_doc = require_document_permission("Price List", price.price_list, "read")
		return {
			"status": "success",
			"data": _serialize_product_price(
				price,
				price_list_type=_resolve_price_list_type(price_list_doc),
			),
		}

	return run_idempotent("terminate_product_price_v1", request_id, _terminate_price)


def _require_product_uom_migration_manager():
	user = current_user()
	if user == "Administrator":
		return user
	if PRODUCT_UOM_MIGRATION_MANAGER_ROLE not in set(frappe.get_roles(user) or []):
		raise frappe.PermissionError(_("只有系统管理员可以执行商品单位迁移。"))
	return user


def _get_product_uom_migration_bins(item_code: str):
	fields = [
		"name",
		"warehouse",
		"actual_qty",
		"valuation_rate",
		"stock_value",
		"projected_qty",
		*PRODUCT_UOM_MIGRATION_COMMITTED_BIN_FIELDS,
	]
	rows = frappe.get_all(
		"Bin",
		filters={"item_code": item_code},
		fields=fields,
		order_by="warehouse asc",
	)
	warehouse_names = [row.warehouse for row in rows if row.warehouse]
	company_by_warehouse = {}
	if warehouse_names:
		company_by_warehouse = {
			row.name: row.company
			for row in frappe.get_all(
				"Warehouse",
				filters={"name": ["in", warehouse_names]},
				fields=["name", "company"],
			)
		}

	result = []
	for row in rows:
		result.append(
			{
				"name": row.name,
				"warehouse": row.warehouse,
				"company": company_by_warehouse.get(row.warehouse),
				"actual_qty": flt(row.actual_qty or 0),
				"valuation_rate": flt(row.valuation_rate or 0),
				"stock_value": flt(row.stock_value or 0),
				"projected_qty": flt(row.projected_qty or 0),
				**{
					fieldname: flt(getattr(row, fieldname, 0) or 0)
					for fieldname in PRODUCT_UOM_MIGRATION_COMMITTED_BIN_FIELDS
				},
			}
		)
	return result


def _get_product_uom_migration_open_transactions(item_code: str):
	sales_rows = frappe.db.sql(
		"""
		SELECT COUNT(DISTINCT soi.parent) AS document_count
		FROM `tabSales Order Item` soi
		INNER JOIN `tabSales Order` so ON so.name = soi.parent
		WHERE soi.item_code = %s
			AND so.docstatus IN (0, 1)
			AND COALESCE(so.status, '') NOT IN ('Closed', 'Completed')
			AND COALESCE(soi.qty, 0) > COALESCE(soi.delivered_qty, 0)
		""",
		(item_code,),
		as_dict=True,
	)
	purchase_rows = frappe.db.sql(
		"""
		SELECT COUNT(DISTINCT poi.parent) AS document_count
		FROM `tabPurchase Order Item` poi
		INNER JOIN `tabPurchase Order` po ON po.name = poi.parent
		WHERE poi.item_code = %s
			AND po.docstatus IN (0, 1)
			AND COALESCE(po.status, '') NOT IN ('Closed', 'Completed')
			AND COALESCE(poi.qty, 0) > COALESCE(poi.received_qty, 0)
		""",
		(item_code,),
		as_dict=True,
	)
	return {
		"sales_order_count": cint(sales_rows[0].document_count if sales_rows else 0),
		"purchase_order_count": cint(purchase_rows[0].document_count if purchase_rows else 0),
	}


def _get_product_uom_migration_prices(item_code: str):
	return [
		{
			"name": row.name,
			"price_list": row.price_list,
			"currency": row.currency,
			"rate": flt(row.price_list_rate or 0),
			"uom": _normalize_text(row.uom) or None,
		}
		for row in frappe.get_all(
			"Item Price",
			filters={"item_code": item_code},
			fields=["name", "price_list", "currency", "price_list_rate", "uom"],
			order_by="price_list asc, currency asc, uom asc, name asc",
		)
	]


def _get_product_uom_migration_alternatives(item_code: str):
	rows = frappe.get_all(
		"Item Alternative",
		filters={"item_code": item_code},
		fields=["name", "alternative_item_code", "two_way"],
		order_by="creation asc",
	)
	return [
		{
			"name": row.name,
			"alternative_item_code": row.alternative_item_code,
			"two_way": bool(cint(row.two_way)),
		}
		for row in rows
	]


def _build_product_uom_migration_assessment(item):
	item_code = item.name
	bins = _get_product_uom_migration_bins(item_code)
	open_transactions = _get_product_uom_migration_open_transactions(item_code)
	prices = _get_product_uom_migration_prices(item_code)
	barcodes = _get_item_barcodes(item)
	stock_ledger_entry_count = frappe.db.count(
		"Stock Ledger Entry",
		{"item_code": item_code, "is_cancelled": 0},
	)
	latest_stock_ledger = frappe.get_all(
		"Stock Ledger Entry",
		filters={"item_code": item_code, "is_cancelled": 0},
		fields=["posting_date", "posting_time", "voucher_type", "voucher_no"],
		order_by="posting_date desc, posting_time desc, creation desc",
		limit_page_length=1,
	)
	total_actual_qty = sum(flt(row.get("actual_qty") or 0) for row in bins)
	positive_stock_bins = [row for row in bins if flt(row.get("actual_qty") or 0) > 0.000001]
	negative_stock_bins = [row for row in bins if flt(row.get("actual_qty") or 0) < -0.000001]
	total_committed_qty = sum(
		max(
			(abs(flt(row.get(fieldname) or 0)) for fieldname in PRODUCT_UOM_MIGRATION_COMMITTED_BIN_FIELDS),
			default=0,
		)
		for row in bins
	)
	blockers = []
	warnings = []
	if positive_stock_bins:
		blockers.append(
			{
				"code": "NON_ZERO_STOCK",
				"message": _("商品仍有实际库存；创建继任商品时必须逐仓确认新数量，并在同一事务中通过 Repack 将旧商品库存清零。"),
			}
		)
	if negative_stock_bins:
		blockers.append(
			{
				"code": "NEGATIVE_STOCK",
				"message": _("商品存在负库存，不能自动 Repack。请先通过库存盘点或业务单据把各仓库存纠正为非负数量。"),
			}
		)
	if total_committed_qty > 0.000001:
		blockers.append(
			{
				"code": "COMMITTED_STOCK_EXISTS",
				"message": _("商品仍有预留、在途、计划或请购数量，请先关闭或完成相关库存承诺。"),
			}
		)
	if open_transactions["sales_order_count"]:
		blockers.append(
			{
				"code": "OPEN_SALES_ORDERS",
				"message": _("商品仍被未完成销售订单引用，请先完成、替换或关闭这些订单。"),
			}
		)
	if open_transactions["purchase_order_count"]:
		blockers.append(
			{
				"code": "OPEN_PURCHASE_ORDERS",
				"message": _("商品仍被未完成采购订单引用，请先完成、替换或关闭这些订单。"),
			}
		)
	if cint(getattr(item, "has_variants", 0)) or _normalize_text(getattr(item, "variant_of", None)):
		blockers.append(
			{
				"code": "ITEM_VARIANT_UNSUPPORTED",
				"message": _("当前商品属于模板或变体，必须按变体族单独制定迁移方案。"),
			}
		)
	if cint(getattr(item, "is_fixed_asset", 0)):
		blockers.append(
			{
				"code": "FIXED_ASSET_UNSUPPORTED",
				"message": _("固定资产商品不支持通过此流程迁移库存单位。"),
			}
		)
	if cint(getattr(item, "disabled", 0)):
		warnings.append(
			{
				"code": "SOURCE_ALREADY_DISABLED",
				"message": _("源商品当前已停用；执行前仍会重新校验库存、订单和映射。"),
			}
		)
	alternatives = _get_product_uom_migration_alternatives(item_code)
	if alternatives:
		warnings.append(
			{
				"code": "ALTERNATIVE_ALREADY_EXISTS",
				"message": _("源商品已配置其他替代商品，请确认本次迁移不会造成选品歧义。"),
			}
		)
	if stock_ledger_entry_count:
		warnings.append(
			{
				"code": "HISTORY_PRESERVED",
				"message": _("历史库存流水将永久保留在源商品下，本流程不会重写或转移历史账本。"),
			}
		)

	uom_rows = _get_uom_map([item_code]).get(item_code, [])
	uom_display_map = build_uom_display_map(_collect_item_uom_names(item=item, all_uoms=uom_rows))
	unresolved_blockers = [row for row in blockers if row["code"] != "NON_ZERO_STOCK"]
	can_execute_with_inventory_conversion = bool(positive_stock_bins) and not unresolved_blockers and not cint(item.disabled)
	can_correct_in_place = (
		not blockers
		and not cint(item.disabled)
		and not alternatives
		and not stock_ledger_entry_count
	)
	can_create_replacement = not unresolved_blockers and not cint(item.disabled)
	return {
		"suggested_new_item_code": _build_item_code(item.item_name),
		"recommended_strategy": "in_place" if can_correct_in_place else ("replacement" if can_create_replacement else None),
		"can_execute_with_inventory_conversion": can_execute_with_inventory_conversion,
		"strategies": {
			"in_place": {
				"available": can_correct_in_place,
				"reason": _("当前库存、占用和未完单据均已清零，可保留原商品编码并受控纠正单位。")
				if can_correct_in_place
				else _("源商品已停用、已有替代关系、存在历史库存流水或其他阻断项，不能原地纠正。"),
			},
			"replacement": {
				"available": can_create_replacement,
				"reason": (
					_("可在本向导中逐仓确认新数量，并通过正式 Repack 转移现有库存后创建继任商品。")
					if can_execute_with_inventory_conversion
					else _("商品物理身份或包装基础真正变化时，可创建正式继任商品。")
				)
				if can_create_replacement
				else _("源商品已停用或存在阻断项，不能创建替代商品。"),
			},
		},
		"source": {
			"item_code": item_code,
			"item_name": item.item_name,
			"modified": str(item.modified),
			"disabled": bool(cint(item.disabled)),
			"stock_uom": item.stock_uom,
			"stock_uom_display": uom_display_map.get(_normalize_text(item.stock_uom)),
			"uom_conversions": _decorate_uom_rows_with_display(uom_rows, uom_display_map),
			"wholesale_default_uom": _extract_mode_default_uoms(item)["wholesale_default_uom"],
			"retail_default_uom": _extract_mode_default_uoms(item)["retail_default_uom"],
		},
		"inventory": {
			"total_actual_qty": flt(total_actual_qty),
			"total_committed_qty": flt(total_committed_qty),
			"bins": bins,
		},
		"history": {
			"stock_ledger_entry_count": cint(stock_ledger_entry_count),
			"latest_stock_ledger_entry": latest_stock_ledger[0] if latest_stock_ledger else None,
		},
		"open_transactions": open_transactions,
		"prices": prices,
		"barcodes": barcodes,
		"alternatives": alternatives,
		"blockers": blockers,
		"warnings": warnings,
		"can_execute": not blockers,
	}


def assess_product_uom_migration_v1(item_code: str):
	_require_product_uom_migration_manager()
	item_code = _normalize_text(item_code)
	if not item_code:
		frappe.throw(_("商品编码不能为空。"))
	item = require_document_permission("Item", item_code, "read")
	return {
		"status": "success",
		"data": _build_product_uom_migration_assessment(item),
	}


def _normalize_product_uom_migration_mappings(value, *, source_rows, mapping_kind: str):
	mapping_config = {
		"price": {"label": _("价格"), "actions": {"copy", "manual", "skip"}},
		"barcode": {"label": _("条码"), "actions": {"move", "keep"}},
	}.get(mapping_kind)
	if not mapping_config:
		raise ValueError(f"Unsupported migration mapping kind: {mapping_kind}")
	mapping_label = mapping_config["label"]
	rows = _coerce_json_value(value, [])
	if not isinstance(rows, list):
		frappe.throw(_("{0}映射格式不正确。").format(mapping_label))
	source_names = {_normalize_text(row.get("name")) for row in source_rows}
	mappings = {}
	for row in rows:
		if not isinstance(row, dict):
			frappe.throw(_("{0}映射必须是对象列表。").format(mapping_label))
		source_name = _normalize_text(row.get("source_name"))
		action = _normalize_text(row.get("action")).lower()
		if not source_name or source_name not in source_names:
			frappe.throw(_("{0}映射引用了不存在的源记录。").format(mapping_label))
		if source_name in mappings:
			frappe.throw(_("同一{0}记录不能重复映射。").format(mapping_label))
		if action not in mapping_config["actions"]:
			frappe.throw(_("{0}映射动作不正确。").format(mapping_label))
		mappings[source_name] = {
			"source_name": source_name,
			"action": action,
			"target_uom": _normalize_text(row.get("target_uom")) or None,
		}
		if mapping_kind == "price":
			mappings[source_name]["target_rate"] = (
				_normalize_product_uom_migration_price_rate(
					row.get("target_rate"),
					field_label=_("手工新价格"),
				)
				if action == "manual"
				else None
			)
	if set(mappings) != source_names:
		frappe.throw(_("必须逐条确认全部{0}记录的迁移方式，不能遗漏或自动猜测。").format(mapping_label))
	return mappings


def _normalize_product_uom_migration_price_rate(value, *, field_label: str):
	if value in (None, ""):
		frappe.throw(_("{0}不能为空。").format(field_label))
	try:
		resolved = Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(_("{0}必须是有效数字。").format(field_label))
	if not resolved.is_finite() or resolved < 0:
		frappe.throw(_("{0}不能为负数或无效数值。").format(field_label))
	return flt(resolved)


def _normalize_product_uom_migration_new_prices(value):
	rows = _coerce_json_value(value, [])
	if not isinstance(rows, list):
		frappe.throw(_("新增价格格式不正确。"))
	result = []
	for index, row in enumerate(rows, start=1):
		if not isinstance(row, dict):
			frappe.throw(_("第 {0} 条新增价格必须是对象。").format(index))
		price_list = _normalize_text(row.get("price_list"))
		target_uom = _normalize_text(row.get("target_uom"))
		if not price_list:
			frappe.throw(_("第 {0} 条新增价格必须选择价格表。").format(index))
		if not target_uom:
			frappe.throw(_("第 {0} 条新增价格必须选择单位。").format(index))
		result.append(
			{
				"price_list": price_list,
				"currency": _normalize_currency(row.get("currency")),
				"rate": _normalize_product_uom_migration_price_rate(
					row.get("rate"),
					field_label=_("第 {0} 条新增价格金额").format(index),
				),
				"target_uom": target_uom,
			}
		)
	return result


def _build_product_uom_migration_price_plan(*, source_prices, price_mappings, new_prices):
	price_by_name = {row["name"]: row for row in source_prices}
	planned_prices = []
	for source_name, mapping in price_mappings.items():
		if mapping["action"] == "skip":
			continue
		price_row = price_by_name[source_name]
		planned_prices.append(
			{
				"action": mapping["action"],
				"currency": price_row["currency"],
				"price_list": price_row["price_list"],
				"rate": price_row["rate"] if mapping["action"] == "copy" else mapping["target_rate"],
				"source_name": source_name,
				"target_uom": mapping["target_uom"],
			}
		)
	planned_prices.extend(
		{
			"action": "new",
			"source_name": None,
			**price,
		}
		for price in new_prices
	)

	seen_price_keys = set()
	for price in planned_prices:
		if not frappe.db.exists("Price List", price["price_list"]):
			frappe.throw(_("价格表 {0} 不存在。").format(price["price_list"]))
		key = (price["price_list"], price["currency"] or "", price["target_uom"])
		if key in seen_price_keys:
			frappe.throw(
				_("新商品价格计划存在重复：{0} / {1} / {2}。").format(
					price["price_list"], price["currency"] or _("默认币种"), price["target_uom"]
				)
			)
		seen_price_keys.add(key)
	return planned_prices


def _validate_business_uom_conversion_map(stock_uom, uom_conversions):
	resolved_stock_uom, conversion_map = _build_item_uom_conversion_map(
		stock_uom=stock_uom,
		uom_conversions=uom_conversions,
	)
	if not resolved_stock_uom or resolved_stock_uom not in conversion_map:
		frappe.throw(_("新商品必须配置正确的库存基准单位和完整换算表。"))
	for uom in conversion_map:
		if not cint(frappe.db.get_value("UOM", uom, BUSINESS_SELECTABLE_UOM_FIELD) or 0):
			frappe.throw(_("单位 {0} 不是日常业务可选单位，不能用于本次迁移。").format(uom))
	return resolved_stock_uom, conversion_map


def _build_product_uom_correction_snapshot(item, assessment):
	return {
		"item_code": item.name,
		"item_name": item.item_name,
		"modified": str(item.modified),
		"disabled": bool(cint(item.disabled)),
		"stock_uom": item.stock_uom,
		"wholesale_default_uom": _extract_mode_default_uoms(item)["wholesale_default_uom"],
		"retail_default_uom": _extract_mode_default_uoms(item)["retail_default_uom"],
		"uom_conversions": assessment.get("source", {}).get("uom_conversions", []),
		"prices": assessment.get("prices", []),
		"barcodes": assessment.get("barcodes", []),
	}


def _execute_in_place_product_uom_correction(
	*,
	source,
	assessment,
	resolved_stock_uom,
	conversion_map,
	wholesale_default_uom,
	retail_default_uom,
	price_mappings,
	planned_prices,
	barcode_mappings,
	request_id,
	reason,
	before_snapshot,
):
	if not assessment.get("strategies", {}).get("in_place", {}).get("available"):
		frappe.throw(_("当前商品不满足原地纠正条件，请重新评估处理策略。"))
	if not _normalize_text(reason):
		frappe.throw(_("原地纠正必须填写业务原因。"))

	if price_mappings:
		require_doctype_permission("Item Price", "write")
	for source_name, mapping in barcode_mappings.items():
		if mapping["action"] == "keep":
			barcode = next((row for row in assessment["barcodes"] if row["name"] == source_name), None)
			if barcode and _normalize_text(barcode.get("uom")) not in conversion_map:
				frappe.throw(_("条码 {0} 的旧单位不在新换算表中，必须改绑新单位。").format(barcode.get("barcode")))

	source_modified_before = source.modified
	source.stock_uom = resolved_stock_uom
	for mode, value in (("wholesale", wholesale_default_uom), ("retail", retail_default_uom)):
		fieldname = _get_item_mode_default_uom_field(mode)
		if fieldname:
			setattr(source, fieldname, value)
	_apply_item_uom_updates(
		item=source,
		stock_uom=resolved_stock_uom,
		uom_conversions=[
			{"uom": uom, "conversion_factor": factor}
			for uom, factor in conversion_map.items()
		],
	)
	for row in list(getattr(source, "barcodes", []) or []):
		mapping = barcode_mappings.get(getattr(row, "name", None))
		if mapping and mapping["action"] == "move":
			row.uom = mapping["target_uom"]
	source.save()

	planned_by_source = {row["source_name"]: row for row in planned_prices if row.get("source_name")}
	updated_price_names = []
	expired_price_names = []
	created_price_names = []
	for source_name, mapping in price_mappings.items():
		price_doc = require_document_permission("Item Price", source_name, "write")
		if mapping["action"] == "skip":
			price_doc.valid_upto = add_days(nowdate(), -1)
			price_doc.save()
			expired_price_names.append(price_doc.name)
			continue
		plan = planned_by_source[source_name]
		price_doc.price_list_rate = plan["rate"]
		price_doc.uom = plan["target_uom"]
		price_doc.currency = plan["currency"]
		price_doc.valid_upto = None
		price_doc.save()
		updated_price_names.append(price_doc.name)
	for price in planned_prices:
		if price.get("source_name"):
			continue
		created_price = _upsert_item_price(
			item_code=source.name,
			rate=price["rate"],
			price_list=price["price_list"],
			currency=price["currency"],
			uom=price["target_uom"],
		)
		created_price_names.append(created_price.name)

	source.reload()
	corrected_item = _build_product_detail_payload(source)
	correction_name = record_product_correction(
		source_item=source.name,
		target_item=source.name,
		correction_type="in_place",
		reason=reason,
		source_modified_before=source_modified_before,
		target_modified_after=source.modified,
		before_snapshot=before_snapshot,
		after_snapshot={
			"item": corrected_item,
			"updated_price_names": updated_price_names,
			"expired_price_names": expired_price_names,
			"created_price_names": created_price_names,
		},
		metadata={"history_preserved": True},
		request_id=request_id,
	)
	return {
		"status": "success",
		"message": _("商品单位已在原编码上完成受控纠正，历史库存流水保持不变。"),
		"data": {
			"strategy": "in_place",
			"correction_name": correction_name,
			"source_item_code": source.name,
			"source_disabled": False,
			"new_item": corrected_item,
			"corrected_item": corrected_item,
			"alternative": None,
			"copied_price_names": updated_price_names,
			"created_price_names": created_price_names,
			"expired_price_names": expired_price_names,
			"moved_barcodes": [
				row["barcode"]
				for row in assessment["barcodes"]
				if barcode_mappings[row["name"]]["action"] == "move"
			],
			"history_preserved": True,
		},
	}


def _normalize_product_uom_inventory_mappings(value, *, assessment):
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except Exception:
			frappe.throw(_("库存转换明细格式无效。"))
	positive_bins = {
		row["warehouse"]: row
		for row in assessment.get("inventory", {}).get("bins", [])
		if flt(row.get("actual_qty") or 0) > 0.000001
	}
	if not positive_bins:
		if value not in (None, "", []):
			frappe.throw(_("源商品当前没有正库存，不应提交库存转换明细。"))
		return []
	if not isinstance(value, list):
		frappe.throw(_("库存转换明细必须是数组。"))

	resolved = []
	seen = set()
	for raw in value:
		if not isinstance(raw, dict):
			frappe.throw(_("库存转换明细行格式无效。"))
		warehouse = _normalize_text(raw.get("warehouse"))
		if not warehouse or warehouse not in positive_bins:
			frappe.throw(_("库存转换仓库 {0} 不在当前正库存仓库中。").format(warehouse or _("空")))
		if warehouse in seen:
			frappe.throw(_("库存转换仓库 {0} 不能重复。").format(warehouse))
		seen.add(warehouse)
		bin_row = positive_bins[warehouse]
		expected_source_qty = flt(bin_row.get("actual_qty") or 0)
		client_source_qty = flt(raw.get("source_qty") or 0)
		if abs(client_source_qty - expected_source_qty) > 0.000001:
			frappe.throw(_("仓库 {0} 的源库存已变化，请重新评估后再执行。").format(warehouse))
		try:
			target_decimal = Decimal(str(raw.get("target_qty")))
		except (InvalidOperation, TypeError, ValueError):
			frappe.throw(_("仓库 {0} 的继任商品数量无效。").format(warehouse))
		if not target_decimal.is_finite() or target_decimal <= 0:
			frappe.throw(_("仓库 {0} 的继任商品数量必须大于 0。").format(warehouse))
		company = _normalize_text(bin_row.get("company"))
		if not company:
			frappe.throw(_("仓库 {0} 未绑定公司，不能执行库存转换。").format(warehouse))
		ensure_warehouse_access(warehouse, company=company, applicable_for="Stock Entry")
		validate_transaction_warehouse(warehouse, company=company)
		resolved.append(
			{
				"warehouse": warehouse,
				"company": company,
				"source_qty": expected_source_qty,
				"target_qty": flt(target_decimal),
				"source_valuation_rate": flt(bin_row.get("valuation_rate") or 0),
				"source_stock_value": flt(bin_row.get("stock_value") or 0),
			}
		)
	missing = sorted(set(positive_bins) - seen)
	if missing:
		frappe.throw(_("以下正库存仓库尚未确认继任商品数量：{0}").format("、".join(missing)))
	return resolved


def _create_product_uom_repack_entries(*, source_item, target_item, inventory_mappings, reason):
	entries = []
	for mapping in inventory_mappings:
		allow_zero_target_valuation = abs(flt(mapping.get("source_stock_value") or 0)) <= 0.000001
		stock_entry = frappe.new_doc("Stock Entry")
		stock_entry.stock_entry_type = "Repack"
		stock_entry.purpose = "Repack"
		stock_entry.company = mapping["company"]
		stock_entry.remarks = _("商品单位纠正：{0}").format(_normalize_text(reason) or source_item.name)
		stock_entry.append(
			"items",
			{
				"item_code": source_item.name,
				"qty": mapping["source_qty"],
				"s_warehouse": mapping["warehouse"],
				"allow_zero_valuation_rate": 1,
			},
		)
		target_row = {
			"item_code": target_item.name,
			"qty": mapping["target_qty"],
			"t_warehouse": mapping["warehouse"],
			"is_finished_item": 1,
		}
		if allow_zero_target_valuation:
			target_row["allow_zero_valuation_rate"] = 1
		stock_entry.append("items", target_row)
		stock_entry.insert()
		stock_entry.submit()
		entries.append(
			{
				"name": stock_entry.name,
				"company": mapping["company"],
				"warehouse": mapping["warehouse"],
				"source_qty": mapping["source_qty"],
				"target_qty": mapping["target_qty"],
				"source_valuation_rate": flt(mapping.get("source_valuation_rate") or 0),
				"source_stock_value": flt(mapping.get("source_stock_value") or 0),
				"allowed_zero_target_valuation": allow_zero_target_valuation,
			}
		)
	return entries


def execute_product_uom_migration_v1(item_code: str, **kwargs):
	_require_product_uom_migration_manager()
	item_code = _normalize_text(item_code)
	if not item_code:
		frappe.throw(_("商品编码不能为空。"))
	strategy = _normalize_text(kwargs.get("strategy")).lower() or "replacement"
	if strategy not in {"in_place", "replacement"}:
		frappe.throw(_("商品单位纠正策略不正确。"))
	if not cint(kwargs.get("confirm_history_preserved")):
		frappe.throw(_("必须确认不修改历史库存流水。"))
	if strategy == "replacement" and not cint(kwargs.get("confirm_disable_source")):
		frappe.throw(_("创建替代商品前必须确认停用源商品。"))
	if strategy == "in_place" and not cint(kwargs.get("confirm_in_place_correction")):
		frappe.throw(_("原地纠正前必须确认保留原商品编码。"))

	request_id = get_current_request_id(kwargs.get("request_id"))
	if not request_id:
		frappe.throw(_("商品单位迁移必须携带 Idempotency-Key。"))

	def _execute_migration():
		source = require_document_permission("Item", item_code, "write")
		if strategy == "replacement":
			require_doctype_permission("Item", "create")
			require_doctype_permission("Item Alternative", "create")

		frappe.db.sql("SELECT name FROM `tabItem` WHERE name = %s FOR UPDATE", (item_code,))
		frappe.db.sql("SELECT name FROM `tabBin` WHERE item_code = %s FOR UPDATE", (item_code,))
		source.reload()
		expected_modified = _normalize_text(kwargs.get("source_modified"))
		if not expected_modified or expected_modified != str(source.modified):
			frappe.throw(_("源商品在评估后已发生变化，请重新评估后再执行迁移。"))

		assessment = _build_product_uom_migration_assessment(source)
		blocker_codes = {row["code"] for row in assessment["blockers"]}
		inventory_conversion_allowed = (
			strategy == "replacement"
			and assessment.get("can_execute_with_inventory_conversion")
			and blocker_codes == {"NON_ZERO_STOCK"}
		)
		if assessment["blockers"] and not inventory_conversion_allowed:
			frappe.throw("\n".join(row["message"] for row in assessment["blockers"]))
		if inventory_conversion_allowed and not cint(kwargs.get("confirm_inventory_conversion")):
			frappe.throw(_("必须确认按逐仓明细通过 Repack 转移全部现有库存。"))
		before_snapshot = _build_product_uom_correction_snapshot(source, assessment)

		resolved_stock_uom, conversion_map = _validate_business_uom_conversion_map(
			kwargs.get("stock_uom"),
			kwargs.get("uom_conversions"),
		)
		inventory_mappings = (
			_normalize_product_uom_inventory_mappings(
				kwargs.get("inventory_mappings"),
				assessment=assessment,
			)
			if inventory_conversion_allowed
			else []
		)
		if inventory_mappings:
			require_doctype_permission("Stock Entry", "create")

		price_mappings = _normalize_product_uom_migration_mappings(
			kwargs.get("price_mappings"),
			source_rows=assessment["prices"],
			mapping_kind="price",
		)
		new_prices = _normalize_product_uom_migration_new_prices(kwargs.get("new_prices"))
		barcode_mappings = _normalize_product_uom_migration_mappings(
			kwargs.get("barcode_mappings"),
			source_rows=assessment["barcodes"],
			mapping_kind="barcode",
		)
		for mapping in [*price_mappings.values(), *barcode_mappings.values()]:
			if mapping["action"] in {"copy", "manual", "move"} and mapping["target_uom"] not in conversion_map:
				frappe.throw(_("映射单位 {0} 不在新商品换算表中。").format(mapping["target_uom"] or _("空")))
		for price in new_prices:
			if price["target_uom"] not in conversion_map:
				frappe.throw(_("新增价格单位 {0} 不在新商品换算表中。").format(price["target_uom"]))

		wholesale_default_uom = _normalize_text(kwargs.get("wholesale_default_uom")) or None
		retail_default_uom = _normalize_text(kwargs.get("retail_default_uom")) or None
		for label, default_uom in (
			(_("批发默认单位"), wholesale_default_uom),
			(_("零售默认单位"), retail_default_uom),
		):
			if default_uom and default_uom not in conversion_map:
				frappe.throw(_("{0} {1} 不在新商品换算表中。").format(label, default_uom))

		planned_prices = _build_product_uom_migration_price_plan(
			source_prices=assessment["prices"],
			price_mappings=price_mappings,
			new_prices=new_prices,
		)
		if (strategy == "replacement" and planned_prices) or (strategy == "in_place" and new_prices):
			require_doctype_permission("Item Price", "create")
		if strategy == "in_place":
			return _execute_in_place_product_uom_correction(
				source=source,
				assessment=assessment,
				resolved_stock_uom=resolved_stock_uom,
				conversion_map=conversion_map,
				wholesale_default_uom=wholesale_default_uom,
				retail_default_uom=retail_default_uom,
				price_mappings=price_mappings,
				planned_prices=planned_prices,
				barcode_mappings=barcode_mappings,
				request_id=request_id,
				reason=kwargs.get("correction_reason"),
				before_snapshot=before_snapshot,
			)

		new_item_name = _normalize_text(kwargs.get("new_item_name")) or source.item_name
		new_item_code = _build_item_code(new_item_name, kwargs.get("new_item_code"))

		barcode_by_name = {row["name"]: row for row in assessment["barcodes"]}
		moved_barcode_names = [
			name for name, mapping in barcode_mappings.items() if mapping["action"] == "move"
		]
		for row in list(getattr(source, "barcodes", []) or []):
			if getattr(row, "name", None) in moved_barcode_names:
				source.remove(row)
		source.allow_alternative_item = 1
		if moved_barcode_names:
			source.save()

		new_item = frappe.new_doc("Item")
		new_item.item_code = new_item_code
		new_item.item_name = new_item_name
		for fieldname in (
			"item_group",
			"brand",
			"description",
			"image",
			"is_stock_item",
			"is_sales_item",
			"is_purchase_item",
			"include_item_in_manufacturing",
			"has_batch_no",
			"has_serial_no",
		):
			setattr(new_item, fieldname, getattr(source, fieldname, None))
		new_item.stock_uom = resolved_stock_uom
		new_item.allow_alternative_item = 1
		new_item.disabled = 0
		nickname_field = _get_item_nickname_field()
		if nickname_field:
			setattr(new_item, nickname_field, getattr(source, nickname_field, None))
		specification_field = _get_item_specification_field()
		if specification_field:
			setattr(new_item, specification_field, getattr(source, specification_field, None))
		for mode, value in (
			("wholesale", wholesale_default_uom),
			("retail", retail_default_uom),
		):
			fieldname = _get_item_mode_default_uom_field(mode)
			if fieldname:
				setattr(new_item, fieldname, value)
		_apply_item_uom_updates(
			item=new_item,
			stock_uom=resolved_stock_uom,
			uom_conversions=[
				{"uom": uom, "conversion_factor": factor}
				for uom, factor in conversion_map.items()
			],
		)
		for source_name, mapping in barcode_mappings.items():
			if mapping["action"] != "move":
				continue
			barcode_row = barcode_by_name[source_name]
			new_item.append(
				"barcodes",
				{
					"barcode": barcode_row["barcode"],
					"uom": mapping["target_uom"],
				},
			)
		new_item.insert()

		repack_entries = _create_product_uom_repack_entries(
			source_item=source,
			target_item=new_item,
			inventory_mappings=inventory_mappings,
			reason=kwargs.get("correction_reason"),
		)
		if inventory_mappings:
			remaining_nonzero_bins = [
				row
				for row in _get_product_uom_migration_bins(source.name)
				if abs(flt(row.get("actual_qty") or 0)) > 0.000001
			]
			if remaining_nonzero_bins:
				frappe.throw(_("库存转换后源商品库存未完全归零，事务已回滚，请重新评估。"))

		source.disabled = 1
		source.save()

		copied_price_names = []
		created_price_names = []
		for price in planned_prices:
			created_price = _upsert_item_price(
				item_code=new_item.name,
				rate=price["rate"],
				price_list=price["price_list"],
				currency=price["currency"],
				uom=price["target_uom"],
			)
			created_price_names.append(created_price.name)
			if price["action"] == "copy":
				copied_price_names.append(created_price.name)

		alternative = frappe.new_doc("Item Alternative")
		alternative.item_code = source.name
		alternative.alternative_item_code = new_item.name
		alternative.two_way = 0
		alternative.insert()

		new_item.reload()
		source.reload()
		correction_name = record_product_correction(
			source_item=source.name,
			target_item=new_item.name,
			correction_type="replacement",
			reason=kwargs.get("correction_reason") or _("库存基准单位纠正"),
			source_modified_before=before_snapshot.get("modified"),
			target_modified_after=new_item.modified,
			before_snapshot=before_snapshot,
			after_snapshot={
				"source_disabled": bool(cint(source.disabled)),
				"new_item": _build_product_detail_payload(new_item),
				"alternative": alternative.name,
				"created_price_names": created_price_names,
				"repack_entries": repack_entries,
			},
			metadata={
				"history_preserved": True,
				"inventory_converted": bool(repack_entries),
			},
			request_id=request_id,
		)
		return {
			"status": "success",
			"message": _("商品单位迁移已完成，源商品已停用，历史库存流水保持不变。"),
			"data": {
				"strategy": "replacement",
				"correction_name": correction_name,
				"source_item_code": source.name,
				"source_disabled": bool(cint(source.disabled)),
				"new_item": _build_product_detail_payload(new_item),
				"alternative": {
					"name": alternative.name,
					"item_code": source.name,
					"alternative_item_code": new_item.name,
				},
				"copied_price_names": copied_price_names,
				"created_price_names": created_price_names,
				"repack_entries": repack_entries,
				"moved_barcodes": [
					barcode_by_name[name]["barcode"] for name in moved_barcode_names
				],
				"history_preserved": True,
			},
		}

	return run_idempotent("execute_product_uom_migration_v1", request_id, _execute_migration)


def search_product_v2(
	search_key: str,
	price_list: str = "Standard Selling",
	currency: str | None = None,
	warehouse: str | None = None,
	company: str | None = None,
	limit: int = 20,
	disabled: int | None = 0,
	item_group: str | None = None,
	brand: str | None = None,
	search_fields=None,
	sort_by: str = "relevance",
	sort_order: str = "asc",
	in_stock_only: bool = False,
	item_context: str | None = "sales",
):
	require_doctype_permission("Item", "read")
	search_key = _normalize_text(search_key)
	limit = _normalize_limit(limit)
	item_context = _normalize_item_context(item_context)
	price_list = _normalize_text(price_list) or "Standard Selling"
	currency = _normalize_currency(currency)
	warehouse = _normalize_text(warehouse) or None
	company = _normalize_text(company) or None
	item_group = _normalize_text(item_group) or None
	brand = _normalize_text(brand) or None
	search_fields = _normalize_search_fields(search_fields)
	sort_by = _normalize_text(sort_by).lower() or "relevance"
	sort_order = "desc" if _normalize_text(sort_order).lower() == "desc" else "asc"
	in_stock_only = bool(cint(in_stock_only))
	disabled = cint(disabled) if disabled is not None else None

	if search_key:
		item_codes = _search_item_codes(
			search_key,
			search_fields=search_fields,
			limit=limit * 3,
			item_context=item_context,
			disabled=disabled,
			item_group=item_group,
			brand=brand,
		)
	else:
		item_codes = _list_item_codes_by_filters(
			limit=limit * 3,
			item_context=item_context,
			disabled=disabled,
			item_group=item_group,
			brand=brand,
		)
	if not item_codes:
		return {"status": "success", "data": [], "message": _("未找到匹配商品")}

	items_data = _get_item_data_map(
		item_codes,
		item_context=item_context,
		disabled=disabled,
		item_group=item_group,
		brand=brand,
	)
	price_map = _get_price_map(item_codes, price_list=price_list, currency=currency)
	uom_map = _get_uom_map(item_codes)
	stock_company = _resolve_stock_company_scope(warehouse, company)
	qty_map = _get_qty_map(item_codes, warehouse=warehouse, company=company)
	total_qty_map = _get_qty_map(item_codes, warehouse=None, company=stock_company)
	warehouse_stock_map = _get_warehouse_stock_detail_map(item_codes, company=stock_company)
	global_total_qty_map = _get_qty_map(item_codes, warehouse=None, company=None)
	global_warehouse_stock_map = _get_warehouse_stock_detail_map(item_codes, company=None)
	selling_price_map = _get_multi_price_map(
		item_codes,
		price_lists=list(DEFAULT_SELLING_PRICE_LISTS),
		currency=currency,
	)
	buying_price_map = _get_multi_price_map(
		item_codes,
		price_lists=list(DEFAULT_BUYING_PRICE_LISTS),
		currency=currency,
	)
	uom_names = []
	for code in item_codes:
		for name in _collect_item_uom_names(item=items_data.get(code), all_uoms=uom_map.get(code, [])):
			if name not in uom_names:
				uom_names.append(name)
	uom_display_map = build_uom_display_map(uom_names)

	results = []
	for code in item_codes:
		item = items_data.get(code)
		if not item:
			continue
		if disabled is not None and cint(getattr(item, "disabled", 0)) != disabled:
			continue

		qty = flt(qty_map.get(code, 0))
		if in_stock_only and qty <= 0:
			continue

		results.append(
			{
				"item_code": item.name,
				"item_name": item.item_name,
				"item_group": item.item_group,
				"brand": getattr(item, "brand", None),
				"uom": item.stock_uom,
				"uom_display": uom_display_map.get(_normalize_text(item.stock_uom)),
				"all_uoms": _decorate_uom_rows_with_display(uom_map.get(code, []), uom_display_map),
				"qty": qty,
				"total_qty": flt(total_qty_map.get(code, 0) or 0),
				"warehouse_stock_details": warehouse_stock_map.get(code, []),
				"global_total_qty": flt(global_total_qty_map.get(code, 0) or 0),
				"global_warehouse_stock_details": global_warehouse_stock_map.get(code, []),
				"price": flt(price_map.get(code, 0) or 0),
				"image": item.image,
				"nickname": _extract_item_nickname(item),
				"specification": _extract_item_specification(item),
				"description": item.description,
				"disabled": cint(getattr(item, "disabled", 0)),
				"is_sales_item": cint(getattr(item, "is_sales_item", 0)),
				"is_purchase_item": cint(getattr(item, "is_purchase_item", 0)),
				"price_summary": _build_price_summary(
					item,
					current_price_list=price_list,
					current_rate=flt(price_map.get(code, 0) or 0),
					selling_price_map=selling_price_map.get(code, {}),
					buying_price_map=buying_price_map.get(code, {}),
				),
				"wholesale_default_uom": _extract_mode_default_uoms(item)["wholesale_default_uom"],
				"wholesale_default_uom_display": uom_display_map.get(
					_normalize_text(_extract_mode_default_uoms(item)["wholesale_default_uom"])
				),
				"retail_default_uom": _extract_mode_default_uoms(item)["retail_default_uom"],
				"retail_default_uom_display": uom_display_map.get(
					_normalize_text(_extract_mode_default_uoms(item)["retail_default_uom"])
				),
				"sales_profiles": _build_sales_profiles_with_display(item, uom_display_map),
				"creation": item.creation,
				"modified": item.modified,
			}
		)

	results = _sort_search_results(results, sort_by=sort_by, sort_order=sort_order, item_code_order=item_codes)[:limit]

	return {
		"status": "success",
		"data": results,
		"filters": {
			"price_list": price_list,
			"currency": currency,
			"warehouse": warehouse,
			"company": company,
			"item_group": item_group,
			"brand": brand,
			"limit": limit,
			"search_fields": search_fields,
			"sort_by": sort_by,
			"sort_order": sort_order,
			"in_stock_only": in_stock_only,
			"disabled": disabled,
			"item_context": item_context,
		},
	}


def _coerce_json_value(value, default):
	if value in (None, ""):
		return default
	if isinstance(value, str):
		return frappe.parse_json(value)
	return value


def _coerce_price_entries(value):
	entries = _coerce_json_value(value, [])
	normalized = []
	for row in entries or []:
		if not isinstance(row, dict):
			continue
		price_list = _normalize_text(row.get("price_list"))
		rate = row.get("rate")
		if not price_list or rate in (None, ""):
			continue
		normalized.append(
			{
				"price_list": price_list,
				"rate": flt(rate),
				"currency": _normalize_currency(row.get("currency")),
				"uom": _normalize_text(row.get("uom")) or None,
			}
		)
	return normalized


def _coerce_uom_conversion_entries(value):
	entries = _coerce_json_value(value, [])
	normalized = []
	seen = set()
	for row in entries or []:
		if not isinstance(row, dict):
			continue
		uom = _normalize_text(row.get("uom"))
		conversion_factor = row.get("conversion_factor")
		if not uom or uom in seen:
			continue
		if conversion_factor in (None, ""):
			continue
		factor = flt(conversion_factor)
		if factor <= 0:
			frappe.throw(_("单位 {0} 的换算系数必须大于 0。").format(uom))
		seen.add(uom)
		normalized.append(
			{
				"uom": _resolve_default_uom(uom),
				"conversion_factor": factor,
			}
		)
	return normalized


def _apply_item_uom_updates(
	*,
	item,
	stock_uom=None,
	uom_conversions=None,
):
	resolved_stock_uom = None
	if stock_uom is not None:
		resolved_stock_uom = _resolve_default_uom(stock_uom)
		item.stock_uom = resolved_stock_uom

	parsed_conversions = None
	if uom_conversions is not None:
		parsed_conversions = _coerce_uom_conversion_entries(uom_conversions)

	if resolved_stock_uom is None:
		resolved_stock_uom = _resolve_default_uom(getattr(item, "stock_uom", None))

	if parsed_conversions is None:
		return

	final_rows = [{"uom": resolved_stock_uom, "conversion_factor": 1}]
	for row in parsed_conversions:
		if row["uom"] == resolved_stock_uom:
			continue
		final_rows.append(row)

	item.set("uoms", [])
	for row in final_rows:
		item.append(
			"uoms",
			{
				"uom": row["uom"],
				"conversion_factor": row["conversion_factor"],
			},
		)


def _apply_item_price_updates(
	*,
	item,
	standard_rate,
	price_list: str | None,
	currency: str | None,
	selling_prices,
	buying_prices,
):
	default_price_list = _normalize_text(price_list) or "Standard Selling"
	default_currency = _normalize_currency(currency)

	if standard_rate not in (None, ""):
		_upsert_item_price(
			item_code=item.name,
			rate=flt(standard_rate),
			price_list=default_price_list,
			currency=default_currency,
			uom=_resolve_item_price_uom(item, None, default_price_list),
		)

	for entry in _coerce_price_entries(selling_prices):
		_upsert_item_price(
			item_code=item.name,
			rate=entry["rate"],
			price_list=entry["price_list"],
			currency=entry["currency"] or default_currency,
			uom=_resolve_item_price_uom(item, entry.get("uom"), entry["price_list"]),
		)

	for entry in _coerce_price_entries(buying_prices):
		_upsert_item_price(
			item_code=item.name,
			rate=entry["rate"],
			price_list=entry["price_list"],
			currency=entry["currency"] or default_currency,
			uom=_resolve_item_price_uom(item, entry.get("uom"), entry["price_list"]),
		)


def _resolve_item_price_uom(item, requested_uom: str | None, price_list: str):
	stock_uom, conversion_map = _build_item_uom_conversion_map(item=item)
	mode_default_uoms = _extract_mode_default_uoms(item)
	default_uom = stock_uom
	if price_list == "Wholesale":
		default_uom = mode_default_uoms.get("wholesale_default_uom") or stock_uom
	elif price_list == "Retail":
		default_uom = mode_default_uoms.get("retail_default_uom") or stock_uom
	resolved_uom = _normalize_text(requested_uom) or default_uom
	if not resolved_uom or resolved_uom not in conversion_map:
		frappe.throw(_("价格单位 {0} 未配置在商品 {1} 的单位换算表中。").format(resolved_uom, item.name))
	return resolved_uom


def _resolve_item_barcode_uom(item, requested_uom: str | None):
	stock_uom, conversion_map = _build_item_uom_conversion_map(item=item)
	resolved_uom = _normalize_text(requested_uom) or stock_uom
	if not resolved_uom or resolved_uom not in conversion_map:
		frappe.throw(_("条码单位 {0} 未配置在商品 {1} 的单位换算表中。").format(resolved_uom, item.name))
	return resolved_uom


def _resolve_default_warehouse(warehouse: str | None, default_warehouse: str | None = None):
	for candidate in (
		warehouse,
		default_warehouse,
		frappe.defaults.get_user_default("warehouse"),
		frappe.defaults.get_user_default("default_warehouse"),
	):
		normalized = (candidate or "").strip()
		if normalized:
			return normalized

	frappe.throw(_("请先选择仓库，或在当前用户默认值中配置 warehouse。"))


def _resolve_default_uom(stock_uom: str | None = None):
	normalized = (stock_uom or "").strip()
	if normalized:
		if not frappe.db.exists("UOM", normalized):
			frappe.throw(_("单位 {0} 不存在。").format(normalized))
		return normalized

	default_uom = "Nos"
	if frappe.db.exists("UOM", default_uom):
		return default_uom

	row = frappe.get_all("UOM", fields=["name"], limit_page_length=1)
	if row:
		return row[0].name

	frappe.throw(_("系统中没有可用单位，请先创建 UOM。"))


def _resolve_default_item_group(item_group: str | None = None):
	normalized = (item_group or "").strip()
	if normalized:
		if not frappe.db.exists("Item Group", normalized):
			frappe.throw(_("商品组 {0} 不存在。").format(normalized))
		return normalized

	if frappe.db.exists("Item Group", "All Item Groups"):
		return "All Item Groups"

	row = frappe.get_all(
		"Item Group",
		fields=["name"],
		filters={"is_group": 0},
		order_by="lft asc",
		limit_page_length=1,
	)
	if row:
		return row[0].name

	frappe.throw(_("系统中没有可用商品组，请先创建叶子商品组。"))


def _resolve_company_from_warehouse(warehouse: str):
	company = frappe.db.get_value("Warehouse", warehouse, "company")
	if not company:
		frappe.throw(_("仓库 {0} 不存在，或未绑定公司。").format(warehouse))
	return company


def _build_item_code(item_name: str, item_code: str | None = None):
	normalized = (item_code or "").strip()
	if normalized:
		if frappe.db.exists("Item", normalized):
			frappe.throw(_("商品编码 {0} 已存在。").format(normalized))
		return normalized

	base_code = frappe.scrub(item_name).replace("_", "-").upper() or "ITEM"
	candidate = base_code
	index = 2
	while frappe.db.exists("Item", candidate):
		candidate = f"{base_code}-{index}"
		index += 1
	return candidate


def _upsert_item_price(
	item_code: str,
	rate: float,
	price_list: str,
	currency: str | None = None,
	uom: str | None = None,
):
	if rate < 0:
		frappe.throw(_("销售价不能为负数。"))

	filters = {"item_code": item_code, "price_list": price_list}
	if currency:
		filters["currency"] = currency
	if uom:
		filters["uom"] = uom

	existing_name = frappe.db.get_value("Item Price", filters, "name")
	if existing_name:
		item_price = frappe.get_doc("Item Price", existing_name)
		item_price.price_list_rate = rate
		if uom:
			item_price.uom = uom
		item_price.save()
		return item_price

	item_price = frappe.new_doc("Item Price")
	item_price.item_code = item_code
	item_price.price_list = price_list
	item_price.price_list_rate = rate
	if uom:
		item_price.uom = uom
	if currency:
		item_price.currency = currency
	item_price.insert()
	return item_price


def _create_stock_entry(
	item_code: str,
	warehouse: str,
	qty: float,
	company: str,
	valuation_rate: float,
	posting_date: str | None = None,
):
	if qty <= 0:
		return None

	stock_entry = frappe.new_doc("Stock Entry")
	stock_entry.stock_entry_type = "Material Receipt"
	stock_entry.purpose = "Material Receipt"
	stock_entry.company = company
	if posting_date:
		stock_entry.posting_date = posting_date

	stock_entry.append(
		"items",
		{
			"item_code": item_code,
			"qty": qty,
			"t_warehouse": warehouse,
			"basic_rate": valuation_rate,
			"valuation_rate": valuation_rate,
			"allow_zero_valuation_rate": 1,
		},
	)
	stock_entry.insert()
	stock_entry.submit()
	return stock_entry


def _create_stock_adjustment_entry(
	item_code: str,
	warehouse: str,
	qty_delta: float,
	company: str,
	valuation_rate: float,
	posting_date: str | None = None,
):
	if not qty_delta:
		return None

	stock_entry = frappe.new_doc("Stock Entry")
	is_receipt = qty_delta > 0
	stock_entry.stock_entry_type = "Material Receipt" if is_receipt else "Material Issue"
	stock_entry.purpose = "Material Receipt" if is_receipt else "Material Issue"
	stock_entry.company = company
	if posting_date:
		stock_entry.posting_date = posting_date

	item_row = {
		"item_code": item_code,
		"qty": abs(qty_delta),
		"basic_rate": valuation_rate,
		"valuation_rate": valuation_rate,
		"allow_zero_valuation_rate": 1,
	}
	if is_receipt:
		item_row["t_warehouse"] = warehouse
	else:
		item_row["s_warehouse"] = warehouse

	stock_entry.append("items", item_row)
	stock_entry.insert()
	stock_entry.submit()
	return stock_entry


def _ensure_zero_stock_bin(item_code: str, warehouse: str):
	from erpnext.stock.utils import get_bin

	return get_bin(item_code, warehouse)


def _bin_exists(item_code: str, warehouse: str):
	return bool(frappe.db.exists("Bin", {"item_code": item_code, "warehouse": warehouse}))


def update_product_v2(
	item_code: str,
	**kwargs,
):
	item_code = _normalize_text(item_code)
	if not item_code:
		frappe.throw(_("商品编码不能为空。"))

	request_id = kwargs.get("request_id")

	def _update_product():
		item = require_document_permission("Item", item_code, "write")
		_require_current_document_version(
			item,
			kwargs.get("item_modified"),
			message=_("商品资料已被其他人修改，请刷新最新资料后重新编辑。"),
		)
		previous_image_url = _normalize_text(getattr(item, "image", None)) or None
		image_change_requested = "image" in kwargs
		next_image_url = _normalize_text(kwargs.get("image")) or None
		nickname_field = _get_item_nickname_field()
		specification_field = _get_item_specification_field()

		item_name = kwargs.get("item_name")
		if item_name is not None:
			item.item_name = _normalize_text(item_name)

		_apply_item_uom_updates(
			item=item,
			stock_uom=(kwargs.get("stock_uom") or kwargs.get("uom")) if "stock_uom" in kwargs or "uom" in kwargs else None,
			uom_conversions=kwargs.get("uom_conversions"),
		)

		item_group = kwargs.get("item_group")
		if item_group is not None:
			item.item_group = _resolve_default_item_group(item_group)

		brand = kwargs.get("brand")
		if brand is not None:
			item.brand = _normalize_text(brand)

		description = kwargs.get("description")
		if description is not None:
			item.description = _normalize_text(description)

		if image_change_requested:
			item.image = next_image_url
			if next_image_url and next_image_url != previous_image_url:
				frappe.db.after_rollback.add(
					lambda file_url=next_image_url: cleanup_temporary_item_image(file_url=file_url)
				)

		if "disabled" in kwargs and kwargs.get("disabled") is not None:
			item.disabled = cint(kwargs.get("disabled"))

		_update_primary_barcode(item, kwargs.get("barcode"))

		nickname = kwargs.get("nickname")
		if nickname is not None:
			normalized_nickname = _normalize_text(nickname)
			if nickname_field:
				setattr(item, nickname_field, normalized_nickname)
			elif description is None and normalized_nickname:
				item.description = normalized_nickname

		specification = kwargs.get("specification")
		if specification is not None and specification_field:
			setattr(item, specification_field, _normalize_text(specification))

		wholesale_default_uom = kwargs.get("wholesale_default_uom")
		if wholesale_default_uom is not None:
			fieldname = _get_item_mode_default_uom_field("wholesale")
			if fieldname:
				setattr(item, fieldname, _normalize_mode_default_uom(wholesale_default_uom))

		retail_default_uom = kwargs.get("retail_default_uom")
		if retail_default_uom is not None:
			fieldname = _get_item_mode_default_uom_field("retail")
			if fieldname:
				setattr(item, fieldname, _normalize_mode_default_uom(retail_default_uom))

		_validate_mode_default_uoms_against_stock_uom(
			item=item,
			stock_uom=(kwargs.get("stock_uom") or kwargs.get("uom")) if "stock_uom" in kwargs or "uom" in kwargs else None,
			uom_conversions=kwargs.get("uom_conversions"),
			overrides={
				"wholesale_default_uom": kwargs.get("wholesale_default_uom"),
				"retail_default_uom": kwargs.get("retail_default_uom"),
			},
		)

		item.save()
		if image_change_requested and next_image_url and next_image_url != previous_image_url:
			bind_uploaded_item_image(file_url=next_image_url, item_code=item.name)
		if image_change_requested and previous_image_url != next_image_url:
			frappe.db.after_commit.add(
				lambda old_url=previous_image_url, new_url=next_image_url: cleanup_replaced_item_image(
					item_code=item.name,
					previous_image_url=old_url,
					current_image_url=new_url,
				)
			)

		warehouse_stock_qty = kwargs.get("warehouse_stock_qty")
		resolved_warehouse = _normalize_text(kwargs.get("warehouse")) or None
		if warehouse_stock_qty not in (None, ""):
			if not resolved_warehouse:
				frappe.throw(_("调整库存时必须指定仓库。"))

			target_qty_context = resolve_item_quantity_to_stock(
				item_code=item.name,
				qty=warehouse_stock_qty,
				uom=kwargs.get("warehouse_stock_uom"),
			)
			target_qty = flt(target_qty_context["stock_qty"])
			current_qty = flt(_get_qty_map([item.name], warehouse=resolved_warehouse, company=None).get(item.name) or 0)
			qty_delta = target_qty - current_qty
			if qty_delta:
				company = _resolve_company_from_warehouse(resolved_warehouse)
				valuation_rate = flt(
					kwargs.get("valuation_rate")
					or kwargs.get("standard_rate")
					or item.valuation_rate
					or item.standard_rate
					or 0
				)
				_create_stock_adjustment_entry(
					item_code=item.name,
					warehouse=resolved_warehouse,
					qty_delta=qty_delta,
					company=company,
					valuation_rate=valuation_rate,
					posting_date=kwargs.get("posting_date"),
				)
			elif not _bin_exists(item.name, resolved_warehouse):
				_ensure_zero_stock_bin(item.name, resolved_warehouse)

		standard_rate = kwargs.get("standard_rate")
		price_list = _normalize_text(kwargs.get("price_list")) or "Standard Selling"
		currency = _normalize_currency(kwargs.get("currency"))
		_apply_item_price_updates(
			item=item,
			standard_rate=standard_rate,
			price_list=price_list,
			currency=currency,
			selling_prices=kwargs.get("selling_prices"),
			buying_prices=kwargs.get("buying_prices"),
		)

		item.reload()
		return {
			"status": "success",
			"data": _build_product_detail_payload(
				item,
				warehouse=resolved_warehouse,
				company=_normalize_text(kwargs.get("company")) or None,
				price_list=price_list,
				currency=currency,
			),
		}

	return run_idempotent("update_product_v2", request_id, _update_product)


def create_product_v2(
	item_name: str,
	**kwargs,
):
	item_name = _normalize_text(item_name)
	if not item_name:
		frappe.throw(_("商品名称不能为空。"))

	request_id = kwargs.get("request_id")

	def _create_product():
		resolved_uom = _resolve_default_uom(kwargs.get("stock_uom") or kwargs.get("uom"))
		item_group = _resolve_default_item_group(kwargs.get("item_group"))
		item_code = _build_item_code(item_name, kwargs.get("item_code"))
		barcode = _normalize_text(kwargs.get("barcode"))
		image_url = _normalize_text(kwargs.get("image")) or None
		warehouse_stock_qty = kwargs.get("warehouse_stock_qty")
		resolved_warehouse = None
		if barcode and frappe.db.exists("Item Barcode", {"barcode": barcode}):
			frappe.throw(_("条码 {0} 已存在。").format(barcode))

		item = frappe.new_doc("Item")
		item.item_code = item_code
		item.item_name = item_name
		item.item_group = item_group
		item.brand = _normalize_text(kwargs.get("brand"))
		item.stock_uom = resolved_uom
		item.is_stock_item = cint(kwargs.get("is_stock_item", 1))
		item.is_sales_item = cint(kwargs.get("is_sales_item", 1))
		item.is_purchase_item = cint(kwargs.get("is_purchase_item", 1))
		item.include_item_in_manufacturing = 0
		item.disabled = cint(kwargs.get("disabled", 0))
		if kwargs.get("description") is not None:
			item.description = kwargs.get("description")
		if kwargs.get("image") is not None:
			item.image = image_url
		if kwargs.get("nickname") is not None:
			nickname_field = _get_item_nickname_field()
			if nickname_field:
				setattr(item, nickname_field, _normalize_text(kwargs.get("nickname")))
		if kwargs.get("specification") is not None:
			specification_field = _get_item_specification_field()
			if specification_field:
				setattr(item, specification_field, _normalize_text(kwargs.get("specification")))
		for mode in ("wholesale", "retail"):
			fieldname = _get_item_mode_default_uom_field(mode)
			if fieldname:
				setattr(
					item,
					fieldname,
					_normalize_mode_default_uom(kwargs.get(f"{mode}_default_uom")),
				)
		_apply_item_uom_updates(
			item=item,
			stock_uom=resolved_uom,
			uom_conversions=kwargs.get("uom_conversions"),
		)
		_validate_mode_default_uoms_against_stock_uom(
			item=item,
			stock_uom=resolved_uom,
			uom_conversions=kwargs.get("uom_conversions"),
		)
		if kwargs.get("standard_rate") not in (None, ""):
			item.standard_rate = flt(kwargs.get("standard_rate"))
		if kwargs.get("valuation_rate") not in (None, ""):
			item.valuation_rate = flt(kwargs.get("valuation_rate"))
		if barcode:
			item.append("barcodes", {"barcode": barcode, "uom": resolved_uom})
		if image_url:
			frappe.db.after_rollback.add(lambda file_url=image_url: cleanup_temporary_item_image(file_url=file_url))
		item.insert()
		if image_url:
			bind_uploaded_item_image(file_url=image_url, item_code=item.name)

		_apply_item_price_updates(
			item=item,
			standard_rate=kwargs.get("standard_rate"),
			price_list=kwargs.get("price_list"),
			currency=kwargs.get("currency"),
			selling_prices=kwargs.get("selling_prices"),
			buying_prices=kwargs.get("buying_prices"),
		)

		if warehouse_stock_qty not in (None, "") or kwargs.get("warehouse") or kwargs.get("default_warehouse"):
			resolved_warehouse = _resolve_default_warehouse(
				_normalize_text(kwargs.get("warehouse")) or None,
				kwargs.get("default_warehouse"),
			)

		if warehouse_stock_qty not in (None, ""):
			input_qty = flt(warehouse_stock_qty)
			if input_qty < 0:
				frappe.throw(_("初始库存数量不能为负数。"))

			target_qty_context = resolve_item_quantity_to_stock(
				item_code=item.name,
				qty=warehouse_stock_qty,
				uom=kwargs.get("warehouse_stock_uom"),
			)
			target_qty = flt(target_qty_context["stock_qty"])
			if target_qty:
				company = _resolve_company_from_warehouse(resolved_warehouse)
				valuation_rate = flt(
					kwargs.get("valuation_rate")
					or kwargs.get("standard_rate")
					or item.valuation_rate
					or item.standard_rate
					or 0
				)
				_create_stock_adjustment_entry(
					item_code=item.name,
					warehouse=resolved_warehouse,
					qty_delta=target_qty,
					company=company,
					valuation_rate=valuation_rate,
					posting_date=kwargs.get("posting_date"),
				)
			else:
				_ensure_zero_stock_bin(item.name, resolved_warehouse)

		item.reload()
		return {
			"status": "success",
			"message": _("商品 {0} 已创建。").format(item.item_name),
			"data": _build_product_detail_payload(
				item,
				warehouse=resolved_warehouse,
				company=_normalize_text(kwargs.get("company")) or None,
				price_list=_normalize_text(kwargs.get("price_list")) or "Standard Selling",
				currency=_normalize_currency(kwargs.get("currency")),
			),
		}

	return run_idempotent("create_product_v2", request_id, _create_product)


def disable_product_v2(item_code: str, disabled: bool | int = True, **kwargs):
	item_code = _normalize_text(item_code)
	if not item_code:
		frappe.throw(_("商品编码不能为空。"))

	request_id = kwargs.get("request_id")

	def _disable_product():
		item = require_document_permission("Item", item_code, "write")
		_require_current_document_version(
			item,
			kwargs.get("item_modified"),
			message=_("商品资料已被其他人修改，请刷新最新资料后再启用或停用。"),
		)
		item.disabled = cint(disabled)
		item.save()
		item.reload()
		return {
			"status": "success",
			"message": _("商品 {0} 已{1}。").format(
				item.item_name,
				_("停用") if cint(disabled) else _("启用"),
			),
			"data": _build_product_detail_payload(
				item,
				warehouse=_normalize_text(kwargs.get("warehouse")) or None,
				company=_normalize_text(kwargs.get("company")) or None,
				price_list=_normalize_text(kwargs.get("price_list")) or "Standard Selling",
				currency=_normalize_currency(kwargs.get("currency")),
			),
		}

	return run_idempotent("disable_product_v2", request_id, _disable_product)


def add_product_barcode_v2(
	item_code: str,
	barcode: str,
	set_primary: bool | int = False,
	**kwargs,
):
	item_code = _normalize_text(item_code)
	barcode = _normalize_text(barcode)
	if not item_code:
		frappe.throw(_("商品编码不能为空。"))
	if not barcode:
		frappe.throw(_("条码不能为空。"))

	request_id = kwargs.get("request_id")

	def _add_product_barcode():
		item = require_document_permission("Item", item_code, "write")
		_require_current_document_version(
			item,
			kwargs.get("item_modified"),
			message=_("商品资料已被其他人修改，请刷新最新资料后重新维护条码。"),
		)
		resolved_uom = _resolve_item_barcode_uom(item, kwargs.get("uom"))
		existing_parent = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")
		if existing_parent and existing_parent != item.name:
			frappe.throw(_("条码 {0} 已存在。").format(barcode))

		existing_rows = list(getattr(item, "barcodes", []) or [])
		matched_row = None
		for row in existing_rows:
			if _normalize_text(getattr(row, "barcode", None)) == barcode:
				matched_row = row
				break
		if not matched_row:
			item.append("barcodes", {"barcode": barcode, "uom": resolved_uom})
			existing_rows = list(getattr(item, "barcodes", []) or [])
			matched_row = existing_rows[-1] if existing_rows else None
		elif kwargs.get("uom") is not None or not _normalize_text(getattr(matched_row, "uom", None)):
			matched_row.uom = resolved_uom

		if cint(set_primary) and matched_row:
			_set_barcode_row_primary(item, matched_row)

		item.save()
		item.reload()
		return {
			"status": "success",
			"data": _build_product_detail_payload(
				item,
				warehouse=_normalize_text(kwargs.get("warehouse")) or None,
				company=_normalize_text(kwargs.get("company")) or None,
				price_list=_normalize_text(kwargs.get("price_list")) or "Standard Selling",
				currency=_normalize_currency(kwargs.get("currency")),
			),
		}

	return run_idempotent("add_product_barcode_v2", request_id, _add_product_barcode)


def _set_barcode_row_primary(item, target_row):
	rows = list(getattr(item, "barcodes", []) or [])
	if not rows or target_row not in rows:
		return
	rows.remove(target_row)
	rows.insert(0, target_row)
	for index, row in enumerate(rows, start=1):
		row.idx = index
	item.barcodes = rows


def set_primary_product_barcode_v2(
	item_code: str,
	barcode: str,
	**kwargs,
):
	item_code = _normalize_text(item_code)
	barcode = _normalize_text(barcode)
	if not item_code:
		frappe.throw(_("商品编码不能为空。"))
	if not barcode:
		frappe.throw(_("条码不能为空。"))

	request_id = kwargs.get("request_id")

	def _set_primary_product_barcode():
		item = require_document_permission("Item", item_code, "write")
		_require_current_document_version(
			item,
			kwargs.get("item_modified"),
			message=_("商品资料已被其他人修改，请刷新最新资料后重新维护条码。"),
		)
		target_row = None
		for row in list(getattr(item, "barcodes", []) or []):
			if _normalize_text(getattr(row, "barcode", None)) == barcode:
				target_row = row
				break
		if not target_row:
			frappe.throw(_("商品 {0} 不存在条码 {1}。").format(item_code, barcode))

		_set_barcode_row_primary(item, target_row)
		item.save()
		item.reload()
		return {
			"status": "success",
			"data": _build_product_detail_payload(
				item,
				warehouse=_normalize_text(kwargs.get("warehouse")) or None,
				company=_normalize_text(kwargs.get("company")) or None,
				price_list=_normalize_text(kwargs.get("price_list")) or "Standard Selling",
				currency=_normalize_currency(kwargs.get("currency")),
			),
		}

	return run_idempotent("set_primary_product_barcode_v2", request_id, _set_primary_product_barcode)


def delete_product_barcode_v2(
	item_code: str,
	barcode: str,
	**kwargs,
):
	item_code = _normalize_text(item_code)
	barcode = _normalize_text(barcode)
	if not item_code:
		frappe.throw(_("商品编码不能为空。"))
	if not barcode:
		frappe.throw(_("条码不能为空。"))

	request_id = kwargs.get("request_id")

	def _delete_product_barcode():
		item = require_document_permission("Item", item_code, "write")
		_require_current_document_version(
			item,
			kwargs.get("item_modified"),
			message=_("商品资料已被其他人修改，请刷新最新资料后重新维护条码。"),
		)
		rows = list(getattr(item, "barcodes", []) or [])
		kept_rows = [row for row in rows if _normalize_text(getattr(row, "barcode", None)) != barcode]
		if len(kept_rows) == len(rows):
			frappe.throw(_("商品 {0} 不存在条码 {1}。").format(item_code, barcode))
		for index, row in enumerate(kept_rows, start=1):
			row.idx = index
		item.barcodes = kept_rows
		item.save()
		item.reload()
		return {
			"status": "success",
			"data": _build_product_detail_payload(
				item,
				warehouse=_normalize_text(kwargs.get("warehouse")) or None,
				company=_normalize_text(kwargs.get("company")) or None,
				price_list=_normalize_text(kwargs.get("price_list")) or "Standard Selling",
				currency=_normalize_currency(kwargs.get("currency")),
			),
		}

	return run_idempotent("delete_product_barcode_v2", request_id, _delete_product_barcode)


def create_product_and_stock(
	item_name: str,
	warehouse: str | None = None,
	opening_qty: float = 0,
	**kwargs,
):
	item_name = (item_name or "").strip()
	if not item_name:
		frappe.throw(_("商品名称不能为空。"))

	request_id = kwargs.get("request_id")

	def _create_product():
		resolved_warehouse = _resolve_default_warehouse(
			warehouse,
			kwargs.get("default_warehouse"),
		)
		company = kwargs.get("company") or _resolve_company_from_warehouse(resolved_warehouse)
		resolved_uom = _resolve_default_uom(kwargs.get("stock_uom") or kwargs.get("uom"))
		item_group = _resolve_default_item_group(kwargs.get("item_group"))
		item_code = _build_item_code(item_name, kwargs.get("item_code"))
		input_qty = flt(opening_qty or kwargs.get("qty") or 0)
		if input_qty < 0:
			frappe.throw(_("初始入库数量不能为负数。"))

		barcode = (kwargs.get("barcode") or "").strip()
		image_url = _normalize_text(kwargs.get("image")) or None
		if barcode and frappe.db.exists("Item Barcode", {"barcode": barcode}):
			frappe.throw(_("条码 {0} 已存在。").format(barcode))

		item = frappe.new_doc("Item")
		item.item_code = item_code
		item.item_name = item_name
		item.item_group = item_group
		item.stock_uom = resolved_uom
		item.is_stock_item = 1
		item.include_item_in_manufacturing = 0
		if kwargs.get("description"):
			item.description = kwargs["description"]
		if kwargs.get("image"):
			item.image = image_url
		if kwargs.get("nickname"):
			nickname_field = _get_item_nickname_field()
			if nickname_field:
				setattr(item, nickname_field, kwargs["nickname"])
			else:
				item.description = (
					f"{kwargs['nickname']}\n{item.description}".strip()
					if item.description
					else kwargs["nickname"]
				)
		if kwargs.get("specification"):
			specification_field = _get_item_specification_field()
			if specification_field:
				setattr(item, specification_field, _normalize_text(kwargs["specification"]))
		_apply_item_uom_updates(
			item=item,
			stock_uom=resolved_uom,
			uom_conversions=kwargs.get("uom_conversions"),
		)
		_validate_mode_default_uoms_against_stock_uom(
			item=item,
			stock_uom=resolved_uom,
			uom_conversions=kwargs.get("uom_conversions"),
		)
		if barcode:
			item.append("barcodes", {"barcode": barcode, "uom": resolved_uom})
		if image_url:
			frappe.db.after_rollback.add(lambda file_url=image_url: cleanup_temporary_item_image(file_url=file_url))
		item.insert()
		if image_url:
			bind_uploaded_item_image(file_url=image_url, item_code=item.name)
		opening_qty_context = resolve_item_quantity_to_stock(
			item_code=item.item_code,
			qty=input_qty,
			uom=kwargs.get("opening_uom"),
		)
		uom_display_map = build_uom_display_map(_collect_item_uom_names(item=item))

		selling_price_list = (kwargs.get("selling_price_list") or "Standard Selling").strip()
		currency = (kwargs.get("currency") or frappe.defaults.get_user_default("currency") or "").strip() or None
		standard_rate = kwargs.get("standard_rate")
		if standard_rate not in (None, ""):
			_upsert_item_price(
				item_code=item.item_code,
				rate=flt(standard_rate),
				price_list=selling_price_list,
				currency=currency,
				uom=_resolve_item_price_uom(item, None, selling_price_list),
			)

		stock_entry = _create_stock_entry(
			item_code=item.item_code,
			warehouse=resolved_warehouse,
			qty=opening_qty_context["stock_qty"],
			company=company,
			valuation_rate=flt(standard_rate or 0),
			posting_date=kwargs.get("posting_date"),
		)

		return {
			"status": "success",
			"message": _("商品 {0} 已创建，并可直接加入订单。").format(item.item_name),
			"data": {
				"item_code": item.item_code,
				"item_name": item.item_name,
				"uom": item.stock_uom,
				"uom_display": uom_display_map.get(_normalize_text(item.stock_uom)),
				"qty": opening_qty_context["stock_qty"],
				"input_qty": opening_qty_context["qty"],
				"input_uom": opening_qty_context["uom"],
				"price": flt(standard_rate) if standard_rate not in (None, "") else 0,
				"warehouse": resolved_warehouse,
				"image": item.image,
				"nickname": _extract_item_nickname(item),
				"specification": _extract_item_specification(item),
				"description": item.description,
				"item_group": item_group,
				"wholesale_default_uom": _extract_mode_default_uoms(item)["wholesale_default_uom"],
				"wholesale_default_uom_display": uom_display_map.get(
					_normalize_text(_extract_mode_default_uoms(item)["wholesale_default_uom"])
				),
				"retail_default_uom": _extract_mode_default_uoms(item)["retail_default_uom"],
				"retail_default_uom_display": uom_display_map.get(
					_normalize_text(_extract_mode_default_uoms(item)["retail_default_uom"])
				),
				"stock_entry": stock_entry.name if stock_entry else None,
			},
		}

	return run_idempotent("create_product_and_stock", request_id, _create_product)
