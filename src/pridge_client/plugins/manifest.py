# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


MANIFEST_FILE_NAME = "manifest.json"

# The plugin system is not tied to printing: "category" is a first-class,
# validated field so a future plugin kind (e.g. a non-print feature plugin)
# can be added by extending this set and adding a matching discovery path,
# without changing the manifest format or the install/remove mechanism.
SUPPORTED_PLUGIN_CATEGORIES = ("renderer",)


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    api_version: int
    category: str
    entry_point: str
    supported_mime_types: tuple[str, ...] = field(default_factory=tuple)
    supported_extensions: tuple[str, ...] = field(default_factory=tuple)

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "api_version": self.api_version,
            "category": self.category,
            "supported_mime_types": list(self.supported_mime_types),
            "supported_extensions": list(self.supported_extensions),
        }


def load_manifest(manifest_path: Path) -> PluginManifest:
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"Could not read the plugin manifest: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"The plugin manifest is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError("The plugin manifest must be a JSON object.")

    plugin_id = str(raw.get("id", "")).strip()
    name = str(raw.get("name", "")).strip()
    entry_point = str(raw.get("entry_point", "")).strip()
    category = str(raw.get("category", "")).strip().lower()

    if not plugin_id:
        raise ManifestError("The plugin manifest is missing the required field 'id'.")
    if not name:
        raise ManifestError("The plugin manifest is missing the required field 'name'.")
    if ":" not in entry_point or not all(entry_point.split(":", 1)):
        raise ManifestError(
            "The plugin manifest's 'entry_point' must be in the form 'module:ClassName'."
        )
    if category not in SUPPORTED_PLUGIN_CATEGORIES:
        raise ManifestError(
            f"Unsupported plugin category '{category or '(none)'}'. Supported categories: "
            + ", ".join(SUPPORTED_PLUGIN_CATEGORIES)
        )
    try:
        api_version = int(raw.get("api_version", 0))
    except (TypeError, ValueError) as exc:
        raise ManifestError("The plugin manifest's 'api_version' must be an integer.") from exc

    return PluginManifest(
        id=plugin_id,
        name=name,
        version=str(raw.get("version", "")).strip() or "0.0.0",
        api_version=api_version,
        category=category,
        entry_point=entry_point,
        supported_mime_types=tuple(
            str(value).strip() for value in raw.get("supported_mime_types", []) if str(value).strip()
        ),
        supported_extensions=tuple(
            str(value).strip() for value in raw.get("supported_extensions", []) if str(value).strip()
        ),
    )
