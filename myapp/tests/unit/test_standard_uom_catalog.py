from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from myapp.patches import govern_ambiguous_packaging_uoms
from myapp.scripts.sync_standard_uoms import _upsert_standard_uoms
from myapp.utils.standard_uoms import STANDARD_UOM_BUSINESS_SELECTABLE_DEFAULTS


class TestStandardUomCatalog(TestCase):
	def test_box_is_the_only_default_selectable_box_style_uom(self):
		self.assertEqual(STANDARD_UOM_BUSINESS_SELECTABLE_DEFAULTS["Box"], 1)
		self.assertEqual(STANDARD_UOM_BUSINESS_SELECTABLE_DEFAULTS["Case"], 0)
		self.assertEqual(STANDARD_UOM_BUSINESS_SELECTABLE_DEFAULTS["Carton"], 0)

	@patch("myapp.scripts.sync_standard_uoms.STANDARD_UOM_BUSINESS_SELECTABLE_DEFAULTS", {"Case": 0})
	@patch(
		"myapp.scripts.sync_standard_uoms.STANDARD_UOMS",
		(
			{
				"name": "Case",
				"uom_name": "Case",
				"display_name": "箱装",
				"symbol": "箱装",
				"must_be_whole_number": 1,
				"description": "箱装商品计量单位。",
				"aliases": ("CASES",),
			},
		),
	)
	@patch("myapp.scripts.sync_standard_uoms.frappe")
	def test_sync_applies_catalog_default_when_creating_uom(self, mock_frappe):
		doc = MagicMock()
		doc.name = "Case"
		mock_frappe.db.exists.return_value = False
		mock_frappe.new_doc.return_value = doc

		result = _upsert_standard_uoms(commit=False)

		self.assertEqual(result["created"], ["Case"])
		self.assertEqual(doc.myapp_business_selectable, 0)
		self.assertEqual(doc.symbol, "箱装")
		doc.insert.assert_called_once_with()

	@patch("myapp.scripts.sync_standard_uoms.STANDARD_UOM_BUSINESS_SELECTABLE_DEFAULTS", {"Case": 0})
	@patch(
		"myapp.scripts.sync_standard_uoms.STANDARD_UOMS",
		(
			{
				"name": "Case",
				"uom_name": "Case",
				"display_name": "箱装",
				"symbol": "箱装",
				"must_be_whole_number": 1,
				"description": "箱装商品计量单位。",
				"aliases": ("CASES",),
			},
		),
	)
	@patch("myapp.scripts.sync_standard_uoms.frappe")
	def test_sync_preserves_existing_admin_business_selectable_choice(self, mock_frappe):
		doc = MagicMock()
		doc.symbol = "箱装"
		doc.description = "箱装商品计量单位。"
		doc.enabled = 1
		doc.myapp_business_selectable = 1
		doc.must_be_whole_number = 1
		mock_frappe.db.exists.return_value = True
		mock_frappe.get_doc.return_value = doc

		result = _upsert_standard_uoms(commit=False)

		self.assertEqual(result["updated"], [])
		doc.save.assert_not_called()
		self.assertEqual(doc.myapp_business_selectable, 1)

	@patch("myapp.patches.govern_ambiguous_packaging_uoms.frappe")
	def test_governance_patch_hides_ambiguous_defaults_without_deleting_uoms(
		self,
		mock_frappe,
	):
		mock_frappe.db.exists.return_value = True
		govern_ambiguous_packaging_uoms.execute()

		self.assertEqual(
			mock_frappe.db.set_value.call_args_list,
			[
				call(
					"UOM",
					"Case",
					{"myapp_business_selectable": 0, "symbol": "箱装"},
					update_modified=False,
				),
				call(
					"UOM",
					"Carton",
					{"myapp_business_selectable": 0, "symbol": "纸箱"},
					update_modified=False,
				),
			],
		)
