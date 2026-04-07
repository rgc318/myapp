from unittest import TestCase

from myapp.utils.uom_display import resolve_uom_display_name


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
