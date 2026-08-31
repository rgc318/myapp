from unittest import TestCase
from unittest.mock import patch

import frappe

from myapp.utils.uom import resolve_item_quantity_to_stock, resolve_item_uom
from myapp.utils.uom_display import build_uom_input_aliases


def _context_map(*, include_case=False, whole_number=True):
	conversion_factors = {"Nos": 1, "Box": 24}
	metadata = {
		"Nos": {
			"aliases": build_uom_input_aliases("Nos", symbol="件"),
			"must_be_whole_number": True,
			"uom_display": "件",
		},
		"Box": {
			"aliases": build_uom_input_aliases("Box", symbol="箱"),
			"must_be_whole_number": whole_number,
			"uom_display": "箱",
		},
	}
	if include_case:
		conversion_factors["Case"] = 12
		metadata["Case"] = {
			"aliases": build_uom_input_aliases("Case", symbol="箱"),
			"must_be_whole_number": True,
			"uom_display": "箱",
		}
	return {
		"ITEM-001": {
			"conversion_factors": conversion_factors,
			"stock_uom": "Nos",
			"uom_metadata": metadata,
		}
	}


class TestUom(TestCase):
	def test_resolve_item_uom_accepts_chinese_display_alias(self):
		resolved = resolve_item_uom(
			item_code="ITEM-001",
			uom="箱",
			uom_context_map=_context_map(),
		)

		self.assertEqual(resolved["uom"], "Box")
		self.assertEqual(resolved["conversion_factor"], 24)

	def test_resolve_item_uom_rejects_unconfigured_alias_without_fallback(self):
		with patch("myapp.utils.uom.frappe.throw", side_effect=frappe.ValidationError), self.assertRaises(
			frappe.ValidationError
		):
			resolve_item_uom(
				item_code="ITEM-001",
				uom="托盘",
				uom_context_map=_context_map(),
			)

	def test_resolve_item_uom_rejects_ambiguous_display_alias(self):
		with patch("myapp.utils.uom.frappe.throw", side_effect=frappe.ValidationError), self.assertRaises(
			frappe.ValidationError
		):
			resolve_item_uom(
				item_code="ITEM-001",
				uom="箱",
				uom_context_map=_context_map(include_case=True),
			)

	def test_resolve_item_quantity_to_stock_converts_display_alias(self):
		resolved = resolve_item_quantity_to_stock(
			item_code="ITEM-001",
			qty=1000,
			uom="箱",
			uom_context_map=_context_map(),
		)

		self.assertEqual(resolved["uom"], "Box")
		self.assertEqual(resolved["stock_uom"], "Nos")
		self.assertEqual(resolved["stock_qty"], 24000)

	def test_resolve_item_quantity_to_stock_enforces_whole_number_input(self):
		with patch("myapp.utils.uom.frappe.throw", side_effect=frappe.ValidationError), self.assertRaises(
			frappe.ValidationError
		):
			resolve_item_quantity_to_stock(
				item_code="ITEM-001",
				qty=0.5,
				uom="Box",
				uom_context_map=_context_map(),
			)
