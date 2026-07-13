# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from printbridge_endpoint.platform_window import disable_minimize


class PlatformWindowTests(unittest.TestCase):
    @patch("printbridge_endpoint.platform_window.platform.system", return_value="Darwin")
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

    @patch("printbridge_endpoint.platform_window.platform.system", return_value="Windows")
    def test_disables_windows_minimize_box(self, _system):
        native = SimpleNamespace(MinimizeBox=True, InvokeRequired=False)

        disable_minimize(SimpleNamespace(native=native))

        self.assertFalse(native.MinimizeBox)


if __name__ == "__main__":
    unittest.main()
