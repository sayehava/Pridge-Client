# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

"""Private local service used by detachable terminal dashboards."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from threading import Event

from pridge_client.tui_ipc import default_socket_path, receive_line, service_available


ALLOWED_METHODS = frozenset(
    {
        "dashboard_data",
        "servers_data",
        "printers_data",
        "plugins_data",
        "settings_data",
        "toggle_server",
        "toggle_plugin",
        "toggle_setting",
    }
)


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

    def serve(self, stop_event: Event) -> None:
        if self.listener is None:
            raise RuntimeError("The TUI service socket is not open")
        try:
            while not stop_event.is_set():
                try:
                    connection, _ = self.listener.accept()
                except socket.timeout:
                    continue
                with connection:
                    self._handle(connection, stop_event)
        finally:
            self.close()

    def _handle(self, connection: socket.socket, stop_event: Event) -> None:
        try:
            request = json.loads(receive_line(connection).decode("utf-8"))
            method = str(request.get("method", ""))
            args = request.get("args", [])
            if method == "ping":
                result = "pong"
            elif method == "shutdown":
                result = None
                stop_event.set()
            elif method in ALLOWED_METHODS and isinstance(args, list):
                result = getattr(self.controller, method)(*args)
            else:
                raise ValueError("Unsupported TUI service request")
            response = {"ok": True, "result": result}
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        connection.sendall(json.dumps(response).encode("utf-8") + b"\n")
