# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from pydantic import HttpUrl
from typing import Dict, List, Type

from .robot_api import GausiumRobotAPI, Vaccum40RobotAPI

# Mapping of connector types to their corresponding GausiumRobotAPI classes
ROBOT_API_CLASSES: Dict[str, Type[GausiumRobotAPI]] = {
    "V40": Vaccum40RobotAPI,
    # Add more mappings as new robot types are introduced
}

# Mapping of connector types to their corresponding allowed model types
# The "model type" is the value reported by the `info` endpoint. It is used to validate
# the model type of the robot and the API wrapper in use match.
CLOUD_APIS_ALLOWED_MODEL_TYPES: Dict[str, List[str]] = {
    "V40": ["VC 40 Pro"],
}


def create_robot_api(
    connector_type: str,
    base_url: HttpUrl,
    loglevel: str = "INFO",
    ignore_model_type_validation: bool = False,
) -> GausiumRobotAPI:
    """
    Factory function to create the appropriate GausiumRobotAPI instance based on connector_type.

    Args:
        connector_type (str): The type of connector specified in the configuration.
        base_url (HttpUrl): Base URL of the robot API.
        loglevel (str, optional): Log level for the robot API. Defaults to "INFO".
        ignore_model_type_validation (bool, optional): If True, the model type validation will be
            ignored. Defaults to False.
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

    allowed_model_types = (
        CLOUD_APIS_ALLOWED_MODEL_TYPES.get(connector_type, [])
        if not ignore_model_type_validation
        else []
    )

    return api_class(base_url=base_url, loglevel=loglevel, allowed_model_types=allowed_model_types)
