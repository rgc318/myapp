import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt

from myapp.utils.idempotency import run_idempotent
from myapp.utils.uom import resolve_item_quantity_to_stock

ITEM_NICKNAME_FIELD = "custom_nickname"
WHOLESALE_DEFAULT_UOM_FIELD = "custom_wholesale_default_uom"
RETAIL_DEFAULT_UOM_FIELD = "custom_retail_default_uom"
DEFAULT_SELLING_PRICE_LISTS = ("Standard Selling", "Wholesale", "Retail")
DEFAULT_BUYING_PRICE_LISTS = ("Standard Buying",)


def _normalize_text(value: str | None):
	return (value or "").strip()


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


def _get_item_filters():
	return {"disabled": 0, "is_sales_item": 1}


def _has_item_field(fieldname: str):
	try:
		return bool(frappe.get_meta("Item").has_field(fieldname))
	except Exception:
		return False


def _get_item_nickname_field():
	return ITEM_NICKNAME_FIELD if _has_item_field(ITEM_NICKNAME_FIELD) else None


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


def _search_item_codes(search_key: str, *, search_fields: list[str], limit: int):
	item_filters = _get_item_filters()
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
		codes = frappe.get_all(
			"Item",
			filters={**item_filters, "name": ["like", f"%{search_key}%"]},
			pluck="name",
			limit_page_length=limit,
			order_by="modified desc",
		)
		if _extend(codes):
			return matched_codes

	if "item_name" in search_fields:
		codes = frappe.get_all(
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
		codes = frappe.get_all(
			"Item",
			filters=item_filters,
			or_filters=or_filters,
			pluck="name",
			limit_page_length=limit,
			order_by="modified desc",
		)
		_extend(codes)

	return matched_codes[:limit]


def _get_item_data_map(item_codes: list[str]):
	if not item_codes:
		return {}

	fields = ["name", "item_name", "stock_uom", "image", "description", "creation", "modified"]
	nickname_field = _get_item_nickname_field()
	if nickname_field:
		fields.append(nickname_field)
	for fieldname in (WHOLESALE_DEFAULT_UOM_FIELD, RETAIL_DEFAULT_UOM_FIELD):
		if _has_item_field(fieldname):
			fields.append(fieldname)

	return {
		d.name: d
		for d in frappe.get_all(
			"Item",
			filters={**_get_item_filters(), "name": ["in", item_codes]},
			fields=fields,
		)
	}


def _get_item_rows(
	*,
	search_key: str | None = None,
	item_group: str | None = None,
	disabled: int | None = None,
	limit: int = 20,
	start: int = 0,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	fields = [
		"name",
		"item_name",
		"item_group",
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
	for fieldname in (WHOLESALE_DEFAULT_UOM_FIELD, RETAIL_DEFAULT_UOM_FIELD):
		if _has_item_field(fieldname):
			fields.append(fieldname)

	filters = {}
	if item_group:
		filters["item_group"] = item_group
	if disabled is not None:
		filters["disabled"] = cint(disabled)

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

	rows = frappe.get_all(
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
				frappe.get_all("Item", filters={"name": ["in", missing]}, fields=fields, limit_page_length=len(missing))
				+ rows
			)[:limit]

	return rows


def _get_price_map(item_codes: list[str], *, price_list: str, currency: str | None):
	if not item_codes:
		return {}

	price_filters = {"item_code": ["in", item_codes], "price_list": price_list}
	if currency:
		price_filters["currency"] = currency
	price_data = frappe.get_all("Item Price", filters=price_filters, fields=["item_code", "price_list_rate"])
	return {p.item_code: p.price_list_rate for p in price_data}


def _get_multi_price_map(item_codes: list[str], *, price_lists: list[str], currency: str | None):
	if not item_codes or not price_lists:
		return {}

	price_filters = {"item_code": ["in", item_codes], "price_list": ["in", price_lists]}
	if currency:
		price_filters["currency"] = currency
	price_rows = frappe.get_all(
		"Item Price",
		filters=price_filters,
		fields=["item_code", "price_list", "price_list_rate", "currency"],
	)

	result = {}
	for row in price_rows:
		result.setdefault(row.item_code, {})[row.price_list] = {
			"price_list": row.price_list,
			"rate": flt(row.price_list_rate or 0),
			"currency": row.currency or currency,
		}
	return result


def _get_uom_map(item_codes: list[str]):
	if not item_codes:
		return {}

	uom_data = frappe.get_all(
		"UOM Conversion Detail",
		filters={"parent": ["in", item_codes]},
		fields=["parent", "uom", "conversion_factor"],
	)
	uom_map = {}
	for u in uom_data:
		uom_map.setdefault(u.parent, []).append({"uom": u.uom, "conversion_factor": u.conversion_factor})
	return uom_map


def _get_qty_map(item_codes: list[str], *, warehouse: str | None, company: str | None):
	if not item_codes:
		return {}

	bin_dt = frappe.qb.DocType("Bin")
	query = (
		frappe.qb.from_(bin_dt)
		.select(bin_dt.item_code, Sum(bin_dt.actual_qty).as_("total_qty"))
		.where(bin_dt.item_code.isin(item_codes))
	)

	if warehouse:
		query = query.where(bin_dt.warehouse == warehouse)
	elif company:
		warehouse_dt = frappe.qb.DocType("Warehouse")
		query = (
			frappe.qb.from_(bin_dt)
			.inner_join(warehouse_dt)
			.on(bin_dt.warehouse == warehouse_dt.name)
			.select(bin_dt.item_code, Sum(bin_dt.actual_qty).as_("total_qty"))
			.where(bin_dt.item_code.isin(item_codes))
			.where(warehouse_dt.company == company)
		)

	inventory_data = query.groupby(bin_dt.item_code).run(as_dict=True)
	return {d.item_code: d.total_qty or 0 for d in inventory_data}


def _get_warehouse_stock_detail_map(item_codes: list[str], *, company: str | None):
	if not item_codes:
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
	)
	if company:
		query = query.where(warehouse_dt.company == company)

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
	return {
		"current_price_list": current_price_list,
		"current_rate": flt(current_rate or 0),
		"standard_selling_rate": flt(
			(selling_price_map.get("Standard Selling") or {}).get("rate")
			or getattr(item, "standard_rate", 0)
			or 0
		),
		"wholesale_rate": flt((selling_price_map.get("Wholesale") or {}).get("rate") or 0),
		"retail_rate": flt((selling_price_map.get("Retail") or {}).get("rate") or 0),
		"standard_buying_rate": flt((buying_price_map.get("Standard Buying") or {}).get("rate") or 0),
		"valuation_rate": flt(getattr(item, "valuation_rate", 0) or 0),
		"selling_prices": list(selling_price_map.values()),
		"buying_prices": list(buying_price_map.values()),
	}


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
	return frappe.db.get_value("Item Barcode", {"parent": item_code}, "barcode")


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
		else:
			item.append("barcodes", {"barcode": normalized})


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
	uom_map = _get_uom_map([item.name])
	current_rate = flt(price_map.get(item.name, 0) or 0)
	mode_default_uoms = _extract_mode_default_uoms(item)

	return {
		"item_code": item.name,
		"item_name": item.item_name,
		"item_group": item.item_group,
		"brand": getattr(item, "brand", None),
		"stock_uom": item.stock_uom,
		"uom": item.stock_uom,
		"all_uoms": uom_map.get(item.name, []),
		"image": item.image,
		"nickname": _extract_item_nickname(item),
		"description": item.description,
		"disabled": cint(item.disabled),
		"is_sales_item": cint(getattr(item, "is_sales_item", 0)),
		"barcode": _get_primary_barcode(item.name),
		"qty": flt(qty_map.get(item.name, 0)),
		"total_qty": flt(total_qty_map.get(item.name, 0)),
		"warehouse_stock_details": warehouse_stock_map.get(item.name, []),
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
		"retail_default_uom": mode_default_uoms["retail_default_uom"],
		"sales_profiles": _build_sales_profiles(item),
		"warehouse": warehouse,
		"company": company,
		"creation": getattr(item, "creation", None),
		"modified": getattr(item, "modified", None),
	}


def list_products_v2(
	search_key: str | None = None,
	warehouse: str | None = None,
	company: str | None = None,
	limit: int = 20,
	start: int = 0,
	item_group: str | None = None,
	disabled: int | None = None,
	price_list: str = "Standard Selling",
	currency: str | None = None,
	selling_price_lists=None,
	buying_price_lists=None,
	sort_by: str = "modified",
	sort_order: str = "desc",
):
	limit = _normalize_limit(limit)
	start = _normalize_start(start)
	warehouse = _normalize_text(warehouse) or None
	company = _normalize_text(company) or None
	price_list = _normalize_text(price_list) or "Standard Selling"
	currency = _normalize_currency(currency)
	selling_price_lists = _normalize_price_list_names(selling_price_lists, defaults=DEFAULT_SELLING_PRICE_LISTS)
	buying_price_lists = _normalize_price_list_names(buying_price_lists, defaults=DEFAULT_BUYING_PRICE_LISTS)
	sort_by = _normalize_text(sort_by).lower() or "modified"
	if sort_by not in {"modified", "creation", "item_name", "name"}:
		sort_by = "modified"
	sort_order = "asc" if _normalize_text(sort_order).lower() == "asc" else "desc"

	rows = _get_item_rows(
		search_key=search_key,
		item_group=_normalize_text(item_group) or None,
		disabled=disabled,
		limit=limit,
		start=start,
		sort_by=sort_by,
		sort_order=sort_order,
	)
	item_codes = [row.name for row in rows]
	stock_company = _resolve_stock_company_scope(warehouse, company)
	qty_map = _get_qty_map(item_codes, warehouse=warehouse, company=company)
	total_qty_map = _get_qty_map(item_codes, warehouse=None, company=stock_company)
	warehouse_stock_map = _get_warehouse_stock_detail_map(item_codes, company=stock_company)
	current_price_map = _get_price_map(item_codes, price_list=price_list, currency=currency)
	selling_price_map = _get_multi_price_map(item_codes, price_lists=selling_price_lists, currency=currency)
	buying_price_map = _get_multi_price_map(item_codes, price_lists=buying_price_lists, currency=currency)

	items = []
	for row in rows:
		current_rate = flt(current_price_map.get(row.name, 0) or 0)
		mode_default_uoms = _extract_mode_default_uoms(row)
		items.append(
			{
				"item_code": row.name,
				"item_name": row.item_name,
				"item_group": row.item_group,
				"stock_uom": row.stock_uom,
				"image": row.image,
				"nickname": _extract_item_nickname(row),
				"description": row.description,
				"disabled": cint(row.disabled),
				"is_sales_item": cint(getattr(row, "is_sales_item", 0)),
				"is_purchase_item": cint(getattr(row, "is_purchase_item", 0)),
				"qty": flt(qty_map.get(row.name, 0) or 0),
				"total_qty": flt(total_qty_map.get(row.name, 0) or 0),
				"warehouse_stock_details": warehouse_stock_map.get(row.name, []),
				"price": current_rate,
				"price_list": price_list,
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
				"retail_default_uom": mode_default_uoms["retail_default_uom"],
				"sales_profiles": _build_sales_profiles(row),
				"creation": row.creation,
				"modified": row.modified,
			}
		)

	return {
		"status": "success",
		"data": items,
		"filters": {
			"search_key": _normalize_text(search_key) or None,
			"warehouse": warehouse,
			"company": company,
			"limit": limit,
			"start": start,
			"item_group": _normalize_text(item_group) or None,
			"disabled": disabled,
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
		search_fields=["barcode", "item_code", "item_name"],
		limit=limit,
	)

	if not item_codes:
		return {"status": "success", "data": [], "message": _("未找到匹配商品")}

	items_data = _get_item_data_map(item_codes)
	price_map = _get_price_map(item_codes, price_list=price_list, currency=currency)
	uom_map = _get_uom_map(item_codes)
	qty_map = _get_qty_map(item_codes, warehouse=warehouse, company=company)
	selling_price_map = _get_multi_price_map(item_codes, price_lists=list(DEFAULT_SELLING_PRICE_LISTS), currency=currency)
	buying_price_map = _get_multi_price_map(item_codes, price_lists=list(DEFAULT_BUYING_PRICE_LISTS), currency=currency)
	selling_price_map = _get_multi_price_map(item_codes, price_lists=list(DEFAULT_SELLING_PRICE_LISTS), currency=currency)
	buying_price_map = _get_multi_price_map(item_codes, price_lists=list(DEFAULT_BUYING_PRICE_LISTS), currency=currency)
	selling_price_map = _get_multi_price_map(item_codes, price_lists=list(DEFAULT_SELLING_PRICE_LISTS), currency=currency)
	buying_price_map = _get_multi_price_map(item_codes, price_lists=list(DEFAULT_BUYING_PRICE_LISTS), currency=currency)

	results = []
	for code in item_codes:
		item = items_data.get(code)
		if not item:
			continue

		results.append(
			{
				"item_code": item.name,
				"item_name": item.item_name,
				"uom": item.stock_uom,
				"all_uoms": uom_map.get(code, []),
				"qty": qty_map.get(code, 0),
				"price": price_map.get(code, 0),
				"image": item.image,
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

	item = frappe.get_doc("Item", item_code)
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


def search_product_v2(
	search_key: str,
	price_list: str = "Standard Selling",
	currency: str | None = None,
	warehouse: str | None = None,
	company: str | None = None,
	limit: int = 20,
	search_fields=None,
	sort_by: str = "relevance",
	sort_order: str = "asc",
	in_stock_only: bool = False,
):
	search_key = _normalize_text(search_key)
	if not search_key:
		return {"status": "success", "data": []}

	limit = _normalize_limit(limit)
	price_list = _normalize_text(price_list) or "Standard Selling"
	currency = _normalize_currency(currency)
	warehouse = _normalize_text(warehouse) or None
	company = _normalize_text(company) or None
	search_fields = _normalize_search_fields(search_fields)
	sort_by = _normalize_text(sort_by).lower() or "relevance"
	sort_order = "desc" if _normalize_text(sort_order).lower() == "desc" else "asc"
	in_stock_only = bool(cint(in_stock_only))

	item_codes = _search_item_codes(search_key, search_fields=search_fields, limit=limit * 3)
	if not item_codes:
		return {"status": "success", "data": [], "message": _("未找到匹配商品")}

	items_data = _get_item_data_map(item_codes)
	price_map = _get_price_map(item_codes, price_list=price_list, currency=currency)
	uom_map = _get_uom_map(item_codes)
	stock_company = _resolve_stock_company_scope(warehouse, company)
	qty_map = _get_qty_map(item_codes, warehouse=warehouse, company=company)
	total_qty_map = _get_qty_map(item_codes, warehouse=None, company=stock_company)
	warehouse_stock_map = _get_warehouse_stock_detail_map(item_codes, company=stock_company)
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

	results = []
	for code in item_codes:
		item = items_data.get(code)
		if not item:
			continue

		qty = flt(qty_map.get(code, 0))
		if in_stock_only and qty <= 0:
			continue

		results.append(
			{
				"item_code": item.name,
				"item_name": item.item_name,
				"uom": item.stock_uom,
				"all_uoms": uom_map.get(code, []),
				"qty": qty,
				"total_qty": flt(total_qty_map.get(code, 0) or 0),
				"warehouse_stock_details": warehouse_stock_map.get(code, []),
				"price": flt(price_map.get(code, 0) or 0),
				"image": item.image,
				"nickname": _extract_item_nickname(item),
				"description": item.description,
				"price_summary": _build_price_summary(
					item,
					current_price_list=price_list,
					current_rate=flt(price_map.get(code, 0) or 0),
					selling_price_map=selling_price_map.get(code, {}),
					buying_price_map=buying_price_map.get(code, {}),
				),
				"wholesale_default_uom": _extract_mode_default_uoms(item)["wholesale_default_uom"],
				"retail_default_uom": _extract_mode_default_uoms(item)["retail_default_uom"],
				"sales_profiles": _build_sales_profiles(item),
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
			"limit": limit,
			"search_fields": search_fields,
			"sort_by": sort_by,
			"sort_order": sort_order,
			"in_stock_only": in_stock_only,
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
	item_code: str,
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
			item_code=item_code,
			rate=flt(standard_rate),
			price_list=default_price_list,
			currency=default_currency,
		)

	for entry in _coerce_price_entries(selling_prices):
		_upsert_item_price(
			item_code=item_code,
			rate=entry["rate"],
			price_list=entry["price_list"],
			currency=entry["currency"] or default_currency,
		)

	for entry in _coerce_price_entries(buying_prices):
		_upsert_item_price(
			item_code=item_code,
			rate=entry["rate"],
			price_list=entry["price_list"],
			currency=entry["currency"] or default_currency,
		)


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


def _upsert_item_price(item_code: str, rate: float, price_list: str, currency: str | None = None):
	if rate < 0:
		frappe.throw(_("销售价不能为负数。"))

	filters = {"item_code": item_code, "price_list": price_list}
	if currency:
		filters["currency"] = currency

	existing_name = frappe.db.get_value("Item Price", filters, "name")
	if existing_name:
		item_price = frappe.get_doc("Item Price", existing_name)
		item_price.price_list_rate = rate
		item_price.save()
		return item_price

	item_price = frappe.new_doc("Item Price")
	item_price.item_code = item_code
	item_price.price_list = price_list
	item_price.price_list_rate = rate
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


def update_product_v2(
	item_code: str,
	**kwargs,
):
	item_code = _normalize_text(item_code)
	if not item_code:
		frappe.throw(_("商品编码不能为空。"))

	request_id = kwargs.get("request_id")

	def _update_product():
		item = frappe.get_doc("Item", item_code)
		nickname_field = _get_item_nickname_field()

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

		image = kwargs.get("image")
		if image is not None:
			item.image = _normalize_text(image)

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

		standard_rate = kwargs.get("standard_rate")
		price_list = _normalize_text(kwargs.get("price_list")) or "Standard Selling"
		currency = _normalize_currency(kwargs.get("currency"))
		_apply_item_price_updates(
			item_code=item.name,
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
			item.image = kwargs.get("image")
		if kwargs.get("nickname") is not None:
			nickname_field = _get_item_nickname_field()
			if nickname_field:
				setattr(item, nickname_field, _normalize_text(kwargs.get("nickname")))
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
			item.append("barcodes", {"barcode": barcode})
		item.insert()

		_apply_item_price_updates(
			item_code=item.item_code,
			standard_rate=kwargs.get("standard_rate"),
			price_list=kwargs.get("price_list"),
			currency=kwargs.get("currency"),
			selling_prices=kwargs.get("selling_prices"),
			buying_prices=kwargs.get("buying_prices"),
		)

		item.reload()
		return {
			"status": "success",
			"message": _("商品 {0} 已创建。").format(item.item_name),
			"data": _build_product_detail_payload(
				item,
				warehouse=_normalize_text(kwargs.get("warehouse")) or None,
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
		item = frappe.get_doc("Item", item_code)
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
			item.image = kwargs["image"]
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
			item.append("barcodes", {"barcode": barcode})
		item.insert()
		opening_qty_context = resolve_item_quantity_to_stock(
			item_code=item.item_code,
			qty=input_qty,
			uom=kwargs.get("opening_uom"),
		)

		selling_price_list = (kwargs.get("selling_price_list") or "Standard Selling").strip()
		currency = (kwargs.get("currency") or frappe.defaults.get_user_default("currency") or "").strip() or None
		standard_rate = kwargs.get("standard_rate")
		if standard_rate not in (None, ""):
			_upsert_item_price(
				item_code=item.item_code,
				rate=flt(standard_rate),
				price_list=selling_price_list,
				currency=currency,
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
				"qty": opening_qty_context["stock_qty"],
				"input_qty": opening_qty_context["qty"],
				"input_uom": opening_qty_context["uom"],
				"price": flt(standard_rate) if standard_rate not in (None, "") else 0,
				"warehouse": resolved_warehouse,
				"image": item.image,
				"nickname": _extract_item_nickname(item),
				"description": item.description,
				"item_group": item_group,
				"stock_entry": stock_entry.name if stock_entry else None,
			},
		}

	return run_idempotent("create_product_and_stock", request_id, _create_product)
