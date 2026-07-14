# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import argparse
import logging
import signal
import threading

from printbridge_client.config import ClientTokenStore, ConfigStore, ClientConfig, ServerConfig
from printbridge_client.logging_setup import configure_logging
from printbridge_client.platform_window import show_startup_error
from printbridge_client.strings import APP_NAME
from printbridge_client.strings import MESSAGE_GUI_STARTUP_FAILED
from printbridge_client.version import __version__
from printbridge_client.worker import PollingWorker


logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(prog="pridge-client")
    parser.add_argument("--version", action="store_true", help="Show version and exit.")
    parser.add_argument("--headless", action="store_true", help="Start without opening the settings window.")
    parser.add_argument("--gui-smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.version:
        print(__version__)
        return

    config = ConfigStore().load()
    configure_logging(config)
    logger.info("%s %s starting", APP_NAME, __version__)
    if args.headless:
        token_store = ClientTokenStore()
        workers = [
            PollingWorker(_runtime_config(config, server), token_store.get(server.id))
            for server in config.servers
            if server.enabled
        ]
        stop_event = threading.Event()

        def stop(_signum: int, _frame: object) -> None:
            for worker in workers:
                worker.stop()
            stop_event.set()

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        for worker in workers:
            worker.start()
        stop_event.wait()
        for worker in workers:
            worker.join(timeout=10)
        return

    try:
        from printbridge_client.gui import run_gui

        run_gui(gui_smoke_test=args.gui_smoke_test)
    except Exception:
        logger.exception("Desktop GUI startup failed")
        if not args.gui_smoke_test:
            show_startup_error(APP_NAME, MESSAGE_GUI_STARTUP_FAILED)
        raise SystemExit(1)


def _runtime_config(config: ClientConfig, server: ServerConfig) -> ClientConfig:
    return ClientConfig(
        server_url=server.server_url,
        servers=[server],
        selected_printer=config.selected_printer,
        printer_profiles=config.printer_profiles,
        polling_interval_seconds=server.polling_interval_seconds,
        heartbeat_interval_seconds=server.heartbeat_interval_seconds,
        start_polling_on_launch=config.start_polling_on_launch,
        start_at_login=config.start_at_login,
        logging=config.logging,
    )
