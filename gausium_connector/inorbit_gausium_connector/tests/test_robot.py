# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from math import radians
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

import pytest
from inorbit_gausium_connector.src.robot.datatypes import MapData, PathData
from inorbit_gausium_connector.src.robot.robot import ModelTypeMismatchError, Robot
from inorbit_gausium_connector.src.robot.robot_api import GausiumCloudAPI


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


class TestGausiumRobotStateUpdate:
    """Tests for the Robot update methods."""

    @pytest.fixture
    def mock_robot(
        self, robot_info, device_status_data, current_position_data, robot_status_data_idle
    ):
        """Create a mock Robot instance."""
        robot = Robot(
            api_wrapper=AsyncMock(GausiumCloudAPI),
            allowed_model_types=["Scrubber 50H"],
            loglevel="DEBUG",
        )
        robot._logger = Mock()

        # Mock API methods
        robot._api_wrapper._get_robot_info = AsyncMock(return_value=robot_info)
        robot._api_wrapper._get_device_status = AsyncMock(return_value=device_status_data)
        robot._api_wrapper._fetch_position = AsyncMock(return_value=current_position_data)
        robot._api_wrapper._get_robot_status = AsyncMock(return_value=robot_status_data_idle)

        return robot

    @pytest.mark.asyncio
    async def test_update_robot_info_with_valid_model_type(self, mock_robot, robot_info):
        """Test that _update_robot_info() succeeds when the robot reports a valid model type."""

        # This should not raise an exception
        await mock_robot._update_robot_info()

        # Just verify the update completed without errors
        assert mock_robot._robot_info is not None

    @pytest.mark.asyncio
    async def test_update_robot_info_with_invalid_model_type(self, mock_robot, robot_info):
        """Test that update() raises ValueError when the robot reports an invalid model type."""
        # Create modified version of firmware_version_info with invalid model type
        invalid_robot_info = robot_info.copy()
        invalid_robot_info["data"] = robot_info["data"].copy()
        invalid_robot_info["data"]["modelType"] = "Invalid Model"

        with patch.object(
            mock_robot._api_wrapper, "_get_robot_info", return_value=invalid_robot_info
        ):
            # This should raise a ModelTypeMismatchError
            with pytest.raises(ModelTypeMismatchError) as excinfo:
                await mock_robot._update_robot_info()

            # Check the error message
            error_msg = str(excinfo.value)
            assert "is not supported by the API wrapper" in error_msg
            assert robot_info["data"]["modelType"] in error_msg
            assert "Invalid Model" in error_msg

    @pytest.mark.asyncio
    async def test_no_validation_when_allowed_model_types_empty(self, mock_robot, robot_info):
        """Test that no validation occurs when allowed_model_types is empty."""
        # Set allowed_model_types to empty list
        mock_robot._allowed_model_types = []

        # Create modified version of firmware_version_info with invalid model type
        invalid_robot_info = robot_info.copy()
        invalid_robot_info["data"] = robot_info["data"].copy()
        invalid_robot_info["data"]["modelType"] = "Invalid Model"

        with patch.object(
            mock_robot._api_wrapper, "_get_robot_info", return_value=invalid_robot_info
        ):
            # This should not raise an exception despite invalid model type
            await mock_robot._update_robot_info()

    @pytest.mark.asyncio
    async def test_explicit_ignore_model_type_validation(
        self, robot_info, device_status_data, current_position_data, robot_status_data_idle
    ):
        """Test that validation can be explicitly bypassed using empty allowed_model_types."""
        # Create API with empty allowed_model_types list (which effectively ignores validation)
        robot = Robot(
            api_wrapper=AsyncMock(GausiumCloudAPI),
            allowed_model_types=[],  # Empty list means no validation
            loglevel="DEBUG",
        )
        robot._logger = Mock()

        # Create modified version of firmware_version_info with invalid model type
        invalid_robot_info = robot_info.copy()
        invalid_robot_info["data"] = robot_info["data"].copy()
        invalid_robot_info["data"]["modelType"] = "Some Totally Invalid Model"

        with patch.object(robot._api_wrapper, "_get_robot_info", return_value=invalid_robot_info):
            # This should not raise an exception despite the invalid model type
            await robot._update_robot_info()

    @pytest.mark.asyncio
    async def test_update_robot_status(self, mock_robot, robot_status_data_idle):
        """Test that _update_robot_status() succeeds when the robot reports a valid model type."""

        # This should not raise an exception
        await mock_robot._update_robot_status()

        assert mock_robot._robot_status is not None

    @pytest.mark.asyncio
    async def test_update_device_status(self, mock_robot, device_status_data):
        """Test that _update_device_status() succeeds when the robot reports a valid model type."""

        # This should not raise an exception
        await mock_robot._update_device_status()

        assert mock_robot._device_status is not None

    @pytest.mark.asyncio
    async def test_update_position(self, mock_robot, current_position_data):
        """Test that _update_position() succeeds when the robot reports a valid model type."""

        # This should not raise an exception
        await mock_robot._update_position()

        assert mock_robot._position is not None

    def test_api_call_success_or_log(self, mock_robot, robot_status_data_idle):
        """Test that _api_call_success_or_log() returns the correct value."""

        # Test successful API call
        result = mock_robot._api_call_success_or_log(robot_status_data_idle)
        assert result is not None
        assert result == robot_status_data_idle

        # Test failed API call
        failed_response = {
            "successed": False,
            "errorCode": 500,
            "msg": "Internal Server Error",
            "data": {"details": "Something went wrong"},
        }
        result = mock_robot._api_call_success_or_log(failed_response)
        assert result == {}
        mock_robot._logger.error.assert_called_once_with(
            "API call failed with error code 500: Internal Server Error, data: {'details': "
            "'Something went wrong'}"
        )

        # Test failed API call with minimal error info
        mock_robot._logger.error.reset_mock()
        minimal_failed_response = {"successed": False}
        result = mock_robot._api_call_success_or_log(minimal_failed_response)
        assert result == {}
        mock_robot._logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_current_map_property_update(self, mock_robot, device_status_data):
        """Test that the current_map property is correctly updated."""

        # This should not raise an exception
        await mock_robot._update_position()
        await mock_robot._update_device_status()

        map = mock_robot.current_map
        assert map is not None
        assert mock_robot._api_wrapper._get_map_image.call_count == 1
        assert map.map_name == device_status_data["data"]["currentMapName"]
        assert map.map_id == device_status_data["data"]["currentMapID"]

    @pytest.mark.asyncio
    async def test_firmware_version_property_update(self, mock_robot, robot_info):
        """Test that the firmware_version property is correctly updated."""

        # This should not raise an exception
        await mock_robot._update_robot_info()

        assert mock_robot.firmware_version == "3-6-6"

    @pytest.mark.asyncio
    async def test_frame_id_property_update(self, mock_robot, device_status_data):
        """Test that the frame_id property is correctly updated."""

        # This should not raise an exception
        await mock_robot._update_position()
        await mock_robot._update_device_status()

        assert mock_robot.frame_id == device_status_data["data"]["currentMapName"]

    @pytest.mark.asyncio
    async def test_frame_id_default_value(self, mock_robot):
        """Test that the frame_id property has a default value of "map"."""

        assert mock_robot.frame_id == "map"

    @pytest.mark.asyncio
    async def test_pose_property_update(self, mock_robot, current_position_data):
        """Test that the pose property is correctly updated."""

        # This should not raise an exception
        await mock_robot._update_position()

        assert mock_robot.pose == {
            "x": current_position_data["worldPosition"]["position"]["x"],
            "y": current_position_data["worldPosition"]["position"]["y"],
            "yaw": radians(current_position_data["angle"]),
            "frame_id": "map",
        }

    @pytest.mark.asyncio
    async def test_path_property_update(self, mock_robot, robot_status_data_task):
        """Test that the path property is correctly updated."""

        # This should not raise an exception
        await mock_robot._update_robot_status()

        assert mock_robot.path is not None
        assert isinstance(mock_robot.path, PathData)


