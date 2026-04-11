from __future__ import annotations

import argparse
import json
import re

import frappe


SKIP_PREFIXES = ("HTTP-", "链路-", "采购链路-", "RANGE-")
SPEC_PATTERN = re.compile(
    r"(?i)(?P<spec>\d+(?:\.\d+)?\s*(?:ml|l|g|kg|mg|cm|mm|m|pcs|pc|pack|袋|包|盒|箱|瓶|听|支|片))$"
)


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _infer_from_item_name(item_name: str) -> tuple[str | None, str | None]:
    normalized = _normalize_whitespace(item_name)
    if not normalized:
        return None, None

    match = SPEC_PATTERN.search(normalized)
    if not match:
        return normalized, None

    specification = _normalize_whitespace(match.group("spec"))
    nickname = _normalize_whitespace(normalized[: match.start()].rstrip("-_/ "))
    return (nickname or normalized), specification


@frappe.whitelist()
def run(commit: bool = False):
    commit_flag = frappe.utils.cint(commit) == 1 or commit is True
    rows = frappe.get_all(
        "Item",
        filters={"disabled": 0},
        fields=["name", "item_code", "item_name", "custom_nickname", "custom_specification"],
        order_by="modified desc",
        limit_page_length=0,
    )

    summary = {
        "scanned": 0,
        "skipped": 0,
        "nickname_updated": 0,
        "specification_updated": 0,
        "updated_items": [],
    }

    for row in rows:
        item_code = (row.get("item_code") or "").strip()
        if not item_code or item_code.startswith(SKIP_PREFIXES):
            summary["skipped"] += 1
            continue

        summary["scanned"] += 1
        item_name = row.get("item_name") or item_code
        current_nickname = (row.get("custom_nickname") or "").strip()
        current_specification = (row.get("custom_specification") or "").strip()
        inferred_nickname, inferred_specification = _infer_from_item_name(item_name)

        updates = {}
        if not current_nickname and inferred_nickname:
            updates["custom_nickname"] = inferred_nickname

        if not current_specification and inferred_specification:
            updates["custom_specification"] = inferred_specification

        if not updates:
            continue

        summary["updated_items"].append(
            {
                "item_code": item_code,
                "item_name": item_name,
                "updates": updates,
            }
        )

        if "custom_nickname" in updates:
            summary["nickname_updated"] += 1
        if "custom_specification" in updates:
            summary["specification_updated"] += 1

        if commit_flag:
            doc = frappe.get_doc("Item", row["name"])
            for fieldname, value in updates.items():
                doc.db_set(fieldname, value, update_modified=False)

    if commit_flag:
        frappe.db.commit()

    return summary


def main():
    parser = argparse.ArgumentParser(description="Backfill item nickname/specification from item_name.")
    parser.add_argument("--site", default="localhost", help="Frappe site name.")
    parser.add_argument("--commit", action="store_true", help="Persist changes to the database.")
    args = parser.parse_args()

    frappe.init(site=args.site, sites_path="/home/frappe/frappe-bench/sites")
    frappe.connect()
    try:
        result = run(commit=args.commit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        frappe.destroy()


if __name__ == "__main__":
    main()
