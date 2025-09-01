# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
import pytz
from unittest.mock import MagicMock, Mock, AsyncMock
from inorbit_edge.robot import RobotSession
from inorbit_mir_connector.src.mir_api import MirApiV2
from mir_connector.inorbit_mir_connector.src.mission_tracking import MirInorbitMissionTracking
from deepdiff import DeepDiff


@pytest.fixture
def mission_tracking():
    mission_tracking = MirInorbitMissionTracking(
        mir_api=MagicMock(autospec=MirApiV2),
        inorbit_sess=MagicMock(autospec=RobotSession),
        robot_tz_info=pytz.timezone("UTC"),
        enable_io_mission_tracking=True,
    )
    mission_tracking.inorbit_sess.missions_module.executor.wait_until_idle = Mock(return_value=True)
    return mission_tracking


@pytest.mark.asyncio
async def test_get_current_mission(mission_tracking):
    # Only missions with "Executing" state should be stored in executing_mission_id
    assert mission_tracking.executing_mission_id is None
    dummy_data = {"state": "Executing"}
    id = 1
    mission_tracking.mir_api.get_executing_mission_id = AsyncMock(return_value=id)
    mission_tracking.mir_api.get_mission = AsyncMock(return_value=dummy_data)
    assert await mission_tracking.get_current_mission() == dummy_data
    assert mission_tracking.executing_mission_id == 1

    dummy_data = {"state": "Completed"}
    mission_tracking.mir_api.get_mission = AsyncMock(return_value=dummy_data)
    assert await mission_tracking.get_current_mission() == dummy_data
    assert mission_tracking.executing_mission_id is None


@pytest.mark.asyncio
async def test_toggle_mir_tracking(
    mission_tracking, sample_metrics_data, sample_status_data, sample_mir_mission_data
):
    mission_tracking.get_current_mission = AsyncMock(return_value=sample_mir_mission_data)

    # MiR tracking should be disabled
    assert mission_tracking.mir_mission_tracking_enabled is False
    await mission_tracking.report_mission(sample_status_data, sample_metrics_data)
    assert len(mission_tracking.get_current_mission.call_args_list) == 0

    # Enable tracking. This is ussually set by the connector
    mission_tracking.mir_mission_tracking_enabled = True
    await mission_tracking.report_mission(sample_status_data, sample_metrics_data)
    assert len(mission_tracking.get_current_mission.call_args_list) == 1


@pytest.mark.asyncio
async def test_report_mission(
    mission_tracking, sample_metrics_data, sample_status_data, sample_mir_mission_data
):
    mission_tracking.mir_mission_tracking_enabled = True
    mission_tracking.io_mission_tracking_enabled = True
    mission_tracking.get_current_mission = AsyncMock(return_value=sample_mir_mission_data)
    await mission_tracking.report_mission(sample_status_data, sample_metrics_data)
    reported_mission = mission_tracking.inorbit_sess.publish_key_values.call_args.kwargs[
        "key_values"
    ]

    assert len(mission_tracking.inorbit_sess.publish_key_values.call_args_list) == 1

    should_be = {
        "mission_tracking": {
            "missionId": 14026,
            "inProgress": True,
            "state": "Executing",
            "label": "Charge",
            "startTs": 1701946471000.0,
            "data": {
                "Total Distance (m)": 671648.3914381799,
                "Mission Steps": 1,
                "Total Missions": 14026,
                "Robot Model": "MiR100",
                "Uptime (s)": 3552693,
                "Serial Number": "200100005001715",
                "Battery Time Remaning (s)": 89725,
                "WiFi RSSI (dbm)": -46.0,
            },
            "completedPercent": 1.0,
        }
    }

    assert DeepDiff(reported_mission, should_be) == {}


@pytest.mark.asyncio
async def test_toggle_inorbit_tracking(
    mission_tracking, sample_metrics_data, sample_status_data, sample_mir_mission_data
):
    # Enable MiR tracking. This is ussually set by the connector
    mission_tracking.mir_mission_tracking_enabled = True
    mission_tracking.get_current_mission = AsyncMock(return_value=sample_mir_mission_data)

    # Should be enabled
    await mission_tracking.report_mission(sample_status_data, sample_metrics_data)
    assert len(mission_tracking.get_current_mission.call_args_list) == 1
    assert len(mission_tracking.inorbit_sess.publish_key_values.call_args_list) == 1

    # Disable InOrbit Mission Tracking
    mission_tracking.enable_io_mission_tracking = False
    await mission_tracking.report_mission(sample_status_data, sample_metrics_data)
    assert len(mission_tracking.get_current_mission.call_args_list) == 2
    assert len(mission_tracking.inorbit_sess.publish_key_values.call_args_list) == 1
