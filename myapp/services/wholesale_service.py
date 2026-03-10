import frappe
from frappe import _
from frappe.query_builder.functions import Sum


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
	search_key = (search_key or "").strip()
	if not search_key:
		return {"status": "success", "data": []}

	limit = max(1, min(int(limit or 20), 100))
	price_list = (price_list or "Standard Selling").strip()
	currency = (currency or frappe.defaults.get_user_default("currency") or "").strip() or None
	warehouse = (warehouse or "").strip() or None
	company = (company or "").strip() or None

	item_filters = {"disabled": 0, "is_sales_item": 1}
	barcode_parent = frappe.db.get_value("Item Barcode", {"barcode": search_key}, "parent")

	if barcode_parent:
		item_codes = frappe.get_all("Item", filters={**item_filters, "name": barcode_parent}, pluck="name")
	else:
		item_codes = frappe.get_all(
			"Item",
			filters=item_filters,
			or_filters={"name": ["like", f"%{search_key}%"], "item_name": ["like", f"%{search_key}%"]},
			pluck="name",
			limit_page_length=limit,
		)

	if not item_codes:
		return {"status": "success", "data": [], "message": _("未找到匹配商品")}

	items_data = {
		d.name: d
		for d in frappe.get_all(
			"Item",
			filters={**item_filters, "name": ["in", item_codes]},
			fields=["name", "item_name", "stock_uom", "image"],
		)
	}

	price_filters = {"item_code": ["in", item_codes], "price_list": price_list}
	if currency:
		price_filters["currency"] = currency
	price_data = frappe.get_all("Item Price", filters=price_filters, fields=["item_code", "price_list_rate"])
	price_map = {p.item_code: p.price_list_rate for p in price_data}

	uom_data = frappe.get_all(
		"UOM Conversion Detail",
		filters={"parent": ["in", item_codes]},
		fields=["parent", "uom", "conversion_factor"],
	)
	uom_map = {}
	for u in uom_data:
		uom_map.setdefault(u.parent, []).append({"uom": u.uom, "conversion_factor": u.conversion_factor})

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
	qty_map = {d.item_code: d.total_qty or 0 for d in inventory_data}

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
