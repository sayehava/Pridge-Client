#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
from pathlib import Path

from release_common import (
    AUTHOR,
    COPYRIGHT,
    LICENSE_NAME,
    MACOS_PACKAGES,
    RELEASE_NOTES_NAME,
    ROOT,
    WINDOWS_PACKAGES,
    application_version,
    ensure_release_dir,
)


SECTION_RULES = (
    ("Features", re.compile(r"^(feat(?:ure)?|add|implement|create|introduce)\b", re.IGNORECASE)),
    ("Fixes", re.compile(r"^(fix|repair|resolve|correct)\b", re.IGNORECASE)),
    ("Documentation", re.compile(r"^(docs?|document|readme)\b", re.IGNORECASE)),
    ("Build and packaging", re.compile(r"^(build|package|release|ci|workflow|installer)\b", re.IGNORECASE)),
    ("Improvements", re.compile(r"^(improve|update|enhance|refine|optimize|support)\b", re.IGNORECASE)),
)
NOISE = re.compile(
    r"(dependabot|bump .* from .* to |format(?:ting)? only|generated files?|merge (?:branch|pull request))",
    re.IGNORECASE,
)


def git(*arguments: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=ROOT, check=check, capture_output=True, text=True
    )
    return result.stdout.strip()


def tag_exists(tag: str) -> bool:
    return subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"],
        cwd=ROOT,
        capture_output=True,
    ).returncode == 0


def previous_tag(tag: str) -> str | None:
    reference = f"{tag}^" if tag_exists(tag) else "HEAD"
    tags = git("tag", "--merged", reference, "--sort=-version:refname", check=False).splitlines()
    return next((value for value in tags if value.startswith("v") and value != tag), None)


def relevant_commits(tag: str) -> list[str]:
    previous = previous_tag(tag)
    end = tag if tag_exists(tag) else "HEAD"
    revision = f"{previous}..{end}" if previous else end
    subjects = git("log", revision, "--no-merges", "--format=%s").splitlines()
    return [subject.strip() for subject in subjects if subject.strip() and not NOISE.search(subject)]


def grouped_commits(subjects: list[str]) -> dict[str, list[str]]:
    groups = {name: [] for name in ("Features", "Fixes", "Improvements", "Documentation", "Build and packaging", "Internal changes")}
    for subject in subjects:
        section = "Internal changes"
        for name, pattern in SECTION_RULES:
            if pattern.search(subject):
                section = name
                break
        groups[section].append(subject.rstrip("."))
    return groups


def package_list(variant: str) -> list[str]:
    windows = list(WINDOWS_PACKAGES[variant])
    macos = list(MACOS_PACKAGES[variant].values())
    return windows + macos


def render(tag: str, markdown: bool) -> str:
    version = application_version()
    groups = grouped_commits(relevant_commits(tag))
    heading = (lambda value: f"## {value}") if markdown else (lambda value: value + "\n" + "-" * len(value))
    bullet = "- "
    lines = [
        "# PrintBridge Client Release Notes" if markdown else "PrintBridge Client Release Notes",
        "" if markdown else "=" * len("PrintBridge Client Release Notes"),
        "",
        f"Application version: {version}",
        f"Release date: {dt.datetime.now(dt.timezone.utc).date().isoformat()}",
        f"Git tag: {tag}",
        "Supported platforms: Windows x64, macOS arm64, macOS x86_64",
        "",
        heading("Available Native packages"),
        *[bullet + name for name in package_list("Native")],
        "",
        heading("Available PyInstaller packages"),
        *[bullet + name for name in package_list("PyInstaller")],
        "",
    ]
    release_sections = (
        ("New features", groups["Features"]),
        ("Improvements", groups["Improvements"]),
        ("Bug fixes", groups["Fixes"]),
        ("Documentation", groups["Documentation"]),
        ("Build and packaging", groups["Build and packaging"]),
        ("Internal changes", groups["Internal changes"]),
    )
    for name, entries in release_sections:
        lines.extend([heading(name), *[bullet + entry for entry in (entries or ["No changes recorded."])], ""])
    lines.extend(
        [
            heading("Known issues"),
            bullet + "Windows requires Microsoft WebView2 Runtime; the setup packages install it automatically when missing.",
            bullet + "Packages are unsigned unless the optional signing secrets are configured.",
            "",
            heading("Upgrade notes"),
            bullet + "Close an existing PrintBridge Client instance before installing or replacing a portable directory.",
            bullet + "Existing user configuration and credentials are preserved.",
            "",
            heading("Build system information"),
            bullet + "Native packages use Nuitka standalone compilation.",
            bullet + "PyInstaller packages use PyInstaller onedir application bundles.",
            bullet + "All packages are self-contained and do not require Python or pip on the destination system.",
            "",
            heading("License and attribution notice"),
            bullet + f"License: {LICENSE_NAME}",
            bullet + f"Original author: {AUTHOR}",
            bullet + COPYRIGHT,
            bullet + "Additional attribution terms apply; see ADDITIONAL_TERMS.md included with each package.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate release notes from Git history.")
    parser.add_argument("--output-dir", help="Build output directory; defaults to PRINTBRIDGE_RELEASE_DIR or project/build.")
    parser.add_argument("--tag", default=os.environ.get("GITHUB_REF_NAME", ""), help="Release tag; defaults to GITHUB_REF_NAME.")
    parser.add_argument("--markdown-output", help="Optional path for the GitHub Release Markdown body.")
    args = parser.parse_args()

    output_dir = ensure_release_dir(args.output_dir)
    tag = args.tag.strip() or f"v{application_version()}"
    destination = output_dir / RELEASE_NOTES_NAME
    destination.write_text(render(tag, markdown=False), encoding="utf-8")
    if args.markdown_output:
        markdown_path = Path(args.markdown_output).expanduser().resolve()
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render(tag, markdown=True), encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
