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
