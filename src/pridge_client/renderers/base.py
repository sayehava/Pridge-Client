# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


PRIDGE_RENDERER_API_VERSION = 1


class RenderError(RuntimeError):
    pass


@dataclass
class RenderOptions:
    scaling: str = "fit"
    auto_rotate: bool = True
    page_range: str = ""
    font_family: str = "Helvetica"
    font_size: float = 10.0
    margins_pt: tuple[float, float, float, float] = field(
        default_factory=lambda: (36.0, 36.0, 36.0, 36.0)
    )
    line_wrap: bool = True
    tab_width: int = 4
    encoding: str = ""
    dpi: float = 96.0


@runtime_checkable
class RendererPlugin(Protocol):
    plugin_id: str
    display_name: str
    version: str
    api_version: int
    supported_mime_types: frozenset[str]
    supported_extensions: frozenset[str]

    def can_render(
        self,
        *,
        mime_type: str | None,
        filename: str | None,
        data: bytes,
    ) -> bool: ...

    def render_to_pdf(
        self,
        *,
        data: bytes,
        mime_type: str | None,
        filename: str | None,
        options: RenderOptions,
    ) -> bytes: ...
