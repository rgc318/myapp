from __future__ import annotations

import frappe
from frappe.utils import cint
from rgc_backend_kit.security import InvalidTokenError

from myapp.auth.jwt_service import delete_refresh_token, issue_token_pair, rotate_refresh_token, revoke_access_token
from myapp.utils.api_response import success_response


def _to_bool(value) -> bool:
	if isinstance(value, bool):
		return value
	return bool(cint(value))


def _find_user_by_credentials(username: str, password: str) -> str:
	from frappe.core.doctype.user.user import User

	user = User.find_by_credentials(username, password)
	if not user or not getattr(user, "is_authenticated", False):
		raise frappe.AuthenticationError("用户名或密码错误。")
	if not (user.name == "Administrator" or user.enabled):
		raise frappe.AuthenticationError("用户已被禁用。")
	return user.name


def _token_pair_payload(pair):
	return {
		"access_token": pair.access_token,
		"refresh_token": pair.refresh_token,
		"token_type": pair.token_type,
		"expires_in": pair.access_expires_in,
		"refresh_expires_in": pair.refresh_expires_in,
		"access_jti": pair.access_jti,
		"refresh_jti": pair.refresh_jti,
	}


def _current_user_payload(user: str) -> dict:
	return {
		"user": user,
		"roles": frappe.get_roles(user),
		"full_name": frappe.db.get_value("User", user, "full_name"),
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def login_v1(username: str | None = None, password: str | None = None, usr: str | None = None, pwd: str | None = None, remember_me=0):
	resolved_username = (username or usr or "").strip()
	resolved_password = password if password is not None else pwd
	if not resolved_username or not resolved_password:
		raise frappe.AuthenticationError("请提供用户名和密码。")

	user = _find_user_by_credentials(resolved_username, resolved_password)
	pair = issue_token_pair(
		user,
		{
			"roles": frappe.get_roles(user),
		},
		remember_me=_to_bool(remember_me),
	)
	return success_response(
		message="JWT 令牌已签发。",
		code="JWT_TOKEN_ISSUED",
		data={
			**_token_pair_payload(pair),
			"user": _current_user_payload(user),
		},
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def refresh_v1(refresh_token: str):
	if not (refresh_token or "").strip():
		raise frappe.AuthenticationError("请提供 refresh token。")

	try:
		pair = rotate_refresh_token(refresh_token.strip())
	except InvalidTokenError:
		raise frappe.AuthenticationError("Refresh token 无效、已过期或已被使用。")

	return success_response(
		message="JWT 令牌已刷新。",
		code="JWT_TOKEN_REFRESHED",
		data=_token_pair_payload(pair),
	)


@frappe.whitelist(methods=["POST"])
def logout_v1(access_token: str | None = None, refresh_token: str | None = None):
	token = (access_token or "").strip()
	if not token:
		header = frappe.get_request_header("Authorization", "") or ""
		auth_type, _, header_token = header.partition(" ")
		if auth_type.lower() == "bearer":
			token = header_token.strip()

	if token:
		revoke_access_token(token)
	if (refresh_token or "").strip():
		delete_refresh_token(refresh_token.strip())

	return success_response(
		message="JWT 令牌已注销。",
		code="JWT_TOKEN_REVOKED",
		data={},
	)


@frappe.whitelist()
def me_v1():
	user = getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		raise frappe.AuthenticationError("请先登录。")
	return success_response(
		message="已获取当前用户信息。",
		code="JWT_CURRENT_USER_FETCHED",
		data=_current_user_payload(user),
	)
