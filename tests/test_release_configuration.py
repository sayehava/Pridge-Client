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
        self.assertIn('Join-Path $Repository "build"', text)
        self.assertIn("[switch]$SelectOutputDir", text)
        self.assertIn("System.Windows.Forms.FolderBrowserDialog", text)
        self.assertIn('"--standalone"', text)
        self.assertIn('"--windows-console-mode=disable"', text)
        self.assertNotIn('"--include-package=webview"', text)
        self.assertNotIn('"--include-package=PIL"', text)
        self.assertIn('"--include-module=pystray._win32"', text)
        self.assertIn('"--nofollow-import-to=tkinter"', text)
        self.assertNotIn('"--onefile"', text)

    def test_macos_build_creates_native_app_bundles_and_dmgs(self):
        text = (ROOT / "scripts" / "build-macos.sh").read_text(encoding="utf-8")

        self.assertIn("${PRINTBRIDGE_RELEASE_DIR:-$REPOSITORY/build}", text)
        self.assertIn("--select-output-dir", text)
        self.assertIn("choose folder", text)
        self.assertIn("--macos-create-app-bundle", text)
        self.assertIn("hdiutil create", text)
        self.assertIn("PRINTBRIDGE_MACOS_SIGNING_IDENTITY", text)
        self.assertIn("notarytool submit", text)
        self.assertNotIn("--include-package=webview", text)
        self.assertNotIn("--include-package=PIL", text)
        self.assertIn("--include-module=pystray._darwin", text)
        self.assertIn("--nofollow-import-to=tkinter", text)
        self.assertNotIn("--onefile", text)

    def test_tag_workflow_publishes_all_expected_packages(self):
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

        expected = (
            "PrintBridge-Client-Native-Setup-x64.exe",
            "PrintBridge-Client-Native-Windows-x64-Portable.zip",
            "PrintBridge-Client-Native-macOS-arm64.dmg",
            "PrintBridge-Client-Native-macOS-x86_64.dmg",
            "PrintBridge-Client-PyInstaller-Setup-x64.exe",
            "PrintBridge-Client-PyInstaller-Windows-x64-Portable.zip",
            "PrintBridge-Client-PyInstaller-macOS-arm64.dmg",
            "PrintBridge-Client-PyInstaller-macOS-x86_64.dmg",
            "SHA256SUMS.txt",
            "PrintBridge-Client-Release-Notes.txt",
        )
        for filename in expected:
            self.assertIn(filename, text)
        self.assertIn('tags:\n      - "v*"', text)
        self.assertIn("${{ github.workspace }}/build", text)


if __name__ == "__main__":
    unittest.main()
