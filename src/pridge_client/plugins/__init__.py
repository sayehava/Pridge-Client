# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

from pridge_client.plugins.installer import PluginInstallError, install_renderer_plugin, remove_renderer_plugin
from pridge_client.plugins.manifest import (
    MANIFEST_FILE_NAME,
    ManifestError,
    PluginManifest,
    load_manifest,
)

__all__ = [
    "MANIFEST_FILE_NAME",
    "ManifestError",
    "PluginInstallError",
    "PluginManifest",
    "install_renderer_plugin",
    "load_manifest",
    "remove_renderer_plugin",
]
