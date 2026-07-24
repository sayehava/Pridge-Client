# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
from pathlib import Path

from pridge_client.renderers.base import RenderError, RendererPlugin
from pridge_client.renderers.registry import RendererRegistry
from pridge_client.renderers.validation import PDFValidationService


logger = logging.getLogger(__name__)

_MAGIC_TABLE: list[tuple[bytes, str]] = [
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
]


def _detect_mime_from_magic(data: bytes) -> str | None:
    header = data[:16]
    for magic, mime in _MAGIC_TABLE:
        if header.startswith(magic):
            return mime
    if header[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image/webp"
    try:
        sample = data[:512].decode("utf-8", errors="replace").lstrip()
        low = sample.lower()
        if "<svg" in low[:200]:
            return "image/svg+xml"
        if low.startswith("<!doctype html") or low.startswith("<html"):
            return "text/html"
        if sample.startswith("<?xml") and "<svg" in low[:400]:
            return "image/svg+xml"
    except Exception:
        pass
    return None


class RendererSelectionService:
    def __init__(
        self,
        registry: RendererRegistry,
        validation: PDFValidationService | None = None,
    ) -> None:
        self._registry = registry
        self._validation = validation or PDFValidationService()

    def select(
        self,
        *,
        data: bytes,
        mime_type: str | None = None,
        filename: str | None = None,
        explicit_plugin_id: str | None = None,
    ) -> tuple[RendererPlugin, str]:
        plugins = self._registry.enabled_plugins()

        if explicit_plugin_id:
            entry = self._registry.get_entry(explicit_plugin_id)
            if entry and entry.enabled and not entry.load_error:
                logger.info(
                    "Renderer selected: plugin_id=%s reason=explicit"
                    " source_filename=%s declared_mime=%s",
                    explicit_plugin_id, filename, mime_type,
                )
                return entry.plugin, f"explicit:{explicit_plugin_id}"
            raise RenderError(
                f"Requested renderer plugin '{explicit_plugin_id}' is not available."
            )

        if mime_type:
            for plugin in plugins:
                if mime_type in plugin.supported_mime_types:
                    reason = f"mime:{mime_type}"
                    self._log(plugin.plugin_id, reason, filename, mime_type)
                    return plugin, reason

        if filename:
            ext = Path(filename).suffix.lower()
            if ext:
                for plugin in plugins:
                    if ext in plugin.supported_extensions:
                        reason = f"extension:{ext}"
                        self._log(plugin.plugin_id, reason, filename, mime_type)
                        return plugin, reason

        detected_mime = _detect_mime_from_magic(data)
        if detected_mime:
            for plugin in plugins:
                if detected_mime in plugin.supported_mime_types:
                    reason = f"magic-byte:{detected_mime}"
                    self._log(plugin.plugin_id, reason, filename, mime_type)
                    return plugin, reason

        for plugin in plugins:
            if plugin.can_render(mime_type=mime_type, filename=filename, data=data):
                reason = f"can_render:{plugin.plugin_id}"
                self._log(plugin.plugin_id, reason, filename, mime_type)
                return plugin, reason

        declared = mime_type or "unknown type"
        suffix = f" ({filename})" if filename else ""
        raise RenderError(f"No compatible renderer found for {declared}{suffix}.")

    def _log(
        self,
        plugin_id: str,
        reason: str,
        filename: str | None,
        mime_type: str | None,
    ) -> None:
        logger.info(
            "Renderer selected: plugin_id=%s reason=%s source_filename=%s declared_mime=%s",
            plugin_id, reason, filename, mime_type,
        )
