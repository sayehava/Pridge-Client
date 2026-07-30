# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import time
import unittest
from unittest.mock import Mock, patch

from pridge_client.api import ApiError, ReservedJob, ServerInstructions, parse_server_instructions
from pridge_client.config import ClientConfig, PrinterMapping, PrinterProfile, ServerConfig
from pridge_client.printers import PrinterError
from pridge_client.worker import PollingWorker, decode_payload, resolve_printer_name


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
            filename=None,
            job_name="Pridge 42",
            submission_method=None,
            explicit_renderer=None,
            fit_mode="fit",
            raw_header_template="",
            raw_footer_template="",
            raw_paper_width_dots=384,
            raw_chars_per_line=32,
            receipt_scope_key="",
        )
        client.report_printed.assert_called_once_with("42")

    def test_server_specific_profile_overrides_the_global_default(self) -> None:
        server = ServerConfig(
            id="office",
            default_printer="Office Driver",
            printer_profiles={
                "Office Driver": PrinterProfile(mode="system_driver", submission_method="pdfium"),
            },
        )
        config = ClientConfig(
            server_url="https://example.test",
            servers=[server],
            printer_profiles={
                "Office Driver": PrinterProfile(mode="system_driver", submission_method="direct_pdf"),
            },
        )
        printer_manager = Mock()
        client = Mock()
        worker = PollingWorker(config, "token", printer_manager=printer_manager)
        job = ReservedJob(job_id="42", payload_base64="JVBERg==", content_type="application/pdf")

        worker._process_job(client, job)

        printer_manager.print_job.assert_called_once_with(
            "Office Driver",
            b"%PDF",
            mode="system_driver",
            driver_settings={},
            content_type="application/pdf",
            filename=None,
            job_name="Pridge 42",
            submission_method="pdfium",
            explicit_renderer=None,
            fit_mode="fit",
            raw_header_template="",
            raw_footer_template="",
            raw_paper_width_dots=384,
            raw_chars_per_line=32,
            receipt_scope_key="",
        )

    def test_job_history_entries_carry_the_printer_name_on_success(self) -> None:
        server = ServerConfig(id="office", default_printer="Office Driver")
        config = ClientConfig(server_url="https://example.test", servers=[server])
        printer_manager = Mock()
        client = Mock()
        entries = []
        worker = PollingWorker(config, "token", printer_manager=printer_manager, on_job=entries.append)
        job = ReservedJob(job_id="42", payload_base64="JVBERg==", content_type="application/pdf")

        worker._process_job(client, job)

        printed = [entry for entry in entries if entry.status == "printed"]
        self.assertEqual(len(printed), 1)
        self.assertEqual(printed[0].printer_name, "Office Driver")

    def test_job_history_entries_carry_the_printer_name_on_failure(self) -> None:
        server = ServerConfig(id="office", default_printer="Office Driver")
        config = ClientConfig(server_url="https://example.test", servers=[server])
        printer_manager = Mock()
        printer_manager.print_job.side_effect = PrinterError("no paper")
        client = Mock()
        entries = []
        worker = PollingWorker(config, "token", printer_manager=printer_manager, on_job=entries.append)
        job = ReservedJob(job_id="42", payload_base64="JVBERg==", content_type="application/pdf")

        worker._process_job(client, job)

        failed = [entry for entry in entries if entry.status == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].printer_name, "Office Driver")


