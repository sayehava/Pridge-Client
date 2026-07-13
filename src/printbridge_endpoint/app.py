# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import argparse
import logging
import signal
import threading

from printbridge_endpoint.config import ClientTokenStore, ConfigStore, EndpointConfig, ServerConfig
from printbridge_endpoint.logging_setup import configure_logging
from printbridge_endpoint.strings import APP_NAME
from printbridge_endpoint.version import __version__
from printbridge_endpoint.worker import PollingWorker


logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(prog="printbridge-client")
    parser.add_argument("--version", action="store_true", help="Show version and exit.")
    parser.add_argument("--headless", action="store_true", help="Start without opening the settings window.")
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

    from printbridge_endpoint.gui import run_gui

    run_gui()


def _runtime_config(config: EndpointConfig, server: ServerConfig) -> EndpointConfig:
    return EndpointConfig(
        server_url=server.server_url,
        servers=[server],
        selected_printer=config.selected_printer,
        polling_interval_seconds=server.polling_interval_seconds,
        heartbeat_interval_seconds=server.heartbeat_interval_seconds,
        start_polling_on_launch=config.start_polling_on_launch,
        start_at_login=config.start_at_login,
        logging=config.logging,
    )
