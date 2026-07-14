# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import json
import logging
import queue
import uuid
from logging import Handler, LogRecord
from pathlib import Path
from urllib.parse import urlencode

import webview

from printbridge_client.api import ApiError, PrintBridgeClient
from printbridge_client.autostart import AutoStartError, set_start_at_login
from printbridge_client.build_info import BUILD_SYSTEM, BUILD_VARIANT
from printbridge_client.config import (
    DARKNESS_GRADES,
    PRINT_MODES,
    ClientTokenStore,
    ConfigStore,
    ClientConfig,
    PrinterMapping,
    PrinterProfile,
    ServerConfig,
)
from printbridge_client.models import JobHistoryEntry
from printbridge_client.platform_window import (
    configure_application_identity,
    configure_application_menu,
    configure_utility_window,
    create_application_menu,
    preferred_webview_gui,
)
from printbridge_client.printers import Printer, PrinterError, PrinterManager, validate_driver_settings
from printbridge_client.strings import (
    APP_NAME,
    MESSAGE_READY,
    MESSAGE_CONNECTION_FAILED,
    MESSAGE_CONNECTION_SUCCESS,
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
    MENU_QUIT,
    MENU_SETTINGS,
    STATUS_RUNNING,
    STATUS_STOPPED,
    WINDOW_ADD_SERVER,
    WINDOW_ABOUT,
    WINDOW_EDIT_SERVER,
    WINDOW_SETTINGS,
    WINDOW_TITLE,
)
from printbridge_client.tray import TrayController, TrayUnavailableError
from printbridge_client.version import __version__
from printbridge_client.worker import PollingWorker


logger = logging.getLogger(__name__)

WEBUI_DIR = Path(__file__).resolve().parent / "webui"
ASSET_DIR = WEBUI_DIR / "assets"
APP_ICON_PATH = ASSET_DIR / "Icon.png"
TRAY_ICON_PATH = ASSET_DIR / "IconTray.png"
MAX_RECENT_JOBS = 50
MAX_LOG_LINES = 300


class QueueLogHandler(Handler):
    def __init__(self, events: queue.Queue[tuple[str, object]]) -> None:
        super().__init__()
        self.events = events

    def emit(self, record: LogRecord) -> None:
        self.events.put(("log", self.format(record)))


