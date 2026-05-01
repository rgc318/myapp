from __future__ import annotations

from datetime import timedelta

import frappe


DEFAULT_ISSUER = "myapp"
DEFAULT_ACCESS_TOKEN_MINUTES = 60
DEFAULT_REFRESH_TOKEN_DAYS = 7
DEFAULT_REMEMBER_ME_DAYS = 14
DEFAULT_LEEWAY_SECONDS = 0


def _conf_value(key: str, default=None):
	conf = getattr(frappe, "conf", {}) or {}
	if hasattr(conf, "get"):
		return conf.get(key, default)
	return getattr(conf, key, default)


def _int_conf(key: str, default: int) -> int:
	value = _conf_value(key, default)
	try:
		return int(value)
	except (TypeError, ValueError):
		return default


def get_jwt_secret() -> str:
	secret = _conf_value("myapp_jwt_secret") or _conf_value("jwt_secret")
	return str(secret or "").strip()


def build_jwt_config():
	try:
		from rgc_backend_kit.security import JWTConfig
	except ModuleNotFoundError as exc:
		raise RuntimeError("rgc-backend-kit is not installed in the current bench environment.") from exc

	return JWTConfig(
		secret=get_jwt_secret(),
		algorithm=str(_conf_value("myapp_jwt_algorithm", "HS256") or "HS256"),
		issuer=str(_conf_value("myapp_jwt_issuer", DEFAULT_ISSUER) or DEFAULT_ISSUER),
		audience=_conf_value("myapp_jwt_audience") or None,
		access_token_ttl=timedelta(minutes=_int_conf("myapp_jwt_access_token_minutes", DEFAULT_ACCESS_TOKEN_MINUTES)),
		refresh_token_ttl=timedelta(days=_int_conf("myapp_jwt_refresh_token_days", DEFAULT_REFRESH_TOKEN_DAYS)),
		remember_me_access_token_ttl=timedelta(
			days=_int_conf("myapp_jwt_remember_me_days", DEFAULT_REMEMBER_ME_DAYS)
		),
		leeway_seconds=_int_conf("myapp_jwt_leeway_seconds", DEFAULT_LEEWAY_SECONDS),
		refresh_key_prefix=str(_conf_value("myapp_jwt_refresh_key_prefix", "myapp:jwt:refresh")),
		revoked_key_prefix=str(_conf_value("myapp_jwt_revoked_key_prefix", "myapp:jwt:revoked")),
	)

