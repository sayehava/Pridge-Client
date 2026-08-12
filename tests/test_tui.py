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


class PluginsDataTests(TuiControllerTestCase):
    def test_plugins_data_reflects_the_registry(self) -> None:
        self.printer_manager.renderer_registry.register(
            FakePlugin("builtin.pdf"), priority=10, is_builtin=True, category="Renderer"
        )
        self.printer_manager.renderer_registry.register(
            FakePlugin("third.party"), priority=20, is_builtin=False, category="Renderer", enabled=False
        )

        data = self.controller.plugins_data()

        self.assertEqual([p["plugin_id"] for p in data], ["builtin.pdf", "third.party"])
        self.assertTrue(data[0]["core"])
        self.assertFalse(data[1]["enabled"])

    def test_toggle_plugin_flips_enabled_state(self) -> None:
        self.printer_manager.renderer_registry.register(FakePlugin("builtin.pdf"), priority=10)

        self.controller.toggle_plugin(0)

        self.assertFalse(self.printer_manager.renderer_registry.get_entry("builtin.pdf").enabled)


class ServersDataTests(TuiControllerTestCase):
    def test_servers_data_shows_stopped_when_no_worker_is_running(self) -> None:
        self.controller.config.servers = [ServerConfig(id="office", name="Office", server_url="https://example.test")]

        data = self.controller.servers_data()

        self.assertEqual(data[0]["status"], "Stopped")
        self.assertEqual(data[0]["heartbeat"], "—")

    def test_servers_data_counts_distinct_mapped_printers(self) -> None:
        server = ServerConfig(
            id="office",
            name="Office",
            default_printer="Front Desk",
            printer_mappings=[
                PrinterMapping(remote_printer_id="1", local_printer_name="Kitchen"),
                PrinterMapping(remote_printer_id="2", local_printer_name="Kitchen"),
            ],
        )
        self.controller.config.servers = [server]

        data = self.controller.servers_data()

        self.assertEqual(data[0]["printers"], 2)  # Front Desk + Kitchen, deduped

    @patch("pridge_client.tui.PollingWorker")
    def test_toggle_server_starts_a_stopped_server_and_stops_a_running_one(self, worker_cls) -> None:
        server = ServerConfig(id="office", name="Office", server_url="https://example.test")
        self.controller.config.servers = [server]
        worker = Mock()
        worker.state.running = False
        worker_cls.return_value = worker

        self.controller.toggle_server(0)
        worker.start.assert_called_once()

        worker.state.running = True
        self.controller.toggle_server(0)
        worker.stop.assert_called_once()


class PrintersDataTests(TuiControllerTestCase):
    def test_printers_data_reports_raw_vs_system_driver_and_stats(self) -> None:
        self.printer_manager._printers = [Printer(name="Receipt Printer")]
        self.controller.config.printer_profiles = {"Receipt Printer": PrinterProfile(mode="raw")}
        self.controller.config.printer_stats = {"Receipt Printer": {"remote": {"success": 3, "failed": 1}}}

        data = self.controller.printers_data()

        self.assertEqual(data[0]["mode"], "RAW")
        self.assertTrue(data[0]["used"])
        self.assertEqual(data[0]["success_count"], 3)
        self.assertEqual(data[0]["failed_count"], 1)

    def test_printers_data_defaults_to_system_driver_with_no_profile(self) -> None:
        self.printer_manager._printers = [Printer(name="Office Printer")]

        data = self.controller.printers_data()

        self.assertEqual(data[0]["mode"], "System Driver")
        self.assertFalse(data[0]["used"])
        self.assertEqual(data[0]["success_count"], 0)

    def test_printers_data_degrades_to_empty_when_the_os_print_service_is_unreachable(self) -> None:
        self.printer_manager.list_printers = Mock(side_effect=PrinterError("no print service"))

        self.assertEqual(self.controller.printers_data(), [])
        self.assertEqual(self.controller.dashboard_data()["printer_count"], 0)
