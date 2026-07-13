# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from printbridge_endpoint.api import RemotePrinter
from printbridge_endpoint.config import ConfigStore
from printbridge_endpoint.gui import EndpointApi, _window_effects


class MemoryTokenStore:
    def __init__(self):
        self.tokens = {}

    def get(self, server_id="default"):
        return self.tokens.get(server_id, "")

    def set(self, token, server_id="default"):
        self.tokens[server_id] = token

    def clear(self, server_id="default"):
        self.tokens.pop(server_id, None)


class NoPrinters:
    def list_printers(self):
        return []


class FakeWindowEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def emit(self, window):
        for handler in self.handlers:
            handler(window)


class FakeWindow:
    def __init__(self):
        self.events = Mock()
        self.events.closed = FakeWindowEvent()
        self.events.shown = FakeWindowEvent()
        self.events.minimized = FakeWindowEvent()
        self.show = Mock()
        self.destroy = Mock()
        self.restore = Mock()
        self.native = None


class EndpointApiTests(unittest.TestCase):
    def setUp(self):
        self.previous_handlers = list(logging.getLogger().handlers)
        self.temporary_directory = tempfile.TemporaryDirectory()
        config_path = Path(self.temporary_directory.name) / "config.json"
        self.api = EndpointApi(
            config_store=ConfigStore(config_path),
            token_store=MemoryTokenStore(),
            printer_manager=NoPrinters(),
        )

    def tearDown(self):
        logging.getLogger().handlers = self.previous_handlers
        self.temporary_directory.cleanup()

    @patch("printbridge_endpoint.gui.PrintBridgeClient")
    def test_adds_multiple_server_profiles(self, _client_class):
        first = self.api.add_server(
            {"name": "Office", "server_url": "https://office.example.test", "token": "office-token"}
        )
        second = self.api.add_server(
            {"name": "Warehouse", "server_url": "https://warehouse.example.test", "token": "warehouse-token"}
        )

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual([server["name"] for server in second["state"]["servers"]], ["Office", "Warehouse"])

    def test_stores_per_server_mapping_and_timing(self):
        result = self.api.add_server(
            {
                "name": "Office",
                "server_url": "https://office.example.test",
                "polling_interval_seconds": 9,
                "heartbeat_interval_seconds": 41,
                "default_printer": "Backup Printer",
                "printer_mappings": [
                    {
                        "remote_printer_id": "12",
                        "remote_printer_name": "Receipts",
                        "local_printer_name": "EPSON TM-T88",
                    }
                ],
            }
        )

        server = result["state"]["servers"][0]
        self.assertEqual(server["polling_interval_seconds"], 9)
        self.assertEqual(server["heartbeat_interval_seconds"], 41)
        self.assertEqual(server["default_printer"], "Backup Printer")
        self.assertEqual(server["printer_mappings"][0]["local_printer_name"], "EPSON TM-T88")

    def test_starts_and_stops_one_server(self):
        result = self.api.add_server({"name": "Office", "server_url": "https://office.example.test"})
        server_id = result["state"]["servers"][0]["id"]

        with patch.object(self.api, "start_worker") as start_worker:
            self.api.start_server(server_id)
        with patch.object(self.api, "stop_worker") as stop_worker:
            self.api.stop_server(server_id)

        start_worker.assert_called_once_with(self.api.config.servers[0])
        stop_worker.assert_called_once_with(server_id)

    def test_disabling_running_server_stops_without_restart(self):
        result = self.api.add_server({"name": "Office", "server_url": "https://office.example.test"})
        server_id = result["state"]["servers"][0]["id"]
        self.api.workers[server_id] = Mock(state=Mock(running=True))

        with patch.object(self.api, "stop_worker") as stop_worker, patch.object(self.api, "start_worker") as start_worker:
            self.api.update_server(
                server_id,
                {"name": "Office", "server_url": "https://office.example.test", "enabled": False},
            )

        stop_worker.assert_called_once_with(server_id)
        start_worker.assert_not_called()

    @patch("printbridge_endpoint.gui.PrintBridgeClient")
    def test_discovers_remote_printers_for_mapping(self, client_class):
        client_class.return_value.list_remote_printers.return_value = [RemotePrinter("12", "Receipts")]

        result = self.api.discover_remote_printers(
            "",
            {"server_url": "https://office.example.test", "token": "client-token"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["remote_printers"],
            [
                {
                    "remote_printer_id": "12",
                    "remote_printer_name": "Receipts",
                    "enabled": True,
                    "assigned": False,
                }
            ],
        )

    @patch("printbridge_endpoint.gui.PrintBridgeClient")
    def test_syncs_selected_endpoints_when_updating_server(self, client_class):
        created = self.api.add_server({"name": "Office", "server_url": "https://office.example.test"})
        server_id = created["state"]["servers"][0]["id"]
        self.api.token_store.set("client-token", server_id)

        result = self.api.update_server(
            server_id,
            {
                "name": "Office",
                "server_url": "https://office.example.test",
                "printer_mappings": [
                    {
                        "remote_printer_id": "12",
                        "remote_printer_name": "Receipts",
                        "local_printer_name": "Office Printer",
                    },
                    {
                        "remote_printer_id": "20",
                        "remote_printer_name": "Labels",
                        "local_printer_name": "",
                    },
                ],
            },
        )

        self.assertTrue(result["ok"])
        client_class.return_value.sync_remote_printers.assert_called_once_with(["12"])

    @patch("printbridge_endpoint.gui.webview.create_window")
    def test_opens_add_server_in_separate_window(self, create_window):
        create_window.return_value = Mock()

        result = self.api.open_server_window()

        self.assertTrue(result["ok"])
        self.assertEqual(create_window.call_args.args[0], "Add Server")
        self.assertIn("server.html?", create_window.call_args.kwargs["url"])
        self.assertEqual(len(self.api.server_windows), 1)

    @patch("printbridge_endpoint.gui.webview.create_window")
    def test_opens_settings_in_one_separate_window(self, create_window):
        create_window.return_value = FakeWindow()

        first = self.api.open_settings_window()
        second = self.api.open_settings_window()

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        create_window.assert_called_once()
        self.assertIn("settings.html", create_window.call_args.kwargs["url"])
        self.assertFalse(create_window.call_args.kwargs["resizable"])
        create_window.return_value.show.assert_called_once()

    @patch("printbridge_endpoint.gui.webview.create_window")
    def test_reopens_settings_after_native_window_close(self, create_window):
        first_window = FakeWindow()
        second_window = FakeWindow()
        create_window.side_effect = [first_window, second_window]

        self.api.open_settings_window()
        first_window.events.closed.emit(first_window)
        reopened = self.api.open_settings_window()

        self.assertTrue(reopened["ok"])
        self.assertEqual(create_window.call_count, 2)
        self.assertIs(self.api.utility_windows["settings"], second_window)

    @patch("printbridge_endpoint.gui.webview.create_window")
    def test_opens_about_window_at_fixed_size(self, create_window):
        create_window.return_value = FakeWindow()

        result = self.api.open_about_window()

        self.assertTrue(result["ok"])
        self.assertIn("about.html", create_window.call_args.kwargs["url"])
        self.assertFalse(create_window.call_args.kwargs["resizable"])
        create_window.return_value.events.minimized.emit(create_window.return_value)
        create_window.return_value.restore.assert_called_once()

    def test_quit_closes_every_window_and_allows_main_window_close(self):
        main_window = Mock()
        server_window = Mock()
        utility_window = Mock()
        self.api.window = main_window
        self.api.server_windows["server"] = server_window
        self.api.utility_windows["settings"] = utility_window

        result = self.api.quit_application()

        self.assertTrue(result["ok"])
        self.assertTrue(self.api.on_closing())
        server_window.destroy.assert_called_once()
        utility_window.destroy.assert_called_once()
        main_window.destroy.assert_called_once()

    @patch("printbridge_endpoint.gui.set_start_at_login")
    def test_updates_application_darkness_setting(self, set_start_at_login):
        self.api.window = Mock()
        server_window = Mock()
        about_window = Mock()
        settings_window = Mock()
        self.api.server_windows["server"] = server_window
        self.api.utility_windows.update({"about": about_window, "settings": settings_window})

        result = self.api.update_application_settings(
            {
                "start_polling_on_launch": True,
                "start_at_login": True,
                "darkness_grade": "Obsidian",
            }
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["restart_required"])
        self.assertEqual(result["state"]["appearance"]["darkness_grade"], "Obsidian")
        self.assertEqual(self.api.config.appearance.darkness_grade, "Obsidian")
        expected_script = 'document.documentElement.dataset.darkness = "obsidian";'
        self.api.window.evaluate_js.assert_called_once_with(expected_script)
        server_window.evaluate_js.assert_called_once_with(expected_script)
        about_window.evaluate_js.assert_called_once_with(expected_script)
        settings_window.evaluate_js.assert_not_called()
        set_start_at_login.assert_called_once_with(True)

    def test_native_transparency_is_always_disabled(self):
        self.assertEqual(_window_effects(), {"transparent": False, "vibrancy": False})


if __name__ == "__main__":
    unittest.main()
