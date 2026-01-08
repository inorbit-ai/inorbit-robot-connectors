# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import math
import pytest
import uuid
from unittest.mock import MagicMock, Mock, call, AsyncMock
from inorbit_edge.robot import RobotSession
from inorbit_mir_connector.src.connector import MirConnector
from inorbit_mir_connector.config.connector_model import ConnectorConfig
from .. import get_module_version
from inorbit_connector.connector import CommandResultCode


@pytest.fixture
def connector(monkeypatch, tmp_path):
    monkeypatch.setenv("INORBIT_KEY", "abc123")
    monkeypatch.setattr(RobotSession, "connect", MagicMock())

    connector = MirConnector(
        "mir100-1",
        ConnectorConfig(
            inorbit_robot_key="robot_key",
            location_tz="UTC",
            logging={"log_level": "INFO"},
            connector_type="MiR100",
            connector_version="0.1.0",
            connector_config={
                "mir_host_address": "example.com",
                "mir_host_port": 80,
                "mir_use_ssl": False,
                "mir_username": "user",
                "mir_password": "pass",
                "mir_api_version": "v2.0",
                "mir_firmware_version": "v2",
                "enable_temporary_mission_group": True,
            },
            user_scripts_dir=tmp_path,
        ),
    )
    connector.mir_api = MagicMock()
    # Async API methods
    connector.mir_api.get_status = AsyncMock()
    connector.mir_api.get_metrics = AsyncMock()
    connector.mir_api.queue_mission = AsyncMock()
    connector.mir_api.abort_all_missions = AsyncMock()
    connector.mir_api.set_state = AsyncMock()
    connector.mir_api.clear_error = AsyncMock()
    connector.mir_api.set_status = AsyncMock()
    connector.mir_api.create_mission = AsyncMock()
    connector.mir_api.add_action_to_mission = AsyncMock()
    connector.mir_api.get_mission_group_missions = AsyncMock()
    connector.mir_api.get_missions_queue = AsyncMock()
    connector.mir_api.get_mission = AsyncMock()
    connector.mir_api.delete_mission_definition = AsyncMock()
    connector.mir_api.get_mission_groups = AsyncMock(return_value=[])
    connector.mir_api.create_mission_group = AsyncMock()
    connector._robot_session = MagicMock()
    return connector


@pytest.fixture
def connector_with_mission_tracking(monkeypatch, tmp_path):
    """Connector fixture with mission tracking enabled for tests that need it."""
    monkeypatch.setenv("INORBIT_KEY", "abc123")
    monkeypatch.setattr(RobotSession, "connect", MagicMock())

    connector = MirConnector(
        "mir100-1",
        ConnectorConfig(
            inorbit_robot_key="robot_key",
            location_tz="UTC",
            logging={"log_level": "INFO"},
            connector_type="MiR100",
            connector_version="0.1.0",
            connector_config={
                "mir_host_address": "example.com",
                "mir_host_port": 80,
                "mir_use_ssl": False,
                "mir_username": "user",
                "mir_password": "pass",
                "mir_api_version": "v2.0",
                "mir_firmware_version": "v2",
            },
            user_scripts_dir=tmp_path,
        ),
    )
    connector.mir_api = MagicMock()
    # Async API methods
    connector.mir_api.get_status = AsyncMock()
    connector.mir_api.get_metrics = AsyncMock()
    connector.mir_api.queue_mission = AsyncMock()
    connector.mir_api.abort_all_missions = AsyncMock()
    connector.mir_api.set_state = AsyncMock()
    connector.mir_api.clear_error = AsyncMock()
    connector.mir_api.set_status = AsyncMock()
    connector.mir_api.create_mission = AsyncMock()
    connector.mir_api.add_action_to_mission = AsyncMock()
    connector.mir_api.get_mission_group_missions = AsyncMock()
    connector.mir_api.get_missions_queue = AsyncMock()
    connector.mir_api.get_mission = AsyncMock()
    connector.mir_api.delete_mission_definition = AsyncMock()
    connector.mir_api.get_mission_groups = AsyncMock(return_value=[])
    connector.mir_api.create_mission_group = AsyncMock()
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


