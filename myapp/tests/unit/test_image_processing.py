from io import BytesIO
from unittest import TestCase

import frappe
from PIL import Image

from myapp.utils.image_processing import (
	ITEM_IMAGE_PROFILE,
	USER_AVATAR_PROFILE,
	normalize_image_upload,
)


def _build_image(*, size=(1200, 800), image_format="PNG", mode="RGB") -> bytes:
	buffer = BytesIO()
	Image.new(mode, size, (20, 120, 220)).save(buffer, format=image_format)
	return buffer.getvalue()


class TestImageProcessing(TestCase):
	def test_item_profile_crops_and_converts_to_canonical_webp(self):
		result = normalize_image_upload(
			filename="wide-product.png",
			content=_build_image(),
			profile=ITEM_IMAGE_PROFILE,
		)

		self.assertEqual(result.filename, "wide-product.webp")
		self.assertEqual(result.content_type, "image/webp")
		self.assertEqual((result.width, result.height), (1600, 1600))
		self.assertEqual((result.source_width, result.source_height), (1200, 800))
		with Image.open(BytesIO(result.content)) as rendered:
			self.assertEqual(rendered.format, "WEBP")
			self.assertEqual(rendered.size, (1600, 1600))

	def test_avatar_profile_outputs_512_square(self):
		result = normalize_image_upload(
			filename="avatar.jpg",
			content=_build_image(size=(640, 900), image_format="JPEG"),
			profile=USER_AVATAR_PROFILE,
		)

		self.assertEqual(result.profile, "avatar-square-v1")
		self.assertEqual((result.width, result.height), (512, 512))

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
