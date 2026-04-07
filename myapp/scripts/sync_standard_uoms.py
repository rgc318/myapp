from __future__ import annotations

import argparse

import frappe

from myapp.services.uom_service import _collect_uom_references
from myapp.utils.standard_uoms import STANDARD_UOMS, TEST_UOM_PREFIXES


def _find_test_uoms() -> list[str]:
	rows = frappe.get_all("UOM", fields=["name"], filters={"name": ["like", "HTTP-%"]}, limit_page_length=0)
	return [row.name for row in rows if any(row.name.startswith(prefix) for prefix in TEST_UOM_PREFIXES)]


def _delete_test_uoms(*, commit: bool) -> dict[str, list[str]]:
	deleted: list[str] = []
	skipped: list[str] = []
	disabled: list[str] = []

	for name in _find_test_uoms():
		usage_summary = _collect_uom_references(name)
		if usage_summary.get("total_references"):
			doc = frappe.get_doc("UOM", name)
			if int(getattr(doc, "enabled", 1) or 0) != 0:
				doc.enabled = 0
				doc.save()
			disabled.append(name)
			continue
		doc = frappe.get_doc("UOM", name)
		doc.delete()
		deleted.append(name)

	if commit and deleted:
		frappe.db.commit()

	return {"deleted": deleted, "disabled": disabled, "skipped": skipped}


def _upsert_standard_uoms(*, commit: bool) -> dict[str, list[str]]:
	created: list[str] = []
	updated: list[str] = []
	skipped_rule_change: list[str] = []

	for row in STANDARD_UOMS:
		exists = frappe.db.exists("UOM", row["name"])
		if not exists:
			doc = frappe.new_doc("UOM")
			doc.uom_name = row["uom_name"]
			doc.enabled = 1
			doc.must_be_whole_number = row["must_be_whole_number"]
			doc.symbol = row["symbol"]
			doc.description = row["description"]
			doc.insert()
			created.append(row["name"])
			continue

		doc = frappe.get_doc("UOM", row["name"])
		changed = False

		if (getattr(doc, "symbol", None) or None) != row["symbol"]:
			doc.symbol = row["symbol"]
			changed = True

		if (getattr(doc, "description", None) or "") != row["description"]:
			doc.description = row["description"]
			changed = True

		if int(getattr(doc, "enabled", 1) or 0) != 1:
			doc.enabled = 1
			changed = True

		current_whole = int(getattr(doc, "must_be_whole_number", 0) or 0)
		if current_whole != row["must_be_whole_number"]:
			usage_summary = _collect_uom_references(row["name"])
			if usage_summary.get("total_references"):
				skipped_rule_change.append(row["name"])
			else:
				doc.must_be_whole_number = row["must_be_whole_number"]
				changed = True

		if changed:
			doc.save()
			updated.append(row["name"])

	if commit and (created or updated):
		frappe.db.commit()

	return {
		"created": created,
		"updated": updated,
		"skipped_rule_change": skipped_rule_change,
	}


def run(*, commit: bool = False):
	delete_result = _delete_test_uoms(commit=commit)
	upsert_result = _upsert_standard_uoms(commit=commit)

	print("DELETE_TEST_UOMS")
	print("  deleted:", ", ".join(delete_result["deleted"]) or "-")
	print("  disabled_referenced:", ", ".join(delete_result["disabled"]) or "-")
	print("  skipped:", ", ".join(delete_result["skipped"]) or "-")
	print("UPSERT_STANDARD_UOMS")
	print("  created:", ", ".join(upsert_result["created"]) or "-")
	print("  updated:", ", ".join(upsert_result["updated"]) or "-")
	print("  skipped_rule_change:", ", ".join(upsert_result["skipped_rule_change"]) or "-")


def main():
	parser = argparse.ArgumentParser(description="Delete HTTP test UOMs and sync standard business UOMs.")
	parser.add_argument("--site", default="localhost", help="Frappe site name.")
	parser.add_argument("--commit", action="store_true", help="Persist changes to the database.")
	args = parser.parse_args()
	frappe.init(site=args.site, sites_path="/home/frappe/frappe-bench/sites")
	frappe.connect()
	try:
		run(commit=args.commit)
	finally:
		frappe.destroy()


if __name__ == "__main__":
	main()
