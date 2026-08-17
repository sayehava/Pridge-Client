# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import argparse
import logging
import signal
import sys
import threading

from pridge_client.config import ConfigStore
from pridge_client.logging_setup import configure_logging
from pridge_client.platform_window import show_headless_address, show_startup_error
from pridge_client.strings import APP_NAME
from pridge_client.strings import MESSAGE_GUI_STARTUP_FAILED
from pridge_client.version import __version__


logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(prog="pridge-client")
    parser.add_argument("--version", action="store_true", help="Show version and exit.")
    startup_mode = parser.add_mutually_exclusive_group()
    startup_mode.add_argument("--headless", action="store_true", help="Start without opening the settings window.")
    startup_mode.add_argument("--tui", action="store_true", help="Start the full-color terminal dashboard (POSIX only).")
    parser.add_argument("--gui-smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--supervised-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.version:
        print(__version__)
        return

    config = ConfigStore().load()
    configure_logging(config)
    logger.info("%s %s starting", APP_NAME, __version__)

    if args.headless and config.restart_on_crash and not args.supervised_child:
        from pridge_client.supervisor import run_supervised

        raise SystemExit(run_supervised(["--headless"]))

    if args.tui:
        from pridge_client.tui import TuiController, run_tui
        from pridge_client.tui_ipc import RemoteTuiController

        remote_controller = RemoteTuiController.connect()
        if remote_controller is not None:
            run_tui(remote_controller, attached_to_service=True)
        else:
            controller = TuiController()
            controller.start()
            run_tui(controller)
        return

    if args.headless:
        _run_headless_service()
        return

    try:
        from pridge_client.gui import run_gui

        run_gui(gui_smoke_test=args.gui_smoke_test)
    except Exception:
        logger.exception("Desktop GUI startup failed")
        if not args.gui_smoke_test:
            show_startup_error(APP_NAME, MESSAGE_GUI_STARTUP_FAILED)
        raise SystemExit(1)


def _run_headless_service() -> None:
    from pridge_client.gui import ClientApi
    from pridge_client.headless_tui import HeadlessTuiController
    from pridge_client.web_gui import BrowserGuiServer

    api = ClientApi()
    stop_event = threading.Event()
    browser: BrowserGuiServer | None = None
    tui_server = None

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    def start_browser(port: int) -> str:
        nonlocal browser
        browser = BrowserGuiServer(api, port, on_stop=stop_event.set)
        url = browser.start()
        print(f"Browser GUI: {url}", flush=True)
        if sys.platform == "win32":
            show_headless_address(APP_NAME, url)
        return url

    def set_browser_enabled(enabled: bool) -> str:
        nonlocal browser
        if enabled and browser is None:
            return f"Browser GUI: {start_browser(api.config.web_gui_port)}"
        elif not enabled and browser is not None:
            browser.close()
            browser = None
            return "Browser GUI disabled"
        return f"Browser GUI: {browser.url}" if browser is not None else "Browser GUI disabled"

    def change_browser_port(port: int) -> str:
        nonlocal browser
        if browser is None:
            return ""
        browser.close()
        browser = None
        return start_browser(port)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    api.set_browser_port_change_handler(change_browser_port)
    controller = HeadlessTuiController(api, set_browser_enabled)
    if sys.platform != "win32":
        from pridge_client.tui_service import TuiServiceAlreadyRunning, TuiServiceServer

        tui_server = TuiServiceServer(controller)
        try:
            tui_server.open()
        except TuiServiceAlreadyRunning:
            logger.info("The headless service is already running")
            return
    try:
        controller.start()
        set_browser_enabled(sys.platform == "win32" or api.config.web_gui_enabled)
        if tui_server is not None:
            tui_server.serve(stop_event)
        else:
            stop_event.wait()
    finally:
        if browser is not None:
            browser.close()
        if tui_server is not None:
            tui_server.close()
        controller.stop_all()
