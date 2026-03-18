import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt

from myapp.utils.idempotency import run_idempotent

ITEM_NICKNAME_FIELD = "custom_nickname"


def _normalize_text(value: str | None):
	return (value or "").strip()


def _normalize_currency(value: str | None):
	return _normalize_text(value) or _normalize_text(frappe.defaults.get_user_default("currency")) or None


def _normalize_limit(limit: int | None):
	return max(1, min(int(limit or 20), 100))


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


def _get_item_filters():
	return {"disabled": 0, "is_sales_item": 1}


def _has_item_field(fieldname: str):
	try:
		return bool(frappe.get_meta("Item").has_field(fieldname))
	except Exception:
		return False


def _get_item_nickname_field():
	return ITEM_NICKNAME_FIELD if _has_item_field(ITEM_NICKNAME_FIELD) else None


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

	return {
		d.name: d
		for d in frappe.get_all(
			"Item",
			filters={**_get_item_filters(), "name": ["in", item_codes]},
			fields=fields,
		)
	}


def _get_price_map(item_codes: list[str], *, price_list: str, currency: str | None):
	if not item_codes:
		return {}

	price_filters = {"item_code": ["in", item_codes], "price_list": price_list}
	if currency:
		price_filters["currency"] = currency
	price_data = frappe.get_all("Item Price", filters=price_filters, fields=["item_code", "price_list_rate"])
	return {p.item_code: p.price_list_rate for p in price_data}


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


def _get_primary_barcode(item_code: str):
	return frappe.db.get_value("Item Barcode", {"parent": item_code}, "barcode")


def _build_product_detail_payload(
	item,
	*,
	warehouse: str | None = None,
	company: str | None = None,
	price_list: str = "Standard Selling",
	currency: str | None = None,
):
	qty_map = _get_qty_map([item.name], warehouse=warehouse, company=company)
	price_map = _get_price_map([item.name], price_list=price_list, currency=currency)
	uom_map = _get_uom_map([item.name])

	return {
		"item_code": item.name,
		"item_name": item.item_name,
		"item_group": item.item_group,
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
		"price": flt(price_map.get(item.name, 0) or 0),
		"price_list": price_list,
		"currency": currency,
		"warehouse": warehouse,
		"company": company,
		"creation": getattr(item, "creation", None),
		"modified": getattr(item, "modified", None),
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
	qty_map = _get_qty_map(item_codes, warehouse=warehouse, company=company)

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
				"price": flt(price_map.get(code, 0) or 0),
				"image": item.image,
				"nickname": _extract_item_nickname(item),
				"description": item.description,
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

		description = kwargs.get("description")
		if description is not None:
			item.description = _normalize_text(description)

		image = kwargs.get("image")
		if image is not None:
			item.image = _normalize_text(image)

		if "disabled" in kwargs and kwargs.get("disabled") is not None:
			item.disabled = cint(kwargs.get("disabled"))

		nickname = kwargs.get("nickname")
		if nickname is not None:
			normalized_nickname = _normalize_text(nickname)
			if nickname_field:
				setattr(item, nickname_field, normalized_nickname)
			elif description is None and normalized_nickname:
				item.description = normalized_nickname

		item.save()

		standard_rate = kwargs.get("standard_rate")
		price_list = _normalize_text(kwargs.get("price_list")) or "Standard Selling"
		currency = _normalize_currency(kwargs.get("currency"))
		if standard_rate not in (None, ""):
			_upsert_item_price(
				item_code=item.name,
				rate=flt(standard_rate),
				price_list=price_list,
				currency=currency,
			)

		item.reload()
		return {
			"status": "success",
			"data": _build_product_detail_payload(
				item,
				warehouse=_normalize_text(kwargs.get("warehouse")) or None,
				company=_normalize_text(kwargs.get("company")) or None,
				price_list=price_list,
				currency=currency,
			),
		}

	return run_idempotent("update_product_v2", request_id, _update_product)


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
		qty = flt(opening_qty or kwargs.get("qty") or 0)
		if qty < 0:
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
		if barcode:
			item.append("barcodes", {"barcode": barcode})
		item.insert()

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
			qty=qty,
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
				"qty": qty,
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
