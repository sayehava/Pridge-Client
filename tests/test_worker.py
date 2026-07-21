# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import time
import unittest
from unittest.mock import Mock, patch

from printbridge_client.api import ApiError, ReservedJob, ServerInstructions, parse_server_instructions
from printbridge_client.config import ClientConfig, PrinterMapping, PrinterProfile, ServerConfig
from printbridge_client.worker import PollingWorker, decode_payload, resolve_printer_name


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


class WorkerPrintingModeTests(unittest.TestCase):
    def test_submits_job_with_saved_printer_mode_and_driver_settings(self) -> None:
        server = ServerConfig(id="office", default_printer="Office Driver")
        config = ClientConfig(
            server_url="https://example.test",
            servers=[server],
            printer_profiles={
                "Office Driver": PrinterProfile(
                    mode="system_driver",
                    driver_settings={"PageSize": "A4"},
                )
            },
        )
        printer_manager = Mock()
        client = Mock()
        worker = PollingWorker(config, "token", printer_manager=printer_manager)
        job = ReservedJob(
            job_id="42",
            payload_base64="JVBERg==",
            content_type="application/pdf",
        )

        worker._process_job(client, job)

        printer_manager.print_job.assert_called_once_with(
            "Office Driver",
            b"%PDF",
            mode="system_driver",
            driver_settings={"PageSize": "A4"},
            content_type="application/pdf",
            job_name="Pridge 42",
        )
        client.report_printed.assert_called_once_with("42")


class WorkerStatusRecoveryTests(unittest.TestCase):
    @patch("printbridge_client.worker.PrintBridgeClient")
    def test_status_recovers_after_a_transient_error(self, client_cls) -> None:
        call_count = {"heartbeat": 0}

        def heartbeat_side_effect(*_args, **_kwargs):
            call_count["heartbeat"] += 1
            if call_count["heartbeat"] == 1:
                raise ApiError("HTTP 401 returned for /api/client/heartbeat.")

        client = Mock()
        client.heartbeat.side_effect = heartbeat_side_effect
        client.reserve_job.return_value = None
        client.last_instructions = ServerInstructions()
        client_cls.return_value = client

        config = ClientConfig(
            server_url="https://example.test",
            polling_interval_seconds=0,
            heartbeat_interval_seconds=0,
        )
        statuses: list[str] = []
        worker = PollingWorker(config, "token", on_status=statuses.append)

        worker.start()
        try:
            deadline = time.monotonic() + 2
            saw_error = False
            recovered = False
            while time.monotonic() < deadline:
                saw_error = saw_error or any(status.startswith("Retrying after error") for status in statuses)
                if saw_error and worker.state.status == "Running":
                    recovered = True
                    break
                time.sleep(0.01)
        finally:
            worker.stop()
            worker.join(timeout=1)

        self.assertTrue(saw_error, "worker never recorded the injected heartbeat failure")
        self.assertTrue(recovered, "worker status never recovered to Running after the transient error cleared")
        self.assertEqual(worker.state.last_error, "")


if __name__ == "__main__":
    unittest.main()
