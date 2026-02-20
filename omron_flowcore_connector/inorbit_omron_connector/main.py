# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Entry point for FlowCore connector."""

# Standard
import argparse
import logging
import signal
import sys
from typing import NoReturn

# InOrbit
from inorbit_connector.utils import read_yaml

# Local
from inorbit_omron_connector import __version__
from inorbit_omron_connector.src.config.models import FlowCoreConnectorConfig
from inorbit_omron_connector.src.connector import OmronConnector

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
    Handles graceful shutdown on SIGINT.
    """
    parser = CustomParser(
        prog="flowcore-connector",
        description="FlowCore connector for InOrbit",
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
        config = FlowCoreConnectorConfig(**yaml_data)

        robot_ids = [robot.robot_id for robot in config.fleet]
        LOGGER.info(f"Configuration loaded for fleet of {len(robot_ids)} robots")
        LOGGER.info(f"Robot IDs: {robot_ids}")

    except FileNotFoundError:
        LOGGER.error(f"Configuration file '{config_filename}' not found")
        sys.exit(1)
    except ValueError as e:
        LOGGER.error(f"Configuration validation error: {e}")
        sys.exit(1)

    connector = OmronConnector(config)
    LOGGER.info("Starting FlowCore connector...")
    connector.start()

    # Adjust the log level of certain libraries to reduce noise
    if logging.getLogger().getEffectiveLevel() == logging.INFO:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.INFO)
        logging.getLogger("RobotSession").setLevel(logging.INFO)

    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, lambda sig, frame: connector.stop())

    # Wait for the connector to finish
    connector.join()


if __name__ == "__main__":
    start()
