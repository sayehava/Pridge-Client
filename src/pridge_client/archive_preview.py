# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

"""Create bounded, browser-safe previews from locally archived print data."""

from __future__ import annotations

import base64
import io
import logging
from typing import Any

from pridge_client.archive import ArchivedJob
from pridge_client.pdfium_service import PDFiumRenderService


logger = logging.getLogger(__name__)
MAX_TEXT_BYTES = 64 * 1024
MAX_TEXT_CHARS = 12_000
MAX_IMAGE_EDGE = 1_200
IMAGE_HEADERS = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"BM", b"II*\x00", b"MM\x00*")


def build_archive_preview(job: ArchivedJob, pdf_service: PDFiumRenderService | None = None) -> dict[str, Any]:
    data = job.payload
    if data.startswith(b"%PDF-") or job.content_type == "application/pdf":
        try:
            return _pdf_preview(data, pdf_service or PDFiumRenderService())
        except Exception:
            logger.debug("Could not create PDF archive preview", exc_info=True)
            return _unavailable("This PDF could not be previewed.")
    if _looks_like_image(data, job.content_type):
        try:
            return _image_preview(data)
        except Exception:
            logger.debug("Could not create image archive preview", exc_info=True)
    return _text_preview(data, raw=job.mode == "raw")


def _pdf_preview(data: bytes, service: PDFiumRenderService) -> dict[str, Any]:
    page_count = service.get_page_count(data)
    pages = service.render_pages(data, target_dpi=96.0, page_indices=[0])
    if not pages:
        raise ValueError("PDF has no renderable pages")
    page = pages[0]
    from PIL import Image

    image = Image.frombytes("RGBA", (page.width_px, page.height_px), page.data, "raw", "BGRA").convert("RGB")
    image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    return {
        "kind": "image",
        "data_url": _png_data_url(image),
        "page_count": page_count,
        "note": "Showing the first page." if page_count > 1 else "",
    }


def _image_preview(data: bytes) -> dict[str, Any]:
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    if getattr(image, "n_frames", 1) > 1:
        image.seek(0)
    image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    return {"kind": "image", "data_url": _png_data_url(image.convert("RGB")), "page_count": 1, "note": ""}


def _png_data_url(image: Any) -> str:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _looks_like_image(data: bytes, content_type: str) -> bool:
    if content_type.startswith("image/") and content_type != "image/svg+xml":
        return True
    if any(data.startswith(header) for header in IMAGE_HEADERS):
        return True
    return data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP"


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
