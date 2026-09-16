from __future__ import annotations

import re


_MODEL_DISPLAY_TOKEN_MAP = {
	"deepseek": "DeepSeek",
	"gemini": "Gemini",
	"glm": "GLM",
	"gpt": "GPT",
	"kimi": "Kimi",
	"llama": "Llama",
	"minimax": "MiniMax",
	"mistral": "Mistral",
	"qwen": "Qwen",
}
_MODEL_PROVIDER_LABELS = {
	"aliyun": "阿里云",
	"anthropic": "Anthropic",
	"azure": "Azure OpenAI",
	"google": "Google",
	"minimax": "MiniMax",
	"openai": "OpenAI",
	"openrouter": "OpenRouter",
	"siliconflow": "硅基流动",
	"volcengine": "火山引擎",
}
_MODEL_PROVIDER_KEYS_BY_LABEL = {
	label.casefold(): key for key, label in _MODEL_PROVIDER_LABELS.items()
}


def _normalize_text(value, *, max_length: int) -> str:
	return " ".join(str(value or "").split())[:max_length]


def _format_model_display_token(token: str) -> str:
	lowered = token.casefold()
	if lowered in _MODEL_DISPLAY_TOKEN_MAP:
		return _MODEL_DISPLAY_TOKEN_MAP[lowered]
	if re.fullmatch(r"[var]\d+(?:\.\d+)*", lowered):
		return f"{lowered[0].upper()}{lowered[1:]}"
	if re.fullmatch(r"[a-z]\d+[a-z0-9]*", lowered):
		return lowered.upper()
	if any(char.isupper() for char in token[1:]):
		return token
	return token[:1].upper() + token[1:]


def derive_model_display_name(
	model_alias: str | None, provider_model_display: str | None = None,
) -> str:
	alias = _normalize_text(model_alias, max_length=140)
	provider_display = _normalize_text(provider_model_display, max_length=255)
	candidate = provider_display or alias
	if "/" in candidate:
		candidate = candidate.rstrip("/").rsplit("/", 1)[-1]
	parts = [part for part in re.split(r"[-_\s]+", candidate) if part]
	return " ".join(_format_model_display_token(part) for part in parts) or alias


def derive_model_provider_label(model_alias: str | None, provider_family: str | None) -> str | None:
	alias = _normalize_text(model_alias, max_length=140)
	family = _normalize_text(provider_family, max_length=80)
	provider_key = alias.split("/", 1)[0].casefold() if "/" in alias else family.casefold()
	if not provider_key or provider_key == "litellm":
		return None
	return _MODEL_PROVIDER_LABELS.get(provider_key) or _format_model_display_token(provider_key)


def expand_model_search_terms(search: str | None) -> list[str]:
	resolved = _normalize_text(search, max_length=140)
	if not resolved:
		return []
	terms = [resolved]
	if " " in resolved:
		terms.extend((resolved.replace(" ", "-"), resolved.replace(" ", "_")))
	provider_key = _MODEL_PROVIDER_KEYS_BY_LABEL.get(resolved.casefold())
	if provider_key:
		terms.append(provider_key)
	return list(dict.fromkeys(term for term in terms if term))
