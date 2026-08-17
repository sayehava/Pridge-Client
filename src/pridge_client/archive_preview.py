# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

"""Create bounded, browser-safe previews from locally archived print data."""

from __future__ import annotations

from typing import Any

from pridge_client.archive import ArchivedJob


MAX_TEXT_BYTES = 64 * 1024
MAX_TEXT_CHARS = 12_000


def build_archive_preview(job: ArchivedJob) -> dict[str, Any]:
    return _text_preview(job.payload, raw=job.mode == "raw")


def _text_preview(data: bytes, raw: bool) -> dict[str, Any]:
    sample = data[:MAX_TEXT_BYTES]
    text = sample.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\ufffd", " ")
    text = "".join(character if character in "\n\t" or character.isprintable() else " " for character in text)
    text = text[:MAX_TEXT_CHARS].strip()
    if not text:
        return _unavailable("This archived format does not have a visual preview.")
    truncated = len(data) > len(sample) or len(text) >= MAX_TEXT_CHARS
    note = "Showing printable payload text; template decoration, controls, and graphics may not appear." if raw else ""
    if truncated:
        note = f"{note} Preview truncated.".strip()
    return {"kind": "text", "text": text, "truncated": truncated, "note": note}


def _unavailable(message: str) -> dict[str, Any]:
    return {"kind": "unavailable", "message": message, "note": ""}
