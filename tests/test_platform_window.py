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
)


class PlatformWindowTests(unittest.TestCase):
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
            configure_application_identity("PrintBridge Client")

        self.assertEqual(info["CFBundleName"], "PrintBridge Client")
        self.assertEqual(info["CFBundleDisplayName"], "PrintBridge Client")
        process_info.setProcessName_.assert_called_once_with("PrintBridge Client")

    @patch("printbridge_client.platform_window.platform.system", return_value="Linux")
    def test_skips_application_identity_outside_macos(self, _system):
        with patch.dict(sys.modules, {"Foundation": None}):
            configure_application_identity("PrintBridge Client")

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


if __name__ == "__main__":
    unittest.main()
