# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import unittest
from types import SimpleNamespace

from pridge_client.printer_backends import (
    _windows_duplex_option,
    _windows_job_devmode,
    _windows_paper_size_option,
)


class FakeWin32Con:
    DC_PAPERNAMES = 16
    DC_PAPERS = 2
    DC_DUPLEX = 7
    DM_PAPERSIZE = 0x00000002
    DM_DUPLEX = 0x00001000
    DM_IN_BUFFER = 8
    DM_OUT_BUFFER = 2
    DMDUP_SIMPLEX = 1
    DMDUP_VERTICAL = 2
    DMDUP_HORIZONTAL = 3


class FakeWin32Print:
    """Stands in for pywin32's win32print module. DeviceCapabilities and
    DocumentProperties are dependency-injected into the functions under test
    specifically so this logic can be verified without pywin32 installed or a
    real Windows printer - both unavailable in this environment.
    """

    def __init__(self, *, paper_names=None, paper_ids=None, duplex_supported=0, raises=None):
        self.paper_names = paper_names or []
        self.paper_ids = paper_ids or []
        self.duplex_supported = duplex_supported
        self.raises = raises
        self.document_properties_calls: list[tuple] = []

    def DeviceCapabilities(self, printer_name, port_name, capability):
        if self.raises is not None:
            raise self.raises
        if capability == FakeWin32Con.DC_PAPERNAMES:
            return list(self.paper_names)
        if capability == FakeWin32Con.DC_PAPERS:
            return list(self.paper_ids)
        if capability == FakeWin32Con.DC_DUPLEX:
            return self.duplex_supported
        raise ValueError(f"Unexpected capability {capability}")

    def DocumentProperties(self, hwnd, handle, printer_name, devmode_out, devmode_in, mode):
        self.document_properties_calls.append((handle, printer_name, mode))
        return 0


class WindowsPaperSizeOptionTests(unittest.TestCase):
    def test_builds_option_from_matching_names_and_ids(self) -> None:
        win32print = FakeWin32Print(paper_names=["Letter", "A4"], paper_ids=[1, 9])
        devmode = SimpleNamespace(PaperSize=9)

        option = _windows_paper_size_option(win32print, FakeWin32Con, "Printer", "LPT1", devmode)

        self.assertIsNotNone(option)
        self.assertEqual(option.id, "PageSize")
        self.assertEqual({c.id: c.label for c in option.choices}, {"1": "Letter", "9": "A4"})
        self.assertEqual(option.default, "9")

    def test_default_falls_back_to_first_choice_when_devmode_value_unknown(self) -> None:
        win32print = FakeWin32Print(paper_names=["Letter", "A4"], paper_ids=[1, 9])
        devmode = SimpleNamespace(PaperSize=999)

        option = _windows_paper_size_option(win32print, FakeWin32Con, "Printer", "LPT1", devmode)

        self.assertEqual(option.default, "1")

    def test_none_devmode_falls_back_to_first_choice(self) -> None:
        win32print = FakeWin32Print(paper_names=["Letter"], paper_ids=[1])

        option = _windows_paper_size_option(win32print, FakeWin32Con, "Printer", "LPT1", None)

        self.assertEqual(option.default, "1")

    def test_mismatched_lengths_resolve_to_none(self) -> None:
        win32print = FakeWin32Print(paper_names=["Letter", "A4"], paper_ids=[1])

        option = _windows_paper_size_option(win32print, FakeWin32Con, "Printer", "LPT1", None)

        self.assertIsNone(option)

    def test_empty_capabilities_resolve_to_none(self) -> None:
        win32print = FakeWin32Print(paper_names=[], paper_ids=[])

        option = _windows_paper_size_option(win32print, FakeWin32Con, "Printer", "LPT1", None)

        self.assertIsNone(option)

    def test_device_capabilities_failure_resolves_to_none(self) -> None:
        win32print = FakeWin32Print(raises=RuntimeError("no such printer"))

        option = _windows_paper_size_option(win32print, FakeWin32Con, "Printer", "LPT1", None)

        self.assertIsNone(option)


class WindowsDuplexOptionTests(unittest.TestCase):
    def test_returns_none_when_duplex_unsupported(self) -> None:
        win32print = FakeWin32Print(duplex_supported=0)

        option = _windows_duplex_option(win32print, FakeWin32Con, "Printer", "LPT1", None)

        self.assertIsNone(option)

    def test_returns_three_choices_when_supported(self) -> None:
        win32print = FakeWin32Print(duplex_supported=1)
        devmode = SimpleNamespace(Duplex=FakeWin32Con.DMDUP_VERTICAL)

        option = _windows_duplex_option(win32print, FakeWin32Con, "Printer", "LPT1", devmode)

        self.assertIsNotNone(option)
        self.assertEqual(option.id, "Duplex")
        self.assertEqual({c.id for c in option.choices}, {"1", "2", "3"})
        self.assertEqual(option.default, "2")

    def test_defaults_to_simplex_when_devmode_missing(self) -> None:
        win32print = FakeWin32Print(duplex_supported=1)

        option = _windows_duplex_option(win32print, FakeWin32Con, "Printer", "LPT1", None)

        self.assertEqual(option.default, "1")


class WindowsJobDevmodeTests(unittest.TestCase):
    def _win32print_with_devmode(self, devmode):
        win32print = FakeWin32Print()
        win32print.GetPrinter = lambda handle, level: {"pDevMode": devmode}
        return win32print

    def test_applies_page_size_and_duplex_and_normalizes(self) -> None:
        devmode = SimpleNamespace(PaperSize=1, Duplex=1, Fields=0)
        win32print = self._win32print_with_devmode(devmode)

        result = _windows_job_devmode(win32print, FakeWin32Con, handle="H", printer_name="Printer", settings={"PageSize": "9", "Duplex": "2"})

        self.assertIs(result, devmode)
        self.assertEqual(devmode.PaperSize, 9)
        self.assertEqual(devmode.Duplex, 2)
        self.assertEqual(devmode.Fields, FakeWin32Con.DM_PAPERSIZE | FakeWin32Con.DM_DUPLEX)
        self.assertEqual(len(win32print.document_properties_calls), 1)
        _, _, mode = win32print.document_properties_calls[0]
        self.assertEqual(mode, FakeWin32Con.DM_IN_BUFFER | FakeWin32Con.DM_OUT_BUFFER)

    def test_no_matching_settings_skips_document_properties(self) -> None:
        devmode = SimpleNamespace(PaperSize=1, Duplex=1, Fields=0)
        win32print = self._win32print_with_devmode(devmode)

        result = _windows_job_devmode(win32print, FakeWin32Con, handle="H", printer_name="Printer", settings={})

        self.assertIs(result, devmode)
        self.assertEqual(win32print.document_properties_calls, [])

    def test_malformed_values_are_ignored(self) -> None:
        devmode = SimpleNamespace(PaperSize=1, Duplex=1, Fields=0)
        win32print = self._win32print_with_devmode(devmode)

        _windows_job_devmode(win32print, FakeWin32Con, handle="H", printer_name="Printer", settings={"PageSize": "not-a-number"})

        self.assertEqual(devmode.PaperSize, 1)
        self.assertEqual(win32print.document_properties_calls, [])

    def test_missing_devmode_resolves_to_none(self) -> None:
        win32print = self._win32print_with_devmode(None)

        result = _windows_job_devmode(win32print, FakeWin32Con, handle="H", printer_name="Printer", settings={"PageSize": "9"})

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
