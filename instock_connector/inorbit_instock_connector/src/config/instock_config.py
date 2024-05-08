#!/usr/bin/env python
# -*- coding: utf-8 -*-

from pydantic import BaseModel, field_validator

from .config_base_model import EdgeConnectorModel
from .utils import read_yaml

# Expected values
CONNECTOR_TYPE = "instock"
INSTOCK_API_VERSION = "0"

default_instock_config = {
    "location_tz": "America/Los_Angeles",
    "log_level": "INFO",
    "cameras": [],
    "connector_type": CONNECTOR_TYPE,
    "pose": {"x": 0, "y": 0, "yaw": 0},
    "user_scripts_dir": "./user_scripts",
}


class InstockConfigModel(BaseModel):
    """
    Specific configuration for the Instock connector.
    """

    # TODO(tomi): docstrings
    instock_base_url: str
    instock_api_version: str
    pose: dict = default_instock_config["pose"]

    # TODO(tomi): instock_base_url validator

    # TODO(russell): pose validator

    # noinspection PyMethodParameters
    @field_validator("instock_api_version")
    def api_version_validation(cls, instock_api_version):
        if instock_api_version != INSTOCK_API_VERSION:
            raise ValueError(
                f"Unexpected Instock API version '{instock_api_version}'. "
                f"Expected '{INSTOCK_API_VERSION}'"
            )
        return instock_api_version


class InstockConfig(EdgeConnectorModel):
    """Instock ASRS connector configuration schema."""

    # TODO(russell): docstrings
    connector_config: InstockConfigModel

    # noinspection PyMethodParameters
    @field_validator("connector_type")
    def connector_type_validation(cls, connector_type):
        if connector_type != CONNECTOR_TYPE:
            raise ValueError(
                f"Unexpected connector type '{connector_type}'. "
                f"Expected '{CONNECTOR_TYPE}'"
            )
        return connector_type


def load_and_validate(config_filename: str, robot_id: str) -> InstockConfig:
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
    return InstockConfig(**config)
