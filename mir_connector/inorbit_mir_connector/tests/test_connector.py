# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import os
import math
import time
import pytest
import threading
import websocket
from inorbit_mir_connector.src.connector import Mir100Connector
from unittest.mock import MagicMock, Mock, call
from inorbit_mir_connector.src.mir_api import APIS
import inorbit_mir_connector.src.connector
from inorbit_edge.robot import RobotSession
from inorbit_mir_connector.config.mir100_model import MiR100Config

API_VERSION = "v2.0"
MirApi = APIS[API_VERSION]["rest"]

# NOTE(b-Tomas): Added some example data below to help creating rea
@pytest.fixture
def connector(monkeypatch):
    monkeypatch.setenv("INORBIT_KEY", "abc123")
    monkeypatch.setattr(MirApi, "_create_api_session", MagicMock())
    monkeypatch.setattr(MirApi, "_create_web_session", MagicMock())
    monkeypatch.setattr(websocket, "WebSocketApp", MagicMock())
    monkeypatch.setattr(RobotSession, "connect", MagicMock())
    monkeypatch.setattr(inorbit_mir_connector.src.connector.os, "makedirs", Mock())

    connector = Mir100Connector(
        "mir100-1",
        MiR100Config(
            inorbit_robot_key="robot_key",
            location_tz="UTC",
            log_level="INFO",
            connector_type="mir100",
            connector_version="0.1.0",
            connector_config={
                "mir_host_address": "example.com",
                "mir_host_port": 80,
                "mir_ws_port": 9090,
                "mir_use_ssl": False,
                "mir_username": "user",
                "mir_password": "pass",
                "mir_api_version": "v2.0",
                "enable_mission_tracking": False,
            },
            user_scripts={"path": "/path/to/scripts", "env_vars": {"name": "value"}},
        ),
    )
    connector.mir_api = MagicMock()
    connector.inorbit_sess = MagicMock()
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


def test_command_callback_unknown_command(connector, callback_kwargs):
    callback_kwargs["command_name"] = "unknown"
    connector.command_callback(**callback_kwargs)
    assert not callback_kwargs["options"]["result_function"].called
    callback_kwargs["command_name"] = "customCommand"
    callback_kwargs["args"] = ["unknown_command", ["arg1", "arg2"]]
    connector.command_callback(**callback_kwargs)
    assert not callback_kwargs["options"]["result_function"].called


def test_command_callback_missions(connector, callback_kwargs):
    def reset_mock():
        callback_kwargs["options"]["result_function"].reset_mock()
        connector.mir_api.reset_mock()

    # Simulate an executor timeout, which should disable robot mission tracking
    connector.inorbit_sess.missions_module.executor.wait_until_idle = Mock(return_value=False)
    assert connector.mission_tracking.mir_mission_tracking_enabled is False
    callback_kwargs["command_name"] = "customCommand"
    callback_kwargs["args"] = ["queue_mission", ["--mission_id", "1"]]
    connector.command_callback(**callback_kwargs)
    assert connector.mission_tracking.mir_mission_tracking_enabled is False
    assert connector.mir_api.queue_mission.call_args == call("1")
    callback_kwargs["options"]["result_function"].assert_called_with("0")
    reset_mock()

    # Queue mission
    connector.inorbit_sess.missions_module.executor.wait_until_idle = Mock(return_value=True)
    callback_kwargs["command_name"] = "customCommand"
    callback_kwargs["args"] = ["queue_mission", ["--mission_id", "2"]]
    connector.command_callback(**callback_kwargs)
    assert connector.mission_tracking.mir_mission_tracking_enabled is True
    assert connector.mir_api.queue_mission.call_args == call("2")
    callback_kwargs["options"]["result_function"].assert_called_with("0")
    reset_mock()

    # Run mission now
    callback_kwargs["command_name"] = "customCommand"
    callback_kwargs["args"] = ["run_mission_now", ["--mission_id", "3"]]
    connector.command_callback(**callback_kwargs)
    assert connector.mir_api.abort_all_missions.call_args == call()
    assert connector.mir_api.queue_mission.call_args == call("3")
    callback_kwargs["options"]["result_function"].assert_called_with("0")
    reset_mock()

    # Abort all
    callback_kwargs["command_name"] = "customCommand"
    callback_kwargs["args"] = ["abort_missions", []]
    connector.command_callback(**callback_kwargs)
    assert connector.inorbit_sess.missions_module.executor.cancel_mission.call_args == call("*")
    assert connector.mir_api.abort_all_missions.call_args == call()
    callback_kwargs["options"]["result_function"].assert_called_with("0")
    reset_mock()


