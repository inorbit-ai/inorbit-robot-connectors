# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from inorbit_gausium_connector.src.robot.robot import MapData

from inorbit_gausium_connector.src.robot.utils import (
    coordinate_to_grid_units,
    grid_units_to_coordinate,
)


@pytest.fixture
def map_data():
    """Create a MapData instance with known values for testing."""

    return MapData(
        map_name="test_map",
        map_id="test_map_id",
        origin_x=-10.0,
        origin_y=-5.0,
        resolution=0.05,
        map_image=None,  # No image needed for these tests
    )


class TestGausiumCoordinateConversion:
    """Tests for the coordinate conversion methods."""

    def test_coordinate_to_grid_units(self, map_data):
        """Test coordinate conversion with standard values."""
        # Test case 1: Origin point should convert to (0,0) in grid units
        grid_x, grid_y = coordinate_to_grid_units(-10.0, -5.0, map_data)
        assert grid_x == 0
        assert grid_y == 0

        # Test case 2: 1 meter in each direction from origin
        grid_x, grid_y = coordinate_to_grid_units(-9.0, -4.0, map_data)
        assert grid_x == 20  # ((-9) - (-10)) / 0.05 = 20
        assert grid_y == 20  # ((-4) - (-5)) / 0.05 = 20

        # Test case 3: Arbitrary point
        grid_x, grid_y = coordinate_to_grid_units(5.0, 7.5, map_data)
        assert grid_x == 300  # (5 - (-10)) / 0.05 = 300
        assert grid_y == 250  # (7.5 - (-5)) / 0.05 = 250

    def test_coordinate_to_grid_units_rounding(self, map_data):
        """Test that coordinate conversion properly rounds to integers."""
        # Test with fractional results that should be rounded to nearest integer
        grid_x, grid_y = coordinate_to_grid_units(-9.974, -4.987, map_data)
        assert grid_x == 1  # ((-9.974) - (-10)) / 0.05 = 0.52 → 1 (rounded to nearest)
        assert grid_y == 0  # ((-4.987) - (-5)) / 0.05 = 0.26 → 0 (rounded to nearest)

    def test_coordinate_to_grid_units_zero_resolution(self, map_data):
        """Test behavior when map resolution is zero (should raise ZeroDivisionError)."""
        # Modify map_data to have zero resolution
        map_data.resolution = 0.0

        with pytest.raises(ZeroDivisionError):
            coordinate_to_grid_units(0.0, 0.0, map_data)

    def test_grid_units_to_coordinate(self, map_data):
        """Test grid units to coordinate conversion with standard values."""
        # Test case 1: Origin point (0,0) in grid units should convert to origin coordinates
        coord_x, coord_y = grid_units_to_coordinate(0, 0, map_data)
        assert coord_x == -10.0
        assert coord_y == -5.0

        # Test case 2: 20 grid units in each direction (1 meter with 0.05 resolution)
        coord_x, coord_y = grid_units_to_coordinate(20, 20, map_data)
        assert coord_x == -9.0  # 20 * 0.05 + (-10) = -9.0
        assert coord_y == -4.0  # 20 * 0.05 + (-5) = -4.0

        # Test case 3: Arbitrary grid point
        coord_x, coord_y = grid_units_to_coordinate(300, 250, map_data)
        assert coord_x == 5.0  # 300 * 0.05 + (-10) = 5.0
        assert coord_y == 7.5  # 250 * 0.05 + (-5) = 7.5

    def test_grid_units_to_coordinate_consistency(self, map_data):
        """Test that coordinate conversion is consistent in both directions."""
        # Convert from coordinates to grid units
        test_coords = [
            (-10.0, -5.0),  # Origin
            (-9.0, -4.0),  # 1m from origin
            (5.0, 7.5),  # Random point
        ]

        for x, y in test_coords:
            # Convert coordinates -> grid units
            grid_x, grid_y = coordinate_to_grid_units(x, y, map_data)
            # Convert back grid units -> coordinates
            coord_x, coord_y = grid_units_to_coordinate(grid_x, grid_y, map_data)

            # Check that we get back the original coordinates (within floating point precision)
            assert abs(coord_x - x) < 1e-10
            assert abs(coord_y - y) < 1e-10
