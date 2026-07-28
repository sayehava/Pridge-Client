# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
import platform
import re
import textwrap
import time
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Mapping

from pridge_client.version import __version__


logger = logging.getLogger(__name__)
_LOGO_PATH = Path(__file__).resolve().parent / "webui" / "assets" / "Logo.png"
_PAGE_WIDTH = 612
_PAGE_HEIGHT = 792
_MARGIN = 72

_PAGE_SIZES_PT: dict[str, tuple[float, float]] = {
    "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0),
    "executive": (522.0, 756.0),
    "statement": (396.0, 612.0),
    "folio": (612.0, 936.0),
    "tabloid": (792.0, 1224.0),
    "ledger": (1224.0, 792.0),
    "a3": (842.0, 1191.0),
    "a4": (595.0, 842.0),
    "a5": (420.0, 595.0),
    "a6": (298.0, 420.0),
    "b5": (499.0, 709.0),
}
_PWG_SIZE_RE = re.compile(r"_(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)(in|mm)$", re.IGNORECASE)
_CUSTOM_SIZE_RE = re.compile(r"^custom\.(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)", re.IGNORECASE)
_WH_POINTS_RE = re.compile(r"^w(\d+(?:\.\d+)?)h(\d+(?:\.\d+)?)$", re.IGNORECASE)


def _page_size_for_option(value_id: str) -> tuple[float, float] | None:
    """Resolve a CUPS/PPD PageSize option value (e.g. "A4", "Custom.420x595",
    or a PWG self-describing name like "iso_a5_148x210mm") to (width_pt, height_pt).
    Returns None for unrecognized values so callers can fall back to a default.
    """
    if not value_id:
        return None
    key = value_id.strip().lower()

    match = _CUSTOM_SIZE_RE.match(key)
    if match:
        return float(match.group(1)), float(match.group(2))

    match = _WH_POINTS_RE.match(key)
    if match:
        return float(match.group(1)), float(match.group(2))

    match = _PWG_SIZE_RE.search(key)
    if match:
        width, height, unit = match.groups()
        factor = 72.0 if unit.lower() == "in" else 72.0 / 25.4
        return float(width) * factor, float(height) * factor

    simplified = key.rsplit("_", 1)[-1] if "_" in key else key
    for candidate in (key, simplified):
        if candidate in _PAGE_SIZES_PT:
            return _PAGE_SIZES_PT[candidate]
    return None


