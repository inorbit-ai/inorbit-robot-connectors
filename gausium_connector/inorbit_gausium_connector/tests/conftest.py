# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
import warnings

# Fixtures defined in conftest.py do not require importing


@pytest.fixture(autouse=True)
def disable_network_calls(monkeypatch, requests_mock):
    # Including requests_mock will disable network calls on every test
    pass


@pytest.fixture(autouse=True)
def suppress_pydantic_warnings():
    """Suppress pydantic serialization warnings during tests.

    This fixture runs automatically for all tests and suppresses the UserWarnings
    that Pydantic generates when serializing HttpUrl objects.
    """
    # Filter the specific Pydantic serialization warnings
    warnings.filterwarnings("ignore", message="Pydantic serializer warnings", category=UserWarning)
    yield
    # Reset the filter after the test (optional - helps keep the warning filter clean)
    warnings.resetwarnings()


@pytest.fixture
def robot_info():
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
            "acceleratorStatus": False,
            "activeCleaningType": 0,
            "autoMode": True,
            "battery": 100.0,
            "batteryAlarm": 0,
            "batteryCellNumber": 16,
            "batteryCurrent": 12.063000000000001,
            "batteryHalfVoltage": 27477,
            "batteryVoltage": 27.699999999999999,
            "blanceState": 0,
            "brakerDown": False,
            "brushDown": True,
            "brushLiftMotorCurrent": 0,
            "brushMotor": True,
            "brushMotorCurrent": 1,
            "brushMotorWorking": True,
            "brushPositionLevel": 2,
            "brushPressureLevel": 0,
            "brushSpinLevel": 0,
            "brushUsage": 41.723466000000002,
            "brushUsageAlert": 20.0,
            "capFull": 400,
            "capNow": 399,
            "charge": False,
            "chargeCurrent": 0,
            "chargeNum": 1020,
            "charger": 0,
            "chargerCurrent": 0.0,
            "chargerPileStatus": 2,
            "chargerStatus": False,
            "chargerVoltage": 0.0,
            "cleaningMode": "__地毯清洁",
            "cleaningModeId": "52a3d553a5804f408fdde8e18dd0b277",
            "cleaningModeName": "__地毯清洁",
            "cleaningWorking": True,
            "clothBrushUsage": 0.0,
            "clothBrushUsageAlert": 20.0,
            "cloudNetworkStatus": "online",
            "cronJob": True,
            "currentCleaningType": 0,
            "currentCleaningWidth": 0.40000000000000002,
            "currentMapID": "9993b3a8-aadb-46e0-9b66-980cf6be5b95",
            "currentMapName": "T2B1",
            "detailedBatteryCellTemperature0": 39,
            "detailedBatteryCellTemperature1": 39,
            "detailedBatteryCellVoltage0": 0,
            "detailedBatteryCellVoltage1": 0,
            "detailedBatteryCellVoltage10": 3406,
            "detailedBatteryCellVoltage11": 0,
            "detailedBatteryCellVoltage12": 0,
            "detailedBatteryCellVoltage13": 0,
            "detailedBatteryCellVoltage14": 0,
            "detailedBatteryCellVoltage15": 0,
            "detailedBatteryCellVoltage2": 0,
            "detailedBatteryCellVoltage3": 3440,
            "detailedBatteryCellVoltage4": 3435,
            "detailedBatteryCellVoltage5": 3438,
            "detailedBatteryCellVoltage6": 3435,
            "detailedBatteryCellVoltage7": 3438,
            "detailedBatteryCellVoltage8": 3443,
            "detailedBatteryCellVoltage9": 3442,
            "detailedBatteryVoltageAdc": 271,
            "detailedChargerCurrentAdc": 0,
            "detailedChargerVoltageAdc": 0,
            "detailedCountsLeft": 20784,
            "detailedCountsRight": 34911,
            "detailedDeltaCountsLeft": 8832,
            "detailedDeltaCountsRight": 8720,
            "detailedDi": 0,
            "detailedDo": 0,
            "detailedLeftMotorLoad": 130,
            "detailedMcuErrorCode13": 16,
            "detailedMcuErrorCode14": 0,
            "detailedMcuErrorCode15": 0,
            "detailedMcuErrorCode16": 0,
            "detailedMcuErrorCode17": 1572864,
            "detailedMcuErrorCode18": 0,
            "detailedMcuErrorCode19": 0,
            "detailedMcuErrorCode24": -1073741824,
            "detailedMcuErrorCode26": 0,
            "detailedMcuErrorCode27": 512,
            "detailedPitch": 0,
            "detailedProtectorStatus": 0,
            "detailedRelay": 86,
            "detailedRightMotorLoad": 84,
            "detailedRoll": 0,
            "detailedYaw": 2591,
            "discahrgeCurrent": 12063,
            "dischargeNum": 1020,
            "dnMotorDeviceTemperature": 36,
            "dustPushCleanSpinLevel": 3,
            "dustPushSpinLevel": 3,
            "dustPushUsage": 0.0,
            "dustPushUsageAlert": 20.0,
            "emergency": False,
            "emergencyStop": False,
            "emergencyStopAutoResume": False,
            "expectCleaningType": 0,
            "fanLevel": 1,
            "filterUsage": 0.0,
            "filterUsageAlert": 20.0,
            "flushWater": False,
            "imuResetStatus": False,
            "laborSaving": 0,
            "laborSavingOverSpeed": False,
            "leftMotorCurrent": 33,
            "leftMotorTemperature": 32,
            "leftSideBrushUsage": 0.012683,
            "leftSideBrushUsageAlert": 200.0,
            "locationNeedConfirm": False,
            "locationStatus": True,
            "lockTime": 30,
            "maintainBrushSqueegee": False,
            "mileage": 1361.692832,
            "mileageLeft": 1399.347628,
            "mileageRight": 1372.9397799999999,
            "mobileAvailable": True,
            "mobileNetworkAvailable": True,
            "mobileSpeed": 13132,
            "mobileSpeedRx": 3997,
            "mobileSpeedTx": 9135,
            "mobileStatus": True,
            "modeButton": False,
            "motorMode": 0,
            "navigationSpeedLevel": 0,
            "neededSupplyItems": 1,
            "networkSignalType": 7,
            "ordinaryDustPushUsage": 0.0052779999999999997,
            "ordinaryDustPushUsageAlert": 200.0,
            "playPathSpeedLevel": 0,
            "realWaterUsage": 0.0,
            "remainingTime": 333.33333299999998,
            "rightMotorCurrent": 21,
            "rightMotorTemperature": 29,
            "rightSideBrushUsage": 0.012500000000000001,
            "rightSideBrushUsageAlert": 200.0,
            "rollerSqueegeeUsage": 0.0,
            "rollerSqueegeeUsageAlert": 20.0,
            "rollingBrushUsage": 265.15856100000002,
            "rollingBrushUsageAlert": 200.0,
            "routeType": 1,
            "sideBrushMotor": False,
            "sideBrushPositionLevel": 0,
            "sideBrushSpinFeedback": 0,
            "sideBrushSpinLevel": 0,
            "sleepMode": False,
            "softSqueegeeUsage": 0.0,
            "softSqueegeeUsageAlert": 20.0,
            "speed": 0.62168885750031544,
            "speedLevel": 1,
            "squeegeeDown": False,
            "squeegeeLiftMotorCurrent": 0,
            "squeegeeMotor": True,
            "statusUpdatedAt": 1741877817,
            "suctionCleaningMode": False,
            "temperatureNum": 2,
            "totalMileage": 4035326.4766994589,
            "uptime": 9116.0,
            "vacuumMotorCurrent": 12,
            "waterUsage": 0.0,
            "wifiAvailable": True,
            "wifiConnect": False,
            "wifiNetworkAvailable": False,
            "wifiSpeed": 0,
            "wifiSpeedRx": 0,
            "wifiSpeedTx": 0,
            "wifiStatus": True,
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


