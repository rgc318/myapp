from __future__ import annotations

from dataclasses import dataclass

import frappe
from frappe import _

PRINT_SETTING_TABLE = "MyApp Print Setting"


@dataclass(frozen=True)
class PrintTemplateDefinition:
	key: str
	label: str
	print_format: str | None
	is_default: bool = False
	source: str = "erpnext"
	category: str = "standard"
	paper_size: str = "A4"
	orientation: str = "Portrait"
	description: str | None = None
	enabled: bool = True
	allowed_roles: tuple[str, ...] = ()

	def as_dict(self):
		version_info = _get_template_version_info(self.print_format)
		return {
			"key": self.key,
			"label": self.label,
			"print_format": self.print_format,
			"is_default": self.is_default,
			"source": self.source,
			"category": self.category,
			"paper_size": self.paper_size,
			"orientation": self.orientation,
			"description": self.description,
			"enabled": self.enabled,
			"managed": bool(version_info.get("managed")) if version_info else False,
			"template_version": version_info.get("version") if version_info else None,
			"template_hash": version_info.get("hash") if version_info else None,
			"restricted": bool(self.allowed_roles),
			"allowed_roles": list(self.allowed_roles),
		}


@dataclass(frozen=True)
class PrintDocumentDefinition:
	doctype: str
	label: str
	module: str
	capabilities: tuple[str, ...] = ("preview", "download_pdf", "archive_pdf")

	def as_dict(self):
		templates = get_print_template_options(self.doctype)
		return {
			"doctype": self.doctype,
			"label": self.label,
			"module": self.module,
			"capabilities": list(self.capabilities),
			"templates": templates,
			"default_template": resolve_print_template(self.doctype)["key"],
		}


_PRINT_DOCUMENT_REGISTRY: dict[str, PrintDocumentDefinition] = {
	"Sales Invoice": PrintDocumentDefinition(doctype="Sales Invoice", label="销售发票", module="sales"),
	"Purchase Invoice": PrintDocumentDefinition(doctype="Purchase Invoice", label="采购发票", module="purchase"),
	"Purchase Receipt": PrintDocumentDefinition(doctype="Purchase Receipt", label="采购收货单", module="purchase"),
	"Sales Order": PrintDocumentDefinition(doctype="Sales Order", label="销售订单", module="sales"),
	"Purchase Order": PrintDocumentDefinition(doctype="Purchase Order", label="采购订单", module="purchase"),
	"Delivery Note": PrintDocumentDefinition(doctype="Delivery Note", label="发货单", module="sales"),
	"Payment Entry": PrintDocumentDefinition(doctype="Payment Entry", label="收付款凭证", module="finance"),
}


_PRINT_TEMPLATE_REGISTRY: dict[str, tuple[PrintTemplateDefinition, ...]] = {
	"Sales Invoice": (
		PrintTemplateDefinition(
			key="standard",
			label="标准发票",
			print_format="myapp Sales Invoice Standard",
			is_default=True,
			source="myapp",
			category="external",
			description="面向客户的正式发票模板，包含购方、销方、明细和金额大写。",
		),
		PrintTemplateDefinition(
			key="finance",
			label="财务留档",
			print_format="myapp Sales Invoice Finance",
			source="myapp",
			category="finance",
			description="面向财务复核和归档的销售发票模板。",
			allowed_roles=("Accounts Manager", "Accounts User"),
		),
	),
	"Purchase Invoice": (
		PrintTemplateDefinition(
			key="standard",
			label="标准采购发票",
			print_format="myapp Purchase Invoice Standard",
			is_default=True,
			source="myapp",
			category="external",
			description="面向供应商核对的正式采购发票模板。",
		),
		PrintTemplateDefinition(
			key="finance",
			label="财务留档",
			print_format="myapp Purchase Invoice Finance",
			source="myapp",
			category="finance",
			description="面向财务复核和归档的采购发票模板。",
			allowed_roles=("Accounts Manager", "Accounts User"),
		),
	),
	"Purchase Receipt": (
		PrintTemplateDefinition(
			key="standard",
			label="标准采购收货单",
			print_format="myapp Purchase Receipt Standard",
			is_default=True,
			source="myapp",
			category="warehouse",
			description="采购收货正式模板，兼顾供应商信息、仓库和金额。",
		),
		PrintTemplateDefinition(
			key="warehouse",
			label="仓库执行版",
			print_format="myapp Purchase Receipt Warehouse",
			source="myapp",
			category="warehouse",
			description="面向仓库收货、复核和入库留档的执行模板。",
			allowed_roles=("Stock Manager", "Stock User", "Purchase Manager", "Purchase User"),
		),
	),
	"Sales Order": (
		PrintTemplateDefinition(
			key="standard",
			label="标准销售订单",
			print_format="myapp Sales Order Standard",
			is_default=True,
			source="myapp",
			category="external",
			description="面向客户确认和销售留档的正式销售订单模板。",
		),
		PrintTemplateDefinition(
			key="external",
			label="客户确认版",
			print_format="myapp Sales Order External",
			source="myapp",
			category="external",
			description="面向客户确认、对账和外部沟通的销售订单模板。",
			allowed_roles=("Sales Manager", "Sales User"),
		),
	),
	"Purchase Order": (
		PrintTemplateDefinition(
			key="standard",
			label="标准采购订单",
			print_format="myapp Purchase Order Standard",
			is_default=True,
			source="myapp",
			category="external",
			description="面向供应商确认和采购留档的正式采购订单模板。",
		),
		PrintTemplateDefinition(
			key="external",
			label="供应商确认版",
			print_format="myapp Purchase Order External",
			source="myapp",
			category="external",
			description="面向供应商确认、对账和外部沟通的采购订单模板。",
			allowed_roles=("Purchase Manager", "Purchase User"),
		),
	),
	"Delivery Note": (
		PrintTemplateDefinition(
			key="standard",
			label="标准发货单",
			print_format="myapp Delivery Note Standard",
			is_default=True,
			source="myapp",
			category="warehouse",
			description="销售发货正式模板，兼顾客户信息、出库复核和金额。",
		),
		PrintTemplateDefinition(
			key="warehouse",
			label="仓库执行版",
			print_format="myapp Delivery Note Warehouse",
			source="myapp",
			category="warehouse",
			description="面向仓库拣货、发货和复核的执行模板。",
			allowed_roles=("Stock Manager", "Stock User", "Sales Manager", "Sales User"),
		),
	),
	"Payment Entry": (
		PrintTemplateDefinition(
			key="standard",
			label="标准收付款凭证",
			print_format="myapp Payment Entry Standard",
			is_default=True,
			source="myapp",
			category="finance",
			description="收款、付款、退款和内部转账的标准凭证模板。",
			allowed_roles=("Accounts Manager", "Accounts User"),
		),
		PrintTemplateDefinition(
			key="finance",
			label="财务核销版",
			print_format="myapp Payment Entry Finance",
			source="myapp",
			category="finance",
			description="强化账户方向、核销明细、差额和制单信息的财务模板。",
			allowed_roles=("Accounts Manager", "Accounts User"),
		),
	),
}


