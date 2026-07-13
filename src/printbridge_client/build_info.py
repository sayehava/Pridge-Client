# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

"""Identify the tool that produced the running application."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _embedded_metadata() -> dict[str, str]:
    path = Path(__file__).resolve().parent / "_build.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _detect_build() -> tuple[str, str]:
    metadata = _embedded_metadata()
    if metadata.get("variant") and metadata.get("system"):
        return metadata["variant"], metadata["system"]
    if "__compiled__" in globals():
        return "Native", "Nuitka"
    if bool(getattr(sys, "frozen", False)):
        return "PyInstaller", "PyInstaller"
    return "Development", "Python"


BUILD_VARIANT, BUILD_SYSTEM = _detect_build()


def embedded_version(default: str) -> str:
    return _embedded_metadata().get("version", default)