@pytest.mark.asyncio
async def test_command_callback_unknown_command(connector, callback_kwargs):
    callback_kwargs["command_name"] = "unknown"
    await connector._inorbit_command_handler(**callback_kwargs)
    assert not callback_kwargs["options"]["result_function"].called
    callback_kwargs["command_name"] = "customCommand"
    callback_kwargs["args"] = ["unknown_command", ["arg1", "arg2"]]
    await connector._inorbit_command_handler(**callback_kwargs)
    assert not callback_kwargs["options"]["result_function"].called


@pytest.mark.asyncio
async def test_command_callback_missions(
    connector_with_mission_tracking, callback_kwargs
):
    connector = connector_with_mission_tracking

    def reset_mock():
        callback_kwargs["options"]["result_function"].reset_mock()
        connector.mir_api.reset_mock()

    # Simulate an executor timeout, which should disable robot mission tracking
    connector._get_session().missions_module.executor.wait_until_idle = Mock(
        return_value=False
    )
    # Initial state is True, will be updated when command is executed
    assert connector.mission_tracking.mir_mission_tracking_enabled is True
    callback_kwargs["command_name"] = "customCommand"
    callback_kwargs["args"] = ["queue_mission", ["--mission_id", "1"]]
    await connector._inorbit_command_handler(**callback_kwargs)
    assert connector.mission_tracking.mir_mission_tracking_enabled is False
    assert connector.mir_api.queue_mission.call_args == call("1")
    callback_kwargs["options"]["result_function"].assert_called_with(
        CommandResultCode.SUCCESS
    )
    reset_mock()

    # Queue mission
    connector._get_session().missions_module.executor.wait_until_idle = Mock(
        return_value=True
    )
    callback_kwargs["command_name"] = "customCommand"
    callback_kwargs["args"] = ["queue_mission", ["--mission_id", "2"]]
    await connector._inorbit_command_handler(**callback_kwargs)
    assert connector.mission_tracking.mir_mission_tracking_enabled is True
    assert connector.mir_api.queue_mission.call_args == call("2")
    callback_kwargs["options"]["result_function"].assert_called_with(
        CommandResultCode.SUCCESS
    )
    reset_mock()

    # Run mission now
    callback_kwargs["command_name"] = "customCommand"
    callback_kwargs["args"] = ["run_mission_now", ["--mission_id", "3"]]
    await connector._inorbit_command_handler(**callback_kwargs)
    assert connector.mir_api.abort_all_missions.call_args == call()
    assert connector.mir_api.queue_mission.call_args == call("3")
    callback_kwargs["options"]["result_function"].assert_called_with(
        CommandResultCode.SUCCESS
    )
    reset_mock()

    # Abort all
    callback_kwargs["command_name"] = "customCommand"
    callback_kwargs["args"] = ["abort_missions", []]
    await connector._inorbit_command_handler(**callback_kwargs)
    assert (
        connector._get_session().missions_module.executor.cancel_mission.call_args
        == call("*")
    )
    assert connector.mir_api.abort_all_missions.call_args == call()
    callback_kwargs["options"]["result_function"].assert_called_with(
        CommandResultCode.SUCCESS
    )
    reset_mock()


