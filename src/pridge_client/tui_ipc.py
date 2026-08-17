# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

"""Client side of the private local TUI service protocol."""

from __future__ import annotations

import json
import socket
from pathlib import Path

from pridge_client.config import default_config_dir


SOCKET_FILE_NAME = "tui-service.sock"
REQUEST_LIMIT = 1024 * 1024


class TuiServiceUnavailable(ConnectionError):
    pass


def default_socket_path() -> Path:
    return default_config_dir() / SOCKET_FILE_NAME


def request(method: str, *args, socket_path: Path | None = None):
    path = socket_path or default_socket_path()
    payload = json.dumps({"method": method, "args": args}).encode("utf-8") + b"\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            connection.connect(str(path))
            connection.sendall(payload)
            response = receive_line(connection)
    except (OSError, ValueError) as exc:
        raise TuiServiceUnavailable(str(exc)) from exc
    decoded = json.loads(response.decode("utf-8"))
    if not decoded.get("ok"):
        raise TuiServiceUnavailable(str(decoded.get("error", "TUI service request failed")))
    return decoded.get("result")


def receive_line(connection: socket.socket) -> bytes:
    data = bytearray()
    while len(data) < REQUEST_LIMIT:
        chunk = connection.recv(min(65536, REQUEST_LIMIT - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if b"\n" in chunk:
            return bytes(data).split(b"\n", 1)[0]
    raise TuiServiceUnavailable("The TUI service returned an incomplete response")


def service_available(socket_path: Path | None = None) -> bool:
    try:
        return request("ping", socket_path=socket_path) == "pong"
    except TuiServiceUnavailable:
        return False


class RemoteTuiController:
    """TuiController-compatible proxy for an existing headless service."""

    def __init__(self, socket_path: Path | None = None) -> None:
        self.socket_path = socket_path or default_socket_path()

    @classmethod
    def connect(cls, socket_path: Path | None = None) -> "RemoteTuiController | None":
        controller = cls(socket_path)
        return controller if service_available(controller.socket_path) else None

    def _call(self, method: str, *args):
        return request(method, *args, socket_path=self.socket_path)

    def dashboard_data(self) -> dict:
        return self._call("dashboard_data")

    def servers_data(self) -> list[dict]:
        return self._call("servers_data")

    def printers_data(self) -> list[dict]:
        return self._call("printers_data")

    def plugins_data(self) -> list[dict]:
        return self._call("plugins_data")

    def settings_data(self) -> list[dict]:
        return self._call("settings_data")

    def toggle_server(self, index: int) -> None:
        self._call("toggle_server", index)

    def toggle_plugin(self, index: int) -> None:
        self._call("toggle_plugin", index)

    def toggle_setting(self, index: int) -> str:
        return self._call("toggle_setting", index)

    def shutdown(self) -> None:
        self._call("shutdown")
