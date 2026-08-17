# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from pridge_client.archive import ArchiveStore
from pridge_client.config import ClientConfig, ConfigStore
from pridge_client.headless_tui import HeadlessTuiController


class HeadlessTuiControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        config_store = ConfigStore(Path(self.directory.name) / "config.json")
        config_store.save(ClientConfig())
        self.api = Mock()
        self.api.config_store = config_store
        self.api.token_store = Mock()
        self.api.printer_manager = Mock()
        self.api.archive_store = ArchiveStore(Path(self.directory.name) / "archive.sqlite3")
        self.api.config = config_store.load()
        self.api.workers = {}
        self.browser_toggle = Mock(return_value="Browser GUI: http://127.0.0.1:8765")
        self.controller = HeadlessTuiController(self.api, self.browser_toggle)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_starts_and_stops_the_shared_browser_api_workers(self) -> None:
        self.controller.start()
        self.controller.stop_all()

        self.api.start_workers.assert_called_once_with()
        self.api.stop_workers.assert_called_once_with()

    def test_browser_setting_takes_effect_immediately(self) -> None:
        result = self.controller.toggle_setting(3)

        self.assertEqual(result, "Browser GUI: http://127.0.0.1:8765")
        self.assertTrue(self.api.config.web_gui_enabled)
        self.assertTrue(self.api.config_store.load().web_gui_enabled)
        self.browser_toggle.assert_called_once_with(True)


if __name__ == "__main__":
    unittest.main()
