# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import json
import logging
import os
import platform
import queue
import sys
import uuid
from collections.abc import Sequence
from datetime import datetime
from logging import Handler, LogRecord
from pathlib import Path
from threading import Event, Thread, Timer
from urllib.parse import urlencode

import webview

from pridge_client.api import ApiError, PridgeClient
from pridge_client.archive import ArchivedJob, ArchiveStore
from pridge_client.autostart import AutoStartError, set_start_at_login
from pridge_client.build_info import BUILD_SYSTEM, BUILD_VARIANT
from pridge_client.config import (
    DARKNESS_GRADES,
    FIT_MODES,
    PRINT_MODES,
    SUBMISSION_METHODS,
    ClientTokenStore,
    ConfigStore,
    ClientConfig,
    DashboardWidget,
    PrinterMapping,
    PrinterProfile,
    ServerConfig,
    mapping_scope_key,
)
from pridge_client.logging_setup import (
    ERROR_LOG_FILE_NAME,
    ERROR_LOGGER_NAME,
    clear_error_log_files,
    clear_log_files,
    configure_logging,
    export_logs_to,
    has_log_files,
    log_detailed_error,
    log_directory_for,
    parse_log_export_date,
)
from pridge_client.models import JobHistoryEntry
from pridge_client.platform_window import (
    configure_application_identity,
    configure_application_menu,
    configure_utility_window,
    create_application_menu,
    ensure_webview2_runtime,
    preferred_webview_gui,
)
from pridge_client.printers import (
    Printer,
    PrinterCapabilities,
    PrinterError,
    PrinterManager,
    validate_driver_settings,
)
from pridge_client.strings import (
    APP_NAME,
    MESSAGE_ARCHIVE_CLEARED,
    MESSAGE_ARCHIVED_JOB_NOT_FOUND,
    MESSAGE_READY,
    MESSAGE_REPRINT_SUBMITTED,
    MESSAGE_CONNECTION_FAILED,
    MESSAGE_CONNECTION_SUCCESS,
    MESSAGE_ERROR_LOGS_CLEARED,
    MESSAGE_ERROR_LOG_EXPORTED,
    MESSAGE_LOG_DIRECTORY_FAILED,
    MESSAGE_LOG_EXPORTED,
    MESSAGE_LOG_EXPORT_FAILED,
    MESSAGE_LOGS_CLEARED,
    MESSAGE_NO_ERROR_LOG_FILE,
    MESSAGE_NO_LOG_ENTRIES_IN_RANGE,
    MESSAGE_NO_LOG_FILE,
    MESSAGE_NOTHING_TO_CLEAR,
    MESSAGE_NOTHING_TO_CLEAR_ERRORS,
    MESSAGE_PLUGIN_INSTALLED,
    MESSAGE_PLUGIN_INSTALL_FAILED,
    MESSAGE_PLUGIN_REMOVED,
    MESSAGE_PLUGIN_REMOVE_FAILED,
    MESSAGE_MAPPING_NOT_FOUND,
    MESSAGE_SERVER_NOT_FOUND,
    MESSAGE_SERVER_REQUIRED,
    MESSAGE_SETTINGS_SAVED,
    MESSAGE_TEST_PRINT_DRIVER_ONLY,
    MESSAGE_TEST_PRINT_SUBMITTED,
    MESSAGE_TOKEN_REQUIRED,
    MESSAGE_TRAY_UNAVAILABLE,
    MESSAGE_WINDOW_HIDDEN,
    MESSAGE_WINDOW_MINIMIZED,
    MENU_ABOUT,
    MENU_HISTORY,
    MENU_PLUGINS,
    MENU_PRINTERS,
    MENU_QUIT,
    MENU_SERVERS,
    MENU_SETTINGS,
    STATUS_RUNNING,
    STATUS_STOPPED,
    WINDOW_ADD_SERVER,
    WINDOW_ABOUT,
    WINDOW_APP_MAPPING,
    WINDOW_EDIT_SERVER,
    WINDOW_HISTORY,
    WINDOW_PLUGINS,
    WINDOW_PRINTERS,
    WINDOW_RECEIPT_COMPOSER,
    WINDOW_SERVERS,
    WINDOW_SETTINGS,
    WINDOW_TITLE,
)
from pridge_client.tray import TrayController, TrayUnavailableError
from pridge_client.version import __version__
from pridge_client.worker import PollingWorker


logger = logging.getLogger(__name__)

WEBUI_DIR = Path(__file__).resolve().parent / "webui"
ASSET_DIR = WEBUI_DIR / "assets"
APP_ICON_PATH = ASSET_DIR / "Icon.png"
TRAY_ICON_PATH = ASSET_DIR / "IconTray.png"
MAX_RECENT_JOBS = 50
MAX_LOG_LINES = 300
MAX_ERROR_LOG_LINES = 100
MAX_DASHBOARD_WIDGETS_PER_PAGE = 4

# The smoke test must never depend on a JS round trip to decide when the
# native GUI has finished initializing: pywebview's `func` callback runs on a
# background thread once the platform GUI loop has actually started, so the
# whole verify-then-shutdown sequence is driven from Python and bounded by a
# watchdog that fires even if window/webview creation itself hangs.
SMOKE_TEST_WATCHDOG_SECONDS = 20
SMOKE_TEST_WINDOW_SHOWN_TIMEOUT_SECONDS = 15
SMOKE_TEST_PRINTER_TIMEOUT_SECONDS = 5
SMOKE_TEST_EXIT_DELAY_SECONDS = 1.0


def _log_stage(stage: str, detail: str) -> None:
    logger.info("[smoke-test] %s: %s", stage, detail)


class QueueLogHandler(Handler):
    def __init__(self, events: queue.Queue[tuple[str, object]], event_name: str = "log") -> None:
        super().__init__()
        self.events = events
        self.event_name = event_name

    def emit(self, record: LogRecord) -> None:
        self.events.put((self.event_name, self.format(record)))


