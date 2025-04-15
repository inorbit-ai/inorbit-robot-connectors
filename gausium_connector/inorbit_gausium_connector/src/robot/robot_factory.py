# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from pydantic import HttpUrl
from typing import Dict, List, Tuple, Type

from inorbit_gausium_connector.src.robot.robot import Robot

from .robot_api import GausiumCloudAPI, Vaccum40RobotAPI

# Mapping of connector types to their corresponding GausiumRobotAPI classes
ROBOT_API_CLASSES: Dict[str, Type[GausiumCloudAPI]] = {
    "V40": Vaccum40RobotAPI,
    # Add more mappings as new robot types are introduced
}

# Mapping of connector types to their corresponding allowed model types
# The "model type" is the value reported by the `info` endpoint. It is used to validate
# the model type of the robot and the API wrapper in use match.
CLOUD_APIS_ALLOWED_MODEL_TYPES: Dict[str, List[str]] = {
    "V40": ["VC 40 Pro"],
}


def create_robot(
    connector_type: str,
    base_url: HttpUrl,
    loglevel: str = "INFO",
    ignore_model_type_validation: bool = False,
) -> Tuple[GausiumCloudAPI, Robot]:
    """
    Factory function to create the appropriate GausiumRobotAPI instance based on connector_type
    and the corresponding Robot instance.

    Args:
        connector_type (str): The type of connector specified in the configuration.
        base_url (HttpUrl): Base URL of the robot API.
        loglevel (str, optional): Log level for the robot API. Defaults to "INFO".
        ignore_model_type_validation (bool, optional): If True, the model type validation will be
            ignored. Defaults to False.
    Returns:
        Tuple[GausiumCloudAPI, Robot]: A tuple containing the GausiumCloudAPI instance and the
            Robot instance.

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

    robot_api = api_class(base_url=base_url, loglevel=loglevel)
    robot_state = Robot(
        api_wrapper=robot_api, loglevel=loglevel, allowed_model_types=allowed_model_types
    )
    return robot_api, robot_state
