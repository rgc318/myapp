from __future__ import annotations

import frappe

from myapp.auth.jwt_service import decode_access_token


def _get_bearer_token() -> str | None:
	header = frappe.get_request_header("Authorization", "") or ""
	auth_type, _, token = header.partition(" ")
	if auth_type.lower() != "bearer":
		return None
	return token.strip() or None


def _is_enabled_user(user: str) -> bool:
	if user == "Administrator":
		return True
	return bool(frappe.db.get_value("User", {"name": user, "enabled": True}))


def validate():
	token = _get_bearer_token()
	if not token:
		return

	try:
		payload = decode_access_token(token)
	except Exception:
		raise frappe.AuthenticationError("JWT 访问令牌无效或已过期。")

	if not _is_enabled_user(payload.subject):
		raise frappe.AuthenticationError("JWT 用户不存在或已被禁用。")

	frappe.set_user(payload.subject)
