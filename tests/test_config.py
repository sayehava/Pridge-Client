# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import json
import tempfile
import unittest
from pathlib import Path

from printbridge_client.config import ConfigStore


class ConfigStoreTests(unittest.TestCase):
    def test_migrates_legacy_single_server_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "server_url": "https://print.example.test",
                        "polling_interval_seconds": 11,
                        "heartbeat_interval_seconds": 44,
                    }
                ),
                encoding="utf-8",
            )

            config = ConfigStore(path).load()

        self.assertEqual(len(config.servers), 1)
        self.assertEqual(config.servers[0].id, "default")
        self.assertEqual(config.servers[0].server_url, "https://print.example.test")
        self.assertEqual(config.servers[0].polling_interval_seconds, 11)
        self.assertEqual(config.servers[0].heartbeat_interval_seconds, 44)

    def test_loads_multiple_server_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "servers": [
                            {"id": "one", "name": "One", "server_url": "https://one.example.test"},
                            {"id": "two", "name": "Two", "server_url": "https://two.example.test", "enabled": False},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            config = ConfigStore(path).load()

        self.assertEqual([server.id for server in config.servers], ["one", "two"])
        self.assertFalse(config.servers[1].enabled)

    def test_loads_per_server_printer_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "servers": [
                            {
                                "id": "office",
                                "name": "Office",
                                "server_url": "https://office.example.test",
                                "default_printer": "Office Backup",
                                "printer_mappings": [
                                    {
                                        "remote_printer_id": "12",
                                        "remote_printer_name": "Receipts",
                                        "local_printer_name": "EPSON TM-T88",
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            config = ConfigStore(path).load()

        server = config.servers[0]
        self.assertEqual(server.default_printer, "Office Backup")
        self.assertEqual(server.printer_mappings[0].remote_printer_id, "12")
        self.assertEqual(server.printer_mappings[0].remote_printer_name, "Receipts")
        self.assertEqual(server.printer_mappings[0].local_printer_name, "EPSON TM-T88")

    def test_migrates_global_printer_to_server_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "selected_printer": "Legacy Printer",
                        "servers": [
                            {"id": "one", "name": "One", "server_url": "https://one.example.test"}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = ConfigStore(path).load()

        self.assertEqual(config.servers[0].default_printer, "Legacy Printer")

    def test_migrates_legacy_opacity_to_darkness_grade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "appearance": {
                            "transparency_enabled": True,
                            "glass_opacity_percent": 80,
                        }
                    }
                ),
                encoding="utf-8",
            )

            config = ConfigStore(path).load()

        self.assertEqual(config.appearance.darkness_grade, "Obsidian")


if __name__ == "__main__":
    unittest.main()
