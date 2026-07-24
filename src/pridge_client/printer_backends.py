# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
import platform
import re
import subprocess
from typing import Mapping

from pridge_client.printers import (
    DriverChoice,
    DriverOption,
    Printer,
    PrinterCapabilities,
    PrinterError,
)


logger = logging.getLogger(__name__)


def create_backend(system: str):
    if system == "Windows":
        return WindowsPrinterBackend()
    if system in {"Linux", "Darwin"}:
        return PosixPrinterBackend(system)
    return UnsupportedPrinterBackend(system)


class UnsupportedPrinterBackend:
    def __init__(self, system: str) -> None:
        self.system = system

    def list_printers(self) -> list[Printer]:
        return []

    def get_capabilities(self, printer_name: str) -> PrinterCapabilities:
        raise PrinterError(f"Unsupported platform: {self.system}")

    def open_driver_settings(self, printer_name: str) -> None:
        raise PrinterError(f"Unsupported platform: {self.system}")

    def print_raw(self, printer_name: str, data: bytes, job_name: str) -> None:
        raise PrinterError(f"Unsupported platform: {self.system}")

    def print_driver_pdf(
        self,
        printer_name: str,
        pdf_data: bytes,
        settings: Mapping[str, str],
        job_name: str,
        submission_method: str = "direct_pdf",
    ) -> None:
        raise PrinterError(f"Unsupported platform: {self.system}")


