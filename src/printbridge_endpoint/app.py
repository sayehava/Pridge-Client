import logging
import argparse

from printbridge_endpoint.config import ConfigStore
from printbridge_endpoint.logging_setup import configure_logging
from printbridge_endpoint.strings import APP_NAME
from printbridge_endpoint.version import __version__


logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(prog="printbridge-endpoint")
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
        print(f"{APP_NAME} {__version__}")
        return

    from printbridge_endpoint.gui import run_gui

    run_gui()