@pytest.mark.asyncio
async def test_command_callback_state(connector, callback_kwargs):
    MIR_STATE = {3: "READY", 4: "PAUSE", 11: "MANUALCONTROL"}

    callback_kwargs["command_name"] = "customCommand"
    for id, state in MIR_STATE.items():
        callback_kwargs["args"] = ["set_state", ["--state_id", str(id)]]
        await connector._inorbit_command_handler(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with(
            CommandResultCode.SUCCESS
        )
        connector.mir_api.set_state.assert_called_with(id)
        connector.mir_api.set_state.reset_mock()
        callback_kwargs["options"]["result_function"].reset_mock()

    callback_kwargs["args"] = ["set_state", ["--state_id", "123"]]
    await connector._inorbit_command_handler(**callback_kwargs)
    callback_kwargs["options"]["result_function"].assert_called_with(
        CommandResultCode.FAILURE, execution_status_details="Invalid `state_id` '123'"
    )
    assert not connector.mir_api.set_state.called

    callback_kwargs["args"] = ["set_state", ["--state_id", "abc"]]
    await connector._inorbit_command_handler(**callback_kwargs)
    callback_kwargs["options"]["result_function"].assert_called_with(
        CommandResultCode.FAILURE, execution_status_details="Invalid `state_id` 'abc'"
    )
    assert not connector.mir_api.set_state.called


@pytest.mark.asyncio
async def test_command_callback_nav_goal(connector, callback_kwargs):
    callback_kwargs["command_name"] = "navGoal"
    callback_kwargs["args"] = [{"x": "1", "y": "2", "theta": "3.14"}]
    connector.send_waypoint_over_missions = AsyncMock()
    await connector._inorbit_command_handler(**callback_kwargs)
    connector.send_waypoint_over_missions.assert_called_with(
        {"x": "1", "y": "2", "theta": "3.14"}
    )


@pytest.mark.asyncio
async def test_send_waypoint_over_missions(connector, monkeypatch):
    monkeypatch.setattr(uuid, "uuid4", Mock(return_value="uuid"))
    # Test MiR100 firmware v2
    connector.config.connector_type = "MiR100"
    connector.config.connector_config.mir_firmware_version = "v2"

    # Mock the mission group to have an ID so the method doesn't fail
    connector.mission_group = MagicMock()
    connector.mission_group.missions_group_id = "test_group_id"

    await connector.send_waypoint_over_missions({"x": "1", "y": "2", "theta": "0"})
    connector.mir_api.create_mission.assert_called_once()
    connector.mir_api.add_action_to_mission.assert_called_once_with(
        action_type="move_to_position",
        mission_id="uuid",
        parameters=[
            {"value": 1.0, "input_name": None, "guid": "uuid", "id": "x"},
            {"value": 2.0, "input_name": None, "guid": "uuid", "id": "y"},
            {"value": 0, "input_name": None, "guid": "uuid", "id": "orientation"},
            {
                "value": 0.1,
                "input_name": None,
                "guid": "uuid",
                "id": "distance_threshold",
            },
            {"value": 5, "input_name": None, "guid": "uuid", "id": "retries"},
        ],
        priority=1,
    )
    connector.mir_api.queue_mission.assert_called_once_with("uuid")
    connector.mir_api.reset_mock()
    # Test MiR100 firmware v3
    connector.config.connector_type = "MiR250"
    connector.config.connector_config.mir_firmware_version = "v3"
    await connector.send_waypoint_over_missions({"x": "1", "y": "2", "theta": "0"})
    connector.mir_api.create_mission.assert_called_once()
    connector.mir_api.add_action_to_mission.assert_called_once_with(
        action_type="move_to_position",
        mission_id="uuid",
        parameters=[
            {"value": 1.0, "input_name": None, "guid": "uuid", "id": "x"},
            {"value": 2.0, "input_name": None, "guid": "uuid", "id": "y"},
            {"value": 0, "input_name": None, "guid": "uuid", "id": "orientation"},
            {
                "value": 0.1,
                "input_name": None,
                "guid": "uuid",
                "id": "distance_threshold",
            },
            {
                "value": 60.0,
                "input_name": None,
                "guid": "uuid",
                "id": "blocked_path_timeout",
            },
        ],
        priority=1,
    )
    connector.mir_api.queue_mission.assert_called_once_with("uuid")


@pytest.mark.asyncio
async def test_command_callback_inorbit_messages(connector, callback_kwargs):
    callback_kwargs["command_name"] = "message"
    for message, code in {"inorbit_pause": 4, "inorbit_resume": 3}.items():
        callback_kwargs["args"] = [message]
        await connector._inorbit_command_handler(**callback_kwargs)
        assert connector.mir_api.set_state.call_args == call(code)


@pytest.mark.asyncio
async def test_command_callback_change_map(connector, callback_kwargs):
    callback_kwargs["command_name"] = "customCommand"
    # test invalid args
    callback_kwargs["args"] = ["localize", ["--map_id", "map_id"]]
    await connector._inorbit_command_handler(**callback_kwargs)
    connector.mir_api.change_map.assert_not_called()
    callback_kwargs["options"]["result_function"].assert_called_with(
        CommandResultCode.FAILURE, execution_status_details="Invalid arguments"
    )
    # test valid args
    callback_kwargs["args"] = [
        "localize",
        [
            "--x",
            1.0,
            "--y",
            2.0,
            "--orientation",
            90.0,
            "--map_id",
            "map_id",
        ],
    ]
    await connector._inorbit_command_handler(**callback_kwargs)
    connector.mir_api.set_status.assert_called_with(
        {
            "position": {
                "x": 1.0,
                "y": 2.0,
                "orientation": 90.0,
            },
            "map_id": "map_id",
        }
    )


@pytest.mark.asyncio
async def test_connector_loop(connector_with_mission_tracking, monkeypatch):
    connector = connector_with_mission_tracking
    connector.mission_tracking.report_mission = AsyncMock()

    status_data = {
        "joystick_low_speed_mode_enabled": False,
        "mission_queue_url": "/v2.0.0/mission_queue/14026",
        "mode_id": 7,
        "moved": 671648.3914381799,
        "mission_queue_id": 14026,
        "robot_name": "Miriam",
        "joystick_web_session_id": "",
        "uptime": 3552693,
        "errors": [],
        "unloaded_map_changes": False,
        "distance_to_next_target": 0.1987656205892563,
        "serial_number": "200100005001715",
        "mode_key_state": "idle",
        "battery_percentage": 93.5,
        "map_id": "20f762ff-5e0a-11ee-abc8-0001299981c4",
        "safety_system_muted": False,
        "mission_text": "Charging until battery reaches 95% (Current: 94%)...",
        "state_text": "Executing",
        "velocity": {"linear": 1.1, "angular": 180},
        "footprint": "[[-0.454,0.32],[0.506,0.32],[0.506,-0.32],[-0.454,-0.32]]",
        "user_prompt": None,
        "allowed_methods": None,
        "robot_model": "MiR100",
        "mode_text": "Mission",
        "session_id": "85e7b6a1-61bb-11ed-9f1f-0001299981c4",
        "state_id": 5,
        "battery_time_remaining": 89725,
        "position": {
            "y": 7.156267166137695,
            "x": 9.52050495147705,
            "orientation": 104.30510711669922,
        },
    }

    # Mock the robot status and metrics directly
    connector.robot._status = status_data
    connector.mir_api.get_status.return_value = status_data

    # Mock publish_map to avoid map loading during the test
    connector.publish_map = MagicMock()

    metrics_data = {
        "mir_robot_localization_score": 0.027316320645337056,
        "mir_robot_position_x_meters": 9.52050495147705,
        "mir_robot_position_y_meters": 7.156267166137695,
        "mir_robot_orientation_degrees": 104.30510711669922,
        "mir_robot_info": 1.0,
        "mir_robot_distance_moved_meters_total": 671648.3914381799,
        "mir_robot_errors": 0.0,
        "mir_robot_state_id": 5.0,
        "mir_robot_uptime_seconds": 3552693.0,
        "mir_robot_battery_percent": 93.5,
        "mir_robot_battery_time_remaining_seconds": 89725.0,
        "mir_robot_wifi_access_point_rssi_dbm": -46.0,
        "mir_robot_wifi_access_point_info": 1.0,
        "mir_robot_wifi_access_point_frequency_hertz": 0.0,
    }

    # Mock the robot metrics directly
    connector.robot._metrics = metrics_data
    connector.mir_api.get_metrics.return_value = metrics_data

    # Mock diagnostics to include battery information
    connector.robot._diagnostics = {
        "/Power System/Battery": {
            "values": {
                "Remaining battery capacity [%]": 93.5,
                "Remaining battery time [sec]": 89725,
            }
        }
    }

    await connector._execution_loop()

    mock_session = connector._get_session()
    assert mock_session.publish_pose.call_args == call(
        9.52050495147705,
        7.156267166137695,
        1.8204675458317707,
        "20f762ff-5e0a-11ee-abc8-0001299981c4",
    )
    assert mock_session.publish_odometry.call_args == call(
        linear_speed=1.1, angular_speed=math.pi
    )
    assert mock_session.publish_key_values.call_args == call(
        {
            "connector_version": get_module_version(),
            "robot_name": "Miriam",
            "errors": [],
            "distance_to_next_target": 0.1987656205892563,
            "mission_text": "Charging until battery reaches 95% (Current: 94%)...",
            "state_text": "Executing",
            "mode_text": "Mission",
            "robot_model": "MiR100",
            "waiting_for": "",
            "api_connected": True,
            "localization_score": 0.027316320645337056,
            "uptime": 3552693,
            "battery percent": 0.935,  # Converted by to_inorbit_percent (93.5 / 100)
            "battery_time_remaining": 89725,
        }
    )
    # System stats not published when diagnostics don't include CPU/memory/disk data
    assert not mock_session.publish_system_stats.called

    # Test error handling - clear robot status to simulate failure
    connector.robot._status = {}  # Empty status should cause early return
    connector.status = None  # Clear connector's cached status too
    mock_session.reset_mock()
    await connector._execution_loop()
    assert not mock_session.publish_pose.called
    assert not mock_session.publish_odometry.called
    assert not mock_session.publish_key_values.called


@pytest.mark.asyncio
async def test_connector_loop_publishes_system_stats(
    connector_with_mission_tracking, monkeypatch
):
    """Test that system stats (CPU, RAM, disk) are published separately from key values."""
    connector = connector_with_mission_tracking
    connector.mission_tracking.report_mission = AsyncMock()

    status_data = {
        "robot_name": "Miriam",
        "uptime": 3552693,
        "errors": [],
        "distance_to_next_target": 0.1,
        "mission_text": "Idle",
        "state_text": "Ready",
        "mode_text": "Manual",
        "robot_model": "MiR100",
        "map_id": "test-map-id",
        "position": {"x": 1.0, "y": 2.0, "orientation": 90.0},
        "velocity": {"linear": 0.0, "angular": 0.0},
    }

    connector.robot._status = status_data
    connector.mir_api.get_status.return_value = status_data
    connector.publish_map = MagicMock()

    # Mock diagnostics with CPU, memory, and disk data
    connector.robot._diagnostics = {
        "/Power System/Battery": {
            "values": {
                "Remaining battery capacity [%]": 85.0,
                "Remaining battery time [sec]": 7200,
            }
        },
        "/Computer/PC/CPU Load": {
            "values": {
                "Average CPU load [%]": 45.0,
            }
        },
        "/Computer/PC/Memory": {
            "values": {
                "Used": 4000,
                "Total": 8000,
            }
        },
        "/Computer/PC/Harddrive": {
            "values": {
                "Used": 50000,
                "Total": 100000,
            }
        },
    }

    connector.robot._metrics = {"mir_robot_localization_score": 0.5}
    connector.mir_api.get_metrics.return_value = connector.robot._metrics

    await connector._execution_loop()

    mock_session = connector._get_session()

    # Verify system stats are published with correct values
    assert mock_session.publish_system_stats.called
    system_stats_call = mock_session.publish_system_stats.call_args
    assert system_stats_call == call(
        cpu_load_percentage=0.45,  # 45% / 100
        ram_usage_percentage=0.5,  # 4000 / 8000
        hdd_usage_percentage=0.5,  # 50000 / 100000
    )

    # Verify key values do NOT contain system stats
    key_values_call = mock_session.publish_key_values.call_args[0][0]
    assert "cpu_usage_percent" not in key_values_call
    assert "memory_usage_percent" not in key_values_call
    assert "disk_usage_percent" not in key_values_call

    # Verify battery is still in key values (robot-specific, not system stat)
    assert key_values_call["battery percent"] == 0.85
    assert key_values_call["battery_time_remaining"] == 7200


@pytest.mark.asyncio
async def test_missions_garbage_collector(connector):
    # Missions in the temporary group
    connector.tmp_missions_group_id = "tmp_group_id"
    connector.mir_api.get_mission_group_missions.return_value = [
        {
            "url": "/v2.0.0/missions/72003359-6445-419c-85fb-df5576a9ce2e",
            "guid": "72003359-6445-419c-85fb-df5576a9ce2e",
            "name": "Move to waypoint",
        },
        {
            "url": "/v2.0.0/missions/c0a17f65-39f1-4b10-8fee-77dfe1470ac1",
            "guid": "c0a17f65-39f1-4b10-8fee-77dfe1470ac1",
            "name": "Move to waypoint",
        },
        {
            "url": "/v2.0.0/missions/d871d686-9006-4ddf-af78-bac9a22ddb53",
            "guid": "d871d686-9006-4ddf-af78-bac9a22ddb53",
            "name": "Move to waypoint",
        },
        {
            "url": "/v2.0.0/missions/not_in_queue_so_safe_to_delete",
            "guid": "not_in_queue_so_safe_to_delete",
            "name": "Move to waypoint",
        },
    ]
    # Missions in the queue
    connector.mir_api.get_missions_queue.return_value = [
        {"url": "/v2.0.0/mission_queue/1", "state": "Abort", "id": 1},
        {"url": "/v2.0.0/mission_queue/2", "state": "Finalized", "id": 2},
        {"url": "/v2.0.0/mission_queue/3", "state": "Pending", "id": 3},
        {"url": "/v2.0.0/mission_queue/4", "state": "Executing", "id": 4},
    ]
    # Definition of missions in the queue
    defs = {
        1: {
            "mission_id": "72003359-6445-419c-85fb-df5576a9ce2e",
            "id": 1,
        },  # Would be safe to delete
        2: {"mission_id": "not_in_tmp_group", "id": 2},  # Should not be deleted
        3: {
            "mission_id": "d871d686-9006-4ddf-af78-bac9a22ddb53",
            "id": 3,
        },  # Not safe to delete
        4: {
            "mission_id": "c0a17f65-39f1-4b10-8fee-77dfe1470ac1",
            "id": 4,
        },  # Not safe to delete
    }
    connector.mir_api.get_mission.side_effect = lambda id: defs[id]
    await connector._delete_unused_missions()
    # Only deletes the mission definition of mission with id 1
    # and mission that is not in the queue
    connector.mir_api.delete_mission_definition.assert_any_call(
        "72003359-6445-419c-85fb-df5576a9ce2e"
    )
    connector.mir_api.delete_mission_definition.assert_any_call(
        "not_in_queue_so_safe_to_delete"
    )
    assert connector.mir_api.delete_mission_definition.call_count == 2


def test_is_robot_online_api_connected(connector):
    """Test that _is_robot_online returns True when MiR API is connected."""
    # Set the underlying attribute that api_connected property reads from
    connector.robot._last_call_successful = True

    # Verify _is_robot_online returns True (via api_connected property)
    assert connector._is_robot_online() is True


def test_is_robot_online_api_disconnected(connector):
    """Test that _is_robot_online returns False when MiR API is disconnected."""
    # Set the underlying attribute that api_connected property reads from
    connector.robot._last_call_successful = False

    # Verify _is_robot_online returns False (via api_connected property)
    assert connector._is_robot_online() is False
