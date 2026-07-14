# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
import platform
import subprocess
from dataclasses import dataclass


logger = logging.getLogger(__name__)


class PrinterError(RuntimeError):
    pass


@dataclass(frozen=True)
class Printer:
    name: str
    is_default: bool = False


class PrinterManager:
    def __init__(self) -> None:
        self.system = platform.system()

    def list_printers(self) -> list[Printer]:
        if self.system == "Windows":
            return _list_windows_printers()
        if self.system == "Linux":
            return _list_linux_printers()
        if self.system == "Darwin":
            return _list_posix_printers()
        return []

    def print_raw(self, printer_name: str, data: bytes, job_name: str = "Pridge Job") -> None:
        if not printer_name:
            raise PrinterError("No printer is selected.")
        if not data:
            raise PrinterError("Print payload is empty.")

        logger.info("Sending raw job to printer %s", printer_name)
        if self.system == "Windows":
            _print_windows_raw(printer_name, data, job_name)
        elif self.system in {"Linux", "Darwin"}:
            _print_posix_raw(printer_name, data, job_name)
        else:
            raise PrinterError(f"Unsupported platform: {self.system}")


def _list_windows_printers() -> list[Printer]:
    try:
        import win32print
    except ImportError as exc:
        raise PrinterError("Windows printer discovery requires pywin32.") from exc

    default_name = ""
    try:
        default_name = win32print.GetDefaultPrinter()
    except Exception:
        pass

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    printers = []
    for item in win32print.EnumPrinters(flags):
        name = item[2]
        if name:
            printers.append(Printer(name=name, is_default=name == default_name))
    return sorted(printers, key=lambda printer: printer.name.lower())


def _list_linux_printers() -> list[Printer]:
    try:
        import cups
    except ImportError:
        return _list_posix_printers()

    connection = cups.Connection()
    default_name = connection.getDefault() or ""
    printers = [
        Printer(name=name, is_default=name == default_name)
        for name in connection.getPrinters().keys()
    ]
    return sorted(printers, key=lambda printer: printer.name.lower())


def _list_posix_printers() -> list[Printer]:
    completed = subprocess.run(
        ["lpstat", "-p", "-d"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        raise PrinterError("Could not list printers with lpstat.")

    default_name = ""
    printers: list[Printer] = []
    for line in completed.stdout.splitlines():
        if line.startswith("system default destination:"):
            default_name = line.split(":", 1)[1].strip()
        elif line.startswith("printer "):
            parts = line.split()
            if len(parts) >= 2:
                printers.append(Printer(name=parts[1]))

    return sorted(
        [Printer(name=printer.name, is_default=printer.name == default_name) for printer in printers],
        key=lambda printer: printer.name.lower(),
    )


def _print_windows_raw(printer_name: str, data: bytes, job_name: str) -> None:
    try:
        import win32print
    except ImportError as exc:
        raise PrinterError("Windows RAW printing requires pywin32.") from exc

    handle = win32print.OpenPrinter(printer_name)
    try:
        job_id = win32print.StartDocPrinter(handle, 1, (job_name, None, "RAW"))
        try:
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, data)
            win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
        logger.info("Windows raw print job %s submitted", job_id)
    finally:
        win32print.ClosePrinter(handle)


def _print_posix_raw(printer_name: str, data: bytes, job_name: str) -> None:
    completed = subprocess.run(
        ["lp", "-d", printer_name, "-t", job_name, "-o", "raw"],
        input=data,
        check=False,
        capture_output=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise PrinterError("Could not submit raw print job.")