class ClientApi:
    """Backend controller exposed to the React frontend as ``pywebview.api``."""

    def __init__(
        self,
        config_store: ConfigStore | None = None,
        token_store: ClientTokenStore | None = None,
        printer_manager: PrinterManager | None = None,
    ) -> None:
        self.config_store = config_store or ConfigStore()
        self.token_store = token_store or ClientTokenStore()
        self.printer_manager = printer_manager or PrinterManager()
        self.config = self.config_store.load()
        self.workers: dict[str, PollingWorker] = {}
        self.server_windows: dict[str, webview.Window] = {}
        self.utility_windows: dict[str, webview.Window] = {}
        self.tray: TrayController | None = None
        self.window: webview.Window | None = None
        self._quitting = False
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.printers: list[Printer] = []

        self.selected_server_id = self.config.servers[0].id if self.config.servers else ""
        self.selected_printer = self.config.selected_printer
        self.start_polling_on_launch = self.config.start_polling_on_launch
        self.start_at_login = self.config.start_at_login
        self.connection_status = STATUS_STOPPED
        self.heartbeat_status = STATUS_STOPPED
        self.ready_status = MESSAGE_READY
        self.recent_jobs: list[str] = []
        self.logs: list[str] = ["Pridge Client GUI loaded"]

        self._install_log_handler()
        self.refresh_printers()

    # ------------------------------------------------------------------
    # JS-exposed API (methods below are callable from the frontend as
    # pywebview.api.<name>(...); every mutating call returns the fresh
    # state so the frontend can re-render without a second round trip)
    # ------------------------------------------------------------------
    def get_state(self) -> dict:
        return {"ok": True, "error": None, "state": self._build_state()}

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
        mappings = self._printer_mappings(fields.get("printer_mappings", []))
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
        self.server_windows[window_key] = window
        return self._ok()

    def close_server_window(self, window_key: str) -> dict:
        window = self.server_windows.pop(window_key, None)
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

    def close_utility_window(self, key: str) -> dict:
        window = self.utility_windows.pop(str(key), None)
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
            PrintBridgeClient(server_url, token).authenticate()
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
            client = PrintBridgeClient(server_url, token)
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

    def select_printer(self, name: str) -> dict:
        self.selected_printer = str(name)
        return self._ok()

    def get_printer_capabilities(self, printer_name: str) -> dict:
        name = str(printer_name).strip()
        if name not in {printer.name for printer in self.printers}:
            return self._error("The selected printer is no longer available.")
        profile = self.config.printer_profiles.get(name, PrinterProfile())
        try:
            capabilities = self.printer_manager.get_capabilities(name)
        except PrinterError as exc:
            return self._error(str(exc))

        validated = validate_driver_settings(capabilities, profile.driver_settings)
        if capabilities.system_driver_available and validated != profile.driver_settings:
            profile.driver_settings = validated
            self.config.printer_profiles[name] = profile
            self.config_store.save(self._current_config())
        return {
            "ok": True,
            "error": None,
            "capabilities": capabilities.public(validated),
            "profile": self._printer_profile_public(profile),
            "state": self._build_state(),
        }

    def update_printer_profile(self, printer_name: str, fields: dict) -> dict:
        name = str(printer_name).strip()
        if name not in {printer.name for printer in self.printers}:
            return self._error("The selected printer is no longer available.")
        mode = str(fields.get("mode", "system_driver")).strip().lower()
        if mode not in PRINT_MODES:
            return self._error("The selected printing mode is not supported.")

        existing = self.config.printer_profiles.get(name, PrinterProfile())
        raw_settings = fields.get("driver_settings", existing.driver_settings)
        settings = self._driver_settings(raw_settings)
        capabilities = None
        if mode == "system_driver":
            try:
                capabilities = self.printer_manager.get_capabilities(name)
            except PrinterError as exc:
                return self._error(str(exc))
            if not capabilities.system_driver_available:
                return self._error("The selected printer does not have an available system driver.")
            settings = validate_driver_settings(capabilities, settings)

        profile = PrinterProfile(mode=mode, driver_settings=settings)
        self.config.printer_profiles[name] = profile
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

    def open_printer_driver_settings(self, printer_name: str) -> dict:
        name = str(printer_name).strip()
        if name not in {printer.name for printer in self.printers}:
            return self._error("The selected printer is no longer available.")
        try:
            self.printer_manager.open_driver_settings(name)
        except PrinterError as exc:
            return self._error(str(exc))
        return self.get_printer_capabilities(name)

    def test_printer(self, printer_name: str) -> dict:
        name = str(printer_name).strip()
        if name not in {printer.name for printer in self.printers}:
            return self._error("The selected printer is no longer available.")
        profile = self.config.printer_profiles.get(name, PrinterProfile())
        if profile.mode != "system_driver":
            return self._error(MESSAGE_TEST_PRINT_DRIVER_ONLY)
        try:
            self.printer_manager.print_test_page(
                name,
                mode=profile.mode,
                driver_settings=profile.driver_settings,
            )
        except PrinterError as exc:
            return self._error(str(exc))
        logger.info("Submitted test page to printer %s", name)
        return {
            "ok": True,
            "error": None,
            "message": MESSAGE_TEST_PRINT_SUBMITTED,
            "state": self._build_state(),
        }

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
        darkness_grade = str(fields.get("darkness_grade", self.config.appearance.darkness_grade)).strip().title()
        if darkness_grade in DARKNESS_GRADES:
            self.config.appearance.darkness_grade = darkness_grade
        self._broadcast_appearance()
        self.config = self._current_config()
        self.config_store.save(self.config)
        try:
            set_start_at_login(self.config.start_at_login)
        except AutoStartError as exc:
            logger.warning("Could not update auto-start setting: %s", exc)
        logger.info(MESSAGE_SETTINGS_SAVED)
        return {
            "ok": True,
            "error": None,
            "message": MESSAGE_SETTINGS_SAVED,
            "restart_required": False,
            "state": self._build_state(),
        }

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
        if self.tray:
            self.tray.stop()
        for server_id in list(self.workers.keys()):
            self.stop_worker(server_id)
        for window in list(self.server_windows.values()):
            window.destroy()
        for window in list(self.utility_windows.values()):
            window.destroy()
        if self.window is not None:
            self.window.destroy()
        return self._ok()

    # ------------------------------------------------------------------
    # Window / tray lifecycle
    # ------------------------------------------------------------------
    def start_tray(self) -> None:
        self.tray = TrayController(
            on_show=self.show_window,
            on_quit=self.quit_application,
            icon_path=TRAY_ICON_PATH,
        )
        try:
            self.tray.start()
        except TrayUnavailableError as exc:
            self.tray = None
            logger.warning("%s %s", MESSAGE_TRAY_UNAVAILABLE, exc)

    def hide_window(self) -> None:
        if self.tray is None:
            logger.warning(MESSAGE_TRAY_UNAVAILABLE)
            if self.window is not None:
                self.window.minimize()
            logger.info(MESSAGE_WINDOW_MINIMIZED)
            return
        logger.info(MESSAGE_WINDOW_HIDDEN)
        if self.window is not None:
            self.window.hide()

    def show_window(self) -> None:
        if self.window is not None:
            self.window.show()

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
            "appearance": {
                "darkness_grade": self.config.appearance.darkness_grade,
            },
            "recent_jobs": list(self.recent_jobs),
            "logs": list(self.logs),
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
                }
                for mapping in server.printer_mappings
            ],
            "has_token": bool(self.token_store.get(server.id)),
            "running": bool(worker and worker.state.running),
            "status": worker.state.status if worker else STATUS_STOPPED,
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
        existing = self.utility_windows.get(key)
        if existing is not None:
            try:
                existing.show()
                return self._ok()
            except Exception:
                self.utility_windows.pop(key, None)
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
        self.utility_windows[key] = window
        window.events.closed += lambda window: self._forget_utility_window(key, window)
        configure_utility_window(window)
        return self._ok()

    def _forget_utility_window(self, key: str, window: webview.Window) -> None:
        if self.utility_windows.get(key) is window:
            self.utility_windows.pop(key, None)

    def _broadcast_appearance(self) -> None:
        grade = self.config.appearance.darkness_grade.lower()
        script = f"document.documentElement.dataset.darkness = {json.dumps(grade)};"
        targets = [
            self.window,
            *self.server_windows.values(),
            *(window for key, window in self.utility_windows.items() if key != "settings"),
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

    def _printer_mappings(self, value: object) -> list[PrinterMapping]:
        if not isinstance(value, list):
            return []
        mappings: list[PrinterMapping] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, dict):
                continue
            remote_printer_id = str(item.get("remote_printer_id", "")).strip()
            local_printer_name = str(item.get("local_printer_name", "")).strip()
            if not remote_printer_id or not local_printer_name or remote_printer_id in seen:
                continue
            mappings.append(
                PrinterMapping(
                    remote_printer_id=remote_printer_id,
                    remote_printer_name=str(item.get("remote_printer_name", "")).strip(),
                    local_printer_name=local_printer_name,
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

    def _printer_profile_public(self, profile: PrinterProfile) -> dict[str, object]:
        return {
            "mode": profile.mode,
            "driver_settings": dict(profile.driver_settings),
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
            PrintBridgeClient(server_url, token).sync_remote_printers(
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
            elif event == "config":
                server_id, runtime_config = payload  # type: ignore[misc]
                self._apply_runtime_config(server_id, runtime_config)
            elif event == "log":
                self.logs.append(str(payload))
                if len(self.logs) > MAX_LOG_LINES:
                    self.logs = self.logs[-MAX_LOG_LINES:]

    def _apply_runtime_config(self, server_id: str, runtime_config: ClientConfig) -> None:
        server = self._server_by_id(server_id)
        if server is None:
            return
        server.polling_interval_seconds = runtime_config.polling_interval_seconds
        server.heartbeat_interval_seconds = runtime_config.heartbeat_interval_seconds
        self.config_store.save(self._current_config())

    def _update_running_status(self) -> None:
        running = sum(1 for worker in self.workers.values() if worker.state.running)
        if running:
            self.ready_status = f"{running} server(s) running"
            self.connection_status = f"{running} server(s) running"
        else:
            self.ready_status = MESSAGE_READY
            self.connection_status = STATUS_STOPPED


def run_gui() -> None:
    configure_application_identity(APP_NAME)
    api = ClientApi()
    menu_actions = [
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
    api.window = window
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
        icon=str(APP_ICON_PATH),
    )


def _window_effects() -> dict[str, bool]:
    return {"transparent": False, "vibrancy": False}


if __name__ == "__main__":
    run_gui()
