# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import io
import unittest

from pridge_client.receipt_composer.raster import RASTER_COMMAND_PREFIX, image_to_escpos_raster


def _png_bytes(width: int, height: int, color=(0, 0, 0)) -> bytes:
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        raise unittest.SkipTest("Pillow not installed")
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buf, format="PNG")
    return buf.getvalue()


class RasterConversionTests(unittest.TestCase):
    def test_starts_with_the_gs_v_0_command_prefix(self) -> None:
        result = image_to_escpos_raster(_png_bytes(8, 8), target_width_dots=8)

        self.assertTrue(result.startswith(RASTER_COMMAND_PREFIX))

    def test_header_encodes_width_in_bytes_and_height_in_pixels(self) -> None:
        # 8 dots wide -> exactly 1 width-byte; 8 dots tall.
        result = image_to_escpos_raster(_png_bytes(8, 8), target_width_dots=8)

        mode_byte = result[3]
        width_bytes = int.from_bytes(result[4:6], "little")
        height = int.from_bytes(result[6:8], "little")
        self.assertEqual(mode_byte, 0)
        self.assertEqual(width_bytes, 1)
        self.assertEqual(height, 8)
        self.assertEqual(len(result), 8 + width_bytes * height)

    def test_non_multiple_of_eight_width_rounds_up_to_the_next_byte(self) -> None:
        # 10 dots wide needs 2 width-bytes (10/8 rounded up), padded with blank bits.
        result = image_to_escpos_raster(_png_bytes(10, 4), target_width_dots=10)

        width_bytes = int.from_bytes(result[4:6], "little")
        height = int.from_bytes(result[6:8], "little")
        self.assertEqual(width_bytes, 2)
        self.assertEqual(height, 4)
        self.assertEqual(len(result), 8 + width_bytes * height)

    def test_preserves_aspect_ratio_when_resizing(self) -> None:
        # 20x10 source resized to target width 10 dots -> height should be 5.
        result = image_to_escpos_raster(_png_bytes(20, 10), target_width_dots=10)

        height = int.from_bytes(result[6:8], "little")
        self.assertEqual(height, 5)

    def test_an_all_black_image_sets_every_bit(self) -> None:
        result = image_to_escpos_raster(_png_bytes(8, 1, color=(0, 0, 0)), target_width_dots=8)

        pixel_data = result[8:]
        self.assertEqual(pixel_data, b"\xff")

    def test_an_all_white_image_clears_every_bit(self) -> None:
        result = image_to_escpos_raster(_png_bytes(8, 1, color=(255, 255, 255)), target_width_dots=8, dither=False)

        pixel_data = result[8:]
        self.assertEqual(pixel_data, b"\x00")

    def test_dither_and_threshold_can_produce_different_output(self) -> None:
        # A mid-gray image: dithering scatters some black pixels, a hard
        # threshold at 128 renders it as a single flat tone. They need not
        # always differ for every image, but for a uniform mid-gray patch
        # large enough to dither, the two modes should diverge.
        gray_bytes = _png_bytes(16, 16, color=(128, 128, 128))

        dithered = image_to_escpos_raster(gray_bytes, target_width_dots=16, dither=True)
        thresholded = image_to_escpos_raster(gray_bytes, target_width_dots=16, dither=False)

        self.assertNotEqual(dithered[8:], thresholded[8:])

    def test_non_positive_target_width_raises(self) -> None:
        with self.assertRaises(ValueError):
            image_to_escpos_raster(_png_bytes(8, 8), target_width_dots=0)

    def test_undecodable_input_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            image_to_escpos_raster(b"not an image", target_width_dots=8)


if __name__ == "__main__":
    unittest.main()
