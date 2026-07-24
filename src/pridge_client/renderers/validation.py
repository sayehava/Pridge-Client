# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging

from pridge_client.renderers.base import RenderError


logger = logging.getLogger(__name__)


class PDFValidationService:
    def is_valid_pdf(self, data: bytes) -> bool:
        if not data.startswith(b"%PDF-"):
            return False
        try:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(data)
            valid = len(doc) >= 1
            doc.close()
            return valid
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("PDFium validation rejected document: %s", exc)
            return False
        return b"%%EOF" in data[-128:]

    def require_valid_pdf(self, data: bytes) -> None:
        if not self.is_valid_pdf(data):
            raise RenderError("The generated PDF is invalid.")
