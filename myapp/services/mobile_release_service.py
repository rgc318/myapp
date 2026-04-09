from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

import frappe


def _normalize_text(value: Any) -> str:
	if isinstance(value, str):
		return value.strip()
	return ""


def _coerce_bool(value: Any) -> bool:
	if isinstance(value, bool):
		return value
	if isinstance(value, (int, float)):
		return bool(value)
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes", "y", "on"}
	return False


def _load_release_config() -> dict[str, Any]:
	conf = frappe.conf or {}
	repo = _normalize_text(conf.get("myapp_mobile_release_repo"))
	api_url = _normalize_text(conf.get("myapp_mobile_release_api_url"))
	token = _normalize_text(conf.get("myapp_mobile_release_token"))
	asset_suffix = _normalize_text(conf.get("myapp_mobile_release_asset_suffix")) or ".apk"
	include_prerelease = _coerce_bool(conf.get("myapp_mobile_release_include_prerelease"))

	if not api_url and repo:
		api_url = f"https://api.github.com/repos/{repo}/releases/latest"

	return {
		"enabled": bool(api_url),
		"provider": "github",
		"repo": repo,
		"api_url": api_url,
		"token": token,
		"asset_suffix": asset_suffix,
		"include_prerelease": include_prerelease,
	}


def _build_request(api_url: str, token: str | None = None):
	headers = {
		"Accept": "application/vnd.github+json",
		"User-Agent": "myapp-mobile-update-checker",
		"X-GitHub-Api-Version": "2022-11-28",
	}
	if token:
		headers["Authorization"] = f"Bearer {token}"
	return urllib.request.Request(api_url, headers=headers, method="GET")


def _fetch_release_payload(config: dict[str, Any]) -> dict[str, Any]:
	request = _build_request(config["api_url"], config.get("token"))

	try:
		with urllib.request.urlopen(request, timeout=15) as response:
			payload = json.loads(response.read().decode("utf-8"))
	except urllib.error.HTTPError as exc:
		try:
			error_payload = json.loads(exc.read().decode("utf-8"))
			error_message = _normalize_text(error_payload.get("message"))
		except Exception:
			error_message = ""
		raise frappe.ValidationError(error_message or f"移动端版本检查失败：HTTP {exc.code}") from exc
	except urllib.error.URLError as exc:
		raise frappe.ValidationError("移动端版本检查失败：无法连接 GitHub Release 源。") from exc
	except json.JSONDecodeError as exc:
		raise frappe.ValidationError("移动端版本检查失败：Release 响应不是合法 JSON。") from exc

	if not isinstance(payload, dict):
		raise frappe.ValidationError("移动端版本检查失败：Release 响应结构不正确。")

	if payload.get("prerelease") and not config.get("include_prerelease"):
		raise frappe.ValidationError("移动端版本检查失败：当前最新 Release 仍是 prerelease。")

	return payload


def _pick_asset(release_payload: dict[str, Any], suffix: str) -> dict[str, Any] | None:
	assets = release_payload.get("assets")
	if not isinstance(assets, list):
		return None

	suffix_lower = suffix.lower()
	candidates: list[dict[str, Any]] = []
	for asset in assets:
		if not isinstance(asset, dict):
			continue
		name = _normalize_text(asset.get("name"))
		if not name:
			continue
		if suffix_lower and not name.lower().endswith(suffix_lower):
			continue
		candidates.append(asset)

	if not candidates:
		return None

	return candidates[0]


def _extract_version_text(*values: Any) -> str:
	version_pattern = re.compile(r"(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)")
	for value in values:
		text = _normalize_text(value)
		if not text:
			continue
		match = version_pattern.search(text)
		if match:
			return match.group(1)
	return ""


def _extract_build_number(*values: Any) -> int | None:
	build_pattern = re.compile(r"build[._-]?(\d+)", re.IGNORECASE)
	for value in values:
		text = _normalize_text(value)
		if not text:
			continue
		match = build_pattern.search(text)
		if match:
			return int(match.group(1))
	return None


def _parse_version_tuple(value: str) -> tuple[int, ...] | None:
	text = _normalize_text(value)
	if not text:
		return None
	match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
	if not match:
		return None
	return tuple(int(part) for part in match.groups())


def _detect_has_update(
	*,
	current_version: str | None = None,
	current_build_number: int | None = None,
	latest_version: str | None = None,
	latest_build_number: int | None = None,
) -> bool:
	current_tuple = _parse_version_tuple(current_version or "")
	latest_tuple = _parse_version_tuple(latest_version or "")

	if current_tuple and latest_tuple:
		if latest_tuple > current_tuple:
			return True
		if latest_tuple < current_tuple:
			return False

	if (
		current_build_number is not None
		and latest_build_number is not None
		and latest_build_number > current_build_number
	):
		return True

	return False


def get_mobile_release_info(
	current_version: str | None = None,
	current_build_number: int | str | None = None,
) -> dict[str, Any]:
	config = _load_release_config()

	if not config["enabled"]:
		return {
			"code": "MOBILE_RELEASE_SOURCE_NOT_CONFIGURED",
			"message": "未配置移动端 Release 源。",
			"data": {
				"enabled": False,
				"provider": config["provider"],
				"repo": config["repo"],
				"current_version": _normalize_text(current_version),
				"current_build_number": None,
				"has_update": False,
			},
		}

	release_payload = _fetch_release_payload(config)
	asset = _pick_asset(release_payload, config["asset_suffix"])

	if not asset:
		raise frappe.ValidationError("移动端版本检查失败：最新 Release 中未找到 APK 资产。")

	current_version_text = _normalize_text(current_version)
	try:
		current_build_number_value = int(current_build_number) if current_build_number not in (None, "") else None
	except (TypeError, ValueError):
		current_build_number_value = None

	tag_name = _normalize_text(release_payload.get("tag_name"))
	release_name = _normalize_text(release_payload.get("name"))
	asset_name = _normalize_text(asset.get("name"))
	latest_version = _extract_version_text(tag_name, release_name, asset_name)
	latest_build_number = _extract_build_number(tag_name, release_name, asset_name)

	return {
		"code": "MOBILE_RELEASE_INFO_FETCHED",
		"message": "移动端版本信息获取成功。",
		"data": {
			"enabled": True,
			"provider": config["provider"],
			"repo": config["repo"],
			"current_version": current_version_text,
			"current_build_number": current_build_number_value,
			"latest_version": latest_version,
			"latest_build_number": latest_build_number,
			"latest_tag": tag_name,
			"release_name": release_name,
			"release_notes": _normalize_text(release_payload.get("body")),
			"published_at": release_payload.get("published_at"),
			"download_url": _normalize_text(asset.get("browser_download_url")),
			"release_page_url": _normalize_text(release_payload.get("html_url")),
			"asset_name": asset_name,
			"asset_size": asset.get("size"),
			"is_prerelease": bool(release_payload.get("prerelease")),
			"has_update": _detect_has_update(
				current_version=current_version_text,
				current_build_number=current_build_number_value,
				latest_version=latest_version,
				latest_build_number=latest_build_number,
			),
			"force_update": False,
		},
	}
