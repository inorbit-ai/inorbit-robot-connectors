import pytest

# Fixtures defined in conftest.py do not require importing


@pytest.fixture(autouse=True)
def disable_network_calls(monkeypatch, requests_mock):
    # Including requests_mock will disable network calls on every test
    pass


@pytest.fixture
def firmware_version_info():
    # Sample response from /gs-robot/info endpoint
    return {
        "data": {
            "appVersion": "2.10.16.M",
            "cpuArchitecture": "x86_64",
            "diskAvailable": 11,
            "diskCapacity": 57,
            "hardwareVersion0": "r21.9.9",
            "hardwareVersion1": "t0.4.8",
            "hardwareVersion2": "t0.1.2",
            "hardwareVersion3": "t0.0.1",
            "hardwareVersion4": "r1.3.6",
            "hardwareVersion5": "t0.3.31",
            "hardwareVersion6": "t0.0.0",
            "hardwareVersion7": "r0.2.11",
            "hardwareVersion8": "t1.0.3",
            "laser_serial_number": "f8b5689054ff",
            "mcuType": "PRO800",
            "minAppVersion": "1.9.0",
            "modelType": "Scrubber 50H",
            "productId": "GS101-0100-5AM-5000",
            "routerVersion": "2.3.6",
            "softwareVersion": "GS-ES50-OS1604-PRO800-OTA_V3-6-6",
            "systemVersion": "16.04",
            "version": "GS-ES50-OS1604-PRO800-OTA_V3-6-6",
        },
        "errorCode": "",
        "msg": "successed",
        "successed": True,
    }


@pytest.fixture
def load_map_response():
    # Sample response from /gs-robot/cmd/load_map?map_name=<map_name_here> endpoint
    return {"data": "", "errorCode": "", "msg": "successed", "successed": True}


@pytest.fixture
def localize_robot_response():
    # Sample response from
    # /gs-robot/cmd/initialize?map_name=<map_name_here>&init_point_name=<init_point_here> endpoint
    return {"data": "", "errorCode": "", "msg": "successed", "successed": True}


@pytest.fixture
def current_position_data():
    # Sample response from /gs-robot/real_time_data/position endpoint
    return {
        "angle": -173.41528128678252,
        "gridPosition": {"x": 372, "y": 502},
        "mapInfo": {
            "gridHeight": 992,
            "gridWidth": 992,
            "originX": -24.8,
            "originY": -24.8,
            "resolution": 0.05000000074505806,
        },
        "worldPosition": {
            "orientation": {"w": -0.05743089347363588, "x": 0, "y": 0, "z": 0.9983494841361015},
            "position": {"x": -6.189813393986145, "y": 0.3017086724551712, "z": 0},
        },
    }


@pytest.fixture
def task_queues_data():
    # Sample response from /gs-robot/data/task_queues?map_name=<map_name_here> endpoint
    return {
        "data": [
            {
                "coverage_area": 0,
                "estimate_time": 0.0019930555555555578,
                "last_time": 0,
                "length": 5.7400000000000064,
                "loop": False,
                "loop_count": 0,
                "map_id": "137aafc1-6096-4863-82bc-1e110f8ba5b0",
                "map_name": "rmf_test",
                "modify_time": 1614147616,
                "name": "execute_task_test1",
                "picture_url": "",
                "task_queue_id": "7b6ad8d4-49e1-4aca-bff4-ecc450b52c65",
                "task_queue_type": 0,
                "tasks": [
                    {
                        "name": "PlayPathTask",
                        "start_param": {"map_name": "rmf_test", "path_name": "test1"},
                    }
                ],
                "total_area": 3.3575000000000004,
                "used_count": 0,
            },
            {
                "coverage_area": 0,
                "estimate_time": 3.472222222222222e-10,
                "last_time": 0,
                "length": 9.9999999999999995e-07,
                "loop": False,
                "loop_count": 0,
                "map_id": "137aafc1-6096-4863-82bc-1e110f8ba5b0",
                "map_name": "rmf_test",
                "modify_time": 1614150690,
                "name": "tq2",
                "picture_url": "",
                "task_queue_id": "6dff01f7-7a19-4f2b-8c14-d2014b5154c5",
                "task_queue_type": 0,
                "tasks": [
                    {
                        "name": "NavigationTask",
                        "start_param": {"map_name": "rmf_test", "position_name": "Origin"},
                    }
                ],
                "total_area": 0,
                "used_count": 0,
            },
        ],
        "errorCode": "",
        "msg": "successed",
        "successed": True,
    }


