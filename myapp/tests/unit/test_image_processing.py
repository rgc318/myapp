from io import BytesIO
from unittest import TestCase

import frappe
from PIL import Image

from myapp.utils.image_processing import (
	AI_VISION_ATTACHMENT_PROFILE,
	ITEM_IMAGE_PROFILE,
	USER_AVATAR_PROFILE,
	normalize_image_upload,
)


def _build_image(*, size=(1200, 800), image_format="PNG", mode="RGB") -> bytes:
	buffer = BytesIO()
	Image.new(mode, size, (20, 120, 220)).save(buffer, format=image_format)
	return buffer.getvalue()


class TestImageProcessing(TestCase):
	def test_item_profile_preserves_crop_ratio_and_converts_to_canonical_webp(self):
		result = normalize_image_upload(
			filename="wide-product.png",
			content=_build_image(),
			profile=ITEM_IMAGE_PROFILE,
		)

		self.assertEqual(result.filename, "wide-product.webp")
		self.assertEqual(result.content_type, "image/webp")
		self.assertEqual(result.profile, "item-flexible-v2")
		self.assertEqual((result.width, result.height), (1600, 1067))
		self.assertEqual(result.aspect_ratio, round(1600 / 1067, 6))
		self.assertEqual((result.source_width, result.source_height), (1200, 800))
		with Image.open(BytesIO(result.content)) as rendered:
			self.assertEqual(rendered.format, "WEBP")
			self.assertEqual(rendered.size, (1600, 1067))

	def test_item_profile_preserves_portrait_crop_ratio(self):
		result = normalize_image_upload(
			filename="portrait-product.png",
			content=_build_image(size=(800, 1200)),
			profile=ITEM_IMAGE_PROFILE,
		)

		self.assertEqual((result.width, result.height), (1067, 1600))

	def test_avatar_profile_outputs_512_square(self):
		result = normalize_image_upload(
			filename="avatar.jpg",
			content=_build_image(size=(640, 900), image_format="JPEG"),
			profile=USER_AVATAR_PROFILE,
		)

		self.assertEqual(result.profile, "avatar-square-v1")
		self.assertEqual((result.width, result.height), (512, 512))
		self.assertEqual(result.aspect_ratio, 1)

	def test_ai_vision_profile_preserves_small_source_dimensions_without_upscaling(self):
		result = normalize_image_upload(
			filename="evidence.png",
			content=_build_image(size=(96, 64)),
			profile=AI_VISION_ATTACHMENT_PROFILE,
		)

		self.assertEqual(result.profile, "ai-vision-source-v1")
		self.assertEqual((result.width, result.height), (96, 64))
		self.assertEqual((result.source_width, result.source_height), (96, 64))

	def test_rejects_non_image_content_even_with_image_filename(self):
		with self.assertRaises(frappe.ValidationError):
			normalize_image_upload(
				filename="not-an-image.png",
				content=b"not an image",
				profile=ITEM_IMAGE_PROFILE,
			)

	def test_rejects_insufficient_source_resolution(self):
		with self.assertRaises(frappe.ValidationError):
			normalize_image_upload(
				filename="tiny.png",
				content=_build_image(size=(200, 200)),
				profile=ITEM_IMAGE_PROFILE,
			)

	def test_rejects_extreme_item_crop_ratio(self):
		with self.assertRaises(frappe.ValidationError):
			normalize_image_upload(
				filename="too-narrow.png",
				content=_build_image(size=(300, 1000)),
				profile=ITEM_IMAGE_PROFILE,
			)
