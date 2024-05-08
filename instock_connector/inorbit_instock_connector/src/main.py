#!/usr/bin/env python
# -*- coding: utf-8 -*-

# MIT License
#
# Copyright (C) 2024 InOrbit, Inc.

import argparse
import logging
from time import sleep

from connector import InstockConnector
from instock.config_instock import load_and_validate


# TODO(russell): abstract to higher level library
def main():
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-c",
        "--config",
        type=str,
        required=True,
        help="Path to the YAML file containing the robot configuration",
    )
    parser.add_argument(
        "-r",
        "--robot-id",
        dest="robot_id",
        type=str,
        help="Robot ID if not provided to search for in the configuration",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Output verbose information (main entry point only)",
    )

    # Read arguments
    args = parser.parse_args()
    robot_id, config_file, verbose = args.robot_id, args.config, args.verbose

    # Set logging
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    logger.debug(
        f"Running with the following:\n"
        f"\tabstract: {config_file}\n"
        f"\trobot-id: {robot_id}\n"
        f"\tverbose: {verbose}"
    )

    if not robot_id:
        # TODO(tomi/russell): Allow missing param
        logger.error("Robot ID must be provided.")
        exit(1)

    try:
        # Parse the YAML
        instock_config = load_and_validate(config_file, robot_id)
    except FileNotFoundError:
        logger.error(f"'{config_file}' configuration file does not exist")
        exit(1)
    except IndexError:
        logger.error(f"'{robot_id}' not found in '{config_file}'")
        exit(1)

    connector = InstockConnector(robot_id, instock_config)

    logger.info("Starting connector...")
    connector.start()

    try:
        while True:
            # Yield execution to another thread
            sleep(0)
    except KeyboardInterrupt:
        logger.info("...exiting")
        connector.stop()


if __name__ == "__main__":
    main()
