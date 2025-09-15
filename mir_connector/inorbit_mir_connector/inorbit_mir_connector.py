# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import argparse
import logging
import signal
import sys
import os

from pydantic import ValidationError
from inorbit_mir_connector.src.connector import MirConnector
from inorbit_mir_connector.config.connector_model import load_and_validate, format_validation_error

# Configure logging with better formatting and level control
def setup_logging():
    """Configure logging with appropriate levels and formatting"""
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    
    # Create formatter with more detailed information
    formatter = logging.Formatter(
        '%(asctime)s %(levelname)s [%(name)s] %(message)s (%(filename)s:%(lineno)d)'
    )
    
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format='%(asctime)s %(levelname)s [%(name)s] %(message)s (%(filename)s:%(lineno)d)',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Reduce noise from verbose libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    
    # Reduce noise from InOrbit SDK - these log every MQTT publish
    logging.getLogger("inorbit_edge.robot").setLevel(logging.INFO)
    logging.getLogger("RobotSession").setLevel(logging.INFO)
    
    return logging.getLogger(__name__)

LOGGER = setup_logging()


class CustomParser(argparse.ArgumentParser):
    # Handles missing parameters by printing the help message
    def error(self, message):
        sys.stderr.write("error: %s\n" % message)
        self.print_help()
        sys.exit(2)


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
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set the logging level (default: INFO)",
    )

    args = parser.parse_args()
    robot_id, config_filename = args.robot_id, args.config
    
    # Update logging level if specified
    if hasattr(args, 'log_level') and args.log_level:
        logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))

    try:
        mir_config = load_and_validate(config_filename, robot_id)
    except FileNotFoundError:
        LOGGER.error("Missing configuration file")
        exit(1)
    except IndexError:
        LOGGER.error(
            f"Missing configuration section for robot_id '{robot_id}' within {config_filename}."
        )
        exit(1)
    except ValidationError as e:
        LOGGER.error(format_validation_error(e))
        exit(1)

    connector = MirConnector(robot_id, mir_config)

    LOGGER.info("Starting connector...")
    connector.start()

    # Register a signal handler for graceful shutdown
    # When a keyboard interrupt is received (Ctrl+C), the connector will be stopped
    signal.signal(signal.SIGINT, lambda sig, frame: connector.stop())

    # Wait for the connector to finish
    connector.join()
