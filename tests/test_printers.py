# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from pridge_client.plugins.discovery import renderer_plugins_dir
from pridge_client.printer_backends import PosixPrinterBackend, parse_lpoptions
from pridge_client.printers import (
    DriverChoice,
    DriverOption,
    Printer,
    PrinterCapabilities,
    PrinterError,
    PrinterManager,
    _page_size_for_option,
    create_test_page_pdf,
    validate_driver_settings,
)


FIXTURE_PLUGIN_DIR = Path(__file__).resolve().parent / "fixtures" / "example_renderer_plugin"


class PageSizeResolutionTests(unittest.TestCase):
    def test_resolves_common_ppd_keywords(self) -> None:
        self.assertEqual(_page_size_for_option("Letter"), (612.0, 792.0))
        self.assertEqual(_page_size_for_option("A4"), (595.0, 842.0))
        self.assertEqual(_page_size_for_option("a5"), (420.0, 595.0))

    def test_resolves_custom_cups_page_sizes(self) -> None:
        self.assertEqual(_page_size_for_option("Custom.300x400"), (300.0, 400.0))

    def test_resolves_bare_points_custom_size(self) -> None:
        self.assertEqual(_page_size_for_option("w288h432"), (288.0, 432.0))

    def test_resolves_pwg_self_describing_names(self) -> None:
        width, height = _page_size_for_option("na_letter_8.5x11in")
        self.assertAlmostEqual(width, 612.0, delta=1.0)
        self.assertAlmostEqual(height, 792.0, delta=1.0)

        width, height = _page_size_for_option("iso_a5_148x210mm")
        self.assertAlmostEqual(width, 420.0, delta=2.0)
        self.assertAlmostEqual(height, 595.0, delta=2.0)

    def test_returns_none_for_an_unrecognized_value(self) -> None:
        self.assertIsNone(_page_size_for_option("SomeWeirdMediaName"))
        self.assertIsNone(_page_size_for_option(""))


