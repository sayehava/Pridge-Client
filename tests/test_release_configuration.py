# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseConfigurationTests(unittest.TestCase):
    def test_pyinstaller_is_reusable_windowed_onedir_spec(self):
        text = (ROOT / "packaging" / "pyinstaller" / "PrintBridge-Client.spec").read_text(encoding="utf-8")

        self.assertIn("exclude_binaries=True", text)
        self.assertIn("console=False", text)
        self.assertIn("collection = COLLECT", text)
        self.assertNotIn("onefile", text.lower())

    def test_windows_installer_bootstraps_webview_only_when_missing(self):
        text = (ROOT / "packaging" / "windows" / "PrintBridge-Client.iss").read_text(encoding="utf-8")

        self.assertIn("F3017226-FE2A-4295-8BDF-00C3A9A7E4C5", text)
        self.assertIn("Check: not WebView2RuntimeInstalled", text)
        self.assertIn("/silent /install", text)

    def test_windows_build_uses_external_compiler_directories(self):
        text = (ROOT / "scripts" / "build-windows.ps1").read_text(encoding="utf-8")

        self.assertIn("[IO.Path]::GetTempPath()", text)
        self.assertIn("PRINTBRIDGE_RELEASE_DIR", text)
        self.assertIn('"--standalone"', text)
        self.assertIn('"--windows-console-mode=disable"', text)
        self.assertNotIn('"--onefile"', text)


if __name__ == "__main__":
    unittest.main()
