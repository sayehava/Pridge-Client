# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
from dataclasses import dataclass


logger = logging.getLogger(__name__)

PIXEL_FORMAT_BGRA = "BGRA"
PIXEL_FORMAT_BGR = "BGR"


@dataclass
class RenderedPage:
    width_px: int
    height_px: int
    stride: int
    pixel_format: str
    data: bytes
    pdf_page_width_pt: float
    pdf_page_height_pt: float
    dpi: float
    has_alpha: bool = False


class PDFiumRenderService:
    def is_available(self) -> bool:
        try:
            import pypdfium2  # noqa: F401
            return True
        except ImportError:
            return False

    def get_page_count(self, pdf_data: bytes) -> int:
        try:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(pdf_data)
            count = len(doc)
            doc.close()
            return count
        except Exception:
            return 0

    def render_pages(
        self,
        pdf_data: bytes,
        *,
        target_dpi: float = 300.0,
        pixel_format: str = PIXEL_FORMAT_BGRA,
        page_indices: list[int] | None = None,
    ) -> list[RenderedPage]:
        from pridge_client.renderers.base import RenderError
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:
            raise RenderError(
                "PDFium rendering requires pypdfium2."
                " Install it or switch to direct PDF/CUPS submission."
            ) from exc

        doc = pdfium.PdfDocument(pdf_data)
        n_pages = len(doc)
        if page_indices is None:
            page_indices = list(range(n_pages))

        scale = target_dpi / 72.0
        use_alpha = pixel_format == PIXEL_FORMAT_BGRA
        rendered: list[RenderedPage] = []

        try:
            for idx in page_indices:
                if idx < 0 or idx >= n_pages:
                    logger.warning("Page index %d out of range (0..%d)", idx, n_pages - 1)
                    continue
                page = doc[idx]
                width_pt = page.get_width()
                height_pt = page.get_height()
                width_px = max(1, round(width_pt * scale))
                height_px = max(1, round(height_pt * scale))

                bitmap_format = pdfium.raw.FPDFBitmap_BGRA if use_alpha else pdfium.raw.FPDFBitmap_BGR
                bitmap = page.render(scale=scale, rotation=0, force_bitmap_format=bitmap_format)
                raw = bytes(bitmap.buffer)
                stride = bitmap.stride

                rendered.append(RenderedPage(
                    width_px=width_px,
                    height_px=height_px,
                    stride=stride,
                    pixel_format=PIXEL_FORMAT_BGRA if use_alpha else PIXEL_FORMAT_BGR,
                    data=raw,
                    pdf_page_width_pt=width_pt,
                    pdf_page_height_pt=height_pt,
                    dpi=target_dpi,
                    has_alpha=use_alpha,
                ))
                bitmap.close()
                page.close()
                logger.debug(
                    "PDFium rendered page %d: %dx%d px at %.0f dpi (%d bytes)",
                    idx, width_px, height_px, target_dpi, len(raw),
                )
        finally:
            doc.close()

        return rendered
