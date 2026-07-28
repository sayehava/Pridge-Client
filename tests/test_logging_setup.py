# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import logging
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pridge_client.config import ClientConfig
from pridge_client.logging_setup import configure_logging, prune_old_logs, redact


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
        self.addCleanup(logging.getLogger().handlers.clear)

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


if __name__ == "__main__":
    unittest.main()
