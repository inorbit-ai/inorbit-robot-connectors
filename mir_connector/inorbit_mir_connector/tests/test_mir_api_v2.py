# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from inorbit_mir_connector.src.mir_api import MirApiV2
from deepdiff import DeepDiff
from requests.exceptions import HTTPError


@pytest.fixture
def mir_api(requests_mock):
    mir_api_url = "http://example.com"
    requests_mock.post(f"{mir_api_url}/?mode=log-in", text="I'm letting you in")
    api = MirApiV2(
        mir_base_url=mir_api_url,
        mir_username="user",
        mir_password="pass",
        loglevel="INFO",
    )
    return api


def test_http_error(mir_api, requests_mock):
    requests_mock.get(f"{mir_api.mir_api_url}/metrics", status_code=500)
    with pytest.raises(HTTPError):
        mir_api.get_metrics()


def test_get_executing_mission_id(mir_api, requests_mock):
    missions = [
        {"id": 2, "state": "Aborted"},
        {"id": 1, "state": "Executing"},
        {"id": 3, "state": "Completed"},
    ]
    requests_mock.get(f"{mir_api.mir_api_url}/mission_queue", json=missions)
    assert mir_api.get_executing_mission_id() == 1


def test_get_metrics(mir_api, requests_mock):
    input = """
# HELP mir_robot_localization_score A measure of the robots position estimate relative to the map. A value of 0 indicates a perfect value and values closer to zero are better.
# TYPE mir_robot_localization_score gauge
mir_robot_localization_score 0.027316320645337056
# HELP mir_robot_position_x_meters The x coordinate of the robots current position.
# TYPE mir_robot_position_x_meters gauge
# UNIT mir_robot_position_x_meters meters
mir_robot_position_x_meters 9.52050495147705
# HELP mir_robot_position_y_meters The y coordinate of the robots current position.
# TYPE mir_robot_position_y_meters gauge
# UNIT mir_robot_position_y_meters meters
mir_robot_position_y_meters 7.156267166137695
# HELP mir_robot_orientation_degrees The orientation of the robots current position.
# TYPE mir_robot_orientation_degrees gauge
# UNIT mir_robot_orientation_degrees degrees
mir_robot_orientation_degrees 104.30510711669922
# HELP mir_robot_info An info style metric with constant value '1' and labels containing information about the robot.
# TYPE mir_robot_info gauge
mir_robot_info{map_guid="20f762ff-5e0a-11ee-abc8-0001299981c4",model="MIR100",name="Miriam",serial_number="200100005001715",software_version="2.13.0.6"} 1.0
# HELP mir_robot_distance_moved_meters The total distance moved by the robot.
# TYPE mir_robot_distance_moved_meters counter
# UNIT mir_robot_distance_moved_meters meters
mir_robot_distance_moved_meters_total 671648.3914381799
# HELP mir_robot_errors The number of active errors on the robot.
# TYPE mir_robot_errors gauge
mir_robot_errors 0.0
# HELP mir_robot_state_id Integer indicating the current state of the robot.
# TYPE mir_robot_state_id gauge
mir_robot_state_id 5.0
# HELP mir_robot_uptime_seconds Duration describing how long the robot has been running.
# TYPE mir_robot_uptime_seconds gauge
# UNIT mir_robot_uptime_seconds seconds
mir_robot_uptime_seconds 3.558422e+06
# HELP mir_robot_battery_percent The robots current battery percent.
# TYPE mir_robot_battery_percent gauge
mir_robot_battery_percent 98.5999984741211
# HELP mir_robot_battery_time_remaining_seconds Estimated battery time remaining on the robot.
# TYPE mir_robot_battery_time_remaining_seconds gauge
# UNIT mir_robot_battery_time_remaining_seconds seconds
mir_robot_battery_time_remaining_seconds 81695.0
# HELP mir_robot_wifi_access_point_rssi_dbm Decibel value of the signal level of the wireless network.
# TYPE mir_robot_wifi_access_point_rssi_dbm gauge
# UNIT mir_robot_wifi_access_point_rssi_dbm dbm
mir_robot_wifi_access_point_rssi_dbm -47.0
# HELP mir_robot_wifi_access_point_info Information about the access point that the robot is currently connected to.
# TYPE mir_robot_wifi_access_point_info gauge
mir_robot_wifi_access_point_info{bssid="",ssid=""} 1.0
# HELP mir_robot_wifi_access_point_frequency_hertz Frequency of the access point that the robot is currently connected to.
# TYPE mir_robot_wifi_access_point_frequency_hertz gauge
# UNIT mir_robot_wifi_access_point_frequency_hertz hertz
mir_robot_wifi_access_point_frequency_hertz 0.0
# EOF
"""  # noqa: E501
    expected_output = {
        "mir_robot_localization_score": 0.027316320645337056,
        "mir_robot_position_x_meters": 9.52050495147705,
        "mir_robot_position_y_meters": 7.156267166137695,
        "mir_robot_orientation_degrees": 104.30510711669922,
        "mir_robot_info": 1.0,
        "mir_robot_distance_moved_meters_total": 671648.3914381799,
        "mir_robot_errors": 0.0,
        "mir_robot_state_id": 5.0,
        "mir_robot_uptime_seconds": 3558422.0,
        "mir_robot_battery_percent": 98.5999984741211,
        "mir_robot_battery_time_remaining_seconds": 81695.0,
        "mir_robot_wifi_access_point_rssi_dbm": -47.0,
        "mir_robot_wifi_access_point_info": 1.0,
        "mir_robot_wifi_access_point_frequency_hertz": 0.0,
    }

    requests_mock.get(f"{mir_api.mir_api_url}/metrics", text=input)
    metrics = mir_api.get_metrics()

    assert DeepDiff(expected_output, metrics) == {}
