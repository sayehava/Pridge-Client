# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from printbridge_client.config import ClientConfig, ClientTokenStore, ConfigStore, PrinterProfile


class ConfigStoreTests(unittest.TestCase):
    def test_saves_and_loads_per_printer_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = ConfigStore(path)
            store.save(
                ClientConfig(
                    printer_profiles={
                        "Office Labels": PrinterProfile(
                            mode="system_driver",
                            driver_settings={"PageSize": "w288h432", "Duplex": "None"},
                        )
                    }
                )
            )

            config = store.load()

        self.assertEqual(config.printer_profiles["Office Labels"].mode, "system_driver")
        self.assertEqual(config.printer_profiles["Office Labels"].driver_settings["PageSize"], "w288h432")

    def test_invalid_printer_profile_mode_falls_back_to_raw(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "printer_profiles": {
                            "Office Labels": {
                                "mode": "unknown",
                                "driver_settings": {"Resolution": "300dpi", "invalid": None},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            config = ConfigStore(path).load()

        self.assertEqual(config.printer_profiles["Office Labels"].mode, "raw")
        self.assertEqual(config.printer_profiles["Office Labels"].driver_settings, {"Resolution": "300dpi"})

    def test_copies_legacy_default_config_to_client_location(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client_path = root / "Pridge Client" / "config.json"
            legacy_path = root / "PrintBridge Client" / "config.json"
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text(
                json.dumps({"servers": [{"id": "office", "server_url": "https://print.example.test"}]}),
                encoding="utf-8",
            )

            with patch("printbridge_client.config.default_config_path", return_value=client_path), patch(
                "printbridge_client.config.legacy_config_paths", return_value=(legacy_path,)
            ):
                config = ConfigStore().load()

            self.assertEqual(config.servers[0].id, "office")
            self.assertTrue(client_path.exists())
            self.assertTrue(legacy_path.exists())

    @patch("printbridge_client.config._load_keyring", return_value=None)
    def test_copies_legacy_fallback_token_to_client_location(self, _load_keyring) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client_directory = root / "Pridge Client"
            legacy_directory = root / "PrintBridge Client"
            legacy_directory.mkdir(parents=True)
            (legacy_directory / "client-token-office").write_text("legacy-token", encoding="utf-8")

            with patch("printbridge_client.config.default_config_dir", return_value=client_directory), patch(
                "printbridge_client.config.legacy_config_dirs", return_value=(legacy_directory,)
            ):
                token = ClientTokenStore().get("office")

            self.assertEqual(token, "legacy-token")
            self.assertEqual((client_directory / "client-token-office").read_text(encoding="utf-8"), "legacy-token")
            self.assertTrue((legacy_directory / "client-token-office").exists())

    @patch("printbridge_client.config._load_keyring")
    def test_copies_legacy_keyring_token_to_client_service(self, load_keyring) -> None:
        keyring = Mock()
        keyring.get_password.side_effect = lambda service, _username: (
            "legacy-token" if service == "printbridge-client" else None
        )
        load_keyring.return_value = keyring

        token = ClientTokenStore(Path("/unused")).get("office")

        self.assertEqual(token, "legacy-token")
        keyring.set_password.assert_called_once_with(
            "pridge-client",
            "client-token:office",
            "legacy-token",
        )

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
