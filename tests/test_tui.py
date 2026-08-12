# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from pridge_client.archive import ArchiveStore
from pridge_client.config import ClientConfig, ConfigStore, PrinterMapping, PrinterProfile, ServerConfig
from pridge_client.printers import Printer, PrinterError
from pridge_client.renderers.registry import RendererRegistry
from pridge_client.tui import TuiController, _detach_and_exit, _draw, _list_length


class FakePlugin:
    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        self.display_name = plugin_id
        self.version = "1.0.0"
        self.api_version = 1
        self.supported_mime_types = frozenset()
        self.supported_extensions = frozenset()

    def can_render(self, *, mime_type, filename, data):
        return False

    def render_to_pdf(self, *, data, mime_type, filename, options):
        raise NotImplementedError


class FakePrinterManager:
    def __init__(self, printers=None) -> None:
        self._printers = printers or []
        self.renderer_registry = RendererRegistry()

    def list_printers(self):
        return self._printers


class TuiControllerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        config_path = Path(self.temporary_directory.name) / "config.json"
        archive_path = Path(self.temporary_directory.name) / "archive.sqlite3"
        self.printer_manager = FakePrinterManager()
        self.controller = TuiController(
            config_store=ConfigStore(config_path),
            token_store=Mock(),
            printer_manager=self.printer_manager,
            archive_store=ArchiveStore(archive_path),
        )


class SettingsDataTests(TuiControllerTestCase):
    def test_settings_data_reflects_config_defaults(self) -> None:
        data = self.controller.settings_data()
        labels = [item["label"] for item in data]
        self.assertIn("Start at login", labels)
        self.assertIn("Restart automatically if the app crashes", labels)
        restart_item = next(item for item in data if "Restart" in item["label"])
        self.assertTrue(restart_item["enabled"])

    @patch("pridge_client.tui.set_start_at_login")
    def test_toggle_setting_flips_and_persists(self, set_start_at_login) -> None:
        self.assertFalse(self.controller.config.start_polling_on_launch)

        self.controller.toggle_setting(0)

        self.assertTrue(self.controller.config.start_polling_on_launch)
        reloaded = self.controller.config_store.load()
        self.assertTrue(reloaded.start_polling_on_launch)
        set_start_at_login.assert_not_called()

    @patch("pridge_client.tui.set_start_at_login")
    def test_toggling_start_at_login_calls_the_os_hook(self, set_start_at_login) -> None:
        self.controller.toggle_setting(1)

        self.assertTrue(self.controller.config.start_at_login)
        set_start_at_login.assert_called_once_with(True)

    @patch("pridge_client.tui.set_start_at_login")
    def test_toggle_setting_ignores_an_out_of_range_index(self, set_start_at_login) -> None:
        message = self.controller.toggle_setting(99)
        self.assertEqual(message, "")
        set_start_at_login.assert_not_called()
