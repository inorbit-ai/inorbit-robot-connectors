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


@pytest.fixture
def sample_mir_diagnostics_agg_data():
    # Sample return value from ws connection, when getting a
    # diagnostics_agg message
    return {
        "topic": "/diagnostics_agg",
        "msg": {
            "status": [
                {
                    "message": "OK",
                    "hardware_id": "",
                    "values": [
                        {"value": "CPU load is OK", "key": "/Computer/PC/CPU Load"},
                        {"value": "CPU temperature is OK", "key": "/Computer/PC/CPU Temperature"},
                        {"value": "Harddrive is OK", "key": "/Computer/PC/Harddrive"},
                        {"value": "Memory is OK", "key": "/Computer/PC/Memory"},
                    ],
                    "name": "/Computer/PC",
                    "level": 0,
                },
                {
                    "message": "CPU load is OK",
                    "hardware_id": "PC",
                    "values": [
                        {"value": "49.2", "key": "Average CPU load"},
                        {"value": "40.7", "key": "Average CPU load (30 second)"},
                        {"value": "41.5", "key": "Average CPU load (3 minut)"},
                        {
                            "value": "42.2",
                            "key": '{"message": "Thread %(number)d", "args": {"number":0}}',
                        },
                        {
                            "value": "43.5",
                            "key": '{"message": "Thread %(number)d", "args": {"number":1}}',
                        },
                        {
                            "value": "58.7",
                            "key": '{"message": "Thread %(number)d", "args": {"number":2}}',
                        },
                        {
                            "value": "52.3",
                            "key": '{"message": "Thread %(number)d", "args": {"number":3}}',
                        },
                    ],
                    "name": "/Computer/PC/CPU Load",
                    "level": 0,
                },
                {
                    "message": "CPU temperature is OK",
                    "hardware_id": "PC",
                    "values": [
                        {"value": "45", "key": "Package id 0"},
                        {"value": "45", "key": "Core 0"},
                        {"value": "44", "key": "Core 1"},
                    ],
                    "name": "/Computer/PC/CPU Temperature",
                    "level": 0,
                },
                {
                    "message": "Harddrive is OK",
                    "hardware_id": "PC",
                    "values": [
                        {
                            "value": "102.94",
                            "key": '{"message": "Total size %(unit)s", "args": {"unit":"[GB]"}}',
                        },
                        {
                            "value": "23.14",
                            "key": '{"message": "Used %(unit)s", "args": {"unit":"[GB]"}}',
                        },
                        {
                            "value": "79.09",
                            "key": '{"message": "Free %(unit)s", "args": {"unit":"[GB]"}}',
                        },
                    ],
                    "name": "/Computer/PC/Harddrive",
                    "level": 0,
                },
                {
                    "message": "Memory is OK",
                    "hardware_id": "PC",
                    "values": [
                        {
                            "value": "7.63",
                            "key": '{"message": "Total size %(unit)s", "args": {"unit":"[GB]"}}',
                        },
                        {
                            "value": "1.87",
                            "key": '{"message": "Used %(unit)s", "args": {"unit":"[GB]"}}',
                        },
                        {
                            "value": "5.37",
                            "key": '{"message": "Free %(unit)s", "args": {"unit":"[GB]"}}',
                        },
                    ],
                    "name": "/Computer/PC/Memory",
                    "level": 0,
                },
                {
                    "message": "OK",
                    "hardware_id": "",
                    "values": [
                        {"value": "", "key": "/Computer/Network/Gateways"},
                        {
                            "value": '{"message": "Active with Slave Interface %(index)d", "args": {"index":2}}',
                            "key": "/Computer/Network/Master Interface",
                        },
                        {"value": "Link is up", "key": "/Computer/Network/Wifi"},
                        {
                            "value": "Link is down",
                            "key": '/Computer/Network/{"message": "Slave Interface %(index)s", "args": {"index":1}}',
                        },
                        {
                            "value": "Link is up",
                            "key": '/Computer/Network/{"message": "Slave Interface %(index)s", "args": {"index":2}}',
                        },
                    ],
                    "name": "/Computer/Network",
                    "level": 0,
                },
                {
                    "message": "",
                    "hardware_id": "",
                    "values": [
                        {
                            "value": "600",
                            "key": '{"message": "Priority %(gateway)s", "args": {"gateway":"192.168.1.1"}}',
                        }
                    ],
                    "name": "/Computer/Network/Gateways",
                    "level": 0,
                },
                {
                    "message": '{"message": "Active with Slave Interface %(index)d", "args": {"index":2}}',
                    "hardware_id": "enp_br0",
                    "values": [
                        {"value": "enp_br0", "key": "Interface name"},
                        {"value": "00:01:29:99:81:c4", "key": "MAC address"},
                        {"value": "up", "key": "Link status"},
                        {"value": "192.168.12.20", "key": "IP address"},
                        {"value": "255.255.255.0", "key": "IP netmask"},
                        {"value": "1", "key": "Link up count"},
                        {"value": "1", "key": "Link down count"},
                        {"value": "0", "key": "Transmit errors"},
                        {"value": "0", "key": "Receive errors"},
                        {"value": "0", "key": "Collisions"},
                        {
                            "value": "338.81",
                            "key": '{"message": "Transmitted bytes %(unit)s", "args": {"unit":"[MB]"}}',
                        },
                        {
                            "value": "163.7",
                            "key": '{"message": "Received bytes %(unit)s", "args": {"unit":"[MB]"}}',
                        },
                    ],
                    "name": "/Computer/Network/Master Interface",
                    "level": 0,
                },
                {
                    "message": "Link is up",
                    "hardware_id": "wlp2s0",
                    "values": [
                        {"value": "wlp2s0", "key": "Interface name"},
                        {"value": "20:a7:87:00:ba:30", "key": "MAC address"},
                        {"value": "up", "key": "Link status"},
                        {"value": "192.168.1.2", "key": "IP address"},
                        {"value": "255.255.255.0", "key": "IP netmask"},
                        {"value": "4", "key": "Link up count"},
                        {"value": "4", "key": "Link down count"},
                        {"value": "0", "key": "Transmit errors"},
                        {"value": "0", "key": "Receive errors"},
                        {"value": "0", "key": "Collisions"},
                        {
                            "value": "3.81",
                            "key": '{"message": "Transmitted bytes %(unit)s", "args": {"unit":"[GB]"}}',
                        },
                        {
                            "value": "1.77",
                            "key": '{"message": "Received bytes %(unit)s", "args": {"unit":"[GB]"}}',
                        },
                        {"value": "InOrbit", "key": "SSID"},
                        {"value": "a0:40:a0:8c:da:01", "key": "Access point MAC"},
                        {"value": "5745", "key": "Frequency"},
                        {"value": "-43", "key": "Signal level"},
                    ],
                    "name": "/Computer/Network/Wifi",
                    "level": 0,
                },
                {
                    "message": "Link is down",
                    "hardware_id": "enp0s31f6",
                    "values": [
                        {"value": "enp0s31f6", "key": "Interface name"},
                        {"value": "00:01:29:99:81:c5", "key": "MAC address"},
                        {"value": "down", "key": "Link status"},
                        {"value": "0", "key": "Link up count"},
                        {"value": "1", "key": "Link down count"},
                        {"value": "0", "key": "Transmit errors"},
                        {"value": "0", "key": "Receive errors"},
                        {"value": "0", "key": "Collisions"},
                        {
                            "value": "0",
                            "key": '{"message": "Transmitted bytes %(unit)s", "args": {"unit":"[B]"}}',
                        },
                        {
                            "value": "0",
                            "key": '{"message": "Received bytes %(unit)s", "args": {"unit":"[B]"}}',
                        },
                        {"value": " No", "key": "Ethernet link detected"},
                        {"value": "-1", "key": "Ethernet link speed [MBit/s]"},
                        {"value": "Half", "key": "Ethernet link duplex"},
                        {"value": "Yes", "key": "Ethernet link auto negotiation"},
                        {
                            "value": "100baseT_Full, Autoneg, TP",
                            "key": "Ethernet link advertised modes",
                        },
                        {"value": "", "key": "Ethernet link partner advertised modes"},
                    ],
                    "name": '/Computer/Network/{"message": "Slave Interface %(index)s", "args": {"index":1}}',
                    "level": 0,
                },
                {
                    "message": "Link is up",
                    "hardware_id": "enp1s0",
                    "values": [
                        {"value": "enp1s0", "key": "Interface name"},
                        {"value": "00:01:29:99:81:c4", "key": "MAC address"},
                        {"value": "up", "key": "Link status"},
                        {"value": "1", "key": "Link up count"},
                        {"value": "1", "key": "Link down count"},
                        {"value": "0", "key": "Transmit errors"},
                        {"value": "0", "key": "Receive errors"},
                        {"value": "0", "key": "Collisions"},
                        {
                            "value": "338.81",
                            "key": '{"message": "Transmitted bytes %(unit)s", "args": {"unit":"[MB]"}}',
                        },
                        {
                            "value": "204.28",
                            "key": '{"message": "Received bytes %(unit)s", "args": {"unit":"[MB]"}}',
                        },
                        {"value": "Yes", "key": "Ethernet link detected"},
                        {"value": "100", "key": "Ethernet link speed [MBit/s]"},
                        {"value": "Full", "key": "Ethernet link duplex"},
                        {"value": "Yes", "key": "Ethernet link auto negotiation"},
                        {
                            "value": "100baseT_Full, Autoneg, TP",
                            "key": "Ethernet link advertised modes",
                        },
                        {"value": "", "key": "Ethernet link partner advertised modes"},
                    ],
                    "name": '/Computer/Network/{"message": "Slave Interface %(index)s", "args": {"index":2}}',
                    "level": 0,
                },
                {
                    "message": "OK",
                    "hardware_id": "",
                    "values": [{"value": "OK", "key": "PC"}, {"value": "OK", "key": "Network"}],
                    "name": "/Computer",
                    "level": 0,
                },
                {
                    "message": "OK",
                    "hardware_id": "",
                    "values": [
                        {"value": "Controller is OK", "key": "/Motors/Controller"},
                        {"value": "Motor is OK", "key": "/Motors/Left"},
                        {"value": "Motor is ok", "key": "/Motors/Right"},
                    ],
                    "name": "/Motors",
                    "level": 0,
                },
                {
                    "message": "Controller is OK",
                    "hardware_id": "SDC21X0",
                    "values": [
                        {"value": "Serial mode | Script running", "key": "Status Flag"},
                        {"value": "Controller is ok", "key": "Fault Flag"},
                        {"value": "Off", "key": "MC Emergency Stop"},
                        {"value": "Off", "key": "Safety Emergency Stop"},
                        {"value": "12", "key": "Driver Voltage"},
                        {"value": "4.944", "key": "5V out"},
                        {"value": "36", "key": "IC temp"},
                        {"value": "33", "key": "Channel temp"},
                        {"value": "False", "key": "Robot is moving"},
                        {"value": "5601.66", "key": "Time since last movement"},
                        {"value": "False", "key": "Motor 10 sec current limit active"},
                        {"value": "False", "key": "Motor 60 sec current limit active"},
                        {"value": "12", "key": "Motor 10 sec current limit [A]"},
                        {"value": "7.5", "key": "Motor 60 sec current limit [A]"},
                        {"value": "120", "key": "MotorController Script Version"},
                        {"value": "22155070", "key": "Valid commands received"},
                        {"value": "0", "key": "Invalid commands received"},
                        {"value": "511610", "key": "ACK received"},
                        {"value": "0", "key": "NACK received"},
                        {"value": "Roboteq v1.6 SDC2XXX 04/14/2016", "key": "Firmware"},
                        {"value": "SDC2160", "key": "Controller type"},
                        {"value": "10819706", "key": "Encoder delay <30 ms"},
                        {"value": "1572", "key": "Encoder delay 30-50 ms"},
                        {"value": "5", "key": "Encoder delay >50 ms"},
                    ],
                    "name": "/Motors/Controller",
                    "level": 0,
                },
                {
                    "message": "Motor is OK",
                    "hardware_id": "SDC21X0",
                    "values": [
                        {"value": "OK", "key": "Runtime flag"},
                        {"value": "0", "key": "Motor current"},
                        {"value": "0", "key": "Motor error"},
                        {"value": "0", "key": "Closed Loop Error"},
                        {"value": "0", "key": "Motor current (1 sec avg)"},
                        {"value": "0", "key": "Motor current (10 sec avg)"},
                        {"value": "0", "key": "Motor current (60 sec avg)"},
                        {"value": "0", "key": "Motor current (10 min avg)"},
                        {"value": "258732", "key": "Encoder"},
                    ],
                    "name": "/Motors/Left",
                    "level": 0,
                },
                {
                    "message": "Motor is ok",
                    "hardware_id": "SDC21X0",
                    "values": [
                        {"value": "OK", "key": "Runtime Flag"},
                        {"value": "0", "key": "Motor current"},
                        {"value": "0", "key": "Motor Error"},
                        {"value": "0", "key": "Closed Loop Error"},
                        {"value": "0", "key": "Motor current (1 sec avg)"},
                        {"value": "0", "key": "Motor current (10 sec avg)"},
                        {"value": "0", "key": "Motor current (60 sec avg)"},
                        {"value": "0", "key": "Motor current (10 min avg)"},
                        {"value": "180399", "key": "Encoder"},
                    ],
                    "name": "/Motors/Right",
                    "level": 0,
                },
                {
                    "message": "OK",
                    "hardware_id": "",
                    "values": [
                        {"value": "Battery is OK", "key": "/Power System/Battery"},
                        {
                            "value": "BMS communication is OK",
                            "key": "/Power System/Battery Management System",
                        },
                        {
                            "value": "Raw battery data is OK",
                            "key": "/Power System/Battery Raw Data",
                        },
                        {"value": "OK", "key": "/Power System/Charging Status"},
                    ],
                    "name": "/Power System",
                    "level": 0,
                },
                {
                    "message": "Battery is OK",
                    "hardware_id": "Battery",
                    "values": [
                        {"value": "98.8", "key": "Remaining battery capacity [%]"},
                        {"value": "94807", "key": "Remaining battery time [sec]"},
                        {"value": "26:20:07", "key": "Remaining battery time [HH:MM:SS]"},
                        {"value": "0", "key": "Battery Amps"},
                    ],
                    "name": "/Power System/Battery",
                    "level": 0,
                },
                {
                    "message": "BMS communication is OK",
                    "hardware_id": "Battery",
                    "values": [
                        {"value": "28.5", "key": "Pack voltage [V]"},
                        {"value": "3.3", "key": "Charge current [A]"},
                        {"value": "0", "key": "Discharge current [A]"},
                        {"value": "99", "key": "State of charge [%]"},
                        {"value": "0", "key": "Remaining time to full charge [hours]"},
                        {"value": "41286", "key": "Remaining capacity [mAh]"},
                        {"value": "100", "key": "State of health [%]"},
                        {"value": "0", "key": "Status flags"},
                        {"value": "30", "key": "Temperature [degrees]"},
                        {
                            "value": "4069",
                            "key": '{"message": "Cell voltage %(cell)d [mV]", "args": {"cell":0}}',
                        },
                        {
                            "value": "4071",
                            "key": '{"message": "Cell voltage %(cell)d [mV]", "args": {"cell":1}}',
                        },
                        {
                            "value": "4076",
                            "key": '{"message": "Cell voltage %(cell)d [mV]", "args": {"cell":2}}',
                        },
                        {
                            "value": "4072",
                            "key": '{"message": "Cell voltage %(cell)d [mV]", "args": {"cell":3}}',
                        },
                        {
                            "value": "4078",
                            "key": '{"message": "Cell voltage %(cell)d [mV]", "args": {"cell":4}}',
                        },
                        {
                            "value": "4076",
                            "key": '{"message": "Cell voltage %(cell)d [mV]", "args": {"cell":5}}',
                        },
                        {
                            "value": "4076",
                            "key": '{"message": "Cell voltage %(cell)d [mV]", "args": {"cell":6}}',
                        },
                        {"value": "SBS_SLIDE", "key": "Battery type"},
                        {"value": "Charge", "key": "Battery state"},
                        {"value": "3532000000000000", "key": "Battery serial 1"},
                        {"value": "3035393035303232", "key": "Battery serial 2"},
                        {"value": "10.725.2", "key": "Battery article"},
                        {"value": "0.3.32", "key": "Firmware version"},
                    ],
                    "name": "/Power System/Battery Management System",
                    "level": 0,
                },
                {
                    "message": "Raw battery data is OK",
                    "hardware_id": "Battery",
                    "values": [
                        {"value": "0", "key": "Battery 1 current"},
                        {"value": "0", "key": "Battery 2 current"},
                        {"value": "28.2", "key": "Battery Voltage"},
                    ],
                    "name": "/Power System/Battery Raw Data",
                    "level": 0,
                },
                {
                    "message": "OK",
                    "hardware_id": "Battery",
                    "values": [
                        {"value": "On", "key": "Charging relay"},
                        {"value": "28.268", "key": "Voltage [V]"},
                        {"value": "3797", "key": "Voltage [0-4096]"},
                        {"value": "No", "key": "Low voltage"},
                    ],
                    "name": "/Power System/Charging Status",
                    "level": 0,
                },
                {
                    "message": "OK",
                    "hardware_id": "",
                    "values": [
                        {"value": "SICK Safety PLC is OK", "key": "/Safety System/Communication"},
                        {"value": "Emergency Stop is OK", "key": "/Safety System/Emergency Stop"},
                    ],
                    "name": "/Safety System",
                    "level": 0,
                },
                {
                    "message": "SICK Safety PLC is OK",
                    "hardware_id": "SickPLC",
                    "values": [
                        {"value": "192.168.12.9", "key": "IP address"},
                        {"value": "9100", "key": "Port"},
                        {"value": "270338", "key": "PLC auto command received"},
                        {"value": "cd:16:44:87", "key": "CRC"},
                    ],
                    "name": "/Safety System/Communication",
                    "level": 0,
                },
                {
                    "message": "Emergency Stop is OK",
                    "hardware_id": "SickPLC",
                    "values": [
                        {"value": "Free", "key": "Laser (Front)"},
                        {"value": "Free", "key": "Laser (Back)"},
                        {"value": "2", "key": "Revision"},
                        {"value": "Disconnected", "key": "Charger cable or switch"},
                        {"value": "Released", "key": "Emergency button"},
                        {"value": "OK", "key": "Power relay feedback"},
                        {"value": "OK", "key": "Brake relay feedback"},
                        {"value": "OK", "key": "Speed violation"},
                        {"value": "Clean", "key": "Front scanner cover"},
                        {"value": "Clean", "key": "Back scanner cover"},
                        {"value": "OK", "key": "Left encoder discrepancy"},
                        {"value": "OK", "key": "Right encoder discrepancy"},
                        {"value": "3", "key": "Input module 1"},
                        {"value": "3", "key": "Output module 1"},
                    ],
                    "name": "/Safety System/Emergency Stop",
                    "level": 0,
                },
                {
                    "message": "OK",
                    "hardware_id": "",
                    "values": [
                        {
                            "value": "Connected to scanner",
                            "key": "/Sensors/Laserscanner (Back)/Communication",
                        }
                    ],
                    "name": "/Sensors/Laserscanner (Back)",
                    "level": 0,
                },
                {
                    "message": "Connected to scanner",
                    "hardware_id": "Sick S300",
                    "values": [
                        {"value": "/dev/ttyS1", "key": "Device"},
                        {"value": "FTYPRRXA", "key": "Serial number"},
                        {"value": "57600", "key": "Baud rate"},
                        {"value": "4294967295", "key": "Protocol"},
                        {"value": "12.7", "key": "Data frequency [Hz]"},
                        {"value": "3329404", "key": "Total transmissions"},
                        {"value": "0", "key": "Failed transmissions"},
                        {"value": "0", "key": "Failed transmissions (%)"},
                        {"value": "False", "key": "Using calibration map"},
                        {"value": "0.97", "key": "Linearization slope"},
                        {"value": "0.03", "key": "Linearization offset"},
                    ],
                    "name": "/Sensors/Laserscanner (Back)/Communication",
                    "level": 0,
                },
                {
                    "message": "OK",
                    "hardware_id": "",
                    "values": [
                        {"value": "Camera is OK", "key": "/Sensors/3D Camera (Left)/Connection"}
                    ],
                    "name": "/Sensors/3D Camera (Left)",
                    "level": 0,
                },
                {
                    "message": "Camera is OK",
                    "hardware_id": "RealsenseD435",
                    "values": [
                        {"value": "14.99", "key": "Data Frequency [Hz]"},
                        {"value": "3905084", "key": "Frame Counter"},
                        {"value": "Intel RealSense D435", "key": "Device Name"},
                        {"value": "920312071818", "key": "Device Serial Number"},
                        {"value": "05.11.06.250", "key": "Device Firmware Version"},
                        {
                            "value": "/sys/devices/pci0000:00/0000:00:14.0/usb2/2-1/2-1:1.0/video4linux/video0",
                            "key": "Device Physical Port",
                        },
                        {"value": "3.2", "key": "Device USB version"},
                    ],
                    "name": "/Sensors/3D Camera (Left)/Connection",
                    "level": 0,
                },
                {
                    "message": "OK",
                    "hardware_id": "",
                    "values": [
                        {"value": "Camera is OK", "key": "/Sensors/3D Camera (Right)/Connection"}
                    ],
                    "name": "/Sensors/3D Camera (Right)",
                    "level": 0,
                },
                {
                    "message": "Camera is OK",
                    "hardware_id": "RealsenseD435",
                    "values": [
                        {"value": "14.88", "key": "Data Frequency [Hz]"},
                        {"value": "3902606", "key": "Frame Counter"},
                        {"value": "Intel RealSense D435", "key": "Device Name"},
                        {"value": "920312071416", "key": "Device Serial Number"},
                        {"value": "05.11.06.250", "key": "Device Firmware Version"},
                        {
                            "value": "/sys/devices/pci0000:00/0000:00:14.0/usb2/2-2/2-2:1.0/video4linux/video3",
                            "key": "Device Physical Port",
                        },
                        {"value": "3.2", "key": "Device USB version"},
                    ],
                    "name": "/Sensors/3D Camera (Right)/Connection",
                    "level": 0,
                },
                {
                    "message": "OK",
                    "hardware_id": "",
                    "values": [
                        {
                            "value": "Connected to scanner",
                            "key": "/Sensors/Laserscanner (Front)/Communication",
                        }
                    ],
                    "name": "/Sensors/Laserscanner (Front)",
                    "level": 0,
                },
                {
                    "message": "Connected to scanner",
                    "hardware_id": "Sick S300",
                    "values": [
                        {"value": "/dev/ttyS0", "key": "Device"},
                        {"value": "FTYPS40X", "key": "Serial number"},
                        {"value": "57600", "key": "Baud rate"},
                        {"value": "4294967295", "key": "Protocol"},
                        {"value": "12.7", "key": "Data frequency [Hz]"},
                        {"value": "3328779", "key": "Total transmissions"},
                        {"value": "0", "key": "Failed transmissions"},
                        {"value": "0", "key": "Failed transmissions (%)"},
                        {"value": "False", "key": "Using calibration map"},
                        {"value": "0.97", "key": "Linearization slope"},
                        {"value": "0.03", "key": "Linearization offset"},
                    ],
                    "name": "/Sensors/Laserscanner (Front)/Communication",
                    "level": 0,
                },
                {
                    "message": "OK",
                    "hardware_id": "",
                    "values": [
                        {"value": "Accelerometer is OK", "key": "/Sensors/IMU/Accelerometer"},
                        {"value": "Connection OK", "key": "/Sensors/IMU/Connection"},
                        {"value": "Gyroscope is OK", "key": "/Sensors/IMU/Gyroscope"},
                    ],
                    "name": "/Sensors/IMU",
                    "level": 0,
                },
                {
                    "message": "Accelerometer is OK",
                    "hardware_id": "Teensy",
                    "values": [
                        {"value": "49.9709", "key": "Data frequency [Hz]"},
                        {"value": "0.009", "key": "X"},
                        {"value": "-0.003", "key": "Y"},
                        {"value": "0.998", "key": "Z"},
                    ],
                    "name": "/Sensors/IMU/Accelerometer",
                    "level": 0,
                },
                {
                    "message": "Connection OK",
                    "hardware_id": "Teensy",
                    "values": [
                        {"value": "/dev/ttyACM0", "key": "Port"},
                        {"value": "0", "key": "Commands send"},
                        {"value": "22537832", "key": "Messages recieved"},
                        {"value": "3.5.0", "key": "MiR Board SW version"},
                        {"value": "1.2.0", "key": "MiR Board HW version"},
                        {"value": "3.2", "key": "MiR Board Teensy version"},
                    ],
                    "name": "/Sensors/IMU/Connection",
                    "level": 0,
                },
                {
                    "message": "Gyroscope is OK",
                    "hardware_id": "Teensy",
                    "values": [
                        {"value": "49.9709", "key": "Data frequency [Hz]"},
                        {"value": "-82.826", "key": "Yaw"},
                        {"value": "-0.279", "key": "Pitch"},
                        {"value": "-0.243", "key": "Roll"},
                        {"value": "35.21", "key": "IMU Temperature"},
                        {"value": "3.89711", "key": "Last Drift Correction"},
                    ],
                    "name": "/Sensors/IMU/Gyroscope",
                    "level": 0,
                },
                {
                    "message": "Not started",
                    "hardware_id": "",
                    "values": [],
                    "name": "/Sensors/Ultrasonic sensors",
                    "level": -1,
                },
                {
                    "message": "Not started",
                    "hardware_id": "",
                    "values": [],
                    "name": "/Sensors/Ultrasonic sensors/Configuration",
                    "level": -1,
                },
                {
                    "message": "Not started",
                    "hardware_id": "",
                    "values": [],
                    "name": "/Sensors/Ultrasonic sensors/Data",
                    "level": -1,
                },
                {
                    "message": "OK",
                    "hardware_id": "",
                    "values": [
                        {"value": "OK", "key": "Laserscanner (Back)"},
                        {"value": "OK", "key": "3D Camera (Left)"},
                        {"value": "OK", "key": "3D Camera (Right)"},
                        {"value": "OK", "key": "Laserscanner (Front)"},
                        {"value": "OK", "key": "IMU"},
                        {"value": "Not started", "key": "Ultrasonic sensors"},
                    ],
                    "name": "/Sensors",
                    "level": 0,
                },
                {
                    "message": "OK",
                    "hardware_id": "",
                    "values": [
                        {
                            "value": "No serial device configured",
                            "key": "/Serial Interface/Communication",
                        }
                    ],
                    "name": "/Serial Interface",
                    "level": 0,
                },
                {
                    "message": "No serial device configured",
                    "hardware_id": "MirSerialInterface",
                    "values": [
                        {"value": "0", "key": "Command count"},
                        {"value": "/dev/ttyUSB", "key": "Port"},
                        {"value": "", "key": "Serial number"},
                        {"value": "19200", "key": "Baudrate"},
                        {"value": "8", "key": "Datasize"},
                        {"value": "0", "key": "Parity"},
                        {"value": "10000", "key": "Response delay [us]"},
                    ],
                    "name": "/Serial Interface/Communication",
                    "level": 0,
                },
            ],
            "header": {
                "stamp": {"secs": 1702921663, "nsecs": 210045582},
                "frame_id": "",
                "seq": 258453,
            },
        },
        "op": "publish",
    }