@pytest.fixture
def robot_status_data():
    # Sample response from /gs-robot/real_time_data/robot_status endpoint
    return {
        "data": {
            "robotStatus": {
                "map": {
                    "DIYPngName": "",
                    "beautyPngFileName": "",
                    "createdAt": "2022-10-05 10:53:14",
                    "customAreasFileName": "custom_area.json",
                    "dataFileName": "map.data",
                    "extendDataFileName": "map.exdata",
                    "heatPngFileName": "",
                    "id": "9993b3a8-aadb-46e0-9b66-980cf6be5b95",
                    "lethalPngName": "lethal.png",
                    "mapInfo": {
                        "gridHeight": 2112,
                        "gridWidth": 6592,
                        "originX": -87.25,
                        "originY": -87.450000000000003,
                        "resolution": 0.05000000074505806,
                    },
                    "md5": "08d548bda1da0ea213176badad49ed1d",
                    "name": "T2B1",
                    "obstacleFileName": "map.obstacle",
                    "pgmFileName": "map.pgm",
                    "pngFileName": "map.png",
                    "updatedAt": 1742293152,
                    "yamlFileName": "map.yaml",
                },
                "workType": "IDLE",
                "workTypeId": 10,
            },
            "statusData": {},
        },
        "errorCode": "",
        "msg": "successed",
        "successed": True,
    }
