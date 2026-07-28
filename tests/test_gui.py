# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pridge_client.api import RemotePrinter
from pridge_client.config import ConfigStore
from pridge_client.gui import APP_ICON_PATH, ClientApi, _shutdown_smoke_test, _webview_start_icon, _window_effects
from pridge_client.models import JobHistoryEntry
from pridge_client.printers import DriverChoice, DriverOption, Printer, PrinterCapabilities, PrinterError


def _restore_root_handlers(previous_handlers):
    root = logging.getLogger()
    for handler in root.handlers:
        if handler not in previous_handlers:
            handler.close()
    root.handlers = previous_handlers


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
    def __init__(self):
        from tempfile import TemporaryDirectory

        from pridge_client.receipt_composer import ReceiptComposerStore
        from pridge_client.renderers.registry import RendererRegistry

        self.renderer_registry = RendererRegistry()
        self._receipt_composer_scratch = TemporaryDirectory()
        self.receipt_composer_store = ReceiptComposerStore(Path(self._receipt_composer_scratch.name))

    def list_printers(self):
        return []


class FakeRendererPlugin:
    def __init__(self, plugin_id, settings_window=""):
        self.plugin_id = plugin_id
        self.display_name = plugin_id
        self.version = "1.0.0"
        self.api_version = 1
        self.supported_mime_types = frozenset()
        self.supported_extensions = frozenset()
        if settings_window:
            self.settings_window = settings_window

    def can_render(self, *, mime_type, filename, data):
        return False

    def render_to_pdf(self, *, data, mime_type, filename, options):
        raise NotImplementedError


class FakePluginPrinterManager(NoPrinters):
    def __init__(self):
        from pridge_client.renderers.registry import RendererRegistry

        self.renderer_registry = RendererRegistry()
        self.renderer_registry.register(FakeRendererPlugin("builtin.one"), priority=10, is_builtin=True)
        self.app_mapping_plugin = FakeRendererPlugin("app-mapping.none")

    def install_renderer_plugin(self, source):
        from pathlib import Path as _Path

        plugin_id = f"third_party.{_Path(source).name}"
        self.renderer_registry.register(
            FakeRendererPlugin(plugin_id), priority=200, is_builtin=False, source_path=str(source)
        )
        return plugin_id

    def remove_renderer_plugin(self, plugin_id):
        from pridge_client.plugins import PluginInstallError

        if not self.renderer_registry.remove(plugin_id):
            raise PluginInstallError(f"Plugin '{plugin_id}' is not installed.")

    def rescan_renderer_plugins(self):
        pass


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


