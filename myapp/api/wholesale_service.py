from frappe import _
import frappe
from frappe.query_builder.functions import Sum  # 导入求和函数


@frappe.whitelist()
def search_product(search_key: str):
	"""
	搜索商品，并返回基础信息、价格、单位与库存。
	"""
	# [优化] 统一清洗输入，避免仅空格导致无效查询
	search_key = (search_key or "").strip()
	if not search_key:
		return {"status": "success", "data": []}

	# [优化] 提取公共筛选条件，确保全流程只返回可售且未禁用商品
	item_filters = {"disabled": 0, "is_sales_item": 1}
	barcode_parent = frappe.db.get_value("Item Barcode", {"barcode": search_key}, "parent")

	if barcode_parent:
		# [优化] 条码命中后同样应用商品状态过滤，避免返回不可售/禁用商品
		item_codes = frappe.get_all("Item", filters={**item_filters, "name": barcode_parent}, pluck="name")
	else:
		item_codes = frappe.get_all(
			"Item",
			filters=item_filters,
			or_filters={"name": ["like", f"%{search_key}%"], "item_name": ["like", f"%{search_key}%"]},
			pluck="name",
			# [优化] 使用 Frappe 标准参数名 limit_page_length
			limit_page_length=20,
		)

	if not item_codes:
		# [优化] 无匹配结果也返回 success + 空数组，便于前端统一处理
		return {"status": "success", "data": [], "message": _("未找到匹配商品")}

	items_data = {
		d.name: d
		for d in frappe.get_all(
			"Item",
			filters={**item_filters, "name": ["in", item_codes]},
				fields=["name", "item_name", "stock_uom", "image"],
			)
	}

	price_data = frappe.get_all(
		"Item Price",
		filters={"item_code": ["in", item_codes], "price_list": "Standard Selling", "currency": "CNY"},
		fields=["item_code", "price_list_rate"],
	)
	price_map = {p.item_code: p.price_list_rate for p in price_data}

	uom_data = frappe.get_all(
		"UOM Conversion Detail",
		filters={"parent": ["in", item_codes]},
		fields=["parent", "uom", "conversion_factor"],
	)
	uom_map = {}
	for u in uom_data:
		uom_map.setdefault(u.parent, []).append({"uom": u.uom, "conversion_factor": u.conversion_factor})

	bin = frappe.qb.DocType("Bin")
	inventory_data = (
		frappe.qb.from_(bin)
		.select(bin.item_code, Sum(bin.actual_qty).as_("total_qty"))
		.where(bin.item_code.isin(item_codes))
		.groupby(bin.item_code)
	).run(as_dict=True)
	# [优化] 聚合结果为空时回退为 0，避免返回 None
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

	return {"status": "success", "data": results}
