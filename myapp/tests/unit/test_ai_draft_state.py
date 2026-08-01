from unittest import TestCase

from myapp.services.ai_draft_state import (
	build_draft_state,
	classify_value,
	derive_patch_from_submission,
	merge_baseline_patch,
	source_changed,
	stable_hash,
)


class TestAiDraftState(TestCase):
	def test_value_state_distinguishes_missing_and_explicit_zero(self):
		self.assertEqual(classify_value(None), "missing")
		self.assertEqual(classify_value(""), "missing")
		self.assertEqual(classify_value(0), "explicit_zero")
		self.assertEqual(classify_value(0.0), "explicit_zero")
		self.assertEqual(classify_value(False), "known")

	def test_stable_hash_ignores_dictionary_order(self):
		self.assertEqual(stable_hash({"a": 1, "b": 2}), stable_hash({"b": 2, "a": 1}))

	def test_merge_preserves_explicit_null_and_zero_patch(self):
		self.assertEqual(
			merge_baseline_patch({"price": 5, "brand": "A"}, {"price": 0, "brand": None}),
			{"price": 0, "brand": None},
		)

	def test_submission_only_changes_fields_edited_from_previous_effective_state(self):
		patch = derive_patch_from_submission(
			baseline={"price": 5, "brand": "A"},
			previous_patch={"price": 6},
			previous_effective={"price": 6, "brand": "A"},
			submitted={"price": 6, "brand": "B"},
			fields=("price", "brand"),
		)
		self.assertEqual(patch, {"price": 6, "brand": "B"})

	def test_reverting_to_baseline_removes_patch(self):
		patch = derive_patch_from_submission(
			baseline={"price": 5},
			previous_patch={"price": 6},
			previous_effective={"price": 6},
			submitted={"price": 5},
			fields=("price",),
		)
		self.assertEqual(patch, {})

	def test_source_change_uses_authoritative_source_hash(self):
		previous = build_draft_state(
			operation="update", entity_doctype="Item", entity_name="ITEM-1",
			baseline={"price": 5}, source_facts={"modified": "a", "price": 5},
		)
		current = build_draft_state(
			operation="update", entity_doctype="Item", entity_name="ITEM-1",
			baseline={"price": 5}, source_facts={"modified": "b", "price": 5},
		)
		self.assertTrue(source_changed(previous, current))