@pytest.fixture
def path_data_list():
    # Sample response from
    # /gs-robot/data/path_data_list?map_name=<map_name_here>&path_name=<path_name_here> endpoint
    return {
        "data": {
            "data": [
                {
                    "gridPosition": [
                        {"x": 304, "y": 163},
                        {"x": 304, "y": 163},
                        {"x": 305, "y": 163},
                    ],
                    "length": 4.000000000000002,
                    "name": "__DEFAULT",
                    "namedPoints": [
                        {
                            "actions": [
                                {
                                    "fields": [
                                        {
                                            "fields": [],
                                            "name": "squeegee_motor",
                                            "type": "bool",
                                            "value": "true",
                                        }
                                    ],
                                    "name": "OperateDevice",
                                },
                                {
                                    "fields": [
                                        {
                                            "fields": [],
                                            "name": "right_fan",
                                            "type": "bool",
                                            "value": "true",
                                        }
                                    ],
                                    "name": "OperateDevice",
                                },
                            ],
                            "angle": 21.44336432097986,
                            "gridPosition": {"x": 266, "y": 177},
                            "index": 0,
                            "name": "__DEFAULT_0",
                            "worldPose": {
                                "orientation": {"w": 0, "x": 0, "y": 0, "z": 0},
                                "position": {"x": 0, "y": 0, "z": 0},
                            },
                        },
                        {
                            "actions": [
                                {
                                    "fields": [
                                        {
                                            "fields": [],
                                            "name": "right_fan",
                                            "type": "bool",
                                            "value": "false",
                                        }
                                    ],
                                    "name": "OperateDevice",
                                }
                            ],
                            "angle": -12.590328716180169,
                            "gridPosition": {"x": 305, "y": 163},
                            "index": 200,
                            "name": "__DEFAULT_1",
                            "worldPose": {
                                "orientation": {"w": 0, "x": 0, "y": 0, "z": 0},
                                "position": {"x": 0, "y": 0, "z": 0},
                            },
                        },
                    ],
                    "pointCount": 201,
                }
            ],
            "mapInfo": {"gridHeight": 288, "gridWidth": 448},
            "map_name": "Blk71",
            "path_name": "tf1",
            "type": 0,
        },
        "errorCode": "",
        "msg": "successed",
        "successed": True,
    }


@pytest.fixture
def start_task_queue_response():
    # Sample response from /gs-robot/cmd/start_task_queue endpoint
    return {"data": "", "errorCode": "", "msg": "successed", "successed": True}


@pytest.fixture
def start_task_queue_request_body():
    # Sample request body for /gs-robot/cmd/start_task_queue endpoint
    return {
        "name": "tq",
        "loop": False,
        "loop_count": 0,
        "map_name": "rmf_test",
        "tasks": [
            {"name": "PlayPathTask", "start_param": {"map_name": "rmf_test", "path_name": "test1"}}
        ],
    }


@pytest.fixture
def pause_task_queue_response():
    # Sample response from /gs-robot/cmd/pause_task_queue endpoint
    return {"data": "", "errorCode": "", "msg": "successed", "successed": True}


@pytest.fixture
def resume_task_queue_response():
    # Sample response from /gs-robot/cmd/resume_task_queue endpoint
    return {"data": "", "errorCode": "", "msg": "successed", "successed": True}


@pytest.fixture
def stop_task_queue_response():
    # Sample response from /gs-robot/cmd/stop_task_queue endpoint
    return {"data": "", "errorCode": "", "msg": "successed", "successed": True}


