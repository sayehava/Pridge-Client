# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import unittest
from unittest.mock import Mock, patch

from printbridge_client import app


class ApplicationStartupTests(unittest.TestCase):
    @patch("printbridge_client.gui.run_gui", side_effect=RuntimeError("renderer failed"))
    @patch("printbridge_client.app.show_startup_error")
    @patch("printbridge_client.app.configure_logging")
    @patch("printbridge_client.app.ConfigStore")
    @patch("sys.argv", ["pridge-client"])
    def test_reports_gui_startup_failure(self, config_store, _configure_logging, show_error, _run_gui):
        config_store.return_value.load.return_value = Mock(servers=[], logging=Mock())

        with self.assertLogs("printbridge_client.app", level="ERROR") as captured:
            with self.assertRaises(SystemExit) as raised:
                app.main()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("Desktop GUI startup failed", "\n".join(captured.output))
        show_error.assert_called_once_with(app.APP_NAME, app.MESSAGE_GUI_STARTUP_FAILED)


if __name__ == "__main__":
    unittest.main()
