# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import argparse
import logging
import sys
from inorbit_mir_connector.src.connector import Mir100Connector
from inorbit_mir_connector.config.mir100_model import MiR100Config
from inorbit_mir_connector.config.mir100_model import load_and_validate
from inorbit_mir_connector.config.mir100_model import default_mir100_config
from inorbit_mir_connector.config.utils import read_yaml
from inorbit_mir_connector.config.utils import write_yaml

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

    parser = CustomParser(prog="inorbit-mir100-connector")
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

    # TODO(b-Tomas): Make use of all the config values e.g. validate package version, api version, etc.
    try:
        mir_config = load_and_validate(config_filename, robot_id)
    except FileNotFoundError:
        LOGGER.info(f"Missing configuration file")
        exit(1)
    except IndexError:
        LOGGER.info(f"Missing configuration section for robot_id '{robot_id}'. Creating "
                    "a skeleton configuration for it.")
        config_dict = read_yaml(config_filename)
        config_dict[robot_id] = default_mir100_config
        write_yaml(config_filename, config_dict)
        mir_config = MiR100Config(**config_dict[robot_id])

    mir_connector = Mir100Connector(robot_id, mir_config)
    try:
        mir_connector.start()
    except KeyboardInterrupt:
        LOGGER.info("Received SIGINT, stopping connector")
        mir_connector.stop()
