from __future__ import annotations


AI_RUNTIME_PROTOCOL_VERSION = "ai-runtime-contract-v1"
AI_RUNTIME_CLIENT_CAPABILITIES = (
	"release-manifest-v1",
	"runtime-response-metadata-v1",
	"structured-contract-errors-v1",
)

AI_RUNTIME_SCHEMA_FAMILIES = {
	"agent": ("agent-runtime-v1",),
	"chat": ("chat-v1",),
	"intent_parse": ("intent-parse-v1",),
	"inventory_adjustment_draft": ("inventory-adjustment-draft-v1",),
	"product_setup_draft": ("product-setup-draft-v1",),
	"purchase_order_draft": ("purchase-order-draft-v1",),
	"sales_order_draft": ("sales-order-draft-v1",),
}

AI_RUNTIME_SCENARIO_SCHEMA_FAMILIES = {
	"general": ("chat", "agent"),
	"intent_parse": ("intent_parse",),
	"product_search": ("chat", "agent"),
	"order_query": ("chat", "agent"),
	"report_summary": ("chat", "agent"),
	"sales_order_draft": ("sales_order_draft",),
	"purchase_order_draft": ("purchase_order_draft",),
	"inventory_adjustment_draft": ("inventory_adjustment_draft",),
	"product_setup_draft": ("product_setup_draft",),
}

# Prompt revisions remain an audit/resume fact. They are no longer a fresh-request
# compatibility requirement under ai-runtime-contract-v1.
AI_RUNTIME_EXPECTED_PROMPT_VERSIONS = {
	"general": "erp-readonly-v11",
	"intent_parse": "erp-intent-v8",
	"product_search": "erp-readonly-v11",
	"order_query": "erp-readonly-v11",
	"report_summary": "erp-readonly-v11",
	"sales_order_draft": "sales-order-draft-v5",
	"purchase_order_draft": "purchase-order-draft-v5",
	"inventory_adjustment_draft": "inventory-adjustment-draft-v3",
	"product_setup_draft": "product-setup-draft-v7",
}


class AiRuntimeResponseMismatch(ValueError):
	def __init__(self, *, code: str, details: dict):
		self.code = code
		self.details = details
		super().__init__("AI Orchestrator response metadata is incompatible with Backend")


def ai_runtime_request_contract(schema_family: str) -> dict:
	return {
		"protocol_version": AI_RUNTIME_PROTOCOL_VERSION,
		"supported_schema_versions": list(AI_RUNTIME_SCHEMA_FAMILIES[schema_family]),
		"client_capabilities": list(AI_RUNTIME_CLIENT_CAPABILITIES),
	}


def validate_ai_runtime_response(result: dict, *, schema_family: str) -> dict:
	expected_schemas = AI_RUNTIME_SCHEMA_FAMILIES[schema_family]
	actual_protocol = str(result.get("protocol_version") or "").strip() or None
	actual_schema = str(result.get("schema_version") or "").strip() or None
	prompt_version = str(result.get("prompt_version") or "").strip() or None
	runtime_revision = str(result.get("runtime_revision") or "").strip() or None
	release_id = str(result.get("release_id") or "").strip() or None
	if actual_protocol != AI_RUNTIME_PROTOCOL_VERSION:
		raise AiRuntimeResponseMismatch(
			code="AI_RUNTIME_CONTRACT_MISMATCH",
			details={
				"expected_protocol_version": AI_RUNTIME_PROTOCOL_VERSION,
				"actual_protocol_version": actual_protocol,
			},
		)
	if actual_schema not in expected_schemas:
		raise AiRuntimeResponseMismatch(
			code="AI_SCHEMA_VERSION_MISMATCH",
			details={
				"schema_family": schema_family,
				"expected_schema_versions": list(expected_schemas),
				"actual_schema_version": actual_schema,
			},
		)
	if not prompt_version or not runtime_revision or not release_id:
		raise AiRuntimeResponseMismatch(
			code="AI_RUNTIME_CONTRACT_MISMATCH",
			details={
				"missing_response_metadata": [
					key for key, value in {
						"prompt_version": prompt_version,
						"runtime_revision": runtime_revision,
						"release_id": release_id,
					}.items() if not value
				],
			},
		)
	return {
		"protocol_version": actual_protocol,
		"schema_version": actual_schema,
		"prompt_version": prompt_version,
		"runtime_revision": runtime_revision,
		"release_id": release_id,
	}


def evaluate_ai_runtime_compatibility(runtime_status: dict) -> dict:
	actual_protocol = str(runtime_status.get("protocol_version") or "").strip() or None
	runtime_ready = runtime_status.get("ready") is True
	runtime_state = str(runtime_status.get("status") or "").strip() or "unknown"
	actual_schemas = (
		dict(runtime_status.get("schema_versions"))
		if isinstance(runtime_status.get("schema_versions"), dict)
		else {}
	)
	actual_prompts = (
		dict(runtime_status.get("prompt_versions"))
		if isinstance(runtime_status.get("prompt_versions"), dict)
		else {}
	)
	protocol_match = actual_protocol == AI_RUNTIME_PROTOCOL_VERSION
	families = {}
	for family, expected_versions in AI_RUNTIME_SCHEMA_FAMILIES.items():
		actual_versions = actual_schemas.get(family)
		if not isinstance(actual_versions, list):
			actual_versions = []
		actual_versions = [str(value).strip() for value in actual_versions if str(value).strip()]
		compatible_versions = [value for value in expected_versions if value in actual_versions]
		families[family] = {
			"status": "ready" if compatible_versions else "blocked",
			"code": None if compatible_versions else "AI_SCHEMA_VERSION_MISMATCH",
			"expected_versions": list(expected_versions),
			"actual_versions": actual_versions,
			"selected_version": compatible_versions[0] if compatible_versions else None,
		}

	scenarios = {}
	for scenario, required_families in AI_RUNTIME_SCENARIO_SCHEMA_FAMILIES.items():
		blocked_families = [family for family in required_families if families[family]["status"] != "ready"]
		actual_prompt = str(actual_prompts.get(scenario) or "").strip() or None
		scenarios[scenario] = {
			"status": "blocked" if blocked_families else "ready",
			"code": "AI_SCHEMA_VERSION_MISMATCH" if blocked_families else None,
			"required_schema_families": list(required_families),
			"blocked_schema_families": blocked_families,
			"prompt_version": actual_prompt,
			"expected_prompt_version": AI_RUNTIME_EXPECTED_PROMPT_VERSIONS.get(scenario),
		}

	schemas_match = all(row["status"] == "ready" for row in families.values())
	ready = runtime_ready and protocol_match and schemas_match
	if not protocol_match:
		code = "AI_RUNTIME_CONTRACT_MISMATCH"
	elif not schemas_match:
		code = "AI_SCHEMA_VERSION_MISMATCH"
	elif not runtime_ready:
		code = "AI_RUNTIME_NOT_READY"
	else:
		code = None
	status = "blocked" if not ready else "degraded" if runtime_state == "degraded" else "ready"
	return {
		"ready": ready,
		"status": status,
		"code": code,
		"retryable": False if code else None,
		"protocol": {
			"status": "ready" if protocol_match else "blocked",
			"expected_version": AI_RUNTIME_PROTOCOL_VERSION,
			"actual_version": actual_protocol,
		},
		"runtime": {
			"status": runtime_state,
			"revision": str(runtime_status.get("runtime_revision") or "").strip() or None,
			"release_id": str(runtime_status.get("release_id") or "").strip() or None,
		},
		"schema_families": families,
		"scenarios": scenarios,
	}
