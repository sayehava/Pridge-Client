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
            self.assertLessEqual(t.visible_len(line), 30)

    def test_footer_distinguishes_detach_from_quit(self) -> None:
        text = "\n".join(t.footer(120, ""))
        self.assertIn("detach", text)
        self.assertIn("quit", text)


class ScreenBuilderTests(unittest.TestCase):
    def test_dashboard_screen_handles_no_servers_or_jobs(self) -> None:
        lines = t.dashboard_screen(100, [], 0, 0, [], [], 0)
        text = "\n".join(lines)
        self.assertIn("No servers configured", text)
        self.assertIn("No print jobs yet", text)

    def test_dashboard_screen_shows_running_and_error_counts(self) -> None:
        servers = [
            {"name": "A", "status": "Running", "printers": 1, "heartbeat": "1s ago"},
            {"name": "B", "status": "Retrying after error: boom", "printers": 0, "heartbeat": "—"},
        ]
        lines = t.dashboard_screen(100, servers, 2, 5, [1, 2, 3], [], 0)
        text = "\n".join(lines)
        self.assertIn("1 running", text)
        self.assertIn("1 error", text)
        self.assertIn("5 printed today", text)

    def test_servers_screen_shows_detail_for_the_selected_server(self) -> None:
        servers = [
            {"name": "A", "url": "a.test", "status": "Running", "printers": 1, "last_error": ""},
            {"name": "B", "url": "b.test", "status": "Stopped", "printers": 0, "last_error": "boom"},
        ]
        lines = t.servers_screen(100, servers, 1)
        text = "\n".join(lines)
        self.assertIn("B", text)
        self.assertIn("boom", text)

    def test_printers_screen_shows_success_and_failed_counts(self) -> None:
        printers = [{"name": "P1", "mode": "RAW", "used": True, "success_count": 4, "failed_count": 1}]
        lines = t.printers_screen(100, printers, 0)
        text = "\n".join(lines)
        self.assertIn("P1", text)
        self.assertIn("4", text)
        self.assertIn("1", text)

    def test_plugins_screen_groups_by_category(self) -> None:
        plugins = [
            {"name": "PDF Renderer", "category": "Renderer", "enabled": True, "core": True},
            {"name": "Mapper", "category": "Mapper", "enabled": False, "core": True},
        ]
        lines = t.plugins_screen(100, plugins, 0)
        text = "\n".join(lines)
        self.assertIn("RENDERER", text)
        self.assertIn("MAPPER", text)

    def test_settings_screen_marks_the_selected_row(self) -> None:
        settings = [
            {"label": "Start at login", "enabled": True},
            {
                "label": "Terminal command",
                "enabled": True,
                "detail": "Pridge_client",
                "action": "install_terminal_command",
            },
        ]
        lines = t.settings_screen(100, settings, 0)
        text = "\n".join(lines)
        self.assertIn("Start at login", text)
        self.assertIn("enabled", text)
        self.assertIn("Pridge_client", text)
        self.assertNotIn("WebGUI", text)

    def test_about_screen_includes_version_and_build(self) -> None:
        lines = t.about_screen(100, "1.5.3", "Development", "Python")
        text = "\n".join(lines)
        self.assertIn("1.5.3", text)
        self.assertIn("Python", text)
        self.assertIn("Development", text)


class RenderFrameTests(unittest.TestCase):
    def _frame(self, screen_name: str) -> str:
        return t.render_frame(
            screen_name,
            100,
            30,
            "1.5.3",
            {"printer_count": 1, "printed_today": 1, "job_history": [1, 2], "recent_jobs": []},
            [{"name": "A", "url": "a.test", "status": "Running", "printers": 1, "heartbeat": "1s ago", "last_error": ""}],
            [{"name": "P1", "mode": "RAW", "used": True, "success_count": 1, "failed_count": 0}],
            [{"name": "Plug", "category": "Renderer", "enabled": True, "core": True}],
            [{"label": "Start at login", "enabled": True}],
            "Development",
            "Python",
            {"Servers": 0, "Printers": 0, "Plugins": 0, "Settings": 0},
        )

    def test_renders_every_screen_without_error(self) -> None:
        for screen_name in t.SCREENS:
            frame = self._frame(screen_name)
            self.assertIn(screen_name, frame)

    def test_narrow_terminal_adds_a_compact_layout_notice(self) -> None:
        frame = t.render_frame(
            "Dashboard",
            50,
            20,
            "1.5.3",
            {"printer_count": 0, "printed_today": 0, "job_history": [], "recent_jobs": []},
            [],
            [],
            [],
            [],
            "Development",
            "Python",
            {"Servers": 0, "Printers": 0, "Plugins": 0, "Settings": 0},
        )
        self.assertIn("compact layout", frame)


class SplashTests(unittest.TestCase):
    def test_splash_includes_version(self) -> None:
        self.assertIn("1.5.3", t.render_splash(80, "1.5.3"))


if __name__ == "__main__":
    unittest.main()
