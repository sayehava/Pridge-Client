# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

"""Full-color ANSI terminal (TUI) mode for headless/SSH environments.

TuiController is the real-data equivalent of gui.py's ClientApi, minus
every pywebview/window concern - it owns the same PollingWorker/
PrinterManager/ArchiveStore objects --headless already builds, and turns
them into the plain data structures tui_render.py's pure rendering
functions expect.

Exiting the view (q/Esc, Ctrl-C, or losing the terminal via SIGHUP) does
not stop the print service: run_tui spawns a brand-new detached --headless
child process and stops this process's own in-process workers, so the
service keeps running independently of the terminal session. There is no
live reattach yet - running --tui again later starts a separate instance,
not a reconnect to the detached one.

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
from pridge_client.autostart import AutoStartError, command, set_start_at_login
from pridge_client.build_info import BUILD_SYSTEM, BUILD_VARIANT
from pridge_client.config import ClientConfig, ClientTokenStore, ConfigStore, ServerConfig
from pridge_client.printers import PrinterError, PrinterManager
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
        return [{"label": label, "enabled": bool(getattr(self.config, key))} for key, label in SETTING_ITEMS]

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


