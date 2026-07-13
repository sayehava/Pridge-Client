# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import unittest

from printbridge_endpoint.api import ReservedJob, parse_server_instructions
from printbridge_endpoint.config import PrinterMapping, ServerConfig
from printbridge_endpoint.worker import decode_payload, resolve_printer_name


class DecodePayloadTests(unittest.TestCase):
    def test_decodes_base64_payload(self) -> None:
        self.assertEqual(decode_payload("SGVsbG8="), b"Hello")

    def test_rejects_invalid_base64(self) -> None:
        with self.assertRaises(ValueError):
            decode_payload("not-valid")

    def test_rejects_empty_payload(self) -> None:
        with self.assertRaises(ValueError):
            decode_payload("")


class ServerInstructionTests(unittest.TestCase):
    def test_reads_top_level_intervals(self) -> None:
        instructions = parse_server_instructions(
            {
                "polling_interval_seconds": 12,
                "heartbeat_interval_seconds": 45,
            }
        )

        self.assertEqual(instructions.polling_interval_seconds, 12)
        self.assertEqual(instructions.heartbeat_interval_seconds, 45)

    def test_reads_nested_settings_intervals(self) -> None:
        instructions = parse_server_instructions(
            {
                "settings": {
                    "next_poll_seconds": 7,
                    "heartbeat_seconds": 20,
                }
            }
        )

        self.assertEqual(instructions.polling_interval_seconds, 7)
        self.assertEqual(instructions.heartbeat_interval_seconds, 20)


class PrinterMappingTests(unittest.TestCase):
    def test_resolves_remote_endpoint_to_local_printer(self) -> None:
        server = ServerConfig(
            id="office",
            printer_mappings=[
                PrinterMapping(
                    remote_printer_id="12",
                    remote_printer_name="Receipts",
                    local_printer_name="EPSON TM-T88",
                )
            ],
        )
        job = ReservedJob(
            job_id="1",
            payload_base64="SGVsbG8=",
            content_type="application/octet-stream",
            remote_printer_id="12",
        )

        self.assertEqual(resolve_printer_name(server, job), "EPSON TM-T88")

    def test_uses_server_default_for_unmapped_remote_printer(self) -> None:
        server = ServerConfig(id="office", default_printer="Office Backup")
        job = ReservedJob(
            job_id="1",
            payload_base64="SGVsbG8=",
            content_type="application/octet-stream",
            remote_printer_id="99",
        )

        self.assertEqual(resolve_printer_name(server, job), "Office Backup")


if __name__ == "__main__":
    unittest.main()
