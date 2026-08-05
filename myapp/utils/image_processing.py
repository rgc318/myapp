from __future__ import annotations

import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import frappe
from frappe import _
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_SOURCE_IMAGE_PIXELS = 40_000_000
OUTPUT_IMAGE_MIME_TYPE = "image/webp"
OUTPUT_IMAGE_EXTENSION = ".webp"


@dataclass(frozen=True)
class ImageProfile:
	max_output_bytes: int
	min_quality: int
	name: str
	width: int
	height: int
	quality: int
	min_source_edge: int
	preserve_aspect: bool = False
	min_aspect: float | None = None
	max_aspect: float | None = None


@dataclass(frozen=True)
class NormalizedImage:
	aspect_ratio: float
	content: bytes
	content_type: str
	filename: str
	file_size: int
	height: int
	profile: str
	quality: int
	source_format: str
	source_height: int
	source_width: int
	width: int


ITEM_IMAGE_PROFILE = ImageProfile(
	max_output_bytes=5 * 1024 * 1024,
	min_quality=52,
	name="item-flexible-v2",
	width=1600,
	height=1600,
	quality=82,
	min_source_edge=300,
	preserve_aspect=True,
	min_aspect=0.4,
	max_aspect=2.5,
)

USER_AVATAR_PROFILE = ImageProfile(
	max_output_bytes=2 * 1024 * 1024,
	min_quality=55,
	name="avatar-square-v1",
	width=512,
	height=512,
	quality=85,
	min_source_edge=128,
)


def normalize_image_upload(*, filename: str, content: bytes, profile: ImageProfile) -> NormalizedImage:
	try:
		with warnings.catch_warnings():
			warnings.simplefilter("error", Image.DecompressionBombWarning)
			with Image.open(BytesIO(content)) as probe:
				_validate_source_dimensions(probe.size, profile)
				probe.verify()
			with Image.open(BytesIO(content)) as source:
				source.seek(0)
				source_format = str(source.format or "").upper()
				source = ImageOps.exif_transpose(source)
				source.load()
	except (
		Image.DecompressionBombError,
		Image.DecompressionBombWarning,
		UnidentifiedImageError,
		OSError,
		SyntaxError,
		ValueError,
	) as exc:
		raise frappe.ValidationError(_("图片内容损坏、格式不受支持或与文件扩展名不匹配。")) from exc

	source_width, source_height = source.size

	prepared = _prepare_profile_output(_prepare_color_mode(source), profile)
	output_content, output_quality = _encode_webp(prepared, profile)
	output_width, output_height = prepared.size
	return NormalizedImage(
		aspect_ratio=round(output_width / output_height, 6),
		content=output_content,
		content_type=OUTPUT_IMAGE_MIME_TYPE,
		filename=f"{Path(filename).stem}{OUTPUT_IMAGE_EXTENSION}",
		file_size=len(output_content),
		height=output_height,
		profile=profile.name,
		quality=output_quality,
		source_format=source_format.lower(),
		source_height=source_height,
		source_width=source_width,
		width=output_width,
	)


def _prepare_color_mode(image: Image.Image) -> Image.Image:
	has_alpha = image.mode in {"RGBA", "LA"} or (
		image.mode == "P" and "transparency" in image.info
	)
	return image.convert("RGBA" if has_alpha else "RGB")


def _prepare_profile_output(image: Image.Image, profile: ImageProfile) -> Image.Image:
	if not profile.preserve_aspect:
		return ImageOps.fit(
			image,
			(profile.width, profile.height),
			method=Image.Resampling.LANCZOS,
			centering=(0.5, 0.5),
		)

	width, height = image.size
	aspect_ratio = width / height
	if profile.min_aspect is not None and aspect_ratio < profile.min_aspect:
		raise frappe.ValidationError(
			_("商品图片裁剪比例过窄，宽高比至少需要 {0}。").format(profile.min_aspect)
		)
	if profile.max_aspect is not None and aspect_ratio > profile.max_aspect:
		raise frappe.ValidationError(
			_("商品图片裁剪比例过宽，宽高比最多允许 {0}。").format(profile.max_aspect)
		)

	scale = min(profile.width / width, profile.height / height)
	target_size = (
		max(1, round(width * scale)),
		max(1, round(height * scale)),
	)
	return image.resize(target_size, Image.Resampling.LANCZOS)


def _validate_source_dimensions(size: tuple[int, int], profile: ImageProfile):
	width, height = size
	if width <= 0 or height <= 0:
		raise frappe.ValidationError(_("无法读取图片尺寸。"))
	if width * height > MAX_SOURCE_IMAGE_PIXELS:
		raise frappe.ValidationError(_("图片像素过大，请控制在 4000 万像素以内。"))
	if min(width, height) < profile.min_source_edge:
		raise frappe.ValidationError(
			_("图片分辨率过低，最短边至少需要 {0} 像素。").format(profile.min_source_edge)
		)


def _encode_webp(image: Image.Image, profile: ImageProfile) -> tuple[bytes, int]:
	quality = profile.quality
	while True:
		output = BytesIO()
		image.save(
			output,
			format="WEBP",
			quality=quality,
			method=6,
			exact=True,
		)
		content = output.getvalue()
		if len(content) <= profile.max_output_bytes or quality <= profile.min_quality:
			break
		quality = max(profile.min_quality, quality - 10)
	if len(content) > profile.max_output_bytes:
		raise frappe.ValidationError(_("图片格式化后仍然过大，请更换图片。"))
	return content, quality
