# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

"""Minimal example of a third-party Pridge Client renderer plugin.

Install it by copying this folder into:
  <config dir>/plugins/renderers/<any-folder-name>/
or through the Plugins window's "Install Plugin" button, which points at
a folder like this one (containing manifest.json plus this module).

A real plugin does not need to import anything from pridge_client: the
renderer contract is structural (see RendererPlugin in
pridge_client/renderers/base.py), so any object exposing these attributes
and methods is accepted.
"""


class ExampleRendererPlugin:
    plugin_id = "org.example.pridge.renderer.example"
    display_name = "Example Renderer"
    version = "1.0.0"
    api_version = 1
    supported_mime_types = frozenset({"application/x-pridge-example"})
    supported_extensions = frozenset({".example"})

    def can_render(self, *, mime_type, filename, data):
        return False

    def render_to_pdf(self, *, data, mime_type, filename, options):
        text = data.decode("utf-8", errors="replace").strip() or "(empty input)"
        content = (
            b"BT\n/F1 14 Tf\n72 720 Td\n(Example Renderer output) Tj\n"
            b"0 -20 Td\n/F1 10 Tf\n(" + text[:200].encode("latin-1", errors="replace") + b") Tj\nET\n"
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
        for number, value in enumerate(objects, start=1):
            offsets.append(len(document))
            document.extend(f"{number} 0 obj\n".encode("ascii"))
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
