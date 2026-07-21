from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import frappe
from frappe.utils import add_days, flt, getdate

from myapp.services.customer_service import create_customer_v2
from myapp.services.order_service import create_order_v2, create_sales_invoice, submit_delivery
from myapp.services.purchase_service import (
	create_purchase_invoice_from_receipt,
	create_purchase_order,
	create_supplier_v2,
	receive_purchase_order,
	record_supplier_payment,
)
from myapp.services.settlement_service import update_payment_status
from myapp.services.wholesale_service import create_product_and_stock
from myapp.test_data.catalog import DatasetDefinition, ScenarioTemplate
from myapp.test_data.registry import register_object


@dataclass
class GenerationContext:
	run_name: str
	company: str
	warehouse: str
	base_date: object
	item_codes: dict[str, str] = field(default_factory=dict)
	customers: dict[str, str] = field(default_factory=dict)
	suppliers: dict[str, str] = field(default_factory=dict)
	document_order: int = 0
	counts: dict[str, int] = field(default_factory=dict)
	progress_callback: Callable[[str], None] | None = None

	def record(self, scenario_key: str, doctype_name: str, document_name: str | None, metadata=None) -> None:
		if not document_name:
			return
		self.document_order += 1
		register_object(
			run_name=self.run_name,
			scenario_key=scenario_key,
			doctype_name=doctype_name,
			document_name=document_name,
			document_order=self.document_order,
			metadata=metadata,
		)
		self.counts[doctype_name] = self.counts.get(doctype_name, 0) + 1

	def advance(self, message: str) -> None:
		if self.progress_callback:
			self.progress_callback(message)


def _setting_value(doctype: str, fieldname: str) -> str | None:
	value = frappe.db.get_single_value(doctype, fieldname)
	return str(value).strip() if value else None


def resolve_master_defaults() -> dict:
	return {
		"customer_group": str(
			frappe.conf.get("myapp_test_data_customer_group")
			or _setting_value("Selling Settings", "customer_group")
			or ""
		).strip(),
		"territory": str(
			frappe.conf.get("myapp_test_data_territory")
			or _setting_value("Selling Settings", "territory")
			or ""
		).strip(),
		"supplier_group": str(
			frappe.conf.get("myapp_test_data_supplier_group")
			or _setting_value("Buying Settings", "supplier_group")
			or ""
		).strip(),
		"item_group": str(
			frappe.conf.get("myapp_test_data_item_group")
			or _setting_value("Stock Settings", "item_group")
			or ""
		).strip(),
	}


def validate_master_defaults(defaults: dict) -> list[str]:
	issues = []
	checks = (
		("Customer Group", defaults.get("customer_group"), "customer_group"),
		("Territory", defaults.get("territory"), "territory"),
		("Supplier Group", defaults.get("supplier_group"), "supplier_group"),
		("Item Group", defaults.get("item_group"), "item_group"),
	)
	for doctype, value, key in checks:
		if not value:
			issues.append(f"未配置 {key} 默认值。")
		elif not frappe.db.exists(doctype, value):
			issues.append(f"{doctype} {value} 不存在。")
	return issues


def _marker(context: GenerationContext, scenario_key: str) -> str:
	return f"[MYAPP-TDM:{context.run_name}:{scenario_key}]"


def _date(context: GenerationContext, offset_days: int):
	return add_days(getdate(context.base_date), offset_days)


def _payment_reference(context: GenerationContext, scenario_key: str) -> str:
	return f"TDM-{context.run_name[-8:]}-{scenario_key}"


def _record_item_price(context: GenerationContext, scenario_key: str, item_code: str) -> None:
	rows = frappe.get_all(
		"Item Price",
		filters={"item_code": item_code, "price_list": "Standard Selling"},
		pluck="name",
		order_by="creation desc",
		limit=1,
	)
	if rows:
		context.record(scenario_key, "Item Price", rows[0])


