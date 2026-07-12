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
		frappe.cache().sadd(self._refresh_index_key(subject), jti)

	async def refresh_token_exists(self, subject: str, jti: str) -> bool:
		return bool(frappe.cache().get_value(self._refresh_key(subject, jti), expires=True, use_local_cache=False))

	async def delete_refresh_token(self, subject: str, jti: str) -> None:
		frappe.cache().delete_value(self._refresh_key(subject, jti))
		frappe.cache().srem(self._refresh_index_key(subject), jti)

	def get_user_auth_generation(self, subject: str) -> int:
		return int(frappe.cache().get_value(self._auth_generation_key(subject)) or 0)

	def revoke_all_user_tokens(self, subject: str) -> int:
		generation = self.get_user_auth_generation(subject) + 1
		frappe.cache().set_value(self._auth_generation_key(subject), generation)
		frappe.cache().delete_keys(f"{self.refresh_prefix}:{subject}:")
		frappe.cache().delete_value(self._refresh_index_key(subject))
		return generation

	def count_user_refresh_tokens(self, subject: str) -> int:
		cache = frappe.cache()
		members = cache.smembers(self._refresh_index_key(subject)) or set()
		active = 0
		for raw_jti in members:
			jti = raw_jti.decode() if isinstance(raw_jti, bytes) else str(raw_jti)
			if cache.get_value(self._refresh_key(subject, jti), expires=True, use_local_cache=False):
				active += 1
			else:
				cache.srem(self._refresh_index_key(subject), jti)
		return active

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

	def _refresh_index_key(self, subject: str) -> str:
		return f"{self.refresh_prefix}:index:{subject}"

	def _auth_generation_key(self, subject: str) -> str:
		return f"{self.refresh_prefix}:generation:{subject}"
