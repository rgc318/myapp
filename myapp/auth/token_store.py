from __future__ import annotations

import frappe


class FrappeCacheTokenStore:
	"""TokenStore adapter backed by Frappe cache/Redis."""

	def __init__(self, *, refresh_prefix: str = "myapp:jwt:refresh", revoked_prefix: str = "myapp:jwt:revoked"):
		self.refresh_prefix = refresh_prefix
		self.revoked_prefix = revoked_prefix

	async def set_refresh_token(self, subject: str, jti: str, token: str, ttl_seconds: int) -> None:
		frappe.cache().set_value(
			self._refresh_key(subject, jti),
			token,
			expires_in_sec=ttl_seconds,
		)

	async def refresh_token_exists(self, subject: str, jti: str) -> bool:
		return bool(frappe.cache().get_value(self._refresh_key(subject, jti), expires=True, use_local_cache=False))

	async def delete_refresh_token(self, subject: str, jti: str) -> None:
		frappe.cache().delete_value(self._refresh_key(subject, jti))

	async def revoke_token(self, jti: str, ttl_seconds: int) -> None:
		frappe.cache().set_value(
			self._revoked_key(jti),
			"1",
			expires_in_sec=ttl_seconds,
		)

	async def is_token_revoked(self, jti: str) -> bool:
		return bool(frappe.cache().get_value(self._revoked_key(jti), expires=True, use_local_cache=False))

	def _refresh_key(self, subject: str, jti: str) -> str:
		return f"{self.refresh_prefix}:{subject}:{jti}"

	def _revoked_key(self, jti: str) -> str:
		return f"{self.revoked_prefix}:{jti}"

