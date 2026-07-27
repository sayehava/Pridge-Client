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


if __name__ == "__main__":
    unittest.main()
