# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

"""Full-color ANSI terminal (TUI) mode for headless/SSH environments.

TuiController is the real-data equivalent of gui.py's ClientApi, minus
every pywebview/window concern - it owns the same PollingWorker/
PrinterManager/ArchiveStore objects --headless already builds, and turns
them into the plain data structures tui_render.py's pure rendering
functions expect.

Pressing d or Esc, or losing the terminal via SIGHUP, keeps a detached
--headless service running before this view exits. A later --tui command
reattaches to that service. Pressing q or Ctrl-C stops the client.

POSIX only for now (termios/tty-based raw terminal handling has no direct
Windows equivalent) - run_tui refuses to start on Windows with a clear
error rather than crashing partway through terminal setup.
"""

from __future__ import annotations

import logging
import os
import select
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

from pridge_client import tui_render
from pridge_client.archive import ArchiveStore
from pridge_client.autostart import AutoStartError, command, independent_child_environment, set_start_at_login
from pridge_client.build_info import BUILD_SYSTEM, BUILD_VARIANT
from pridge_client.config import ClientConfig, ClientTokenStore, ConfigStore, ServerConfig
from pridge_client.printers import PrinterError, PrinterManager
from pridge_client.terminal_command import (
    DEFAULT_COMMAND_NAME,
    TerminalCommandError,
    install_terminal_command,
    installed_terminal_command,
)
from pridge_client.tui_ipc import RemoteTuiController, service_available
from pridge_client.version import __version__
from pridge_client.worker import PollingWorker


logger = logging.getLogger(__name__)

SPLASH_TIMEOUT_SECONDS = 3.0
REFRESH_INTERVAL_SECONDS = 1.0
JOB_HISTORY_BUCKETS = 12
RECENT_JOBS_SHOWN = 6
DASHBOARD_JOBS_SCANNED = 500

SETTING_ITEMS: list[tuple[str, str]] = [
    ("start_polling_on_launch", "Start polling on launch"),
    ("start_at_login", "Start at login"),
    ("restart_on_crash", "Restart automatically if the app crashes"),
    ("web_gui_enabled", "Browser GUI"),
]


def _runtime_config(config: ClientConfig, server: ServerConfig) -> ClientConfig:
    return ClientConfig(
        server_url=server.server_url,
        servers=[server],
        selected_printer=config.selected_printer,
        printer_profiles=config.printer_profiles,
        polling_interval_seconds=server.polling_interval_seconds,
        heartbeat_interval_seconds=server.heartbeat_interval_seconds,
        logging=config.logging,
        archive=config.archive,
    )


