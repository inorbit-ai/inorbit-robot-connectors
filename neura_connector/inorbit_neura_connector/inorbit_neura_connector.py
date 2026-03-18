"""CLI entry point for the NEURA InOrbit Connector."""

import argparse
import logging
import signal
import sys
import warnings

warnings.filterwarnings("ignore", message="Pydantic serializer warnings")

from pydantic import ValidationError

from inorbit_neura_connector.config.connector_model import (
    load_config,
    format_validation_error,
)


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s (%(filename)s:%(lineno)d)",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    return logging.getLogger(__name__)


def start():
    parser = argparse.ArgumentParser(prog="inorbit_neura_connector")
    parser.add_argument(
        "-c", "--config", type=str, default="config/robot.yaml",
        help="Path to robot config YAML (default: config/robot.yaml)",
    )
    parser.add_argument(
        "--log-level", type=str, default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print(f"ERROR: Config not found: {args.config}", file=sys.stderr)
        sys.exit(1)
    except (ValidationError, ValueError) as e:
        if isinstance(e, ValidationError):
            print(format_validation_error(e), file=sys.stderr)
        else:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    log_level = args.log_level or config.log_level
    logger = setup_logging(log_level)

    logger.info(f"Robot: {config.robot_name} ({config.robot_type}) SN={config.serial_number}")
    logger.info(f"Backend: {config.backend_type}")

    if config.backend_type == "nexus_python":
        logger.info(f"nexus_amr_api: robot={config.robot_ip}, client={config.client_ip}")
    elif config.backend_type == "nexus_rest":
        logger.info(f"REST API: http://{config.rest_api_ip}:{config.rest_api_port}")
    else:
        logger.info(f"neurapy_mav config: {config.mav_config_path}")

    from inorbit_neura_connector.src.connector import NeuraConnector
    connector = NeuraConnector(config)

    connector.start()
    signal.signal(signal.SIGINT, lambda sig, frame: connector.stop())
    connector.join()


if __name__ == "__main__":
    start()
