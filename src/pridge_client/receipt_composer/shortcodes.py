# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import random
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pridge_client.printers import _RAW_MACRO_BYTES
from pridge_client.receipt_composer.store import DEFAULT_COUNTER_KEY


if TYPE_CHECKING:
    from pridge_client.receipt_composer.store import ReceiptComposerStore


TAG_RE = re.compile(r"\[(/?)([a-zA-Z_]+)(?::([^\]]*))?\]")

_ALIGN_BYTES = {
    "left": b"\x1b\x61\x00",
    "center": b"\x1b\x61\x01",
    "right": b"\x1b\x61\x02",
}
_BOLD_ON = b"\x1b\x45\x01"
_BOLD_OFF = b"\x1b\x45\x00"

# There is no universal ESC/POS italic command. Rather than guess a byte
# sequence that may do something unintended on a given printer model, italic
# is a documented no-op in this version — see raw_composer strings for the
# user-facing hint.
_ITALIC_ON = b""
_ITALIC_OFF = b""

DEFAULT_RANDOM_DIGITS = 6
DEFAULT_DATE_FORMAT = "%Y-%m-%d"


def render_template(
    template: str,
    *,
    printer_name: str,
    store: "ReceiptComposerStore",
    paper_width_dots: int,
    chars_per_line: int,
    commit: bool = True,
) -> bytes:
    """Resolve a Receipt Composer shortcode template to literal bytes.

    Never raises: unknown or malformed tags resolve to no bytes rather than
    printing garbage or a literal "[tag]" on an unattended receipt printer.
    The one deliberate exception is `[counter:name]` for a name that doesn't
    exist yet — that auto-creates the counter rather than silently dropping
    it, since the tag shape is still recognized, only the name is new.

    When `commit` is False (used for the settings-window preview), counters
    are peeked at their next value rather than actually incremented, so
    editing a template never burns through real print numbers.
    """
    if not template:
        return b""

    output = bytearray()
    pos = 0
    for match in TAG_RE.finditer(template):
        literal = template[pos : match.start()]
        if literal:
            output.extend(_encode_text(literal))
        pos = match.end()

        closing, name, arg = match.group(1), match.group(2).lower(), match.group(3)
        if closing:
            output.extend(_resolve_closing_tag(name))
        else:
            output.extend(
                _resolve_tag(
                    name,
                    arg,
                    printer_name=printer_name,
                    store=store,
                    paper_width_dots=paper_width_dots,
                    chars_per_line=chars_per_line,
                    commit=commit,
                )
            )

    trailing = template[pos:]
    if trailing:
        output.extend(_encode_text(trailing))

    return bytes(output)


def render_template_blocks(
    template: str,
    *,
    printer_name: str,
    store: "ReceiptComposerStore",
    chars_per_line: int,
) -> list[dict[str, Any]]:
    """Dry-run parse of a shortcode template into structured preview blocks.

    Used by the settings-window live preview to render an approximate CSS
    representation of the composed receipt. Counters are always peeked, never
    incremented — this must be safe to call on every keystroke.
    """
    if not template:
        return []

    blocks: list[dict[str, Any]] = []
    pos = 0
    for match in TAG_RE.finditer(template):
        literal = template[pos : match.start()]
        if literal:
            blocks.append({"type": "text", "value": literal})
        pos = match.end()

        closing, name, arg = match.group(1), match.group(2).lower(), match.group(3)
        block = (
            _preview_closing_block(name)
            if closing
            else _preview_block(name, arg, printer_name=printer_name, store=store, chars_per_line=chars_per_line)
        )
        if block is not None:
            blocks.append(block)

    trailing = template[pos:]
    if trailing:
        blocks.append({"type": "text", "value": trailing})

    return blocks


