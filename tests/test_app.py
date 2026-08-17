# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import unittest
from unittest.mock import Mock, patch

from pridge_client import app


class ApplicationStartupTests(unittest.TestCase):
    @patch("pridge_client.gui.run_gui", side_effect=RuntimeError("renderer failed"))
    @patch("pridge_client.app.show_startup_error")
    @patch("pridge_client.app.configure_logging")
    @patch("pridge_client.app.ConfigStore")
    @patch("sys.argv", ["pridge-client"])
    def test_reports_gui_startup_failure(self, config_store, _configure_logging, show_error, _run_gui):
        config_store.return_value.load.return_value = Mock(servers=[], logging=Mock(), restart_on_crash=False)

        with self.assertLogs("pridge_client.app", level="ERROR") as captured:
            with self.assertRaises(SystemExit) as raised:
                app.main()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("Desktop GUI startup failed", "\n".join(captured.output))
        show_error.assert_called_once_with(app.APP_NAME, app.MESSAGE_GUI_STARTUP_FAILED)

    @patch("pridge_client.gui.run_gui")
    @patch("pridge_client.app.configure_logging")
    @patch("pridge_client.app.ConfigStore")
    @patch("sys.argv", ["pridge-client", "--gui-smoke-test"])
    def test_starts_private_gui_smoke_mode(self, config_store, _configure_logging, run_gui):
        config_store.return_value.load.return_value = Mock(servers=[], logging=Mock())

        app.main()

        run_gui.assert_called_once_with(gui_smoke_test=True)

    @patch("pridge_client.tui.run_tui")
    @patch("pridge_client.tui_ipc.RemoteTuiController.connect")
    @patch("pridge_client.app.configure_logging")
    @patch("pridge_client.app.ConfigStore")
    @patch("sys.argv", ["pridge-client", "--tui"])
    def test_tui_reattaches_to_a_running_service(self, config_store, _logging, connect, run_tui):
        config_store.return_value.load.return_value = Mock(servers=[], logging=Mock(), restart_on_crash=True)
        remote = connect.return_value

        app.main()

        run_tui.assert_called_once_with(remote, attached_to_service=True)

    @patch("pridge_client.app._run_headless_service")
    @patch("pridge_client.app.sys.platform", "darwin")
    @patch("pridge_client.app.configure_logging")
    @patch("pridge_client.app.ConfigStore")
    @patch("sys.argv", ["pridge-client", "--headless", "--supervised-child"])
    def test_posix_headless_child_hosts_the_tui_service(self, config_store, _logging, run_service):
        config_store.return_value.load.return_value = Mock(servers=[], logging=Mock(), restart_on_crash=True)

        app.main()

        run_service.assert_called_once_with()

    @patch("pridge_client.app.show_headless_address")
    @patch("pridge_client.app.signal.signal")
    @patch("pridge_client.app.sys.platform", "win32")
    def test_windows_headless_starts_and_announces_browser_gui(self, _signal, announce):
        api = Mock(config=Mock(web_gui_port=9012, web_gui_enabled=False))
        controller = Mock()
        browser_instances = []

        class FakeBrowser:
            def __init__(self, _api, port, on_stop):
                self.port = port
                self.on_stop = on_stop
                self.closed = False
                browser_instances.append(self)

            def start(self):
                self.on_stop()
                return "http://127.0.0.1:9012"

            def close(self):
                self.closed = True

        with patch("pridge_client.gui.ClientApi", return_value=api), patch(
            "pridge_client.headless_tui.HeadlessTuiController", return_value=controller
        ), patch("pridge_client.web_gui.BrowserGuiServer", FakeBrowser):
            app._run_headless_service()

        controller.start.assert_called_once_with()
        controller.stop_all.assert_called_once_with()
        announce.assert_called_once_with(app.APP_NAME, "http://127.0.0.1:9012")
        self.assertEqual(browser_instances[0].port, 9012)
        self.assertTrue(browser_instances[0].closed)


class SupervisorHandoffTests(unittest.TestCase):
    @patch("pridge_client.gui.run_gui")
    @patch("pridge_client.supervisor.run_supervised", return_value=0)
    @patch("pridge_client.app.configure_logging")
    @patch("pridge_client.app.ConfigStore")
    @patch("sys.argv", ["pridge-client"])
    def test_default_desktop_launch_runs_the_gui_directly(
        self, config_store, _configure_logging, run_supervised, run_gui
    ):
        config_store.return_value.load.return_value = Mock(servers=[], logging=Mock(), restart_on_crash=True)

        app.main()

        run_gui.assert_called_once_with(gui_smoke_test=False)
        run_supervised.assert_not_called()

    @patch("pridge_client.supervisor.run_supervised", return_value=0)
    @patch("pridge_client.app.configure_logging")
    @patch("pridge_client.app.ConfigStore")
    @patch("sys.argv", ["pridge-client", "--headless"])
    def test_delegates_to_the_supervisor_when_restart_on_crash_is_enabled(self, config_store, _configure_logging, run_supervised):
        config_store.return_value.load.return_value = Mock(servers=[], logging=Mock(), restart_on_crash=True)

        with self.assertRaises(SystemExit) as raised:
            app.main()

        self.assertEqual(raised.exception.code, 0)
        run_supervised.assert_called_once_with(["--headless"])

    @patch("pridge_client.gui.run_gui")
    @patch("pridge_client.supervisor.run_supervised")
    @patch("pridge_client.app.configure_logging")
    @patch("pridge_client.app.ConfigStore")
    @patch("sys.argv", ["pridge-client", "--supervised-child"])
    def test_supervised_child_runs_directly_without_recursing(
        self, config_store, _configure_logging, run_supervised, _run_gui
    ):
        config_store.return_value.load.return_value = Mock(servers=[], logging=Mock(), restart_on_crash=True)

        app.main()

        run_supervised.assert_not_called()


if __name__ == "__main__":
    unittest.main()
