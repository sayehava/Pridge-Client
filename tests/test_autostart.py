# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pridge_client.autostart import APP_ID, LEGACY_APP_IDS, AutoStartError, _set_macos_launch_agent, _set_windows_run_key, command


class _FakeWinRegKey:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _FakeWinReg:
    """Minimal stand-in for the winreg module, since it only exists on Windows."""

    HKEY_CURRENT_USER = object()
    KEY_SET_VALUE = object()
    REG_SZ = object()

    def __init__(self):
        self.values = {}
        self.create_key_calls = []

    def CreateKeyEx(self, key, sub_key, reserved=0, access=0):
        self.create_key_calls.append((key, sub_key, reserved, access))
        return _FakeWinRegKey()

    def SetValueEx(self, key, value_name, reserved, value_type, value):
        self.values[value_name] = value

    def DeleteValue(self, key, value_name):
        if value_name not in self.values:
            raise FileNotFoundError(value_name)
        del self.values[value_name]


class AutoStartTests(unittest.TestCase):
    def test_headless_command_uses_client_package(self) -> None:
        self.assertEqual(command()[1:], ["-m", "pridge_client", "--headless"])

    def test_macos_launch_agent_replaces_legacy_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            launch_agents = home / "Library" / "LaunchAgents"
            launch_agents.mkdir(parents=True)
            legacy_paths = [launch_agents / f"{app_id}.plist" for app_id in LEGACY_APP_IDS]
            for legacy_path in legacy_paths:
                legacy_path.write_text("legacy", encoding="utf-8")

            with patch("pridge_client.autostart.Path.home", return_value=home):
                _set_macos_launch_agent(True)

            client_path = launch_agents / f"{APP_ID}.plist"
            self.assertTrue(client_path.exists())
            self.assertFalse(any(legacy_path.exists() for legacy_path in legacy_paths))
            self.assertIn("pridge_client", client_path.read_text(encoding="utf-8"))

    def test_windows_run_key_is_created_even_if_it_does_not_already_exist(self) -> None:
        fake_winreg = _FakeWinReg()
        with patch.dict(sys.modules, {"winreg": fake_winreg}):
            _set_windows_run_key(True)

        self.assertEqual(len(fake_winreg.create_key_calls), 1)
        self.assertIn("Pridge Client", fake_winreg.values)

    def test_windows_run_key_removes_the_value_when_disabled(self) -> None:
        fake_winreg = _FakeWinReg()
        fake_winreg.values["Pridge Client"] = "leftover"
        with patch.dict(sys.modules, {"winreg": fake_winreg}):
            _set_windows_run_key(False)

        self.assertNotIn("Pridge Client", fake_winreg.values)

    def test_windows_run_key_wraps_registry_errors_as_autostart_error(self) -> None:
        fake_winreg = _FakeWinReg()

        def _raise(*_args, **_kwargs):
            raise OSError("Access is denied")

        fake_winreg.CreateKeyEx = _raise
        with patch.dict(sys.modules, {"winreg": fake_winreg}):
            with self.assertRaises(AutoStartError):
                _set_windows_run_key(True)


if __name__ == "__main__":
    unittest.main()
