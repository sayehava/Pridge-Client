# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pridge_client.receipt_composer.shortcodes import render_template, render_template_blocks
from pridge_client.receipt_composer.store import ReceiptComposerStore


def _render(template: str, store: ReceiptComposerStore, printer_name: str = "Kitchen Printer", **kwargs) -> bytes:
    kwargs.setdefault("paper_width_dots", 384)
    kwargs.setdefault("chars_per_line", 10)
    return render_template(template, printer_name=printer_name, store=store, **kwargs)


def _blocks(template: str, store: ReceiptComposerStore, printer_name: str = "Kitchen Printer", **kwargs):
    kwargs.setdefault("chars_per_line", 10)
    return render_template_blocks(template, printer_name=printer_name, store=store, **kwargs)


class ShortcodeTagTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = ReceiptComposerStore(Path(self.temporary_directory.name))

    def test_plain_text_passes_through_unchanged(self) -> None:
        self.assertEqual(_render("Thank you!", self.store), b"Thank you!")

    def test_align_left_center_right(self) -> None:
        self.assertEqual(_render("[align:left]", self.store), b"\x1b\x61\x00")
        self.assertEqual(_render("[align:center]", self.store), b"\x1b\x61\x01")
        self.assertEqual(_render("[align:right]", self.store), b"\x1b\x61\x02")

    def test_align_does_not_require_a_closing_tag(self) -> None:
        result = _render("[align:center]Hi", self.store)
        self.assertEqual(result, b"\x1b\x61\x01Hi")

    def test_bold_wraps_text_with_on_off_bytes(self) -> None:
        self.assertEqual(_render("[bold]Hi[/bold]", self.store), b"\x1b\x45\x01Hi\x1b\x45\x00")

    def test_italic_is_a_documented_no_op(self) -> None:
        self.assertEqual(_render("[italic]Hi[/italic]", self.store), b"Hi")

    def test_hr_emits_a_dash_line_sized_to_chars_per_line(self) -> None:
        self.assertEqual(_render("[hr]", self.store, chars_per_line=5), b"-----\n")

    def test_blank_and_newline_both_emit_a_single_newline(self) -> None:
        self.assertEqual(_render("[blank]", self.store), b"\n")
        self.assertEqual(_render("[newline]", self.store), b"\n")

    def test_date_uses_the_default_format(self) -> None:
        from datetime import datetime

        expected = datetime.now().strftime("%Y-%m-%d").encode("ascii")
        self.assertEqual(_render("[date]", self.store), expected)

    def test_date_accepts_a_custom_strftime_format(self) -> None:
        from datetime import datetime

        expected = datetime.now().strftime("%Y").encode("ascii")
        self.assertEqual(_render("[date:%Y]", self.store), expected)

    def test_random_default_is_six_zero_padded_digits(self) -> None:
        result = _render("[random]", self.store)
        self.assertEqual(len(result), 6)
        self.assertTrue(result.isdigit())

    def test_random_with_explicit_digit_count(self) -> None:
        result = _render("[random:3]", self.store)
        self.assertEqual(len(result), 3)

    def test_cut_full_and_partial(self) -> None:
        self.assertEqual(_render("[cut:full]", self.store), b"\x1d\x56\x00")
        self.assertEqual(_render("[cut:partial]", self.store), b"\x1d\x56\x01")

    def test_drawer(self) -> None:
        self.assertEqual(_render("[drawer]", self.store), b"\x1b\x70\x00\x19\xfa")

    def test_feed_default_matches_the_legacy_macro_bytes(self) -> None:
        self.assertEqual(_render("[feed]", self.store), b"\x1b\x64\x04")
        self.assertEqual(_render("[feed:4]", self.store), b"\x1b\x64\x04")

    def test_feed_with_a_different_line_count(self) -> None:
        self.assertEqual(_render("[feed:2]", self.store), b"\x1b\x64\x02")

    def test_hex_accepts_spaces_and_separators(self) -> None:
        self.assertEqual(_render("[hex:1D 56 00]", self.store), b"\x1d\x56\x00")
        self.assertEqual(_render("[hex:1d:56:00]", self.store), b"\x1d\x56\x00")

    def test_hex_malformed_resolves_to_nothing(self) -> None:
        self.assertEqual(_render("[hex:not-valid-hex]", self.store), b"")
        self.assertEqual(_render("[hex:1d5]", self.store), b"")

    def test_dec_accepts_space_and_comma_separated_byte_values(self) -> None:
        self.assertEqual(_render("[dec:29 86 0]", self.store), b"\x1d\x56\x00")
        self.assertEqual(_render("[dec:29,86,0]", self.store), b"\x1d\x56\x00")

    def test_dec_malformed_or_out_of_range_resolves_to_nothing(self) -> None:
        self.assertEqual(_render("[dec:not-a-number]", self.store), b"")
        self.assertEqual(_render("[dec:29 256 0]", self.store), b"")
        self.assertEqual(_render("[dec:29 -1 0]", self.store), b"")

    def test_dec_empty_resolves_to_nothing(self) -> None:
        self.assertEqual(_render("[dec:]", self.store), b"")
        self.assertEqual(_render("[dec:   ]", self.store), b"")

    def test_unknown_tag_resolves_to_nothing_not_literal_text(self) -> None:
        self.assertEqual(_render("[blod]", self.store), b"")

    def test_unknown_tag_surrounded_by_text_only_drops_the_tag(self) -> None:
        self.assertEqual(_render("A[blod]B", self.store), b"AB")


class ShortcodeCounterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = ReceiptComposerStore(Path(self.temporary_directory.name))

    def test_print_number_increments_the_default_counter_on_commit(self) -> None:
        first = _render("[print_number]", self.store)
        second = _render("[print_number]", self.store)

        self.assertEqual(first, b"1")
        self.assertEqual(second, b"2")

    def test_named_counter_auto_vivifies_on_first_use(self) -> None:
        result = _render("[counter:daily_orders]", self.store)

        self.assertEqual(result, b"1")
        self.assertIn("daily_orders", self.store.get_counters("Kitchen Printer"))

    def test_counter_with_no_name_resolves_to_nothing(self) -> None:
        self.assertEqual(_render("[counter:]", self.store), b"")

    def test_dry_run_does_not_increment_print_number(self) -> None:
        first = _render("[print_number]", self.store, commit=False)
        second = _render("[print_number]", self.store, commit=False)

        self.assertEqual(first, b"1")
        self.assertEqual(second, b"1")
        self.assertEqual(self.store.get_counters("Kitchen Printer"), {})

    def test_dry_run_previews_the_next_value_after_a_real_increment(self) -> None:
        _render("[print_number]", self.store)  # commits, value becomes 1

        preview = _render("[print_number]", self.store, commit=False)

        self.assertEqual(preview, b"2")
        self.assertEqual(self.store.get_counters("Kitchen Printer")["__default__"]["value"], 1)

    def test_counters_are_independent_per_printer(self) -> None:
        _render("[print_number]", self.store, printer_name="Kitchen Printer")
        _render("[print_number]", self.store, printer_name="Kitchen Printer")

        result = _render("[print_number]", self.store, printer_name="Bar Printer")

        self.assertEqual(result, b"1")


class ShortcodeImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = ReceiptComposerStore(Path(self.temporary_directory.name))

    def test_unknown_image_id_resolves_to_nothing(self) -> None:
        self.assertEqual(_render("[image:nothing-here]", self.store), b"")

    def test_known_image_resolves_to_raster_bytes(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), color=(0, 0, 0)).save(buf, format="PNG")
        image = self.store.add_image("Logo", buf.getvalue())

        result = _render(f"[image:{image.id}]", self.store)

        self.assertTrue(result.startswith(b"\x1d\x76\x30"))

    def test_no_image_id_resolves_to_nothing(self) -> None:
        self.assertEqual(_render("[image:]", self.store), b"")


class ShortcodePreviewBlockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = ReceiptComposerStore(Path(self.temporary_directory.name))

    def test_plain_text_becomes_a_single_text_block(self) -> None:
        self.assertEqual(_blocks("Thank you!", self.store), [{"type": "text", "value": "Thank you!"}])

    def test_align_bold_italic_and_layout_tags_become_typed_blocks(self) -> None:
        self.assertEqual(
            _blocks("[align:center][bold]Hi[/bold][italic]Yo[/italic][hr][blank][newline]", self.store),
            [
                {"type": "align", "value": "center"},
                {"type": "bold_start"},
                {"type": "text", "value": "Hi"},
                {"type": "bold_end"},
                {"type": "italic_start"},
                {"type": "text", "value": "Yo"},
                {"type": "italic_end"},
                {"type": "hr", "width": 10},
                {"type": "blank"},
                {"type": "newline"},
            ],
        )

    def test_unrecognized_align_value_falls_back_to_left(self) -> None:
        self.assertEqual(_blocks("[align:diagonal]", self.store), [{"type": "align", "value": "left"}])

    def test_print_number_and_counter_are_peeked_not_incremented(self) -> None:
        blocks = _blocks("[print_number][counter:vip]", self.store)

        self.assertEqual(blocks, [{"type": "text", "value": "1"}, {"type": "text", "value": "1"}])
        self.assertEqual(self.store.get_counters("Kitchen Printer"), {})

    def test_image_tag_becomes_an_image_block(self) -> None:
        self.assertEqual(_blocks("[image:abc123]", self.store), [{"type": "image", "image_id": "abc123"}])

    def test_empty_image_tag_is_dropped(self) -> None:
        self.assertEqual(_blocks("[image:]", self.store), [])

    def test_cut_drawer_feed_hex_and_dec_become_marker_blocks(self) -> None:
        self.assertEqual(
            _blocks("[cut:full][drawer][feed:6][hex:1D 56 00][dec:29 86 0]", self.store),
            [
                {"type": "marker", "label": "cut:full"},
                {"type": "marker", "label": "drawer"},
                {"type": "marker", "label": "feed:6"},
                {"type": "marker", "label": "hex"},
                {"type": "marker", "label": "dec"},
            ],
        )

    def test_unknown_tag_is_dropped(self) -> None:
        self.assertEqual(_blocks("[blod]", self.store), [])

    def test_empty_template_returns_no_blocks(self) -> None:
        self.assertEqual(_blocks("", self.store), [])


if __name__ == "__main__":
    unittest.main()
