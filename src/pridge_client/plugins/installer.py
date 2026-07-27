# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import shutil
from pathlib import Path

from pridge_client.plugins.discovery import renderer_plugins_dir
from pridge_client.plugins.manifest import MANIFEST_FILE_NAME, ManifestError, load_manifest


class PluginInstallError(RuntimeError):
    pass


def install_renderer_plugin(source: Path, config_dir: Path) -> str:
    """Copies a third-party renderer plugin folder (a manifest.json plus its
    entry-point module) into the user's plugins directory, so future starts
    discover it automatically. Returns the installed plugin's id.
    """
    if not source.is_dir():
        raise PluginInstallError("Select the plugin's folder, containing manifest.json.")

    manifest_path = source / MANIFEST_FILE_NAME
    if not manifest_path.is_file():
        raise PluginInstallError(f"No {MANIFEST_FILE_NAME} was found in the selected folder.")
    try:
        manifest = load_manifest(manifest_path)
    except ManifestError as exc:
        raise PluginInstallError(str(exc)) from exc

    destination_root = renderer_plugins_dir(config_dir)
    destination = destination_root / manifest.id
    if destination.exists():
        raise PluginInstallError(f"A plugin with id '{manifest.id}' is already installed.")

    destination_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    return manifest.id


def remove_renderer_plugin(plugin_id: str, config_dir: Path) -> None:
    destination = renderer_plugins_dir(config_dir) / plugin_id
    if not destination.is_dir():
        raise PluginInstallError(f"Plugin '{plugin_id}' is not installed.")
    shutil.rmtree(destination)
