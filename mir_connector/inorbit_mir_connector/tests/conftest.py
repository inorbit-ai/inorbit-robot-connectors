# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest

# Fixtures defined in conftest.py do not require importing


@pytest.fixture(autouse=True)
def disable_network_calls(monkeypatch, requests_mock):
    # Including requests_mock will disable network calls on every test
    pass


@pytest.fixture
def sample_status_data():
    # Sample return value from mir_api.get_status()
    return {
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
        "velocity": {"linear": 0.0, "angular": 0.0},
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


@pytest.fixture
def sample_metrics_data():
    # Sample return value from mir_api.get_metrics()
    return {
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


@pytest.fixture
def sample_mir_mission_data():
    # Sample return value from mir_api.get_mission(id)
    return {
        "priority": 0,
        "ordered": "2023-12-07T10:54:31",
        "description": "",
        "parameters": [],
        "state": "Executing",
        "started": "2023-12-07T10:54:31",
        "created_by_name": "Administrator",
        "mission": "/v2.0.0/missions/71e63050-7b7a-11ed-9f3c-0001299981c4",
        "actions": [{"url": "/v2.0.0/mission_queue/14026/actions/367820", "id": 367820}],
        "fleet_schedule_guid": "",
        "mission_id": "71e63050-7b7a-11ed-9f3c-0001299981c4",
        "finished": None,
        "created_by": "/v2.0.0/users/mirconst-guid-0000-0005-users0000000",
        "created_by_id": "mirconst-guid-0000-0005-users0000000",
        "allowed_methods": ["PUT", "GET", "DELETE"],
        "message": "",
        "control_state": 0,
        "id": 14026,
        "control_posid": "0",
        "definition": {
            "definition": "/v2.0.0/missions/71e63050-7b7a-11ed-9f3c-0001299981c4/definition",
            "guid": "71e63050-7b7a-11ed-9f3c-0001299981c4",
            "allowed_methods": ["PUT", "GET", "DELETE"],
            "description": "",
            "created_by_name": "Administrator",
            "session_id": "85e7b6a1-61bb-11ed-9f1f-0001299981c4",
            "is_template": False,
            "valid": True,
            "created_by": "/v2.0.0/users/mirconst-guid-0000-0005-users0000000",
            "has_user_parameters": False,
            "created_by_id": "mirconst-guid-0000-0005-users0000000",
            "actions": [
                {
                    "priority": 1,
                    "parameters": [
                        {
                            "value": None,
                            "input_name": None,
                            "guid": "723af437-7b7a-11ed-9f3c-0001299981c4",
                            "id": "minimum_time",
                        },
                        {
                            "value": 95.0,
                            "input_name": None,
                            "guid": "723b1f86-7b7a-11ed-9f3c-0001299981c4",
                            "id": "minimum_percentage",
                        },
                        {
                            "value": True,
                            "input_name": None,
                            "guid": "723b45a0-7b7a-11ed-9f3c-0001299981c4",
                            "id": "charge_until_new_mission",
                        },
                    ],
                    "url": "/v2.0.0/mission_actions/723a4e86-7b7a-11ed-9f3c-0001299981c4",
                    "mission_id": "71e63050-7b7a-11ed-9f3c-0001299981c4",
                    "action_type": "charging",
                    "guid": "723a4e86-7b7a-11ed-9f3c-0001299981c4",
                }
            ],
            "group_id": "mirconst-guid-0000-0011-missiongroup",
            "hidden": False,
            "name": "Charge",
        },
    }
