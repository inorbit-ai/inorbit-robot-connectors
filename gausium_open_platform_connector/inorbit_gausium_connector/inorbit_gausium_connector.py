# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import argparse
import logging
import signal
import sys

from dotenv import find_dotenv
from dotenv import load_dotenv

# Attempts to load environment variables from config/.env file relative to the current working
# directory. If the file is not found, a message will be printed out and the program will
# continue. If not using this file, the evironment variables can be set manually anyway
# This must be done before importing from inorbit_connector, which will pick up the environment
# TODO(b-Tomas): Fix inorbit_connector to not use environment variables at import time
# TODO(b-Tomas): Remove `noqa: E402` after fixing the above
load_dotenv(find_dotenv("config/.env", usecwd=True), verbose=True, override=True)

from inorbit_connector.utils import read_yaml  # noqa: E402
from inorbit_gausium_connector.config.connector_model import default_config  # noqa: E402
from inorbit_gausium_connector.config.connector_model import load_and_validate  # noqa: E402
from inorbit_gausium_connector.config.utils import write_yaml  # noqa: E402
from inorbit_gausium_connector.src.connector import PhantasConnector  # noqa: E402

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


class CustomParser(argparse.ArgumentParser):
    # Handles missing parameters by printing the help message
    def error(self, message):
        sys.stderr.write("error: %s\n" % message)
        self.print_help()
        sys.exit(2)


def start():
    """Parses arguments, processes the configuration file and starts the connector."""
    parser = CustomParser(prog="inorbit_gausium_phantas_connector")
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        required=True,
        help="Path to the YAML file containing the robot configuration",
    )
    parser.add_argument(
        "-id",
        "--robot_id",
        type=str,
        required=True,
        help="InOrbit robot id. Will be searched in the config file",
    )

    args = parser.parse_args()
    robot_id, config_filename = args.robot_id, args.config

    try:
        config = load_and_validate(config_filename, robot_id)
    except FileNotFoundError:
        LOGGER.info("Missing configuration file")
        exit(1)
    except IndexError:
        LOGGER.info(
            f"Missing configuration section for robot_id '{robot_id}'. Creating "
            "a skeleton configuration for it."
        )
        config_dict = read_yaml(config_filename)
        config_dict[robot_id] = default_config
        write_yaml(config_filename, config_dict)
        LOGGER.info("Configuration file updated. Please fill in the missing values.")
        exit(1)

    connector = PhantasConnector(robot_id, config)

    LOGGER.info("Starting connector...")
    connector.start()

    # Register a signal handler for graceful shutdown
    # When a keyboard interrupt is received (Ctrl+C), the connector will be stopped
    signal.signal(signal.SIGINT, lambda sig, frame: connector.stop())

    # Wait for the connector to finish
    connector.join()
