# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from typing import List, Optional, Tuple

from pydantic import BaseModel


class ModelTypeMismatchError(Exception):
    """Exception raised when the model type of the robot and the API wrapper in use do not match."""

    def __init__(self, robot_model_type: str, supported_model_types: List[str]):
        super().__init__(
            f"Robot model type '{robot_model_type}' is not supported by the API wrapper. "
            f"Supported model types are: {supported_model_types}.\n"
            "Make sure the `connector_type` value in the configuration matches the robot "
            "model."
        )


class MapData(BaseModel):
    """Data class to hold gausium map information."""

    map_name: str
    map_id: str
    origin_x: float
    origin_y: float
    resolution: float
    # Lazy loaded map image
    # NOTE: Maybe not a great solution, since some maps may be quite large
    map_image: Optional[bytes] = None


class PathData(BaseModel):
    """Data class to hold gausium path information."""

    path_points: List[Tuple[float, float]]
    path_id: str = "0"
    frame_id: str
