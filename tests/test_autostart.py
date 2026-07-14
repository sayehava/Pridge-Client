# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from printbridge_client.autostart import APP_ID, LEGACY_APP_IDS, _set_macos_launch_agent, command


class AutoStartTests(unittest.TestCase):
    def test_headless_command_uses_client_package(self) -> None:
        self.assertEqual(command()[1:], ["-m", "printbridge_client", "--headless"])

    def test_macos_launch_agent_replaces_legacy_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            launch_agents = home / "Library" / "LaunchAgents"
            launch_agents.mkdir(parents=True)
            legacy_paths = [launch_agents / f"{app_id}.plist" for app_id in LEGACY_APP_IDS]
            for legacy_path in legacy_paths:
                legacy_path.write_text("legacy", encoding="utf-8")

            with patch("printbridge_client.autostart.Path.home", return_value=home):
                _set_macos_launch_agent(True)

            client_path = launch_agents / f"{APP_ID}.plist"
            self.assertTrue(client_path.exists())
            self.assertFalse(any(legacy_path.exists() for legacy_path in legacy_paths))
            self.assertIn("printbridge_client", client_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
