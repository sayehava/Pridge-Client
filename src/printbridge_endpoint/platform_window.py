# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
import platform
from collections.abc import Callable, Sequence
from threading import Event
from time import monotonic, sleep
from typing import Any


logger = logging.getLogger(__name__)


def configure_application_identity(name: str) -> None:
    """Set the native process and bundle name used by the macOS menu bar."""
    if platform.system() != "Darwin":
        return

    try:
        import Foundation

        bundle = Foundation.NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary()
        if info is None:
            info = bundle.infoDictionary()
        info["CFBundleName"] = name
        info["CFBundleDisplayName"] = name
        Foundation.NSProcessInfo.processInfo().setProcessName_(name)
    except Exception as exc:
        logger.debug("Could not configure the native application identity: %s", exc)


def create_application_menu(actions: Sequence[tuple[str, Callable[[], Any]]]) -> list[Any]:
    if platform.system() != "Darwin":
        return []

    from webview.menu import Menu, MenuAction

    return [Menu("__app__", [MenuAction(title, action) for title, action in actions])]


def configure_application_menu(
    window: Any,
    name: str,
    item_titles: Sequence[str],
) -> Callable[[], None] | None:
    if platform.system() != "Darwin":
        return None

    import webview

    webview.settings["SHOW_DEFAULT_MENUS"] = False

    def install() -> None:
        import AppKit

        deadline = monotonic() + 10
        application = AppKit.NSApplication.sharedApplication()
        while not application.isRunning() and monotonic() < deadline:
            sleep(0.01)
        if application.isRunning():
            _replace_macos_application_menu(name, item_titles)
            return
        logger.debug("Could not install the macOS application menu before timeout")

    return install


def _replace_macos_application_menu(name: str, item_titles: Sequence[str]) -> None:
    import AppKit
    import Foundation

    completed = Event()

    def apply() -> None:
        try:
            main_menu = AppKit.NSApplication.sharedApplication().mainMenu()
            if main_menu is None or main_menu.numberOfItems() == 0:
                return
            application_item = main_menu.itemAtIndex_(0)
            application_item.setTitle_(name)
            application_menu = application_item.submenu()
            if application_menu is None:
                return
            allowed = set(item_titles)
            for index in range(application_menu.numberOfItems() - 1, -1, -1):
                if application_menu.itemAtIndex_(index).title() not in allowed:
                    application_menu.removeItemAtIndex_(index)
        except Exception as exc:
            logger.debug("Could not replace the macOS application menu: %s", exc)
        finally:
            completed.set()

    Foundation.NSOperationQueue.mainQueue().addOperationWithBlock_(apply)
    if not completed.wait(5):
        logger.debug("Timed out while replacing the macOS application menu")


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
