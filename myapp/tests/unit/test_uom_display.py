from unittest import TestCase

from myapp.utils.uom_display import build_uom_input_aliases, resolve_uom_display_name, sort_uom_rows


class TestUomDisplay(TestCase):
	def test_resolve_uom_display_name_uses_standard_catalog_for_common_business_units(self):
		self.assertEqual(resolve_uom_display_name("Nos"), "件")
		self.assertEqual(resolve_uom_display_name("Kg"), "千克")
		self.assertEqual(resolve_uom_display_name("Month"), "月")
		self.assertEqual(resolve_uom_display_name("Jin"), "斤")

	def test_resolve_uom_display_name_prefers_chinese_symbol(self):
		self.assertEqual(resolve_uom_display_name("Box", symbol="箱"), "箱")

	def test_resolve_uom_display_name_handles_existing_english_symbol_units(self):
		self.assertEqual(resolve_uom_display_name("Litre", symbol="L"), "升")
		self.assertEqual(resolve_uom_display_name("Yard", symbol="yd"), "码")

	def test_build_uom_input_aliases_includes_code_display_symbol_and_common_aliases(self):
		aliases = build_uom_input_aliases("Box", uom_name="Box", symbol="箱")

		self.assertTrue({"Box", "BOX", "BOXES", "箱"}.issubset(aliases))

	def test_sort_uom_rows_prioritizes_box_and_nos_stably(self):
		rows = [
			{"uom": "Kg", "uom_display": "千克"},
			{"uom": "Nos", "uom_display": "件"},
			{"uom": "Bottle", "uom_display": "瓶"},
			{"uom": "Box", "uom_display": "箱"},
		]

		self.assertEqual(
			[row["uom"] for row in sort_uom_rows(rows)],
			["Box", "Nos", "Kg", "Bottle"],
		)
