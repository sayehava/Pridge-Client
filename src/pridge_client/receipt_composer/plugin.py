# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

from pridge_client.renderers.base import PRIDGE_RENDERER_API_VERSION


class ReceiptComposerPlugin:
    """Registers Receipt Composer in the Plugins window (category "Receipts")
    so its settings are discoverable and it can be enabled/disabled like any
    other plugin. It never renders documents — its actual work (shortcode
    parsing, image rasterization, counters) happens in PrinterManager.print_job
    via receipt_composer.shortcodes.render_template, not through this class.
    """

    plugin_id = "pridge.receipts.composer"
    display_name = "Receipt Composer"
    version = "1.0.0"
    api_version = PRIDGE_RENDERER_API_VERSION
    supported_mime_types: frozenset[str] = frozenset()
    supported_extensions: frozenset[str] = frozenset()
    settings_window = "receipt_composer"

    def can_render(self, *, mime_type: str | None, filename: str | None, data: bytes) -> bool:
        return False

    def render_to_pdf(
        self, *, data: bytes, mime_type: str | None, filename: str | None, options: object
    ) -> bytes:
        raise NotImplementedError(
            "Receipt Composer does not render documents; it composes RAW receipt headers/footers."
        )
