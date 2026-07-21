# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from printbridge_client.platform_window import (
    configure_application_identity,
    create_application_menu,
    disable_minimize,
    ensure_webview2_runtime,
    preferred_webview_gui,
    show_startup_error,
)


class PlatformWindowTests(unittest.TestCase):
    @patch("printbridge_client.platform_window.platform.system", return_value="Windows")
    def test_selects_edge_chromium_on_windows(self, _system):
        self.assertEqual(preferred_webview_gui(), "edgechromium")

    @patch("printbridge_client.platform_window.platform.system", return_value="Darwin")
    def test_selects_cocoa_on_macos(self, _system):
        self.assertEqual(preferred_webview_gui(), "cocoa")

    @patch("printbridge_client.platform_window.platform.system", return_value="Linux")
    def test_selects_qt_on_linux(self, _system):
        self.assertEqual(preferred_webview_gui(), "qt")

    @patch("printbridge_client.platform_window.logger.error")
    @patch("printbridge_client.platform_window.platform.system", return_value="Linux")
    def test_logs_startup_error_when_no_native_dialog_is_available(self, _system, log_error):
        show_startup_error("Pridge Client", "Could not start")

        log_error.assert_called_once_with("%s Startup Error: %s", "Pridge Client", "Could not start")

    @patch("printbridge_client.platform_window.platform.system", return_value="Darwin")
    def test_sets_macos_process_and_bundle_name(self, _system):
        info = {}
        bundle = Mock()
        bundle.localizedInfoDictionary.return_value = info
        process_info = Mock()
        foundation = SimpleNamespace(
            NSBundle=SimpleNamespace(mainBundle=lambda: bundle),
            NSProcessInfo=SimpleNamespace(processInfo=lambda: process_info),
        )

        with patch.dict(sys.modules, {"Foundation": foundation}):
            configure_application_identity("Pridge Client")

        self.assertEqual(info["CFBundleName"], "Pridge Client")
        self.assertEqual(info["CFBundleDisplayName"], "Pridge Client")
        process_info.setProcessName_.assert_called_once_with("Pridge Client")

    @patch("printbridge_client.platform_window.platform.system", return_value="Linux")
    def test_skips_application_identity_outside_macos(self, _system):
        with patch.dict(sys.modules, {"Foundation": None}):
            configure_application_identity("Pridge Client")

    @patch("printbridge_client.platform_window.platform.system", return_value="Darwin")
    def test_creates_three_item_macos_application_menu(self, _system):
        actions = [("Settings", Mock()), ("About", Mock()), ("Quit", Mock())]

        menu = create_application_menu(actions)

        self.assertEqual(len(menu), 1)
        self.assertEqual(menu[0].title, "__app__")
        self.assertEqual([item.title for item in menu[0].items], ["Settings", "About", "Quit"])

    @patch("printbridge_client.platform_window.platform.system", return_value="Darwin")
    def test_hides_macos_minimize_button(self, _system):
        button = Mock()
        native = Mock()
        native.standardWindowButton_.return_value = button
        native.styleMask.return_value = 7
        appkit = SimpleNamespace(NSWindowMiniaturizeButton=1, NSWindowMiniaturizableWindowMask=4)
        app_helper = SimpleNamespace(callAfter=lambda callback: callback())

        with patch.dict(sys.modules, {"AppKit": appkit, "PyObjCTools": SimpleNamespace(AppHelper=app_helper)}):
            disable_minimize(SimpleNamespace(native=native))

        button.setEnabled_.assert_called_once_with(False)
        button.setHidden_.assert_called_once_with(True)
        native.setStyleMask_.assert_called_once_with(3)

    @patch("printbridge_client.platform_window.platform.system", return_value="Windows")
    def test_disables_windows_minimize_box(self, _system):
        native = SimpleNamespace(MinimizeBox=True, InvokeRequired=False)

        disable_minimize(SimpleNamespace(native=native))

        self.assertFalse(native.MinimizeBox)

    @patch("printbridge_client.platform_window.platform.system", return_value="Darwin")
    @patch("printbridge_client.platform_window.subprocess.run")
    def test_skips_webview2_check_outside_windows(self, run, _system):
        ensure_webview2_runtime()

        run.assert_not_called()

    @patch("printbridge_client.platform_window.platform.system", return_value="Windows")
    @patch("printbridge_client.platform_window._webview2_runtime_installed", return_value=True)
    @patch("printbridge_client.platform_window.subprocess.run")
    def test_skips_install_when_runtime_already_present(self, run, _installed, _system):
        ensure_webview2_runtime()

        run.assert_not_called()

    @patch("printbridge_client.platform_window.platform.system", return_value="Windows")
    @patch("printbridge_client.platform_window._webview2_runtime_installed", return_value=False)
    @patch("printbridge_client.platform_window._bundled_webview2_bootstrapper", return_value=None)
    @patch("printbridge_client.platform_window.subprocess.run")
    def test_skips_install_when_no_bootstrapper_is_bundled(self, run, _bootstrapper, _installed, _system):
        ensure_webview2_runtime()

        run.assert_not_called()

    @patch("printbridge_client.platform_window.platform.system", return_value="Windows")
    @patch("printbridge_client.platform_window._webview2_runtime_installed", return_value=False)
    @patch(
        "printbridge_client.platform_window._bundled_webview2_bootstrapper",
        return_value=r"C:\App\MicrosoftEdgeWebview2Setup.exe",
    )
    @patch("printbridge_client.platform_window.subprocess.run")
    def test_silently_installs_the_bundled_bootstrapper_when_runtime_is_missing(
        self, run, _bootstrapper, _installed, _system
    ):
        ensure_webview2_runtime()

        run.assert_called_once_with(
            [r"C:\App\MicrosoftEdgeWebview2Setup.exe", "/silent", "/install"], check=True, timeout=180
        )

    @patch("printbridge_client.platform_window.platform.system", return_value="Windows")
    @patch("printbridge_client.platform_window._webview2_runtime_installed", return_value=False)
    @patch("printbridge_client.platform_window._bundled_webview2_bootstrapper", return_value="C:\\bootstrap.exe")
    @patch("printbridge_client.platform_window.subprocess.run", side_effect=OSError("boom"))
    def test_install_failure_is_logged_and_swallowed(self, _run, _bootstrapper, _installed, _system):
        ensure_webview2_runtime()


if __name__ == "__main__":
    unittest.main()
