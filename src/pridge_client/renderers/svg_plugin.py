# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging

from pridge_client.renderers.base import PRIDGE_RENDERER_API_VERSION, RenderError, RenderOptions


logger = logging.getLogger(__name__)

_SUPPORTED_MIME_TYPES: frozenset[str] = frozenset({"image/svg+xml"})
_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".svg", ".svgz"})


class SvgRendererPlugin:
    plugin_id = "pridge.renderer.svg"
    display_name = "SVG"
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
        try:
            sample = data[:512].decode("utf-8", errors="replace").lower()
            return "<svg" in sample
        except Exception:
            return False

    def render_to_pdf(
        self,
        *,
        data: bytes,
        mime_type: str | None,
        filename: str | None,
        options: RenderOptions,
    ) -> bytes:
        try:
            import cairosvg
        except ImportError as exc:
            raise RenderError(
                "SVG rendering requires cairosvg. Install it separately or configure"
                " an External Application Mapping for SVG files."
            ) from exc

        try:
            pdf_bytes = cairosvg.svg2pdf(bytestring=data)
        except Exception as exc:
            raise RenderError(f"Could not convert SVG to PDF: {exc}") from exc

        logger.debug(
            "SVG rendered to PDF: %d → %d bytes", len(data), len(pdf_bytes)
        )
        return pdf_bytes
