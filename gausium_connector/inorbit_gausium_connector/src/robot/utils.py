# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from inorbit_gausium_connector.src.robot.datatypes import MapData


def coordinate_to_grid_units(x: float, y: float, map: MapData) -> tuple[int, int]:
    """Convert coordinates to grid units of a map

    Args:
        x (float): X coordinate in meters
        y (float): Y coordinate in meters

    Returns:
        tuple[int, int]: Grid units in the map
    """
    resolution = map.resolution
    origin_x = map.origin_x
    origin_y = map.origin_y

    grid_x = round((x - origin_x) / resolution)
    grid_y = round((y - origin_y) / resolution)
    return grid_x, grid_y


def grid_units_to_coordinate(x: int, y: int, map: MapData) -> tuple[float, float]:
    """Convert grid units to coordinates of a map

    Args:
        x (int): X coordinate in grid units
        y (int): Y coordinate in grid units
        map (MapData): The map to convert the coordinates to

    Returns:
        tuple[float, float]: Coordinates in the map
    """
    resolution = map.resolution
    origin_x = map.origin_x
    origin_y = map.origin_y

    coordinate_x = x * resolution + origin_x
    coordinate_y = y * resolution + origin_y
    return coordinate_x, coordinate_y
