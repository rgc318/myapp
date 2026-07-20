from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from rgc_backend_kit.security import InvalidTokenError

from myapp.auth.jwt_config import build_jwt_config
from myapp.auth.token_store import FrappeCacheTokenStore


def run_async(coro):
	try:
		asyncio.get_running_loop()
	except RuntimeError:
		return asyncio.run(coro)

	with ThreadPoolExecutor(max_workers=1) as executor:
		return executor.submit(lambda: asyncio.run(coro)).result()


def get_jwt_manager():
	try:
		from rgc_backend_kit.security import JWTManager
	except ModuleNotFoundError as exc:
		raise RuntimeError("rgc-backend-kit is not installed in the current bench environment.") from exc

	config = build_jwt_config()
	return JWTManager(
		config,
		token_store=FrappeCacheTokenStore(
			refresh_prefix=config.refresh_key_prefix,
			revoked_prefix=config.revoked_key_prefix,
		),
	)


def issue_token_pair(subject: str, claims: dict[str, Any] | None = None, *, remember_me: bool = False):
	return run_async(get_jwt_manager().issue_pair(subject, claims, remember_me=remember_me))


def decode_access_token(token: str):
	return run_async(get_jwt_manager().decode_access_token(token))


def rotate_refresh_token(refresh_token: str, claims: dict[str, Any] | None = None):
	manager = get_jwt_manager()
	payload = run_async(manager.decode_refresh_token(refresh_token))
	_validate_auth_generation(payload)
	return run_async(manager.rotate_refresh_token(refresh_token, claims))


def decode_refresh_token(refresh_token: str):
	return run_async(get_jwt_manager().decode_refresh_token(refresh_token))


def revoke_access_token(access_token: str) -> None:
	run_async(get_jwt_manager().revoke_access_token(access_token))


def delete_refresh_token(refresh_token: str) -> None:
	manager = get_jwt_manager()
	payload = run_async(manager.decode_refresh_token(refresh_token))
	run_async(manager.token_store.delete_refresh_token(payload.subject, payload.jti))


def get_user_auth_generation(user: str) -> int:
	return FrappeCacheTokenStore().get_user_auth_generation(user)


def revoke_all_user_tokens(user: str) -> int:
	return FrappeCacheTokenStore().revoke_all_user_tokens(user)


def count_user_refresh_tokens(user: str) -> int:
	return FrappeCacheTokenStore().count_user_refresh_tokens(user)


def validate_auth_generation(payload) -> None:
	_validate_auth_generation(payload)


def _validate_auth_generation(payload) -> None:
	claims = payload.claims if isinstance(payload.claims, dict) else {}
	token_generation = int(claims.get("auth_generation") or 0)
	if token_generation != get_user_auth_generation(payload.subject):
		raise InvalidTokenError("Token authorization generation is no longer valid.")
