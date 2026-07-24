# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
from dataclasses import dataclass

from pridge_client.renderers.base import PRIDGE_RENDERER_API_VERSION, RendererPlugin


logger = logging.getLogger(__name__)


@dataclass
class RegistryEntry:
    plugin: RendererPlugin
    priority: int = 0
    enabled: bool = True
    is_builtin: bool = True
    load_error: str = ""
    source_path: str = ""


class RendererRegistry:
    def __init__(self) -> None:
        self._entries: list[RegistryEntry] = []

    def register(
        self,
        plugin: RendererPlugin,
        *,
        priority: int = 0,
        enabled: bool = True,
        is_builtin: bool = True,
        source_path: str = "",
    ) -> None:
        if any(e.plugin.plugin_id == plugin.plugin_id for e in self._entries):
            raise ValueError(f"Duplicate plugin ID: {plugin.plugin_id}")
        if plugin.api_version != PRIDGE_RENDERER_API_VERSION:
            raise ValueError(
                f"Plugin '{plugin.plugin_id}' requires API version {plugin.api_version},"
                f" but Pridge supports version {PRIDGE_RENDERER_API_VERSION}."
            )
        self._entries.append(RegistryEntry(
            plugin=plugin,
            priority=priority,
            enabled=enabled,
            is_builtin=is_builtin,
            source_path=source_path,
        ))
        logger.debug("Registered renderer plugin: %s (priority=%s)", plugin.plugin_id, priority)

    def register_error(
        self,
        plugin_id: str,
        load_error: str,
        source_path: str = "",
    ) -> None:
        self._entries.append(RegistryEntry(
            plugin=_ErrorPlaceholder(plugin_id),
            priority=999,
            enabled=False,
            is_builtin=False,
            load_error=load_error,
            source_path=source_path,
        ))
        logger.warning("Renderer plugin failed to load: %s — %s", plugin_id, load_error)

    def enabled_plugins(self) -> list[RendererPlugin]:
        active = [e for e in self._entries if e.enabled and not e.load_error]
        active.sort(key=lambda e: e.priority)
        return [e.plugin for e in active]

    def all_entries(self) -> list[RegistryEntry]:
        return list(self._entries)

    def get_entry(self, plugin_id: str) -> RegistryEntry | None:
        return next((e for e in self._entries if e.plugin.plugin_id == plugin_id), None)

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        entry = self.get_entry(plugin_id)
        if entry is not None:
            entry.enabled = enabled

    def set_priority(self, plugin_id: str, priority: int) -> None:
        entry = self.get_entry(plugin_id)
        if entry is not None:
            entry.priority = priority

    def remove(self, plugin_id: str) -> bool:
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.plugin.plugin_id != plugin_id]
        return len(self._entries) < before


class _ErrorPlaceholder:
    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        self.display_name = plugin_id
        self.version = ""
        self.api_version = 0
        self.supported_mime_types: frozenset[str] = frozenset()
        self.supported_extensions: frozenset[str] = frozenset()

    def can_render(self, *, mime_type: str | None, filename: str | None, data: bytes) -> bool:
        return False

    def render_to_pdf(
        self, *, data: bytes, mime_type: str | None, filename: str | None, options: object
    ) -> bytes:
        raise RuntimeError(f"Plugin {self.plugin_id} failed to load.")
