# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from pydantic import HttpUrl
from typing import Dict, Type

from .robot_api import GausiumRobotAPI, Vaccum40RobotAPI

# Mapping of connector types to their corresponding GausiumRobotAPI classes
ROBOT_API_CLASSES: Dict[str, Type[GausiumRobotAPI]] = {
    "V40": Vaccum40RobotAPI,
    # Add more mappings as new robot types are introduced
}


def create_robot_api(
    connector_type: str, base_url: HttpUrl, loglevel: str = "INFO"
) -> GausiumRobotAPI:
    """
    Factory function to create the appropriate GausiumRobotAPI instance based on connector_type.

    Args:
        connector_type (str): The type of connector specified in the configuration.
        base_url (HttpUrl): Base URL of the robot API.
        loglevel (str, optional): Log level for the robot API. Defaults to "INFO".

    Returns:
        GausiumRobotAPI: An instance of the appropriate GausiumRobotAPI subclass.

    Raises:
        ValueError: If the connector_type is not supported.
    """
    api_class = ROBOT_API_CLASSES.get(connector_type)

    if api_class is None:
        supported_types = ", ".join(ROBOT_API_CLASSES.keys())
        raise ValueError(
            f"Unsupported connector_type: {connector_type}. "
            f"Supported types are: {supported_types}"
        )

    return api_class(base_url=base_url, loglevel=loglevel)
