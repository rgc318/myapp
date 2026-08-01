from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from typing import Any


SCHEMA_VERSION = "ai-draft-state-v1"
MISSING = object()


def _json_default(value: Any):
	if isinstance(value, (date, datetime)):
		return value.isoformat()
	if isinstance(value, Decimal):
		return float(value)
	return str(value)


def stable_hash(value: Any) -> str:
	serialized = json.dumps(
		value,
		default=_json_default,
		ensure_ascii=False,
		sort_keys=True,
		separators=(",", ":"),
	)
	return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def classify_value(value: Any = MISSING, *, applicable: bool = True) -> str:
	if not applicable:
		return "not_applicable"
	if value is MISSING or value is None or value == "":
		return "missing"
	if isinstance(value, bool):
		return "known"
	if isinstance(value, (int, float, Decimal)) and value == 0:
		return "explicit_zero"
	return "known"


def field_fact(
	value: Any = MISSING,
	*,
	source: str,
	applicable: bool = True,
	status: str | None = None,
) -> dict:
	return {
		"status": status or classify_value(value, applicable=applicable),
		"source": source,
	}


def merge_baseline_patch(baseline: dict | None, patch: dict | None) -> dict:
	merged = deepcopy(baseline or {})
	for key, value in (patch or {}).items():
		merged[key] = deepcopy(value)
	return merged


def derive_patch_from_submission(
	*,
	baseline: dict | None,
	previous_patch: dict | None,
	previous_effective: dict | None,
	submitted: dict,
	fields: tuple[str, ...] | list[str],
) -> dict:
	"""Keep prior intent and only treat values changed from the shown draft as new intent."""
	baseline = baseline or {}
	patch = deepcopy(previous_patch or {})
	previous_effective = previous_effective or merge_baseline_patch(baseline, patch)
	for field in fields:
		if field not in submitted:
			continue
		value = submitted.get(field)
		if value == previous_effective.get(field):
			continue
		if value == baseline.get(field):
			patch.pop(field, None)
		else:
			patch[field] = deepcopy(value)
	return patch


def build_draft_state(
	*,
	operation: str,
	entity_doctype: str | None,
	entity_name: str | None,
	entity_modified: Any = None,
	observed_at: Any = None,
	baseline: dict | None = None,
	patch: dict | None = None,
	fields: dict | None = None,
	source_facts: dict | None = None,
) -> dict:
	baseline = deepcopy(baseline or {})
	patch = deepcopy(patch or {})
	effective = merge_baseline_patch(baseline, patch)
	source_facts = deepcopy(source_facts if source_facts is not None else baseline)
	return {
		"schema_version": SCHEMA_VERSION,
		"operation": operation,
		"entity": {
			"doctype": entity_doctype,
			"name": entity_name,
			"modified": _json_default(entity_modified) if entity_modified is not None else None,
		},
		"observed_at": _json_default(observed_at) if observed_at is not None else None,
		"source_hash": stable_hash(source_facts),
		"baseline": baseline,
		"patch": patch,
		"effective": effective,
		"fields": deepcopy(fields or {}),
	}


def source_changed(previous_state: dict | None, current_state: dict | None) -> bool:
	previous_hash = (previous_state or {}).get("source_hash")
	current_hash = (current_state or {}).get("source_hash")
	return bool(previous_hash and current_hash and previous_hash != current_hash)
