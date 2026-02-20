# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Configuration models for FlowCore connector."""

# Standard
from typing import Optional

# Third Party
from pydantic import (
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

# InOrbit
from inorbit_connector.models import ConnectorConfig, RobotConfig


CONNECTOR_TYPE = "flowcore"

# Default environment file, relative to the directory the connector is executed from. If using a
# different .env file, make sure to source it before running the connector.
DEFAULT_ENV_FILE = "config/.env"


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


class FlowCoreConfig(BaseSettings):
    """Custom configuration fields for FlowCore connector.

    These are fleet-wide settings shared by all robots.

    Attributes:
        url (str): Base URL of the FlowCore API
        username (str): Username for FlowCore API
        password (str): Password for FlowCore API
        verify_ssl (bool): Verify SSL certificates (set to False for self-signed)

    If any field is missing, the initializer will attempt to replace it by reading from the
    environment. Values are set in the environment with the prefix INORBIT_FLOWCORE_
        (e.g. url -> INORBIT_FLOWCORE_URL)
    """

    model_config = SettingsConfigDict(
        env_prefix="INORBIT_FLOWCORE_",
        env_ignore_empty=True,
        case_sensitive=False,
        env_file=DEFAULT_ENV_FILE,
        extra="allow",
    )

    url: str
    username: str = "toolkitadmin"
    password: str
    arcl_port: int = 7171
    arcl_password: str
    arcl_timeout: int = 5
    verify_ssl: bool = False
    use_mock: bool = False



class FlowCoreConnectorConfig(ConnectorConfig):
    """Configuration for FlowCore connector.

    Inherits from ConnectorConfig and adds FlowCore-specific fields.

    Attributes:
        connector_config (FlowCoreConfig): FlowCore-specific configuration
        fleet (list[FlowCoreRobotConfig]): List of robot configurations
    """

    connector_config: FlowCoreConfig  # type: ignore[assignment]
    fleet: list[FlowCoreRobotConfig]  # type: ignore[assignment]

    @field_validator("connector_type")
    def check_connector_type(cls, connector_type: str) -> str:
        """Validate the connector type.

        Args:
            connector_type (str): The connector type from config

        Returns:
            str: The validated connector type

        Raises:
            ValueError: If connector type doesn't match expected value
        """
        if connector_type != CONNECTOR_TYPE:
            raise ValueError(f"Expected connector type '{CONNECTOR_TYPE}' not '{connector_type}'")
        return connector_type

    @model_validator(mode="after")
    def validate_unique_fleet_robot_ids(self) -> "FlowCoreConnectorConfig":
        """Validate that fleet_robot_id values are unique across the fleet.

        Returns:
            FlowCoreConnectorConfig: The validated configuration

        Raises:
            ValueError: If fleet_robot_id values are not unique
        """
        fleet_ids = [robot.fleet_robot_id for robot in self.fleet]
        if len(fleet_ids) != len(set(fleet_ids)):
            raise ValueError("fleet_robot_id values must be unique")
        return self
