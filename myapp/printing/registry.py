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
			print_format=None,
			is_default=True,
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


def get_print_template_options(doctype: str):
	return [
		{
			"key": item.key,
			"label": item.label,
			"print_format": item.print_format,
			"is_default": item.is_default,
			"source": item.source,
		}
		for item in _get_doctype_template_definitions(doctype)
	]


def resolve_print_template(doctype: str, template_key: str | None = None):
	definitions = _get_doctype_template_definitions(doctype)
	if not definitions:
		frappe.throw(_("暂不支持该单据类型的打印。"))

	if template_key:
		resolved_key = template_key.strip()
		for item in definitions:
			if item.key == resolved_key:
				return {
					"key": item.key,
					"label": item.label,
					"print_format": item.print_format,
					"is_default": item.is_default,
					"source": item.source,
				}
		frappe.throw(_("所选打印模板不存在或未启用。"))

	for item in definitions:
		if item.is_default:
			return {
				"key": item.key,
				"label": item.label,
				"print_format": item.print_format,
				"is_default": item.is_default,
				"source": item.source,
			}

	item = definitions[0]
	return {
		"key": item.key,
		"label": item.label,
		"print_format": item.print_format,
		"is_default": item.is_default,
		"source": item.source,
	}


def _get_doctype_template_definitions(doctype: str):
	return _PRINT_TEMPLATE_REGISTRY.get((doctype or "").strip(), ())
