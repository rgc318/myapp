def success_response(
	*,
	message: str = "",
	data=None,
	meta: dict | None = None,
	code: str = "OK",
	status: str = "success",
):
	return {
		"ok": True,
		"status": status,
		"code": code,
		"message": message,
		"data": data if data is not None else {},
		"meta": meta or {},
	}


def error_response(
	*,
	message: str,
	code: str = "INTERNAL_ERROR",
	status: str = "error",
	data=None,
	meta: dict | None = None,
):
	return {
		"ok": False,
		"status": status,
		"code": code,
		"message": message,
		"data": data if data is not None else {},
		"meta": meta or {},
	}


def normalize_service_response(result: dict | None, *, code: str = "OK"):
	result = result or {}
	message = result.get("message", "")
	status = result.get("status", "success")

	meta = {}
	if "filters" in result:
		meta["filters"] = result["filters"]

	if "meta" in result and isinstance(result["meta"], dict):
		meta.update(result["meta"])

	data = result.get("data")
	if data is None:
		data = {
			key: value
			for key, value in result.items()
			if key not in {"status", "message", "code", "data", "filters", "meta"}
		}

	return success_response(
		message=message,
		data=data,
		meta=meta,
		code=result.get("code", code),
		status=status,
	)


def map_exception_to_error(exc: Exception):
	import frappe

	code = "INTERNAL_ERROR"
	http_status = 500

	if isinstance(exc, frappe.ValidationError):
		code = "VALIDATION_ERROR"
		http_status = 422
	elif isinstance(exc, frappe.PermissionError):
		code = "PERMISSION_DENIED"
		http_status = 403
	elif isinstance(exc, frappe.AuthenticationError):
		code = "AUTHENTICATION_REQUIRED"
		http_status = 401
	elif isinstance(exc, frappe.DoesNotExistError):
		code = "RESOURCE_NOT_FOUND"
		http_status = 404
	elif isinstance(exc, frappe.DuplicateEntryError):
		code = "DUPLICATE_ENTRY"
		http_status = 409

	try:
		from frappe.model.workflow import WorkflowTransitionError

		if isinstance(exc, WorkflowTransitionError):
			code = "WORKFLOW_ACTION_INVALID"
			http_status = 409
	except Exception:
		pass

	try:
		from erpnext.stock.stock_ledger import NegativeStockError

		if isinstance(exc, NegativeStockError):
			code = "INSUFFICIENT_STOCK"
			http_status = 409
	except Exception:
		pass

	return code, http_status
