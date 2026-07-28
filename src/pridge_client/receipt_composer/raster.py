# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import io

RASTER_COMMAND_PREFIX = b"\x1d\x76\x30"  # GS v 0
_MAX_DIMENSION = 0xFFFF
# A generous cap for a header/footer image - well beyond any real logo or
# banner (2000 dots is ~25cm at the common 203 DPI thermal-printer
# resolution) but far short of the multi-meter runaway print an image with
# an extreme aspect ratio (e.g. a tall scrolling screenshot resized to a
# narrow receipt width) would otherwise produce. The protocol-level
# _MAX_DIMENSION above is a wire-format limit, not a sanity limit - it would
# happily accept a print several meters long.
_MAX_HEIGHT_DOTS = 2000


def image_to_escpos_raster(image_bytes: bytes, *, target_width_dots: int, dither: bool = True) -> bytes:
    """Convert an arbitrary image to an ESC/POS monochrome raster bit-image
    command (GS v 0): decode, convert to grayscale, resize to
    `target_width_dots` wide (preserving aspect ratio), reduce to 1-bit
    (Floyd-Steinberg dithered by default, else a hard threshold), and pack
    into MSB-first rows padded to a byte boundary.

    Raises ValueError on undecodable input, an invalid target width, or an
    image too large to encode — callers should treat this the same as any
    other degrade-gracefully failure (e.g. the shortcode resolver drops the
    image tag rather than letting a bad upload break the rest of a print job).
    """
    if target_width_dots <= 0:
        raise ValueError("target_width_dots must be positive.")

    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError("Pillow is required to convert images to raster bytes.") from exc

    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            grayscale = source.convert("L")
    except Exception as exc:
        raise ValueError(f"Could not decode image: {exc}") from exc

    original_width, original_height = grayscale.size
    if original_width <= 0 or original_height <= 0:
        raise ValueError("Image has no visible content.")

    scale = target_width_dots / original_width
    target_height_dots = max(1, round(original_height * scale))
    if target_height_dots > _MAX_HEIGHT_DOTS:
        raise ValueError(
            f"Image would print {target_height_dots} dots tall at this paper width "
            f"(limit {_MAX_HEIGHT_DOTS}) - crop it or use a wider paper width."
        )
    resized = grayscale.resize((target_width_dots, target_height_dots))

    dither_mode = Image.FLOYDSTEINBERG if dither else Image.NONE
    monochrome = resized.convert("1", dither=dither_mode)

    width, height = monochrome.size
    width_bytes = (width + 7) // 8
    if width_bytes > _MAX_DIMENSION or height > _MAX_DIMENSION:
        raise ValueError("Image is too large to encode as an ESC/POS raster image.")

    pixels = monochrome.load()
    data = bytearray(width_bytes * height)
    for y in range(height):
        row_offset = y * width_bytes
        for x in range(width):
            if pixels[x, y] == 0:  # 0 = black in Pillow's "1" mode
                data[row_offset + (x // 8)] |= 0x80 >> (x % 8)

    header = RASTER_COMMAND_PREFIX + bytes([0]) + width_bytes.to_bytes(2, "little") + height.to_bytes(2, "little")
    return header + bytes(data)
