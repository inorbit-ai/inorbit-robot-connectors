#!/usr/bin/env python
# -*- coding: utf-8 -*-

# MIT License
#
# Copyright (C) 2024 InOrbit, Inc.

# Standard
import numbers
import os

# Third Party
from pydantic import BaseModel, field_validator, HttpUrl

from ..abstract import InorbitConnectorModel
from ..abstract.utils import read_yaml

# Accepted values
CONNECTOR_TYPE = "instock"
DEFAULT_INSTOCK_API_VERSION = "v1"
DEFAULT_INSTOCK_API_URL = f"https://ca.instock.com/incus/{DEFAULT_INSTOCK_API_VERSION}"
VALID_INSTOCK_API_VERSIONS = [DEFAULT_INSTOCK_API_VERSION]

default_instock_config = {
    "location_tz": "America/Los_Angeles",
    "log_level": "INFO",
    "cameras": [],
    "connector_type": CONNECTOR_TYPE,
    "pose": {"x": 0, "y": 0, "yaw": 0},
    "user_scripts_dir": "./user_scripts",
}


class InstockConfigModel(BaseModel):
    """ A class representing the Instock abstract Model.

    InstockConfigModel class is responsible for holding the configuration values related
    to the InStock API. It inherits from the BaseModel class.

    Attributes:
        - instock_api_url (HttpUrl, optional): The URL of the InStock API. Defaults to
                                               DEFAULT_INSTOCK_API_URL.
        - instock_api_token (str): The token used for authentication with InStock.
        - instock_api_version (str, optional): The version of the InStock API. Defaults
                                               to DEFAULT_INSTOCK_API_VERSION.
        - instock_site_id (str): The ID of the InStock site.
        - pose (dict, optional): The pose information which consists of "x", "y", and
                                 "yaw" values. Defaults to {"x": 0, "y": 0, "yaw": 0}.
    """
    instock_api_url: HttpUrl = os.getenv("INSTOCK_API_URL", DEFAULT_INSTOCK_API_URL)
    instock_api_token: str = os.getenv("INSTOCK_API_TOKEN")
    instock_api_version: str = DEFAULT_INSTOCK_API_VERSION
    instock_site_id: str
    instock_org_id: str
    pose: dict = default_instock_config["pose"]

    # TODO(tomi): instock_base_url validator

    # noinspection PyMethodParameters
    @field_validator("pose")
    def pose_validation(cls, pose: dict) -> dict:
        """Validate a post dictionary.

        Validates a pose contains x, y, and yaw values of any number type.

        Args:
            pose (dict): A dictionary representing a pose with keys "x", "y", and "yaw".

        Returns:
            dict: The same pose dictionary passed as input, if it passes the validation.

        Raises:
            ValueError: If the pose dictionary doesn't contain all and only the required
            keys "x", "y", and "yaw", or if any of the pose values are not numbers.
        """

        required_keys = {"x", "y", "yaw"}
        if set(pose.keys()) != required_keys:
            raise ValueError(
                'Must contain all and only the following keys: "x", "y", "yaw"'
            )
        if not all(isinstance(val, numbers.Number) for val in pose.values()):
            raise ValueError("All pose values must be numbers")
        return pose

    # noinspection PyMethodParameters
    @field_validator("instock_api_version")
    def api_version_validation(cls, instock_api_version):
        """Validates the Instock API version.

        Validates against all known supported API versions.

        Args:
            instock_api_version (str): The Instock API version to be validated.

        Returns:
            str: The validated Instock API version.

        Raises:
            ValueError: If the Instock API version is not a valid supported API version.

        """

        if instock_api_version not in VALID_INSTOCK_API_VERSIONS:
            raise ValueError("Invalid Instock API version")
        return instock_api_version


class InstockConfig(InorbitConnectorModel):
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
