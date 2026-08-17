# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import tempfile
import unittest
from pathlib import Path
from threading import Event, Thread

from pridge_client.tui_ipc import RemoteTuiController
from pridge_client.tui_service import TuiServiceServer


class _FakeController:
    def __init__(self) -> None:
        self.server_toggles = []

    def dashboard_data(self):
        return {"printed_today": 7}

    def servers_data(self):
        return [{"name": "Office"}]

    def printers_data(self):
        return [{"name": "Printer"}]

    def plugins_data(self):
        return [{"name": "PDF"}]

    def settings_data(self):
        return [{"label": "Polling", "enabled": True}]

    def toggle_server(self, index):
        self.server_toggles.append(index)

    def toggle_plugin(self, _index):
        return None

    def toggle_setting(self, index):
        return f"setting {index}"


class TuiServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.directory.cleanup)
        self.socket_path = Path(self.directory.name) / "service.sock"
        self.controller = _FakeController()
        self.server = TuiServiceServer(self.controller, self.socket_path)
        self.stop_event = Event()
        self.server.open()
        self.thread = Thread(target=self.server.serve, args=(self.stop_event,))
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2)
        self.server.close()

    def test_remote_controller_reads_and_mutates_the_running_service(self) -> None:
        remote = RemoteTuiController.connect(self.socket_path)

        self.assertIsNotNone(remote)
        self.assertEqual(remote.dashboard_data()["printed_today"], 7)
        self.assertEqual(remote.servers_data()[0]["name"], "Office")
        remote.toggle_server(2)
        self.assertEqual(self.controller.server_toggles, [2])
        self.assertEqual(remote.toggle_setting(1), "setting 1")

    def test_shutdown_request_stops_the_service(self) -> None:
        remote = RemoteTuiController.connect(self.socket_path)
        remote.shutdown()
        self.thread.join(timeout=2)

        self.assertFalse(self.thread.is_alive())

if __name__ == "__main__":
    unittest.main()
