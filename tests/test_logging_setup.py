# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import logging
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pridge_client.config import ClientConfig
from pridge_client.logging_setup import (
    clear_log_files,
    configure_logging,
    export_logs_to,
    has_log_files,
    parse_log_export_date,
    prune_old_logs,
    redact,
)


def _close_and_clear_root_handlers() -> None:
    root = logging.getLogger()
    for handler in root.handlers[:]:
        handler.close()
    root.handlers.clear()


class RedactionTests(unittest.TestCase):
    def test_redacts_bearer_token(self) -> None:
        self.assertEqual(redact("Authorization: Bearer abcdef1234567890"), "Authorization: Bearer [redacted]")

    def test_redacts_long_token_like_value(self) -> None:
        self.assertEqual(redact("token abcdef12zzzzzzzzzzzz"), "token abcdef12...[redacted]")


class ConfigureLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.temporary_directory.name)
        self.addCleanup(self.temporary_directory.cleanup)
        self.addCleanup(_close_and_clear_root_handlers)

    def test_writes_to_the_configured_directory(self) -> None:
        configure_logging(ClientConfig(), log_dir=self.log_dir)
        logging.getLogger("pridge.test").warning("hello")

        self.assertTrue((self.log_dir / "client.log").is_file())

    def test_disabling_file_logging_creates_no_file(self) -> None:
        config = ClientConfig()
        config.logging.file_enabled = False
        configure_logging(config, log_dir=self.log_dir)
        logging.getLogger("pridge.test").warning("hello")

        self.assertFalse((self.log_dir / "client.log").is_file())
        self.assertFalse(clear_log_files())

    def test_clear_log_files_truncates_current_file_and_removes_backups(self) -> None:
        configure_logging(ClientConfig(), log_dir=self.log_dir)
        logging.getLogger("pridge.test").warning("hello")
        (self.log_dir / "client.log.2026-07-01").write_text("old backup", encoding="utf-8")

        self.assertTrue(clear_log_files())

        self.assertEqual((self.log_dir / "client.log").read_text(encoding="utf-8"), "")
        self.assertFalse((self.log_dir / "client.log.2026-07-01").exists())

        logging.getLogger("pridge.test").warning("still writable")
        self.assertIn("still writable", (self.log_dir / "client.log").read_text(encoding="utf-8"))


class PruneOldLogsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.temporary_directory.name)
        self.addCleanup(self.temporary_directory.cleanup)

    def test_removes_files_older_than_the_retention_window(self) -> None:
        old_date = (date.today() - date.resolution * 40).isoformat()
        recent_date = (date.today() - date.resolution * 2).isoformat()
        (self.log_dir / f"client.log.{old_date}").write_text("old", encoding="utf-8")
        (self.log_dir / f"client.log.{recent_date}").write_text("recent", encoding="utf-8")

        prune_old_logs(self.log_dir, retention_days=14)

        self.assertFalse((self.log_dir / f"client.log.{old_date}").exists())
        self.assertTrue((self.log_dir / f"client.log.{recent_date}").exists())

    def test_ignores_files_without_a_date_suffix(self) -> None:
        (self.log_dir / "client.log").write_text("current", encoding="utf-8")

        prune_old_logs(self.log_dir, retention_days=1)

        self.assertTrue((self.log_dir / "client.log").exists())


class ExportLogsToTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.temporary_directory.name)
        self.destination = self.log_dir / "exported.log"
        self.addCleanup(self.temporary_directory.cleanup)

    def test_returns_false_when_no_log_files_exist(self) -> None:
        self.assertFalse(export_logs_to(self.log_dir, self.destination))
        self.assertFalse(has_log_files(self.log_dir))

    def test_exports_everything_when_no_range_is_given(self) -> None:
        (self.log_dir / "client.log").write_text("2026-07-20 10:00:00 INFO x: hello\n", encoding="utf-8")

        self.assertTrue(export_logs_to(self.log_dir, self.destination))
        self.assertEqual(self.destination.read_text(encoding="utf-8"), "2026-07-20 10:00:00 INFO x: hello\n")

    def test_filters_lines_outside_the_requested_date_range(self) -> None:
        (self.log_dir / "client.log.2026-07-01").write_text(
            "2026-07-01 09:00:00 INFO x: old entry\n", encoding="utf-8"
        )
        (self.log_dir / "client.log").write_text(
            "2026-07-20 10:00:00 INFO x: recent entry\n", encoding="utf-8"
        )

        export_logs_to(self.log_dir, self.destination, start_date=date(2026, 7, 15), end_date=date(2026, 7, 25))

        exported = self.destination.read_text(encoding="utf-8")
        self.assertNotIn("old entry", exported)
        self.assertIn("recent entry", exported)

    def test_keeps_untimestamped_continuation_lines_with_their_matched_entry(self) -> None:
        (self.log_dir / "client.log").write_text(
            "2026-07-20 10:00:00 ERROR x: boom\nTraceback details here\n", encoding="utf-8"
        )

        export_logs_to(self.log_dir, self.destination, start_date=date(2026, 7, 20), end_date=date(2026, 7, 20))

        self.assertIn("Traceback details here", self.destination.read_text(encoding="utf-8"))

    def test_returns_false_when_range_matches_nothing(self) -> None:
        (self.log_dir / "client.log").write_text("2026-07-20 10:00:00 INFO x: hello\n", encoding="utf-8")

        result = export_logs_to(self.log_dir, self.destination, start_date=date(2020, 1, 1), end_date=date(2020, 1, 2))

        self.assertFalse(result)


class ParseLogExportDateTests(unittest.TestCase):
    def test_parses_a_valid_iso_date(self) -> None:
        self.assertEqual(parse_log_export_date("2026-07-20"), date(2026, 7, 20))

    def test_returns_none_for_empty_or_invalid_input(self) -> None:
        self.assertIsNone(parse_log_export_date(""))
        self.assertIsNone(parse_log_export_date("not-a-date"))


if __name__ == "__main__":
    unittest.main()
