# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path


logger = logging.getLogger(__name__)


class TrayUnavailableError(RuntimeError):
    pass


class TrayController:
    def __init__(
        self,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
        icon_path: Path | None = None,
    ) -> None:
        self.on_show = on_show
        self.on_quit = on_quit
        self.icon_path = icon_path
        self.icon = None

    def start(self) -> None:
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError as exc:
            raise TrayUnavailableError("Tray support requires pystray and Pillow.") from exc

        if self.icon_path is not None and self.icon_path.exists():
            image = Image.open(self.icon_path).convert("RGBA")
        else:
            image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((8, 8, 56, 56), radius=10, fill=(30, 94, 255, 255))
            draw.rectangle((18, 16, 46, 28), fill=(255, 255, 255, 255))
            draw.rectangle((18, 36, 46, 48), fill=(255, 255, 255, 255))

        self.icon = pystray.Icon(
            "pridge-client",
            image,
            "Pridge Client",
            menu=pystray.Menu(
                pystray.MenuItem("Open", self._show),
                pystray.MenuItem("Quit", self._quit),
            ),
        )
        if hasattr(self.icon, "run_detached"):
            self.icon.run_detached()
            return
        threading.Thread(target=self.icon.run, name="printbridge-tray", daemon=True).start()

    def stop(self) -> None:
        if self.icon is not None:
            self.icon.stop()

    def _show(self, _icon: object, _item: object) -> None:
        self.on_show()

    def _quit(self, _icon: object, _item: object) -> None:
        self.on_quit()