def get_supported_print_doctypes():
	return tuple(_PRINT_TEMPLATE_REGISTRY.keys())


def get_print_doctype_options():
	options = []
	for doctype in get_supported_print_doctypes():
		if not get_print_template_options(doctype):
			continue
		options.append(
			_PRINT_DOCUMENT_REGISTRY.get(
				doctype,
				PrintDocumentDefinition(doctype=doctype, label=doctype, module="unknown"),
			).as_dict()
		)
	return options


def get_print_template_options(doctype: str):
	return [
		item.as_dict()
		for item in _get_doctype_template_definitions(doctype)
		if item.enabled and _is_template_allowed_for_current_user(item)
	]


def resolve_print_template(doctype: str, template_key: str | None = None):
	definitions = _get_doctype_template_definitions(doctype)
	if not definitions:
		frappe.throw(_("暂不支持该单据类型的打印。"))

	if template_key:
		resolved_key = template_key.strip()
		for item in definitions:
			if item.enabled and item.key == resolved_key and _is_template_allowed_for_current_user(item):
				return item.as_dict()
		frappe.throw(_("所选打印模板不存在或未启用。"))

	configured_default = _get_configured_default_template_key(doctype)
	if configured_default:
		for item in definitions:
			if item.enabled and item.key == configured_default and _is_template_allowed_for_current_user(item):
				return item.as_dict()

	for item in definitions:
		if item.enabled and item.is_default and _is_template_allowed_for_current_user(item):
			return item.as_dict()

	for item in definitions:
		if item.enabled and _is_template_allowed_for_current_user(item):
			return item.as_dict()

	frappe.throw(_("该单据类型没有启用的打印模板。"))


def _get_doctype_template_definitions(doctype: str):
	return _PRINT_TEMPLATE_REGISTRY.get((doctype or "").strip(), ())


def _is_template_allowed_for_current_user(template: PrintTemplateDefinition):
	if not template.allowed_roles:
		return True
	user_roles = _get_current_user_roles()
	if "System Manager" in user_roles:
		return True
	return bool(set(template.allowed_roles).intersection(user_roles))


def _get_current_user_roles():
	try:
		roles = frappe.get_roles()
	except Exception:
		return set()
	return set(roles or [])


def _get_configured_default_template_key(doctype: str):
	try:
		if not frappe.db.table_exists(PRINT_SETTING_TABLE):
			return None
		rows = frappe.db.sql(
			"""
			SELECT default_template
			FROM `tabMyApp Print Setting`
			WHERE reference_doctype = %s AND enabled = 1
			LIMIT 1
			""",
			((doctype or "").strip(),),
			as_dict=True,
		)
	except Exception:
		return None
	if not rows:
		return None
	return (rows[0].get("default_template") or "").strip() or None


def _get_template_version_info(print_format: str | None):
	try:
		from myapp.printing.templates import get_managed_print_format_version
	except Exception:
		return None
	return get_managed_print_format_version(print_format)
