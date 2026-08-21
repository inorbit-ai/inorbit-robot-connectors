# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Entry point for the InOrbit Gausium Open Platform Connector."""

# Standard
import argparse
import logging
import signal
import sys
from typing import NoReturn

# InOrbit
from inorbit_connector.utils import read_yaml

# Local
from gausium_open_platform_connector import __version__
from gausium_open_platform_connector.src.config.models import GausiumOpenPlatformConnectorConfig
from gausium_open_platform_connector.src.connector import GausiumOpenPlatformConnector

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


class CustomParser(argparse.ArgumentParser):
    """Custom argument parser that shows help on error."""

    def error(self, message: str) -> NoReturn:
        """Handle parser errors by showing help.

        Args:
            message: Error message to display
        """
        sys.stderr.write(f"error: {message}\n")
        self.print_help()
        sys.exit(2)


def start() -> None:
    """Main entry point for the connector.

    Parses command-line arguments, loads configuration, and starts the connector.
    Handles graceful shutdown on SIGINT and SIGTERM.
    """
    parser = CustomParser(
        prog="gausium-open-platform-connector",
        description="InOrbit Gausium Open Platform Connector",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        required=True,
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args()
    config_filename = args.config

    try:
        yaml_data = read_yaml(config_filename)
        config = GausiumOpenPlatformConnectorConfig(**yaml_data)

        robot_ids = [robot.robot_id for robot in config.fleet]
        LOGGER.info(f"Configuration loaded for fleet of {len(robot_ids)} robots")
        LOGGER.info(f"Robot IDs: {robot_ids}")

    except FileNotFoundError:
        LOGGER.error(f"Configuration file '{config_filename}' not found")
        sys.exit(1)
    except ValueError as e:
        LOGGER.error(f"Configuration validation error: {e}")
        sys.exit(1)

    # Create and start the fleet connector
    connector = GausiumOpenPlatformConnector(config)
    LOGGER.info("Starting Gausium Open Platform Connector...")
    connector.start()

    # Adjust the log level of certain libraries to reduce noise
    level = logging.getLogger().getEffectiveLevel()
    if level <= logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.INFO)
        logging.getLogger("RobotSession").setLevel(logging.INFO)
    elif level == logging.INFO:
        logging.getLogger("httpx").setLevel(logging.WARNING)

    # Register signal handlers (SIGINT and SIGTERM) for graceful shutdown
    stop_requested = False

    def handle_signal(signum: int, frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True
        connector.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Wait for the connector to finish
    connector.join()
    if not stop_requested:
        # The connector thread died on its own (e.g. connect failure): exit non-zero
        # so a supervisor with a restart-on-failure policy restarts the process
        LOGGER.error("Connector stopped unexpectedly")
        sys.exit(1)


if __name__ == "__main__":
    start()
