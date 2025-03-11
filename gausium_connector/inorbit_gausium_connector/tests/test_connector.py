from unittest.mock import call
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND
from inorbit_edge.robot import COMMAND_MESSAGE
from inorbit_edge.robot import COMMAND_NAV_GOAL
from inorbit_edge.robot import RobotSession
from inorbit_gausium_connector.src.config.connector_model import ConnectorConfig
from inorbit_gausium_connector.src.connector import GausiumConnector


@pytest.fixture
def connector(monkeypatch):
    monkeypatch.setenv("INORBIT_KEY", "abc123")
    monkeypatch.setattr(RobotSession, "connect", MagicMock())

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
    connector.robot_api = MagicMock()
    connector._robot_session = MagicMock()
    return connector


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


def test_command_callback_unknown_command(connector: GausiumConnector, callback_kwargs):
    callback_kwargs["command_name"] = "unknown"
    connector._inorbit_command_handler(**callback_kwargs)
    assert not callback_kwargs["options"]["result_function"].called
    callback_kwargs["command_name"] = "customCommand"
    callback_kwargs["args"] = ["unknown_command", ["arg1", "arg2"]]
    connector._inorbit_command_handler(**callback_kwargs)
    callback_kwargs["options"]["result_function"].assert_called_with("0")


def test_command_callback_nav_goal(connector: GausiumConnector, callback_kwargs):
    callback_kwargs["command_name"] = COMMAND_NAV_GOAL
    callback_kwargs["args"] = [{"x": "1", "y": "2", "theta": "3.14"}]
    connector._inorbit_command_handler(**callback_kwargs)
    assert connector.robot_api.send_waypoint.call_args_list == [
        call({"x": "1", "y": "2", "theta": "3.14"})
    ]


@pytest.mark.skip(reason="Custom commands not yet implemented")
def test_command_callback_inorbit_messages(connector: GausiumConnector, callback_kwargs):
    callback_kwargs["command_name"] = COMMAND_MESSAGE
    for message in ["inorbit_pause", "inorbit_resume"]:
        callback_kwargs["args"] = [message]
        connector._inorbit_command_handler(**callback_kwargs)
        # Not implemented yet
        callback_kwargs["options"]["result_function"].assert_called_with(
            "1", f"'{COMMAND_MESSAGE}' is not implemented"
        )


def test_command_callback_custom_command(connector: GausiumConnector, callback_kwargs):
    callback_kwargs["command_name"] = COMMAND_CUSTOM_COMMAND

    # Test with valid arguments
    callback_kwargs["args"] = ["script_name", ["param1", "value1", "param2", "value2"]]
    connector._inorbit_command_handler(**callback_kwargs)
    callback_kwargs["options"]["result_function"].assert_called_with("0")

    # Test with invalid arguments
    callback_kwargs["args"] = ["script_name", ["not_even_key_value_pairs"]]
    connector._inorbit_command_handler(**callback_kwargs)
    callback_kwargs["options"]["result_function"].assert_called_with("1", "Invalid arguments")

    # Test with robot unavailable
    connector.robot_api._last_call_successful = False
    connector.status = {"online": False}
    callback_kwargs["args"] = ["script_name", ["param1", "value1"]]
    connector._inorbit_command_handler(**callback_kwargs)
    callback_kwargs["options"]["result_function"].assert_called_with("1", "Robot is not available")


def test_execution_loop(
    connector: GausiumConnector, firmware_version_info, current_position_data, device_status_data
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
        "model": firmware_version_info["data"]["modelType"],
        "uptime": 1000,
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
    assert (
        connector._robot_session.publish_key_values.call_count == 1
    )  # Still just the one call from before


def test_is_robot_available(connector: GausiumConnector):
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