def test_registers_user_scripts_config(monkeypatch):
    old_env = os.environ.copy()

    def create_connector(user_scripts):
        monkeypatch.setenv("INORBIT_KEY", "abc123")
        monkeypatch.setattr(MirApi, "_create_api_session", MagicMock())
        monkeypatch.setattr(MirApi, "_create_web_session", MagicMock())
        monkeypatch.setattr(websocket, "WebSocketApp", MagicMock())
        monkeypatch.setattr(RobotSession, "connect", MagicMock())
        monkeypatch.setattr(RobotSession, "register_commands_path", MagicMock())
        monkeypatch.setattr(time, "sleep", Mock())
        monkeypatch.setattr(inorbit_mir_connector.src.connector.os, "makedirs", Mock())

        connector = Mir100Connector(
            "mir100-1",
            MiR100Config(
                inorbit_robot_key="robot_key",
                location_tz="UTC",
                log_level="INFO",
                connector_type="mir100",
                connector_version="0.1.0",
                connector_config={
                    "mir_username": "user",
                    "mir_password": "pass",
                    "mir_host_address": "example.com",
                    "mir_host_port": 80,
                    "mir_ws_port": 9090,
                    "mir_use_ssl": False,
                    "mir_api_version": "v2.0",
                    "enable_mission_tracking": False,
                },
                user_scripts=user_scripts,
                cameras=[],
            ),
        )
        return connector

    # A default scripts dir is set
    os.environ.clear()
    connector = create_connector({})
    connector.inorbit_sess.register_commands_path.assert_called_with(
        os.path.expanduser("~/.inorbit_connectors/connector-mir100-1/local/"),
        exec_name_regex=r".*\.sh",
    )
    assert os.environ == {"INORBIT_KEY": "abc123"}

    # A custom scripts dir is set
    connector = create_connector({"path": "/path/to/scripts"})
    connector.inorbit_sess.register_commands_path.assert_called_with(
        "/path/to/scripts", exec_name_regex=r".*\.sh"
    )

    # Env vars are set
    connector = create_connector({"env_vars": {"name": "value"}})
    connector.inorbit_sess.register_commands_path.assert_called_with(
        os.path.expanduser("~/.inorbit_connectors/connector-mir100-1/local/"),
        exec_name_regex=r".*\.sh",
    )
    assert os.environ.get("name") == "value"

    for k, v in old_env.items():
        os.environ[k] = v


def test_command_callback_state(connector, callback_kwargs):
    MIR_STATE = {3: "READY", 4: "PAUSE", 11: "MANUALCONTROL"}

    callback_kwargs["command_name"] = "customCommand"
    for id, state in MIR_STATE.items():
        callback_kwargs["args"] = ["set_state", ["--state_id", str(id)]]
        connector.command_callback(**callback_kwargs)
        callback_kwargs["options"]["result_function"].assert_called_with("0")
        connector.mir_api.set_state.assert_called_with(id)
        connector.mir_api.set_state.reset_mock()
        callback_kwargs["options"]["result_function"].reset_mock()

    callback_kwargs["args"] = ["set_state", ["--state_id", "123"]]
    connector.command_callback(**callback_kwargs)
    callback_kwargs["options"]["result_function"].assert_called_with("1")
    assert not connector.mir_api.set_state.called

    callback_kwargs["args"] = ["set_state", ["--state_id", "abc"]]
    connector.command_callback(**callback_kwargs)
    callback_kwargs["options"]["result_function"].assert_called_with("1")
    assert not connector.mir_api.set_state.called


def test_command_callback_nav_goal(connector, callback_kwargs):
    callback_kwargs["command_name"] = "navGoal"
    callback_kwargs["args"] = [{"x": "1", "y": "2", "theta": "3.14"}]
    connector.command_callback(**callback_kwargs)
    assert connector.mir_api.send_waypoint.call_args_list == [
        call({"x": "1", "y": "2", "theta": "3.14"})
    ]


def test_command_callback_inorbit_messages(connector, callback_kwargs):
    callback_kwargs["command_name"] = "message"
    for message, code in {"inorbit_pause": 4, "inorbit_resume": 3}.items():
        callback_kwargs["args"] = [message]
        connector.command_callback(**callback_kwargs)
        assert connector.mir_api.set_state.call_args == call(code)


def test_connector_loop(connector, monkeypatch):
    connector.mission_tracking.report_mission = Mock()

    def run_loop_once():
        monkeypatch.setattr(inorbit_mir_connector.src.connector, "sleep", Mock())
        connector_thread = threading.Thread(target=connector.start)
        connector_thread.start()
        while not inorbit_mir_connector.src.connector.sleep.called:
            pass
        connector.stop()
        connector_thread.join()

    connector.mir_api.get_status.return_value = {
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

    connector.mir_api.get_metrics.return_value = {
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

    run_loop_once()

    assert connector.inorbit_sess.publish_pose.call_args == call(
        x=9.52050495147705, y=7.156267166137695, yaw=1.8204675458317707
    )
    assert connector.inorbit_sess.publish_odometry.call_args == call(
        linear_speed=1.1, angular_speed=math.pi
    )
    assert connector.inorbit_sess.publish_key_values.call_args == call(
        {
            "battery percent": 93.5,
            "battery_time_remaining": 89725,
            "uptime": 3552693,
            "localization_score": 0.027316320645337056,
            "robot_name": "Miriam",
            "errors": [],
            "distance_to_next_target": 0.1987656205892563,
            "mission_text": "Charging until battery reaches 95% (Current: 94%)...",
            "state_text": "Executing",
            "mode_text": "Mission",
            "robot_model": "MiR100",
            "waiting_for": "",
        }
    )

    connector.mir_api.get_metrics.side_effect = Exception("Test")
    connector.inorbit_sess.reset_mock()
    run_loop_once()
    assert not connector.inorbit_sess.publish_pose.called
    assert not connector.inorbit_sess.publish_key_values.called
    assert not connector.inorbit_sess.publish_odometry.called


def test_stops(connector, monkeypatch):
    monkeypatch.setattr(inorbit_mir_connector.src.connector, "sleep", Mock())
    connector_thread = threading.Thread(target=connector.start)
    connector_thread.start()
    connector.stop()
    connector_thread.join()
    assert connector.inorbit_sess.disconnect.called
    # This is to make sure the mock object is helping reduce test time.
    # Importing sleep in a different way in the connector module would make the patch above useless
    # and it'd need to be updated.
    assert inorbit_mir_connector.src.connector.sleep.called