# Reused by receipt_composer.shortcodes for the [cut:...]/[drawer]/[feed] tags,
# which superseded this module's own RAW header/footer preset resolution.
_RAW_MACRO_BYTES: dict[str, bytes] = {
    "full_cut": b"\x1d\x56\x00",
    "partial_cut": b"\x1d\x56\x01",
    "open_drawer": b"\x1b\x70\x00\x19\xfa",
    "feed": b"\x1b\x64\x04",
}


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
        from pridge_client.config import default_config_dir
        from pridge_client.plugins.discovery import register_third_party_renderers
        from pridge_client.printer_backends import create_backend
        from pridge_client.receipt_composer import ReceiptComposerPlugin, ReceiptComposerStore
        from pridge_client.renderers import (
            AppMappingRendererPlugin,
            AppMappingStore,
            PDFValidationService,
            RendererSelectionService,
            build_default_registry,
        )

        self.system = system or platform.system()
        self.backend = create_backend(self.system)
        self._config_dir = default_config_dir()
        self._registry = build_default_registry()
        self._app_mapping_store = AppMappingStore(self._config_dir)
        self._app_mapping_plugin = AppMappingRendererPlugin(self._app_mapping_store.load())
        self._registry.register(self._app_mapping_plugin, priority=100, is_builtin=True, category="Mapper")
        self._receipt_composer_store = ReceiptComposerStore(self._config_dir)
        self._receipt_composer_plugin = ReceiptComposerPlugin()
        self._registry.register(self._receipt_composer_plugin, priority=110, is_builtin=True, category="Receipts")
        self._third_party_renderer_ids = register_third_party_renderers(self._registry, self._config_dir)
        self._validation = PDFValidationService()
        self._renderer_selector = RendererSelectionService(self._registry, self._validation)

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
        content_type: str | None = None,
        filename: str | None = None,
        job_name: str = "Pridge Job",
        submission_method: str | None = None,
        explicit_renderer: str | None = None,
        fit_mode: str = "fit",
        raw_header_template: str = "",
        raw_footer_template: str = "",
        raw_paper_width_dots: int = 384,
        raw_chars_per_line: int = 32,
    ) -> None:
        from pridge_client.receipt_composer.shortcodes import render_template
        from pridge_client.renderers.base import RenderError, RenderOptions

        if not printer_name:
            raise PrinterError("No printer is selected.")
        if not data:
            raise PrinterError("Print payload is empty.")

        if mode == "raw":
            template_kwargs = {
                "printer_name": printer_name,
                "store": self._receipt_composer_store,
                "paper_width_dots": raw_paper_width_dots,
                "chars_per_line": raw_chars_per_line,
            }
            header = render_template(raw_header_template, **template_kwargs)
            footer = render_template(raw_footer_template, **template_kwargs)
            logger.info("Sending raw job to printer %s", printer_name)
            self.backend.print_raw(printer_name, header + data + footer, job_name)
            return
        if mode != "system_driver":
            raise PrinterError("The configured printing mode is not supported.")

        capabilities = self.get_capabilities(printer_name)
        if not capabilities.system_driver_available:
            raise PrinterError("The selected printer does not have an available system driver.")
        settings = validate_driver_settings(capabilities, driver_settings or {})

        try:
            plugin, reason = self._renderer_selector.select(
                data=data,
                mime_type=content_type or None,
                filename=filename or None,
                explicit_plugin_id=explicit_renderer or None,
            )
        except RenderError as exc:
            raise PrinterError(str(exc)) from exc

        options = RenderOptions()

        t0 = time.monotonic()
        try:
            pdf_data = plugin.render_to_pdf(
                data=data,
                mime_type=content_type or None,
                filename=filename or None,
                options=options,
            )
        except RenderError as exc:
            raise PrinterError(
                f"Renderer plugin {plugin.plugin_id} failed while converting the document: {exc}"
            ) from exc
        logger.info(
            f"Renderer {plugin.plugin_id} produced {len(pdf_data)} bytes in "
            f"{time.monotonic() - t0:.3f}s (reason={reason})"
        )

        try:
            self._validation.require_valid_pdf(pdf_data)
        except RenderError as exc:
            raise PrinterError(str(exc)) from exc

        method = submission_method or _default_submission_method(self.system)
        page_size_pt = self._resolve_selected_page_size(printer_name, settings)
        logger.info(f"Submitting system-driver job to printer {printer_name} (submission_method={method})")
        t0 = time.monotonic()
        try:
            self.backend.print_driver_pdf(
                printer_name, pdf_data, settings, job_name, method, fit_mode=fit_mode, target_page_size_pt=page_size_pt
            )
        except PrinterError:
            raise
        except Exception as exc:
            raise PrinterError(f"Printing failed: {exc}") from exc
        logger.info(f"Native submission of {len(pdf_data)} bytes completed in {time.monotonic() - t0:.3f}s")

    def print_raw(self, printer_name: str, data: bytes, job_name: str = "Pridge Job") -> None:
        self.print_job(printer_name, data, mode="raw", job_name=job_name)

    def print_test_page(
        self,
        printer_name: str,
        mode: str,
        driver_settings: Mapping[str, str] | None = None,
        submission_method: str | None = None,
        fit_mode: str = "fit",
        raw_header_template: str = "",
        raw_footer_template: str = "",
        raw_paper_width_dots: int = 384,
        raw_chars_per_line: int = 32,
    ) -> None:
        if mode == "raw":
            # Intentionally inert: no ESC @ reset (don't touch printer state
            # Pridge doesn't own) and no assumed cut — the header/footer
            # template under test is what should decide that, so this test
            # actually exercises the same real RAW path end to end.
            self.print_job(
                printer_name,
                _raw_test_body(raw_chars_per_line),
                mode="raw",
                job_name="Pridge Test Page",
                raw_header_template=raw_header_template,
                raw_footer_template=raw_footer_template,
                raw_paper_width_dots=raw_paper_width_dots,
                raw_chars_per_line=raw_chars_per_line,
            )
            return
        if mode != "system_driver":
            raise PrinterError("Test printing is available only in System Driver or RAW mode.")
        page_width_pt, page_height_pt = self._resolve_selected_page_size(printer_name, driver_settings)
        self.print_job(
            printer_name,
            create_test_page_pdf(page_width_pt, page_height_pt),
            mode="system_driver",
            driver_settings=driver_settings,
            content_type="application/pdf",
            job_name="Pridge Test Page",
            submission_method=submission_method,
            fit_mode=fit_mode,
        )

    def _resolve_selected_page_size(
        self,
        printer_name: str,
        driver_settings: Mapping[str, str] | None,
    ) -> tuple[float, float]:
        try:
            capabilities = self.get_capabilities(printer_name)
            page_size_option = next(
                (option for option in capabilities.options if option.id.lower() == "pagesize"), None
            )
            if page_size_option is not None:
                selected = (driver_settings or {}).get(page_size_option.id) or page_size_option.default
                resolved = _page_size_for_option(selected)
                if resolved is not None:
                    return resolved
        except Exception as exc:
            logger.debug("Could not resolve the selected paper size for %s: %s", printer_name, exc)
        return _PAGE_WIDTH, _PAGE_HEIGHT

    def install_renderer_plugin(self, source: Path) -> str:
        from pridge_client.plugins.installer import install_renderer_plugin

        plugin_id = install_renderer_plugin(source, self._config_dir)
        self.rescan_renderer_plugins()
        return plugin_id

    def remove_renderer_plugin(self, plugin_id: str) -> None:
        from pridge_client.plugins.installer import remove_renderer_plugin

        remove_renderer_plugin(plugin_id, self._config_dir)
        self.rescan_renderer_plugins()

    def rescan_renderer_plugins(self) -> None:
        from pridge_client.plugins.discovery import register_third_party_renderers

        for plugin_id in self._third_party_renderer_ids:
            self._registry.remove(plugin_id)
        for entry in self._registry.all_entries():
            if entry.load_error and not entry.is_builtin:
                self._registry.remove(entry.plugin.plugin_id)
        self._third_party_renderer_ids = register_third_party_renderers(self._registry, self._config_dir)

    @property
    def renderer_registry(self):
        return self._registry

    @property
    def app_mapping_plugin(self):
        return self._app_mapping_plugin

    @property
    def app_mapping_store(self):
        return self._app_mapping_store

    @property
    def receipt_composer_plugin(self):
        return self._receipt_composer_plugin

    @property
    def receipt_composer_store(self):
        return self._receipt_composer_store


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


