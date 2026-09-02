import hashlib
import json

import frappe


DRAFT_TABLE = "tabMyApp AI Draft"
MESSAGE_TABLE = "tabMyApp AI Message"


def _add_column(doctype: str, table: str, column: str, definition: str):
	if frappe.db.table_exists(doctype) and not frappe.db.has_column(doctype, column):
		frappe.db.sql(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")


def _has_index(table: str, index_name: str) -> bool:
	return bool(
		frappe.db.sql(
			f"SHOW INDEX FROM `{table}` WHERE Key_name = %s",
			(index_name,),
			as_dict=True,
		)
	)


def _draft_target(draft_type: str, payload: dict) -> tuple[str | None, str | None]:
	if draft_type == "product_setup":
		item_code = str(payload.get("item_code") or "").strip() or None
		return "product_update", item_code
	if draft_type == "inventory_adjustment":
		items = payload.get("items") if isinstance(payload.get("items"), list) else []
		row = items[0] if items and isinstance(items[0], dict) else {}
		item_code = str(row.get("item_code") or "").strip() or None
		return "inventory_adjustment", item_code
	return None, None


def _active_key(*, owner: str, conversation: str, company: str, action: str, item_code: str) -> str:
	value = "\x1f".join((owner, conversation, company, action, "Item", item_code))
	return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _classify_action_drafts():
	if not frappe.db.table_exists("MyApp AI Draft"):
		return
	rows = frappe.db.sql(
		f"""
		SELECT name, owner, conversation, company, draft_type, status, version_no,
			payload_json, creation, modified
		FROM `{DRAFT_TABLE}`
		WHERE source_run LIKE 'AI-ACTION-%'
		ORDER BY modified DESC, creation DESC, name DESC
		""",
		as_dict=True,
	)
	groups: dict[tuple[str, str, str, str, str], list] = {}
	for row in rows:
		try:
			payload = json.loads(row.payload_json or "{}")
		except Exception:
			payload = {}
		action, item_code = _draft_target(row.draft_type, payload)
		if not action or not item_code:
			continue
		frappe.db.sql(
			f"""
			UPDATE `{DRAFT_TABLE}`
			SET origin_kind = 'ui_product_action', origin_action = %s,
				origin_entity_type = 'Item', origin_entity_name = %s
			WHERE name = %s
			""",
			(action, item_code, row.name),
		)
		if row.status == "draft":
			groups.setdefault(
				(row.owner, row.conversation, row.company or "", action, item_code),
				[],
			).append(row)

	for (owner, conversation, company, action, item_code), group in groups.items():
		canonical = next(
			(row for row in group if int(row.version_no or 0) > 1),
			group[0],
		)
		key = _active_key(
			owner=owner,
			conversation=conversation,
			company=company,
			action=action,
			item_code=item_code,
		)
		frappe.db.sql(
			f"UPDATE `{DRAFT_TABLE}` SET active_dedupe_key = %s WHERE name = %s",
			(key, canonical.name),
		)
		for duplicate in group[1:]:
			if int(duplicate.version_no or 0) == 1:
				frappe.db.sql(
					f"""
					UPDATE `{DRAFT_TABLE}`
					SET status = 'superseded', active_dedupe_key = NULL,
						superseded_by = %s, modified = NOW(6), modified_by = 'Administrator'
					WHERE name = %s AND status = 'draft' AND version_no = 1
					""",
					(canonical.name, duplicate.name),
				)


def _classify_action_messages():
	if not frappe.db.table_exists("MyApp AI Message") or not frappe.db.table_exists("MyApp AI Draft"):
		return
	rows = frappe.db.sql(
		f"""
		SELECT name, conversation, sequence_no, citations_json
		FROM `{MESSAGE_TABLE}`
		WHERE run_id IS NULL AND role = 'assistant'
			AND scenario IN ('product_setup_draft', 'inventory_adjustment_draft')
		ORDER BY conversation, sequence_no
		""",
		as_dict=True,
	)
	for row in rows:
		try:
			citations = json.loads(row.citations_json or "[]")
		except Exception:
			citations = []
		draft_ids = [
			str(citation.get("id") or "").strip()
			for citation in citations
			if isinstance(citation, dict) and citation.get("type") == "ai_draft"
		]
		if not draft_ids:
			continue
		placeholders = ", ".join(["%s"] * len(draft_ids))
		linked = frappe.db.sql(
			f"SELECT name FROM `{DRAFT_TABLE}` WHERE name IN ({placeholders}) AND source_run LIKE 'AI-ACTION-%%' LIMIT 1",
			tuple(draft_ids),
		)
		if not linked:
			continue
		frappe.db.sql(
			f"UPDATE `{MESSAGE_TABLE}` SET message_kind = 'activity' WHERE name = %s",
			(row.name,),
		)
		frappe.db.sql(
			f"""
			UPDATE `{MESSAGE_TABLE}`
			SET message_kind = 'activity'
			WHERE conversation = %s AND sequence_no = %s
				AND role = 'user' AND run_id IS NULL
			""",
			(row.conversation, int(row.sequence_no) - 1),
		)


def execute():
	for column, definition in (
		("origin_kind", "varchar(40) DEFAULT NULL AFTER `source_run`"),
		("origin_action", "varchar(40) DEFAULT NULL AFTER `origin_kind`"),
		("origin_entity_type", "varchar(80) DEFAULT NULL AFTER `origin_action`"),
		("origin_entity_name", "varchar(140) DEFAULT NULL AFTER `origin_entity_type`"),
		("active_dedupe_key", "varchar(64) DEFAULT NULL AFTER `origin_entity_name`"),
		("superseded_by", "varchar(140) DEFAULT NULL AFTER `active_dedupe_key`"),
	):
		_add_column("MyApp AI Draft", DRAFT_TABLE, column, definition)
	_add_column(
		"MyApp AI Message",
		MESSAGE_TABLE,
		"message_kind",
		"varchar(20) NOT NULL DEFAULT 'chat' AFTER `role`",
	)
	_classify_action_drafts()
	_classify_action_messages()
	# Frappe blocks implicit-commit DDL while data updates are pending.
	# Persist the reversible classifications before adding the final guard.
	frappe.db.commit()
	if frappe.db.table_exists("MyApp AI Draft") and not _has_index(
		DRAFT_TABLE, "uniq_myapp_ai_draft_active_dedupe",
	):
		frappe.db.sql(
			f"ALTER TABLE `{DRAFT_TABLE}` ADD UNIQUE KEY `uniq_myapp_ai_draft_active_dedupe` (`active_dedupe_key`)"
		)
	frappe.db.commit()
