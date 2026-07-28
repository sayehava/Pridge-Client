# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pridge_client.renderers.base import PRIDGE_RENDERER_API_VERSION, RenderError, RenderOptions


logger = logging.getLogger(__name__)

_CURRENT_PLATFORM = platform.system().lower()


@dataclass
class AppMapping:
    id: str
    name: str
    extensions: list[str] = field(default_factory=list)
    mime_types: list[str] = field(default_factory=list)
    executable: str = ""
    arguments: list[str] = field(default_factory=list)
    timeout: float = 60.0
    enabled: bool = True
    platform_filter: str = ""


class AppMappingStore:
    FILE_NAME = "app-mappings.json"

    def __init__(self, config_dir: Path) -> None:
        self._path = config_dir / self.FILE_NAME

    def load(self) -> list[AppMapping]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not load app mappings: %s", exc)
            return []
        if not isinstance(raw, list):
            return []
        result: list[AppMapping] = []
        for item in raw:
            if isinstance(item, dict):
                parsed = _parse_mapping(item)
                if parsed is not None:
                    result.append(parsed)
        return result

    def save(self, mappings: list[AppMapping]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps([asdict(m) for m in mappings], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


class AppMappingRendererPlugin:
    plugin_id = "pridge.renderer.app_mapping"
    display_name = "External Application Mapper"
    version = "1.0.0"
    api_version = PRIDGE_RENDERER_API_VERSION
    settings_window = "app_mapping"
    supported_mime_types: frozenset[str] = frozenset()
    supported_extensions: frozenset[str] = frozenset()

    def __init__(self, mappings: list[AppMapping] | None = None) -> None:
        self._mappings: list[AppMapping] = []
        self.set_mappings(mappings or [])

    def set_mappings(self, mappings: list[AppMapping]) -> None:
        self._mappings = list(mappings)
        active = [m for m in self._mappings if m.enabled and _platform_ok(m.platform_filter)]
        self.supported_mime_types = frozenset(mt for m in active for mt in m.mime_types)
        self.supported_extensions = frozenset(
            e if e.startswith(".") else f".{e}" for m in active for e in m.extensions
        )

    def get_mappings(self) -> list[AppMapping]:
        return list(self._mappings)

    def can_render(
        self,
        *,
        mime_type: str | None,
        filename: str | None,
        data: bytes,
    ) -> bool:
        return _find_mapping(self._mappings, mime_type=mime_type, filename=filename) is not None

    def render_to_pdf(
        self,
        *,
        data: bytes,
        mime_type: str | None,
        filename: str | None,
        options: RenderOptions,
    ) -> bytes:
        mapping = _find_mapping(self._mappings, mime_type=mime_type, filename=filename)
        if mapping is None:
            raise RenderError("No configured application mapping matched this file.")
        if not mapping.executable:
            raise RenderError(
                f"Application mapping {mapping.name!r} has no executable configured."
            )

        ext = Path(filename).suffix if filename else ".bin"
        input_fd, input_path = tempfile.mkstemp(suffix=ext)
        output_path = input_path + ".out.pdf"
        try:
            os.write(input_fd, data)
            os.close(input_fd)
            input_fd = -1

            args = [
                a.replace("{input}", input_path).replace("{output}", output_path)
                for a in mapping.arguments
            ]
            logger.info(
                "App mapping %r: executing %s",
                mapping.name,
                " ".join(repr(c) for c in [mapping.executable, *args]),
            )
            try:
                result = subprocess.run(
                    [mapping.executable, *args],
                    timeout=mapping.timeout,
                    capture_output=True,
                )
            except subprocess.TimeoutExpired:
                raise RenderError(
                    f"Application mapping {mapping.name!r} timed out after {mapping.timeout:.0f}s."
                )
            except FileNotFoundError:
                raise RenderError(
                    f"Application mapping {mapping.name!r}: executable not found: {mapping.executable!r}"
                )

            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace").strip()
                raise RenderError(
                    f"Application mapping {mapping.name!r} exited with code {result.returncode}"
                    + (f": {stderr}" if stderr else "")
                )

            if not Path(output_path).is_file():
                raise RenderError(
                    f"Application mapping {mapping.name!r} did not produce the expected output PDF."
                )

            pdf_bytes = Path(output_path).read_bytes()
            logger.info("App mapping %r produced %d bytes", mapping.name, len(pdf_bytes))
            return pdf_bytes
        finally:
            if input_fd >= 0:
                try:
                    os.close(input_fd)
                except OSError:
                    pass
            for path in (input_path, output_path):
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass


def _platform_ok(platform_filter: str) -> bool:
    return not platform_filter or platform_filter == _CURRENT_PLATFORM


def _find_mapping(
    mappings: list[AppMapping],
    *,
    mime_type: str | None,
    filename: str | None,
) -> AppMapping | None:
    ext = Path(filename).suffix.lower() if filename else ""
    for m in mappings:
        if not m.enabled or not m.executable:
            continue
        if not _platform_ok(m.platform_filter):
            continue
        if mime_type and any(mt.lower() == mime_type.lower() for mt in m.mime_types):
            return m
        if ext:
            norm = [e if e.startswith(".") else f".{e}" for e in m.extensions]
            if ext in norm:
                return m
    return None


def _parse_mapping(raw: dict[str, Any]) -> AppMapping | None:
    mapping_id = str(raw.get("id", "")).strip()
    name = str(raw.get("name", "")).strip()
    if not mapping_id or not name:
        return None
    try:
        timeout = float(raw.get("timeout", 60.0))
    except (TypeError, ValueError):
        timeout = 60.0
    return AppMapping(
        id=mapping_id,
        name=name,
        extensions=[str(e).strip() for e in raw.get("extensions", []) if str(e).strip()],
        mime_types=[str(m).strip() for m in raw.get("mime_types", []) if str(m).strip()],
        executable=str(raw.get("executable", "")).strip(),
        arguments=[str(a) for a in raw.get("arguments", [])],
        timeout=max(1.0, timeout),
        enabled=bool(raw.get("enabled", True)),
        platform_filter=str(raw.get("platform_filter", "")).strip().lower(),
    )
