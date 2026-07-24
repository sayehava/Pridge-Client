# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import unittest

from pridge_client.printers import create_test_page_pdf
from pridge_client.renderers import (
    PRIDGE_RENDERER_API_VERSION,
    PDFValidationService,
    RenderError,
    RenderOptions,
    RendererRegistry,
    RendererSelectionService,
    build_default_registry,
)
from pridge_client.renderers.image_plugin import ImageRendererPlugin
from pridge_client.renderers.pdf_plugin import PdfRendererPlugin
from pridge_client.renderers.registry import RegistryEntry
from pridge_client.renderers.selection import _detect_mime_from_magic
from pridge_client.renderers.text_plugin import TextRendererPlugin


class RendererRegistryTests(unittest.TestCase):
    def test_registers_plugin_and_retrieves_it_by_id(self) -> None:
        registry = RendererRegistry()
        plugin = PdfRendererPlugin()
        registry.register(plugin, priority=0)

        entry = registry.get_entry("pridge.renderer.pdf")
        self.assertIsNotNone(entry)
        self.assertIs(entry.plugin, plugin)

    def test_enabled_plugins_returns_only_enabled_plugins_sorted_by_priority(self) -> None:
        registry = RendererRegistry()
        pdf = PdfRendererPlugin()
        img = ImageRendererPlugin()
        registry.register(img, priority=20)
        registry.register(pdf, priority=10)

        plugins = registry.enabled_plugins()
        self.assertEqual([p.plugin_id for p in plugins], [
            "pridge.renderer.pdf",
            "pridge.renderer.image",
        ])

    def test_disabled_plugin_is_excluded_from_enabled_list(self) -> None:
        registry = RendererRegistry()
        registry.register(PdfRendererPlugin(), priority=0)
        registry.set_enabled("pridge.renderer.pdf", False)

        self.assertEqual(registry.enabled_plugins(), [])

    def test_rejects_duplicate_plugin_ids(self) -> None:
        registry = RendererRegistry()
        registry.register(PdfRendererPlugin())
        with self.assertRaises(ValueError):
            registry.register(PdfRendererPlugin())

    def test_rejects_incompatible_api_version(self) -> None:
        class FuturePlugin:
            plugin_id = "test.future"
            display_name = "Future"
            version = "1.0.0"
            api_version = PRIDGE_RENDERER_API_VERSION + 1
            supported_mime_types: frozenset[str] = frozenset()
            supported_extensions: frozenset[str] = frozenset()

            def can_render(self, *, mime_type, filename, data):
                return False

            def render_to_pdf(self, *, data, mime_type, filename, options):
                return b""

        registry = RendererRegistry()
        with self.assertRaises(ValueError):
            registry.register(FuturePlugin())

    def test_register_error_records_broken_plugin_without_crashing(self) -> None:
        registry = RendererRegistry()
        registry.register_error("org.broken.plugin", "ImportError: no module", "/path/to/plugin")

        entries = registry.all_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].load_error, "ImportError: no module")
        self.assertEqual(registry.enabled_plugins(), [])

    def test_removes_plugin_by_id(self) -> None:
        registry = RendererRegistry()
        registry.register(PdfRendererPlugin())
        removed = registry.remove("pridge.renderer.pdf")
        self.assertTrue(removed)
        self.assertEqual(registry.enabled_plugins(), [])

    def test_priority_reordering_changes_selection_order(self) -> None:
        registry = RendererRegistry()
        registry.register(PdfRendererPlugin(), priority=10)
        registry.register(ImageRendererPlugin(), priority=20)
        registry.set_priority("pridge.renderer.image", 5)

        plugins = registry.enabled_plugins()
        self.assertEqual(plugins[0].plugin_id, "pridge.renderer.image")


