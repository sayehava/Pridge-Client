# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

"""Private local service used by detachable terminal dashboards."""

from __future__ import annotations

import os
import socket
from pathlib import Path

from pridge_client.tui_ipc import default_socket_path, service_available


class TuiServiceAlreadyRunning(RuntimeError):
    pass


class TuiServiceServer:
    def __init__(self, controller, socket_path: Path | None = None) -> None:
        self.controller = controller
        self.socket_path = socket_path or default_socket_path()
        self.listener: socket.socket | None = None

    def open(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if service_available(self.socket_path):
            raise TuiServiceAlreadyRunning("The TUI service is already running")
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o600)
            listener.listen(4)
            listener.settimeout(0.5)
        except BaseException:
            listener.close()
            raise
        self.listener = listener

    def close(self) -> None:
        if self.listener is None:
            return
        self.listener.close()
        self.listener = None
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
