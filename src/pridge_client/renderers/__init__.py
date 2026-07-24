# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

from pridge_client.renderers.base import (
    PRIDGE_RENDERER_API_VERSION,
    RenderError,
    RenderOptions,
    RendererPlugin,
)
from pridge_client.renderers.registry import RegistryEntry, RendererRegistry
from pridge_client.renderers.selection import RendererSelectionService
from pridge_client.renderers.validation import PDFValidationService


def build_default_registry() -> RendererRegistry:
    from pridge_client.renderers.pdf_plugin import PdfRendererPlugin
    from pridge_client.renderers.image_plugin import ImageRendererPlugin
    from pridge_client.renderers.text_plugin import TextRendererPlugin
    from pridge_client.renderers.svg_plugin import SvgRendererPlugin

    registry = RendererRegistry()
    registry.register(PdfRendererPlugin(), priority=10)
    registry.register(ImageRendererPlugin(), priority=20)
    registry.register(TextRendererPlugin(), priority=30)
    registry.register(SvgRendererPlugin(), priority=40)
    return registry


__all__ = [
    "PRIDGE_RENDERER_API_VERSION",
    "RenderError",
    "RenderOptions",
    "RendererPlugin",
    "RegistryEntry",
    "RendererRegistry",
    "RendererSelectionService",
    "PDFValidationService",
    "build_default_registry",
]