class ClientApiTests(unittest.TestCase):
    def setUp(self):
        self.previous_handlers = list(logging.getLogger().handlers)
        self.temporary_directory = tempfile.TemporaryDirectory()
        config_path = Path(self.temporary_directory.name) / "config.json"
        self.api = ClientApi(
            config_store=ConfigStore(config_path),
            token_store=MemoryTokenStore(),
            printer_manager=NoPrinters(),
        )

    def tearDown(self):
        _restore_root_handlers(self.previous_handlers)
        self.temporary_directory.cleanup()

    @patch("pridge_client.gui.PridgeClient")
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
        self.assertIsNone(server["last_heartbeat_at"])
        self.assertEqual(server["last_error"], "")

    def test_saves_validated_system_driver_profile(self):
        manager = Mock()
        manager.renderer_registry.all_entries.return_value = []
        manager.list_printers.return_value = [Printer("Office Driver", system_driver_available=True)]
        capabilities = PrinterCapabilities(
            printer_name="Office Driver",
            system_driver_available=True,
            options=(
                DriverOption(
                    id="PageSize",
                    label="Media Size",
                    choices=(DriverChoice("A4", "A4"), DriverChoice("Letter", "Letter")),
                    default="A4",
                ),
            ),
        )
        manager.get_capabilities.return_value = capabilities
        self.api.printer_manager = manager
        self.api.refresh_printers()

        result = self.api.update_printer_profile(
            "Office Driver",
            {"mode": "system_driver", "driver_settings": {"PageSize": "Removed"}},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["profile"],
            {
                "mode": "system_driver",
                "driver_settings": {"PageSize": "A4"},
                "submission_method": "",
                "fit_mode": "fit",
                "raw_header_template": "",
                "raw_footer_template": "",
                "raw_paper_width_dots": 384,
                "raw_chars_per_line": 32,
            },
        )
        self.assertEqual(self.api.config_store.load().printer_profiles["Office Driver"].mode, "system_driver")

    def test_saves_a_valid_submission_method(self):
        manager = Mock()
        manager.renderer_registry.all_entries.return_value = []
        manager.list_printers.return_value = [Printer("Office Driver", system_driver_available=True)]
        manager.get_capabilities.return_value = PrinterCapabilities(
            printer_name="Office Driver", system_driver_available=True
        )
        self.api.printer_manager = manager
        self.api.refresh_printers()

        result = self.api.update_printer_profile(
            "Office Driver", {"mode": "system_driver", "submission_method": "direct_pdf"}
        )

        self.assertEqual(result["profile"]["submission_method"], "direct_pdf")
        self.assertEqual(
            self.api.config_store.load().printer_profiles["Office Driver"].submission_method, "direct_pdf"
        )

    def test_saves_raw_header_and_footer_templates(self):
        manager = Mock()
        manager.renderer_registry.all_entries.return_value = []
        manager.list_printers.return_value = [Printer("Receipt", system_driver_available=True)]
        self.api.printer_manager = manager
        self.api.refresh_printers()

        result = self.api.update_printer_profile(
            "Receipt",
            {
                "mode": "raw",
                "raw_header_template": "[feed:4]",
                "raw_footer_template": "[hex:1D 56 00]",
                "raw_paper_width_dots": 576,
                "raw_chars_per_line": 48,
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["profile"]["raw_header_template"], "[feed:4]")
        self.assertEqual(result["profile"]["raw_footer_template"], "[hex:1D 56 00]")
        self.assertEqual(result["profile"]["raw_paper_width_dots"], 576)
        self.assertEqual(result["profile"]["raw_chars_per_line"], 48)
        saved = self.api.config_store.load().printer_profiles["Receipt"]
        self.assertEqual(saved.raw_header_template, "[feed:4]")
        self.assertEqual(saved.raw_footer_template, "[hex:1D 56 00]")

    def test_falls_back_to_the_existing_raw_paper_width_when_invalid(self):
        manager = Mock()
        manager.renderer_registry.all_entries.return_value = []
        manager.list_printers.return_value = [Printer("Receipt", system_driver_available=True)]
        self.api.printer_manager = manager
        self.api.refresh_printers()
        self.api.update_printer_profile("Receipt", {"mode": "raw", "raw_paper_width_dots": 576})

        result = self.api.update_printer_profile("Receipt", {"mode": "raw", "raw_paper_width_dots": "not-a-number"})

        self.assertEqual(result["profile"]["raw_paper_width_dots"], 576)

    def test_falls_back_to_the_existing_submission_method_when_invalid(self):
        manager = Mock()
        manager.renderer_registry.all_entries.return_value = []
        manager.list_printers.return_value = [Printer("Office Driver", system_driver_available=True)]
        manager.get_capabilities.return_value = PrinterCapabilities(
            printer_name="Office Driver", system_driver_available=True
        )
        self.api.printer_manager = manager
        self.api.refresh_printers()
        self.api.update_printer_profile("Office Driver", {"mode": "system_driver", "submission_method": "pdfium"})

        result = self.api.update_printer_profile(
            "Office Driver", {"mode": "system_driver", "submission_method": "not-a-real-method"}
        )

        self.assertEqual(result["profile"]["submission_method"], "pdfium")

    @patch("pridge_client.gui.PridgeClient")
    def test_server_id_targets_that_servers_own_profile_override(self, _client_class):
        manager = Mock()
        manager.renderer_registry.all_entries.return_value = []
        manager.list_printers.return_value = [Printer("Office Driver", system_driver_available=True)]
        manager.get_capabilities.return_value = PrinterCapabilities(
            printer_name="Office Driver", system_driver_available=True
        )
        self.api.printer_manager = manager
        self.api.refresh_printers()
        add_result = self.api.add_server({"name": "Office", "server_url": "https://office.example.test"})
        server_id = add_result["state"]["servers"][0]["id"]

        result = self.api.update_printer_profile(
            "Office Driver", {"mode": "system_driver", "submission_method": "pdfium"}, server_id
        )

        self.assertEqual(result["profile"]["submission_method"], "pdfium")
        saved = self.api.config_store.load()
        self.assertEqual(
            saved.servers[0].printer_profiles["Office Driver"].submission_method, "pdfium"
        )
        self.assertNotIn("Office Driver", saved.printer_profiles)

    def test_exposes_driver_capabilities_with_saved_profile(self):
        manager = Mock()
        manager.renderer_registry.all_entries.return_value = []
        manager.list_printers.return_value = [Printer("Office Driver", system_driver_available=True)]
        capabilities = PrinterCapabilities(
            printer_name="Office Driver",
            system_driver_available=True,
            driver_name="Office Driver 2",
            supports_native_dialog=True,
        )
        manager.get_capabilities.return_value = capabilities
        self.api.printer_manager = manager
        self.api.refresh_printers()

        result = self.api.get_printer_capabilities("Office Driver")

        self.assertTrue(result["ok"])
        self.assertEqual(result["capabilities"]["driver_name"], "Office Driver 2")
        self.assertTrue(result["capabilities"]["supports_native_dialog"])

    def test_opens_native_driver_settings(self):
        manager = Mock()
        manager.renderer_registry.all_entries.return_value = []
        manager.list_printers.return_value = [Printer("Office Driver", system_driver_available=True)]
        manager.get_capabilities.return_value = PrinterCapabilities(
            printer_name="Office Driver",
            system_driver_available=True,
            supports_native_dialog=True,
        )
        self.api.printer_manager = manager
        self.api.refresh_printers()

        result = self.api.open_printer_driver_settings("Office Driver")

        self.assertTrue(result["ok"])
        manager.open_driver_settings.assert_called_once_with("Office Driver")

    def test_submits_test_page_using_saved_driver_profile(self):
        manager = Mock()
        manager.renderer_registry.all_entries.return_value = []
        manager.list_printers.return_value = [Printer("Office Driver", system_driver_available=True)]
        self.api.printer_manager = manager
        self.api.refresh_printers()

        result = self.api.test_printer("Office Driver")

        self.assertTrue(result["ok"])
        manager.print_test_page.assert_called_once_with(
            "Office Driver",
            mode="system_driver",
            driver_settings={},
            submission_method=None,
            fit_mode="fit",
            raw_header_template="",
            raw_footer_template="",
            raw_paper_width_dots=384,
            raw_chars_per_line=32,
        )

    def test_successful_test_print_increments_the_printer_test_success_count(self):
        manager = Mock()
        manager.renderer_registry.all_entries.return_value = []
        manager.list_printers.return_value = [Printer("Office Driver", system_driver_available=True)]
        self.api.printer_manager = manager
        self.api.refresh_printers()

        self.api.test_printer("Office Driver")
        state = self.api._build_state()

        details = next(p for p in state["printer_details"] if p["name"] == "Office Driver")
        self.assertEqual(details["test_success_count"], 1)
        self.assertEqual(details["test_failed_count"], 0)
        self.assertEqual(details["remote_success_count"], 0)
        self.assertEqual(details["remote_failed_count"], 0)

    def test_failed_test_print_increments_the_printer_test_failed_count(self):
        manager = Mock()
        manager.renderer_registry.all_entries.return_value = []
        manager.list_printers.return_value = [Printer("Office Driver", system_driver_available=True)]
        manager.print_test_page.side_effect = PrinterError("out of paper")
        self.api.printer_manager = manager
        self.api.refresh_printers()

        self.api.test_printer("Office Driver")
        state = self.api._build_state()

        details = next(p for p in state["printer_details"] if p["name"] == "Office Driver")
        self.assertEqual(details["test_success_count"], 0)
        self.assertEqual(details["test_failed_count"], 1)
        self.assertEqual(details["remote_success_count"], 0)
        self.assertEqual(details["remote_failed_count"], 0)

    def test_a_remote_job_event_increments_the_printer_remote_counts_not_test_counts(self):
        manager = Mock()
        manager.renderer_registry.all_entries.return_value = []
        manager.list_printers.return_value = [Printer("Office Driver", system_driver_available=True)]
        self.api.printer_manager = manager
        self.api.refresh_printers()

        self.api.events.put(("job", ("Office", JobHistoryEntry(job_id="1", status="printed", printer_name="Office Driver"))))
        self.api.events.put(("job", ("Office", JobHistoryEntry(job_id="2", status="failed", printer_name="Office Driver"))))
        state = self.api._build_state()

        details = next(p for p in state["printer_details"] if p["name"] == "Office Driver")
        self.assertEqual(details["remote_success_count"], 1)
        self.assertEqual(details["remote_failed_count"], 1)
        self.assertEqual(details["test_success_count"], 0)
        self.assertEqual(details["test_failed_count"], 0)

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

    @patch("pridge_client.gui.PridgeClient")
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

    @patch("pridge_client.gui.PridgeClient")
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

    @patch("pridge_client.gui.webview.create_window")
    def test_opens_add_server_in_separate_window(self, create_window):
        create_window.return_value = Mock()

        result = self.api.open_server_window()

        self.assertTrue(result["ok"])
        self.assertEqual(create_window.call_args.args[0], "Add Server")
        self.assertIn("server.html?", create_window.call_args.kwargs["url"])
        self.assertEqual(len(self.api._server_windows), 1)

    @patch("pridge_client.gui.webview.create_window")
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

    @patch("pridge_client.gui.webview.create_window")
    def test_reopens_settings_after_native_window_close(self, create_window):
        first_window = FakeWindow()
        second_window = FakeWindow()
        create_window.side_effect = [first_window, second_window]

        self.api.open_settings_window()
        first_window.events.closed.emit(first_window)
        reopened = self.api.open_settings_window()

        self.assertTrue(reopened["ok"])
        self.assertEqual(create_window.call_count, 2)
        self.assertIs(self.api._utility_windows["settings"], second_window)

    @patch("pridge_client.gui.webview.create_window")
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
        self.api._window = main_window
        self.api._server_windows["server"] = server_window
        self.api._utility_windows["settings"] = utility_window

        result = self.api.quit_application()

        self.assertTrue(result["ok"])
        self.assertTrue(self.api.on_closing())
        server_window.destroy.assert_called_once()
        utility_window.destroy.assert_called_once()
        main_window.destroy.assert_called_once()

    def test_exposes_build_diagnostics(self):
        state = self.api.get_state()["state"]

        self.assertIn(state["build_variant"], {"Development", "Native", "PyInstaller"})
        self.assertIn(state["build_system"], {"Python", "Nuitka", "PyInstaller"})

    def test_gui_ready_notification_does_not_drive_smoke_test_shutdown(self):
        # Smoke-test shutdown is now driven deterministically from Python via
        # webview.start's `func` callback, not from the JS-triggered
        # notify_gui_ready round trip, so this call must be a no-op beyond
        # marking readiness.
        api = ClientApi(
            config_store=self.api.config_store,
            token_store=self.api.token_store,
            printer_manager=self.api.printer_manager,
            gui_smoke_test=True,
        )
        api._window = Mock()

        result = api.notify_gui_ready()

        self.assertTrue(result["ok"])
        self.assertTrue(api.gui_ready.is_set())
        api._window.destroy.assert_not_called()

    def test_smoke_test_printer_refresh_is_bounded_and_warning_only(self):
        manager = Mock()
        manager.list_printers.side_effect = RuntimeError("no print service")

        api = ClientApi(
            config_store=self.api.config_store,
            token_store=self.api.token_store,
            printer_manager=manager,
            gui_smoke_test=True,
        )

        self.assertEqual(api.printers, [])

    @patch("pridge_client.gui.logger.info")
    def test_gui_ready_notification_is_handled_once(self, info):
        first = self.api.notify_gui_ready()
        second = self.api.notify_gui_ready()

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertTrue(self.api.gui_ready.is_set())
        info.assert_called_once_with("Desktop interface became ready")

    @patch("pridge_client.gui.set_start_at_login")
    def test_updates_application_darkness_setting(self, set_start_at_login):
        self.api._window = Mock()
        server_window = Mock()
        about_window = Mock()
        settings_window = Mock()
        self.api._server_windows["server"] = server_window
        self.api._utility_windows.update({"about": about_window, "settings": settings_window})

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
        self.api._window.evaluate_js.assert_called_once_with(expected_script)
        server_window.evaluate_js.assert_called_once_with(expected_script)
        about_window.evaluate_js.assert_called_once_with(expected_script)
        settings_window.evaluate_js.assert_not_called()
        set_start_at_login.assert_called_once_with(True)

    def test_exports_the_current_run_log_to_a_chosen_destination(self):
        log_dir = Path(self.temporary_directory.name) / "logs"
        log_dir.mkdir()
        (log_dir / "client.log").write_text("2026-07-21 10:00:00 hello world\n", encoding="utf-8")
        destination = Path(self.temporary_directory.name) / "exported.log"
        window = Mock()
        window.create_file_dialog.return_value = (str(destination),)
        self.api._window = window
        self.api.config.logging.directory = str(log_dir)

        result = self.api.export_log()

        self.assertTrue(result["ok"])
        self.assertEqual(destination.read_text(encoding="utf-8"), "2026-07-21 10:00:00 hello world\n")

    def test_export_log_prefers_the_open_settings_window_for_the_dialog(self):
        log_dir = Path(self.temporary_directory.name) / "logs"
        log_dir.mkdir()
        (log_dir / "client.log").write_text("2026-07-21 10:00:00 data\n", encoding="utf-8")
        destination = Path(self.temporary_directory.name) / "exported.log"
        main_window = Mock()
        settings_window = Mock()
        settings_window.create_file_dialog.return_value = (str(destination),)
        self.api._window = main_window
        self.api._utility_windows["settings"] = settings_window
        self.api.config.logging.directory = str(log_dir)

        self.api.export_log()

        settings_window.create_file_dialog.assert_called_once()
        main_window.create_file_dialog.assert_not_called()

    def test_export_log_reports_an_error_when_no_log_file_exists_yet(self):
        log_dir = Path(self.temporary_directory.name) / "empty-logs"
        log_dir.mkdir()
        self.api._window = Mock()
        self.api.config.logging.directory = str(log_dir)

        result = self.api.export_log()

        self.assertFalse(result["ok"])

    def test_export_log_leaves_state_unchanged_when_dialog_is_cancelled(self):
        log_dir = Path(self.temporary_directory.name) / "logs"
        log_dir.mkdir()
        (log_dir / "client.log").write_text("2026-07-21 10:00:00 data\n", encoding="utf-8")
        window = Mock()
        window.create_file_dialog.return_value = None
        self.api._window = window
        self.api.config.logging.directory = str(log_dir)

        result = self.api.export_log()

        self.assertTrue(result["ok"])

    def test_export_log_filters_by_date_range(self):
        log_dir = Path(self.temporary_directory.name) / "logs"
        log_dir.mkdir()
        (log_dir / "client.log.2026-07-01").write_text("2026-07-01 09:00:00 old entry\n", encoding="utf-8")
        (log_dir / "client.log").write_text("2026-07-21 10:00:00 recent entry\n", encoding="utf-8")
        destination = Path(self.temporary_directory.name) / "exported.log"
        window = Mock()
        window.create_file_dialog.return_value = (str(destination),)
        self.api._window = window
        self.api.config.logging.directory = str(log_dir)

        result = self.api.export_log(start_date="2026-07-15", end_date="2026-07-25")

        self.assertTrue(result["ok"])
        exported = destination.read_text(encoding="utf-8")
        self.assertNotIn("old entry", exported)
        self.assertIn("recent entry", exported)

    def test_export_log_reports_an_error_when_range_matches_nothing(self):
        log_dir = Path(self.temporary_directory.name) / "logs"
        log_dir.mkdir()
        (log_dir / "client.log").write_text("2026-07-21 10:00:00 recent entry\n", encoding="utf-8")
        destination = Path(self.temporary_directory.name) / "exported.log"
        window = Mock()
        window.create_file_dialog.return_value = (str(destination),)
        self.api._window = window
        self.api.config.logging.directory = str(log_dir)

        result = self.api.export_log(start_date="2020-01-01", end_date="2020-01-02")

        self.assertFalse(result["ok"])
        self.assertFalse(destination.exists())

    def test_clear_logs_reports_an_error_when_file_logging_is_disabled(self):
        result = self.api.clear_logs()

        self.assertFalse(result["ok"])

    def test_choose_log_directory_returns_the_selected_path(self):
        chosen = Path(self.temporary_directory.name) / "chosen-logs"
        window = Mock()
        window.create_file_dialog.return_value = (str(chosen),)
        self.api._window = window

        result = self.api.choose_log_directory()

        self.assertTrue(result["ok"])
        self.assertEqual(result["directory"], str(chosen))

    def test_choose_log_directory_leaves_state_unchanged_when_dialog_is_cancelled(self):
        window = Mock()
        window.create_file_dialog.return_value = None
        self.api._window = window

        result = self.api.choose_log_directory()

        self.assertTrue(result["ok"])

    def test_update_application_settings_reconfigures_file_logging(self):
        log_dir = Path(self.temporary_directory.name) / "chosen-logs"

        result = self.api.update_application_settings(
            {"log_file_enabled": True, "log_retention_days": 7, "log_directory": str(log_dir)}
        )

        self.assertTrue(result["ok"])
        self.assertEqual(self.api.config.logging.retention_days, 7)
        self.assertEqual(self.api.config.logging.directory, str(log_dir))
        self.assertEqual(result["state"]["logging"]["retention_days"], 7)
        logging.getLogger("pridge.test").warning("after settings change")
        self.assertTrue((log_dir / "client.log").is_file())

    @patch("pridge_client.gui.webview.create_window")
    def test_opens_plugins_window_at_fixed_size(self, create_window):
        create_window.return_value = FakeWindow()

        result = self.api.open_plugins_window()

        self.assertTrue(result["ok"])
        self.assertIn("plugins.html", create_window.call_args.kwargs["url"])

    @patch("pridge_client.gui.webview.create_window")
    def test_opens_servers_window_at_fixed_size(self, create_window):
        create_window.return_value = FakeWindow()

        result = self.api.open_servers_window()

        self.assertTrue(result["ok"])
        self.assertIn("servers.html", create_window.call_args.kwargs["url"])

    @patch("pridge_client.gui.webview.create_window")
    def test_opens_printers_window_at_fixed_size(self, create_window):
        create_window.return_value = FakeWindow()

        result = self.api.open_printers_window()

        self.assertTrue(result["ok"])
        self.assertIn("printers.html", create_window.call_args.kwargs["url"])

    def test_install_plugin_registers_the_selected_folder(self):
        self.api.printer_manager = FakePluginPrinterManager()
        window = Mock()
        window.create_file_dialog.return_value = (str(Path(self.temporary_directory.name) / "my-plugin"),)
        self.api._window = window

        result = self.api.install_plugin()

        self.assertTrue(result["ok"])
        plugin_ids = [plugin["plugin_id"] for plugin in result["plugins"]]
        self.assertIn("third_party.my-plugin", plugin_ids)

    def test_install_plugin_leaves_state_unchanged_when_dialog_is_cancelled(self):
        self.api.printer_manager = FakePluginPrinterManager()
        window = Mock()
        window.create_file_dialog.return_value = None
        self.api._window = window

        result = self.api.install_plugin()

        self.assertTrue(result["ok"])
        self.assertEqual([p["plugin_id"] for p in result["plugins"]], ["builtin.one"])

    def test_get_renderer_plugins_reports_each_entry_s_category(self):
        manager = FakePluginPrinterManager()
        manager.renderer_registry.register(
            FakeRendererPlugin("mapper.one"), priority=100, is_builtin=True, category="Mapper"
        )
        self.api.printer_manager = manager

        result = self.api.get_renderer_plugins()

        by_id = {plugin["plugin_id"]: plugin["category"] for plugin in result["plugins"]}
        self.assertEqual(by_id["mapper.one"], "Mapper")

    def test_get_renderer_plugins_reports_has_settings_generically(self):
        manager = FakePluginPrinterManager()
        manager.renderer_registry.register(
            FakeRendererPlugin("with.settings", settings_window="app_mapping"),
            priority=100,
            is_builtin=True,
        )
        self.api.printer_manager = manager

        result = self.api.get_renderer_plugins()

        by_id = {plugin["plugin_id"]: plugin for plugin in result["plugins"]}
        self.assertTrue(by_id["with.settings"]["has_settings"])
        self.assertEqual(by_id["with.settings"]["settings_window"], "app_mapping")
        self.assertFalse(by_id["builtin.one"]["has_settings"])
        self.assertEqual(by_id["builtin.one"]["settings_window"], "")

    def test_open_plugin_settings_window_dispatches_to_the_matching_opener(self):
        with patch.object(self.api, "open_app_mapping_window", return_value={"ok": True}) as opener:
            result = self.api.open_plugin_settings_window("app_mapping")

        self.assertTrue(result["ok"])
        opener.assert_called_once()

    def test_open_plugin_settings_window_errors_for_an_unknown_key(self):
        result = self.api.open_plugin_settings_window("not-a-real-window")

        self.assertFalse(result["ok"])

    def test_remove_plugin_removes_a_third_party_plugin(self):
        manager = FakePluginPrinterManager()
        manager.install_renderer_plugin(Path(self.temporary_directory.name) / "my-plugin")
        self.api.printer_manager = manager

        result = self.api.remove_plugin("third_party.my-plugin")

        self.assertTrue(result["ok"])
        self.assertNotIn("third_party.my-plugin", [p["plugin_id"] for p in result["plugins"]])

    def test_remove_plugin_rejects_a_builtin_plugin(self):
        self.api.printer_manager = FakePluginPrinterManager()

        result = self.api.remove_plugin("builtin.one")

        self.assertFalse(result["ok"])

    def test_reorder_renderer_plugin_moves_it_to_the_target_index(self):
        manager = FakePluginPrinterManager()
        manager.renderer_registry.register(FakeRendererPlugin("builtin.two"), priority=20, is_builtin=True)
        manager.renderer_registry.register(FakeRendererPlugin("builtin.three"), priority=30, is_builtin=True)
        self.api.printer_manager = manager

        result = self.api.reorder_renderer_plugin("builtin.three", 0)

        ordered = [p["plugin_id"] for p in sorted(result["plugins"], key=lambda p: p["priority"])]
        self.assertEqual(ordered, ["builtin.three", "builtin.one", "builtin.two"])

    def test_reorder_renderer_plugin_is_scoped_to_its_category(self):
        manager = FakePluginPrinterManager()
        manager.renderer_registry.register(
            FakeRendererPlugin("r1"), priority=20, is_builtin=True, category="Renderer"
        )
        manager.renderer_registry.register(
            FakeRendererPlugin("m1"), priority=25, is_builtin=True, category="Mapper"
        )
        manager.renderer_registry.register(
            FakeRendererPlugin("r2"), priority=30, is_builtin=True, category="Renderer"
        )
        self.api.printer_manager = manager

        result = self.api.reorder_renderer_plugin("r2", 0, category="Renderer")

        ordered = [p["plugin_id"] for p in sorted(result["plugins"], key=lambda p: p["priority"])]
        self.assertEqual(ordered, ["builtin.one", "r2", "m1", "r1"])

    def test_reorder_renderer_plugin_with_an_unknown_id_is_a_no_op(self):
        manager = FakePluginPrinterManager()
        self.api.printer_manager = manager

        result = self.api.reorder_renderer_plugin("no-such-plugin", 0)

        self.assertEqual([p["plugin_id"] for p in result["plugins"]], ["builtin.one"])

    def test_native_transparency_is_always_disabled(self):
        self.assertEqual(_window_effects(), {"transparent": False, "vibrancy": False})

    @patch("pridge_client.gui.platform.system", return_value="Windows")
    def test_webview_start_icon_is_skipped_on_windows(self, _system):
        # pywebview's winforms backend builds a raw System.Drawing.Icon from
        # this path, which requires an actual .ico file; passing the
        # bundled PNG there crashes with an unhandled CLR exception.
        self.assertIsNone(_webview_start_icon())

    @patch("pridge_client.gui.platform.system", return_value="Darwin")
    def test_webview_start_icon_is_used_off_windows(self, _system):
        self.assertEqual(_webview_start_icon(), str(APP_ICON_PATH))

    def test_smoke_test_shutdown_stops_tray_workers_and_windows(self):
        api = Mock()
        tray = Mock()
        api._tray = tray
        worker = Mock()
        api.workers = {"srv": worker}
        server_window = Mock()
        api._server_windows = {"srv": server_window}
        utility_window = Mock()
        api._utility_windows = {"settings": utility_window}
        main_window = Mock()
        api._window = main_window

        _shutdown_smoke_test(api)

        tray.stop.assert_called_once()
        self.assertIsNone(api._tray)
        worker.stop.assert_called_once()
        worker.join.assert_called_once_with(timeout=2)
        self.assertEqual(api.workers, {})
        server_window.destroy.assert_called_once()
        self.assertEqual(api._server_windows, {})
        utility_window.destroy.assert_called_once()
        self.assertEqual(api._utility_windows, {})
        main_window.destroy.assert_called_once()


def _tiny_png_bytes() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(0, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


class ReceiptComposerApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        config_path = Path(self.temporary_directory.name) / "config.json"
        self.api = ClientApi(
            config_store=ConfigStore(config_path),
            token_store=MemoryTokenStore(),
            printer_manager=NoPrinters(),
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_open_receipt_composer_window_dispatches_through_the_generalized_opener(self):
        with patch.object(self.api, "open_receipt_composer_window", return_value={"ok": True}) as opener:
            result = self.api.open_plugin_settings_window("receipt_composer")

        self.assertTrue(result["ok"])
        opener.assert_called_once()

    def test_get_receipt_images_starts_empty(self):
        result = self.api.get_receipt_images()

        self.assertTrue(result["ok"])
        self.assertEqual(result["images"], [])

    def test_add_receipt_image_round_trips_through_get_receipt_images(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed")
        import base64

        data_base64 = base64.b64encode(_tiny_png_bytes()).decode("ascii")

        result = self.api.add_receipt_image("Logo", data_base64)

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["images"]), 1)
        image = result["images"][0]
        self.assertEqual(image["name"], "Logo")
        self.assertEqual(image["width"], 8)
        self.assertTrue(image["data_base64"])

    def test_add_receipt_image_rejects_invalid_base64(self):
        result = self.api.add_receipt_image("Logo", "not-valid-base64!!")

        self.assertFalse(result["ok"])

    def test_add_receipt_image_rejects_data_that_is_not_an_image(self):
        import base64

        result = self.api.add_receipt_image("Logo", base64.b64encode(b"not an image").decode("ascii"))

        self.assertFalse(result["ok"])

    def test_remove_receipt_image_drops_it_from_the_list(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed")
        import base64

        added = self.api.add_receipt_image("Logo", base64.b64encode(_tiny_png_bytes()).decode("ascii"))
        image_id = added["images"][0]["id"]

        result = self.api.remove_receipt_image(image_id)

        self.assertTrue(result["ok"])
        self.assertEqual(result["images"], [])

    def test_get_receipt_counters_starts_empty_for_an_unused_printer(self):
        result = self.api.get_receipt_counters("Kitchen Printer")

        self.assertTrue(result["ok"])
        self.assertEqual(result["counters"], {})

    def test_add_receipt_counter_creates_a_named_counter_at_zero(self):
        result = self.api.add_receipt_counter("Kitchen Printer", "vip", "VIP receipts")

        self.assertTrue(result["ok"])
        self.assertEqual(result["counters"]["vip"], {"value": 0, "label": "VIP receipts"})

    def test_add_receipt_counter_rejects_the_reserved_default_key(self):
        result = self.api.add_receipt_counter("Kitchen Printer", "__default__", "")

        self.assertFalse(result["ok"])

    def test_reset_receipt_counter_sets_a_new_value(self):
        self.api.add_receipt_counter("Kitchen Printer", "vip", "VIP")

        result = self.api.reset_receipt_counter("Kitchen Printer", "vip", 42)

        self.assertEqual(result["counters"]["vip"]["value"], 42)

    def test_reset_receipt_counter_clamps_negative_values_to_zero(self):
        self.api.add_receipt_counter("Kitchen Printer", "vip", "VIP")

        result = self.api.reset_receipt_counter("Kitchen Printer", "vip", -5)

        self.assertEqual(result["counters"]["vip"]["value"], 0)

    def test_remove_receipt_counter_drops_a_named_counter(self):
        self.api.add_receipt_counter("Kitchen Printer", "vip", "VIP")

        result = self.api.remove_receipt_counter("Kitchen Printer", "vip")

        self.assertTrue(result["ok"])
        self.assertNotIn("vip", result["counters"])

    def test_remove_receipt_counter_rejects_the_default_counter(self):
        result = self.api.remove_receipt_counter("Kitchen Printer", "__default__")

        self.assertFalse(result["ok"])

    def test_preview_receipt_template_does_not_increment_counters(self):
        result = self.api.preview_receipt_template("[print_number]", printer_name="Kitchen Printer")

        self.assertTrue(result["ok"])
        self.assertEqual(result["blocks"], [{"type": "text", "value": "1"}])
        self.assertEqual(self.api.get_receipt_counters("Kitchen Printer")["counters"], {})

    def test_preview_receipt_template_uses_the_printer_s_saved_chars_per_line(self):
        manager = Mock()
        manager.renderer_registry.all_entries.return_value = []
        manager.list_printers.return_value = [Printer("Kitchen Printer", system_driver_available=True)]
        manager.receipt_composer_store = self.api.printer_manager.receipt_composer_store
        self.api.printer_manager = manager
        self.api.refresh_printers()
        self.api.update_printer_profile("Kitchen Printer", {"mode": "raw", "raw_chars_per_line": 12})

        result = self.api.preview_receipt_template("[hr]", printer_name="Kitchen Printer")

        self.assertEqual(result["blocks"], [{"type": "hr", "width": 12}])


class DashboardWidgetTests(unittest.TestCase):
    def setUp(self):
        self.previous_handlers = list(logging.getLogger().handlers)
        self.temporary_directory = tempfile.TemporaryDirectory()
        config_path = Path(self.temporary_directory.name) / "config.json"
        self.api = ClientApi(
            config_store=ConfigStore(config_path),
            token_store=MemoryTokenStore(),
            printer_manager=NoPrinters(),
        )

    def tearDown(self):
        _restore_root_handlers(self.previous_handlers)
        self.temporary_directory.cleanup()

    def test_default_layout_has_recent_jobs_and_logs_on_one_page(self):
        result = self.api.get_dashboard_layout()

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["pages"]), 1)
        self.assertEqual([w["widget_type"] for w in result["pages"][0]], ["recent_jobs", "logs"])
        self.assertEqual(
            {item["type"] for item in result["catalog"]},
            {"recent_jobs", "logs", "printer_stats", "server_status"},
        )

    def test_add_widget_rejects_an_unknown_type(self):
        result = self.api.add_dashboard_widget("not-a-real-widget")

        self.assertFalse(result["ok"])

    def test_add_widget_fills_the_current_page_before_a_new_one(self):
        self.api.add_dashboard_widget("recent_jobs")
        self.api.add_dashboard_widget("recent_jobs")
        result = self.api.add_dashboard_widget("logs")

        self.assertEqual(len(result["pages"]), 2)
        self.assertEqual(len(result["pages"][0]), 4)
        self.assertEqual(len(result["pages"][1]), 1)

    def test_remove_widget_compacts_empty_pages(self):
        layout = self.api.get_dashboard_layout()
        first_id = layout["pages"][0][0]["id"]
        second_id = layout["pages"][0][1]["id"]

        self.api.remove_dashboard_widget(first_id)
        result = self.api.remove_dashboard_widget(second_id)

        self.assertEqual(result["pages"], [[]])

    def test_update_widget_config_persists_and_survives_reorder(self):
        added = self.api.add_dashboard_widget("server_status")
        widget_id = added["pages"][-1][-1]["id"]

        result = self.api.update_dashboard_widget_config(
            widget_id, {"server_ids": ["srv-1"], "auto_rotate": True}
        )
        widget = next(w for page in result["pages"] for w in page if w["id"] == widget_id)
        self.assertEqual(widget["config"], {"server_ids": ["srv-1"], "auto_rotate": True})

        reordered = self.api.reorder_dashboard_widget(widget_id, 0, 0)
        widget = next(w for page in reordered["pages"] for w in page if w["id"] == widget_id)
        self.assertEqual(widget["config"], {"server_ids": ["srv-1"], "auto_rotate": True})

    def test_reorder_moves_a_widget_within_the_same_page(self):
        layout = self.api.get_dashboard_layout()
        first_id = layout["pages"][0][0]["id"]
        second_id = layout["pages"][0][1]["id"]

        result = self.api.reorder_dashboard_widget(first_id, 0, 1)

        self.assertEqual([w["id"] for w in result["pages"][0]], [second_id, first_id])

    def test_reorder_moves_a_widget_to_a_new_page(self):
        layout = self.api.get_dashboard_layout()
        widget_id = layout["pages"][0][0]["id"]

        result = self.api.reorder_dashboard_widget(widget_id, 1, 0)

        self.assertEqual(len(result["pages"]), 2)
        self.assertEqual([w["id"] for w in result["pages"][1]], [widget_id])
        self.assertEqual(len(result["pages"][0]), 1)

    def test_reorder_is_a_no_op_when_the_target_page_is_full(self):
        self.api.add_dashboard_widget("recent_jobs")
        self.api.add_dashboard_widget("recent_jobs")
        layout = self.api.add_dashboard_widget("logs")
        widget_to_move = layout["pages"][1][0]["id"]

        result = self.api.reorder_dashboard_widget(widget_to_move, 0, 0)

        self.assertEqual(len(result["pages"][0]), 4)
        self.assertEqual(len(result["pages"][1]), 1)

    def test_reorder_with_an_unknown_id_is_a_no_op(self):
        before = self.api.get_dashboard_layout()

        result = self.api.reorder_dashboard_widget("no-such-widget", 0, 0)

        self.assertEqual(result["pages"], before["pages"])

    def test_catalog_includes_a_plugin_widget_with_its_script_source_inlined(self):
        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "example_widget_plugin"
        self.api.printer_manager.renderer_registry.register(
            FakeRendererPlugin("org.example.pridge.widget.example"),
            priority=200,
            is_builtin=False,
            source_path=str(fixture_dir),
        )

        result = self.api.get_dashboard_layout()

        plugin_entries = [item for item in result["catalog"] if item["source"] == "plugin"]
        self.assertEqual(len(plugin_entries), 1)
        self.assertEqual(plugin_entries[0]["type"], "org.example.pridge.widget.example")
        self.assertEqual(plugin_entries[0]["title"], "Example Widget")
        self.assertIn("Example widget rendered", plugin_entries[0]["script_source"])

    def test_catalog_omits_a_renderer_plugin_without_widget_fields(self):
        self.api.printer_manager.renderer_registry.register(
            FakeRendererPlugin("org.example.no.widget"),
            priority=200,
            is_builtin=False,
            source_path="/nonexistent/plugin/path",
        )

        result = self.api.get_dashboard_layout()

        self.assertEqual(
            [item["source"] for item in result["catalog"]], ["builtin", "builtin", "builtin", "builtin"]
        )


if __name__ == "__main__":
    unittest.main()
