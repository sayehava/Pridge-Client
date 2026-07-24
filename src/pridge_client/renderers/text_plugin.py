# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
import textwrap

from pridge_client.renderers.base import PRIDGE_RENDERER_API_VERSION, RenderError, RenderOptions


logger = logging.getLogger(__name__)

_SUPPORTED_MIME_TYPES: frozenset[str] = frozenset({
    "text/plain",
    "text/csv",
    "text/markdown",
})

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".txt", ".text", ".csv", ".md", ".markdown", ".log",
})

_A4_W = 595.0
_A4_H = 842.0
_AVG_CHAR_WIDTH_RATIO = 0.52


def _chars_per_line(font_size: float, available_width_pt: float) -> int:
    char_width = font_size * _AVG_CHAR_WIDTH_RATIO
    if char_width <= 0:
        return 80
    return max(10, int(available_width_pt / char_width))


def _detect_encoding(data: bytes, hint: str) -> str:
    if hint:
        return hint
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"


def _escape_pdf_string(text: str) -> bytes:
    encoded = text.encode("latin-1", errors="replace")
    result = bytearray()
    for byte in encoded:
        if byte == ord("("):
            result.extend(b"\\(")
        elif byte == ord(")"):
            result.extend(b"\\)")
        elif byte == ord("\\"):
            result.extend(b"\\\\")
        else:
            result.append(byte)
    return bytes(result)


def _build_text_pdf(
    pages: list[list[str]],
    font_size: float,
    line_height: float,
    margins: tuple[float, float, float, float],
    pw: float,
    ph: float,
) -> bytes:
    n = len(pages)
    margin_top, _mr, _mb, margin_left = margins

    # Object layout:
    # 1: Catalog
    # 2: Font (Helvetica)
    # 3 .. n+2: Content streams (one per page)
    # n+3 .. 2n+2: Page objects
    # 2n+3: Pages
    catalog_id = 1
    font_id = 2
    stream_base = 3
    page_base = stream_base + n
    pages_id = page_base + n

    objects: dict[int, bytes] = {}

    for i, page_lines in enumerate(pages):
        content = bytearray()
        content.extend(b"BT\n")
        content.extend(f"/F1 {font_size:.2f} Tf\n".encode())
        y_start = ph - margin_top - font_size
        first = True
        for line in page_lines:
            if first:
                content.extend(f"{margin_left:.2f} {y_start:.2f} Td\n".encode())
                first = False
            else:
                content.extend(f"0 {-line_height:.2f} Td\n".encode())
            content.extend(b"(" + _escape_pdf_string(line) + b") Tj\n")
        content.extend(b"ET\n")
        stream = bytes(content)
        objects[stream_base + i] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )

    kids = " ".join(f"{page_base + i} 0 R" for i in range(n))
    for i in range(n):
        objects[page_base + i] = (
            f"<< /Type /Page /Parent {pages_id} 0 R"
            f" /MediaBox [0 0 {pw:.2f} {ph:.2f}]"
            f" /Resources << /Font << /F1 {font_id} 0 R >> >>"
            f" /Contents {stream_base + i} 0 R >>".encode()
        )

    objects[pages_id] = f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode()
    objects[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objects[catalog_id] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()

    total = pages_id
    doc = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for obj_id in range(1, total + 1):
        if obj_id not in objects:
            continue
        offsets[obj_id] = len(doc)
        doc.extend(f"{obj_id} 0 obj\n".encode())
        doc.extend(objects[obj_id])
        doc.extend(b"\nendobj\n")

    xref_offset = len(doc)
    doc.extend(f"xref\n0 {total + 1}\n".encode())
    doc.extend(b"0000000000 65535 f \n")
    for obj_id in range(1, total + 1):
        doc.extend(f"{offsets.get(obj_id, 0):010d} 00000 n \n".encode())
    doc.extend(
        f"trailer\n<< /Size {total + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(doc)


class TextRendererPlugin:
    plugin_id = "pridge.renderer.text"
    display_name = "Text"
    version = "1.0.0"
    api_version = PRIDGE_RENDERER_API_VERSION
    supported_mime_types: frozenset[str] = _SUPPORTED_MIME_TYPES
    supported_extensions: frozenset[str] = _SUPPORTED_EXTENSIONS

    def can_render(
        self,
        *,
        mime_type: str | None,
        filename: str | None,
        data: bytes,
    ) -> bool:
        sample = data[:512]
        if not sample:
            return True
        # Reject if more than 10% of the sample are non-printable non-whitespace bytes
        non_text = sum(
            1 for b in sample
            if b < 0x09 or (0x0E <= b <= 0x1F) or b == 0x7F
        )
        if non_text / len(sample) > 0.10:
            return False
        for enc in ("utf-8", "latin-1"):
            try:
                sample.decode(enc)
                return True
            except UnicodeDecodeError:
                continue
        return False

    def render_to_pdf(
        self,
        *,
        data: bytes,
        mime_type: str | None,
        filename: str | None,
        options: RenderOptions,
    ) -> bytes:
        encoding = _detect_encoding(data, options.encoding)
        try:
            text = data.decode(encoding, errors="replace")
        except Exception as exc:
            raise RenderError(f"Could not decode text as {encoding}: {exc}") from exc

        margins = options.margins_pt
        font_size = options.font_size
        line_height = font_size * 1.4
        margin_top, _mr, margin_bottom, margin_left = margins
        pw, ph = _A4_W, _A4_H
        usable_w = pw - margin_left - (margins[1])
        usable_h = ph - margin_top - margin_bottom
        lines_per_page = max(1, int(usable_h / line_height))
        chars = _chars_per_line(font_size, usable_w) if options.line_wrap else 0

        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.expandtabs(options.tab_width)

        raw_lines = text.split("\n")
        wrapped: list[str] = []
        for raw in raw_lines:
            if chars > 0 and len(raw) > chars:
                wrapped.extend(textwrap.wrap(raw, width=chars) or [""])
            else:
                wrapped.append(raw)

        pages: list[list[str]] = [
            wrapped[i: i + lines_per_page]
            for i in range(0, max(1, len(wrapped)), lines_per_page)
        ] or [[""]]

        try:
            pdf_bytes = _build_text_pdf(pages, font_size, line_height, margins, pw, ph)
        except Exception as exc:
            raise RenderError(f"Could not convert text to PDF: {exc}") from exc

        logger.debug(
            "Text rendered to PDF: %d chars, %d page(s), %d bytes",
            len(text), len(pages), len(pdf_bytes),
        )
        return pdf_bytes