class DriverCapabilityTests(unittest.TestCase):
    def test_generates_a_complete_pdf_test_page(self) -> None:
        document = create_test_page_pdf()

        self.assertTrue(document.startswith(b"%PDF-1.4"))
        self.assertIn(b"PRIDGE TEST PAGE", document)
        self.assertIn(b"IF YOU CAN READ THIS CLEARLY, PRINTING WORKS", document)
        self.assertTrue(document.endswith(b"%%EOF\n"))

    def test_embeds_the_pridge_logo_as_an_image_xobject(self) -> None:
        document = create_test_page_pdf()

        self.assertIn(b"/Subtype /Image", document)

    def test_media_box_matches_the_requested_page_size(self) -> None:
        document = create_test_page_pdf(420.0, 595.0)

        self.assertIn(b"/MediaBox [0 0 420 595]", document)

    def test_defaults_to_letter_when_no_page_size_is_given(self) -> None:
        document = create_test_page_pdf()

        self.assertIn(b"/MediaBox [0 0 612 792]", document)
        self.assertIn(b"/Im1", document)

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
        from unittest.mock import MagicMock
        from pridge_client.renderers import (
            PDFValidationService,
            RendererSelectionService,
            build_default_registry,
        )
        self.manager = PrinterManager.__new__(PrinterManager)
        self.manager.system = "Test"
        self.manager.backend = Mock()
        self.manager._registry = build_default_registry()
        self.manager._validation = PDFValidationService()
        self.manager._renderer_selector = RendererSelectionService(
            self.manager._registry, self.manager._validation
        )

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
            create_test_page_pdf(),
            mode="system_driver",
            driver_settings={"Resolution": "300dpi", "Removed": "value"},
            content_type="application/pdf",
            job_name="Driver job",
        )

        call_args = self.manager.backend.print_driver_pdf.call_args
        self.assertEqual(call_args.args[0], "Labels")
        self.assertTrue(call_args.args[1].startswith(b"%PDF"))
        self.assertEqual(call_args.args[2], {"Resolution": "300dpi"})
        self.assertEqual(call_args.args[3], "Driver job")

    def test_print_job_passes_fit_mode_and_resolved_page_size_to_the_backend(self) -> None:
        self.manager.backend.get_capabilities.return_value = PrinterCapabilities(
            printer_name="Labels",
            system_driver_available=True,
            options=(
                DriverOption(
                    id="PageSize",
                    label="Page Size",
                    choices=(DriverChoice("A4", "A4"),),
                    default="A4",
                ),
            ),
        )

        self.manager.print_job(
            "Labels",
            create_test_page_pdf(),
            mode="system_driver",
            driver_settings={"PageSize": "A4"},
            content_type="application/pdf",
            fit_mode="actual_size",
        )

        call_kwargs = self.manager.backend.print_driver_pdf.call_args.kwargs
        self.assertEqual(call_kwargs["fit_mode"], "actual_size")
        self.assertEqual(call_kwargs["target_page_size_pt"], (595.0, 842.0))

    def test_rejects_system_driver_mode_when_no_driver_is_available(self) -> None:
        self.manager.backend.get_capabilities.return_value = PrinterCapabilities(
            printer_name="Labels",
            system_driver_available=False,
        )

        with self.assertRaises(PrinterError):
            self.manager.print_job("Labels", b"document", mode="system_driver")

    def test_an_unexpected_backend_error_is_surfaced_as_a_printer_error(self) -> None:
        self.manager.backend.get_capabilities.return_value = PrinterCapabilities(
            printer_name="Labels",
            system_driver_available=True,
        )
        self.manager.backend.print_driver_pdf.side_effect = AttributeError(
            "module 'pypdfium2' has no attribute 'BitmapType'"
        )

        with self.assertRaises(PrinterError):
            self.manager.print_job(
                "Labels",
                create_test_page_pdf(),
                mode="system_driver",
                content_type="application/pdf",
            )

    def test_submits_pdf_test_page_through_system_driver(self) -> None:
        self.manager.backend.get_capabilities.return_value = PrinterCapabilities(
            printer_name="Labels",
            system_driver_available=True,
        )

        self.manager.print_test_page("Labels", "system_driver")

        call_args = self.manager.backend.print_driver_pdf.call_args
        self.assertEqual(call_args.args[0], "Labels")
        self.assertTrue(call_args.args[1].startswith(b"%PDF-1.4"))
        self.assertEqual(call_args.args[2], {})
        self.assertEqual(call_args.args[3], "Pridge Test Page")

    def test_test_page_fits_the_printers_default_page_size(self) -> None:
        self.manager.backend.get_capabilities.return_value = PrinterCapabilities(
            printer_name="Labels",
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

        self.manager.print_test_page("Labels", "system_driver")

        pdf_data = self.manager.backend.print_driver_pdf.call_args.args[1]
        self.assertIn(b"/MediaBox [0 0 595 842]", pdf_data)

    def test_test_page_fits_an_explicit_page_size_override(self) -> None:
        self.manager.backend.get_capabilities.return_value = PrinterCapabilities(
            printer_name="Labels",
            system_driver_available=True,
            options=(
                DriverOption(
                    id="PageSize",
                    label="Media Size",
                    choices=(DriverChoice("A4", "A4"), DriverChoice("A5", "A5")),
                    default="A4",
                ),
            ),
        )

        self.manager.print_test_page("Labels", "system_driver", driver_settings={"PageSize": "A5"})

        pdf_data = self.manager.backend.print_driver_pdf.call_args.args[1]
        self.assertIn(b"/MediaBox [0 0 420 595]", pdf_data)

    def test_does_not_inject_a_generic_test_payload_in_raw_mode(self) -> None:
        with self.assertRaises(PrinterError):
            self.manager.print_test_page("Labels", "raw")

        self.manager.backend.print_raw.assert_not_called()


class PrinterManagerPluginLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        from pridge_client.renderers import PDFValidationService, RendererSelectionService, build_default_registry

        self.scratch = TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.config_dir = Path(self.scratch.name)

        self.manager = PrinterManager.__new__(PrinterManager)
        self.manager.system = "Test"
        self.manager.backend = Mock()
        self.manager._config_dir = self.config_dir
        self.manager._registry = build_default_registry()
        self.manager._third_party_renderer_ids = []
        self.manager._validation = PDFValidationService()
        self.manager._renderer_selector = RendererSelectionService(
            self.manager._registry, self.manager._validation
        )

    def test_install_makes_a_third_party_plugin_immediately_selectable(self) -> None:
        plugin_id = self.manager.install_renderer_plugin(FIXTURE_PLUGIN_DIR)

        self.assertEqual(plugin_id, "org.example.pridge.renderer.example")
        entry = self.manager.renderer_registry.get_entry(plugin_id)
        self.assertIsNotNone(entry)
        self.assertFalse(entry.is_builtin)
        self.assertIn(plugin_id, self.manager._third_party_renderer_ids)

    def test_remove_drops_the_plugin_from_the_live_registry(self) -> None:
        plugin_id = self.manager.install_renderer_plugin(FIXTURE_PLUGIN_DIR)

        self.manager.remove_renderer_plugin(plugin_id)

        self.assertIsNone(self.manager.renderer_registry.get_entry(plugin_id))
        self.assertNotIn(plugin_id, self.manager._third_party_renderer_ids)

    def test_rescan_does_not_duplicate_an_already_loaded_plugin(self) -> None:
        plugin_dir = renderer_plugins_dir(self.config_dir) / "example"
        shutil.copytree(FIXTURE_PLUGIN_DIR, plugin_dir)

        self.manager.rescan_renderer_plugins()
        self.manager.rescan_renderer_plugins()

        matches = [
            entry
            for entry in self.manager.renderer_registry.all_entries()
            if entry.plugin.plugin_id == "org.example.pridge.renderer.example"
        ]
        self.assertEqual(len(matches), 1)


class PosixPrinterBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = PosixPrinterBackend("Darwin")
        self.backend.list_printers = Mock(  # type: ignore[method-assign]
            return_value=[Printer("Labels", system_driver_available=True)]
        )

    @patch("pridge_client.printer_backends.subprocess.run")
    def test_driverless_queue_remains_available_when_no_ppd_options_are_reported(self, run) -> None:
        run.return_value = Mock(returncode=1, stdout="")

        capabilities = self.backend.get_capabilities("Labels")

        self.assertTrue(capabilities.system_driver_available)
        self.assertEqual(capabilities.options, ())

    @patch("pridge_client.printer_backends.subprocess.run")
    def test_raw_submission_preserves_binary_payload(self, run) -> None:
        run.return_value = Mock(returncode=0)
        payload = b"\x1b@\x00\xff\r\n"

        self.backend.print_raw("Labels", payload, "Raw job")

        self.assertEqual(run.call_args.kwargs["input"], payload)
        self.assertEqual(run.call_args.args[0][-2:], ["-o", "raw"])

    @patch("pridge_client.printer_backends.subprocess.run")
    def test_direct_pdf_submission_passes_options_and_pdf_format(self, run) -> None:
        run.return_value = Mock(returncode=0)

        self.backend.print_driver_pdf(
            "Labels",
            b"%PDF",
            {"PageSize": "w288h432", "CutMedia": "EndOfPage"},
            "Driver job",
            "direct_pdf",
        )

        command = run.call_args.args[0]
        self.assertIn("PageSize=w288h432", command)
        self.assertIn("CutMedia=EndOfPage", command)
        self.assertIn("document-format=application/pdf", command)
        self.assertNotIn("raw", command)

    @patch("pridge_client.printer_backends.subprocess.run")
    def test_direct_pdf_submission_requests_fit_to_page_scaling_by_default(self, run) -> None:
        run.return_value = Mock(returncode=0)

        self.backend.print_driver_pdf("Labels", b"%PDF", {}, "Driver job", "direct_pdf")

        command = run.call_args.args[0]
        self.assertIn("print-scaling=fit", command)

    @patch("pridge_client.printer_backends.subprocess.run")
    def test_direct_pdf_submission_disables_scaling_for_actual_size(self, run) -> None:
        run.return_value = Mock(returncode=0)

        self.backend.print_driver_pdf(
            "Labels", b"%PDF", {}, "Driver job", "direct_pdf", fit_mode="actual_size"
        )

        command = run.call_args.args[0]
        self.assertIn("print-scaling=none", command)


class FitImageToPageTests(unittest.TestCase):
    def test_downscales_and_centers_an_oversized_image(self) -> None:
        from PIL import Image

        from pridge_client.printer_backends import _fit_image_to_page

        source = Image.new("RGB", (1200, 1200), "black")

        result = _fit_image_to_page(source, dpi=300.0, target_page_size_pt=(216.0, 72.0))

        self.assertEqual(result.size, (900, 300))
        # Centered horizontally: scaled image is 300x300, target width is 900.
        self.assertEqual(result.getpixel((100, 150)), (255, 255, 255))
        self.assertEqual(result.getpixel((450, 150)), (0, 0, 0))

    def test_is_a_no_op_when_the_image_already_matches_the_target_size(self) -> None:
        from PIL import Image

        from pridge_client.printer_backends import _fit_image_to_page

        source = Image.new("RGB", (300, 300), "black")

        result = _fit_image_to_page(source, dpi=300.0, target_page_size_pt=(72.0, 72.0))

        self.assertIs(result, source)


if __name__ == "__main__":
    unittest.main()
