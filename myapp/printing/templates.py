from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

import frappe


@dataclass(frozen=True)
class ManagedPrintFormatDefinition:
	name: str
	doctype: str
	module: str
	html_path: str
	css_path: str | None = None
	print_format_type: str = "Jinja"
	custom_format: int = 1
	print_format_builder: int = 0
	raw_printing: int = 0
	standard: str = "No"
	disabled: int = 0


_TEMPLATES_DIR = Path(__file__).with_name("templates")
_MANAGED_PRINT_FORMATS: dict[str, ManagedPrintFormatDefinition] = {
	"myapp Sales Invoice Standard": ManagedPrintFormatDefinition(
		name="myapp Sales Invoice Standard",
		doctype="Sales Invoice",
		module="myapp",
		html_path="sales_invoice_standard.html",
	),
	"myapp Purchase Invoice Standard": ManagedPrintFormatDefinition(
		name="myapp Purchase Invoice Standard",
		doctype="Purchase Invoice",
		module="myapp",
		html_path="purchase_invoice_standard.html",
	),
	"myapp Purchase Receipt Standard": ManagedPrintFormatDefinition(
		name="myapp Purchase Receipt Standard",
		doctype="Purchase Receipt",
		module="myapp",
		html_path="purchase_receipt_standard.html",
	),
	"myapp Delivery Note Standard": ManagedPrintFormatDefinition(
		name="myapp Delivery Note Standard",
		doctype="Delivery Note",
		module="myapp",
		html_path="delivery_note_standard.html",
	),
}


def ensure_managed_print_format(print_format_name: str | None):
	if not print_format_name:
		return None

	definition = _MANAGED_PRINT_FORMATS.get(print_format_name)
	if not definition:
		return None

	html = _read_template_file(definition.html_path)
	css = _read_template_file(definition.css_path) if definition.css_path else ""

	existing_name = frappe.db.exists("Print Format", definition.name)
	if existing_name:
		doc = frappe.get_doc("Print Format", definition.name)
	else:
		doc = frappe.new_doc("Print Format")
		doc.name = definition.name

	updated = False
	for fieldname, value in (
		("doc_type", definition.doctype),
		("module", definition.module),
		("standard", definition.standard),
		("disabled", definition.disabled),
		("custom_format", definition.custom_format),
		("print_format_builder", definition.print_format_builder),
		("raw_printing", definition.raw_printing),
		("print_format_type", definition.print_format_type),
		("html", html),
		("css", css),
	):
		if getattr(doc, fieldname, None) != value:
			setattr(doc, fieldname, value)
			updated = True

	if not existing_name:
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return doc

	if updated:
		doc.save(ignore_permissions=True)
		frappe.db.commit()

	return doc


def _read_template_file(filename: str):
	return (_TEMPLATES_DIR / filename).read_text(encoding="utf-8")
