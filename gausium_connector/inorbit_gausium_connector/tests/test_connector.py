# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import logging
import math
from unittest.mock import AsyncMock, MagicMock, Mock, call

import pytest
from inorbit_edge.commands import COMMAND_INITIAL_POSE
from inorbit_edge.robot import (
    COMMAND_CUSTOM_COMMAND,
    COMMAND_MESSAGE,
    COMMAND_NAV_GOAL,
    RobotSession,
)
from inorbit_gausium_connector.src.config.connector_model import ConnectorConfig
from inorbit_gausium_connector.src.connector import GausiumConnector
from inorbit_gausium_connector.src.robot.datatypes import MapData


class TestGausiumConnector:
    """Tests for the GausiumConnector class."""

    @pytest.fixture
    def connector(self, monkeypatch):
        # Patch environment and robot session
        monkeypatch.setenv("INORBIT_KEY", "abc123")
        monkeypatch.setattr(RobotSession, "connect", MagicMock())

        # Mock the logger to suppress Pydantic validation warnings
        mock_logger = Mock(spec=logging.Logger)
        monkeypatch.setattr(logging, "getLogger", Mock(return_value=mock_logger))

        # Create the connector with test configuration
        connector = GausiumConnector(
            "hoolibot3000-1",
            ConnectorConfig(
                inorbit_robot_key="robot_key",
                location_tz="UTC",
                log_level="INFO",
                connector_type="V40",
                connector_version="0.1.0",
                connector_config={
                    "base_url": "https://hoolibot.local",
                },
                user_scripts={"path": "/path/to/scripts"},
            ),
        )

        # Mock API and session
        connector.robot_api = AsyncMock()
        connector.robot_state = MagicMock()
        connector.mission_tracking = MagicMock()
        connector._robot_session = MagicMock()

        # Explicitly set the logger to our mock
        connector._logger = mock_logger

        return connector

    @pytest.fixture
    def callback_kwargs(self):
        return {
            "command_name": "cmd_name",
            "args": [],
            "options": {
                "result_function": Mock(),
                "progress_funtion": Mock(),
                "metadata": {},
            },
        }

    def test_publish_map(self, connector, monkeypatch):
        """Test the publish_map method in different scenarios."""
        # Mock the parent class's publish_map method
        super_publish_map = MagicMock()
        monkeypatch.setattr("inorbit_connector.connector.Connector.publish_map", super_publish_map)

        # Mock the MapConfig class to avoid file validation
        mock_map_config = MagicMock()
        monkeypatch.setattr("inorbit_gausium_connector.src.connector.MapConfig", mock_map_config)

        # Mock the api to return a fake image
        connector.robot_api.get_map_image_sync = MagicMock(return_value=b"fake_image_data")

        # Test case 1: Map exists in config
        # Setup a test map in the config
        connector.config.maps = {"existing_map": MagicMock()}

        # Call the method with an existing map
        connector.publish_map("existing_map")

        # Verify parent method was called with correct parameters
        super_publish_map.assert_called_once_with("existing_map", False)
        super_publish_map.reset_mock()

        # Test case 2: Map doesn't exist in config but robot provides map data
        # Create mock map data from the robot
        mock_map_data = MagicMock(MapData)
        mock_map_data.map_id = "robot_map"
        mock_map_data.map_name = "test_map_name"
        mock_map_data.origin_x = 10.5
        mock_map_data.origin_y = 20.7
        mock_map_data.resolution = 0.05
        connector.robot_state.current_map = mock_map_data

        # Mock tempfile.mkstemp to return a known file descriptor and path
        mock_fd = 42
        mock_temp_path = "/tmp/test_map.png"
        monkeypatch.setattr("tempfile.mkstemp", Mock(return_value=(mock_fd, mock_temp_path)))

        # Mock os.fdopen to avoid actual file operations
        mock_file = MagicMock()
        mock_fdopen = MagicMock(return_value=mock_file)
        monkeypatch.setattr("os.fdopen", mock_fdopen)

        # Mock PIL Image operations
        mock_image = MagicMock()
        mock_flipped_image = MagicMock()
        mock_image.transpose.return_value = mock_flipped_image
        mock_byte_io = MagicMock()
        mock_byte_io.getvalue.return_value = b"flipped_image_data"

        # Mock Image.open and io.BytesIO
        monkeypatch.setattr("PIL.Image.open", Mock(return_value=mock_image))
        monkeypatch.setattr("io.BytesIO", Mock(return_value=mock_byte_io))

        # Call the method with a non-existing map
        mock_map_data.map_name = "new_map"
        connector.publish_map("new_map")

        # Verify the map image was fetched from the robot
        connector.robot_api.get_map_image_sync.assert_called_once_with("new_map")

        # Verify temporary file was created and written to
        assert mock_fdopen.call_args.args[0] == mock_fd
        assert mock_fdopen.call_args.args[1] == "wb"
        mock_file.__enter__().write.assert_called_once_with(b"flipped_image_data")

        # Verify MapConfig was called with the correct parameters
        # Now using the actual property values from mock_map_data
        mock_map_config.assert_called_once_with(
            file=mock_temp_path,
            map_id="new_map",
            frame_id="new_map",
            origin_x=mock_map_data.origin_x,
            origin_y=mock_map_data.origin_y,
            resolution=mock_map_data.resolution,
        )

        # Verify parent method was called to publish the map
        super_publish_map.assert_called_once_with("new_map", False)
        super_publish_map.reset_mock()

        # Test case 3: Map doesn't exist and robot doesn't provide map data
        connector.robot_state.current_map = None
        connector.config.maps = {}  # Reset maps

        # Call the method
        connector.publish_map("nonexistent_map")

        # Verify parent method was not called since no map was available
        assert not super_publish_map.called

        # Test case 4: Error flipping the image
        connector.robot_state.current_map = mock_map_data
        monkeypatch.setattr("PIL.Image.open", Mock(side_effect=Exception("Failed to open image")))

        # Reset counters for this test case
        mock_map_config.reset_mock()
        mock_file.__enter__().write.reset_mock()

        # Call the method
        mock_map_data.map_name = "error_map"
        connector.publish_map("error_map")

        # Verify original bytes were used when flipping failed
        mock_file.__enter__().write.assert_called_once_with(b"fake_image_data")

    def test_connector_passes_ignore_model_type_validation(self, monkeypatch):
        """Test that ignore_model_type_validation parameter is passed to the robot API."""
        # Patch environment and robot session
        monkeypatch.setenv("INORBIT_KEY", "abc123")
        monkeypatch.setattr(RobotSession, "connect", MagicMock())

        # Mock the create_robot function
        mock_create_robot = MagicMock(return_value=(..., ...))
        monkeypatch.setattr(
            "inorbit_gausium_connector.src.connector.create_robot", mock_create_robot
        )

        # Create a connector with ignore_model_type_validation set to True
        GausiumConnector(
            "hoolibot3000-1",
            ConnectorConfig(
                inorbit_robot_key="robot_key",
                location_tz="UTC",
                log_level="INFO",
                connector_type="V40",
                connector_version="0.1.0",
                connector_config={
                    "base_url": "https://hoolibot.local",
                    "ignore_model_type_validation": True,
                },
                user_scripts={"path": "/path/to/scripts"},
            ),
        )

        # Verify that create_robot was called with ignore_model_type_validation=True
        mock_create_robot.assert_called_once()
        call_kwargs = mock_create_robot.call_args.kwargs
        assert call_kwargs["ignore_model_type_validation"] is True

        # Reset the mock
        mock_create_robot.reset_mock()

        # Create a connector with ignore_model_type_validation set to False
        GausiumConnector(
            "hoolibot3000-1",
            ConnectorConfig(
                inorbit_robot_key="robot_key",
                location_tz="UTC",
                log_level="INFO",
                connector_type="V40",
                connector_version="0.1.0",
                connector_config={
                    "base_url": "https://hoolibot.local",
                    "ignore_model_type_validation": False,
                },
                user_scripts={"path": "/path/to/scripts"},
            ),
        )

        # Verify that create_robot was called with ignore_model_type_validation=False
        mock_create_robot.assert_called_once()
        call_kwargs = mock_create_robot.call_args.kwargs
        assert call_kwargs["ignore_model_type_validation"] is False

    @pytest.mark.asyncio
    async def test_command_callback_unknown_commands(self, connector, callback_kwargs, monkeypatch):
        # Unknown command
        callback_kwargs["command_name"] = "unknown_command"
        await connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with(
            "1", "'unknown_command' is not implemented"
        )

        # Unknown customCommand command
        callback_kwargs["options"]["result_function"].reset_mock()
        callback_kwargs["command_name"] = "customCommand"
        callback_kwargs["args"] = ["unknown_custom_command", ["arg1", "arg2"]]
        await connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with(
            "1", "Custom command 'unknown_custom_command' is not implemented"
        )

        # Unknown message command
        callback_kwargs["options"]["result_function"].reset_mock()
        callback_kwargs["command_name"] = "message"
        callback_kwargs["args"] = ["unknown_message", ["arg1", "arg2"]]
        await connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with(
            "1", "Message 'unknown_message' is not implemented"
        )

        # Script command
        callback_kwargs["options"]["result_function"].reset_mock()
        callback_kwargs["command_name"] = "customCommand"
        callback_kwargs["args"] = ["script.sh", ["arg1", "arg2"]]
        # The connector should let the edge-sdk handle this
        await connector._inorbit_command_handler(**callback_kwargs)
        assert not callback_kwargs["options"]["result_function"].called

    @pytest.mark.asyncio
    async def test_command_callback_nav_goal(self, connector, callback_kwargs):
        callback_kwargs["command_name"] = COMMAND_NAV_GOAL
        callback_kwargs["args"] = [{"x": "1", "y": "2", "theta": "3.14"}]
        await connector._inorbit_command_handler(**callback_kwargs)
        assert connector.robot_api.send_waypoint.call_args_list == [
            call(
                1.0,
                2.0,
                math.degrees(3.14),
                connector.robot_state.current_map.map_name,
                connector.robot_state.firmware_version,
            )
        ]
        callback_kwargs["options"]["result_function"].assert_called_with("0")

    @pytest.mark.asyncio
    async def test_command_callback_initial_pose(self, connector, callback_kwargs):
        connector.robot_state.current_map = MapData(
            map_name="test_map",
            map_id="test_map_id",
            origin_x=0,
            origin_y=0,
            resolution=0.05,
        )
        callback_kwargs["command_name"] = COMMAND_INITIAL_POSE
        callback_kwargs["args"] = [{"x": "1", "y": "2", "theta": "3.1415"}]
        connector.robot_state.pose = {"x": 0, "y": 0, "yaw": 0, "frame_id": "test_map"}
        await connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with("0")
        assert connector.robot_api.localize_at.call_args_list[0].args[0] == 1
        assert connector.robot_api.localize_at.call_args_list[0].args[1] == 2
        assert abs(connector.robot_api.localize_at.call_args_list[0].args[2] - 180) < 0.1
        assert connector.robot_api.localize_at.call_args_list[0].args[3] == "test_map"
        connector.robot_api.localize_at.reset_mock()
        callback_kwargs["args"] = [{"x": "1", "y": "2", "theta": "3.1415"}]
        connector.robot_state.pose = {"x": 1, "y": 2, "yaw": 3.1415, "frame_id": "test_map"}
        await connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with("0")
        assert connector.robot_api.localize_at.call_args_list[0].args[0] == 2
        assert connector.robot_api.localize_at.call_args_list[0].args[1] == 4
        assert abs(connector.robot_api.localize_at.call_args_list[0].args[2]) < 0.1
        assert connector.robot_api.localize_at.call_args_list[0].args[3] == "test_map"

    @pytest.mark.asyncio
    async def test_command_callback_inorbit_messages(self, connector, callback_kwargs):
        callback_kwargs["command_name"] = COMMAND_MESSAGE
        # InOrbit pause message
        callback_kwargs["args"] = ["inorbit_pause"]
        await connector._inorbit_command_handler(**callback_kwargs)
        connector.robot_api.pause.assert_called_once()
        callback_kwargs["options"]["result_function"].assert_called_with("0")

        # InOrbit resume message
        callback_kwargs["args"] = ["inorbit_resume"]
        await connector._inorbit_command_handler(**callback_kwargs)
        connector.robot_api.resume.assert_called_once()
        callback_kwargs["options"]["result_function"].assert_called_with("0")

        # Unknown message
        callback_kwargs["args"] = ["unknown_message"]
        await connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with(
            "1", "Message 'unknown_message' is not implemented"
        )

    @pytest.mark.asyncio
    async def test_command_callback_custom_command(self, connector, callback_kwargs):
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND

        # Test with invalid arguments
        callback_kwargs["args"] = ["script_name", ["not_even_key_value_pairs"]]
        await connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with("1", "Invalid arguments")

    @pytest.mark.asyncio
    async def test_command_callback_start_task_queue(self, connector, callback_kwargs):
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
        callback_kwargs["args"] = [
            "start_task_queue",
            ["task_queue_name", "vacuum_zone_corridor_123"],
        ]
        await connector._inorbit_command_handler(**callback_kwargs)
        # Verify the result function was called with success code
        callback_kwargs["options"]["result_function"].assert_called_with("0")
        # Verify the robot API method was called with the correct parameters
        connector.robot_api.start_task_queue.assert_called_once_with(
            "vacuum_zone_corridor_123",  # task_queue_name
            None,  # map_name (defaults to None/current map)
            False,  # loop (default)
            0,  # loop_count (default)
        )

        # Reset the mock
        connector.robot_api.start_task_queue.reset_mock()

        # Test with additional parameters
        callback_kwargs["args"] = [
            "start_task_queue",
            [
                "task_queue_name",
                "vacuum_zone_corridor_123",
                "map_name",
                "test_map",
                "loop",
                True,
                "loop_count",
                3,
            ],
        ]
        await connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with("0")
        connector.robot_api.start_task_queue.assert_called_once_with(
            "vacuum_zone_corridor_123",
            "test_map",
            True,
            3,
        )

    @pytest.mark.asyncio
    async def test_command_callback_send_to_named_waypoint(self, connector, callback_kwargs):
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
        callback_kwargs["args"] = ["send_to_named_waypoint", ["position_name", "waypoint_1"]]
        await connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with("0")
        connector.robot_api.send_to_named_waypoint.assert_called_once_with(
            "waypoint_1",
            connector.robot_state.current_map.map_name,
            connector.robot_state.firmware_version,
        )
        connector.robot_api.send_to_named_waypoint.reset_mock()

        # Test with map name
        callback_kwargs["args"] = [
            "send_to_named_waypoint",
            ["position_name", "waypoint_1", "map_name", "test_map"],
        ]
        await connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with("0")
        connector.robot_api.send_to_named_waypoint.assert_called_once_with(
            "waypoint_1",
            "test_map",
            connector.robot_state.firmware_version,
        )

    @pytest.mark.asyncio
    async def test_command_callback_pause_task_queue(self, connector, callback_kwargs):
        # Set up the robot to be available
        connector.robot_api._last_call_successful = True
        connector.status = {"online": True}

        # Configure the custom command for pausing cleaning task
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
        callback_kwargs["args"] = ["pause_task_queue", []]

        # Call the handler
        await connector._inorbit_command_handler(**callback_kwargs)

        # Verify the result function was called with success code
        callback_kwargs["options"]["result_function"].assert_called_with("0")

        # Verify the robot API method was called
        connector.robot_api.pause_task_queue.assert_called_once()

    @pytest.mark.asyncio
    async def test_command_callback_resume_task_queue(self, connector, callback_kwargs):
        # Set up the robot to be available
        connector.robot_api._last_call_successful = True
        connector.status = {"online": True}

        # Configure the custom command for resuming cleaning task
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
        callback_kwargs["args"] = ["resume_task_queue", []]

        # Call the handler
        await connector._inorbit_command_handler(**callback_kwargs)

        # Verify the result function was called with success code
        callback_kwargs["options"]["result_function"].assert_called_with("0")

        # Verify the robot API method was called
        connector.robot_api.resume_task_queue.assert_called_once()

    @pytest.mark.asyncio
    async def test_command_callback_cancel_task_queue(self, connector, callback_kwargs):
        # Set up the robot to be available
        connector.robot_api._last_call_successful = True
        connector.status = {"online": True}

        # Configure the custom command for canceling cleaning task
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
        callback_kwargs["args"] = ["cancel_task_queue", []]

        # Call the handler
        await connector._inorbit_command_handler(**callback_kwargs)

        # Verify the result function was called with success code
        callback_kwargs["options"]["result_function"].assert_called_with("0")

        # Verify the robot API method was called
        connector.robot_api.cancel_task_queue.assert_called_once()

    @pytest.mark.asyncio
    async def test_command_callback_pause_navigation_task(self, connector, callback_kwargs):
        # Set up the robot to be available
        connector.robot_api._last_call_successful = True
        connector.status = {"online": True}

        # Configure the custom command for pausing navigation task
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
        callback_kwargs["args"] = ["pause_navigation_task", []]

        # Call the handler
        await connector._inorbit_command_handler(**callback_kwargs)

        # Verify the result function was called with success code
        callback_kwargs["options"]["result_function"].assert_called_with("0")

        # Verify the robot API method was called
        connector.robot_api.pause_navigation_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_command_callback_resume_navigation_task(self, connector, callback_kwargs):
        # Set up the robot to be available
        connector.robot_api._last_call_successful = True
        connector.status = {"online": True}

        # Configure the custom command for resuming navigation task
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
        callback_kwargs["args"] = ["resume_navigation_task", []]

        # Call the handler
        await connector._inorbit_command_handler(**callback_kwargs)

        # Verify the result function was called with success code
        callback_kwargs["options"]["result_function"].assert_called_with("0")

        # Verify the robot API method was called
        connector.robot_api.resume_navigation_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_command_callback_cancel_navigation_task(self, connector, callback_kwargs):
        # Set up the robot to be available
        connector.robot_api._last_call_successful = True
        connector.status = {"online": True}

        # Configure the custom command for canceling navigation task
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
        callback_kwargs["args"] = ["cancel_navigation_task", []]

        # Call the handler
        await connector._inorbit_command_handler(**callback_kwargs)

        # Verify the result function was called with success code
        callback_kwargs["options"]["result_function"].assert_called_with("0")

        # Verify the robot API method was called
        connector.robot_api.cancel_navigation_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_execution_loop(
        self,
        connector,
        robot_info,
        current_position_data,
        device_status_data,
        robot_status_data_task,
    ):
        # Setup mock return values based on fixtures
        connector.robot_state.pose = {
            "x": current_position_data["worldPosition"]["position"]["x"],
            "y": current_position_data["worldPosition"]["position"]["y"],
            "yaw": current_position_data["angle"],
            "frame_id": "map",
        }
        connector.robot_state.key_values = {
            "battery_percentage": device_status_data["data"]["battery"],
            "model": robot_info["data"]["modelType"],
            "uptime": 1000,
            "robotStatus": robot_status_data_task["data"]["robotStatus"],
            "statusData": robot_status_data_task["data"]["statusData"],
        }

        # Mock the publish_pose method
        connector.publish_pose = MagicMock()

        # Test successful execution loop
        await connector._execution_loop()

        # Verify that the data was published
        connector.publish_pose.assert_called_once_with(**connector.robot_state.pose)
        connector._robot_session.publish_key_values.assert_called_once()
        connector.mission_tracking.mission_update.assert_called_once_with(
            connector.robot_state.key_values["robotStatus"],
            connector.robot_state.key_values["statusData"],
        )

    def test_is_robot_available(self, connector):
        # Test with robot available
        connector.robot_api._last_call_successful = True
        assert connector.is_robot_available() is True

        # Test with robot unavailable
        connector.robot_api._last_call_successful = False
        assert connector.is_robot_available() is False
