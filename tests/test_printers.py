# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import unittest
from unittest.mock import Mock, patch

from printbridge_client.printer_backends import PosixPrinterBackend, parse_lpoptions
from printbridge_client.printers import (
    DriverChoice,
    DriverOption,
    Printer,
    PrinterCapabilities,
    PrinterError,
    PrinterManager,
    validate_driver_settings,
)


class DriverCapabilityTests(unittest.TestCase):
    def test_parses_cups_option_ids_labels_choices_and_defaults(self) -> None:
        capabilities = parse_lpoptions(
            "PageSize/Media Size: Letter/US_Letter *A4/A4\n"
            "Duplex/Two-Sided: *None/Off DuplexNoTumble/Long_Edge\n"
        )

        self.assertEqual([option.id for option in capabilities], ["PageSize", "Duplex"])
        self.assertEqual(capabilities[0].label, "Media Size")
        self.assertEqual(capabilities[0].default, "A4")
        self.assertEqual(capabilities[1].choices[1].label, "Long Edge")

    def test_validates_saved_settings_against_current_driver_choices(self) -> None:
        capabilities = PrinterCapabilities(
            printer_name="Office",
            system_driver_available=True,
            options=(
                DriverOption(
                    id="PageSize",
                    label="Media Size",
                    choices=(DriverChoice("A4", "A4"), DriverChoice("Letter", "Letter")),
                    default="A4",
                ),
            ),
        )

        settings = validate_driver_settings(capabilities, {"PageSize": "RemovedSize", "Unknown": "value"})

        self.assertEqual(settings, {"PageSize": "A4"})


class PrinterManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = PrinterManager.__new__(PrinterManager)
        self.manager.system = "Test"
        self.manager.backend = Mock()

    def test_raw_mode_preserves_payload_and_does_not_request_capabilities(self) -> None:
        payload = b"\x00\xff\r\n"

        self.manager.print_job("Labels", payload, mode="raw", job_name="Raw job")

        self.manager.backend.print_raw.assert_called_once_with("Labels", payload, "Raw job")
        self.manager.backend.get_capabilities.assert_not_called()

    def test_system_driver_mode_validates_and_submits_options(self) -> None:
        self.manager.backend.get_capabilities.return_value = PrinterCapabilities(
            printer_name="Labels",
            system_driver_available=True,
            options=(
                DriverOption(
                    id="Resolution",
                    label="Resolution",
                    choices=(DriverChoice("203dpi", "203 dpi"), DriverChoice("300dpi", "300 dpi")),
                    default="203dpi",
                ),
            ),
        )

        self.manager.print_job(
            "Labels",
            b"%PDF",
            mode="system_driver",
            driver_settings={"Resolution": "300dpi", "Removed": "value"},
            content_type="application/pdf",
            job_name="Driver job",
        )

        self.manager.backend.print_driver.assert_called_once_with(
            "Labels",
            b"%PDF",
            "application/pdf",
            {"Resolution": "300dpi"},
            "Driver job",
        )

    def test_rejects_system_driver_mode_when_no_driver_is_available(self) -> None:
        self.manager.backend.get_capabilities.return_value = PrinterCapabilities(
            printer_name="Labels",
            system_driver_available=False,
        )

        with self.assertRaises(PrinterError):
            self.manager.print_job("Labels", b"document", mode="system_driver")


class PosixPrinterBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = PosixPrinterBackend("Darwin")
        self.backend.list_printers = Mock(  # type: ignore[method-assign]
            return_value=[Printer("Labels", system_driver_available=True)]
        )

    @patch("printbridge_client.printer_backends.subprocess.run")
    def test_raw_submission_preserves_binary_payload(self, run) -> None:
        run.return_value = Mock(returncode=0)
        payload = b"\x1b@\x00\xff\r\n"

        self.backend.print_raw("Labels", payload, "Raw job")

        self.assertEqual(run.call_args.kwargs["input"], payload)
        self.assertEqual(run.call_args.args[0][-2:], ["-o", "raw"])

    @patch("printbridge_client.printer_backends.subprocess.run")
    def test_driver_submission_uses_exact_validated_option_ids(self, run) -> None:
        run.return_value = Mock(returncode=0)

        self.backend.print_driver(
            "Labels",
            b"%PDF",
            "application/pdf",
            {"PageSize": "w288h432", "CutMedia": "EndOfPage"},
            "Driver job",
        )

        command = run.call_args.args[0]
        self.assertIn("PageSize=w288h432", command)
        self.assertIn("CutMedia=EndOfPage", command)
        self.assertIn("document-format=application/pdf", command)
        self.assertNotIn("raw", command)


if __name__ == "__main__":
    unittest.main()
