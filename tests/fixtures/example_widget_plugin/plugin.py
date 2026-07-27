# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

"""Minimal example of a third-party plugin that also provides a dashboard
widget (see manifest.json's widget_title/widget_entry and widget.js).
"""


class ExampleWidgetRendererPlugin:
    plugin_id = "org.example.pridge.widget.example"
    display_name = "Example Widget Plugin"
    version = "1.0.0"
    api_version = 1
    supported_mime_types = frozenset()
    supported_extensions = frozenset()

    def can_render(self, *, mime_type, filename, data):
        return False

    def render_to_pdf(self, *, data, mime_type, filename, options):
        raise NotImplementedError
