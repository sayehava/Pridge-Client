from __future__ import annotations

import logging
import queue
import uuid
from logging import Handler, LogRecord
from pathlib import Path
from urllib.parse import urlencode

import webview

from printbridge_endpoint.api import ApiError, PrintBridgeClient
from printbridge_endpoint.autostart import AutoStartError, set_start_at_login
from printbridge_endpoint.config import ClientTokenStore, ConfigStore, EndpointConfig, ServerConfig
from printbridge_endpoint.models import JobHistoryEntry
from printbridge_endpoint.printers import Printer, PrinterError, PrinterManager
from printbridge_endpoint.strings import (
    APP_NAME,
    MESSAGE_READY,
    MESSAGE_CONNECTION_FAILED,
    MESSAGE_CONNECTION_SUCCESS,
    MESSAGE_SERVER_NOT_FOUND,
    MESSAGE_SERVER_REQUIRED,
    MESSAGE_SETTINGS_SAVED,
    MESSAGE_TOKEN_REQUIRED,
    MESSAGE_TRAY_UNAVAILABLE,
    MESSAGE_WINDOW_HIDDEN,
    MESSAGE_WINDOW_MINIMIZED,
    STATUS_RUNNING,
    STATUS_STOPPED,
    WINDOW_ADD_SERVER,
    WINDOW_EDIT_SERVER,
    WINDOW_TITLE,
)
from printbridge_endpoint.tray import TrayController, TrayUnavailableError
from printbridge_endpoint.version import __version__
from printbridge_endpoint.worker import PollingWorker


logger = logging.getLogger(__name__)

WEBUI_DIR = Path(__file__).resolve().parent / "webui"
MAX_RECENT_JOBS = 50
MAX_LOG_LINES = 300


class QueueLogHandler(Handler):
    def __init__(self, events: queue.Queue[tuple[str, object]]) -> None:
        super().__init__()
        self.events = events

    def emit(self, record: LogRecord) -> None:
        self.events.put(("log", self.format(record)))


class EndpointApi:
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
        self.tray: TrayController | None = None
        self.window: webview.Window | None = None
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
        self.logs: list[str] = ["PrintBridge Endpoint GUI loaded"]

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
        new_server = ServerConfig(
            id=uuid.uuid4().hex,
            name=name,
            server_url=server_url,
            enabled=bool(server.get("enabled", True)),
            polling_interval_seconds=self._safe_int(server.get("polling_interval_seconds"), 5, minimum=1),
            heartbeat_interval_seconds=self._safe_int(server.get("heartbeat_interval_seconds"), 30, minimum=5),
        )
        self.config.servers.append(new_server)
        token = str(server.get("token", "")).strip()
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
        server.name = name
        server.server_url = server_url
        server.enabled = bool(fields.get("enabled", server.enabled))
        server.polling_interval_seconds = self._safe_int(
            fields.get("polling_interval_seconds"), server.polling_interval_seconds, minimum=1
        )
        server.heartbeat_interval_seconds = self._safe_int(
            fields.get("heartbeat_interval_seconds"), server.heartbeat_interval_seconds, minimum=5
        )
        token = str(fields.get("token", "")).strip()
        if token:
            self.token_store.set(token, server.id)
        self.config_store.save(self._current_config())
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

        window_key = uuid.uuid4().hex
        query = urlencode({"server_id": server_id, "window_key": window_key})
        title = WINDOW_EDIT_SERVER if server_id else WINDOW_ADD_SERVER
        window = webview.create_window(
            title,
            url=f"{WEBUI_DIR / 'server.html'}?{query}",
            js_api=self,
            width=520,
            height=680,
            min_size=(460, 620),
            background_color="#15171c",
        )
        self.server_windows[window_key] = window
        return self._ok()

    def close_server_window(self, window_key: str) -> dict:
        window = self.server_windows.pop(window_key, None)
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

    def start_workers(self) -> dict:
        self.save_settings()
        for server in self.config.servers:
            if server.enabled:
                self.start_worker(server)
        self._update_running_status()
        return self._ok()

    def stop_workers(self) -> dict:
        for server_id in list(self.workers.keys()):
            self.stop_worker(server_id)
        self._update_running_status()
        return self._ok()

    def quit_application(self) -> dict:
        if self.tray:
            self.tray.stop()
        for server_id in list(self.workers.keys()):
            self.stop_worker(server_id)
        if self.window is not None:
            self.window.destroy()
        return self._ok()

    # ------------------------------------------------------------------
    # Window / tray lifecycle
    # ------------------------------------------------------------------
    def start_tray(self) -> None:
        self.tray = TrayController(on_show=self.show_window, on_quit=self.quit_application)
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
            "ready_status": self.ready_status,
            "connection_status": self.connection_status,
            "heartbeat_status": self.heartbeat_status,
            "servers": [self._server_public(server) for server in self.config.servers],
            "selected_server_id": self.selected_server_id,
            "printers": [printer.name for printer in self.printers],
            "selected_printer": self.selected_printer,
            "start_polling_on_launch": self.start_polling_on_launch,
            "start_at_login": self.start_at_login,
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
            "has_token": bool(self.token_store.get(server.id)),
            "running": bool(worker and worker.state.running),
            "status": worker.state.status if worker else STATUS_STOPPED,
        }

    def _current_config(self) -> EndpointConfig:
        return EndpointConfig(
            server_url=self.config.servers[0].server_url if self.config.servers else "",
            servers=self.config.servers,
            selected_printer=self.selected_printer,
            polling_interval_seconds=self.config.polling_interval_seconds,
            heartbeat_interval_seconds=self.config.heartbeat_interval_seconds,
            start_polling_on_launch=self.start_polling_on_launch,
            start_at_login=self.start_at_login,
            logging=self.config.logging,
        )

    def _runtime_config(self, server: ServerConfig) -> EndpointConfig:
        return EndpointConfig(
            server_url=server.server_url,
            servers=[server],
            selected_printer=self.selected_printer,
            polling_interval_seconds=server.polling_interval_seconds,
            heartbeat_interval_seconds=server.heartbeat_interval_seconds,
            start_polling_on_launch=self.start_polling_on_launch,
            start_at_login=self.start_at_login,
            logging=self.config.logging,
        )

    def _safe_int(self, value: object, default: int, minimum: int) -> int:
        try:
            return max(int(value), minimum)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return max(default, minimum)

    def _server_by_id(self, server_id: str) -> ServerConfig | None:
        return next((server for server in self.config.servers if server.id == server_id), None)

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

    def _apply_runtime_config(self, server_id: str, runtime_config: EndpointConfig) -> None:
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
    api = EndpointApi()
    window = webview.create_window(
        WINDOW_TITLE,
        url=str(WEBUI_DIR / "index.html"),
        js_api=api,
        width=1120,
        height=760,
        min_size=(980, 640),
        background_color="#15171c",
    )
    api.window = window
    window.events.closing += api.on_closing
    api.start_tray()

    if api.config.start_polling_on_launch:
        api.start_workers()

    webview.start(debug=False)


if __name__ == "__main__":
    run_gui()