def create_master_data(
	context: GenerationContext,
	dataset: DatasetDefinition,
	defaults: dict,
	*,
	opening_qty_multiplier: int = 1,
) -> None:
	for customer in dataset.customers:
		result = create_customer_v2(
			customer.name,
			customer_group=defaults["customer_group"],
			territory=defaults["territory"],
			remarks=_marker(context, f"customer-{customer.key}"),
		)
		name = result["data"]["name"]
		context.customers[customer.key] = name
		context.record(f"customer-{customer.key}", "Customer", name)
		context.advance(f"已创建客户：{customer.name}")

	for supplier in dataset.suppliers:
		result = create_supplier_v2(
			supplier.name,
			supplier_group=defaults["supplier_group"],
			remarks=_marker(context, f"supplier-{supplier.key}"),
		)
		name = result["data"]["name"]
		context.suppliers[supplier.key] = name
		context.record(f"supplier-{supplier.key}", "Supplier", name)
		context.advance(f"已创建供应商：{supplier.name}")

	for item in dataset.items:
		scenario_key = f"item-{item.key}"
		result = create_product_and_stock(
			item_name=item.item_name,
			item_code=item.item_code,
			warehouse=context.warehouse,
			company=context.company,
			opening_qty=item.opening_qty * opening_qty_multiplier,
			opening_uom=item.stock_uom,
			stock_uom=item.stock_uom,
			uom_conversions=[{"uom": uom, "conversion_factor": factor} for uom, factor in item.uom_conversions],
			wholesale_default_uom=item.wholesale_default_uom,
			retail_default_uom=item.retail_default_uom,
			standard_rate=item.standard_rate,
			item_group=defaults["item_group"],
			description=_marker(context, scenario_key),
			posting_date=_date(context, -60),
		)
		data = result["data"]
		context.item_codes[item.key] = data["item_code"]
		context.record(scenario_key, "Item", data["item_code"])
		_record_item_price(context, scenario_key, data["item_code"])
		context.record(scenario_key, "Stock Entry", data.get("stock_entry"))
		context.advance(f"已创建商品与库存：{item.item_name}")


def load_existing_master_data(context: GenerationContext, dataset: DatasetDefinition) -> None:
	for customer in dataset.customers:
		name = frappe.db.get_value("Customer", {"customer_name": customer.name}, "name")
		if not name:
			frappe.throw(f"补充场景所需客户不存在：{customer.name}")
		context.customers[customer.key] = name
	for supplier in dataset.suppliers:
		name = frappe.db.get_value("Supplier", {"supplier_name": supplier.name}, "name")
		if not name:
			frappe.throw(f"补充场景所需供应商不存在：{supplier.name}")
		context.suppliers[supplier.key] = name
	for item in dataset.items:
		if not frappe.db.exists("Item", item.item_code):
			frappe.throw(f"补充场景所需商品不存在：{item.item_code}")
		context.item_codes[item.key] = item.item_code


def _sales_items(context: GenerationContext, scenario: ScenarioTemplate) -> list[dict]:
	return [
		{
			"item_code": context.item_codes[scenario.item_key],
			"qty": scenario.qty,
			"uom": scenario.uom,
			"warehouse": context.warehouse,
			"price": scenario.rate,
		}
	]


def _purchase_items(context: GenerationContext, scenario: ScenarioTemplate) -> list[dict]:
	return _sales_items(context, scenario)


def create_sales_scenario(
	context: GenerationContext,
	scenario: ScenarioTemplate,
	*,
	scenario_key: str | None = None,
	date_shift_days: int = 0,
) -> None:
	scenario_key = scenario_key or scenario.key
	posting_date = _date(context, scenario.date_offset_days + date_shift_days)
	item_code = context.item_codes[scenario.item_key]
	marker = _marker(context, scenario_key)
	order_result = create_order_v2(
		customer=context.customers[scenario.party_key],
		items=_sales_items(context, scenario),
		company=context.company,
		immediate=0,
		transaction_date=posting_date,
		delivery_date=add_days(posting_date, 3),
		remarks=marker,
	)
	order_name = order_result["order"]
	context.record(scenario_key, "Sales Order", order_name, {"expected_state": scenario.state})

	if scenario.state == "order_only":
		return
	if scenario.state in {"partial_delivery", "complete"}:
		delivery_qty = scenario.partial_qty if scenario.state == "partial_delivery" else scenario.qty
		delivery_result = submit_delivery(
			order_name,
			delivery_items=[{"item_code": item_code, "qty": delivery_qty}],
			kwargs={"posting_date": posting_date, "remarks": marker},
		)
		context.record(scenario_key, "Delivery Note", delivery_result["delivery_note"])
		if scenario.state == "partial_delivery":
			return

	invoice_result = create_sales_invoice(
		order_name,
		kwargs={
			"posting_date": posting_date,
			"due_date": add_days(posting_date, 30),
			"remarks": marker,
		},
	)
	invoice_name = invoice_result["sales_invoice"]
	context.record(scenario_key, "Sales Invoice", invoice_name)
	if scenario.state == "unpaid_invoice":
		return

	outstanding = flt(frappe.db.get_value("Sales Invoice", invoice_name, "outstanding_amount") or 0)
	payment_amount = round(outstanding * flt(scenario.payment_ratio or 1), 2)
	payment_result = update_payment_status(
		"Sales Invoice",
		invoice_name,
		payment_amount,
		mode_of_payment="Cash",
		reference_no=_payment_reference(context, scenario_key),
		reference_date=posting_date,
	)
	context.record(scenario_key, "Payment Entry", payment_result["payment_entry"])


