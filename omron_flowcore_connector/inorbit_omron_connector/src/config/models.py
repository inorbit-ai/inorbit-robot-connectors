# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Configuration models for FlowCore connector."""

# Standard
from typing import Optional

# Third Party
from pydantic import model_validator

# InOrbit
from inorbit_connector.models import (
    ConnectorRootConfig,
    ConnectorSpecificConfig,
    RobotConfig,
)

# Connector identity. The framework derives the env-var prefix
# (``INORBIT_FLOWCORE_``) from this value and enforces that the YAML's
# ``connector_type`` matches it.
CONNECTOR_TYPE = "flowcore"


class FlowCoreRobotConfig(RobotConfig):
    """Robot configuration with FlowCore-specific fields.

    Extends base RobotConfig to include Fleet robot ID.

    Attributes:
        robot_id (str): InOrbit robot ID
        fleet_robot_id (str): Robot ID in FlowCore (NameKey)
        map_id (str): Map ID in connector config to use with this robot
        ip_address (str): Optional IP address for manual override
    """

    fleet_robot_id: str
    map_id: Optional[str] = None
    ip_address: Optional[str] = None
    mock_data: Optional[dict] = None

    @model_validator(mode="after")
    def validate_fleet_id(self) -> "FlowCoreRobotConfig":
        """Ensure fleet_robot_id is present."""
        if not self.fleet_robot_id:
            raise ValueError("fleet_robot_id is required")
        return self


class FlowCoreConfig(ConnectorSpecificConfig):
    """Fleet-wide FlowCore settings shared by all robots.

    Any field can be supplied via ``INORBIT_FLOWCORE_<FIELD>`` env vars
    (prefix derived from CONNECTOR_TYPE by the framework), e.g.
    ``INORBIT_FLOWCORE_PASSWORD``.
    """

    CONNECTOR_TYPE = CONNECTOR_TYPE

    url: str
    username: str = "toolkitadmin"
    password: str
    arcl_port: int = 7171
    arcl_password: str
    arcl_timeout: int = 5
    # Seconds a failing /Robot/UpdatedSince poll is tolerated before every robot is
    # reported offline. The Fleet Manager reflects attach and detach within 10s and the
    # poll runs at update_freq, so this absorbs a few missed sweeps without flapping.
    api_grace_secs: float = 30.0
    verify_ssl: bool = False
    use_mock: bool = False


class FlowCoreConnectorConfig(ConnectorRootConfig[FlowCoreConfig]):
    """Top-level FlowCore connector configuration (the whole YAML file).

    ``connector_type`` identity ("flowcore") is enforced by the framework.
    ``fleet`` is narrowed to :class:`FlowCoreRobotConfig`.
    """

    fleet: list[FlowCoreRobotConfig]

    @model_validator(mode="after")
    def validate_unique_fleet_robot_ids(self) -> "FlowCoreConnectorConfig":
        """Validate that fleet_robot_id values are unique across the fleet."""
        fleet_ids = [robot.fleet_robot_id for robot in self.fleet]
        if len(fleet_ids) != len(set(fleet_ids)):
            raise ValueError("fleet_robot_id values must be unique")
        return self
