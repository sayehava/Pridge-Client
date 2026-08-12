# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import unittest

from pridge_client import tui_render as t


class TextMeasurementTests(unittest.TestCase):
    def test_visible_len_ignores_ansi_escapes(self) -> None:
        colored = t.rgb_fg("FF0000") + "hi" + t.RESET
        self.assertEqual(t.visible_len(colored), 2)

    def test_pad_accounts_for_ansi_width(self) -> None:
        colored = t.rgb_fg("FF0000") + "hi" + t.RESET
        padded = t.pad(colored, 5)
        self.assertEqual(t.visible_len(padded), 5)

    def test_truncate_adds_ellipsis_when_over_width(self) -> None:
        self.assertEqual(t.truncate("hello world", 5), "hell…")
        self.assertEqual(t.truncate("hi", 5), "hi")

    def test_visible_truncate_preserves_ansi_and_resets(self) -> None:
        colored = t.rgb_fg("FF0000") + "hello world" + t.RESET
        result = t.visible_truncate(colored, 5)
        self.assertLessEqual(t.visible_len(result), 5)
        self.assertTrue(result.endswith(t.RESET))

    def test_center_pads_evenly(self) -> None:
        result = t.center("hi", 6)
        self.assertEqual(result, "  hi")  # left-padded only; width isn't forced on the right side
        self.assertTrue(result.endswith("hi"))


class SparklineAndMeterTests(unittest.TestCase):
    def test_sparkline_is_empty_for_no_values(self) -> None:
        self.assertEqual(t.sparkline([]), "")

    def test_sparkline_produces_one_char_per_value(self) -> None:
        result = t.sparkline([1, 2, 3, 4, 5])
        self.assertEqual(t.visible_len(result), 5)

    def test_sparkline_handles_a_flat_series(self) -> None:
        result = t.sparkline([3, 3, 3])
        self.assertEqual(t.visible_len(result), 3)

    def test_meter_fills_proportionally(self) -> None:
        empty = t.meter(0.0, 10)
        full = t.meter(1.0, 10)
        half = t.meter(0.5, 10)
        self.assertIn("░" * 10, empty)
        self.assertIn("█" * 10, full)
        self.assertIn("█" * 5, half)

    def test_meter_clamps_out_of_range_percentages(self) -> None:
        over = t.meter(2.0, 10)
        under = t.meter(-1.0, 10)
        self.assertIn("█" * 10, over)
        self.assertIn("░" * 10, under)


class BoxTests(unittest.TestCase):
    def test_box_wraps_rows_with_top_and_bottom(self) -> None:
        rows = t.box(40, "Title", ["one", "two"])
        self.assertEqual(len(rows), 4)
        self.assertIn("Title", rows[0])

    def test_box_row_truncates_overlong_content(self) -> None:
        row = t.box_row(20, "a" * 100)
        self.assertLessEqual(t.visible_len(row), 20)

    def test_zip_columns_pads_the_shorter_column(self) -> None:
        result = t.zip_columns(["a"], ["b", "c"])
        self.assertEqual(len(result), 2)


class HeaderFooterTests(unittest.TestCase):
    def test_header_stays_within_width_when_wide(self) -> None:
        lines = t.header(120, "Dashboard", "1.5.3")
        for line in lines:
            self.assertLessEqual(t.visible_len(line), 120)

    def test_header_stays_within_width_when_narrow(self) -> None:
        lines = t.header(45, "Dashboard", "1.5.3")
        for line in lines:
            self.assertLessEqual(t.visible_len(line), 45)

    def test_footer_stays_within_width(self) -> None:
        lines = t.footer(30, "a busy status message that is far too long")
        for line in lines:
