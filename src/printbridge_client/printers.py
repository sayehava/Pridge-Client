# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass, field
from typing import Mapping


logger = logging.getLogger(__name__)


class PrinterError(RuntimeError):
    pass


@dataclass(frozen=True)
class Printer:
    name: str
    is_default: bool = False
    system_driver_available: bool = False


@dataclass(frozen=True)
class DriverChoice:
    id: str
    label: str

    def public(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label}


@dataclass(frozen=True)
class DriverOption:
    id: str
    label: str
    choices: tuple[DriverChoice, ...]
    default: str = ""

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "default": self.default,
            "choices": [choice.public() for choice in self.choices],
        }


@dataclass(frozen=True)
class PrinterCapabilities:
    printer_name: str
    system_driver_available: bool
    driver_name: str = ""
    options: tuple[DriverOption, ...] = field(default_factory=tuple)
    supports_native_dialog: bool = False

    def public(self, settings: Mapping[str, str] | None = None) -> dict[str, object]:
        return {
            "printer_name": self.printer_name,
            "system_driver_available": self.system_driver_available,
            "driver_name": self.driver_name,
            "supports_native_dialog": self.supports_native_dialog,
            "options": [option.public() for option in self.options],
            "settings": validate_driver_settings(self, settings or {}),
        }


class PrinterManager:
    def __init__(self, system: str | None = None) -> None:
        from printbridge_client.printer_backends import create_backend

        self.system = system or platform.system()
        self.backend = create_backend(self.system)

    def list_printers(self) -> list[Printer]:
        return self.backend.list_printers()

    def get_capabilities(self, printer_name: str) -> PrinterCapabilities:
        if not printer_name:
            raise PrinterError("No printer is selected.")
        return self.backend.get_capabilities(printer_name)

    def validate_driver_settings(
        self,
        printer_name: str,
        settings: Mapping[str, str],
    ) -> dict[str, str]:
        return validate_driver_settings(self.get_capabilities(printer_name), settings)

    def open_driver_settings(self, printer_name: str) -> None:
        if not printer_name:
            raise PrinterError("No printer is selected.")
        self.backend.open_driver_settings(printer_name)

    def print_job(
        self,
        printer_name: str,
        data: bytes,
        mode: str = "system_driver",
        driver_settings: Mapping[str, str] | None = None,
        content_type: str = "application/octet-stream",
        job_name: str = "Pridge Job",
    ) -> None:
        if not printer_name:
            raise PrinterError("No printer is selected.")
        if not data:
            raise PrinterError("Print payload is empty.")

        if mode == "raw":
            logger.info("Sending raw job to printer %s", printer_name)
            self.backend.print_raw(printer_name, data, job_name)
            return
        if mode != "system_driver":
            raise PrinterError("The configured printing mode is not supported.")

        capabilities = self.get_capabilities(printer_name)
        if not capabilities.system_driver_available:
            raise PrinterError("The selected printer does not have an available system driver.")
        settings = validate_driver_settings(capabilities, driver_settings or {})
        logger.info("Submitting system-driver job to printer %s", printer_name)
        self.backend.print_driver(printer_name, data, content_type, settings, job_name)

    def print_raw(self, printer_name: str, data: bytes, job_name: str = "Pridge Job") -> None:
        self.print_job(printer_name, data, mode="raw", job_name=job_name)

    def print_test_page(
        self,
        printer_name: str,
        mode: str,
        driver_settings: Mapping[str, str] | None = None,
    ) -> None:
        if mode != "system_driver":
            raise PrinterError("Test printing is available only in System Driver mode.")
        self.print_job(
            printer_name,
            create_test_page_pdf(),
            mode="system_driver",
            driver_settings=driver_settings,
            content_type="application/pdf",
            job_name="Pridge Test Page",
        )


def validate_driver_settings(
    capabilities: PrinterCapabilities,
    settings: Mapping[str, str],
) -> dict[str, str]:
    validated: dict[str, str] = {}
    for option in capabilities.options:
        allowed = {choice.id for choice in option.choices}
        selected = str(settings.get(option.id, option.default)).strip()
        if selected not in allowed:
            selected = option.default if option.default in allowed else ""
        if selected:
            validated[option.id] = selected
    return validated


def create_test_page_pdf() -> bytes:
    content = (
        b"BT\n"
        b"/F1 24 Tf\n"
        b"72 700 Td\n"
        b"(Pridge Client Test Page) Tj\n"
        b"0 -38 Td\n"
        b"/F1 12 Tf\n"
        b"(System driver printing is configured correctly.) Tj\n"
        b"ET\n"
    )
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"endstream",
    )
    document = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_number, value in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{object_number} 0 obj\n".encode("ascii"))
        document.extend(value)
        document.extend(b"\nendobj\n")
    xref_offset = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(document)
