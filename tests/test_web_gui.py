# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import json
import socket
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pridge_client.web_gui import BrowserGuiServer


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_state(self) -> dict:
        self.calls.append(("get_state", None))
        return {"ok": True, "state": {"status": "ready"}}

    def update_application_settings(self, fields: dict) -> dict:
        self.calls.append(("update_application_settings", fields))
        return {"ok": True}


class BrowserGuiServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeApi()
        self.server = BrowserGuiServer(self.api, 0)
        self.url = self.server.start()

    def tearDown(self) -> None:
        self.server.close()

    def test_serves_index_with_the_browser_bridge(self) -> None:
        with urlopen(self.url) as response:
            page = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn('<script src="/web-bridge.js"></script>', page)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_calls_only_allowlisted_api_methods(self) -> None:
        result = self._rpc("update_application_settings", [{"archive_retention_days": 45}])

        self.assertTrue(result["ok"])
        self.assertEqual(self.api.calls[-1][0], "update_application_settings")

        with self.assertRaises(HTTPError) as context:
            self._rpc("_current_config")
        self.assertEqual(context.exception.code, 400)

    def test_rejects_cross_origin_requests(self) -> None:
        request = Request(
            self.url + "/api/rpc",
            json.dumps({"method": "get_state", "args": []}).encode("utf-8"),
            {"Content-Type": "application/json", "Origin": "https://malicious.example"},
        )

        with self.assertRaises(HTTPError) as context:
            urlopen(request)

        self.assertEqual(context.exception.code, 403)
        self.assertEqual(self.api.calls, [])

    def test_does_not_serve_files_outside_the_web_root(self) -> None:
        with self.assertRaises(HTTPError) as context:
            urlopen(self.url + "/%2e%2e/config.py")

        self.assertEqual(context.exception.code, 404)

    def test_selects_a_free_port_when_the_configured_port_is_busy(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
            blocker.bind(("127.0.0.1", 0))
            blocker.listen(1)
            busy_port = blocker.getsockname()[1]
            fallback = BrowserGuiServer(FakeApi(), busy_port)
            try:
                url = fallback.start()
                self.assertNotEqual(fallback.httpd.server_port, busy_port)
                self.assertEqual(url, f"http://127.0.0.1:{fallback.httpd.server_port}")
            finally:
                fallback.close()

    def test_port_update_response_survives_a_live_server_rebind(self) -> None:
        old_server = self.server

        def update_settings(fields: dict) -> dict:
            old_server.close()
            self.server = BrowserGuiServer(self.api, int(fields["web_gui_port"]))
            new_url = self.server.start()
            return {"ok": True, "browser_gui_url": new_url}

        self.api.update_application_settings = update_settings
        result = self._rpc("update_application_settings", [{"web_gui_port": 0}])

        self.assertTrue(result["ok"])
        self.assertNotEqual(result["browser_gui_url"], self.url)
        with urlopen(result["browser_gui_url"]) as response:
            self.assertEqual(response.status, 200)

    def _rpc(self, method: str, args: list | None = None) -> dict:
        request = Request(
            self.url + "/api/rpc",
            json.dumps({"method": method, "args": args or []}).encode("utf-8"),
            {"Content-Type": "application/json", "Origin": self.url},
        )
        with urlopen(request) as response:
            return json.load(response)


if __name__ == "__main__":
    unittest.main()
