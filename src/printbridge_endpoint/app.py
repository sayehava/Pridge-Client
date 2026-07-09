import logging

from printbridge_endpoint.config import ConfigStore
from printbridge_endpoint.logging_setup import configure_logging
from printbridge_endpoint.strings import APP_NAME
from printbridge_endpoint.version import __version__


logger = logging.getLogger(__name__)


def main() -> None:
    config = ConfigStore().load()
    configure_logging(config)
    logger.info("%s %s starting", APP_NAME, __version__)
    print(f"{APP_NAME} {__version__}")
