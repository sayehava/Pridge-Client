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

