# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

"""Shared metadata and filesystem safeguards for release tooling."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
PACKAGE_ROOT = SOURCE_ROOT / "printbridge_client"
ENTRY_POINT = PACKAGE_ROOT / "__main__.py"
WEBUI_ROOT = PACKAGE_ROOT / "webui"
ICON_PNG = WEBUI_ROOT / "assets" / "Icon.png"

APP_NAME = "Pridge Client"
EXECUTABLE_NAME = "Pridge Client"
AUTHOR = "Sayeh Ava Pazouki"
COMPANY_NAME = "Sayeh Ava Pazouki"
COPYRIGHT = "Copyright © 2026 Sayeh Ava Pazouki"
DESCRIPTION = "Desktop printing client for PrintBridge"
IDENTIFIER = "com.pridge.client"
LICENSE_NAME = "GPL-3.0-or-later"
RELEASE_NOTES_NAME = "Pridge-Client-Release-Notes.txt"
CHECKSUMS_NAME = "SHA256SUMS.txt"

WINDOWS_PACKAGES = {
    "Native": (
        "Pridge-Client-Native-Setup-x64.exe",
        "Pridge-Client-Native-Windows-x64-Portable.zip",
    ),
    "PyInstaller": (
        "Pridge-Client-PyInstaller-Setup-x64.exe",
        "Pridge-Client-PyInstaller-Windows-x64-Portable.zip",
    ),
}

MACOS_PACKAGES = {
    "Native": {
        "arm64": "Pridge-Client-Native-macOS-arm64.dmg",
        "x86_64": "Pridge-Client-Native-macOS-x86_64.dmg",
    },
    "PyInstaller": {
        "arm64": "Pridge-Client-PyInstaller-macOS-arm64.dmg",
        "x86_64": "Pridge-Client-PyInstaller-macOS-x86_64.dmg",
    },
}


def application_version() -> str:
    override = os.environ.get("PRINTBRIDGE_VERSION", "").strip()
    if override:
        version = override.removeprefix("v") if hasattr(override, "removeprefix") else override.lstrip("v")
    else:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
        if match is None:
            raise RuntimeError("Could not read the application version from pyproject.toml")
        version = match.group(1)
    if re.fullmatch(r"\d+\.\d+\.\d+(?:[.-][0-9A-Za-z.-]+)?", version) is None:
        raise ValueError(f"Unsupported application version: {version}")
    return version


def numeric_file_version(version: str | None = None) -> str:
    numbers = [int(value) for value in re.findall(r"\d+", version or application_version())[:4]]
    return ".".join(str(value) for value in (numbers + [0, 0, 0, 0])[:4])


def default_release_dir() -> Path:
    configured = os.environ.get("PRINTBRIDGE_RELEASE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return ROOT / "build"


def ensure_release_dir(value: str | Path | None = None) -> Path:
    destination = Path(value).expanduser() if value else default_release_dir()
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def write_build_metadata(path: Path, variant: str, system: str, version: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"variant": variant, "system": system, "version": version or application_version()},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def package_names() -> tuple[str, ...]:
    windows = [name for names in WINDOWS_PACKAGES.values() for name in names]
    macos = [name for names in MACOS_PACKAGES.values() for name in names.values()]
    return tuple(windows + macos)


def git_status() -> str:
    process = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return process.stdout


def assert_git_status_unchanged(before: str) -> None:
    after = git_status()
    if after != before:
        raise RuntimeError("The build changed the source repository:\n" + after)


def existing_packages(directory: Path, require_all: bool = False) -> Iterable[Path]:
    paths = [directory / name for name in package_names()]
    if require_all:
        missing = [path.name for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError("Missing release packages: " + ", ".join(missing))
    return (path for path in paths if path.is_file())