class PosixPrinterBackend:
    def __init__(self, system: str) -> None:
        self.system = system

    def list_printers(self) -> list[Printer]:
        if self.system == "Linux":
            try:
                import cups
            except ImportError:
                pass
            else:
                try:
                    connection = cups.Connection()
                    default_name = connection.getDefault() or ""
                    printers = [
                        Printer(name=name, is_default=name == default_name, system_driver_available=True)
                        for name in connection.getPrinters().keys()
                    ]
                    return sorted(printers, key=lambda printer: printer.name.casefold())
                except Exception as exc:
                    logger.warning("CUPS printer discovery failed: %s", _safe_backend_error(exc))
        return self._list_with_lpstat()

    def _list_with_lpstat(self) -> list[Printer]:
        completed = subprocess.run(
            ["lpstat", "-p", "-d"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if completed.returncode != 0:
            raise PrinterError("Could not list printers with the operating system print service.")

        default_name = ""
        names: list[str] = []
        for line in completed.stdout.splitlines():
            if line.startswith("system default destination:"):
                default_name = line.split(":", 1)[1].strip()
            elif line.startswith("printer "):
                parts = line.split()
                if len(parts) >= 2:
                    names.append(parts[1])
        return sorted(
            [
                Printer(name=name, is_default=name == default_name, system_driver_available=True)
                for name in names
            ],
            key=lambda printer: printer.name.casefold(),
        )

    def get_capabilities(self, printer_name: str) -> PrinterCapabilities:
        self._require_printer(printer_name)
        completed = subprocess.run(
            ["lpoptions", "-p", printer_name, "-l"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if completed.returncode != 0:
            return PrinterCapabilities(
                printer_name=printer_name,
                system_driver_available=True,
                driver_name="System print service",
            )
        return PrinterCapabilities(
            printer_name=printer_name,
            system_driver_available=True,
            driver_name="CUPS",
            options=parse_lpoptions(completed.stdout),
        )

    def open_driver_settings(self, printer_name: str) -> None:
        raise PrinterError("Use the driver options shown in Pridge Client for this printer.")

    def print_raw(self, printer_name: str, data: bytes, job_name: str) -> None:
        self._require_printer(printer_name)
        completed = subprocess.run(
            ["lp", "-d", printer_name, "-t", job_name, "-o", "raw"],
            input=data,
            check=False,
            capture_output=True,
            timeout=60,
        )
        if completed.returncode != 0:
            raise PrinterError("Could not submit raw print job.")

    def print_driver_pdf(
        self,
        printer_name: str,
        pdf_data: bytes,
        settings: Mapping[str, str],
        job_name: str,
        submission_method: str = "direct_pdf",
    ) -> None:
        if submission_method == "pdfium":
            self._print_pdf_via_pdfium(printer_name, pdf_data, settings, job_name)
        else:
            self._print_pdf_direct(printer_name, pdf_data, settings, job_name)

    def _print_pdf_direct(
        self,
        printer_name: str,
        pdf_data: bytes,
        settings: Mapping[str, str],
        job_name: str,
    ) -> None:
        self._require_printer(printer_name)
        command = ["lp", "-d", printer_name, "-t", job_name]
        for option_id, value_id in settings.items():
            command.extend(["-o", f"{option_id}={value_id}"])
        command.extend(["-o", "document-format=application/pdf"])
        completed = subprocess.run(
            command,
            input=pdf_data,
            check=False,
            capture_output=True,
            timeout=120,
        )
        if completed.returncode != 0:
            raise PrinterError("CUPS rejected the PDF print job.")
        logger.info("Direct PDF submitted to CUPS queue %s", printer_name)

    def _print_pdf_via_pdfium(
        self,
        printer_name: str,
        pdf_data: bytes,
        settings: Mapping[str, str],
        job_name: str,
    ) -> None:
        from pridge_client.pdfium_service import PDFiumRenderService

        svc = PDFiumRenderService()
        rendered_pages = svc.render_pages(pdf_data, target_dpi=300.0)
        if not rendered_pages:
            raise PrinterError("PDFium produced no pages from the document.")

        if self.system == "Darwin":
            self._macos_print_rendered_pages(printer_name, rendered_pages, settings, job_name)
        else:
            self._linux_print_rendered_pages(printer_name, rendered_pages, settings, job_name)

    def _macos_print_rendered_pages(self, printer_name, rendered_pages, settings, job_name):
        import io
        try:
            from PIL import Image
        except ImportError as exc:
            raise PrinterError("PDFium rendered-page printing requires Pillow.") from exc

        # Convert rendered pages to a multi-page PDF via Pillow and submit directly
        images = []
        for page in rendered_pages:
            img = Image.frombytes(
                "RGBA" if page.has_alpha else "RGB",
                (page.width_px, page.height_px),
                page.data,
                "raw",
                "BGRA" if page.has_alpha else "BGR",
            )
            images.append(img.convert("RGB"))

        buf = io.BytesIO()
        if images:
            images[0].save(
                buf,
                format="PDF",
                save_all=True,
                append_images=images[1:],
                resolution=rendered_pages[0].dpi,
            )
        pdf_data = buf.getvalue()
        self._print_pdf_direct(printer_name, pdf_data, settings, job_name)

    def _linux_print_rendered_pages(self, printer_name, rendered_pages, settings, job_name):
        # Same approach as macOS: re-wrap rendered pages as PDF and submit via CUPS
        self._macos_print_rendered_pages(printer_name, rendered_pages, settings, job_name)

    def _require_printer(self, printer_name: str) -> None:
        if printer_name not in {printer.name for printer in self.list_printers()}:
            raise PrinterError("The selected printer is no longer available.")


class WindowsPrinterBackend:
    def list_printers(self) -> list[Printer]:
        win32print = _load_win32print()
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
                printers.append(
                    Printer(name=name, is_default=name == default_name, system_driver_available=True)
                )
        return sorted(printers, key=lambda printer: printer.name.casefold())

    def get_capabilities(self, printer_name: str) -> PrinterCapabilities:
        win32print = _load_win32print()
        handle = self._open_printer(win32print, printer_name)
        try:
            info = win32print.GetPrinter(handle, 2)
            driver_name = str(info.get("pDriverName", "")).strip()
        finally:
            win32print.ClosePrinter(handle)
        return PrinterCapabilities(
            printer_name=printer_name,
            system_driver_available=bool(driver_name),
            driver_name=driver_name,
            supports_native_dialog=bool(driver_name),
        )

    def open_driver_settings(self, printer_name: str) -> None:
        win32print = _load_win32print()
        handle = self._open_printer(win32print, printer_name)
        win32print.ClosePrinter(handle)
        completed = subprocess.run(
            ["rundll32.exe", "printui.dll,PrintUIEntry", "/e", "/n", printer_name],
            check=False,
            capture_output=True,
            timeout=300,
        )
        if completed.returncode != 0:
            raise PrinterError("Could not open the installed printer driver's settings.")

    def print_raw(self, printer_name: str, data: bytes, job_name: str) -> None:
        win32print = _load_win32print()
        handle = self._open_printer(win32print, printer_name)
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

    def print_driver_pdf(
        self,
        printer_name: str,
        pdf_data: bytes,
        settings: Mapping[str, str],
        job_name: str,
        submission_method: str = "pdfium",
    ) -> None:
        _windows_gdi_print_pdf(pdf_data, printer_name, settings, job_name)

    @staticmethod
    def _open_printer(win32print, printer_name: str):
        try:
            return win32print.OpenPrinter(printer_name)
        except Exception as exc:
            raise PrinterError("The selected printer is no longer available.") from exc


def _windows_gdi_print_pdf(
    pdf_data: bytes,
    printer_name: str,
    settings: Mapping[str, str],
    job_name: str,
) -> None:
    try:
        import win32ui
        import win32con
    except ImportError as exc:
        raise PrinterError("Windows system-driver printing requires pywin32.") from exc

    try:
        from PIL import Image, ImageWin
    except ImportError as exc:
        raise PrinterError("Windows system-driver printing requires Pillow.") from exc

    from pridge_client.pdfium_service import PDFiumRenderService

    svc = PDFiumRenderService()
    if not svc.is_available():
        raise PrinterError(
            "Windows system-driver printing requires pypdfium2."
            " It must be included in the Pridge Client installation."
        )

    dc = win32ui.CreateDC()
    try:
        dc.CreatePrinterDC(printer_name)
    except Exception as exc:
        raise PrinterError("Could not create a printer device context.") from exc

    try:
        dpi_x = dc.GetDeviceCaps(win32con.LOGPIXELSX)
        dpi_y = dc.GetDeviceCaps(win32con.LOGPIXELSY)
        target_dpi = float(max(dpi_x, dpi_y, 72))
        print_w = dc.GetDeviceCaps(win32con.HORZRES)
        print_h = dc.GetDeviceCaps(win32con.VERTRES)

        rendered_pages = svc.render_pages(pdf_data, target_dpi=target_dpi, pixel_format="BGRA")
        if not rendered_pages:
            raise PrinterError("PDFium produced no pages from the document.")

        dc.StartDoc(job_name)
        try:
            for page in rendered_pages:
                dc.StartPage()
                try:
                    img = Image.frombytes(
                        "RGBA",
                        (page.width_px, page.height_px),
                        page.data,
                        "raw",
                        "BGRA",
                    ).convert("RGB")

                    scale = min(print_w / page.width_px, print_h / page.height_px)
                    dst_w = int(page.width_px * scale)
                    dst_h = int(page.height_px * scale)
                    dst_x = (print_w - dst_w) // 2
                    dst_y = (print_h - dst_h) // 2

                    if abs(scale - 1.0) > 0.01:
                        img = img.resize((dst_w, dst_h), Image.LANCZOS)

                    dib = ImageWin.Dib(img)
                    dib.draw(dc.GetSafeHdc(), (dst_x, dst_y, dst_x + dst_w, dst_y + dst_h))
                    logger.debug(
                        "Windows GDI: drew page %dx%d at (%d,%d)+%dx%d",
                        page.width_px, page.height_px, dst_x, dst_y, dst_w, dst_h,
                    )
                finally:
                    dc.EndPage()
        except Exception:
            dc.AbortDoc()
            raise
        else:
            dc.EndDoc()
            logger.info("Windows GDI print job '%s' submitted to %s", job_name, printer_name)
    finally:
        dc.DeleteDC()


def parse_lpoptions(output: str) -> tuple[DriverOption, ...]:
    options: list[DriverOption] = []
    seen: set[str] = set()
    for raw_line in output.splitlines():
        if ":" not in raw_line:
            continue
        raw_option, raw_choices = raw_line.split(":", 1)
        option_id, separator, option_label = raw_option.strip().partition("/")
        option_id = option_id.strip()
        if not option_id or option_id in seen:
            continue
        choices: list[DriverChoice] = []
        choice_ids: set[str] = set()
        default = ""
        for token in raw_choices.split():
            raw_id, choice_separator, raw_label = token.partition("/")
            selected = raw_id.startswith("*")
            choice_id = raw_id.removeprefix("*").strip()
            if not choice_id or choice_id in choice_ids:
                continue
            label = raw_label.strip().replace("_", " ") if choice_separator else choice_id
            choices.append(DriverChoice(id=choice_id, label=label or choice_id))
            choice_ids.add(choice_id)
            if selected:
                default = choice_id
        if not choices:
            continue
        if not default:
            default = choices[0].id
        options.append(
            DriverOption(
                id=option_id,
                label=option_label.strip() or option_id,
                choices=tuple(choices),
                default=default,
            )
        )
        seen.add(option_id)
    return tuple(options)


def _load_win32print():
    try:
        import win32print
    except ImportError as exc:
        raise PrinterError("Windows printing requires pywin32.") from exc
    return win32print


def _safe_backend_error(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__
