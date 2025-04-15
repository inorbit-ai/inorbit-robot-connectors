# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import patch, Mock, AsyncMock
from pydantic import HttpUrl

from inorbit_gausium_connector.src.robot.robot_api import GausiumCloudAPI
from inorbit_gausium_connector.src.robot.datatypes import MapData


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


class TestGausiumCloudAPIPauseResume:
    """Tests for the GausiumCloudAPI pause() and resume() methods."""

    @pytest.fixture
    def mock_robot_api(self, robot_info):
        """Create a mock GausiumCloudAPI instance for testing pause/resume."""
        api = GausiumCloudAPI(
            base_url=HttpUrl("http://example.com/"),
            loglevel="DEBUG",
        )

        # Mock components to prevent actual HTTP requests
        api.logger = Mock()
        api.api_session = Mock()

        # Set up mocks for API methods
        api._pause_task_queue = AsyncMock(return_value=True)
        api._resume_task_queue = AsyncMock(return_value=True)
        api._pause_cleaning_task = AsyncMock(return_value=True)
        api._resume_cleaning_task = AsyncMock(return_value=True)
        api._pause_navigation_task = AsyncMock(return_value=True)
        api._resume_navigation_task = AsyncMock(return_value=True)
        api._is_cleaning_task_finished = AsyncMock(return_value=True)

        return api

    @pytest.mark.asyncio
    async def test_pause_pre_v3_6_6(self, mock_robot_api):
        """Test that pause() calls _pause_task_queue() for pre v3-6-6 firmware."""
        # Mock firmware version check to return False (pre v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=False):
            # Call the pause method
            result = await mock_robot_api.pause(...)

            # Verify the result and that the right method was called
            assert result is True
            mock_robot_api._pause_task_queue.assert_called_once()
            mock_robot_api._pause_cleaning_task.assert_not_called()
            mock_robot_api._pause_navigation_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_pause_post_v3_6_6_cleaning_finished(self, mock_robot_api):
        """Test that pause() calls _pause_cleaning_task() when cleaning is finished."""
        # Mock firmware version check to return True (post v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=True):
            # Mock cleaning task is finished
            mock_robot_api._is_cleaning_task_finished.return_value = True

            # Call the pause method
            result = await mock_robot_api.pause(...)

            # Verify the result and that the right method was called
            assert result is True
            assert mock_robot_api._last_pause_command == "navigation"
            mock_robot_api._pause_navigation_task.assert_called_once()
            mock_robot_api._pause_cleaning_task.assert_not_called()
            mock_robot_api._pause_task_queue.assert_not_called()

    @pytest.mark.asyncio
    async def test_pause_post_v3_6_6_cleaning_running(self, mock_robot_api):
        """Test that pause() calls _pause_navigation_task() when cleaning is running."""
        # Mock firmware version check to return True (post v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=True):
            # Mock cleaning task is not finished
            mock_robot_api._is_cleaning_task_finished.return_value = False

            # Call the pause method
            result = await mock_robot_api.pause(...)

            # Verify the result and that the right method was called
            assert result is True
            assert mock_robot_api._last_pause_command == "cleaning"
            mock_robot_api._pause_cleaning_task.assert_called_once()
            mock_robot_api._pause_navigation_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_pre_v3_6_6(self, mock_robot_api):
        """Test that resume() calls _resume_task_queue() for pre v3-6-6 firmware."""
        # Mock firmware version check to return False (pre v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=False):
            # Call the resume method
            result = await mock_robot_api.resume(...)

            # Verify the result and that the right method was called
            assert result is True
            mock_robot_api._resume_task_queue.assert_called_once()
            mock_robot_api._resume_cleaning_task.assert_not_called()
            mock_robot_api._resume_navigation_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_post_v3_6_6_cleaning_paused(self, mock_robot_api):
        """Test that resume() calls _resume_cleaning_task() after cleaning was paused."""
        # Mock firmware version check to return True (post v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=True):
            # Set the last pause command
            mock_robot_api._last_pause_command = "cleaning"

            # Call the resume method
            result = await mock_robot_api.resume(...)

            # Verify the result and that the right method was called
            assert result is True
            assert mock_robot_api._last_pause_command is None
            mock_robot_api._resume_task_queue.assert_not_called()
            mock_robot_api._resume_cleaning_task.assert_called_once()
            mock_robot_api._resume_navigation_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_post_v3_6_6_navigation_paused(self, mock_robot_api):
        """Test that resume() calls _resume_navigation_task() after navigation was paused."""
        # Mock firmware version check to return True (post v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=True):
            # Set the last pause command
            mock_robot_api._last_pause_command = "navigation"

            # Call the resume method
            result = await mock_robot_api.resume(...)

            # Verify the result and that the right method was called
            assert result is True
            assert mock_robot_api._last_pause_command is None
            mock_robot_api._resume_task_queue.assert_not_called()
            mock_robot_api._resume_navigation_task.assert_called_once()
            mock_robot_api._resume_cleaning_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_post_v3_6_6_no_previous_pause(self, mock_robot_api):
        """Test that resume() raises an exception if no previous pause command was stored."""
        # Mock firmware version check to return True (post v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=True):
            # No last pause command set
            mock_robot_api._last_pause_command = None

            # Call the resume method and expect an exception
            with pytest.raises(Exception) as excinfo:
                await mock_robot_api.resume(...)

            # Check the error message
            assert "No previously paused command found" in str(excinfo.value)
            mock_robot_api._resume_task_queue.assert_not_called()
            mock_robot_api._resume_cleaning_task.assert_not_called()
            mock_robot_api._resume_navigation_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_pause_api_failure(self, mock_robot_api):
        """Test pause() handles API failure when pausing."""
        # Mock firmware version check to return True (post v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=True):
            # Test when cleaning is finished
            mock_robot_api._is_cleaning_task_finished.return_value = True
            mock_robot_api._pause_navigation_task.return_value = False

            # Call the pause method
            result = await mock_robot_api.pause(...)

            # Check result is False due to API failure
            assert result is False
            mock_robot_api._pause_navigation_task.assert_called_once()
            mock_robot_api._pause_cleaning_task.assert_not_called()

            # Reset mocks
            mock_robot_api._pause_cleaning_task.reset_mock()
            mock_robot_api._pause_navigation_task.reset_mock()

            # Test when cleaning is running
            mock_robot_api._is_cleaning_task_finished.return_value = False
            mock_robot_api._pause_cleaning_task.return_value = False

            # Call the pause method
            result = await mock_robot_api.pause(...)

            # Check result is False due to API failure
            assert result is False
            mock_robot_api._pause_cleaning_task.assert_called_once()
            mock_robot_api._pause_navigation_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_api_failure(self, mock_robot_api):
        """Test resume() handles API failure when resuming."""
        # Mock firmware version check to return True (post v3-6-6)
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=True):
            # Test cleaning case
            mock_robot_api._last_pause_command = "cleaning"
            mock_robot_api._resume_cleaning_task.return_value = False

            # Call the resume method
            result = await mock_robot_api.resume(...)

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
            result = await mock_robot_api.resume(...)

            # Check result is False due to API failure and last_pause_command is reset
            assert result is False
            assert mock_robot_api._last_pause_command is None
            mock_robot_api._resume_navigation_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_last_pause_command_tracking(self, mock_robot_api):
        """Test that _last_pause_command tracking works correctly across multiple calls."""
        # Start with no pause command
        assert mock_robot_api._last_pause_command is None

        # First pause when cleaning is finished
        with patch.object(mock_robot_api, "_is_firmware_post_v3_6_6", return_value=True):
            mock_robot_api._is_cleaning_task_finished.return_value = True
            await mock_robot_api.pause(...)
            assert mock_robot_api._last_pause_command == "navigation"

            # Resume cleaning
            await mock_robot_api.resume(...)
            assert mock_robot_api._last_pause_command is None

            # Now pause when cleaning is running
            mock_robot_api._is_cleaning_task_finished.return_value = False
            await mock_robot_api.pause(...)
            assert mock_robot_api._last_pause_command == "cleaning"

            # Resume cleaning
            await mock_robot_api.resume(...)
            assert mock_robot_api._last_pause_command is None
