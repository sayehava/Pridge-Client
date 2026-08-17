# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import json
import logging
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


WEBUI_DIR = Path(__file__).resolve().parent / "webui"
BRIDGE_TAG = b'<script src="/web-bridge.js"></script>'
logger = logging.getLogger(__name__)
RPC_METHODS = frozenset(
    """get_state notify_gui_ready add_server update_server remove_server select_server
    test_server_connection discover_remote_printers refresh_printers select_printer
    get_printer_capabilities update_printer_profile open_printer_driver_settings test_printer
    get_dashboard_layout add_dashboard_widget remove_dashboard_widget reorder_dashboard_widget
    update_dashboard_widget_config update_application_settings get_renderer_plugins
    set_renderer_plugin_enabled remove_plugin rescan_plugins get_app_mappings add_app_mapping
    update_app_mapping remove_app_mapping get_receipt_images add_receipt_image remove_receipt_image
    get_mapping_receipt_design update_mapping_receipt_design clear_mapping_receipt_design
    test_mapping_receipt_design get_receipt_counters add_receipt_counter reset_receipt_counter
    remove_receipt_counter preview_receipt_template reorder_renderer_plugin clear_logs
    clear_error_log start_workers start_server stop_server stop_workers quit_application
    list_archived_jobs preview_archived_job reprint_job clear_archive get_pending_receipt_selection""".split()
)


class BrowserGuiServer:
    def __init__(self, api: object, port: int = 8765, on_stop: object | None = None) -> None:
        self.api = api
        self.requested_port = port
        self.on_stop = on_stop
        self.rpc_lock = threading.Lock()
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
                if not self._trusted_host():
                    self.send_error(403)
                    return
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
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:
                if self.path != "/api/rpc" or not self._trusted_origin():
                    self.send_error(403)
                    return
                try:
                    if self.headers.get_content_type() != "application/json":
                        raise ValueError("JSON content is required")
                    size = int(self.headers.get("Content-Length", "0"))
                    if size < 1 or size > 2_000_000:
                        raise ValueError("Invalid request size")
                    request = json.loads(self.rfile.read(size))
                    method = request.get("method") if isinstance(request, dict) else None
                    args = request.get("args", []) if isinstance(request, dict) else []
                    if method not in RPC_METHODS or not isinstance(args, list):
                        raise ValueError("Unsupported API request")
                    with owner.rpc_lock:
                        result = getattr(owner.api, method)(*args)
                    self._json_response(200, result)
                    if method == "quit_application" and callable(owner.on_stop):
                        owner.on_stop()
                except (AttributeError, TypeError, ValueError) as exc:
                    self._json_response(400, {"ok": False, "message": str(exc)})
                except Exception:
                    logger.exception("Browser GUI API request failed")
                    self._json_response(500, {"ok": False, "message": "The request failed."})

            def _trusted_host(self) -> bool:
                host = self.headers.get("Host", "")
                port = owner.httpd.server_port if owner.httpd else 0
                return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

            def _trusted_origin(self) -> bool:
                host = self.headers.get("Host", "")
                return self._trusted_host() and self.headers.get("Origin") == f"http://{host}"

            def _json_response(self, status: int, result: object) -> None:
                payload = json.dumps(result).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: object) -> None:
                logger.debug("Browser GUI: " + format, *args)

        Handler.owner = owner  # type: ignore[attr-defined]
        return Handler