class WorkerReceiptMappingScopeTests(unittest.TestCase):
    """Receipt Composer content (template + counters) is scoped to the
    mapping a job arrived through, not to the local printer it targets."""

    def test_uses_the_mapping_s_own_template_and_a_mapping_scoped_key(self) -> None:
        server = ServerConfig(
            id="office",
            printer_mappings=[
                PrinterMapping(
                    remote_printer_id="kitchen-1",
                    local_printer_name="Kitchen Printer",
                    raw_header_template="[bold]Kitchen[/bold]",
                    raw_footer_template="[cut:full]",
                    raw_paper_width_dots=576,
                    raw_chars_per_line=48,
                )
            ],
        )
        config = ClientConfig(server_url="https://example.test", servers=[server])
        printer_manager = Mock()
        client = Mock()
        worker = PollingWorker(config, "token", printer_manager=printer_manager)
        job = ReservedJob(
            job_id="42",
            payload_base64="JVBERg==",
            content_type="application/pdf",
            remote_printer_id="kitchen-1",
        )

        worker._process_job(client, job)

        _args, kwargs = printer_manager.print_job.call_args
        self.assertEqual(kwargs["raw_header_template"], "[bold]Kitchen[/bold]")
        self.assertEqual(kwargs["raw_footer_template"], "[cut:full]")
        self.assertEqual(kwargs["raw_paper_width_dots"], 576)
        self.assertEqual(kwargs["raw_chars_per_line"], 48)
        self.assertEqual(kwargs["receipt_scope_key"], "office::kitchen-1")

    def test_two_mappings_on_the_same_local_printer_get_independent_scope_keys(self) -> None:
        server = ServerConfig(
            id="office",
            printer_mappings=[
                PrinterMapping(
                    remote_printer_id="kitchen-1",
                    local_printer_name="Shared Printer",
                    raw_header_template="[bold]Kitchen[/bold]",
                ),
                PrinterMapping(
                    remote_printer_id="register-1",
                    local_printer_name="Shared Printer",
                    raw_header_template="[bold]Register[/bold]",
                ),
            ],
        )
        config = ClientConfig(server_url="https://example.test", servers=[server])
        printer_manager = Mock()
        client = Mock()
        worker = PollingWorker(config, "token", printer_manager=printer_manager)

        worker._process_job(
            client,
            ReservedJob(job_id="1", payload_base64="JVBERg==", content_type="application/pdf", remote_printer_id="kitchen-1"),
        )
        worker._process_job(
            client,
            ReservedJob(job_id="2", payload_base64="JVBERg==", content_type="application/pdf", remote_printer_id="register-1"),
        )

        first_kwargs = printer_manager.print_job.call_args_list[0].kwargs
        second_kwargs = printer_manager.print_job.call_args_list[1].kwargs
        self.assertEqual(first_kwargs["receipt_scope_key"], "office::kitchen-1")
        self.assertEqual(first_kwargs["raw_header_template"], "[bold]Kitchen[/bold]")
        self.assertEqual(second_kwargs["receipt_scope_key"], "office::register-1")
        self.assertEqual(second_kwargs["raw_header_template"], "[bold]Register[/bold]")

    def test_job_with_no_matching_mapping_gets_a_blank_template_and_no_scope_key(self) -> None:
        server = ServerConfig(id="office", default_printer="Fallback Printer")
        config = ClientConfig(server_url="https://example.test", servers=[server])
        printer_manager = Mock()
        client = Mock()
        worker = PollingWorker(config, "token", printer_manager=printer_manager)
        job = ReservedJob(job_id="42", payload_base64="JVBERg==", content_type="application/pdf")

        worker._process_job(client, job)

        _args, kwargs = printer_manager.print_job.call_args
        self.assertEqual(kwargs["raw_header_template"], "")
        self.assertEqual(kwargs["raw_footer_template"], "")
        self.assertEqual(kwargs["receipt_scope_key"], "")


class WorkerStatusRecoveryTests(unittest.TestCase):
    @patch("pridge_client.worker.PridgeClient")
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


class WorkerCompatibilityWarningTests(unittest.TestCase):
    @patch("pridge_client.worker.PridgeClient")
    def test_compatibility_warning_is_copied_from_the_client_onto_worker_state(self, client_cls) -> None:
        client = Mock()
        client.heartbeat.return_value = None
        client.reserve_job.return_value = None
        client.last_instructions = ServerInstructions()
        client.compatibility_warning = "This client (v1.2.1) is older than this server (v2.0.0). Please update the client."
        client_cls.return_value = client

        config = ClientConfig(
            server_url="https://example.test",
            polling_interval_seconds=0,
            heartbeat_interval_seconds=0,
        )
        worker = PollingWorker(config, "token")

        worker.start()
        try:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not worker.state.compatibility_warning:
                time.sleep(0.01)
        finally:
            worker.stop()
            worker.join(timeout=1)

        self.assertEqual(worker.state.compatibility_warning, client.compatibility_warning)


if __name__ == "__main__":
    unittest.main()
