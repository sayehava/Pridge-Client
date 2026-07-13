# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
import platform
from typing import Any


logger = logging.getLogger(__name__)


def configure_utility_window(window: Any) -> None:
    """Remove native minimize controls and reject minimize requests."""
    window.events.shown += disable_minimize
    window.events.minimized += restore_if_minimized
    disable_minimize(window)


def disable_minimize(window: Any) -> None:
    native = getattr(window, "native", None)
    if native is None:
        return

    try:
        system = platform.system()
        if system == "Darwin":
            _disable_macos_minimize(native)
        elif system == "Windows":
            _disable_windows_minimize(native)
        elif system == "Linux":
            _disable_linux_minimize(native)
    except Exception as exc:
        logger.debug("Could not remove the native minimize control: %s", exc)


def restore_if_minimized(window: Any) -> None:
    try:
        window.restore()
    except Exception as exc:
        logger.debug("Could not restore a minimized utility window: %s", exc)


def _disable_macos_minimize(native: Any) -> None:
    import AppKit
    from PyObjCTools import AppHelper

    def apply() -> None:
        button = native.standardWindowButton_(AppKit.NSWindowMiniaturizeButton)
        if button is not None:
            button.setEnabled_(False)
            button.setHidden_(True)
        native.setStyleMask_(native.styleMask() & ~AppKit.NSWindowMiniaturizableWindowMask)

    AppHelper.callAfter(apply)


def _disable_windows_minimize(native: Any) -> None:
    def apply() -> None:
        native.MinimizeBox = False

    if getattr(native, "InvokeRequired", False):
        from System import Action

        native.BeginInvoke(Action(apply))
    else:
        apply()


def _disable_linux_minimize(native: Any) -> None:
    if hasattr(native, "set_type_hint"):
        from gi.repository import Gdk, GLib

        def apply_gtk() -> bool:
            native.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            return False

        GLib.idle_add(apply_gtk)
        return

    if hasattr(native, "setWindowFlag"):
        from webview.platforms.qt import QtCore

        def apply_qt() -> None:
            native.setWindowFlag(QtCore.Qt.WindowMinimizeButtonHint, False)
            native.show()

        QtCore.QTimer.singleShot(0, apply_qt)
