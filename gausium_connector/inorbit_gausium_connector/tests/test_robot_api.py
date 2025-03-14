# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import patch, Mock
from math import radians
from pydantic import HttpUrl

from inorbit_gausium_connector.src.robot.robot_api import (
    GausiumCloudAPI,
    ModelTypeMismatchError,
)


class TestGausiumCloudAPIUpdate:
    """Tests for the GausiumCloudAPI.update() method."""

    @pytest.fixture
    def mock_robot_api(self, robot_info, device_status_data, current_position_data):
        """Create a mock GausiumCloudAPI instance with validation enabled."""
        api = GausiumCloudAPI(
            base_url=HttpUrl("http://example.com/"),
            allowed_model_types=[robot_info["data"]["modelType"]],
            loglevel="DEBUG",
        )

        # Mock components to prevent actual HTTP requests
        api.logger = Mock()
        api.api_session = Mock()
        api._device_status = {}

        # Mock API methods
        api._get_robot_info = Mock(return_value=robot_info)
        api._get_device_status = Mock(return_value=device_status_data)
        api._fetch_position = Mock(return_value=current_position_data)

        return api

    def test_update_with_valid_model_type(self, mock_robot_api, robot_info):
        """Test that update() succeeds when the robot reports a valid model type."""

        # Need to patch necessary methods called in update()
        with patch.object(mock_robot_api, "_get_robot_info", return_value=robot_info):
            # This should not raise an exception
            mock_robot_api.update()

            # Just verify the update completed without errors
            assert mock_robot_api._pose is not None

    def test_pose_data_update(
        self, mock_robot_api, robot_info, device_status_data, current_position_data
    ):
        """Test that pose data is correctly updated in the update() method."""

        # Need to patch necessary methods called in update()
        with patch.object(mock_robot_api, "_get_robot_info", return_value=robot_info):
            # Run the update
            mock_robot_api.update()

            # Verify that pose was updated correctly
            assert mock_robot_api._pose is not None
            assert (
                mock_robot_api._pose["x"] == current_position_data["worldPosition"]["position"]["x"]
            )
            assert (
                mock_robot_api._pose["y"] == current_position_data["worldPosition"]["position"]["y"]
            )
            assert mock_robot_api._pose["yaw"] == radians(
                current_position_data["worldPosition"]["orientation"]["z"]
            )
            # The frame_id should be the map name from the device status
            expected_frame_id = device_status_data["data"]["currentMapName"]
            assert mock_robot_api._pose["frame_id"] == expected_frame_id

    def test_update_with_invalid_model_type(self, mock_robot_api, robot_info):
        """Test that update() raises ValueError when the robot reports an invalid model type."""
        # Create modified version of firmware_version_info with invalid model type
        invalid_robot_info = robot_info.copy()
        invalid_robot_info["data"] = robot_info["data"].copy()
        invalid_robot_info["data"]["modelType"] = "Invalid Model"

        # Patch necessary methods called in update()
        with patch.object(mock_robot_api, "_get_robot_info", return_value=invalid_robot_info):
            # This should raise a ModelTypeMismatchError
            with pytest.raises(ModelTypeMismatchError) as excinfo:
                mock_robot_api.update()

            # Check the error message
            error_msg = str(excinfo.value)
            assert "is not supported by the API wrapper" in error_msg
            assert robot_info["data"]["modelType"] in error_msg
            assert "Invalid Model" in error_msg

    def test_no_validation_when_allowed_model_types_empty(
        self, mock_robot_api, robot_info, device_status_data, current_position_data
    ):
        """Test that no validation occurs when allowed_model_types is empty."""
        # Set allowed_model_types to empty list
        mock_robot_api._allowed_model_types = []

        # Create modified version of firmware_version_info with invalid model type
        invalid_robot_info = robot_info.copy()
        invalid_robot_info["data"] = robot_info["data"].copy()
        invalid_robot_info["data"]["modelType"] = "Invalid Model"

        # Patch necessary methods called in update()
        with patch.object(mock_robot_api, "_get_robot_info", return_value=invalid_robot_info):
            # This should not raise an exception despite invalid model type
            mock_robot_api.update()

    def test_explicit_ignore_model_type_validation(
        self, robot_info, device_status_data, current_position_data
    ):
        """Test that validation can be explicitly bypassed using empty allowed_model_types."""
        # Create API with empty allowed_model_types list (which effectively ignores validation)
        api = GausiumCloudAPI(
            base_url=HttpUrl("http://example.com/"),
            allowed_model_types=[],  # Empty list means no validation
            loglevel="DEBUG",
        )

        # Mock components to prevent actual HTTP requests
        api.logger = Mock()
        api.api_session = Mock()

        # Create modified version of firmware_version_info with invalid model type
        invalid_robot_info = robot_info.copy()
        invalid_robot_info["data"] = robot_info["data"].copy()
        invalid_robot_info["data"]["modelType"] = "Some Totally Invalid Model"

        # Patch necessary methods for update()
        with (
            patch.object(api, "_get_robot_info", return_value=invalid_robot_info),
            patch.object(api, "_get_device_status", return_value=device_status_data),
            patch.object(api, "_fetch_position", return_value=current_position_data),
        ):
            # This should not raise an exception despite the invalid model type
            api.update()
