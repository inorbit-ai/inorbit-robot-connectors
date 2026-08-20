# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Configuration models for the Gausium Open Platform connector."""

from inorbit_connector.models import ConnectorRootConfig, ConnectorSpecificConfig, RobotConfig
from pydantic import Field, HttpUrl, model_validator

CONNECTOR_TYPE = "gausium_open_platform"

DEFAULT_BASE_URL = "https://openapi.gs-robot.com/"

# A mission is considered successful if the cleaned area percentage reaches this threshold
DEFAULT_MISSION_SUCCESS_PERCENTAGE_THRESHOLD = 0.90


class GausiumOpenPlatformRobotConfig(RobotConfig):
    """Per-robot configuration.

    Attributes:
        robot_id (str): InOrbit robot ID (inherited)
        serial_number (str): Robot serial number in the Gausium Open Platform
    """

    serial_number: str


class GausiumOpenPlatformConfig(ConnectorSpecificConfig):
    """Fleet-wide Gausium Open Platform settings.

    Credentials are account-scoped: one OAuth session serves the whole fleet.
    Every field can also be set via the environment with the INORBIT_GAUSIUM_OPEN_PLATFORM_
    prefix (e.g. INORBIT_GAUSIUM_OPEN_PLATFORM_CLIENT_ID).

    Attributes:
        base_url (HttpUrl): Base URL of the Gausium Open Platform API
        client_id (str): OAuth client ID
        client_secret (str): OAuth client secret
        access_key_secret (str): OAuth open access key
        api_timeout (float): Timeout for API requests in seconds
        mission_success_percentage_threshold (float): Cleaned area ratio above which a
            finished mission is reported as successful
    """

    CONNECTOR_TYPE = CONNECTOR_TYPE

    base_url: HttpUrl = Field(default=HttpUrl(DEFAULT_BASE_URL))
    client_id: str
    client_secret: str
    access_key_secret: str
    api_timeout: float = 10.0
    mission_success_percentage_threshold: float = Field(
        default=DEFAULT_MISSION_SUCCESS_PERCENTAGE_THRESHOLD, ge=0.0, le=1.0
    )


class GausiumOpenPlatformConnectorConfig(ConnectorRootConfig[GausiumOpenPlatformConfig]):
    """Root configuration for the Gausium Open Platform connector.

    Attributes:
        fleet (list[GausiumOpenPlatformRobotConfig]): List of robot configurations
    """

    fleet: list[GausiumOpenPlatformRobotConfig]  # type: ignore[assignment]

    @model_validator(mode="after")
    def validate_unique_serial_numbers(self) -> "GausiumOpenPlatformConnectorConfig":
        """Validate that serial numbers are unique across the fleet.

        Raises:
            ValueError: If serial_number values are not unique
        """
        serial_numbers = [robot.serial_number for robot in self.fleet]
        if len(serial_numbers) != len(set(serial_numbers)):
            raise ValueError("serial_number values must be unique")
        return self
