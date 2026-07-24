# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import io
import logging

from pridge_client.renderers.base import PRIDGE_RENDERER_API_VERSION, RenderError, RenderOptions


logger = logging.getLogger(__name__)

_SUPPORTED_MIME_TYPES: frozenset[str] = frozenset({
    "image/png",
    "image/jpeg",
    "image/bmp",
    "image/tiff",
    "image/webp",
    "image/gif",
})

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".gif",
})

_MAGIC_HEADERS = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"BM",
    b"II*\x00",
    b"MM\x00*",
    b"GIF87a",
    b"GIF89a",
)


class ImageRendererPlugin:
    plugin_id = "pridge.renderer.image"
    display_name = "Image"
    version = "1.0.0"
    api_version = PRIDGE_RENDERER_API_VERSION
    supported_mime_types: frozenset[str] = _SUPPORTED_MIME_TYPES
    supported_extensions: frozenset[str] = _SUPPORTED_EXTENSIONS

    def can_render(
        self,
        *,
        mime_type: str | None,
        filename: str | None,
        data: bytes,
    ) -> bool:
        header = data[:16]
        if any(header.startswith(magic) for magic in _MAGIC_HEADERS):
            return True
        return bool(data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP")

    def render_to_pdf(
        self,
        *,
        data: bytes,
        mime_type: str | None,
        filename: str | None,
        options: RenderOptions,
    ) -> bytes:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RenderError("Image rendering requires Pillow.") from exc

        try:
            img = Image.open(io.BytesIO(data))
            if hasattr(img, "n_frames") and img.n_frames > 1:
                img.seek(0)
            img = img.convert("RGB")
        except Exception as exc:
            raise RenderError(f"Could not decode image: {exc}") from exc

        dpi = options.dpi or 96.0
        buf = io.BytesIO()
        try:
            img.save(buf, format="PDF", resolution=dpi)
        except Exception as exc:
            raise RenderError(f"Could not convert image to PDF: {exc}") from exc

        pdf_bytes = buf.getvalue()
        logger.debug(
            "Image rendered to PDF: %d → %d bytes (dpi=%.0f)",
            len(data), len(pdf_bytes), dpi,
        )
        return pdf_bytes
