# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


WEBUI_DIR = Path(__file__).resolve().parent / "webui"
BRIDGE_TAG = b'<script src="/web-bridge.js"></script>'
logger = logging.getLogger(__name__)


class BrowserGuiServer:
    def __init__(self, api: object, port: int = 8765) -> None:
        self.api = api
        self.requested_port = port
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        if self.httpd is None:
            return ""
        return f"http://127.0.0.1:{self.httpd.server_port}"

    def start(self) -> str:
        handler = self._handler()
        try:
            self.httpd = ThreadingHTTPServer(("127.0.0.1", self.requested_port), handler)
        except OSError:
            self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="browser-gui", daemon=True)
        self.thread.start()
        logger.info("Browser GUI available at %s", self.url)
        return self.url

    def close(self) -> None:
        if self.httpd is None:
            return
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)
        self.httpd = None
        self.thread = None

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                requested = unquote(urlsplit(self.path).path).lstrip("/") or "index.html"
                target = (WEBUI_DIR / requested).resolve()
                if WEBUI_DIR not in target.parents or not target.is_file():
                    self.send_error(404)
                    return
                payload = target.read_bytes()
                if target.suffix == ".html":
                    payload = payload.replace(b"</head>", BRIDGE_TAG + b"</head>", 1)
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: object) -> None:
                logger.debug("Browser GUI: " + format, *args)

        Handler.owner = owner  # type: ignore[attr-defined]
        return Handler