class ClientApi:
    """Backend controller exposed to the React frontend as ``pywebview.api``."""

    def __init__(
        self,
        config_store: ConfigStore | None = None,
        token_store: ClientTokenStore | None = None,
        printer_manager: PrinterManager | None = None,
        archive_store: ArchiveStore | None = None,
        gui_smoke_test: bool = False,
    ) -> None:
        self.config_store = config_store or ConfigStore()
        self.token_store = token_store or ClientTokenStore()
        self.printer_manager = printer_manager or PrinterManager()
        self.archive_store = archive_store or ArchiveStore()
        self.config = self.config_store.load()
        self.workers: dict[str, PollingWorker] = {}
        self._server_windows: dict[str, webview.Window] = {}
        self._utility_windows: dict[str, webview.Window] = {}
        self._tray: TrayController | None = None
        self._window: webview.Window | None = None
        self._quitting = False
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.printers: list[Printer] = []
        self.gui_smoke_test = gui_smoke_test
        self.gui_ready = Event()
        self._pending_receipt_selection: tuple[str, str] | None = None

        self.selected_server_id = self.config.servers[0].id if self.config.servers else ""
        self.selected_printer = self.config.selected_printer
        self.start_polling_on_launch = self.config.start_polling_on_launch
        self.start_at_login = self.config.start_at_login
        self.restart_on_crash = self.config.restart_on_crash
        self.connection_status = STATUS_STOPPED
        self.heartbeat_status = STATUS_STOPPED
        self.ready_status = MESSAGE_READY
        self.recent_jobs: list[str] = []
        self.logs: list[str] = ["Pridge Client GUI loaded"]
        # Detailed, full-traceback error entries - a separate channel from
        # self.logs so they never clutter the ordinary Logs/Status widget;
        # see logging_setup.log_detailed_error for how entries land here.
        self.error_details: list[str] = []
        # Lifetime counts persist through config.json (see _bump_printer_stat);
        # session counts are intentionally never saved, so they always read
        # zero right after a restart - "how many since the client came up".
        self.printer_stats: dict[str, dict[str, dict[str, int]]] = self.config.printer_stats
        self.printer_stats_session: dict[str, dict[str, dict[str, int]]] = {}

        self._install_log_handler()
        if self.gui_smoke_test:
            self._smoke_test_refresh_printers()
        else:
            self.refresh_printers()

    # ------------------------------------------------------------------
    # JS-exposed API (methods below are callable from the frontend as
    # pywebview.api.<name>(...); every mutating call returns the fresh
    # state so the frontend can re-render without a second round trip)
    # ------------------------------------------------------------------
    def get_state(self) -> dict:
        return {"ok": True, "error": None, "state": self._build_state()}

    def notify_gui_ready(self) -> dict:
        first_notification = not self.gui_ready.is_set()
        self.gui_ready.set()
        if first_notification:
            logger.info("Desktop interface became ready")
        return {"ok": True}

    def add_server(self, server: dict) -> dict:
        name = str(server.get("name", "")).strip()
        server_url = str(server.get("server_url", "")).strip()
        if not name or not server_url:
            return self._error(MESSAGE_SERVER_REQUIRED)
        mappings = self._printer_mappings(server.get("printer_mappings", []))
        token = str(server.get("token", "")).strip()
        if token:
            sync_error = self._sync_server_endpoints(server_url, token, mappings)
            if sync_error is not None:
                return self._error(sync_error)
        new_server = ServerConfig(
            id=uuid.uuid4().hex,
            name=name,
            server_url=server_url,
            enabled=bool(server.get("enabled", True)),
            polling_interval_seconds=self._safe_int(server.get("polling_interval_seconds"), 5, minimum=1),
            heartbeat_interval_seconds=self._safe_int(server.get("heartbeat_interval_seconds"), 30, minimum=5),
            default_printer=str(server.get("default_printer", "")).strip(),
            printer_mappings=mappings,
        )
        self.config.servers.append(new_server)
        if token:
            self.token_store.set(token, new_server.id)
        self.config_store.save(self._current_config())
        self.selected_server_id = new_server.id
        return self._ok()

    def update_server(self, server_id: str, fields: dict) -> dict:
        server = self._server_by_id(server_id)
        if server is None:
            return self._error(MESSAGE_SERVER_NOT_FOUND)
        name = str(fields.get("name", "")).strip()
        server_url = str(fields.get("server_url", "")).strip()
        if not name or not server_url:
            return self._error(MESSAGE_SERVER_REQUIRED)
        mappings = self._printer_mappings(fields.get("printer_mappings", []), existing=server.printer_mappings)
        replacement_token = str(fields.get("token", "")).strip()
        token = replacement_token or self.token_store.get(server.id)
        if token:
            sync_error = self._sync_server_endpoints(server_url, token, mappings)
            if sync_error is not None:
                return self._error(sync_error)
        was_running = bool(self.workers.get(server_id) and self.workers[server_id].state.running)
        if was_running:
            self.stop_worker(server_id)
        server.name = name
        server.server_url = server_url
        server.enabled = bool(fields.get("enabled", server.enabled))
        server.polling_interval_seconds = self._safe_int(
            fields.get("polling_interval_seconds"), server.polling_interval_seconds, minimum=1
        )
        server.heartbeat_interval_seconds = self._safe_int(
            fields.get("heartbeat_interval_seconds"), server.heartbeat_interval_seconds, minimum=5
        )
        server.default_printer = str(fields.get("default_printer", server.default_printer)).strip()
        server.printer_mappings = mappings
        if replacement_token:
            self.token_store.set(replacement_token, server.id)
        self.config_store.save(self._current_config())
        if was_running and server.enabled:
            self.start_worker(server)
        return self._ok()

    def remove_server(self, server_id: str) -> dict:
        self.stop_worker(server_id)
        self.config.servers = [s for s in self.config.servers if s.id != server_id]
        self.token_store.clear(server_id)
        if self.selected_server_id == server_id:
            self.selected_server_id = self.config.servers[0].id if self.config.servers else ""
        self.config_store.save(self._current_config())
        return self._ok()

    def select_server(self, server_id: str) -> dict:
        if self._server_by_id(server_id) is not None:
            self.selected_server_id = server_id
        return self._ok()

    def open_server_window(self, server_id: str = "") -> dict:
        if server_id and self._server_by_id(server_id) is None:
            return self._error(MESSAGE_SERVER_NOT_FOUND)

        self.refresh_printers()
        window_key = uuid.uuid4().hex
        query = urlencode({"server_id": server_id, "window_key": window_key})
        title = WINDOW_EDIT_SERVER if server_id else WINDOW_ADD_SERVER
        window = webview.create_window(
            title,
            url=f"{WEBUI_DIR / 'server.html'}?{query}",
            js_api=self,
            width=680,
            height=820,
            min_size=(580, 700),
            background_color="#111827",
            **_window_effects(),
        )
        self._server_windows[window_key] = window
        return self._ok()

    def close_server_window(self, window_key: str) -> dict:
        window = self._server_windows.pop(window_key, None)
        if window is not None:
            window.destroy()
        return self._ok()

    def open_settings_window(self) -> dict:
        return self._open_utility_window(
            key="settings",
            title=WINDOW_SETTINGS,
            page="settings.html",
            width=620,
            height=700,
        )

    def open_about_window(self) -> dict:
        return self._open_utility_window(
            key="about",
            title=WINDOW_ABOUT,
            page="about.html",
            width=600,
            height=690,
        )

    def open_plugins_window(self) -> dict:
        return self._open_utility_window(
            key="plugins",
            title=WINDOW_PLUGINS,
            page="plugins.html",
            width=680,
            height=760,
        )

    def open_servers_window(self) -> dict:
        return self._open_utility_window(
            key="servers",
            title=WINDOW_SERVERS,
            page="servers.html",
            width=760,
            height=780,
        )

    def open_printers_window(self) -> dict:
        return self._open_utility_window(
            key="printers",
            title=WINDOW_PRINTERS,
            page="printers.html",
            width=680,
            height=760,
        )

    def open_history_window(self) -> dict:
        return self._open_utility_window(
            key="history",
            title=WINDOW_HISTORY,
            page="history.html",
            width=760,
            height=780,
        )

    def open_app_mapping_window(self) -> dict:
        return self._open_utility_window(
            key="app_mapping",
            title=WINDOW_APP_MAPPING,
            page="app-mapping.html",
            width=640,
            height=720,
        )

    def open_receipt_composer_window(self, server_id: str = "", remote_printer_id: str = "") -> dict:
        server_id = str(server_id or "").strip()
        remote_printer_id = str(remote_printer_id or "").strip()
        if server_id and remote_printer_id:
            self._pending_receipt_selection = (server_id, remote_printer_id)
        already_open = self._utility_windows.get("receipt_composer")
        result = self._open_utility_window(
            key="receipt_composer",
            title=WINDOW_RECEIPT_COMPOSER,
            page="receipt-composer.html",
            width=760,
            height=800,
        )
        if already_open is not None and self._pending_receipt_selection:
            # The window was already open, so receipt-composer.js's mount-time
            # check already ran and won't automatically notice the newly set
            # pending selection - nudge it to re-check right now instead of
            # only applying on the next fresh page load.
            try:
                already_open.evaluate_js(
                    "window.__pridgeApplyPendingReceiptSelection && window.__pridgeApplyPendingReceiptSelection()"
                )
            except Exception:
                pass
        return result

    def get_pending_receipt_selection(self) -> dict:
        pending = self._pending_receipt_selection
        self._pending_receipt_selection = None
        server_id, remote_printer_id = pending or ("", "")
        return {"ok": True, "error": None, "server_id": server_id, "remote_printer_id": remote_printer_id}

    def open_plugin_settings_window(self, settings_window: str) -> dict:
        openers = {
            "app_mapping": self.open_app_mapping_window,
            "receipt_composer": self.open_receipt_composer_window,
        }
        opener = openers.get(str(settings_window))
        if opener is None:
            return self._error("This plugin does not have a settings window.")
        return opener()

    def close_utility_window(self, key: str) -> dict:
        window = self._utility_windows.pop(str(key), None)
        if window is not None:
            window.destroy()
        return self._ok()

    def test_server_connection(self, server_id: str, fields: dict) -> dict:
        server_url = str(fields.get("server_url", "")).strip()
        token = str(fields.get("token", "")).strip()
        if not token and server_id:
            token = self.token_store.get(server_id)
        if not server_url:
            return self._error(MESSAGE_SERVER_REQUIRED)
        if not token:
            return self._error(MESSAGE_TOKEN_REQUIRED)

        try:
            PridgeClient(server_url, token).authenticate()
        except ApiError as exc:
            return self._error(str(exc))
        except Exception as exc:
            logger.warning("Server connection test failed: %s", exc)
            return self._error(MESSAGE_CONNECTION_FAILED)
        return {"ok": True, "error": None, "message": MESSAGE_CONNECTION_SUCCESS, "state": self._build_state()}

    def discover_remote_printers(self, server_id: str, fields: dict) -> dict:
        server_url = str(fields.get("server_url", "")).strip()
        token = str(fields.get("token", "")).strip()
        if not token and server_id:
            token = self.token_store.get(server_id)
        if not server_url:
            return self._error(MESSAGE_SERVER_REQUIRED)
        if not token:
            return self._error(MESSAGE_TOKEN_REQUIRED)

        try:
            client = PridgeClient(server_url, token)
            printers = client.list_remote_printers()
        except ApiError as exc:
            return self._error(str(exc))
        except Exception as exc:
            logger.warning("Remote printer discovery failed: %s", exc)
            return self._error(MESSAGE_CONNECTION_FAILED)
        return {
            "ok": True,
            "error": None,
            "remote_printers": [
                {
                    "remote_printer_id": printer.printer_id,
                    "remote_printer_name": printer.name,
                    "enabled": printer.enabled,
                    "assigned": printer.assigned,
                }
                for printer in printers
            ],
            "state": self._build_state(),
        }

    def refresh_printers(self) -> dict:
        try:
            self.printers = self.printer_manager.list_printers()
        except PrinterError as exc:
            logger.warning("Printer refresh failed: %s", exc)
            self.printers = []

        names = [printer.name for printer in self.printers]
        if names and self.selected_printer not in names:
            default = next((printer.name for printer in self.printers if printer.is_default), names[0])
            self.selected_printer = default
        if not names:
            self.selected_printer = ""
        return self._ok()

    def _smoke_test_refresh_printers(self) -> None:
        """Bounded, non-blocking printer check used only by --gui-smoke-test.

        A missing or unresponsive system print service must never block or
        fail the smoke test, so enumeration runs on a daemon thread with a
        strict timeout and any outcome other than a clean list is treated as
        a warning.
        """
        _log_stage("printer test", "starting bounded printer enumeration")
        discovered: list[Printer] = []
        failure: list[BaseException] = []

        def worker() -> None:
            try:
                discovered.extend(self.printer_manager.list_printers())
            except BaseException as exc:  # noqa: BLE001 - reported, never raised
                failure.append(exc)

        thread = Thread(target=worker, name="pridge-smoke-printer-check", daemon=True)
        thread.start()
        thread.join(timeout=SMOKE_TEST_PRINTER_TIMEOUT_SECONDS)

        self.printers = []
        if thread.is_alive():
            logger.warning(
                "Printer test: enumeration did not finish within %ss; continuing without printers",
                SMOKE_TEST_PRINTER_TIMEOUT_SECONDS,
            )
        elif failure:
            logger.warning("Printer test: printer enumeration failed: %s", failure[0])
        else:
            self.printers = discovered
        _log_stage("printer test", f"complete, discovered {len(self.printers)} printer(s)")

    def select_printer(self, name: str) -> dict:
        self.selected_printer = str(name)
        return self._ok()

    def get_printer_capabilities(self, printer_name: str, server_id: str = "") -> dict:
        name = str(printer_name).strip()
        if not name:
            return self._error("No printer is selected.")
        store = self._profile_store(server_id)
        profile = store.get(name, PrinterProfile())
        try:
            capabilities = self.printer_manager.get_capabilities(name)
        except PrinterError:
            # Not currently detected by the OS (asleep, offline, or this call
            # is coming from a machine other than wherever the printer is
            # actually reachable from) - keep the profile (mode, RAW/Composer
            # settings) editable regardless; only live driver capabilities are
            # unavailable until the printer is detected again.
            capabilities = PrinterCapabilities(printer_name=name, system_driver_available=False)

        validated = validate_driver_settings(capabilities, profile.driver_settings)
        if capabilities.system_driver_available and validated != profile.driver_settings:
            profile.driver_settings = validated
            store[name] = profile
            self.config_store.save(self._current_config())
        return {
            "ok": True,
            "error": None,
            "capabilities": capabilities.public(validated),
            "profile": self._printer_profile_public(profile),
            "platform_system": platform.system(),
            "state": self._build_state(),
        }

    def update_printer_profile(self, printer_name: str, fields: dict, server_id: str = "") -> dict:
        name = str(printer_name).strip()
        if not name:
            return self._error("No printer is selected.")
        mode = str(fields.get("mode", "system_driver")).strip().lower()
        if mode not in PRINT_MODES:
            return self._error("The selected printing mode is not supported.")

        store = self._profile_store(server_id)
        existing = store.get(name, PrinterProfile())
        raw_settings = fields.get("driver_settings", existing.driver_settings)
        settings = self._driver_settings(raw_settings)
        submission_method = str(fields.get("submission_method", existing.submission_method)).strip().lower()
        if submission_method not in SUBMISSION_METHODS:
            submission_method = existing.submission_method
        fit_mode = str(fields.get("fit_mode", existing.fit_mode)).strip().lower()
        if fit_mode not in FIT_MODES:
            fit_mode = existing.fit_mode
        capabilities = None
        if mode == "system_driver":
            # Only System Driver mode actually needs live driver capabilities
            # (to validate driver_settings against real options) - RAW mode
            # needs none of this, so it must never be blocked by the printer
            # being temporarily undetected (asleep, offline, or configured
            # from a different machine than the one that'll print to it).
            try:
                capabilities = self.printer_manager.get_capabilities(name)
            except PrinterError as exc:
                return self._error(str(exc))
            if not capabilities.system_driver_available:
                return self._error("The selected printer does not have an available system driver.")
            settings = validate_driver_settings(capabilities, settings)

        profile = PrinterProfile(
            mode=mode,
            driver_settings=settings,
            submission_method=submission_method,
            fit_mode=fit_mode,
            raw_header_preset=existing.raw_header_preset,
            raw_header_custom_hex=existing.raw_header_custom_hex,
            raw_footer_preset=existing.raw_footer_preset,
            raw_footer_custom_hex=existing.raw_footer_custom_hex,
        )
        store[name] = profile
        self.config = self._current_config()
        self.config_store.save(self.config)
        logger.info("Updated printing mode for printer %s", name)
        return {
            "ok": True,
            "error": None,
            "message": MESSAGE_SETTINGS_SAVED,
            "capabilities": capabilities.public(settings) if capabilities else None,
            "profile": self._printer_profile_public(profile),
            "state": self._build_state(),
        }

    def open_printer_driver_settings(self, printer_name: str, server_id: str = "") -> dict:
        name = str(printer_name).strip()
        if name not in {printer.name for printer in self.printers}:
            return self._error("The selected printer is no longer available.")
        try:
            self.printer_manager.open_driver_settings(name)
        except PrinterError as exc:
            return self._error(str(exc))
        return self.get_printer_capabilities(name, server_id)

    def test_printer(self, printer_name: str, server_id: str = "") -> dict:
        name = str(printer_name).strip()
        if name not in {printer.name for printer in self.printers}:
            return self._error("The selected printer is no longer available.")
        profile = self._profile_store(server_id).get(name, PrinterProfile())
        if profile.mode not in {"system_driver", "raw"}:
            return self._error(MESSAGE_TEST_PRINT_DRIVER_ONLY)
        try:
            # No specific mapping context here (this is the generic Printers
            # window, not the mapping-scoped Receipt Composer) - RAW mode test
            # prints from here exercise bare connectivity only, with no
            # header/footer template, same as a real job with no matching
            # mapping. See test_mapping_receipt_design for the composed-template
            # test print.
            self.printer_manager.print_test_page(
                name,
                mode=profile.mode,
                driver_settings=profile.driver_settings,
                submission_method=profile.submission_method or None,
                fit_mode=profile.fit_mode,
            )
        except PrinterError as exc:
            self._bump_printer_stat(name, origin="test", success=False)
            log_detailed_error(f"Test print failed on printer {name}", exc)
            return self._error(str(exc))
        logger.info("Submitted test page to printer %s", name)
        self._bump_printer_stat(name, origin="test", success=True)
        return {
            "ok": True,
            "error": None,
            "message": MESSAGE_TEST_PRINT_SUBMITTED,
            "state": self._build_state(),
        }

    def _profile_store(self, server_id: str) -> dict[str, PrinterProfile]:
        server_id = str(server_id or "").strip()
        if server_id:
            server = self._server_by_id(server_id)
            if server is not None:
                return server.printer_profiles
        return self.config.printer_profiles

    def get_dashboard_layout(self) -> dict:
        return {"ok": True, "error": None, **self._dashboard_layout_payload()}

    def add_dashboard_widget(self, widget_type: str) -> dict:
        widget_type = str(widget_type).strip()
        catalog = self._dashboard_catalog()
        if widget_type not in {item["type"] for item in catalog}:
            return {"ok": False, "error": "That widget is not available.", **self._dashboard_layout_payload()}

        pages = self._grouped_dashboard_widgets()
        target_page = next(
            (index for index, widgets in enumerate(pages) if len(widgets) < MAX_DASHBOARD_WIDGETS_PER_PAGE),
            len(pages),
        )
        if target_page == len(pages):
            pages.append([])
        pages[target_page].append(DashboardWidget(id=uuid.uuid4().hex, widget_type=widget_type))
        self._save_dashboard_widgets(pages)
        return self.get_dashboard_layout()

    def remove_dashboard_widget(self, widget_id: str) -> dict:
        widget_id = str(widget_id).strip()
        pages = self._grouped_dashboard_widgets()
        for widgets in pages:
            widgets[:] = [widget for widget in widgets if widget.id != widget_id]
        self._save_dashboard_widgets([widgets for widgets in pages if widgets])
        return self.get_dashboard_layout()

    def reorder_dashboard_widget(self, widget_id: str, target_page: int, target_position: int) -> dict:
        widget_id = str(widget_id).strip()
        try:
            target_page = int(target_page)
            target_position = int(target_position)
        except (TypeError, ValueError):
            return self.get_dashboard_layout()

        pages = self._grouped_dashboard_widgets()
        source = None
        for page_index, widgets in enumerate(pages):
            for position, widget in enumerate(widgets):
                if widget.id == widget_id:
                    source = (page_index, position)
                    break
            if source:
                break

        if source is not None:
            source_page, source_position = source
            widget = pages[source_page][source_position]
            target_page = max(0, min(target_page, len(pages)))
            if target_page == len(pages):
                pages.append([])
            same_page = target_page == source_page
            room_available = same_page or len(pages[target_page]) < MAX_DASHBOARD_WIDGETS_PER_PAGE
            if room_available:
                pages[source_page].pop(source_position)
                target_widgets = pages[target_page]
                target_position = max(0, min(target_position, len(target_widgets)))
                target_widgets.insert(target_position, widget)

        self._save_dashboard_widgets([widgets for widgets in pages if widgets])
        return self.get_dashboard_layout()

    def update_dashboard_widget_config(self, widget_id: str, config: dict) -> dict:
        widget_id = str(widget_id).strip()
        if not isinstance(config, dict):
            return {"ok": False, "error": "Invalid widget configuration.", **self._dashboard_layout_payload()}

        pages = self._grouped_dashboard_widgets()
        for widgets in pages:
            for widget in widgets:
                if widget.id == widget_id:
                    widget.config = config

        self._save_dashboard_widgets(pages)
        return self.get_dashboard_layout()

    def _dashboard_layout_payload(self) -> dict:
        catalog = self._dashboard_catalog()
        catalog_by_type = {item["type"]: item for item in catalog}
        pages = []
        for widgets in self._grouped_dashboard_widgets():
            page = []
            for widget in widgets:
                meta = catalog_by_type.get(widget.widget_type, {"title": widget.widget_type, "source": "unknown"})
                page.append(
                    {
                        "id": widget.id,
                        "widget_type": widget.widget_type,
                        "title": meta.get("title", widget.widget_type),
                        "source": meta.get("source", "unknown"),
                        "script_source": meta.get("script_source", ""),
                        "config": widget.config,
                    }
                )
            pages.append(page)
        return {"pages": pages, "catalog": catalog}

    def _dashboard_catalog(self) -> list[dict]:
        catalog = [
            {"type": "recent_jobs", "title": "Recent Jobs", "source": "builtin", "category": "Core"},
            {"type": "logs", "title": "Logs / Status", "source": "builtin", "category": "Core"},
            {"type": "error_log", "title": "Error Details", "source": "builtin", "category": "Core"},
            {
                "type": "printer_stats",
                "title": "Printer Activity",
                "source": "builtin",
                "configurable": True,
                "category": "Core",
            },
            {
                "type": "server_status",
                "title": "Server Status",
                "source": "builtin",
                "configurable": True,
                "category": "Core",
            },
        ]

        composer_entry = self.printer_manager.renderer_registry.get_entry(
            self.printer_manager.receipt_composer_plugin.plugin_id
        )
        if composer_entry is not None and composer_entry.enabled:
            catalog.append(
                {"type": "receipt_composer_items", "title": "Receipt Composer", "source": "builtin", "category": "Core"}
            )

        from pridge_client.plugins.manifest import MANIFEST_FILE_NAME, load_manifest

        for entry in self.printer_manager.renderer_registry.all_entries():
            if entry.is_builtin or not entry.source_path or entry.load_error:
                continue
            try:
                manifest = load_manifest(Path(entry.source_path) / MANIFEST_FILE_NAME)
            except Exception:
                continue
            if not manifest.has_widget:
                continue
            script_path = Path(entry.source_path) / manifest.widget_entry
            if not script_path.is_file():
                continue
            try:
                script_source = script_path.read_text(encoding="utf-8")
            except OSError:
                continue
            catalog.append(
                {
                    "type": entry.plugin.plugin_id,
                    "title": manifest.widget_title,
                    "source": "plugin",
                    "category": entry.category or "Plugins",
                    "script_source": script_source,
                }
            )
        return catalog

    def _grouped_dashboard_widgets(self) -> list[list[DashboardWidget]]:
        pages: dict[int, list[DashboardWidget]] = {}
        for widget in sorted(self.config.dashboard_widgets, key=lambda w: (w.page, w.position)):
            pages.setdefault(widget.page, []).append(widget)
        ordered = [pages[key] for key in sorted(pages.keys())]
        return ordered or [[]]

    def _save_dashboard_widgets(self, pages: list[list[DashboardWidget]]) -> None:
        flattened: list[DashboardWidget] = []
        for page_index, widgets in enumerate(pages):
            for position, widget in enumerate(widgets):
                flattened.append(
                    DashboardWidget(
                        id=widget.id,
                        widget_type=widget.widget_type,
                        page=page_index,
                        position=position,
                        config=widget.config,
                    )
                )
        self.config.dashboard_widgets = flattened
        self.config = self._current_config()
        self.config_store.save(self.config)

    def set_start_polling_on_launch(self, value: bool) -> dict:
        self.start_polling_on_launch = bool(value)
        return self._ok()

    def set_start_at_login(self, value: bool) -> dict:
        self.start_at_login = bool(value)
        return self._ok()

    def save_settings(self) -> dict:
        self.config = self._current_config()
        self.config_store.save(self.config)
        try:
            set_start_at_login(self.config.start_at_login)
        except AutoStartError as exc:
            logger.warning("Could not update auto-start setting: %s", exc)
        logger.info(MESSAGE_SETTINGS_SAVED)
        return self._ok()

    def update_application_settings(self, fields: dict) -> dict:
        self.start_polling_on_launch = bool(fields.get("start_polling_on_launch", self.start_polling_on_launch))
        self.start_at_login = bool(fields.get("start_at_login", self.start_at_login))
        self.restart_on_crash = bool(fields.get("restart_on_crash", self.restart_on_crash))
        darkness_grade = str(fields.get("darkness_grade", self.config.appearance.darkness_grade)).strip().title()
        if darkness_grade in DARKNESS_GRADES:
            self.config.appearance.darkness_grade = darkness_grade

        previous_logging = (
            self.config.logging.file_enabled,
            self.config.logging.retention_days,
            self.config.logging.directory,
        )
        if "log_file_enabled" in fields:
            self.config.logging.file_enabled = bool(fields["log_file_enabled"])
        if "log_retention_days" in fields:
            self.config.logging.retention_days = self._safe_int(
                fields["log_retention_days"], self.config.logging.retention_days, 1, 365
            )
        if "log_directory" in fields:
            self.config.logging.directory = str(fields["log_directory"] or "").strip()
        logging_changed = (
            self.config.logging.file_enabled,
            self.config.logging.retention_days,
            self.config.logging.directory,
        ) != previous_logging

        self._broadcast_appearance()
        self.config = self._current_config()
        self.config_store.save(self.config)
        try:
            set_start_at_login(self.config.start_at_login)
        except AutoStartError as exc:
            logger.warning("Could not update auto-start setting: %s", exc)
        if logging_changed:
            configure_logging(self.config)
            self._install_log_handler()
        logger.info(MESSAGE_SETTINGS_SAVED)
        return {
            "ok": True,
            "error": None,
            "message": MESSAGE_SETTINGS_SAVED,
            "restart_required": False,
            "state": self._build_state(),
        }

    def get_renderer_plugins(self) -> dict:
        entries = self.printer_manager.renderer_registry.all_entries()
        entries_sorted = sorted(entries, key=lambda e: e.priority)
        plugins = [
            {
                "plugin_id": entry.plugin.plugin_id,
                "display_name": entry.plugin.display_name,
                "version": entry.plugin.version,
                "api_version": entry.plugin.api_version,
                "mime_types": sorted(entry.plugin.supported_mime_types),
                "extensions": sorted(entry.plugin.supported_extensions),
                "enabled": entry.enabled,
                "priority": entry.priority,
                "is_builtin": entry.is_builtin,
                "category": entry.category,
                "load_error": entry.load_error,
                "source_path": entry.source_path,
                "settings_window": getattr(entry.plugin, "settings_window", ""),
                "has_settings": bool(getattr(entry.plugin, "settings_window", "")),
            }
            for entry in entries_sorted
        ]
        return {"ok": True, "error": None, "plugins": plugins}

    def set_renderer_plugin_enabled(self, plugin_id: str, enabled: bool) -> dict:
        self.printer_manager.renderer_registry.set_enabled(str(plugin_id), bool(enabled))
        return self.get_renderer_plugins()

    def install_plugin(self) -> dict:
        window = self._utility_windows.get("plugins") or self._window
        if window is None:
            return self._error(MESSAGE_PLUGIN_INSTALL_FAILED)
        try:
            selection = window.create_file_dialog(webview.FileDialog.FOLDER)
        except Exception as exc:
            logger.warning("Could not open the plugin install dialog: %s", exc)
            return self._error(MESSAGE_PLUGIN_INSTALL_FAILED)
        if not selection:
            return self.get_renderer_plugins()

        from pridge_client.plugins import PluginInstallError

        source = selection[0] if isinstance(selection, (list, tuple)) else selection
        try:
            plugin_id = self.printer_manager.install_renderer_plugin(Path(source))
        except PluginInstallError as exc:
            return self._error(str(exc))
        logger.info("Installed third-party renderer plugin %s", plugin_id)
        result = self.get_renderer_plugins()
        result["message"] = MESSAGE_PLUGIN_INSTALLED
        return result

    def remove_plugin(self, plugin_id: str) -> dict:
        from pridge_client.plugins import PluginInstallError

        entry = self.printer_manager.renderer_registry.get_entry(str(plugin_id))
        if entry is None or entry.is_builtin:
            return self._error(MESSAGE_PLUGIN_REMOVE_FAILED)
        try:
            self.printer_manager.remove_renderer_plugin(str(plugin_id))
        except PluginInstallError as exc:
            return self._error(str(exc))
        logger.info("Removed third-party renderer plugin %s", plugin_id)
        result = self.get_renderer_plugins()
        result["message"] = MESSAGE_PLUGIN_REMOVED
        return result

    def rescan_plugins(self) -> dict:
        self.printer_manager.rescan_renderer_plugins()
        return self.get_renderer_plugins()

    def get_app_mappings(self) -> dict:
        mappings = self.printer_manager.app_mapping_plugin.get_mappings()
        return {"ok": True, "error": None, "mappings": [self._mapping_public(m) for m in mappings]}

    def add_app_mapping(self, fields: dict) -> dict:
        from pridge_client.renderers import AppMapping
        import uuid as _uuid
        mapping = AppMapping(
            id=_uuid.uuid4().hex,
            name=str(fields.get("name", "")).strip(),
            extensions=self._str_list(fields.get("extensions", [])),
            mime_types=self._str_list(fields.get("mime_types", [])),
            executable=str(fields.get("executable", "")).strip(),
            arguments=self._str_list(fields.get("arguments", [])),
            timeout=self._safe_float(fields.get("timeout"), 60.0, minimum=1.0),
            enabled=bool(fields.get("enabled", True)),
            platform_filter=str(fields.get("platform_filter", "")).strip().lower(),
        )
        if not mapping.name:
            return self._error("Mapping name is required.")
        mappings = self.printer_manager.app_mapping_plugin.get_mappings()
        mappings.append(mapping)
        self.printer_manager.app_mapping_plugin.set_mappings(mappings)
        self.printer_manager.app_mapping_store.save(mappings)
        return self.get_app_mappings()

    def update_app_mapping(self, mapping_id: str, fields: dict) -> dict:
        from pridge_client.renderers import AppMapping
        mappings = self.printer_manager.app_mapping_plugin.get_mappings()
        idx = next((i for i, m in enumerate(mappings) if m.id == str(mapping_id)), None)
        if idx is None:
            return self._error("Mapping not found.")
        existing = mappings[idx]
        updated = AppMapping(
            id=existing.id,
            name=str(fields.get("name", existing.name)).strip() or existing.name,
            extensions=self._str_list(fields.get("extensions", existing.extensions)),
            mime_types=self._str_list(fields.get("mime_types", existing.mime_types)),
            executable=str(fields.get("executable", existing.executable)).strip(),
            arguments=self._str_list(fields.get("arguments", existing.arguments)),
            timeout=self._safe_float(fields.get("timeout"), existing.timeout, minimum=1.0),
            enabled=bool(fields.get("enabled", existing.enabled)),
            platform_filter=str(fields.get("platform_filter", existing.platform_filter)).strip().lower(),
        )
        mappings[idx] = updated
        self.printer_manager.app_mapping_plugin.set_mappings(mappings)
        self.printer_manager.app_mapping_store.save(mappings)
        return self.get_app_mappings()

    def remove_app_mapping(self, mapping_id: str) -> dict:
        mappings = self.printer_manager.app_mapping_plugin.get_mappings()
        mappings = [m for m in mappings if m.id != str(mapping_id)]
        self.printer_manager.app_mapping_plugin.set_mappings(mappings)
        self.printer_manager.app_mapping_store.save(mappings)
        return self.get_app_mappings()

    def _receipt_image_public(self, image) -> dict:
        import base64

        data = self.printer_manager.receipt_composer_store.load_image_bytes(image.id)
        return {
            "id": image.id,
            "name": image.name,
            "width": image.width,
            "height": image.height,
            "data_base64": base64.b64encode(data).decode("ascii") if data else "",
        }

    def get_receipt_images(self) -> dict:
        images = self.printer_manager.receipt_composer_store.list_images()
        return {"ok": True, "error": None, "images": [self._receipt_image_public(image) for image in images]}

    def add_receipt_image(self, name: str, data_base64: str) -> dict:
        import base64
        import binascii

        try:
            data = base64.b64decode(str(data_base64), validate=True)
        except (binascii.Error, ValueError):
            return self._error("The uploaded image data is not valid Base64.")
        if not data:
            return self._error("The uploaded image is empty.")
        try:
            self.printer_manager.receipt_composer_store.add_image(str(name), data)
        except Exception as exc:
            logger.warning("Could not add receipt image: %s", exc)
            return self._error("Could not read the uploaded image. Make sure it's a valid image file.")
        return self.get_receipt_images()

    def remove_receipt_image(self, image_id: str) -> dict:
        self.printer_manager.receipt_composer_store.remove_image(str(image_id))
        return self.get_receipt_images()

    def _find_mapping(self, server_id: str, remote_printer_id: str) -> tuple[ServerConfig | None, PrinterMapping | None]:
        server = self._server_by_id(str(server_id or "").strip())
        if server is None:
            return None, None
        remote_printer_id = str(remote_printer_id or "").strip()
        mapping = next((m for m in server.printer_mappings if m.remote_printer_id == remote_printer_id), None)
        return (server, mapping) if mapping is not None else (server, None)

    def get_mapping_receipt_design(self, server_id: str, remote_printer_id: str) -> dict:
        server, mapping = self._find_mapping(server_id, remote_printer_id)
        if server is None or mapping is None:
            return self._error(MESSAGE_MAPPING_NOT_FOUND)
        profile = server.printer_profiles.get(
            mapping.local_printer_name, self.config.printer_profiles.get(mapping.local_printer_name, PrinterProfile())
        )
        return {
            "ok": True,
            "error": None,
            "design": self._mapping_receipt_design_public(mapping),
            "local_printer_name": mapping.local_printer_name,
            "printer_mode": profile.mode,
            "state": self._build_state(),
        }

    def update_mapping_receipt_design(self, server_id: str, remote_printer_id: str, fields: dict) -> dict:
        server, mapping = self._find_mapping(server_id, remote_printer_id)
        if server is None or mapping is None:
            return self._error(MESSAGE_MAPPING_NOT_FOUND)
        mapping.raw_template = str(fields.get("raw_template", mapping.raw_template))
        raw_paper_width_dots = self._safe_int(
            fields.get("raw_paper_width_dots", mapping.raw_paper_width_dots), mapping.raw_paper_width_dots, 8, 4096
        )
        mapping.raw_paper_width_dots = max(8, (raw_paper_width_dots // 8) * 8)
        mapping.raw_chars_per_line = self._safe_int(
            fields.get("raw_chars_per_line", mapping.raw_chars_per_line), mapping.raw_chars_per_line, 8, 128
        )
        mapping.composer_enabled = bool(fields.get("composer_enabled", mapping.composer_enabled))
        mapping.receipt_design_migrated = True
        self.config_store.save(self._current_config())
        return {
            "ok": True,
            "error": None,
            "message": MESSAGE_SETTINGS_SAVED,
            "design": self._mapping_receipt_design_public(mapping),
        }

    def clear_mapping_receipt_design(self, server_id: str, remote_printer_id: str) -> dict:
        _server, mapping = self._find_mapping(server_id, remote_printer_id)
        if mapping is None:
            return self._error(MESSAGE_MAPPING_NOT_FOUND)
        # Clears the design only - saved counters are print history, not
        # design state, and are left alone rather than deleted alongside it.
        mapping.raw_template = ""
        mapping.raw_paper_width_dots = 384
        mapping.raw_chars_per_line = 32
        mapping.receipt_design_migrated = True
        self.config_store.save(self._current_config())
        return {"ok": True, "error": None, "state": self._build_state()}

    def test_mapping_receipt_design(self, server_id: str, remote_printer_id: str) -> dict:
        server, mapping = self._find_mapping(server_id, remote_printer_id)
        if server is None or mapping is None:
            return self._error(MESSAGE_MAPPING_NOT_FOUND)
        name = mapping.local_printer_name
        if name not in {printer.name for printer in self.printers}:
            return self._error("The selected printer is no longer available.")
        profile = server.printer_profiles.get(name, self.config.printer_profiles.get(name, PrinterProfile()))
        if profile.mode != "raw":
            return self._error(MESSAGE_TEST_PRINT_DRIVER_ONLY)
        try:
            self.printer_manager.print_test_page(
                name,
                mode="raw",
                driver_settings=profile.driver_settings,
                # Test Print mirrors real jobs exactly, including the
                # composer_enabled toggle - what you test is what you get.
                raw_template=mapping.raw_template if mapping.composer_enabled else "",
                raw_paper_width_dots=mapping.raw_paper_width_dots,
                raw_chars_per_line=mapping.raw_chars_per_line,
                receipt_scope_key=mapping_scope_key(server.id, mapping.remote_printer_id),
            )
        except PrinterError as exc:
            self._bump_printer_stat(name, origin="test", success=False)
            log_detailed_error(f"Test print failed on printer {name}", exc)
            return self._error(str(exc))
        logger.info("Submitted test page for mapping %s on server %s", remote_printer_id, server.id)
        self._bump_printer_stat(name, origin="test", success=True)
        return {"ok": True, "error": None, "message": MESSAGE_TEST_PRINT_SUBMITTED, "state": self._build_state()}

    def _mapping_receipt_design_public(self, mapping: PrinterMapping) -> dict[str, object]:
        return {
            "raw_template": mapping.raw_template,
            "raw_paper_width_dots": mapping.raw_paper_width_dots,
            "raw_chars_per_line": mapping.raw_chars_per_line,
            "composer_enabled": mapping.composer_enabled,
        }

    def get_receipt_counters(self, server_id: str, remote_printer_id: str) -> dict:
        _server, mapping = self._find_mapping(server_id, remote_printer_id)
        if mapping is None:
            return self._error(MESSAGE_MAPPING_NOT_FOUND)
        counters = self.printer_manager.receipt_composer_store.get_counters(
            mapping_scope_key(server_id, remote_printer_id)
        )
        return {"ok": True, "error": None, "counters": counters}

    def add_receipt_counter(self, server_id: str, remote_printer_id: str, key: str, label: str = "") -> dict:
        from pridge_client.receipt_composer.store import DEFAULT_COUNTER_KEY

        _server, mapping = self._find_mapping(server_id, remote_printer_id)
        if mapping is None:
            return self._error(MESSAGE_MAPPING_NOT_FOUND)
        key = str(key).strip()
        if not key or key == DEFAULT_COUNTER_KEY:
            return self._error("A unique counter name is required.")
        self.printer_manager.receipt_composer_store.add_named_counter(
            mapping_scope_key(server_id, remote_printer_id), key, str(label)
        )
        return self.get_receipt_counters(server_id, remote_printer_id)

    def reset_receipt_counter(self, server_id: str, remote_printer_id: str, key: str, value: int = 0) -> dict:
        _server, mapping = self._find_mapping(server_id, remote_printer_id)
        if mapping is None:
            return self._error(MESSAGE_MAPPING_NOT_FOUND)
        safe_value = self._safe_int(value, 0, minimum=0)
        self.printer_manager.receipt_composer_store.reset(
            mapping_scope_key(server_id, remote_printer_id), str(key), safe_value
        )
        return self.get_receipt_counters(server_id, remote_printer_id)

    def remove_receipt_counter(self, server_id: str, remote_printer_id: str, key: str) -> dict:
        from pridge_client.receipt_composer.store import DEFAULT_COUNTER_KEY

        _server, mapping = self._find_mapping(server_id, remote_printer_id)
        if mapping is None:
            return self._error(MESSAGE_MAPPING_NOT_FOUND)
        key = str(key)
        if key == DEFAULT_COUNTER_KEY:
            return self._error("The default counter cannot be removed.")
        self.printer_manager.receipt_composer_store.remove_named_counter(
            mapping_scope_key(server_id, remote_printer_id), key
        )
        return self.get_receipt_counters(server_id, remote_printer_id)

    def preview_receipt_template(self, template: str, server_id: str = "", remote_printer_id: str = "") -> dict:
        from pridge_client.receipt_composer import render_template_blocks

        _server, mapping = self._find_mapping(server_id, remote_printer_id)
        chars_per_line = mapping.raw_chars_per_line if mapping else 32
        blocks = render_template_blocks(
            str(template),
            printer_name=mapping_scope_key(server_id, remote_printer_id),
            store=self.printer_manager.receipt_composer_store,
            chars_per_line=chars_per_line,
            custom_resolvers=self.printer_manager.receipt_shortcode_resolvers(),
        )
        return {"ok": True, "error": None, "blocks": blocks}

    def reorder_renderer_plugin(self, plugin_id: str, target_index: int, category: str = "") -> dict:
        plugin_id = str(plugin_id).strip()
        try:
            target_index = int(target_index)
        except (TypeError, ValueError):
            return self.get_renderer_plugins()

        registry = self.printer_manager.renderer_registry
        entries = sorted(registry.all_entries(), key=lambda e: e.priority)
        ordered_ids = [entry.plugin.plugin_id for entry in entries]
        if plugin_id not in ordered_ids:
            return self.get_renderer_plugins()

        category = str(category or "")
        if category:
            id_to_category = {entry.plugin.plugin_id: entry.category for entry in entries}
            group_ids = [pid for pid in ordered_ids if id_to_category.get(pid) == category]
            if plugin_id not in group_ids:
                return self.get_renderer_plugins()
            group_ids.remove(plugin_id)
            target_index = max(0, min(target_index, len(group_ids)))
            group_ids.insert(target_index, plugin_id)
            group_iter = iter(group_ids)
            ordered_ids = [
                next(group_iter) if id_to_category.get(pid) == category else pid for pid in ordered_ids
            ]
        else:
            ordered_ids.remove(plugin_id)
            target_index = max(0, min(target_index, len(ordered_ids)))
            ordered_ids.insert(target_index, plugin_id)

        for position, ordered_id in enumerate(ordered_ids):
            registry.set_priority(ordered_id, (position + 1) * 10)
        return self.get_renderer_plugins()

    def export_log(self, start_date: str = "", end_date: str = "") -> dict:
        directory = log_directory_for(self.config)
        if not has_log_files(directory):
            return self._error(MESSAGE_NO_LOG_FILE)

        window = self._utility_windows.get("settings") or self._window
        if window is None:
            return self._error(MESSAGE_LOG_EXPORT_FAILED)

        default_name = f"pridge-client-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        try:
            selection = window.create_file_dialog(webview.FileDialog.SAVE, save_filename=default_name)
        except Exception as exc:
            logger.warning("Could not open the log export dialog: %s", exc)
            return self._error(MESSAGE_LOG_EXPORT_FAILED)

        if not selection:
            return self._ok()
        destination = Path(selection[0] if isinstance(selection, (list, tuple)) else selection)

        parsed_start = parse_log_export_date(start_date)
        parsed_end = parse_log_export_date(end_date)
        try:
            wrote_any = export_logs_to(directory, destination, parsed_start, parsed_end)
        except OSError as exc:
            logger.warning("Could not export the run log: %s", exc)
            return self._error(MESSAGE_LOG_EXPORT_FAILED)

        if not wrote_any:
            destination.unlink(missing_ok=True)
            return self._error(MESSAGE_NO_LOG_ENTRIES_IN_RANGE)

        logger.info("Run log exported to %s", destination)
        return {"ok": True, "error": None, "message": MESSAGE_LOG_EXPORTED, "state": self._build_state()}

    def clear_logs(self) -> dict:
        if not clear_log_files():
            return self._error(MESSAGE_NOTHING_TO_CLEAR)
        logger.info("Logs cleared")
        return {"ok": True, "error": None, "message": MESSAGE_LOGS_CLEARED, "state": self._build_state()}

    def export_error_log(self, start_date: str = "", end_date: str = "") -> dict:
        directory = log_directory_for(self.config)
        if not has_log_files(directory, ERROR_LOG_FILE_NAME):
            return self._error(MESSAGE_NO_ERROR_LOG_FILE)

        window = self._utility_windows.get("settings") or self._window
        if window is None:
            return self._error(MESSAGE_LOG_EXPORT_FAILED)

        default_name = f"pridge-client-errors-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        try:
            selection = window.create_file_dialog(webview.FileDialog.SAVE, save_filename=default_name)
        except Exception as exc:
            logger.warning("Could not open the error log export dialog: %s", exc)
            return self._error(MESSAGE_LOG_EXPORT_FAILED)

        if not selection:
            return self._ok()
        destination = Path(selection[0] if isinstance(selection, (list, tuple)) else selection)

        parsed_start = parse_log_export_date(start_date)
        parsed_end = parse_log_export_date(end_date)
        try:
            wrote_any = export_logs_to(directory, destination, parsed_start, parsed_end, ERROR_LOG_FILE_NAME)
        except OSError as exc:
            logger.warning("Could not export the error log: %s", exc)
            return self._error(MESSAGE_LOG_EXPORT_FAILED)

        if not wrote_any:
            destination.unlink(missing_ok=True)
            return self._error(MESSAGE_NO_LOG_ENTRIES_IN_RANGE)

        logger.info("Error log exported to %s", destination)
        return {"ok": True, "error": None, "message": MESSAGE_ERROR_LOG_EXPORTED, "state": self._build_state()}

    def clear_error_log(self) -> dict:
        if not clear_error_log_files():
            return self._error(MESSAGE_NOTHING_TO_CLEAR_ERRORS)
        self.error_details = []
        logger.info("Error log cleared")
        return {"ok": True, "error": None, "message": MESSAGE_ERROR_LOGS_CLEARED, "state": self._build_state()}

    def choose_log_directory(self) -> dict:
        window = self._utility_windows.get("settings") or self._window
        if window is None:
            return self._error(MESSAGE_LOG_DIRECTORY_FAILED)
        try:
            selection = window.create_file_dialog(webview.FileDialog.FOLDER)
        except Exception as exc:
            logger.warning("Could not open the log directory dialog: %s", exc)
            return self._error(MESSAGE_LOG_DIRECTORY_FAILED)
        if not selection:
            return self._ok()
        directory = selection[0] if isinstance(selection, (list, tuple)) else selection
        return {"ok": True, "error": None, "directory": str(directory), "state": self._build_state()}

    def start_workers(self) -> dict:
        self.save_settings()
        for server in self.config.servers:
            if server.enabled:
                self.start_worker(server)
        self._update_running_status()
        return self._ok()

    def start_server(self, server_id: str) -> dict:
        server = self._server_by_id(server_id)
        if server is None:
            return self._error(MESSAGE_SERVER_NOT_FOUND)
        self.start_worker(server)
        self._update_running_status()
        return self._ok()

    def stop_server(self, server_id: str) -> dict:
        if self._server_by_id(server_id) is None:
            return self._error(MESSAGE_SERVER_NOT_FOUND)
        self.stop_worker(server_id)
        self._update_running_status()
        return self._ok()

    def stop_workers(self) -> dict:
        for server_id in list(self.workers.keys()):
            self.stop_worker(server_id)
        self._update_running_status()
        return self._ok()

    def quit_application(self) -> dict:
        self._quitting = True
        if self._tray:
            self._tray.stop()
        for server_id in list(self.workers.keys()):
            self.stop_worker(server_id)
        for window in list(self._server_windows.values()):
            window.destroy()
        for window in list(self._utility_windows.values()):
            window.destroy()
        if self._window is not None:
            self._window.destroy()
        return self._ok()

    # ------------------------------------------------------------------
    # Window / tray lifecycle
    # ------------------------------------------------------------------
    def start_tray(self) -> None:
        self._tray = TrayController(
            on_show=self.show_window,
            on_quit=self.quit_application,
            icon_path=TRAY_ICON_PATH,
        )
        try:
            self._tray.start()
        except TrayUnavailableError as exc:
            self._tray = None
            logger.warning("%s %s", MESSAGE_TRAY_UNAVAILABLE, exc)

    def hide_window(self) -> None:
        if self._tray is None:
            logger.warning(MESSAGE_TRAY_UNAVAILABLE)
            if self._window is not None:
                self._window.minimize()
            logger.info(MESSAGE_WINDOW_MINIMIZED)
            return
        logger.info(MESSAGE_WINDOW_HIDDEN)
        if self._window is not None:
            self._window.hide()

    def show_window(self) -> None:
        if self._window is not None:
            self._window.show()

    def on_closing(self) -> bool:
        if self._quitting:
            return True
        self.hide_window()
        return False

    def start_worker(self, server: ServerConfig) -> None:
        existing = self.workers.get(server.id)
        if existing and existing.state.running:
            return
        runtime_config = self._runtime_config(server)
        worker = PollingWorker(
            runtime_config,
            self.token_store.get(server.id),
            printer_manager=self.printer_manager,
            archive_store=self.archive_store,
            on_status=lambda status, server_id=server.id, name=server.name: self.events.put(("status", (server_id, name, status))),
            on_job=lambda job, name=server.name: self.events.put(("job", (name, job))),
            on_config=lambda config, server_id=server.id: self.events.put(("config", (server_id, config))),
        )
        self.workers[server.id] = worker
        worker.start()

    def stop_worker(self, server_id: str) -> None:
        worker = self.workers.pop(server_id, None)
        if worker:
            worker.stop()
            worker.join(timeout=5)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ok(self) -> dict:
        return {"ok": True, "error": None, "state": self._build_state()}

    def _error(self, message: str) -> dict:
        return {"ok": False, "error": message, "state": self._build_state()}

    def _build_state(self) -> dict:
        self._drain_events()
        return {
            "app_name": APP_NAME,
            "window_title": WINDOW_TITLE,
            "version": __version__,
            "build_variant": BUILD_VARIANT,
            "build_system": BUILD_SYSTEM,
            "ready_status": self.ready_status,
            "connection_status": self.connection_status,
            "heartbeat_status": self.heartbeat_status,
            "servers": [self._server_public(server) for server in self.config.servers],
            "selected_server_id": self.selected_server_id,
            "printers": [printer.name for printer in self.printers],
            "printer_details": [
                {
                    "name": printer.name,
                    "is_default": printer.is_default,
                    "system_driver_available": printer.system_driver_available,
                    "test_success_count": self.printer_stats.get(printer.name, {}).get("test", {}).get("success", 0),
                    "test_failed_count": self.printer_stats.get(printer.name, {}).get("test", {}).get("failed", 0),
                    "remote_success_count": self.printer_stats.get(printer.name, {}).get("remote", {}).get("success", 0),
                    "remote_failed_count": self.printer_stats.get(printer.name, {}).get("remote", {}).get("failed", 0),
                    "session_test_success_count": self.printer_stats_session.get(printer.name, {}).get("test", {}).get("success", 0),
                    "session_test_failed_count": self.printer_stats_session.get(printer.name, {}).get("test", {}).get("failed", 0),
                    "session_remote_success_count": self.printer_stats_session.get(printer.name, {}).get("remote", {}).get("success", 0),
                    "session_remote_failed_count": self.printer_stats_session.get(printer.name, {}).get("remote", {}).get("failed", 0),
                }
                for printer in self.printers
            ],
            "printer_profiles": {
                name: self._printer_profile_public(profile)
                for name, profile in self.config.printer_profiles.items()
            },
            "selected_printer": self.selected_printer,
            "start_polling_on_launch": self.start_polling_on_launch,
            "start_at_login": self.start_at_login,
            "restart_on_crash": self.restart_on_crash,
            "appearance": {
                "darkness_grade": self.config.appearance.darkness_grade,
            },
            "logging": {
                "file_enabled": self.config.logging.file_enabled,
                "retention_days": self.config.logging.retention_days,
                "directory": self.config.logging.directory,
            },
            "recent_jobs": list(self.recent_jobs),
            "logs": list(self.logs),
            "error_details": list(self.error_details),
        }

    def _server_public(self, server: ServerConfig) -> dict:
        worker = self.workers.get(server.id)
        return {
            "id": server.id,
            "name": server.name,
            "server_url": server.server_url,
            "enabled": server.enabled,
            "polling_interval_seconds": server.polling_interval_seconds,
            "heartbeat_interval_seconds": server.heartbeat_interval_seconds,
            "default_printer": server.default_printer,
            "printer_mappings": [
                {
                    "remote_printer_id": mapping.remote_printer_id,
                    "remote_printer_name": mapping.remote_printer_name,
                    "local_printer_name": mapping.local_printer_name,
                    "has_receipt_design": bool(mapping.raw_template),
                }
                for mapping in server.printer_mappings
            ],
            "has_token": bool(self.token_store.get(server.id)),
            "running": bool(worker and worker.state.running),
            "status": worker.state.status if worker else STATUS_STOPPED,
            "compatibility_warning": worker.state.compatibility_warning if worker else "",
            "last_heartbeat_at": (
                worker.state.last_heartbeat_at.isoformat() if worker and worker.state.last_heartbeat_at else None
            ),
            "last_error": worker.state.last_error if worker else "",
        }

    def _current_config(self) -> ClientConfig:
        return ClientConfig(
            server_url=self.config.servers[0].server_url if self.config.servers else "",
            servers=self.config.servers,
            selected_printer=self.selected_printer,
            printer_profiles=self.config.printer_profiles,
            polling_interval_seconds=self.config.polling_interval_seconds,
            heartbeat_interval_seconds=self.config.heartbeat_interval_seconds,
            start_polling_on_launch=self.start_polling_on_launch,
            start_at_login=self.start_at_login,
            logging=self.config.logging,
            appearance=self.config.appearance,
            dashboard_widgets=self.config.dashboard_widgets,
            printer_stats=self.printer_stats,
        )

    def _runtime_config(self, server: ServerConfig) -> ClientConfig:
        return ClientConfig(
            server_url=server.server_url,
            servers=[server],
            selected_printer=server.default_printer or self.selected_printer,
            printer_profiles=self.config.printer_profiles,
            polling_interval_seconds=server.polling_interval_seconds,
            heartbeat_interval_seconds=server.heartbeat_interval_seconds,
            start_polling_on_launch=self.start_polling_on_launch,
            start_at_login=self.start_at_login,
            logging=self.config.logging,
            appearance=self.config.appearance,
        )

    def _safe_int(self, value: object, default: int, minimum: int, maximum: int | None = None) -> int:
        try:
            parsed = max(int(value), minimum)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            parsed = max(default, minimum)
        return min(parsed, maximum) if maximum is not None else parsed

    def _open_utility_window(
        self,
        key: str,
        title: str,
        page: str,
        width: int,
        height: int,
    ) -> dict:
        existing = self._utility_windows.get(key)
        if existing is not None:
            try:
                existing.show()
                return self._ok()
            except Exception:
                self._utility_windows.pop(key, None)
        window = webview.create_window(
            title,
            url=str(WEBUI_DIR / page),
            js_api=self,
            width=width,
            height=height,
            resizable=False,
            background_color="#111827",
            **_window_effects(),
        )
        self._utility_windows[key] = window
        window.events.closed += lambda window: self._forget_utility_window(key, window)
        configure_utility_window(window)
        return self._ok()

    def _forget_utility_window(self, key: str, window: webview.Window) -> None:
        if self._utility_windows.get(key) is window:
            self._utility_windows.pop(key, None)

    def _broadcast_appearance(self) -> None:
        grade = self.config.appearance.darkness_grade.lower()
        script = f"document.documentElement.dataset.darkness = {json.dumps(grade)};"
        targets = [
            self._window,
            *self._server_windows.values(),
            *(window for key, window in self._utility_windows.items() if key != "settings"),
        ]
        seen: set[int] = set()
        for window in targets:
            if window is None or id(window) in seen:
                continue
            seen.add(id(window))
            try:
                window.evaluate_js(script)
            except Exception as exc:
                logger.debug("Could not apply appearance to an open window: %s", exc)

    def _printer_mappings(self, value: object, existing: Sequence[PrinterMapping] = ()) -> list[PrinterMapping]:
        """Rebuild a server's printer_mappings from the Servers window's edit
        payload, which only ever carries remote_printer_id/local_printer_name/
        remote_printer_name - never Receipt Composer content. Composer fields
        for any mapping that already existed (matched by remote_printer_id)
        are carried over from `existing` so saving unrelated server settings
        (or reassigning a different local printer) never silently wipes a
        mapping's saved header/footer/counters-relevant fields.
        """
        if not isinstance(value, list):
            return []
        existing_by_id = {mapping.remote_printer_id: mapping for mapping in existing}
        mappings: list[PrinterMapping] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, dict):
                continue
            remote_printer_id = str(item.get("remote_printer_id", "")).strip()
            local_printer_name = str(item.get("local_printer_name", "")).strip()
            if not remote_printer_id or not local_printer_name or remote_printer_id in seen:
                continue
            previous = existing_by_id.get(remote_printer_id)
            mappings.append(
                PrinterMapping(
                    remote_printer_id=remote_printer_id,
                    remote_printer_name=str(item.get("remote_printer_name", "")).strip(),
                    local_printer_name=local_printer_name,
                    raw_template=previous.raw_template if previous else "",
                    raw_paper_width_dots=previous.raw_paper_width_dots if previous else 384,
                    raw_chars_per_line=previous.raw_chars_per_line if previous else 32,
                    composer_enabled=previous.composer_enabled if previous else True,
                    receipt_design_migrated=previous.receipt_design_migrated if previous else False,
                )
            )
            seen.add(remote_printer_id)
        return mappings

    def _driver_settings(self, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {
            str(option_id).strip(): str(value_id).strip()
            for option_id, value_id in value.items()
            if str(option_id).strip()
            and isinstance(value_id, (str, int, float, bool))
            and str(value_id).strip()
        }

    def _mapping_public(self, mapping: object) -> dict:
        return {
            "id": mapping.id,
            "name": mapping.name,
            "extensions": list(mapping.extensions),
            "mime_types": list(mapping.mime_types),
            "executable": mapping.executable,
            "arguments": list(mapping.arguments),
            "timeout": mapping.timeout,
            "enabled": mapping.enabled,
            "platform_filter": mapping.platform_filter,
        }

    def _str_list(self, value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [s.strip() for s in value.split(",") if s.strip()]
        return []

    def _safe_float(self, value: object, default: float, minimum: float = 0.0) -> float:
        try:
            parsed = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default
        return max(parsed, minimum)

    def _printer_profile_public(self, profile: PrinterProfile) -> dict[str, object]:
        return {
            "mode": profile.mode,
            "driver_settings": dict(profile.driver_settings),
            "submission_method": profile.submission_method,
            "fit_mode": profile.fit_mode,
        }

    def _server_by_id(self, server_id: str) -> ServerConfig | None:
        return next((server for server in self.config.servers if server.id == server_id), None)

    def _sync_server_endpoints(
        self,
        server_url: str,
        token: str,
        mappings: list[PrinterMapping],
    ) -> str | None:
        try:
            PridgeClient(server_url, token).sync_remote_printers(
                [mapping.remote_printer_id for mapping in mappings]
            )
        except ApiError as exc:
            return str(exc)
        except Exception as exc:
            logger.warning("Endpoint assignment failed: %s", exc)
            return MESSAGE_CONNECTION_FAILED
        return None

    def _install_log_handler(self) -> None:
        handler = QueueLogHandler(self.events)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
        logging.getLogger().addHandler(handler)

        # The error logger has propagate=False (see configure_logging), so
        # this handler only ever sees the detailed entries logged through
        # log_detailed_error() - never anything from the main Logs/Status feed.
        error_handler = QueueLogHandler(self.events, event_name="error_detail")
        error_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
        logging.getLogger(ERROR_LOGGER_NAME).addHandler(error_handler)

    def _drain_events(self) -> None:
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "status":
                _server_id, name, status = payload  # type: ignore[misc]
                self.connection_status = f"{name}: {status}"
                if status == STATUS_RUNNING:
                    self.heartbeat_status = f"{name}: waiting"
                self._update_running_status()
            elif event == "job":
                name, job = payload  # type: ignore[misc]
                if isinstance(job, JobHistoryEntry):
                    line = f"{name} - {job.status}: {job.job_id} {job.detail}".strip()
                    self.recent_jobs.insert(0, line)
                    del self.recent_jobs[MAX_RECENT_JOBS:]
                    if job.printer_name and job.status in ("printed", "failed"):
                        self._bump_printer_stat(job.printer_name, origin="remote", success=job.status == "printed")
            elif event == "config":
                server_id, runtime_config = payload  # type: ignore[misc]
                self._apply_runtime_config(server_id, runtime_config)
            elif event == "log":
                self.logs.append(str(payload))
                if len(self.logs) > MAX_LOG_LINES:
                    self.logs = self.logs[-MAX_LOG_LINES:]
            elif event == "error_detail":
                self.error_details.append(str(payload))
                if len(self.error_details) > MAX_ERROR_LOG_LINES:
                    self.error_details = self.error_details[-MAX_ERROR_LOG_LINES:]

    def _apply_runtime_config(self, server_id: str, runtime_config: ClientConfig) -> None:
        server = self._server_by_id(server_id)
        if server is None:
            return
        server.polling_interval_seconds = runtime_config.polling_interval_seconds
        server.heartbeat_interval_seconds = runtime_config.heartbeat_interval_seconds
        self.config_store.save(self._current_config())

    def _bump_printer_stat(self, printer_name: str, origin: str, success: bool) -> None:
        printer_counts = self.printer_stats.setdefault(printer_name, {})
        counts = printer_counts.setdefault(origin, {"success": 0, "failed": 0})
        counts["success" if success else "failed"] += 1
        self.config_store.save(self._current_config())

        session_counts = self.printer_stats_session.setdefault(printer_name, {}).setdefault(
            origin, {"success": 0, "failed": 0}
        )
        session_counts["success" if success else "failed"] += 1

    def _update_running_status(self) -> None:
        running = sum(1 for worker in self.workers.values() if worker.state.running)
        if running:
            self.ready_status = f"{running} server(s) running"
            self.connection_status = f"{running} server(s) running"
        else:
            self.ready_status = MESSAGE_READY
            self.connection_status = STATUS_STOPPED


def run_gui(gui_smoke_test: bool = False) -> None:
    ensure_webview2_runtime()
    if gui_smoke_test:
        _log_stage("argument detection", "--gui-smoke-test recognized before normal startup")
        _run_gui_smoke_test()
        return
    _run_gui_normal()


def _run_gui_normal() -> None:
    configure_application_identity(APP_NAME)
    api = ClientApi(gui_smoke_test=False)
    menu_actions = [
        (MENU_PLUGINS, api.open_plugins_window),
        (MENU_SERVERS, api.open_servers_window),
        (MENU_PRINTERS, api.open_printers_window),
        (MENU_HISTORY, api.open_history_window),
        (MENU_SETTINGS, api.open_settings_window),
        (MENU_ABOUT, api.open_about_window),
        (MENU_QUIT, api.quit_application),
    ]
    window = webview.create_window(
        WINDOW_TITLE,
        url=str(WEBUI_DIR / "index.html"),
        js_api=api,
        width=1120,
        height=760,
        min_size=(980, 640),
        background_color="#111827",
        menu=create_application_menu(menu_actions),
        **_window_effects(),
    )
    api._window = window
    window.events.closing += api.on_closing
    install_application_menu = configure_application_menu(
        window,
        APP_NAME,
        [title for title, _action in menu_actions],
    )
    api.start_tray()

    if api.config.start_polling_on_launch:
        api.start_workers()

    webview.start(
        install_application_menu,
        debug=False,
        gui=preferred_webview_gui(),
        icon=_webview_start_icon(),
    )


def _validate_smoke_test_resources() -> None:
    """Verify bundled resources and platform GUI bindings before any window
    or webview backend work starts, so a packaging defect is reported as a
    clear import/resource error instead of an unexplained hang later on.
    """
    logger.info(
        "[smoke-test] resource validation: sys.frozen=%s build_variant=%s build_system=%s python=%s",
        bool(getattr(sys, "frozen", False)),
        BUILD_VARIANT,
        BUILD_SYSTEM,
        sys.version.split()[0],
    )
    missing = [path for path in (WEBUI_DIR / "index.html", APP_ICON_PATH, TRAY_ICON_PATH) if not path.exists()]
    if missing:
        raise RuntimeError("Missing packaged resource(s): " + ", ".join(str(path) for path in missing))

    try:
        import pystray  # noqa: F401
        import keyring  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(f"A required packaged dependency could not be imported: {exc}") from exc

    if platform.system() == "Darwin":
        try:
            import AppKit  # noqa: F401
            import Foundation  # noqa: F401
            import objc  # noqa: F401
            import WebKit  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(f"A required macOS GUI framework binding could not be imported: {exc}") from exc


def _smoke_test_watchdog_expired() -> None:
    logger.critical(
        "[smoke-test] final smoke-test exit: watchdog expired after %ss without completing "
        "GUI backend initialization or shutdown",
        SMOKE_TEST_WATCHDOG_SECONDS,
    )
    os._exit(1)


def _shutdown_smoke_test(api: ClientApi) -> None:
    if api._tray is not None:
        api._tray.stop()
        api._tray = None
    for worker in list(api.workers.values()):
        worker.stop()
    for worker in list(api.workers.values()):
        worker.join(timeout=2)
    api.workers.clear()
    for window in list(api._server_windows.values()):
        window.destroy()
    api._server_windows.clear()
    for window in list(api._utility_windows.values()):
        window.destroy()
    api._utility_windows.clear()
    if api._window is not None:
        api._window.destroy()


def _run_gui_smoke_test() -> None:
    _log_stage("resource validation", "checking bundled resources and GUI framework imports")
    _validate_smoke_test_resources()
    _log_stage("resource validation", "complete")

    configure_application_identity(APP_NAME)
    api = ClientApi(gui_smoke_test=True)

    _log_stage("GUI backend selection", "selecting the platform webview backend")
    gui_backend = preferred_webview_gui()
    _log_stage("GUI backend selection", f"selected backend {gui_backend!r}")

    _log_stage("window creation", "registering the smoke-test window")
    window = webview.create_window(
        WINDOW_TITLE,
        url=str(WEBUI_DIR / "index.html"),
        js_api=api,
        width=1120,
        height=760,
        min_size=(980, 640),
        background_color="#111827",
        **_window_effects(),
    )
    api._window = window
    _log_stage("window creation", "smoke-test window registered")

    watchdog = Timer(SMOKE_TEST_WATCHDOG_SECONDS, _smoke_test_watchdog_expired)
    watchdog.daemon = True
    watchdog.start()

    def on_started() -> None:
        # pywebview starts this callback's thread immediately, before the
        # native window is actually created on the main thread, so wait for
        # the window's own "shown" signal instead of assuming readiness -
        # destroying a window mid-construction is unsafe.
        try:
            _log_stage("webview initialization", "GUI backend loop started, waiting for the window to show")
            if not window.events.shown.wait(SMOKE_TEST_WINDOW_SHOWN_TIMEOUT_SECONDS):
                raise RuntimeError(
                    f"The smoke-test window did not finish showing within "
                    f"{SMOKE_TEST_WINDOW_SHOWN_TIMEOUT_SECONDS}s."
                )
            _log_stage("webview initialization", "window shown")
            api.gui_ready.set()

            _log_stage("tray initialization", "skipped during smoke test by design")

            _log_stage("thread shutdown", "stopping tray, workers, and destroying windows")
            _shutdown_smoke_test(api)
            _log_stage("thread shutdown", "complete")
        except BaseException:
            logger.exception("Smoke test failed during GUI backend verification")
            os._exit(1)
        else:
            watchdog.cancel()
            _log_stage("final smoke-test exit", "success, exiting with code 0")
            exit_timer = Timer(SMOKE_TEST_EXIT_DELAY_SECONDS, os._exit, args=(0,))
            exit_timer.daemon = True
            exit_timer.start()

    webview.start(
        on_started,
        debug=False,
        gui=gui_backend,
        icon=_webview_start_icon(),
    )


def _webview_start_icon() -> str | None:
    """Runtime window icon passed to webview.start(), or None to skip it.

    pywebview's Windows backend builds a raw System.Drawing.Icon from this
    path, which requires an actual .ico file and raises an unhandled
    ArgumentException for a PNG (crashing the process with the CLR's
    0xE0434352 exit code). GTK, Qt, and Cocoa all load PNG directly and are
    unaffected. Windows already gets the correct icon baked into the
    executable resource at build time, so there is nothing useful to pass
    here on that platform.
    """
    if platform.system() == "Windows":
        return None
    return str(APP_ICON_PATH)


def _window_effects() -> dict[str, bool]:
    return {"transparent": False, "vibrancy": False}


if __name__ == "__main__":
    run_gui()
