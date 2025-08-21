# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import argparse
import logging
import signal
import sys

from inorbit_mir_connector.src.connector import Mir100Connector
from inorbit_mir_connector.config.connector_model import load_and_validate

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


class CustomParser(argparse.ArgumentParser):
    # Handles missing parameters by printing the help message
    def error(self, message):
        sys.stderr.write("error: %s\n" % message)
        self.print_help()
        sys.exit(2)


# TODO(Elvio): Make sure start() has a unit test!
def start():
    """This command takes as input file the MiR connector configuration and starts the connector."""

    parser = CustomParser(prog="inorbit_mir_connector")
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
        mir_config = load_and_validate(config_filename, robot_id)
    except FileNotFoundError:
        LOGGER.info("Missing configuration file")
        exit(1)
    except IndexError:
        LOGGER.info(
            f"Missing configuration section for robot_id '{robot_id}' within {config_filename}."
        )
        exit(1)

    mir_connector = Mir100Connector(robot_id, mir_config)
    try:
        LOGGER.info("Starting connector...")
        mir_connector.start()
        signal.signal(signal.SIGINT, lambda sig, frame: mir_connector.stop())
        mir_connector.join()
    except KeyboardInterrupt:
        LOGGER.info("Received SIGINT, stopping connector")
        mir_connector.stop()