class MagicByteDetectionTests(unittest.TestCase):
    def test_detects_pdf(self) -> None:
        self.assertEqual(_detect_mime_from_magic(b"%PDF-1.4 rest"), "application/pdf")

    def test_detects_png(self) -> None:
        self.assertEqual(_detect_mime_from_magic(b"\x89PNG\r\n\x1a\n..."), "image/png")

    def test_detects_jpeg(self) -> None:
        self.assertEqual(_detect_mime_from_magic(b"\xff\xd8\xff\xe0..."), "image/jpeg")

    def test_detects_gif(self) -> None:
        self.assertEqual(_detect_mime_from_magic(b"GIF89a..."), "image/gif")

    def test_detects_bmp(self) -> None:
        self.assertEqual(_detect_mime_from_magic(b"BM..."), "image/bmp")

    def test_detects_tiff_little_endian(self) -> None:
        self.assertEqual(_detect_mime_from_magic(b"II*\x00..."), "image/tiff")

    def test_detects_tiff_big_endian(self) -> None:
        self.assertEqual(_detect_mime_from_magic(b"MM\x00*..."), "image/tiff")

    def test_detects_webp(self) -> None:
        data = b"RIFF\x00\x00\x00\x00WEBP"
        self.assertEqual(_detect_mime_from_magic(data), "image/webp")

    def test_detects_svg_by_tag(self) -> None:
        self.assertEqual(_detect_mime_from_magic(b"<svg xmlns=..."), "image/svg+xml")

    def test_detects_svg_with_xml_declaration(self) -> None:
        data = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>'
        self.assertEqual(_detect_mime_from_magic(data), "image/svg+xml")

    def test_returns_none_for_unknown_binary(self) -> None:
        self.assertIsNone(_detect_mime_from_magic(b"\x00\x01\x02\x03\x04\x05\x06\x07"))


class RendererSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = build_default_registry()
        self.selector = RendererSelectionService(self.registry)
        self.valid_pdf = create_test_page_pdf()

    def test_selects_pdf_renderer_by_mime_type(self) -> None:
        plugin, reason = self.selector.select(
            data=self.valid_pdf, mime_type="application/pdf"
        )
        self.assertEqual(plugin.plugin_id, "pridge.renderer.pdf")
        self.assertEqual(reason, "mime:application/pdf")

    def test_selects_pdf_renderer_by_magic_bytes(self) -> None:
        plugin, reason = self.selector.select(data=self.valid_pdf)
        self.assertEqual(plugin.plugin_id, "pridge.renderer.pdf")
        self.assertIn("magic-byte", reason)

    def test_selects_image_renderer_by_extension(self) -> None:
        plugin, reason = self.selector.select(
            data=b"\xff\xd8\xff\xe0", filename="photo.jpg"
        )
        self.assertEqual(plugin.plugin_id, "pridge.renderer.image")
        self.assertEqual(reason, "extension:.jpg")

    def test_selects_text_renderer_by_mime_type(self) -> None:
        plugin, reason = self.selector.select(
            data=b"Hello world\n", mime_type="text/plain"
        )
        self.assertEqual(plugin.plugin_id, "pridge.renderer.text")
        self.assertEqual(reason, "mime:text/plain")

    def test_selects_svg_renderer_by_mime_type(self) -> None:
        plugin, reason = self.selector.select(
            data=b"<svg></svg>", mime_type="image/svg+xml"
        )
        self.assertEqual(plugin.plugin_id, "pridge.renderer.svg")
        self.assertEqual(reason, "mime:image/svg+xml")

    def test_selects_svg_renderer_by_magic_bytes(self) -> None:
        data = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        plugin, reason = self.selector.select(data=data)
        self.assertEqual(plugin.plugin_id, "pridge.renderer.svg")
        self.assertIn("magic-byte", reason)

    def test_explicit_plugin_id_overrides_detection(self) -> None:
        plugin, reason = self.selector.select(
            data=self.valid_pdf,
            mime_type="application/pdf",
            explicit_plugin_id="pridge.renderer.text",
        )
        self.assertEqual(plugin.plugin_id, "pridge.renderer.text")
        self.assertIn("explicit", reason)

    def test_raises_on_unknown_explicit_plugin_id(self) -> None:
        with self.assertRaises(RenderError):
            self.selector.select(data=b"data", explicit_plugin_id="org.nonexistent")

    def test_raises_on_unsupported_format(self) -> None:
        with self.assertRaises(RenderError):
            self.selector.select(
                data=b"\x00\x01\x02\x03\x04\x05\x06\x07\x08",
                mime_type="application/x-unknown-binary",
            )

    def test_raw_jobs_bypass_renderer_selection(self) -> None:
        from pridge_client.printers import PrinterManager
        from unittest.mock import Mock
        from pridge_client.renderers import PDFValidationService, build_default_registry

        manager = PrinterManager.__new__(PrinterManager)
        manager.system = "Test"
        manager.backend = Mock()
        manager._registry = build_default_registry()
        manager._validation = PDFValidationService()
        manager._renderer_selector = RendererSelectionService(manager._registry)

        manager.print_job("Labels", b"\x1b@raw-esc-pos", mode="raw", job_name="RAW")

        manager.backend.print_raw.assert_called_once()
        manager.backend.print_driver_pdf.assert_not_called()


class PDFPassthroughRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = PdfRendererPlugin()
        self.options = RenderOptions()
        self.valid_pdf = create_test_page_pdf()

    def test_passes_through_valid_pdf_unchanged(self) -> None:
        result = self.plugin.render_to_pdf(
            data=self.valid_pdf, mime_type="application/pdf", filename=None, options=self.options
        )
        self.assertEqual(result, self.valid_pdf)

    def test_rejects_non_pdf_input(self) -> None:
        with self.assertRaises(RenderError):
            self.plugin.render_to_pdf(
                data=b"not a pdf", mime_type="application/pdf", filename=None, options=self.options
            )

    def test_can_render_detects_pdf_magic_bytes(self) -> None:
        self.assertTrue(self.plugin.can_render(
            mime_type=None, filename=None, data=self.valid_pdf
        ))
        self.assertFalse(self.plugin.can_render(
            mime_type=None, filename=None, data=b"not a pdf"
        ))

    def test_api_version_matches_current(self) -> None:
        self.assertEqual(self.plugin.api_version, PRIDGE_RENDERER_API_VERSION)


class ImageRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = ImageRendererPlugin()
        self.options = RenderOptions()

    def test_can_render_detects_png_magic(self) -> None:
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        self.assertTrue(self.plugin.can_render(
            mime_type=None, filename=None, data=png_header
        ))

    def test_can_render_detects_jpeg_magic(self) -> None:
        jpeg_header = b"\xff\xd8\xff\xe0" + b"\x00" * 64
        self.assertTrue(self.plugin.can_render(
            mime_type=None, filename=None, data=jpeg_header
        ))

    def test_rejects_non_image_data(self) -> None:
        self.assertFalse(self.plugin.can_render(
            mime_type=None, filename=None, data=b"definitely not an image"
        ))

    def test_png_produces_valid_pdf(self) -> None:
        try:
            from PIL import Image
            import io
            buf = io.BytesIO()
            img = Image.new("RGB", (10, 10), color=(255, 0, 0))
            img.save(buf, format="PNG")
            png_data = buf.getvalue()
        except ImportError:
            self.skipTest("Pillow not installed")

        result = self.plugin.render_to_pdf(
            data=png_data, mime_type="image/png", filename="test.png", options=self.options
        )
        self.assertTrue(result.startswith(b"%PDF"))

    def test_raises_on_invalid_image_data(self) -> None:
        with self.assertRaises(RenderError):
            self.plugin.render_to_pdf(
                data=b"\xff\xd8\xff garbage", mime_type="image/jpeg",
                filename=None, options=self.options,
            )


class TextRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = TextRendererPlugin()
        self.options = RenderOptions()

    def test_produces_valid_pdf_from_plain_text(self) -> None:
        result = self.plugin.render_to_pdf(
            data=b"Hello, world!\nSecond line.",
            mime_type="text/plain",
            filename=None,
            options=self.options,
        )
        self.assertTrue(result.startswith(b"%PDF-1.4"))
        self.assertIn(b"%%EOF", result)

    def test_handles_multipage_text(self) -> None:
        many_lines = "\n".join(f"Line {i}" for i in range(300))
        result = self.plugin.render_to_pdf(
            data=many_lines.encode(), mime_type="text/plain", filename=None, options=self.options
        )
        self.assertTrue(result.startswith(b"%PDF-1.4"))

    def test_handles_empty_input(self) -> None:
        result = self.plugin.render_to_pdf(
            data=b"", mime_type="text/plain", filename=None, options=self.options
        )
        self.assertTrue(result.startswith(b"%PDF-1.4"))

    def test_handles_latin1_encoded_text(self) -> None:
        latin1_text = "Caf\xe9 d\xe9j\xe0 vu".encode("latin-1")
        opts = RenderOptions(encoding="latin-1")
        result = self.plugin.render_to_pdf(
            data=latin1_text, mime_type="text/plain", filename=None, options=opts
        )
        self.assertTrue(result.startswith(b"%PDF-1.4"))

    def test_text_with_parentheses_and_backslashes_does_not_break_pdf(self) -> None:
        data = b"Price: (50\\100) and (path\\to\\file)"
        result = self.plugin.render_to_pdf(
            data=data, mime_type="text/plain", filename=None, options=self.options
        )
        self.assertTrue(result.startswith(b"%PDF-1.4"))

    def test_can_render_accepts_utf8_text(self) -> None:
        self.assertTrue(self.plugin.can_render(
            mime_type=None, filename=None, data=b"Plain text content"
        ))

    def test_can_render_rejects_binary_data(self) -> None:
        self.assertFalse(self.plugin.can_render(
            mime_type=None, filename=None, data=bytes(range(256)) * 4
        ))


class PDFValidationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = PDFValidationService()
        self.valid_pdf = create_test_page_pdf()

    def test_accepts_valid_pdf(self) -> None:
        self.assertTrue(self.svc.is_valid_pdf(self.valid_pdf))

    def test_rejects_empty_bytes(self) -> None:
        self.assertFalse(self.svc.is_valid_pdf(b""))

    def test_rejects_non_pdf_bytes(self) -> None:
        self.assertFalse(self.svc.is_valid_pdf(b"not a pdf"))

    def test_rejects_truncated_pdf(self) -> None:
        self.assertFalse(self.svc.is_valid_pdf(b"%PDF-1.4 truncated"))

    def test_require_valid_pdf_raises_for_invalid_data(self) -> None:
        with self.assertRaises(RenderError):
            self.svc.require_valid_pdf(b"not a pdf")

    def test_require_valid_pdf_passes_for_valid_data(self) -> None:
        self.svc.require_valid_pdf(self.valid_pdf)


class DefaultRegistryTests(unittest.TestCase):
    def test_default_registry_contains_all_built_in_plugins(self) -> None:
        registry = build_default_registry()
        plugin_ids = {e.plugin.plugin_id for e in registry.all_entries()}
        self.assertIn("pridge.renderer.pdf", plugin_ids)
        self.assertIn("pridge.renderer.image", plugin_ids)
        self.assertIn("pridge.renderer.text", plugin_ids)
        self.assertIn("pridge.renderer.svg", plugin_ids)

    def test_pdf_renderer_has_higher_priority_than_image(self) -> None:
        registry = build_default_registry()
        pdf_entry = registry.get_entry("pridge.renderer.pdf")
        img_entry = registry.get_entry("pridge.renderer.image")
        self.assertLess(pdf_entry.priority, img_entry.priority)

    def test_all_built_in_plugins_declare_correct_api_version(self) -> None:
        registry = build_default_registry()
        for entry in registry.all_entries():
            self.assertEqual(entry.plugin.api_version, PRIDGE_RENDERER_API_VERSION)


if __name__ == "__main__":
    unittest.main()
