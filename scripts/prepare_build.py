#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path

from PIL import Image

from release_common import (
    APP_NAME,
    AUTHOR,
    COMPANY_NAME,
    COPYRIGHT,
    DESCRIPTION,
    EXECUTABLE_NAME,
    ICON_PNG,
    IDENTIFIER,
    MACOS_PACKAGES,
    ROOT,
    WINDOWS_PACKAGES,
    application_version,
    numeric_file_version,
    write_build_metadata,
)


def write_windows_version_file(path: Path, version: str) -> None:
    numeric = tuple(int(value) for value in numeric_file_version(version).split("."))
    escaped = {
        "company": repr(COMPANY_NAME),
        "description": repr(DESCRIPTION),
        "version": repr(version),
        "name": repr(APP_NAME),
        "copyright": repr(COPYRIGHT),
        "executable": repr(f"{EXECUTABLE_NAME}.exe"),
    }
    path.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numeric!r}, prodvers={numeric!r}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', {escaped['company']}),
      StringStruct('FileDescription', {escaped['description']}),
      StringStruct('FileVersion', {escaped['version']}),
      StringStruct('InternalName', {escaped['name']}),
      StringStruct('LegalCopyright', {escaped['copyright']}),
      StringStruct('OriginalFilename', {escaped['executable']}),
      StringStruct('ProductName', {escaped['name']}),
      StringStruct('ProductVersion', {escaped['version']})
    ])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


def create_icons(work_dir: Path) -> tuple[Path, Path]:
    source = Image.open(ICON_PNG).convert("RGBA")
    icon_ico = work_dir / "Pridge-Client.ico"
    icon_icns = work_dir / "Pridge-Client.icns"
    source.save(icon_ico, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    source.save(icon_icns, format="ICNS")
    return icon_ico, icon_icns


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare generated release metadata outside the repository.")
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--variant", required=True, choices=("Native", "PyInstaller"))
    parser.add_argument("--arch", choices=("x64", "arm64", "x86_64"))
    args = parser.parse_args()

    work_dir = Path(args.work_dir).expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    version = application_version()
    system = "Nuitka" if args.variant == "Native" else "PyInstaller"
    metadata = write_build_metadata(work_dir / "_build.json", args.variant, system, version)
    icon_ico, icon_icns = create_icons(work_dir)
    version_file = work_dir / "windows-version.txt"
    write_windows_version_file(version_file, version)
    machine = platform.machine().lower()
    arch = args.arch or ("arm64" if machine in {"arm64", "aarch64"} else "x86_64")
    context = {
        "app_name": APP_NAME,
        "author": AUTHOR,
        "company_name": COMPANY_NAME,
        "copyright": COPYRIGHT,
        "description": DESCRIPTION,
        "executable_name": EXECUTABLE_NAME,
        "identifier": IDENTIFIER,
        "root": str(ROOT),
        "version": version,
        "numeric_file_version": numeric_file_version(version),
        "variant": args.variant,
        "system": system,
        "arch": arch,
        "metadata": str(metadata),
        "icon_ico": str(icon_ico),
        "icon_icns": str(icon_icns),
        "windows_version_file": str(version_file),
        "windows_packages": WINDOWS_PACKAGES[args.variant],
        "macos_package": MACOS_PACKAGES[args.variant].get(arch, ""),
    }
    context_path = work_dir / "build-context.json"
    context_path.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(context_path)


if __name__ == "__main__":
    main()
