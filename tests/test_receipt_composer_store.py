# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pridge_client.receipt_composer.store import ReceiptComposerStore


def _tiny_png_bytes() -> bytes:
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        raise unittest.SkipTest("Pillow not installed")
    buf = io.BytesIO()
    Image.new("RGB", (10, 6), color=(255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


class ReceiptImageStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = ReceiptComposerStore(Path(self.temporary_directory.name))

    def test_returns_empty_list_when_nothing_uploaded_yet(self) -> None:
        self.assertEqual(self.store.list_images(), [])

    def test_adds_and_lists_an_image_with_dimensions(self) -> None:
        image = self.store.add_image("Logo", _tiny_png_bytes())

        self.assertEqual(image.name, "Logo")
        self.assertEqual((image.width, image.height), (10, 6))
        listed = self.store.list_images()
        self.assertEqual([entry.id for entry in listed], [image.id])

    def test_untitled_name_when_blank(self) -> None:
        image = self.store.add_image("   ", _tiny_png_bytes())

        self.assertEqual(image.name, "Untitled")

    def test_loads_the_stored_image_bytes_back(self) -> None:
        image = self.store.add_image("Logo", _tiny_png_bytes())

        loaded = self.store.load_image_bytes(image.id)

        self.assertIsNotNone(loaded)
        self.assertTrue(loaded.startswith(b"\x89PNG"))

    def test_load_image_bytes_returns_none_for_an_unknown_id(self) -> None:
        self.assertIsNone(self.store.load_image_bytes("nothing-here"))

    def test_removes_an_image_and_its_file(self) -> None:
        image = self.store.add_image("Logo", _tiny_png_bytes())

        removed = self.store.remove_image(image.id)

        self.assertTrue(removed)
        self.assertEqual(self.store.list_images(), [])
        self.assertIsNone(self.store.load_image_bytes(image.id))

    def test_removing_an_unknown_image_id_is_a_no_op(self) -> None:
        self.assertFalse(self.store.remove_image("nothing-here"))

    def test_persists_across_store_instances(self) -> None:
        image = self.store.add_image("Logo", _tiny_png_bytes())

        reloaded = ReceiptComposerStore(Path(self.temporary_directory.name))

        self.assertEqual([entry.id for entry in reloaded.list_images()], [image.id])


class ReceiptCounterStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = ReceiptComposerStore(Path(self.temporary_directory.name))

    def test_get_counters_is_empty_for_an_unknown_printer(self) -> None:
        self.assertEqual(self.store.get_counters("Kitchen Printer"), {})

    def test_increment_creates_and_bumps_the_default_counter(self) -> None:
        first = self.store.increment("Kitchen Printer")
        second = self.store.increment("Kitchen Printer")

        self.assertEqual(first, 1)
        self.assertEqual(second, 2)
        self.assertEqual(self.store.get_counters("Kitchen Printer")["__default__"]["value"], 2)

    def test_increment_supports_independent_named_counters(self) -> None:
        self.store.increment("Kitchen Printer", "daily_orders")
        self.store.increment("Kitchen Printer", "daily_orders")
        self.store.increment("Kitchen Printer")

        counters = self.store.get_counters("Kitchen Printer")
        self.assertEqual(counters["daily_orders"]["value"], 2)
        self.assertEqual(counters["__default__"]["value"], 1)

    def test_counters_are_scoped_by_printer_name_only(self) -> None:
        self.store.increment("Kitchen Printer")
        self.store.increment("Kitchen Printer")

        self.assertEqual(self.store.get_counters("Bar Printer"), {})
        self.assertEqual(self.store.get_counters("Kitchen Printer")["__default__"]["value"], 2)

    def test_reset_sets_an_explicit_value(self) -> None:
        self.store.increment("Kitchen Printer")
        self.store.increment("Kitchen Printer")

        self.store.reset("Kitchen Printer", value=10)

        self.assertEqual(self.store.get_counters("Kitchen Printer")["__default__"]["value"], 10)

    def test_add_named_counter_does_not_reset_an_existing_one(self) -> None:
        self.store.increment("Kitchen Printer", "daily_orders")

        self.store.add_named_counter("Kitchen Printer", "daily_orders", "Daily Orders")

        self.assertEqual(self.store.get_counters("Kitchen Printer")["daily_orders"]["value"], 1)

    def test_add_named_counter_with_a_blank_key_is_a_no_op(self) -> None:
        self.store.add_named_counter("Kitchen Printer", "   ", "Ignored")

        self.assertEqual(self.store.get_counters("Kitchen Printer"), {})

    def test_remove_named_counter(self) -> None:
        self.store.add_named_counter("Kitchen Printer", "daily_orders", "Daily Orders")

        self.store.remove_named_counter("Kitchen Printer", "daily_orders")

        self.assertEqual(self.store.get_counters("Kitchen Printer"), {})

    def test_counters_persist_across_store_instances(self) -> None:
        self.store.increment("Kitchen Printer")

        reloaded = ReceiptComposerStore(Path(self.temporary_directory.name))

        self.assertEqual(reloaded.get_counters("Kitchen Printer")["__default__"]["value"], 1)


if __name__ == "__main__":
    unittest.main()