def _preview_block(
    name: str,
    arg: str | None,
    *,
    printer_name: str,
    store: "ReceiptComposerStore",
    chars_per_line: int,
) -> dict[str, Any] | None:
    if name == "align":
        value = (arg or "").strip().lower()
        return {"type": "align", "value": value if value in _ALIGN_BYTES else "left"}
    if name == "bold":
        return {"type": "bold_start"}
    if name == "italic":
        return {"type": "italic_start"}
    if name == "hr":
        return {"type": "hr", "width": max(1, chars_per_line)}
    if name == "blank":
        return {"type": "blank"}
    if name == "newline":
        return {"type": "newline"}
    if name == "date":
        fmt = (arg or "").strip() or DEFAULT_DATE_FORMAT
        try:
            return {"type": "text", "value": datetime.now().strftime(fmt)}
        except ValueError:
            return {"type": "text", "value": datetime.now().strftime(DEFAULT_DATE_FORMAT)}
    if name == "random":
        digits = max(1, min(_safe_positive_int(arg, DEFAULT_RANDOM_DIGITS), 12))
        return {"type": "text", "value": str(random.randint(0, 10**digits - 1)).zfill(digits)}
    if name == "print_number":
        return {"type": "text", "value": str(_peek_counter(store, printer_name, DEFAULT_COUNTER_KEY))}
    if name == "counter":
        key = (arg or "").strip()
        if not key:
            return None
        return {"type": "text", "value": str(_peek_counter(store, printer_name, key))}
    if name == "image":
        image_id = (arg or "").strip()
        return {"type": "image", "image_id": image_id} if image_id else None
    if name == "cut":
        return {"type": "marker", "label": f"cut:{(arg or '').strip().lower() or 'full'}"}
    if name == "drawer":
        return {"type": "marker", "label": "drawer"}
    if name == "feed":
        return {"type": "marker", "label": f"feed:{_safe_positive_int(arg, 4)}"}
    if name == "hex":
        return {"type": "marker", "label": "hex"}
    return None


def _preview_closing_block(name: str) -> dict[str, Any] | None:
    if name == "bold":
        return {"type": "bold_end"}
    if name == "italic":
        return {"type": "italic_end"}
    return None


def _resolve_tag(
    name: str,
    arg: str | None,
    *,
    printer_name: str,
    store: "ReceiptComposerStore",
    paper_width_dots: int,
    chars_per_line: int,
    commit: bool,
) -> bytes:
    if name == "align":
        return _ALIGN_BYTES.get((arg or "").strip().lower(), b"")
    if name == "bold":
        return _BOLD_ON
    if name == "italic":
        return _ITALIC_ON
    if name == "hr":
        return _encode_text("-" * max(1, chars_per_line) + "\n")
    if name in ("blank", "newline"):
        return b"\n"
    if name == "date":
        fmt = (arg or "").strip() or DEFAULT_DATE_FORMAT
        try:
            return _encode_text(datetime.now().strftime(fmt))
        except ValueError:
            return _encode_text(datetime.now().strftime(DEFAULT_DATE_FORMAT))
    if name == "random":
        digits = max(1, min(_safe_positive_int(arg, DEFAULT_RANDOM_DIGITS), 12))
        return _encode_text(str(random.randint(0, 10**digits - 1)).zfill(digits))
    if name == "print_number":
        value = (
            store.increment(printer_name, DEFAULT_COUNTER_KEY)
            if commit
            else _peek_counter(store, printer_name, DEFAULT_COUNTER_KEY)
        )
        return _encode_text(str(value))
    if name == "counter":
        key = (arg or "").strip()
        if not key:
            return b""
        value = store.increment(printer_name, key) if commit else _peek_counter(store, printer_name, key)
        return _encode_text(str(value))
    if name == "image":
        return _resolve_image_tag((arg or "").strip(), store=store, paper_width_dots=paper_width_dots)
    if name == "cut":
        return _RAW_MACRO_BYTES.get(f"{(arg or '').strip().lower()}_cut", b"")
    if name == "drawer":
        return _RAW_MACRO_BYTES.get("open_drawer", b"")
    if name == "feed":
        lines = _safe_positive_int(arg, 4)
        if lines == 4:
            return _RAW_MACRO_BYTES.get("feed", b"\x1b\x64\x04")
        return b"\x1b\x64" + bytes([min(max(lines, 1), 255)])
    if name == "hex":
        return _resolve_hex_tag(arg or "")
    return b""


def _resolve_closing_tag(name: str) -> bytes:
    if name == "bold":
        return _BOLD_OFF
    if name == "italic":
        return _ITALIC_OFF
    return b""


def _resolve_image_tag(image_id: str, *, store: "ReceiptComposerStore", paper_width_dots: int) -> bytes:
    if not image_id:
        return b""
    data = store.load_image_bytes(image_id)
    if data is None:
        return b""
    from pridge_client.receipt_composer.raster import image_to_escpos_raster

    try:
        return image_to_escpos_raster(data, target_width_dots=paper_width_dots)
    except ValueError:
        return b""


def _resolve_hex_tag(raw_hex: str) -> bytes:
    cleaned = re.sub(r"[\s:-]", "", raw_hex)
    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        return b""


def _peek_counter(store: "ReceiptComposerStore", printer_name: str, counter_key: str) -> int:
    counters = store.get_counters(printer_name)
    entry = counters.get(counter_key)
    return _safe_int(entry.get("value"), 0) + 1 if entry else 1


def _encode_text(text: str) -> bytes:
    return text.encode("ascii", errors="replace")


def _safe_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default
    return parsed if parsed > 0 else default


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
