# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
import platform
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from typing import Any


logger = logging.getLogger(__name__)

# Matches the WebView2Bootstrapper client ID checked by the Inno Setup
# installer (packaging/windows/Pridge-Client.iss) so both entry points agree
# on whether a valid runtime is already present.
WEBVIEW2_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_BOOTSTRAPPER_NAME = "MicrosoftEdgeWebview2Setup.exe"


def ensure_webview2_runtime() -> None:
    """Install the bundled WebView2 Runtime if this machine does not have it.

    The installer build provisions the runtime during setup, but the
    portable build has no setup step, so it must provision the runtime
    itself on first launch using the bootstrapper packaged alongside it.
    """
    if platform.system() != "Windows":
        return
    try:
        if _webview2_runtime_installed():
            return
        bootstrapper = _bundled_webview2_bootstrapper()
        if bootstrapper is None:
            logger.debug("No bundled WebView2 bootstrapper found; skipping runtime install")
            return
        logger.info("Microsoft WebView2 Runtime is missing; installing the bundled runtime")
        subprocess.run([str(bootstrapper), "/silent", "/install"], check=True, timeout=180)
    except Exception as exc:
        logger.warning("Could not install the Microsoft WebView2 Runtime: %s", exc)


def _webview2_runtime_installed() -> bool:
    import winreg

    for hive, key_path in (
        (winreg.HKEY_LOCAL_MACHINE, f"SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{WEBVIEW2_CLIENT_ID}"),
        (winreg.HKEY_CURRENT_USER, f"Software\\Microsoft\\EdgeUpdate\\Clients\\{WEBVIEW2_CLIENT_ID}"),
    ):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                version, _ = winreg.QueryValueEx(key, "pv")
        except OSError:
            continue
        if version and version != "0.0.0.0":
            return True
    return False


def _bundled_webview2_bootstrapper() -> Path | None:
    candidate = Path(sys.executable).resolve().parent / WEBVIEW2_BOOTSTRAPPER_NAME
    return candidate if candidate.is_file() else None


def preferred_webview_gui() -> str | None:
    """Select the renderer whose dependencies are bundled for this platform."""
    system = platform.system()
    if system == "Windows":
        return "edgechromium"
    if system == "Darwin":
        return "cocoa"
    if system == "Linux":
        return "qt"
    return None


def show_startup_error(title: str, message: str) -> None:
    """Display a native fatal-startup message without depending on pywebview."""
    try:
        system = platform.system()
        if system == "Windows":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, f"{title} Startup Error", 0x10)
        elif system == "Darwin":
            import AppKit

            alert = AppKit.NSAlert.alloc().init()
            alert.setMessageText_(f"{title} Startup Error")
            alert.setInformativeText_(message)
            alert.setAlertStyle_(AppKit.NSAlertStyleCritical)
            alert.runModal()
        else:
            logger.error("%s Startup Error: %s", title, message)
    except Exception as exc:
        logger.error("Could not display the startup error dialog: %s", exc)


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
