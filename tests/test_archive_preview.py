# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import base64
import unittest
from datetime import datetime, timezone

from pridge_client.archive import ArchivedJob
from pridge_client.archive_preview import build_archive_preview


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def archived(payload: bytes, **fields) -> ArchivedJob:
    values = {
        "id": "entry-1",
        "job_id": "job-1",
        "printer_name": "Kitchen",
        "status": "printed",
        "detail": "",
        "created_at": datetime.now(timezone.utc),
        "payload": payload,
    }
    values.update(fields)
    return ArchivedJob(**values)


class ArchivePreviewTests(unittest.TestCase):
    def test_previews_plain_text_without_returning_raw_bytes(self) -> None:
        preview = build_archive_preview(archived(b"Order 42\nTwo coffees", content_type="text/plain"))

        self.assertEqual(preview["kind"], "text")
        self.assertIn("Order 42", preview["text"])
        self.assertNotIn("data_url", preview)

    def test_raw_preview_removes_control_characters_and_explains_limitations(self) -> None:
        preview = build_archive_preview(archived(b"\x1b@Kitchen ticket\nBurger\x00", mode="raw"))

        self.assertEqual(preview["kind"], "text")
        self.assertNotIn("\x1b", preview["text"])
        self.assertIn("printable payload text", preview["note"])

    def test_previews_an_image_as_a_bounded_png_data_url(self) -> None:
        preview = build_archive_preview(archived(ONE_PIXEL_PNG, content_type="image/png"))

        self.assertEqual(preview["kind"], "image")
        self.assertTrue(preview["data_url"].startswith("data:image/png;base64,"))

if __name__ == "__main__":
    unittest.main()
