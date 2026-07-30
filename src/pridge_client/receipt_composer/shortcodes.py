# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
import random
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pridge_client.printers import _RAW_MACRO_BYTES
from pridge_client.receipt_composer.store import DEFAULT_COUNTER_KEY


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from pridge_client.receipt_composer.store import ReceiptComposerStore

    # A third-party plugin's custom shortcode resolver: given the tag's raw
    # argument (None if the tag had no `:argument`), return the literal bytes
    # to splice into the template output. Never called for a name the built-in
    # vocabulary already recognizes - see plugin.md's cross-plugin shortcode idea.
    ShortcodeResolver = Callable[[str | None], bytes]


logger = logging.getLogger(__name__)

TAG_RE = re.compile(r"\[(/?)([a-zA-Z_]+)(?::([^\]]*))?\]")

# Names a third-party plugin's receipt_shortcodes may never claim - checked by
# PrinterManager.receipt_shortcode_resolvers() so a plugin can never shadow the
# built-in vocabulary regardless of registration order.
BUILTIN_SHORTCODE_NAMES = frozenset(
    {
        "align",
        "bold",
        "hr",
        "blank",
        "newline",
        "date",
        "random",
        "print_number",
        "counter",
        "image",
        "cut",
        "drawer",
        "feed",
        "hex",
        "dec",
    }
)

_ALIGN_BYTES = {
    "left": b"\x1b\x61\x00",
    "center": b"\x1b\x61\x01",
    "right": b"\x1b\x61\x02",
}
_BOLD_ON = b"\x1b\x45\x01"
_BOLD_OFF = b"\x1b\x45\x00"

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
    custom_resolvers: "Mapping[str, ShortcodeResolver] | None" = None,
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

    `custom_resolvers` is an optional tag-name -> callable map contributed by
    third-party renderer plugins (see PrinterManager.receipt_shortcode_resolvers);
    it's only ever consulted after every built-in tag name has been ruled out,
    so a plugin can never shadow or override the built-in vocabulary.
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
                    custom_resolvers=custom_resolvers,
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
    custom_resolvers: "Mapping[str, ShortcodeResolver] | None" = None,
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
            else _preview_block(
                name,
                arg,
                printer_name=printer_name,
                store=store,
                chars_per_line=chars_per_line,
                custom_resolvers=custom_resolvers,
            )
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
    custom_resolvers: "Mapping[str, ShortcodeResolver] | None" = None,
) -> dict[str, Any] | None:
    if name == "align":
        value = (arg or "").strip().lower()
        return {"type": "align", "value": value if value in _ALIGN_BYTES else "left"}
    if name == "bold":
        return {"type": "bold_start"}
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
        parts = (arg or "").split(":", 1)
        cut_type = parts[0].strip().lower() or "full"
        feed_lines = max(0, _safe_int(parts[1], 0)) if len(parts) > 1 else 0
        suffix = f" +{feed_lines}feed" if feed_lines > 0 else ""
        return {"type": "marker", "label": f"cut:{cut_type}{suffix}"}
    if name == "drawer":
        return {"type": "marker", "label": "drawer"}
    if name == "feed":
        return {"type": "marker", "label": f"feed:{_safe_positive_int(arg, 4)}"}
    if name == "hex":
        return {"type": "marker", "label": "hex"}
    if name == "dec":
        return {"type": "marker", "label": "dec"}
    if custom_resolvers and name in custom_resolvers:
        return {"type": "marker", "label": name}
    return None


def _preview_closing_block(name: str) -> dict[str, Any] | None:
    if name == "bold":
        return {"type": "bold_end"}
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
    custom_resolvers: "Mapping[str, ShortcodeResolver] | None" = None,
) -> bytes:
    if name == "align":
        return _ALIGN_BYTES.get((arg or "").strip().lower(), b"")
    if name == "bold":
        return _BOLD_ON
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
        return _resolve_cut_tag(arg or "")
    if name == "drawer":
        return _RAW_MACRO_BYTES.get("open_drawer", b"")
    if name == "feed":
        return _feed_bytes(_safe_positive_int(arg, 4))
    if name == "hex":
        return _resolve_hex_tag(arg or "")
    if name == "dec":
        return _resolve_dec_tag(arg or "")
    return _resolve_custom_tag(name, arg, custom_resolvers)


def _resolve_closing_tag(name: str) -> bytes:
    if name == "bold":
        return _BOLD_OFF
    return b""


def _resolve_custom_tag(
    name: str, arg: str | None, custom_resolvers: "Mapping[str, ShortcodeResolver] | None"
) -> bytes:
    if not custom_resolvers:
        return b""
    resolver = custom_resolvers.get(name)
    if resolver is None:
        return b""
    try:
        result = resolver(arg)
    except Exception:
        logger.warning("Third-party shortcode '%s' raised while resolving; treating as empty.", name, exc_info=True)
        return b""
    return result if isinstance(result, (bytes, bytearray)) else b""


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


def _feed_bytes(lines: int) -> bytes:
    if lines <= 0:
        return b""
    if lines == 4:
        return _RAW_MACRO_BYTES.get("feed", b"\x1b\x64\x04")
    return b"\x1b\x64" + bytes([min(max(lines, 1), 255)])


def _resolve_cut_tag(raw_arg: str) -> bytes:
    """`[cut:full]` / `[cut:partial]`, or `[cut:full:6]` to feed N lines
    first — most thermal printers mount the cutter blade some distance
    below the print head, so cutting immediately after the last line can
    slice through content that hasn't cleared the blade yet. The feed
    count is opt-in and defaults to 0 (identical to the pre-existing
    two-argument form) so old templates keep behaving exactly as before.
    """
    parts = raw_arg.split(":", 1)
    cut_type = parts[0].strip().lower() or "full"
    feed_lines = max(0, _safe_int(parts[1], 0)) if len(parts) > 1 else 0
    return _feed_bytes(feed_lines) + _RAW_MACRO_BYTES.get(f"{cut_type}_cut", b"")


def _resolve_hex_tag(raw_hex: str) -> bytes:
    cleaned = re.sub(r"[\s:-]", "", raw_hex)
    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        return b""


def _resolve_dec_tag(raw_decimal: str) -> bytes:
    tokens = re.split(r"[\s,]+", raw_decimal.strip())
    tokens = [token for token in tokens if token]
    if not tokens:
        return b""
    try:
        values = [int(token) for token in tokens]
    except ValueError:
        return b""
    if any(value < 0 or value > 255 for value in values):
        return b""
    return bytes(values)


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