def create_purchase_scenario(
	context: GenerationContext,
	scenario: ScenarioTemplate,
	*,
	scenario_key: str | None = None,
	date_shift_days: int = 0,
) -> None:
	scenario_key = scenario_key or scenario.key
	posting_date = _date(context, scenario.date_offset_days + date_shift_days)
	marker = _marker(context, scenario_key)
	order_result = create_purchase_order(
		supplier=context.suppliers[scenario.party_key],
		items=_purchase_items(context, scenario),
		company=context.company,
		transaction_date=posting_date,
		schedule_date=add_days(posting_date, 5),
		remarks=marker,
	)
	order_name = order_result["purchase_order"]
	context.record(scenario_key, "Purchase Order", order_name, {"expected_state": scenario.state})
	if scenario.state == "order_only":
		return

	receipt_result = receive_purchase_order(
		order_name,
		kwargs={"posting_date": posting_date, "remarks": marker},
	)
	receipt_name = receipt_result["purchase_receipt"]
	context.record(scenario_key, "Purchase Receipt", receipt_name)
	if scenario.state == "received":
		return

	invoice_result = create_purchase_invoice_from_receipt(
		receipt_name,
		kwargs={
			"posting_date": posting_date,
			"due_date": add_days(posting_date, 30),
			"remarks": marker,
		},
	)
	invoice_name = invoice_result["purchase_invoice"]
	context.record(scenario_key, "Purchase Invoice", invoice_name)
	outstanding = flt(frappe.db.get_value("Purchase Invoice", invoice_name, "outstanding_amount") or 0)
	payment_amount = round(outstanding * flt(scenario.payment_ratio or 1), 2)
	payment_result = record_supplier_payment(
		invoice_name,
		payment_amount,
		mode_of_payment="Cash",
		reference_no=_payment_reference(context, scenario_key),
		reference_date=posting_date,
	)
	context.record(scenario_key, "Payment Entry", payment_result["payment_entry"])


def _scenario_instance_key(scenario_key: str, copy_number: int) -> str:
	return f"{scenario_key}#{copy_number}"


def generate_dataset(
	*,
	run_name: str,
	company: str,
	warehouse: str,
	base_date,
	dataset: DatasetDefinition,
	create_masters: bool = True,
	scenario_keys: list[str] | None = None,
	scale: str = "small",
	scenario_copies: int = 1,
	progress_callback: Callable[[str], None] | None = None,
) -> dict:
	if scenario_copies < 1 or scenario_copies > 20:
		raise ValueError("场景份数必须在 1 到 20 之间。")
	selected_keys = (
		set(scenario_keys)
		if scenario_keys is not None
		else {scenario.key for scenario in dataset.scenarios}
	)
	scenarios = [scenario for scenario in dataset.scenarios if scenario.key in selected_keys]
	context = GenerationContext(
		run_name=run_name,
		company=company,
		warehouse=warehouse,
		base_date=base_date,
		progress_callback=progress_callback,
	)
	if create_masters:
		defaults = resolve_master_defaults()
		issues = validate_master_defaults(defaults)
		if issues:
			frappe.throw(" ".join(issues))
		create_master_data(
			context,
			dataset,
			defaults,
			opening_qty_multiplier=scenario_copies,
		)
	else:
		load_existing_master_data(context, dataset)
	for copy_number in range(1, scenario_copies + 1):
		for scenario in scenarios:
			scenario_instance_key = _scenario_instance_key(scenario.key, copy_number)
			kwargs = {
				"scenario_key": scenario_instance_key,
				"date_shift_days": -(copy_number - 1),
			}
			if scenario.domain == "sales":
				create_sales_scenario(context, scenario, **kwargs)
			elif scenario.domain == "purchase":
				create_purchase_scenario(context, scenario, **kwargs)
			else:
				raise ValueError(f"未知场景领域：{scenario.domain}")
			context.advance(f"已生成场景：{scenario_instance_key}")
	return {
		"run_name": run_name,
		"dataset_code": dataset.code,
		"dataset_version": dataset.version,
		"company": company,
		"warehouse": warehouse,
		"counts": dict(sorted(context.counts.items())),
		"object_count": context.document_order,
		"scenario_count": len(scenarios),
		"scenario_instance_count": len(scenarios) * scenario_copies,
		"scenario_keys": [scenario.key for scenario in scenarios],
		"scale": scale,
		"scenario_copies": scenario_copies,
		"created_masters": bool(create_masters),
	}
