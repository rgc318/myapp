class AiDraftVersionConflictError(Exception):
	"""Raised when a stale AI draft version attempts to update or execute."""


class AiServiceError(Exception):
	"""User-safe AI service failure carrying a stable recovery code."""

	def __init__(
		self,
		message: str,
		*,
		code: str,
		http_status: int = 503,
		model_alias: str | None = None,
		provider_error_code: str | None = None,
		public_data: dict | None = None,
	):
		super().__init__(message)
		self.code = code
		self.http_status = http_status
		self.model_alias = model_alias
		self.provider_error_code = provider_error_code
		self.public_data = public_data or {}
		self.user_safe = True
