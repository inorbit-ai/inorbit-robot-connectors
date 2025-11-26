# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from inorbit_connector.models import InorbitConnectorConfig
from inorbit_connector.utils import read_yaml
from pydantic import Field
from pydantic import field_validator
from pydantic import HttpUrl
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

# Expected values
CONNECTOR_TYPES = ["Gausium Phantas S", "Scrubber 50"]

DEFAULT_BASE_URL = "https://openapi.gs-robot.com/"

# The mission is considered successful if the completion percentage is greater than this threshold
DEFAULT_MISSION_SUCCESS_PERCENTAGE_THRESHOLD = 0.90

# TODO: leverate ruamel.yaml capabilities to add comments to
# the yaml and improve how the default configuration section
# that gets added automatically looks.
default_config = {
    "location_tz": "America/Los_Angeles",
    "logging": {"log_level": "INFO"},
    "connector_type": CONNECTOR_TYPES[0],
    "connector_config": {
        "base_url": DEFAULT_BASE_URL,
        "serial_number": "GS000-0000-000-0000",
        "client_id": "",
        "client_secret": "",
        "access_key_secret": "",
    },
}


class PhantasConnectorConfig(BaseSettings):
    """
    Specific configuration for the Gausium Phantas Connector.
    If any field is missing, the initializer will attempt to replace it by reading from the
    environment. Every field can be ignored if set in the env with the prefix INORBIT_GAUSIUM_
    (e.g. access_key_secret -> INORBIT_GAUSIUM_ACCESS_KEY_SECRET)
    """

    model_config = SettingsConfigDict(
        env_prefix="INORBIT_GAUSIUM_",
        env_ignore_empty=True,
        case_sensitive=False,
    )

    base_url: HttpUrl = Field(default=DEFAULT_BASE_URL)
    serial_number: str
    client_id: str
    client_secret: str
    access_key_secret: str
    mission_success_percentage_threshold: float = Field(
        default=DEFAULT_MISSION_SUCCESS_PERCENTAGE_THRESHOLD,
        ge=0.0,
        le=1.0,
    )


class ConnectorConfig(InorbitConnectorConfig):
    """
    Gausium Phantas Connector configuration schema.
    """

    connector_config: PhantasConnectorConfig

    @field_validator("connector_type")
    def connector_type_validation(cls, connector_type):
        """Validate the connector type.

        This should always be equal to the pre-defined constant.

        Args:
            connector_type (str): The defined connector type passed in

        Returns:
            str: The validated connector type

        Raises:
            ValueError: If the connector type is not equal to the pre-defined constant
        """
        if connector_type not in CONNECTOR_TYPES:
            raise ValueError(
                f"Unexpected connector type '{connector_type}'. Expected one of '{CONNECTOR_TYPES}'"
            )
        return connector_type


def load_and_validate(config_filename: str, robot_id: str) -> ConnectorConfig:
    """Loads and validates the configuration file.

    Raises an exception if the arguments or configuration are invalid.

    Args:
        config_filename (str): The YAML file to load the configuration from.
        robot_id (str): The InOrbit robot ID for the Instock ASRS system.

    Returns:
        InstockConfig: The Instock configuration object with the loaded values.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
        IndexError: If the configuration file does not contain the robot_id.
        yaml.YAMLError: If the configuration file is not valid YAML.
    """

    config = read_yaml(config_filename, robot_id)
    return ConnectorConfig(**config)
