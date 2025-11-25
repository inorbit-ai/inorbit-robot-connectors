# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import tempfile
from unittest.mock import AsyncMock
from unittest.mock import call
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from inorbit_connector.connector import CommandResultCode
from inorbit_connector.models import MapConfig
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND
from inorbit_edge.robot import COMMAND_MESSAGE
from inorbit_edge.robot import COMMAND_NAV_GOAL
from inorbit_edge.robot import RobotSession
from inorbit_gausium_connector.config.connector_model import ConnectorConfig
from inorbit_gausium_connector.src.connector import CustomCommands
from inorbit_gausium_connector.src.connector import PhantasConnector
from inorbit_gausium_connector.src.robot import RobotAPI


@pytest.fixture
def connector(monkeypatch):
    monkeypatch.setenv("INORBIT_API_KEY", "abc123")
    monkeypatch.setattr(RobotAPI, "init_session", AsyncMock())
    monkeypatch.setattr(RobotSession, "connect", MagicMock())

    # Create a temporary directory for user_scripts_dir
    temp_dir = tempfile.mkdtemp()

    connector = PhantasConnector(
        "hoolibot3000-1",
        ConnectorConfig(
            inorbit_robot_key="robot_key",
            location_tz="UTC",
            logging={"log_level": "INFO"},
            connector_type="Gausium Phantas S",
            connector_version="0.1.0",
            connector_config={
                "base_url": "https://hoolibot.local",
                "serial_number": "GS000-0000-000-0000",
                "client_id": "inorbit",
                "client_secret": "orbito",
                "access_key_secret": "otibro",
            },
            user_scripts_dir=temp_dir,
        ),
    )

    # Mock the robot API with async methods
    connector.robot_api = MagicMock()
    connector.robot_api.send_waypoint = AsyncMock()
    connector.robot_api.create_remote_task_command = AsyncMock()
    connector.robot_api.create_nosite_task = AsyncMock()
    connector.robot_api.create_remote_navigation_command = AsyncMock()

    # Mock the robot abstraction
    mock_robot = MagicMock()
    mock_robot.status = {"online": True}  # Robot is available
    mock_robot.api_connected = True
    connector.robot = mock_robot

    connector._robot_session = MagicMock()

    yield connector

    # Cleanup the temporary directory
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def callback_kwargs():
    return {
        "command_name": "cmd_name",
        "args": [],
        "options": {
            "result_function": Mock(),
            "progress_funtion": Mock(),
            "metadata": {},
        },
    }


@pytest.mark.asyncio
async def test_command_callback_unknown_command(connector: PhantasConnector, callback_kwargs):
    callback_kwargs["command_name"] = "unknown"
    await connector._inorbit_command_handler(**callback_kwargs)
    assert not callback_kwargs["options"]["result_function"].called
    callback_kwargs["command_name"] = "customCommand"
    callback_kwargs["args"] = ["unknown_command", ["arg1", "arg2"]]
    await connector._inorbit_command_handler(**callback_kwargs)
    assert not callback_kwargs["options"]["result_function"].called


@pytest.mark.asyncio
async def test_command_callback_nav_goal(connector: PhantasConnector, callback_kwargs):
    callback_kwargs["command_name"] = COMMAND_NAV_GOAL
    callback_kwargs["args"] = [{"x": "1", "y": "2", "theta": "3.14"}]
    await connector._inorbit_command_handler(**callback_kwargs)
    assert connector.robot_api.send_waypoint.call_args_list == [
        call({"x": "1", "y": "2", "theta": "3.14"})
    ]


@pytest.mark.asyncio
async def test_command_callback_inorbit_messages(connector: PhantasConnector, callback_kwargs):
    callback_kwargs["command_name"] = COMMAND_MESSAGE
    for message in ["inorbit_pause", "inorbit_resume"]:
        callback_kwargs["args"] = [message]
        await connector._inorbit_command_handler(**callback_kwargs)
        # Not implemented yet
        callback_kwargs["options"]["result_function"].assert_called_with(
            CommandResultCode.FAILURE, "'message' is not implemented"
        )


