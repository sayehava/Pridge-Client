# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pridge_client.config import (
    ClientConfig,
    ClientTokenStore,
    ConfigStore,
    DashboardWidget,
    PrinterMapping,
    PrinterProfile,
    ServerConfig,
    _parse_printer_profiles,
)


class ConfigStoreTests(unittest.TestCase):
    def test_missing_config_defaults_to_recent_jobs_and_logs_widgets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigStore(Path(directory) / "config.json").load()

        self.assertEqual([w.widget_type for w in config.dashboard_widgets], ["recent_jobs", "logs"])

    def test_saves_and_loads_dashboard_widget_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = ConfigStore(path)
            store.save(
                ClientConfig(
                    dashboard_widgets=[
                        DashboardWidget(id="a", widget_type="recent_jobs", page=0, position=0),
                        DashboardWidget(id="b", widget_type="org.example.widget", page=1, position=0),
                    ]
                )
            )

            config = store.load()

        self.assertEqual(len(config.dashboard_widgets), 2)
        self.assertEqual(config.dashboard_widgets[1].widget_type, "org.example.widget")
        self.assertEqual(config.dashboard_widgets[1].page, 1)

    def test_malformed_dashboard_widgets_fall_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"dashboard_widgets": "not-a-list"}), encoding="utf-8")

            config = ConfigStore(path).load()

        self.assertEqual([w.widget_type for w in config.dashboard_widgets], ["recent_jobs", "logs"])

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

    def test_saves_and_loads_a_printer_profile_s_fit_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = ConfigStore(path)
            store.save(
                ClientConfig(
                    printer_profiles={"Receipt": PrinterProfile(fit_mode="actual_size")}
                )
            )

            config = store.load()

        self.assertEqual(config.printer_profiles["Receipt"].fit_mode, "actual_size")

    def test_saves_and_loads_raw_header_and_footer_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = ConfigStore(path)
            store.save(
                ClientConfig(
                    printer_profiles={
                        "Receipt": PrinterProfile(
                            raw_header_preset="feed",
                            raw_footer_preset="custom",
                            raw_footer_custom_hex="1D 56 00",
                        )
                    }
                )
            )

            config = store.load()

        profile = config.printer_profiles["Receipt"]
        self.assertEqual(profile.raw_header_preset, "feed")
        self.assertEqual(profile.raw_footer_preset, "custom")
        self.assertEqual(profile.raw_footer_custom_hex, "1D 56 00")

    def test_saves_and_loads_mapping_receipt_composer_template_settings(self) -> None:
        # Receipt Composer content now lives on the mapping itself, not the
        # PrinterProfile shared by everything pointing at a local printer.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = ConfigStore(path)
            store.save(
                ClientConfig(
                    servers=[
                        ServerConfig(
                            id="s1",
                            name="Server",
                            server_url="https://example.test",
                            printer_mappings=[
                                PrinterMapping(
                                    remote_printer_id="ep-1",
                                    local_printer_name="Receipt",
                                    raw_header_template="[align:center][image:logo1][bold]Thanks![/bold]",
                                    raw_footer_template="[cut:full]",
                                    raw_paper_width_dots=576,
                                    raw_chars_per_line=48,
                                    receipt_design_migrated=True,
                                )
                            ],
                        )
                    ]
                )
            )

            config = store.load()

        mapping = config.servers[0].printer_mappings[0]
        self.assertEqual(mapping.raw_header_template, "[align:center][image:logo1][bold]Thanks![/bold]")
        self.assertEqual(mapping.raw_footer_template, "[cut:full]")
        self.assertEqual(mapping.raw_paper_width_dots, 576)
        self.assertEqual(mapping.raw_chars_per_line, 48)
        self.assertTrue(mapping.receipt_design_migrated)

    def test_parse_printer_profiles_migrates_each_legacy_raw_preset_to_an_equivalent_shortcode(self) -> None:
        # _parse_printer_profiles still resolves presets into a template string
        # for _migrate_mapping_receipt_designs to consume - it just no longer
        # stores that string on PrinterProfile itself.
        cases = [
            ({"raw_header_preset": "full_cut"}, "[cut:full]"),
            ({"raw_header_preset": "partial_cut"}, "[cut:partial]"),
            ({"raw_header_preset": "open_drawer"}, "[drawer]"),
            ({"raw_header_preset": "feed"}, "[feed:4]"),
            ({"raw_header_preset": "custom", "raw_header_custom_hex": "1D 56 00"}, "[hex:1D5600]"),
        ]
        for profile_fields, expected_template in cases:
            _profiles, legacy_designs = _parse_printer_profiles({"Receipt": profile_fields})

            header, _footer, _paper_width, _chars = legacy_designs["Receipt"]
            self.assertEqual(header, expected_template, profile_fields)

    def test_parse_printer_profiles_does_not_overwrite_an_explicit_raw_template_with_a_migrated_legacy_preset(
        self,
    ) -> None:
        _profiles, legacy_designs = _parse_printer_profiles(
            {"Receipt": {"raw_header_preset": "full_cut", "raw_header_template": "[drawer]"}}
        )

        header, _footer, _paper_width, _chars = legacy_designs["Receipt"]
        self.assertEqual(header, "[drawer]")

    def test_parse_printer_profiles_legacy_paper_width_is_rounded_down_to_a_byte_boundary_and_clamped(self) -> None:
        _profiles, legacy_designs = _parse_printer_profiles({"Receipt": {"raw_paper_width_dots": 401}})

        _header, _footer, paper_width, _chars = legacy_designs["Receipt"]
        self.assertEqual(paper_width, 400)

    def test_migrates_a_legacy_global_printer_profile_template_onto_a_mapping_targeting_that_printer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "printer_profiles": {
                            "Receipt": {
                                "raw_header_template": "[align:center]Legacy[/align]",
                                "raw_footer_template": "[cut:full]",
                                "raw_paper_width_dots": 576,
                                "raw_chars_per_line": 48,
                            }
                        },
                        "servers": [
                            {
                                "id": "s1",
                                "name": "Server",
                                "server_url": "https://example.test",
                                "printer_mappings": [
                                    {"remote_printer_id": "ep-1", "local_printer_name": "Receipt"}
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = ConfigStore(path).load()

        mapping = config.servers[0].printer_mappings[0]
        self.assertEqual(mapping.raw_header_template, "[align:center]Legacy[/align]")
        self.assertEqual(mapping.raw_footer_template, "[cut:full]")
        self.assertEqual(mapping.raw_paper_width_dots, 576)
        self.assertEqual(mapping.raw_chars_per_line, 48)
        self.assertTrue(mapping.receipt_design_migrated)

    def test_migration_copies_the_shared_legacy_template_to_every_mapping_on_that_printer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "printer_profiles": {"Receipt": {"raw_header_template": "[bold]Shared[/bold]"}},
                        "servers": [
                            {
                                "id": "s1",
                                "name": "Server",
                                "server_url": "https://example.test",
                                "printer_mappings": [
                                    {"remote_printer_id": "kitchen", "local_printer_name": "Receipt"},
                                    {"remote_printer_id": "register", "local_printer_name": "Receipt"},
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = ConfigStore(path).load()

        mappings = config.servers[0].printer_mappings
        self.assertEqual(mappings[0].raw_header_template, "[bold]Shared[/bold]")
        self.assertEqual(mappings[1].raw_header_template, "[bold]Shared[/bold]")

    def test_server_specific_legacy_profile_wins_over_global_for_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "printer_profiles": {"Receipt": {"raw_header_template": "[bold]Global[/bold]"}},
                        "servers": [
                            {
                                "id": "s1",
                                "name": "Server",
                                "server_url": "https://example.test",
                                "printer_profiles": {"Receipt": {"raw_header_template": "[bold]ServerOverride[/bold]"}},
                                "printer_mappings": [
                                    {"remote_printer_id": "ep-1", "local_printer_name": "Receipt"}
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = ConfigStore(path).load()

        self.assertEqual(
            config.servers[0].printer_mappings[0].raw_header_template, "[bold]ServerOverride[/bold]"
        )

    def test_already_migrated_mapping_left_blank_on_purpose_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "printer_profiles": {"Receipt": {"raw_header_template": "[bold]Legacy[/bold]"}},
                        "servers": [
                            {
                                "id": "s1",
                                "name": "Server",
                                "server_url": "https://example.test",
                                "printer_mappings": [
                                    {
                                        "remote_printer_id": "ep-1",
                                        "local_printer_name": "Receipt",
                                        "raw_header_template": "",
                                        "receipt_design_migrated": True,
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = ConfigStore(path).load()

        self.assertEqual(config.servers[0].printer_mappings[0].raw_header_template, "")

    def test_invalid_raw_presets_fall_back_to_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {"printer_profiles": {"Receipt": {"raw_header_preset": "self_destruct"}}}
                ),
                encoding="utf-8",
            )

            config = ConfigStore(path).load()

        self.assertEqual(config.printer_profiles["Receipt"].raw_header_preset, "")

    def test_invalid_printer_profile_fit_mode_falls_back_to_fit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps({"printer_profiles": {"Receipt": {"fit_mode": "stretch-to-infinity"}}}),
                encoding="utf-8",
            )

            config = ConfigStore(path).load()

        self.assertEqual(config.printer_profiles["Receipt"].fit_mode, "fit")

    def test_invalid_printer_profile_mode_falls_back_to_system_driver(self) -> None:
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

        self.assertEqual(config.printer_profiles["Office Labels"].mode, "system_driver")
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

            with patch("pridge_client.config.default_config_path", return_value=client_path), patch(
                "pridge_client.config.legacy_config_paths", return_value=(legacy_path,)
            ):
                config = ConfigStore().load()

            self.assertEqual(config.servers[0].id, "office")
            self.assertTrue(client_path.exists())
            self.assertTrue(legacy_path.exists())

    @patch("pridge_client.config._load_keyring", return_value=None)
    def test_copies_legacy_fallback_token_to_client_location(self, _load_keyring) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client_directory = root / "Pridge Client"
            legacy_directory = root / "PrintBridge Client"
            legacy_directory.mkdir(parents=True)
            (legacy_directory / "client-token-office").write_text("legacy-token", encoding="utf-8")

            with patch("pridge_client.config.default_config_dir", return_value=client_directory), patch(
                "pridge_client.config.legacy_config_dirs", return_value=(legacy_directory,)
            ):
                token = ClientTokenStore().get("office")

            self.assertEqual(token, "legacy-token")
            self.assertEqual((client_directory / "client-token-office").read_text(encoding="utf-8"), "legacy-token")
            self.assertTrue((legacy_directory / "client-token-office").exists())

    @patch("pridge_client.config._load_keyring")
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

    def test_loads_per_server_printer_profile_override(self) -> None:
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
                                "printer_profiles": {
                                    "EPSON TM-T88": {"mode": "raw", "submission_method": "pdfium"}
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            config = ConfigStore(path).load()

        profile = config.servers[0].printer_profiles["EPSON TM-T88"]
        self.assertEqual(profile.mode, "raw")
        self.assertEqual(profile.submission_method, "pdfium")

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
