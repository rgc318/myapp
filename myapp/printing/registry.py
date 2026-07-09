from __future__ import annotations

from dataclasses import dataclass

import frappe
from frappe import _


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
		}


@dataclass(frozen=True)
class PrintDocumentDefinition:
	doctype: str
	label: str
	module: str
	capabilities: tuple[str, ...] = ("preview", "download_pdf", "archive_pdf")

	def as_dict(self):
		return {
			"doctype": self.doctype,
			"label": self.label,
			"module": self.module,
			"capabilities": list(self.capabilities),
			"templates": get_print_template_options(self.doctype),
			"default_template": resolve_print_template(self.doctype)["key"],
		}


_PRINT_DOCUMENT_REGISTRY: dict[str, PrintDocumentDefinition] = {
	"Sales Invoice": PrintDocumentDefinition(doctype="Sales Invoice", label="销售发票", module="sales"),
	"Purchase Invoice": PrintDocumentDefinition(doctype="Purchase Invoice", label="采购发票", module="purchase"),
	"Purchase Receipt": PrintDocumentDefinition(doctype="Purchase Receipt", label="采购收货单", module="purchase"),
	"Sales Order": PrintDocumentDefinition(doctype="Sales Order", label="销售订单", module="sales"),
	"Purchase Order": PrintDocumentDefinition(doctype="Purchase Order", label="采购订单", module="purchase"),
	"Delivery Note": PrintDocumentDefinition(doctype="Delivery Note", label="发货单", module="sales"),
}


_PRINT_TEMPLATE_REGISTRY: dict[str, tuple[PrintTemplateDefinition, ...]] = {
	"Sales Invoice": (
		PrintTemplateDefinition(
			key="standard",
			label="标准发票",
			print_format="myapp Sales Invoice Standard",
			is_default=True,
			source="myapp",
		),
	),
	"Purchase Invoice": (
		PrintTemplateDefinition(
			key="standard",
			label="标准采购发票",
			print_format="myapp Purchase Invoice Standard",
			is_default=True,
			source="myapp",
		),
	),
	"Purchase Receipt": (
		PrintTemplateDefinition(
			key="standard",
			label="标准采购收货单",
			print_format="myapp Purchase Receipt Standard",
			is_default=True,
			source="myapp",
		),
	),
	"Sales Order": (
		PrintTemplateDefinition(
			key="standard",
			label="标准销售订单",
			print_format="myapp Sales Order Standard",
			is_default=True,
			source="myapp",
		),
	),
	"Purchase Order": (
		PrintTemplateDefinition(
			key="standard",
			label="标准采购订单",
			print_format="myapp Purchase Order Standard",
			is_default=True,
			source="myapp",
		),
	),
	"Delivery Note": (
		PrintTemplateDefinition(
			key="standard",
			label="标准发货单",
			print_format="myapp Delivery Note Standard",
			is_default=True,
			source="myapp",
		),
	),
}


def get_supported_print_doctypes():
	return tuple(_PRINT_TEMPLATE_REGISTRY.keys())


def get_print_doctype_options():
	return [
		_PRINT_DOCUMENT_REGISTRY.get(
			doctype,
			PrintDocumentDefinition(doctype=doctype, label=doctype, module="unknown"),
		).as_dict()
		for doctype in get_supported_print_doctypes()
		if _get_doctype_template_definitions(doctype)
	]


def get_print_template_options(doctype: str):
	return [
		item.as_dict()
		for item in _get_doctype_template_definitions(doctype)
		if item.enabled
	]


def resolve_print_template(doctype: str, template_key: str | None = None):
	definitions = _get_doctype_template_definitions(doctype)
	if not definitions:
		frappe.throw(_("暂不支持该单据类型的打印。"))

	if template_key:
		resolved_key = template_key.strip()
		for item in definitions:
			if item.enabled and item.key == resolved_key:
				return item.as_dict()
		frappe.throw(_("所选打印模板不存在或未启用。"))

	for item in definitions:
		if item.enabled and item.is_default:
			return item.as_dict()

	for item in definitions:
		if item.enabled:
			return item.as_dict()

	frappe.throw(_("该单据类型没有启用的打印模板。"))


def _get_doctype_template_definitions(doctype: str):
	return _PRINT_TEMPLATE_REGISTRY.get((doctype or "").strip(), ())


def _get_template_version_info(print_format: str | None):
	try:
		from myapp.printing.templates import get_managed_print_format_version
	except Exception:
		return None
	return get_managed_print_format_version(print_format)
