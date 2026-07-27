# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import unittest

from pridge_client.pdfium_service import PDFiumRenderService
from pridge_client.printers import create_test_page_pdf


class PDFiumRenderServiceTests(unittest.TestCase):
    def test_renders_a_real_pdf_page_with_the_installed_pypdfium2(self) -> None:
        service = PDFiumRenderService()
        pdf_data = create_test_page_pdf()

        pages = service.render_pages(pdf_data, target_dpi=150.0)

        self.assertEqual(len(pages), 1)
        page = pages[0]
        self.assertGreater(page.width_px, 0)
        self.assertGreater(page.height_px, 0)
        self.assertTrue(page.data)

    def test_declared_dimensions_match_the_actual_pixel_buffer(self) -> None:
        # A4 at 100dpi is a real case where round(width_pt * scale) (826) used to
        # disagree with PDFium's own rasterized width (827), silently shearing
        # every row of the decoded image. width_px/height_px must always be
        # PDFium's actual bitmap dimensions, never a separately rounded guess.
        service = PDFiumRenderService()
        pdf_data = create_test_page_pdf(595.0, 842.0)

        page = service.render_pages(pdf_data, target_dpi=100.0)[0]

        self.assertEqual(len(page.data), page.stride * page.height_px)
        self.assertGreaterEqual(page.stride, page.width_px * 4)


if __name__ == "__main__":
    unittest.main()
