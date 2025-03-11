# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from inorbit_connector.models import InorbitConnectorConfig
from inorbit_connector.utils import read_yaml
from inorbit_gausium_connector.src.robot.robot_factory import ROBOT_API_CLASSES
from pydantic import field_validator
from pydantic import HttpUrl
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

# Expected values
CONNECTOR_TYPES = list(ROBOT_API_CLASSES.keys())

# TODO: leverate ruamel.yaml capabilities to add comments to
# the yaml and improve how the default configuration section
# that gets added automatically looks.
default_config = {
    "location_tz": "America/Los_Angeles",
    "log_level": "INFO",
    "connector_type": CONNECTOR_TYPES[0],
    "connector_config": {
        "base_url": "http://ip_and_port",
    },
}


class GausiumConnectorConfig(BaseSettings):
    """
    Specific configuration for the Gausium Connector.
    If any field is missing, the initializer will attempt to replace it by reading from the
    environment. Every field can be ignored if set in the env with the prefix INORBIT_GAUSIUM_
    (e.g. access_key_secret -> INORBIT_GAUSIUM_ACCESS_KEY_SECRET)
    """

    model_config = SettingsConfigDict(
        env_prefix="INORBIT_GAUSIUM_",
        env_ignore_empty=True,
        case_sensitive=False,
    )

    base_url: HttpUrl


class ConnectorConfig(InorbitConnectorConfig):
    """
    Gausium Connector configuration schema.
    """

    connector_config: GausiumConnectorConfig

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
        ConnectorConfig: The configuration object with the loaded values.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
        IndexError: If the configuration file does not contain the robot_id.
        yaml.YAMLError: If the configuration file is not valid YAML.
    """

    config = read_yaml(config_filename, robot_id)
    return ConnectorConfig(**config)
