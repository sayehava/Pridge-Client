#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import argparse
import json
import plistlib
import shutil
from pathlib import Path

from release_common import ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize metadata and legal resources in a macOS app bundle.")
    parser.add_argument("--app", required=True)
    parser.add_argument("--context", required=True)
    args = parser.parse_args()

    app = Path(args.app).expanduser().resolve()
    try:
        app.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("The app bundle must be built outside the source repository")
    context = json.loads(Path(args.context).read_text(encoding="utf-8"))
    plist_path = app / "Contents" / "Info.plist"
    with plist_path.open("rb") as handle:
        plist = plistlib.load(handle)
    plist.update(
        {
            "CFBundleDisplayName": context["app_name"],
            "CFBundleName": context["app_name"],
            "CFBundleIdentifier": context["identifier"],
            "CFBundleShortVersionString": context["version"],
            "CFBundleVersion": context["numeric_file_version"],
            "NSHumanReadableCopyright": context["copyright"],
            "PrintBridgeAuthor": context["author"],
            "PrintBridgeDescription": context["description"],
            "PrintBridgeBuildVariant": context["variant"],
            "PrintBridgeBuildSystem": context["system"],
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
        }
    )
    with plist_path.open("wb") as handle:
        plistlib.dump(plist, handle, sort_keys=True)

    legal_dir = app / "Contents" / "Resources" / "Legal"
    legal_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", legal_dir / "LICENSE")
    shutil.copy2(ROOT / "ADDITIONAL_TERMS.md", legal_dir / "ADDITIONAL_TERMS.md")


if __name__ == "__main__":
    main()
