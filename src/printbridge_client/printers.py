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
        mode: str = "raw",
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