class TestGausiumRobotPaths:
    """Tests for the Robot class path handling functionality."""

    @pytest.fixture
    def mock_robot(self, map_data, monkeypatch):
        """Create a mock Robot instance for testing path generation."""
        robot = Robot(
            api_wrapper=AsyncMock(GausiumCloudAPI),
            allowed_model_types=[],
            loglevel="DEBUG",
            default_polling_freq=0.0,
        )

        # Set up current map data for coordinate conversions
        # Mock the current_map property
        type(robot).current_map = PropertyMock(return_value=map_data)

        # Mock the pose property
        type(robot).pose = PropertyMock(
            return_value={
                "x": 1.0,
                "y": 2.0,
                "yaw": 1.5708,  # ~90 degrees in radians
                "frame_id": "test_map",
            }
        )

        # Mock coordinate conversion to return predictable values
        with patch(
            "inorbit_gausium_connector.src.robot.robot.grid_units_to_coordinate",
            lambda x, y, map_data: (x / 10, y / 10),
        ):
            yield robot

    def test_path_from_task(self, mock_robot, robot_status_data_task):
        """Test path generation when robot is running a task."""

        # Call the method to extract path
        path = mock_robot._path_from_robot_status(
            robot_status_data_task.get("data"), frame_id="test_map"
        )

        # Verify path is extracted correctly
        assert path is not None
        assert path.frame_id == "test_map"
        assert path.path_id == "0"
        assert len(path.path_points) == 6
        assert path.path_points == [
            (95.1, 126.7),
            (95.2, 126.7),
            (95.3, 126.7),
            (95.7, 127.2),
            (95.8, 127.2),
            (95.7, 127.3),
        ]

    def test_path_from_navigation_to_coords(
        self, mock_robot, robot_status_data_navigating_to_coords
    ):
        """Test path generation when robot is navigating to coordinates."""
        # Call the method to extract path
        path = mock_robot._path_from_robot_status(
            robot_status_data_navigating_to_coords.get("data"), frame_id="test_map"
        )

        # Verify path is extracted correctly
        assert path is not None
        assert path.frame_id == "test_map"
        assert path.path_id == "0"
        assert len(path.path_points) == 2
        # First point should be the current position
        assert path.path_points[0] == (1.0, 2.0)
        # Second point should be the target position
        assert path.path_points[1] == (45.525001978501678, -8.5249988239258556)

    def test_path_from_navigation_to_waypoint(
        self, mock_robot, robot_status_data_navigating_to_waypoint
    ):
        """Test path generation when robot is navigating to a waypoint.
        This is the same as navigating to coordinates from the path generation perspective."""

        # Call the method to extract path
        path = mock_robot._path_from_robot_status(
            robot_status_data_navigating_to_waypoint.get("data"), frame_id="test_map"
        )

        # Verify path is extracted correctly
        assert path is not None
        assert path.frame_id == "test_map"
        assert path.path_id == "0"
        assert len(path.path_points) == 2
        # Path should connect current position to target
        assert path.path_points[0] == (1.0, 2.0)
        assert path.path_points[1] == (-46.074999386444688, -45.624999376758936)

    def test_path_from_idle(self, mock_robot, robot_status_data_idle):
        """Test path generation when robot has no path (idle status)."""

        # Call the method with idle status (which should have no path)
        path = mock_robot._path_from_robot_status(
            robot_status_data_idle.get("data"), frame_id="test_map"
        )

        # Since the robot is idle, it should have no path
        assert path is not None
        assert path.frame_id == "test_map"
        assert path.path_id == "0"
        assert len(path.path_points) == 0