def _format_heartbeat(when: datetime | None) -> str:
    if when is None:
        return "—"
    seconds = int((datetime.now(timezone.utc) - when).total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    return f"{seconds // 3600}h ago"


class TuiController:
    def __init__(
        self,
        config_store: ConfigStore | None = None,
        token_store: ClientTokenStore | None = None,
        printer_manager: PrinterManager | None = None,
        archive_store: ArchiveStore | None = None,
    ) -> None:
        self.config_store = config_store or ConfigStore()
        self.token_store = token_store or ClientTokenStore()
        self.printer_manager = printer_manager or PrinterManager()
        self.archive_store = archive_store or ArchiveStore()
        self.config = self.config_store.load()
        self.workers: dict[str, PollingWorker] = {}

    # ------------------------------------------------------------------
    # Worker lifecycle - same shape as gui.py's start_worker/stop_worker
    # ------------------------------------------------------------------
    def start(self) -> None:
        for server in self.config.servers:
            if server.enabled:
                self.start_worker(server)

    def start_worker(self, server: ServerConfig) -> None:
        existing = self.workers.get(server.id)
        if existing and existing.state.running:
            return
        worker = PollingWorker(
            _runtime_config(self.config, server),
            self.token_store.get(server.id),
            printer_manager=self.printer_manager,
            archive_store=self.archive_store,
        )
        self.workers[server.id] = worker
        worker.start()

    def stop_worker(self, server_id: str) -> None:
        worker = self.workers.pop(server_id, None)
        if worker:
            worker.stop()
            worker.join(timeout=5)

    def stop_all(self) -> None:
        for server_id in list(self.workers.keys()):
            self.stop_worker(server_id)

    def toggle_server(self, index: int) -> None:
        if index < 0 or index >= len(self.config.servers):
            return
        server = self.config.servers[index]
        worker = self.workers.get(server.id)
        if worker and worker.state.running:
            self.stop_worker(server.id)
        else:
            self.start_worker(server)

    # ------------------------------------------------------------------
    # Plugins
    # ------------------------------------------------------------------
    def _plugin_entries(self):
        return sorted(self.printer_manager.renderer_registry.all_entries(), key=lambda entry: entry.priority)

    def plugins_data(self) -> list[dict]:
        return [
            {
                "plugin_id": entry.plugin.plugin_id,
                "name": entry.plugin.display_name,
                "category": entry.category,
                "enabled": entry.enabled,
                "core": entry.is_builtin,
            }
            for entry in self._plugin_entries()
        ]

    def toggle_plugin(self, index: int) -> None:
        entries = self._plugin_entries()
        if index < 0 or index >= len(entries):
            return
        entry = entries[index]
        self.printer_manager.renderer_registry.set_enabled(entry.plugin.plugin_id, not entry.enabled)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def settings_data(self) -> list[dict]:
        settings = [{"label": label, "enabled": bool(getattr(self.config, key))} for key, label in SETTING_ITEMS]
        command_name = installed_terminal_command()
        settings.append(
            {
                "label": "Terminal command",
                "enabled": bool(command_name),
                "detail": command_name or "not installed",
                "action": "install_terminal_command",
            }
        )
        return settings

    def toggle_setting(self, index: int) -> str:
        if index < 0 or index >= len(SETTING_ITEMS):
            return ""
        key, _label = SETTING_ITEMS[index]
        setattr(self.config, key, not getattr(self.config, key))
        message = ""
        if key == "start_at_login":
            try:
                set_start_at_login(self.config.start_at_login)
            except AutoStartError as exc:
                message = str(exc)
        self.config_store.save(self.config)
        return message

    # ------------------------------------------------------------------
    # Servers
    # ------------------------------------------------------------------
    def servers_data(self) -> list[dict]:
        out = []
        for server in self.config.servers:
            worker = self.workers.get(server.id)
            state = worker.state if worker else None
            printers = {mapping.local_printer_name for mapping in server.printer_mappings}
            if server.default_printer:
                printers.add(server.default_printer)
            out.append(
                {
                    "name": server.name,
                    "url": server.server_url,
                    "status": state.status if state else "Stopped",
                    "printers": len(printers),
                    "heartbeat": _format_heartbeat(state.last_heartbeat_at) if state else "—",
                    "last_error": state.last_error if state else "",
                }
            )
        return out

    # ------------------------------------------------------------------
    # Printers
    # ------------------------------------------------------------------
    def _list_printers(self):
        try:
            return self.printer_manager.list_printers()
        except PrinterError as exc:
            logger.warning("Printer refresh failed: %s", exc)
            return []

    def printers_data(self) -> list[dict]:
        out = []
        for printer in self._list_printers():
            profile = self.config.printer_profiles.get(printer.name)
            mode = "RAW" if profile and profile.mode == "raw" else "System Driver"
            remote_stats = self.config.printer_stats.get(printer.name, {}).get("remote", {})
            out.append(
                {
                    "name": printer.name,
                    "mode": mode,
                    "used": printer.name in self.config.printer_stats,
                    "success_count": remote_stats.get("success", 0),
                    "failed_count": remote_stats.get("failed", 0),
                }
            )
        return out

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    def dashboard_data(self) -> dict:
        jobs = self.archive_store.list_jobs(limit=DASHBOARD_JOBS_SCANNED)
        now = datetime.now(timezone.utc)
        buckets = [0.0] * JOB_HISTORY_BUCKETS
        for job in jobs:
            age_hours = (now - job.created_at).total_seconds() / 3600
            if 0 <= age_hours < JOB_HISTORY_BUCKETS:
                buckets[JOB_HISTORY_BUCKETS - 1 - int(age_hours)] += 1
        printed_today = sum(1 for job in jobs if job.status == "printed" and job.created_at.date() == now.date())
        recent = [
            {
                "time": job.created_at.astimezone().strftime("%H:%M:%S"),
                "status": job.status,
                "printer_name": job.printer_name,
                "label": job.filename or job.job_id,
            }
            for job in jobs[:RECENT_JOBS_SHOWN]
        ]
        return {
            "printer_count": len(self._list_printers()),
            "printed_today": printed_today,
            "job_history": buckets,
            "recent_jobs": recent,
        }

    def about_data(self) -> dict:
        return {"version": __version__, "build_variant": BUILD_VARIANT, "build_system": BUILD_SYSTEM}


def _list_length(controller: TuiController, screen_name: str) -> int:
    if screen_name == "Servers":
        return len(controller.servers_data())
    if screen_name == "Printers":
        return len(controller.printers_data())
    if screen_name == "Plugins":
        return len(controller.plugins_data())
    if screen_name == "Settings":
        return len(controller.settings_data())
    return 0


def _draw(controller: TuiController, screen_name: str, selection: dict, width: int, height: int, message: str) -> None:
    # A transient error gathering any one screen's data (e.g. the OS print
    # service being briefly unreachable) must never crash the whole
    # interactive session - same "never let this kill the loop" rule
    # worker.py's own polling loop already follows.
    try:
        frame = tui_render.render_frame(
            screen_name,
            width,
            height,
            __version__,
            controller.dashboard_data(),
            controller.servers_data(),
            controller.printers_data(),
            controller.plugins_data(),
            controller.settings_data(),
            BUILD_VARIANT,
            BUILD_SYSTEM,
            selection,
            message=message,
        )
    except Exception as exc:  # noqa: BLE001 - rendering must never crash the session
        logger.warning("TUI render failed: %s", exc)
        frame = tui_render.render_frame(
            screen_name,
            width,
            height,
            __version__,
            {"printer_count": 0, "printed_today": 0, "job_history": [], "recent_jobs": []},
            [],
            [],
            [],
            [],
            BUILD_VARIANT,
            BUILD_SYSTEM,
            selection,
            message=f"{tui_render.DANGER}A data source is temporarily unavailable{tui_render.RESET}",
        )
    sys.stdout.write(frame)
    sys.stdout.flush()


def _start_background_service() -> bool:
    """Start a detached headless instance before the TUI process exits."""
    child_command = command("--headless")
    try:
        with open(os.devnull, "rb") as devnull_in, open(os.devnull, "ab") as devnull_out:
            process = subprocess.Popen(
                child_command,
                start_new_session=True,
                stdin=devnull_in,
                stdout=devnull_out,
                stderr=devnull_out,
                env=independent_child_environment(),
            )
    except OSError as exc:
        logger.warning("Could not spawn a detached headless process: %s", exc)
        return False
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and process.poll() is None:
        if service_available():
            return True
        time.sleep(0.05)
    logger.warning("The detached headless service did not become ready")
    if process.poll() is None:
        process.terminate()
    return False


def _exit_action_for_key(key: str | None) -> str | None:
    if key == "q":
        return "quit"
    if key in ("d", "ESC"):
        return "detach"
    return None


def _finish_controller(controller, action: str | None, attached_to_service: bool) -> None:
    if attached_to_service:
        if action == "quit":
            controller.shutdown()
    else:
        controller.stop_all()


def _prompt_for_terminal_command(fd: int, old_settings) -> str:
    import termios
    import tty

    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    sys.stdout.write(tui_render.SHOW_CURSOR + tui_render.RESET + tui_render.CLEAR_SCREEN)
    sys.stdout.flush()
    try:
        name = input(f"Terminal command name [{DEFAULT_COMMAND_NAME}]: ").strip() or DEFAULT_COMMAND_NAME
        return install_terminal_command(name)
    except (EOFError, OSError, TerminalCommandError) as exc:
        return f"Terminal command was not installed: {exc}"
    finally:
        tty.setcbreak(fd)
        sys.stdout.write(tui_render.HIDE_CURSOR)


def _read_key(fd: int) -> str | None:
    """Reads one logical key, resolving arrow-key escape sequences.

    Arrow keys send ESC '[' <letter>, three bytes read one at a time - a
    naive read of just the ESC byte mistakes them for the standalone Escape
    key and quits the view. A short peek after ESC tells the two apart.

    Reads go through os.read() on the raw fd, not sys.stdin.read(): the
    latter is a buffered TextIOWrapper that can slurp all 3 bytes of an
    arrow sequence from the kernel in one syscall and hold the extra 2 in
    its own internal buffer, invisible to a follow-up select() on the fd -
    which would make every arrow key look like a bare Escape.
    """
    ready, _, _ = select.select([fd], [], [], REFRESH_INTERVAL_SECONDS)
    if not ready:
        return None
    ch = os.read(fd, 1).decode(errors="replace")
    if ch != "\x1b":
        return ch
    ready2, _, _ = select.select([fd], [], [], 0.05)
    if not ready2:
        return "ESC"
    ch2 = os.read(fd, 1).decode(errors="replace")
    if ch2 != "[":
        return "ESC"
    ready3, _, _ = select.select([fd], [], [], 0.05)
    if not ready3:
        return "ESC"
    ch3 = os.read(fd, 1).decode(errors="replace")
    return {"A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT"}.get(ch3)


def run_tui(controller: TuiController | RemoteTuiController, attached_to_service: bool = False) -> None:
    if sys.platform == "win32":
        raise RuntimeError(
            "TUI mode requires a POSIX terminal (Linux/macOS) and is not yet available on Windows."
        )

    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    resized = {"flag": True}
    exit_action = {"value": None}
    background_started = False

    def request_detach(_signum=None, _frame=None) -> None:
        exit_action["value"] = "detach"

    def request_quit(_signum=None, _frame=None) -> None:
        exit_action["value"] = "quit"

    def on_resize(_signum, _frame) -> None:
        resized["flag"] = True

    signal.signal(signal.SIGWINCH, on_resize)
    signal.signal(signal.SIGINT, request_quit)
    signal.signal(signal.SIGHUP, request_detach)

    screen_name = "Dashboard"
    selection = {"Servers": 0, "Printers": 0, "Plugins": 0, "Settings": 0}
    message = "Attached to the running print service." if attached_to_service else ""

    try:
        tty.setcbreak(fd)
        sys.stdout.write(tui_render.HIDE_CURSOR)

        width, _ = shutil.get_terminal_size(fallback=(80, 24))
        sys.stdout.write(tui_render.render_splash(max(40, width), __version__))
        sys.stdout.flush()
        ready, _, _ = select.select([fd], [], [], SPLASH_TIMEOUT_SECONDS)
        if ready:
            os.read(fd, 1)

        last_render = 0.0
        while exit_action["value"] is None:
            width, height = shutil.get_terminal_size(fallback=(80, 24))
            now = time.monotonic()
            if resized["flag"] or now - last_render >= REFRESH_INTERVAL_SECONDS:
                resized["flag"] = False
                last_render = now
                _draw(controller, screen_name, selection, width, height, message)
                message = ""

            key = _read_key(fd)
            if exit_action["value"] is not None:
                break
            if key is None:
                continue
            requested_action = _exit_action_for_key(key)
            if requested_action == "quit":
                exit_action["value"] = "quit"
                break
            if requested_action == "detach":
                background_started = attached_to_service or _start_background_service()
                if background_started:
                    exit_action["value"] = "detach"
                    break
                message = "Could not start the background service. The client is still running."
                continue
            if key in "123456":
                screen_name = tui_render.SCREENS[int(key) - 1]
            elif key in ("\r", "\n", "DOWN") and _list_length(controller, screen_name) > 0:
                count = _list_length(controller, screen_name)
                selection[screen_name] = (selection[screen_name] + 1) % count
            elif key in ("\x7f", "\x08", "UP") and _list_length(controller, screen_name) > 0:
                count = _list_length(controller, screen_name)
                selection[screen_name] = (selection[screen_name] - 1) % count
            elif key == " " and screen_name == "Servers":
                controller.toggle_server(selection["Servers"])
            elif key == " " and screen_name == "Plugins":
                controller.toggle_plugin(selection["Plugins"])
            elif key == " " and screen_name == "Settings":
                settings = controller.settings_data()
                selected_setting = settings[selection["Settings"]]
                if selected_setting.get("action") == "install_terminal_command":
                    message = _prompt_for_terminal_command(fd, old_settings)
                    resized["flag"] = True
                else:
                    message = controller.toggle_setting(selection["Settings"])
            else:
                continue

            width, height = shutil.get_terminal_size(fallback=(80, 24))
            _draw(controller, screen_name, selection, width, height, message)
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            sys.stdout.write(tui_render.SHOW_CURSOR + tui_render.RESET + tui_render.CLEAR_SCREEN)
            sys.stdout.flush()
        except OSError:
            logger.debug("The terminal closed before its TUI state could be restored")
        if exit_action["value"] == "detach" and not background_started and not attached_to_service:
            background_started = _start_background_service()
        _finish_controller(controller, exit_action["value"], attached_to_service)
        if exit_action["value"] == "detach" and background_started:
            print(f"{tui_render.DIM_MUTED}Pridge Client is running in the background.{tui_render.RESET}")
        else:
            print(f"{tui_render.DIM_MUTED}Pridge Client stopped.{tui_render.RESET}")