@pytest.mark.asyncio
async def test_command_callback_task_commands(connector: PhantasConnector, callback_kwargs):
    from inorbit_gausium_connector.src.robot import RemoteTaskCommandType

    print(CustomCommands.TASK_COMMAND)
    assert CustomCommands.TASK_COMMAND == "task_command"
    callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND
    # Test allowed task commands
    for command in [
        "PAUSE_TASK",
        "RESUME_TASK",
        "STOP_TASK",
    ]:
        callback_kwargs["args"] = [CustomCommands.TASK_COMMAND.value, ["command", command]]
        await connector._inorbit_command_handler(**callback_kwargs)
        # The connector should call with the enum value, not the string
        expected_enum = RemoteTaskCommandType[command]
        connector.robot_api.create_remote_task_command.assert_called_with(expected_enum)
        callback_kwargs["options"]["result_function"].assert_called_with(CommandResultCode.SUCCESS)
    # Unallowed task commands
    # Start task should be handled by submit_task
    connector.robot_api.reset_mock()
    for command in ["START_TASK", "unknown"]:
        callback_kwargs["args"] = [CustomCommands.TASK_COMMAND.value, ["command", command]]
        await connector._inorbit_command_handler(**callback_kwargs)
        connector.robot_api.create_remote_task_command.assert_not_called()
        callback_kwargs["options"]["result_function"].assert_called_with(
            CommandResultCode.FAILURE, f"Invalid command {command}"
        )


def test_publish_map_existing_config(connector: PhantasConnector):
    """Test publish_map when map is already in config."""
    # Add a map to the config
    frame_id = "existing_map"

    # Create a temporary file for the map
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
        temp_file.write(b"fake_map_data")
        temp_file_path = temp_file.name

    try:
        connector.config.maps[frame_id] = MapConfig(
            file=temp_file_path,
            map_id="map123",
            origin_x=0.0,
            origin_y=0.0,
            resolution=0.05,
        )

        # Mock the parent publish_map method
        with patch("inorbit_connector.connector.Connector.publish_map") as mock_parent_publish:
            connector.publish_map(frame_id)

            # Should call parent method directly
            mock_parent_publish.assert_called_once_with(frame_id, False)
    finally:
        # Clean up the temporary file
        import os

        try:
            os.unlink(temp_file_path)
        except FileNotFoundError:
            pass


def test_publish_map_fetch_from_robot(connector: PhantasConnector):
    """Test publish_map when map needs to be fetched from robot."""
    frame_id = "f0043258-d2dd-423c-a9f0-e12a1f26f761"

    # Mock robot status with map information
    connector.robot.status_v2 = {
        "localizationInfo": {
            "map": {"id": frame_id, "name": "test_map", "version": "version123"},
            "mapPosition": {"x": 100, "y": 200, "angle": 90},
        }
    }

    # Mock the get_map_image_sync method
    fake_image_data = b"fake_png_image_data"
    connector.robot_api.get_map_image_sync = MagicMock(return_value=fake_image_data)

    # Mock PIL Image operations
    with (
        patch("PIL.Image.open") as mock_image_open,
        patch("inorbit_connector.connector.Connector.publish_map") as mock_parent_publish,
    ):

        # Setup mocks for image processing
        mock_image = MagicMock()
        mock_flipped_image = MagicMock()
        mock_image.transpose.return_value = mock_flipped_image
        mock_image_open.return_value = mock_image

        mock_byte_array = MagicMock()
        mock_byte_array.getvalue.return_value = b"flipped_image_data"
        mock_flipped_image.save = MagicMock()

        # Create a real temporary file for the test
        temp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        temp_path = temp_file.name
        temp_file.close()

        try:
            # Call the method
            connector.publish_map(frame_id)

            # Verify robot API was called
            connector.robot_api.get_map_image_sync.assert_called_once_with(
                frame_id, "test_map", "version123"
            )

            # Verify image processing
            mock_image_open.assert_called_once()
            mock_image.transpose.assert_called_once()
            mock_flipped_image.save.assert_called_once()

            # Verify map was added to config
            assert frame_id in connector.config.maps
            map_config = connector.config.maps[frame_id]
            assert map_config.map_id == frame_id
            assert map_config.resolution == 0.05

            # Verify parent publish_map was called
            mock_parent_publish.assert_called_once_with(frame_id, False)

        finally:
            # Clean up the temporary file
            import os

            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass


@pytest.mark.asyncio
async def test_connector_with_none_user_scripts_dir(monkeypatch):
    """Test that the connector can be instantiated with None user_scripts_dir."""
    monkeypatch.setenv("INORBIT_API_KEY", "abc123")
    monkeypatch.setattr(RobotAPI, "init_session", MagicMock())
    monkeypatch.setattr(RobotSession, "connect", MagicMock())

    # This should not raise an exception
    connector = PhantasConnector(
        "hoolibot3000-1",
        ConnectorConfig(
            inorbit_robot_key="robot_key",
            location_tz="UTC",
            logging={"log_level": "INFO"},
            connector_type="Gausium Phantas S",
            connector_version="0.1.0",
            connector_config={
                "base_url": "https://hoolibot.local",
                "serial_number": "GS000-0000-000-0000",
                "client_id": "inorbit",
                "client_secret": "orbito",
                "access_key_secret": "otibro",
            },
            user_scripts_dir=None,  # This should work without errors
        ),
    )
    assert connector is not None
    assert connector.robot_api is not None