def _raw_test_body(chars_per_line: int) -> bytes:
    width = max(1, chars_per_line)
    lines = [
        "PRIDGE TEST PAGE",
        "-" * width,
        "If you can read this clearly,",
        "RAW printing works.",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "",
    ]
    return ("\n".join(lines) + "\n").encode("ascii", errors="replace")


def create_test_page_pdf(page_width_pt: float = _PAGE_WIDTH, page_height_pt: float = _PAGE_HEIGHT) -> bytes:
    """A one-page PDF that a person, not just a log line, can use to confirm
    printing actually works: the Pridge logo plus large, unmissable status
    text, so a blank or garbled page is as obvious as a correct one.

    The layout is proportional to the given page size (points) so the test
    page always fits the printer's currently selected paper size instead of
    always being laid out for US Letter.
    """
    margin = max(24.0, min(72.0, min(page_width_pt, page_height_pt) * 0.1))
    reference_width = 612.0 - 2 * 72.0
    reference_height = 792.0 - 2 * 72.0
    available_width = page_width_pt - 2 * margin
    available_height = page_height_pt - 2 * margin
    scale = max(0.45, min(1.0, available_width / reference_width, available_height / reference_height))

    title_size = max(18.0, 34.0 * scale)
    status_size = max(12.0, 20.0 * scale)
    body_size = max(8.0, 12.0 * scale)
    footer_size = max(7.0, 9.0 * scale)
    logo_width = max(90.0, 170.0 * scale)

    logo = _logo_jpeg()

    title = "PRIDGE TEST PAGE"
    title_y = page_height_pt - margin
    content = bytearray(_text_op(title, "F2", title_size, _centered_x(title, title_size, 0.62, page_width_pt, margin), title_y))

    image_bottom = title_y - 30 * scale
    if logo is not None:
        jpeg_bytes, native_width, native_height = logo
        display_width = logo_width
        display_height = display_width * native_height / native_width
        x = (page_width_pt - display_width) / 2
        y = image_bottom - display_height
        content.extend(
            f"q\n{display_width:.2f} 0 0 {display_height:.2f} {x:.2f} {y:.2f} cm\n/Im1 Do\nQ\n".encode("ascii")
        )
        image_bottom = y
    else:
        image_bottom -= 20 * scale

    status = "IF YOU CAN READ THIS CLEARLY, PRINTING WORKS"
    status_y = image_bottom - 40 * scale
    content.extend(_text_op(status, "F2", status_size, _centered_x(status, status_size, 0.58, page_width_pt, margin), status_y))

    explanation = textwrap.wrap(
        "This page was generated locally by Pridge Client and submitted through the "
        "selected printer's installed system driver. If the logo, title, and this "
        "paragraph are all sharp and complete, System Driver printing is configured "
        "correctly for this printer. RAW-mode printers do not use this test page, "
        "because RAW jobs are sent unchanged in a device-specific printer language "
        "that Pridge Client never converts or interprets.",
        width=80,
    )
    text_y = status_y - 40 * scale
    for line in explanation:
        content.extend(_text_op(line, "F1", body_size, margin, text_y))
        text_y -= 16 * scale

    footer = f"Pridge Client {__version__}"
    footer_y = max(16.0, margin - 32.0)
    content.extend(_text_op(footer, "F1", footer_size, margin, footer_y))

    resources = b"/Font << /F1 4 0 R /F2 6 0 R >>"
    if logo is not None:
        resources = b"/Font << /F1 4 0 R /F2 6 0 R >> /XObject << /Im1 7 0 R >>"

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
        + f"{page_width_pt:g} {page_height_pt:g}".encode("ascii")
        + b"] /Resources << "
        + resources
        + b" >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + bytes(content) + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    if logo is not None:
        jpeg_bytes, native_width, native_height = logo
        objects.append(
            b"<< /Type /XObject /Subtype /Image /Width "
            + str(native_width).encode("ascii")
            + b" /Height "
            + str(native_height).encode("ascii")
            + b" /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length "
            + str(len(jpeg_bytes)).encode("ascii")
            + b" >>\nstream\n"
            + jpeg_bytes
            + b"\nendstream"
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


def _default_submission_method(system: str) -> str:
    if system == "Windows":
        return "pdfium"
    return "direct_pdf"


def _text_op(text: str, font: str, size: float, x: float, y: float) -> bytes:
    return (
        b"BT\n/"
        + font.encode("ascii")
        + f" {size:g} Tf\n{x:.2f} {y:.2f} Td\n(".encode("ascii")
        + _pdf_escape(text)
        + b") Tj\nET\n"
    )


def _pdf_escape(text: str) -> bytes:
    escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return escaped.encode("latin-1", errors="replace")


def _centered_x(text: str, size: float, average_width_em: float, page_width_pt: float, margin: float) -> float:
    width = len(text) * size * average_width_em
    return max(margin, (page_width_pt - width) / 2)


def _logo_jpeg() -> tuple[bytes, int, int] | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(_LOGO_PATH) as source:
            rgba = source.convert("RGBA")
            flattened = Image.new("RGB", rgba.size, (255, 255, 255))
            flattened.paste(rgba, mask=rgba.split()[3])
    except OSError as exc:
        logger.warning("Could not load the Pridge logo for the test page: %s", exc)
        return None
    buffer = BytesIO()
    flattened.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue(), flattened.width, flattened.height
