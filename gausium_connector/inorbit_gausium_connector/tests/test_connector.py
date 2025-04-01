# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import math
from unittest.mock import call
from unittest.mock import MagicMock
from unittest.mock import Mock
import logging

from inorbit_edge.commands import COMMAND_INITIAL_POSE
import pytest
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND
from inorbit_edge.robot import COMMAND_MESSAGE
from inorbit_edge.robot import COMMAND_NAV_GOAL
from inorbit_edge.robot import RobotSession
from inorbit_gausium_connector.src.config.connector_model import ConnectorConfig
from inorbit_gausium_connector.src.connector import GausiumConnector


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
        connector.robot_api = MagicMock()
        connector.mission_tracking = MagicMock()
        connector._robot_session = MagicMock()

        # Explicitly set the logger to our mock
        connector._logger = mock_logger

        return connector

    def test_publish_map(self, connector, monkeypatch):
        """Test the publish_map method in different scenarios."""
        # Mock the parent class's publish_map method
        super_publish_map = MagicMock()
        monkeypatch.setattr("inorbit_connector.connector.Connector.publish_map", super_publish_map)

        # Mock the MapConfig class to avoid file validation
        mock_map_config = MagicMock()
        monkeypatch.setattr("inorbit_gausium_connector.src.connector.MapConfig", mock_map_config)

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
        mock_map_data = MagicMock()
        mock_map_data.map_id = "robot_map"
        mock_map_data.map_name = "test_map_name"
        mock_map_data.map_image = b"fake_image_data"
        mock_map_data.origin_x = 10.5
        mock_map_data.origin_y = 20.7
        mock_map_data.resolution = 0.05
        connector.robot_api.current_map = mock_map_data

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
        connector.publish_map("new_map")

        # Verify temporary file was created and written to
        assert mock_fdopen.call_args.args[0] == mock_fd
        assert mock_fdopen.call_args.args[1] == "wb"
        mock_file.__enter__().write.assert_called_once_with(b"flipped_image_data")

        # Verify MapConfig was called with the correct parameters
        # Now using the actual property values from mock_map_data
        mock_map_config.assert_called_once_with(
            file=mock_temp_path,
            map_id="test_map_name",
            frame_id="new_map",
            origin_x=mock_map_data.origin_x,
            origin_y=mock_map_data.origin_y,
            resolution=mock_map_data.resolution,
        )

        # Verify parent method was called to publish the map
        super_publish_map.assert_called_once_with("new_map", False)
        super_publish_map.reset_mock()

        # Test case 3: Map doesn't exist and robot doesn't provide map data
        connector.robot_api.current_map = None
        connector.config.maps = {}  # Reset maps

        # Call the method
        connector.publish_map("nonexistent_map")

        # Verify parent method was not called since no map was available
        assert not super_publish_map.called

        # Test case 4: Error flipping the image
        connector.robot_api.current_map = mock_map_data
        monkeypatch.setattr("PIL.Image.open", Mock(side_effect=Exception("Failed to open image")))

        # Reset counters for this test case
        mock_map_config.reset_mock()
        mock_file.__enter__().write.reset_mock()

        # Call the method
        connector.publish_map("error_map")

        # Verify original bytes were used when flipping failed
        mock_file.__enter__().write.assert_called_once_with(b"fake_image_data")

    def test_connector_passes_ignore_model_type_validation(self, monkeypatch):
        """Test that ignore_model_type_validation parameter is passed to the robot API."""
        # Patch environment and robot session
        monkeypatch.setenv("INORBIT_KEY", "abc123")
        monkeypatch.setattr(RobotSession, "connect", MagicMock())

        # Mock the create_robot_api function
        mock_create_robot_api = MagicMock()
        monkeypatch.setattr(
            "inorbit_gausium_connector.src.connector.create_robot_api", mock_create_robot_api
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

        # Verify that create_robot_api was called with ignore_model_type_validation=True
        mock_create_robot_api.assert_called_once()
        call_kwargs = mock_create_robot_api.call_args.kwargs
        assert call_kwargs["ignore_model_type_validation"] is True

        # Reset the mock
        mock_create_robot_api.reset_mock()

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

        # Verify that create_robot_api was called with ignore_model_type_validation=False
        mock_create_robot_api.assert_called_once()
        call_kwargs = mock_create_robot_api.call_args.kwargs
        assert call_kwargs["ignore_model_type_validation"] is False

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

    def test_command_callback_unknown_commands(self, connector, callback_kwargs, monkeypatch):
        # Unknown command
        callback_kwargs["command_name"] = "unknown_command"
        connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with(
            "1", "'unknown_command' is not implemented"
        )

        # Unknown customCommand command
        callback_kwargs["options"]["result_function"].reset_mock()
        callback_kwargs["command_name"] = "customCommand"
        callback_kwargs["args"] = ["unknown_custom_command", ["arg1", "arg2"]]
        connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with(
            "1", "Custom command 'unknown_custom_command' is not implemented"
        )

        # Unknown message command
        callback_kwargs["options"]["result_function"].reset_mock()
        callback_kwargs["command_name"] = "message"
        callback_kwargs["args"] = ["unknown_message", ["arg1", "arg2"]]
        connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with(
            "1", "Message 'unknown_message' is not implemented"
        )

        # Script command
        callback_kwargs["options"]["result_function"].reset_mock()
        callback_kwargs["command_name"] = "customCommand"
        callback_kwargs["args"] = ["script.sh", ["arg1", "arg2"]]
        # The connector should let the edge-sdk handle this
        connector._inorbit_command_handler(**callback_kwargs)
        assert not callback_kwargs["options"]["result_function"].called

    def test_command_callback_nav_goal(self, connector, callback_kwargs):
        callback_kwargs["command_name"] = COMMAND_NAV_GOAL
        callback_kwargs["args"] = [{"x": "1", "y": "2", "theta": "3.14"}]
        connector._inorbit_command_handler(**callback_kwargs)
        assert connector.robot_api.send_waypoint.call_args_list == [call(1, 2, math.degrees(3.14))]
        callback_kwargs["options"]["result_function"].assert_called_with("0")

    def test_command_callback_initial_pose(self, connector, callback_kwargs):
        callback_kwargs["command_name"] = COMMAND_INITIAL_POSE
        callback_kwargs["args"] = [{"x": "1", "y": "2", "theta": "3.1415"}]
        connector.robot_api.pose = {"x": 0, "y": 0, "yaw": 0}
        connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with("0")
        assert connector.robot_api.localize_at.call_args_list[0].args[0] == 1
        assert connector.robot_api.localize_at.call_args_list[0].args[1] == 2
        assert abs(connector.robot_api.localize_at.call_args_list[0].args[2] - 180) < 0.1
        connector.robot_api.localize_at.reset_mock()
        callback_kwargs["args"] = [{"x": "1", "y": "2", "theta": "3.1415"}]
        connector.robot_api.pose = {"x": 1, "y": 2, "yaw": 3.1415}
        connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with("0")
        assert connector.robot_api.localize_at.call_args_list[0].args[0] == 2
        assert connector.robot_api.localize_at.call_args_list[0].args[1] == 4
        assert abs(connector.robot_api.localize_at.call_args_list[0].args[2]) < 0.1

    def test_command_callback_inorbit_messages(self, connector, callback_kwargs):
        callback_kwargs["command_name"] = COMMAND_MESSAGE
        # InOrbit pause message
        callback_kwargs["args"] = ["inorbit_pause"]
        connector._inorbit_command_handler(**callback_kwargs)
        connector.robot_api.pause.assert_called_once()
        callback_kwargs["options"]["result_function"].assert_called_with("0")

        # InOrbit resume message
        callback_kwargs["args"] = ["inorbit_resume"]
        connector._inorbit_command_handler(**callback_kwargs)
        connector.robot_api.resume.assert_called_once()
        callback_kwargs["options"]["result_function"].assert_called_with("0")

        # Unknown message
        callback_kwargs["args"] = ["unknown_message"]
        connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with(
            "1", "Message 'unknown_message' is not implemented"
        )

    def test_command_callback_custom_command(self, connector, callback_kwargs):
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND

        # Test with invalid arguments
        callback_kwargs["args"] = ["script_name", ["not_even_key_value_pairs"]]
        connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with("1", "Invalid arguments")

        # Test with robot unavailable
        connector.robot_api._last_call_successful = False
        connector.status = {"online": False}
        callback_kwargs["args"] = ["script_name", ["param1", "value1"]]
        connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with(
            "1", "Robot is not available"
        )

    def test_command_callback_start_task_queue(self, connector, callback_kwargs):
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
        callback_kwargs["args"] = [
            "start_task_queue",
            ["task_queue_name", "vacuum_zone_corridor_123"],
        ]
        connector._inorbit_command_handler(**callback_kwargs)
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
        connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with("0")
        connector.robot_api.start_task_queue.assert_called_once_with(
            "vacuum_zone_corridor_123",
            "test_map",
            True,
            3,
        )

    def test_command_callback_send_to_named_waypoint(self, connector, callback_kwargs):
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
        callback_kwargs["args"] = ["send_to_named_waypoint", ["position_name", "waypoint_1"]]
        connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with("0")
        connector.robot_api.send_to_named_waypoint.assert_called_once_with("waypoint_1", None)
        connector.robot_api.send_to_named_waypoint.reset_mock()

        # Test with map name
        callback_kwargs["args"] = [
            "send_to_named_waypoint",
            ["position_name", "waypoint_1", "map_name", "test_map"],
        ]
        connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with("0")
        connector.robot_api.send_to_named_waypoint.assert_called_once_with("waypoint_1", "test_map")

    def test_command_callback_pause_task_queue(self, connector, callback_kwargs):
        # Set up the robot to be available
        connector.robot_api._last_call_successful = True
        connector.status = {"online": True}

        # Configure the custom command for pausing cleaning task
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
        callback_kwargs["args"] = ["pause_task_queue", []]

        # Call the handler
        connector._inorbit_command_handler(**callback_kwargs)

        # Verify the result function was called with success code
        callback_kwargs["options"]["result_function"].assert_called_with("0")

        # Verify the robot API method was called
        connector.robot_api.pause_task_queue.assert_called_once()

    def test_command_callback_resume_task_queue(self, connector, callback_kwargs):
        # Set up the robot to be available
        connector.robot_api._last_call_successful = True
        connector.status = {"online": True}

        # Configure the custom command for resuming cleaning task
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
        callback_kwargs["args"] = ["resume_task_queue", []]

        # Call the handler
        connector._inorbit_command_handler(**callback_kwargs)

        # Verify the result function was called with success code
        callback_kwargs["options"]["result_function"].assert_called_with("0")

        # Verify the robot API method was called
        connector.robot_api.resume_task_queue.assert_called_once()

    def test_command_callback_cancel_task_queue(self, connector, callback_kwargs):
        # Set up the robot to be available
        connector.robot_api._last_call_successful = True
        connector.status = {"online": True}

        # Configure the custom command for canceling cleaning task
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
        callback_kwargs["args"] = ["cancel_task_queue", []]

        # Call the handler
        connector._inorbit_command_handler(**callback_kwargs)

        # Verify the result function was called with success code
        callback_kwargs["options"]["result_function"].assert_called_with("0")

        # Verify the robot API method was called
        connector.robot_api.cancel_task_queue.assert_called_once()

    def test_command_callback_pause_navigation_task(self, connector, callback_kwargs):
        # Set up the robot to be available
        connector.robot_api._last_call_successful = True
        connector.status = {"online": True}

        # Configure the custom command for pausing navigation task
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
        callback_kwargs["args"] = ["pause_navigation_task", []]

        # Call the handler
        connector._inorbit_command_handler(**callback_kwargs)

        # Verify the result function was called with success code
        callback_kwargs["options"]["result_function"].assert_called_with("0")

        # Verify the robot API method was called
        connector.robot_api.pause_navigation_task.assert_called_once()

    def test_command_callback_resume_navigation_task(self, connector, callback_kwargs):
        # Set up the robot to be available
        connector.robot_api._last_call_successful = True
        connector.status = {"online": True}

        # Configure the custom command for resuming navigation task
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
        callback_kwargs["args"] = ["resume_navigation_task", []]

        # Call the handler
        connector._inorbit_command_handler(**callback_kwargs)

        # Verify the result function was called with success code
        callback_kwargs["options"]["result_function"].assert_called_with("0")

        # Verify the robot API method was called
        connector.robot_api.resume_navigation_task.assert_called_once()

    def test_command_callback_cancel_navigation_task(self, connector, callback_kwargs):
        # Set up the robot to be available
        connector.robot_api._last_call_successful = True
        connector.status = {"online": True}

        # Configure the custom command for canceling navigation task
        callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
        callback_kwargs["args"] = ["cancel_navigation_task", []]

        # Call the handler
        connector._inorbit_command_handler(**callback_kwargs)

        # Verify the result function was called with success code
        callback_kwargs["options"]["result_function"].assert_called_with("0")

        # Verify the robot API method was called
        connector.robot_api.cancel_navigation_task.assert_called_once()

    def test_command_callback_robot_unavailable(self, connector, callback_kwargs):
        # Set up the robot to be unavailable
        connector.robot_api._last_call_successful = False
        connector.status = {"online": False}

        # Test each command with an unavailable robot
        commands = [
            "pause_task_queue",
            "resume_task_queue",
            "cancel_task_queue",
            "pause_navigation_task",
            "resume_navigation_task",
            "cancel_navigation_task",
        ]

        for command in commands:
            # Reset the result function mock
            callback_kwargs["options"]["result_function"].reset_mock()
            # Reset the robot API method mock
            method_name = command
            robot_api_method = getattr(connector.robot_api, method_name)
            robot_api_method.reset_mock()

            # Configure the custom command
            callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
            callback_kwargs["args"] = [command, []]

            # Call the handler
            connector._inorbit_command_handler(**callback_kwargs)

            # Verify the result function was called with error code
            callback_kwargs["options"]["result_function"].assert_called_with(
                "1", "Robot is not available"
            )

            # Verify the robot API method was NOT called
            assert (
                not robot_api_method.called
            ), f"Robot API method {method_name} was called when robot was unavailable"

    def test_execution_loop(
        self,
        connector,
        robot_info,
        current_position_data,
        device_status_data,
        robot_status_data_task,
    ):
        # Setup mock return values based on fixtures
        connector.robot_api.pose = {
            "x": current_position_data["worldPosition"]["position"]["x"],
            "y": current_position_data["worldPosition"]["position"]["y"],
            "yaw": current_position_data["angle"],
            "frame_id": "map",
        }
        connector.robot_api.odometry = {"vx": 0.1, "vy": 0.2, "vtheta": 0.3}
        connector.robot_api.key_values = {
            "battery_percentage": device_status_data["data"]["battery"],
            "model": robot_info["data"]["modelType"],
            "uptime": 1000,
            "robotStatus": robot_status_data_task["data"]["robotStatus"],
            "statusData": robot_status_data_task["data"]["statusData"],
        }

        # Mock the publish_pose method
        connector.publish_pose = MagicMock()

        # Test successful execution loop
        connector._execution_loop()

        # Verify that the robot API was updated
        connector.robot_api.update.assert_called_once()

        # Verify that the data was published
        connector.publish_pose.assert_called_once_with(**connector.robot_api.pose)
        connector._robot_session.publish_odometry.assert_called_once_with(
            **connector.robot_api.odometry
        )
        connector._robot_session.publish_key_values.assert_called_once()
        connector.mission_tracking.mission_update.assert_called_once_with(
            connector.robot_api.key_values["robotStatus"],
            connector.robot_api.key_values["statusData"],
        )

        # Test execution loop with exception
        connector.robot_api.update.reset_mock()
        connector.robot_api.update.side_effect = Exception("Test exception")

        connector._execution_loop()

        # Verify that the robot API was updated but no data was published
        connector.robot_api.update.assert_called_once()
        assert connector.publish_pose.call_count == 1  # Still just the one call from before
        assert (
            connector._robot_session.publish_odometry.call_count == 1
        )  # Still just the one call from before
        connector._robot_session.publish_key_values.assert_called_with(
            {
                "robot_available": False,
                "connector_last_error": "Test exception",
            }
        )

    def test_is_robot_available(self, connector):
        # Test with robot available
        connector.robot_api._last_call_successful = True
        connector.status = {"online": True}
        assert connector.is_robot_available() is True

        # Test with robot unavailable
        connector.robot_api._last_call_successful = False
        connector.status = {"online": False}
        assert connector.is_robot_available() is False

        # Test with robot status unknown but last call successful
        connector.robot_api._last_call_successful = True
        connector.status = {}
        assert connector.is_robot_available() is True