@pytest.fixture
def is_task_queue_finished_response_ongoing():
    # Sample response from /gs-robot/cmd/is_task_queue_finished endpoint (task ongoing)
    return {"data": "False", "errorCode": "", "msg": "successed", "successed": True}


@pytest.fixture
def is_task_queue_finished_response_completed():
    # Sample response from /gs-robot/cmd/is_task_queue_finished endpoint (task completed)
    return {"data": "True", "errorCode": "", "msg": "successed", "successed": True}


@pytest.fixture
def navigate_to_waypoint_request_body():
    # Sample request body for /gs-robot/cmd/start_task_queue endpoint (navigate to waypoint)
    return {
        "name": "",
        "loop": False,
        "loop_count": 0,
        "map_name": "rmf_test",
        "tasks": [
            {
                "name": "NavigationTask",
                "start_param": {"map_name": "rmf_test", "position_name": "test1"},
            }
        ],
    }


@pytest.fixture
def navigate_to_coordinates_request_body():
    # Sample request body for /gs-robot/cmd/quick/navigate?type=2 endpoint (V3-6-6 and after)
    return {"destination": {"gridPosition": {"x": 122, "y": 201}, "angle": 0.0}}


@pytest.fixture
def navigate_to_coordinates_response():
    # Sample response from /gs-robot/cmd/quick/navigate?type=2 endpoint
    return {"data": "", "errorCode": "", "msg": "successed", "successed": True}


@pytest.fixture
def start_cross_task_response():
    # Sample response from /gs-robot/cmd/start_cross_task endpoint
    return {"data": "", "errorCode": "", "msg": "successed", "successed": True}


@pytest.fixture
def pause_navigate_response():
    # Sample response from /gs-robot/cmd/pause_navigate endpoint (V3-6-6 and after)
    return {"data": "", "errorCode": "", "msg": "successed", "successed": True}


@pytest.fixture
def resume_navigate_response():
    # Sample response from /gs-robot/cmd/resume_navigate endpoint (V3-6-6 and after)
    return {"data": "", "errorCode": "", "msg": "successed", "successed": True}


@pytest.fixture
def cancel_navigate_response():
    # Sample response from /gs-robot/cmd/cancel_navigate endpoint (V3-6-6 and after)
    return {"data": "", "errorCode": "", "msg": "successed", "successed": True}


@pytest.fixture
def is_cross_task_finished_response_ongoing():
    # Sample response from /gs-robot/cmd/is_cross_task_finished endpoint (task ongoing)
    return {"data": "false", "errorCode": "", "msg": "successed", "successed": True}


@pytest.fixture
def is_cross_task_finished_response_completed():
    # Sample response from /gs-robot/cmd/is_cross_task_finished endpoint (task completed)
    return {"data": "true", "errorCode": "", "msg": "successed", "successed": True}


@pytest.fixture
def set_cleaning_mode_response():
    # Sample response from /gs-robot/cmd/set_cleaning_mode?cleaning_mode=<mode_name here> endpoint
    return {"data": "", "errorCode": "", "msg": "successed", "successed": True}


@pytest.fixture
def device_status_data():
    # Sample response from /gs-robot/data/device_status endpoint
    return {
        "data": {
            "battery": 45.435484000000002,
            "batteryVoltage": 21.815000000000001,
            "charge": False,
            "dewaterValve": False,
            "drivingMotor": True,
            "fanMotor": False,
            "leftMotor": False,
            "leftWaterValve": False,
            "purificationMotor": False,
            "rightMotor": False,
            "rightWaterValve": False,
            "suctionMotor": False,
            "waterLevelMax": True,
            "waterLevelMin": False,
            "waterMotor": False,
        },
        "errorCode": "",
        "msg": "successed",
        "successed": True,
    }


@pytest.fixture
def initialize_customized_request_body():
    # Sample request body for /gs-robot/cmd/initialize_customized endpoint
    return {"mapName": "demo", "point": {"angle": 180, "gridPosition": {"x": 100, "y": 200}}}


@pytest.fixture
def initialize_customized_response():
    # Sample response from /gs-robot/cmd/initialize_customized endpoint
    return {"data": "", "errorCode": "", "msg": "successed", "successed": True}
