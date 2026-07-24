# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging

from pridge_client.renderers.base import PRIDGE_RENDERER_API_VERSION, RenderError, RenderOptions


logger = logging.getLogger(__name__)


class PdfRendererPlugin:
    plugin_id = "pridge.renderer.pdf"
    display_name = "PDF"
    version = "1.0.0"
    api_version = PRIDGE_RENDERER_API_VERSION
    supported_mime_types: frozenset[str] = frozenset({"application/pdf"})
    supported_extensions: frozenset[str] = frozenset({".pdf"})

    def can_render(
        self,
        *,
        mime_type: str | None,
        filename: str | None,
        data: bytes,
    ) -> bool:
        return data.startswith(b"%PDF-")

    def render_to_pdf(
        self,
        *,
        data: bytes,
        mime_type: str | None,
        filename: str | None,
        options: RenderOptions,
    ) -> bytes:
        if not data.startswith(b"%PDF-"):
            raise RenderError("Input is not a PDF document.")
        logger.debug("PDF passthrough: %d bytes", len(data))
        return data
