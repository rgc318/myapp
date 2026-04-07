from __future__ import annotations

import argparse

import frappe

from myapp.services.media_service import cleanup_expired_temporary_item_images


def run(*, older_than_hours: int = 24, commit: bool = False):
	result = cleanup_expired_temporary_item_images(older_than_hours=older_than_hours)
	if commit and result["data"]["deleted_count"]:
		frappe.db.commit()

	print("CLEANUP_TEMPORARY_ITEM_IMAGES")
	print("  folder:", result["data"]["folder"])
	print("  retention_hours:", result["data"]["retention_hours"])
	print("  deleted_count:", result["data"]["deleted_count"])
	print("  skipped_recent_count:", result["data"]["skipped_recent_count"])
	print("  deleted_files:", ", ".join(result["data"]["deleted_files"]) or "-")
	print("  skipped_recent_files:", ", ".join(result["data"]["skipped_recent_files"]) or "-")


def main():
	parser = argparse.ArgumentParser(description="Clean expired temporary item images.")
	parser.add_argument("--site", default="localhost", help="Frappe site name.")
	parser.add_argument("--older-than-hours", type=int, default=24, help="Delete temp files older than this many hours.")
	parser.add_argument("--commit", action="store_true", help="Persist deletions to the database.")
	args = parser.parse_args()
	frappe.init(site=args.site, sites_path="/home/frappe/frappe-bench/sites")
	frappe.connect()
	try:
		run(older_than_hours=args.older_than_hours, commit=args.commit)
	finally:
		frappe.destroy()


if __name__ == "__main__":
	main()
