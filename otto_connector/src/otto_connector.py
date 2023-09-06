#!/usr/bin/env python

# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""InOrbit <> OTTO Connector entry point."""

import logging
import os
import sys

import yaml
from otto_connector.connector import OTTOConnector

# Set up the logger.
# Use loglevel INFO initially and pass the configured loglevel to the connector only.
logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


# Load environment variables
# TODO(b-Tomas): Add support for INORBIT_KEY for connect.
LOCATION_TZ = os.getenv("LOCATION_TZ", "America/Los_Angeles")
LOGLEVEL = os.getenv("LOGLEVEL", "INFO")
INORBIT_API_KEY = os.getenv("INORBIT_API_KEY")
INORBIT_API_USE_SSL = os.getenv("INORBIT_API_USE_SSL", "true") != "false"
INORBIT_API_ENDPOINT = os.getenv("INORBIT_URL")
FLEET_MANAGER_ADDRESS = os.getenv("FLEET_MANAGER_ADDRESS")
ROBOT_DEFINITIONS_FILE_NAME = os.getenv("ROBOT_DEFINITIONS_FILE_NAME")
USER_SCRIPTS_DIR = os.getenv("USER_SCRIPTS_DIR", "./../user_scripts")


def load_robot_definitions(filename):
    """Load robot definitions from the configuration file.

    Args:
        filename (str): File path.

    Returns:
        List of robot definition objects.
    """

    LOGGER.info(f"Loading robot definitions from file '{filename}'")
    with open(filename, "r") as stream:
        try:
            robot_definitions = yaml.safe_load(stream)["robot-definitions"]
            assert (
                isinstance(robot_definitions, list) and len(robot_definitions) > 0
            ), "robot-definitions should be a list of at least one element"

            for i, robot in enumerate(robot_definitions):
                assert robot.get(
                    "inorbit_id"
                ), f"Robot definition '{i}' doesn't contain 'inorbit_id'"
                assert robot.get("otto_id"), f"Robot definition '{i}' doesn't contain 'otto_id'"

            LOGGER.info(f"Robot definitions loaded: {robot_definitions}")

            return robot_definitions
        except Exception as e:
            LOGGER.error(f"Error loading robot definitions from file {filename}: {e}")
            sys.exit(1)


def main():
    """Start the connector and run it until stopped."""
    assert INORBIT_API_KEY, "'INORBIT_API_KEY' is required"
    assert FLEET_MANAGER_ADDRESS, "'FLEET_MANAGER_ADDRESS' is required"

    robot_definitions = load_robot_definitions(ROBOT_DEFINITIONS_FILE_NAME)

    connector = OTTOConnector(
        fleet_manager_address=FLEET_MANAGER_ADDRESS,
        robot_definitions=robot_definitions,
        user_scripts_dir=USER_SCRIPTS_DIR,
        inorbit_api_key=INORBIT_API_KEY,
        location_tz=LOCATION_TZ,
        loglevel=LOGLEVEL,
        inorbit_api_use_ssl=INORBIT_API_USE_SSL,
        inorbit_api_endpoint=INORBIT_API_ENDPOINT,
    )
    try:
        connector.start()
    except KeyboardInterrupt:
        LOGGER.info("Received SIGINT, stopping connector")
        connector.stop()


if __name__ == "__main__":
    main()
