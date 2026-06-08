# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from typing import Literal, Optional

from pydantic import field_validator, model_validator, ValidationError
from inorbit_connector.models import (
    ConnectorRootConfig,
    ConnectorSpecificConfig,
    RobotConfig,
)
from inorbit_connector.utils import read_yaml

# Connector identity. The framework derives the env-var prefix
# (``INORBIT_MIR_``) from this value and enforces that the YAML's
# ``connector_type`` matches it.
CONNECTOR_TYPE = "mir"

# Expected values
FIRMWARE_VERSIONS = ["v2", "v3"]
MIR_API_VERSION = "v2.0"


class MirConnectorConfig(ConnectorSpecificConfig):
    """Connector-wide (fleet-shared) MiR configuration.

    Lives under the YAML's ``connector_config`` block. These values are
    shared by every robot the connector instance serves. Credentials are
    intentionally kept here (rather than per-robot in :class:`MirRobotConfig`)
    because :class:`ConnectorSpecificConfig` is a ``pydantic_settings``
    BaseSettings: any field can be supplied via ``INORBIT_MIR_<FIELD>`` env
    vars (prefix derived from ``CONNECTOR_TYPE`` by the framework), which is
    how secrets are injected in production — e.g.
    ``INORBIT_MIR_MIR_PASSWORD``. ``RobotConfig`` subclasses do not get
    env-var loading, so per-robot fleet entries cannot carry secrets.
    """

    CONNECTOR_TYPE = CONNECTOR_TYPE

    # MiR REST API version. Uniform across the fleet (the connector targets a
    # single MiR API generation).
    mir_api_version: str

    # MiR REST API credentials. Shared across the fleet; inject via
    # INORBIT_MIR_MIR_USERNAME / INORBIT_MIR_MIR_PASSWORD rather than
    # committing them to the YAML.
    mir_username: str
    mir_password: str

    @field_validator("mir_api_version")
    def api_version_validation(cls, mir_api_version):
        if mir_api_version != MIR_API_VERSION:
            raise ValueError(
                f"Unexpected MiR API version '{mir_api_version}'. Expected '{MIR_API_VERSION}'"
            )
        return mir_api_version


class MirRobotConfig(RobotConfig):
    """Per-robot MiR configuration (one entry per robot in ``fleet``).

    Extends the framework's ``RobotConfig`` (which provides ``robot_id`` and
    ``cameras``) with the connection and behavior settings that differ from
    robot to robot. Each MiR robot exposes its own REST API at its own
    address, so these cannot be shared in ``connector_config`` the way a
    single fleet-manager's settings could.
    """

    # Robot model. Drives model-specific behavior (e.g. waypoint navigation
    # parameters). May vary across a mixed fleet.
    mir_model: Literal["MiR100", "MiR200", "MiR250", "MiR500"]

    # MiR REST API connection.
    mir_host_address: str
    mir_host_port: int
    mir_firmware_version: str

    # SSL configuration.
    mir_use_ssl: bool
    verify_ssl: bool = True  # Verify SSL certificates (set to False for self-signed)
    ssl_ca_bundle: Optional[str] = None  # Path to CA bundle file for custom CAs
    ssl_verify_hostname: bool = (
        True  # Verify hostname matches certificate (set to False for FRP/proxy)
    )

    # Waypoint navigation.
    enable_temporary_mission_group: Optional[bool] = True
    default_waypoint_mission_id: Optional[str] = None

    # Mission persistence. Path to the per-robot SQLite mission database.
    mission_database_file: Optional[str] = None

    @field_validator("mir_firmware_version")
    def firmware_version_validation(cls, mir_firmware_version):
        if mir_firmware_version not in FIRMWARE_VERSIONS:
            raise ValueError(
                f"Unexpected MiR firmware version '{mir_firmware_version}'. "
                f"Expected one of '{FIRMWARE_VERSIONS}'"
            )
        return mir_firmware_version

    @model_validator(mode="after")
    def check_waypoint_mission_configuration(self):
        """Require ``default_waypoint_mission_id`` when temporary mission
        groups are disabled (the connector has no group to create the move
        mission in otherwise)."""
        if not self.enable_temporary_mission_group and not self.default_waypoint_mission_id:
            raise ValueError(
                "default_waypoint_mission_id should be set when enable_temporary_mission_group "
                "is False."
            )
        return self


class ConnectorConfig(ConnectorRootConfig[MirConnectorConfig]):
    """Top-level MiR connector configuration (the whole YAML file).

    ``connector_type`` identity ("mir") is enforced by the framework — it
    must match ``MirConnectorConfig.CONNECTOR_TYPE``; no local validator
    needed. ``fleet`` is narrowed to :class:`MirRobotConfig` so per-robot
    MiR fields validate.
    """

    fleet: list[MirRobotConfig]

    @field_validator("fleet")
    def fleet_not_empty(cls, fleet):
        if not fleet:
            raise ValueError("fleet must contain at least one robot")
        robot_ids = [robot.robot_id for robot in fleet]
        if len(robot_ids) != len(set(robot_ids)):
            raise ValueError("robot_id values must be unique across the fleet")
        return fleet


def load_config(config_filename: str) -> ConnectorConfig:
    """Load and validate the connector configuration file.

    The YAML follows the inorbit-connector framework's flat schema: top-level
    framework fields, a ``connector_config`` block, and a ``fleet`` list. A
    single config file may describe multiple robots; the connector selects
    one at construction time via the ``robot_id`` passed to
    :class:`~inorbit_mir_connector.src.connector.MirConnector`.

    Args:
        config_filename (str): The YAML file to load the configuration from.

    Returns:
        ConnectorConfig: The validated configuration object.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
        yaml.YAMLError: If the configuration file is not valid YAML.
        ValidationError: If the configuration file is not valid.
    """
    # Constructor (not model_validate): ConnectorRootConfig is a
    # pydantic-settings BaseSettings, and INORBIT_* env vars are only
    # resolved through __init__. YAML values take precedence over env.
    return ConnectorConfig(**read_yaml(config_filename))


def format_validation_error(error: ValidationError) -> str:
    """Format Pydantic validation errors into a user-friendly message."""
    error_messages = []

    for err in error.errors():
        field_path = " -> ".join(str(loc) for loc in err["loc"])
        error_msg = err["msg"]

        if field_path:
            error_messages.append(f"  • Field '{field_path}': {error_msg}")
        else:
            error_messages.append(f"  • {error_msg}")

    return "Config validation failed:\n" + "\n".join(error_messages)
