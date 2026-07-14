# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseConfigurationTests(unittest.TestCase):
    def test_pyinstaller_is_reusable_windowed_onedir_spec(self):
        text = (ROOT / "packaging" / "pyinstaller" / "Pridge-Client.spec").read_text(encoding="utf-8")

        self.assertIn("exclude_binaries=True", text)
        self.assertIn("console=False", text)
        self.assertIn("collection = COLLECT", text)
        self.assertNotIn("onefile", text.lower())

    def test_windows_installer_bootstraps_webview_only_when_missing(self):
        text = (ROOT / "packaging" / "windows" / "Pridge-Client.iss").read_text(encoding="utf-8")

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
        self.assertIn('"--include-module=webview.platforms.winforms"', text)
        self.assertIn('"--include-module=webview.platforms.edgechromium"', text)
        self.assertIn('"--nofollow-import-to=tkinter"', text)
        self.assertIn("function Test-FrozenGui", text)
        self.assertIn('ArgumentList "--gui-smoke-test"', text)
        self.assertIn('Test-FrozenGui $Executable', text)
        self.assertNotIn('"--onefile"', text)

    def test_pyinstaller_collects_windows_webview_runtime(self):
        text = (ROOT / "packaging" / "pyinstaller" / "Pridge-Client.spec").read_text(encoding="utf-8")

        self.assertIn('"webview.platforms.winforms"', text)
        self.assertIn('"webview.platforms.edgechromium"', text)
        self.assertIn('(\"pythonnet\", \"clr_loader\")', text)

    def test_macos_build_creates_native_app_bundles_and_dmgs(self):
        text = (ROOT / "scripts" / "build-macos.sh").read_text(encoding="utf-8")

        self.assertIn("${PRINTBRIDGE_RELEASE_DIR:-$REPOSITORY/build}", text)
        self.assertIn("--select-output-dir", text)
        self.assertIn("choose folder", text)
        self.assertIn("--macos-create-app-bundle", text)
        self.assertIn("hdiutil create", text)
        self.assertIn("PRINTBRIDGE_MACOS_SIGNING_IDENTITY", text)
        self.assertIn("notarytool submit", text)
        self.assertIn('"$app/Contents/MacOS/$executable" --gui-smoke-test', text)
        self.assertNotIn("--include-package=webview", text)
        self.assertNotIn("--include-package=PIL", text)
        self.assertIn("--include-module=pystray._darwin", text)
        self.assertIn("--nofollow-import-to=tkinter", text)
        self.assertNotIn("--onefile", text)

    def test_linux_build_bundles_qt_and_smoke_tests_both_variants(self):
        text = (ROOT / "scripts" / "build-linux.sh").read_text(encoding="utf-8")
        spec = (ROOT / "packaging" / "pyinstaller" / "Pridge-Client.spec").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "build-linux.yml").read_text(encoding="utf-8")

        self.assertIn("--enable-plugin=pyqt6", text)
        self.assertIn("--include-module=webview.platforms.qt", text)
        self.assertIn("--gui-smoke-test", text)
        self.assertIn('"webview.platforms.qt"', spec)
        self.assertIn('PyQt6.QtWebEngineWidgets', spec)
        self.assertIn("xvfb", workflow)
        self.assertIn(".[linux,secure,tray]", workflow)

    def test_tag_workflow_publishes_all_expected_packages(self):
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

        expected = (
            "Pridge-Client-Native-Setup-x64.exe",
            "Pridge-Client-Native-Windows-x64-Portable.zip",
            "Pridge-Client-Native-macOS-arm64.dmg",
            "Pridge-Client-Native-macOS-x86_64.dmg",
            "Pridge-Client-PyInstaller-Setup-x64.exe",
            "Pridge-Client-PyInstaller-Windows-x64-Portable.zip",
            "Pridge-Client-PyInstaller-macOS-arm64.dmg",
            "Pridge-Client-PyInstaller-macOS-x86_64.dmg",
            "Pridge-Client-Native-Linux-x86_64.tar.gz",
            "Pridge-Client-PyInstaller-Linux-x86_64.tar.gz",
            "SHA256SUMS.txt",
            "Pridge-Client-Release-Notes.txt",
        )
        for filename in expected:
            self.assertIn(filename, text)
        self.assertIn('tags:\n      - "v*"', text)
        self.assertIn("${{ github.workspace }}/build", text)

    def test_macos_workflow_checks_variant_runtime_layout(self):
        text = (ROOT / ".github" / "workflows" / "build-macos.yml").read_text(encoding="utf-8")

        self.assertIn('runtime_root="$app/Contents/MacOS"', text)
        self.assertIn('runtime_root="$app/Contents/Resources"', text)
        self.assertIn('"Traceback|CRITICAL|FATAL"', text)
        self.assertIn("--gui-smoke-test", text)


if __name__ == "__main__":
    unittest.main()
