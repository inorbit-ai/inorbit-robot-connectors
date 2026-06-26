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
from inorbit_mir_connector.config.connector_model import (
    load_config,
    format_validation_error,
)


# Configure logging with better formatting and level control
def setup_logging():
    """Configure logging with appropriate levels and formatting"""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s (%(filename)s:%(lineno)d)",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Reduce noise from verbose libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

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


def _make_shutdown_handler(connector):
    """Build a SIGINT handler that stops the connector gracefully.

    Re-entrant-safe: repeated Ctrl+C while shutdown is already in progress is
    ignored instead of stacking stop() calls. It also never lets an exception
    escape the handler — ``connector.stop()`` raises if teardown exceeds its
    join timeout (e.g. a slow camera stream thread), which is logged rather
    than propagated into the main thread.
    """
    state = {"stopping": False}

    def handle_sigint(_sig=None, _frame=None):
        if state["stopping"]:
            LOGGER.warning("Shutdown already in progress; ignoring repeated interrupt")
            return
        state["stopping"] = True
        LOGGER.info("Shutting down connector...")
        try:
            connector.stop()
        except Exception as e:
            LOGGER.error(f"Connector did not shut down cleanly: {e}")

    return handle_sigint


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
    if hasattr(args, "log_level") and args.log_level:
        logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))

    try:
        mir_config = load_config(config_filename)
    except FileNotFoundError:
        LOGGER.error("Missing configuration file")
        exit(1)
    except ValidationError as e:
        LOGGER.error(format_validation_error(e))
        exit(1)

    fleet_robot_ids = [robot.robot_id for robot in mir_config.fleet]
    if robot_id not in fleet_robot_ids:
        LOGGER.error(
            f"Robot id '{robot_id}' not found in {config_filename}. "
            f"Configured robots: {', '.join(fleet_robot_ids) or '(none)'}."
        )
        exit(1)

    # MirConnector narrows the fleet to ``robot_id`` via to_singular_config().
    connector = MirConnector(robot_id, mir_config)

    LOGGER.info("Starting connector...")
    connector.start()

    # Register a signal handler for graceful shutdown. When a keyboard
    # interrupt is received (Ctrl+C), the connector is stopped; repeated
    # interrupts during shutdown are ignored.
    signal.signal(signal.SIGINT, _make_shutdown_handler(connector))

    # Wait for the connector to finish
    connector.join()
