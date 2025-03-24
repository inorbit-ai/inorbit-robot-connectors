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
            assert mock_robot_api._pose["yaw"] == radians(current_position_data["angle"])
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


class TestGausiumCloudAPIPauseResume:
    """Tests for the GausiumCloudAPI pause() and resume() methods."""

    @pytest.fixture
    def mock_robot_api(self, robot_info):
        """Create a mock GausiumCloudAPI instance for testing pause/resume."""
        api = GausiumCloudAPI(
            base_url=HttpUrl("http://example.com/"),
            allowed_model_types=[],  # No validation
            loglevel="DEBUG",
        )

        # Mock components to prevent actual HTTP requests
        api.logger = Mock()
        api.api_session = Mock()

        # Set up mocks for API methods
        api._pause_task_queue = Mock(return_value=True)
        api._resume_task_queue = Mock(return_value=True)
        api._pause_cleaning_task = Mock(return_value=True)
        api._resume_cleaning_task = Mock(return_value=True)
        api._pause_navigation_task = Mock(return_value=True)
        api._resume_navigation_task = Mock(return_value=True)
        api._is_cleaning_task_finished = Mock(return_value=True)

        return api

    def test_pause_pre_v3_6_6(self, mock_robot_api):
        """Test that pause() calls _pause_task_queue() for pre v3-6-6 firmware."""
        # Mock firmware version check to return False (pre v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=False):
            # Call the pause method
            result = mock_robot_api.pause()

            # Verify the result and that the right method was called
            assert result is True
            mock_robot_api._pause_task_queue.assert_called_once()
            mock_robot_api._pause_cleaning_task.assert_not_called()
            mock_robot_api._pause_navigation_task.assert_not_called()

    def test_pause_post_v3_6_6_cleaning_finished(self, mock_robot_api):
        """Test that pause() calls _pause_cleaning_task() when cleaning is finished."""
        # Mock firmware version check to return True (post v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=True):
            # Mock cleaning task is finished
            mock_robot_api._is_cleaning_task_finished.return_value = True

            # Call the pause method
            result = mock_robot_api.pause()

            # Verify the result and that the right method was called
            assert result is True
            assert mock_robot_api._last_pause_command == "cleaning"
            mock_robot_api._pause_task_queue.assert_not_called()
            mock_robot_api._pause_cleaning_task.assert_called_once()
            mock_robot_api._pause_navigation_task.assert_not_called()

    def test_pause_post_v3_6_6_cleaning_running(self, mock_robot_api):
        """Test that pause() calls _pause_navigation_task() when cleaning is running."""
        # Mock firmware version check to return True (post v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=True):
            # Mock cleaning task is not finished
            mock_robot_api._is_cleaning_task_finished.return_value = False

            # Call the pause method
            result = mock_robot_api.pause()

            # Verify the result and that the right method was called
            assert result is True
            assert mock_robot_api._last_pause_command == "navigation"
            mock_robot_api._pause_task_queue.assert_not_called()
            mock_robot_api._pause_cleaning_task.assert_not_called()
            mock_robot_api._pause_navigation_task.assert_called_once()

    def test_resume_pre_v3_6_6(self, mock_robot_api):
        """Test that resume() calls _resume_task_queue() for pre v3-6-6 firmware."""
        # Mock firmware version check to return False (pre v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=False):
            # Call the resume method
            result = mock_robot_api.resume()

            # Verify the result and that the right method was called
            assert result is True
            mock_robot_api._resume_task_queue.assert_called_once()
            mock_robot_api._resume_cleaning_task.assert_not_called()
            mock_robot_api._resume_navigation_task.assert_not_called()

    def test_resume_post_v3_6_6_cleaning_paused(self, mock_robot_api):
        """Test that resume() calls _resume_cleaning_task() after cleaning was paused."""
        # Mock firmware version check to return True (post v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=True):
            # Set the last pause command
            mock_robot_api._last_pause_command = "cleaning"

            # Call the resume method
            result = mock_robot_api.resume()

            # Verify the result and that the right method was called
            assert result is True
            assert mock_robot_api._last_pause_command is None
            mock_robot_api._resume_task_queue.assert_not_called()
            mock_robot_api._resume_cleaning_task.assert_called_once()
            mock_robot_api._resume_navigation_task.assert_not_called()

    def test_resume_post_v3_6_6_navigation_paused(self, mock_robot_api):
        """Test that resume() calls _resume_navigation_task() after navigation was paused."""
        # Mock firmware version check to return True (post v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=True):
            # Set the last pause command
            mock_robot_api._last_pause_command = "navigation"

            # Call the resume method
            result = mock_robot_api.resume()

            # Verify the result and that the right method was called
            assert result is True
            assert mock_robot_api._last_pause_command is None
            mock_robot_api._resume_task_queue.assert_not_called()
            mock_robot_api._resume_cleaning_task.assert_not_called()
            mock_robot_api._resume_navigation_task.assert_called_once()

    def test_resume_post_v3_6_6_no_previous_pause(self, mock_robot_api):
        """Test that resume() raises an exception if no previous pause command was stored."""
        # Mock firmware version check to return True (post v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=True):
            # No last pause command set
            mock_robot_api._last_pause_command = None

            # Call the resume method and expect an exception
            with pytest.raises(Exception) as excinfo:
                mock_robot_api.resume()

            # Check the error message
            assert "No previously paused command found" in str(excinfo.value)
            mock_robot_api._resume_task_queue.assert_not_called()
            mock_robot_api._resume_cleaning_task.assert_not_called()
            mock_robot_api._resume_navigation_task.assert_not_called()

    def test_pause_api_failure(self, mock_robot_api):
        """Test pause() handles API failure when pausing."""
        # Mock firmware version check to return True (post v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=True):
            # Test when cleaning is finished
            mock_robot_api._is_cleaning_task_finished.return_value = True
            mock_robot_api._pause_cleaning_task.return_value = False

            # Call the pause method
            result = mock_robot_api.pause()

            # Check result is False due to API failure
            assert result is False
            mock_robot_api._pause_cleaning_task.assert_called_once()

            # Reset mocks
            mock_robot_api._pause_cleaning_task.reset_mock()
            mock_robot_api._pause_navigation_task.reset_mock()

            # Test when cleaning is running
            mock_robot_api._is_cleaning_task_finished.return_value = False
            mock_robot_api._pause_navigation_task.return_value = False

            # Call the pause method
            result = mock_robot_api.pause()

            # Check result is False due to API failure
            assert result is False
            mock_robot_api._pause_navigation_task.assert_called_once()

    def test_resume_api_failure(self, mock_robot_api):
        """Test resume() handles API failure when resuming."""
        # Mock firmware version check to return True (post v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=True):
            # Test cleaning case
            mock_robot_api._last_pause_command = "cleaning"
            mock_robot_api._resume_cleaning_task.return_value = False

            # Call the resume method
            result = mock_robot_api.resume()

            # Check result is False due to API failure and last_pause_command is reset
            assert result is False
            assert mock_robot_api._last_pause_command is None
            mock_robot_api._resume_cleaning_task.assert_called_once()

            # Reset mocks
            mock_robot_api._resume_cleaning_task.reset_mock()
            mock_robot_api._resume_navigation_task.reset_mock()

            # Test navigation case
            mock_robot_api._last_pause_command = "navigation"
            mock_robot_api._resume_navigation_task.return_value = False

            # Call the resume method
            result = mock_robot_api.resume()

            # Check result is False due to API failure and last_pause_command is reset
            assert result is False
            assert mock_robot_api._last_pause_command is None
            mock_robot_api._resume_navigation_task.assert_called_once()

    def test_last_pause_command_tracking(self, mock_robot_api):
        """Test that _last_pause_command tracking works correctly across multiple calls."""
        # Start with no pause command
        assert mock_robot_api._last_pause_command is None

        # First pause when cleaning is finished
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=True):
            mock_robot_api._is_cleaning_task_finished.return_value = True
            mock_robot_api.pause()
            assert mock_robot_api._last_pause_command == "cleaning"

            # Resume cleaning
            mock_robot_api.resume()
            assert mock_robot_api._last_pause_command is None

            # Now pause when cleaning is running
            mock_robot_api._is_cleaning_task_finished.return_value = False
            mock_robot_api.pause()
            assert mock_robot_api._last_pause_command == "navigation"

            # Resume navigation
            mock_robot_api.resume()
            assert mock_robot_api._last_pause_command is None
