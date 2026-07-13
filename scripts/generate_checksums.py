#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from release_common import CHECKSUMS_NAME, ensure_release_dir, existing_packages


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate release package SHA256 checksums.")
    parser.add_argument("--output-dir", help="Build output directory; defaults to PRINTBRIDGE_RELEASE_DIR or project/build.")
    parser.add_argument("--require-all", action="store_true", help="Require all eight cross-platform packages.")
    args = parser.parse_args()

    output_dir = ensure_release_dir(args.output_dir)
    packages = list(existing_packages(output_dir, require_all=args.require_all))
    if not packages:
        raise SystemExit("No final release packages were found")
    lines = [f"{sha256(path)}  {path.name}" for path in packages]
    destination = output_dir / CHECKSUMS_NAME
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
