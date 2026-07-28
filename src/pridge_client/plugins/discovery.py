# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import importlib.util
import logging
import sys
import uuid
from pathlib import Path

from pridge_client.plugins.manifest import MANIFEST_FILE_NAME, ManifestError, load_manifest
from pridge_client.renderers.base import PRIDGE_RENDERER_API_VERSION
from pridge_client.renderers.registry import RendererRegistry


logger = logging.getLogger(__name__)

# Third-party renderers install below the built-ins (priority 10-40) and the
# app-mapping plugin (priority 100), so a user can still promote one above
# built-ins explicitly via the Plugins UI's priority controls.
THIRD_PARTY_RENDERER_PRIORITY = 200


def renderer_plugins_dir(config_dir: Path) -> Path:
    return config_dir / "plugins" / "renderers"


def discover_plugin_directories(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        (
            child
            for child in directory.iterdir()
            if child.is_dir() and (child / MANIFEST_FILE_NAME).is_file()
        ),
        key=lambda path: path.name,
    )


def load_entry_point(plugin_dir: Path, entry_point: str):
    module_name, _, class_name = entry_point.partition(":")
    module_file = plugin_dir / f"{module_name}.py"
    if not module_file.is_file():
        raise ManifestError(f"Entry point module '{module_name}.py' was not found in the plugin folder.")

    unique_module_name = f"pridge_client._third_party_plugin_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(unique_module_name, module_file)
    if spec is None or spec.loader is None:
        raise ManifestError(f"Could not load the plugin module '{module_name}.py'.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        del sys.modules[unique_module_name]
        raise ManifestError(f"'{module_name}.py' raised an error while loading: {exc}") from exc

    plugin_class = getattr(module, class_name, None)
    if plugin_class is None:
        raise ManifestError(f"Entry point class '{class_name}' was not found in '{module_name}.py'.")
    return plugin_class


def register_third_party_renderers(registry: RendererRegistry, config_dir: Path) -> list[str]:
    """Loads every third-party renderer plugin folder under the user's
    plugins directory and registers it into ``registry``. A plugin that
    fails to load is recorded as a registry error instead of raising, so one
    broken plugin never prevents the client from starting.
    """
    registered_ids: list[str] = []
    for plugin_dir in discover_plugin_directories(renderer_plugins_dir(config_dir)):
        category = ""
        try:
            manifest = load_manifest(plugin_dir / MANIFEST_FILE_NAME)
            category = manifest.category
            if manifest.api_version != PRIDGE_RENDERER_API_VERSION:
                raise ManifestError(
                    f"Plugin declares renderer API version {manifest.api_version}, but Pridge "
                    f"Client supports version {PRIDGE_RENDERER_API_VERSION}."
                )
            plugin_class = load_entry_point(plugin_dir, manifest.entry_point)
            plugin = plugin_class()
            registry.register(
                plugin,
                priority=THIRD_PARTY_RENDERER_PRIORITY,
                is_builtin=False,
                source_path=str(plugin_dir),
                category=category,
            )
            registered_ids.append(plugin.plugin_id)
        except (ManifestError, ValueError) as exc:
            registry.register_error(plugin_dir.name, str(exc), source_path=str(plugin_dir), category=category)
        except Exception as exc:  # noqa: BLE001 - a broken third-party plugin must never crash startup
            registry.register_error(plugin_dir.name, str(exc), source_path=str(plugin_dir), category=category)
    return registered_ids
