class AiDraftVersionConflictError(Exception):
	"""Raised when a stale AI draft version attempts to update or execute."""


class AiServiceError(Exception):
	"""User-safe AI service failure carrying a stable recovery code."""

	def __init__(self, message: str, *, code: str, http_status: int = 503):
		super().__init__(message)
		self.code = code
		self.http_status = http_status
