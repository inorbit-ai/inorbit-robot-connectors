# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
import pytz
from datetime import datetime
from unittest.mock import MagicMock, Mock, AsyncMock
from inorbit_edge.robot import RobotSession
from inorbit_mir_connector.src.mir_api import MirApiV2
from inorbit_mir_connector.src.mission_tracking import MirInorbitMissionTracking
from deepdiff import DeepDiff


@pytest.fixture
def mission_tracking():
    mission_tracking = MirInorbitMissionTracking(
        mir_api=MagicMock(autospec=MirApiV2),
        inorbit_sess=MagicMock(autospec=RobotSession),
        robot_tz_info=pytz.timezone("UTC"),
        enable_io_mission_tracking=True,
    )
    mission_tracking.inorbit_sess.missions_module.executor.wait_until_idle = Mock(
        return_value=True
    )
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
    mission_tracking.get_current_mission = AsyncMock(
        return_value=sample_mir_mission_data
    )

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
    mission_tracking.get_current_mission = AsyncMock(
        return_value=sample_mir_mission_data
    )
    await mission_tracking.report_mission(sample_status_data, sample_metrics_data)
    reported_mission = (
        mission_tracking.inorbit_sess.publish_key_values.call_args.kwargs["key_values"]
    )

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
    mission_tracking.get_current_mission = AsyncMock(
        return_value=sample_mir_mission_data
    )

    # Should be enabled
    await mission_tracking.report_mission(sample_status_data, sample_metrics_data)
    assert len(mission_tracking.get_current_mission.call_args_list) == 1
    assert len(mission_tracking.inorbit_sess.publish_key_values.call_args_list) == 1

    # Disable InOrbit Mission Tracking
    mission_tracking.enable_io_mission_tracking = False
    await mission_tracking.report_mission(sample_status_data, sample_metrics_data)
    assert len(mission_tracking.get_current_mission.call_args_list) == 2
    assert len(mission_tracking.inorbit_sess.publish_key_values.call_args_list) == 1


class TestSafeLocalizeTimestamp:
    """Test suite for the _safe_localize_timestamp function."""

    @pytest.fixture
    def pst_mission_tracking(self):
        """Mission tracking with PST timezone."""
        return MirInorbitMissionTracking(
            mir_api=MagicMock(autospec=MirApiV2),
            inorbit_sess=MagicMock(autospec=RobotSession),
            robot_tz_info=pytz.timezone("America/Los_Angeles"),
            enable_io_mission_tracking=True,
        )

    def test_timestamp_without_timezone_info(self, pst_mission_tracking):
        """Test handling of timestamp without timezone (applies robot timezone)."""
        # ISO timestamp without timezone info
        timestamp_str = "2023-12-07T15:07:51"
        result = pst_mission_tracking._safe_localize_timestamp(timestamp_str)

        # Should apply PST timezone and convert to Unix timestamp
        expected_dt = pytz.timezone("America/Los_Angeles").localize(
            datetime.fromisoformat(timestamp_str)
        )
        expected = expected_dt.timestamp()

        assert result == expected

    def test_timestamp_with_timezone_info(self, pst_mission_tracking):
        """Test handling of timestamp with timezone info (uses existing timezone)."""
        # ISO timestamp with UTC timezone
        timestamp_str = "2023-12-07T23:07:51+00:00"
        result = pst_mission_tracking._safe_localize_timestamp(timestamp_str)

        # Should use the provided timezone directly
        expected_dt = datetime.fromisoformat(timestamp_str)
        expected = expected_dt.timestamp()

        assert result == expected

    def test_timestamp_with_different_timezone(self, pst_mission_tracking):
        """Test timestamp with non-UTC timezone."""
        # ISO timestamp with Eastern timezone
        timestamp_str = "2023-12-07T18:07:51-05:00"
        result = pst_mission_tracking._safe_localize_timestamp(timestamp_str)

        # Should use the provided timezone directly
        expected_dt = datetime.fromisoformat(timestamp_str)
        expected = expected_dt.timestamp()

        assert result == expected

    def test_utc_mission_tracking(self):
        """Test with UTC robot timezone."""
        utc_mission_tracking = MirInorbitMissionTracking(
            mir_api=MagicMock(autospec=MirApiV2),
            inorbit_sess=MagicMock(autospec=RobotSession),
            robot_tz_info=pytz.timezone("UTC"),
            enable_io_mission_tracking=True,
        )

        # Timestamp without timezone should get UTC applied
        timestamp_str = "2023-12-07T23:07:51"
        result = utc_mission_tracking._safe_localize_timestamp(timestamp_str)

        expected_dt = pytz.timezone("UTC").localize(
            datetime.fromisoformat(timestamp_str)
        )
        expected = expected_dt.timestamp()

        assert result == expected

    def test_invalid_timestamp_fallback(self, pst_mission_tracking):
        """Test fallback behavior for invalid timestamp strings."""
        # Invalid ISO format
        invalid_timestamp = "not-a-valid-timestamp"

        # Should return current time (approximately)
        before_call = datetime.now().timestamp()
        result = pst_mission_tracking._safe_localize_timestamp(invalid_timestamp)
        after_call = datetime.now().timestamp()

        # Result should be between before and after call times (within 1 second)
        assert before_call <= result <= after_call + 1

    def test_empty_string_fallback(self, pst_mission_tracking):
        """Test fallback behavior for empty string."""
        # Empty string
        result = pst_mission_tracking._safe_localize_timestamp("")

        # Should return current time (approximately)
        current_time = datetime.now().timestamp()
        assert abs(result - current_time) < 1  # Within 1 second

    def test_microseconds_handling(self, pst_mission_tracking):
        """Test handling of timestamps with microseconds."""
        # ISO timestamp with microseconds and no timezone
        timestamp_str = "2023-12-07T15:07:51.123456"
        result = pst_mission_tracking._safe_localize_timestamp(timestamp_str)

        expected_dt = pytz.timezone("America/Los_Angeles").localize(
            datetime.fromisoformat(timestamp_str)
        )
        expected = expected_dt.timestamp()

        assert result == expected

    def test_microseconds_with_timezone(self, pst_mission_tracking):
        """Test handling of timestamps with microseconds and timezone."""
        # ISO timestamp with microseconds and timezone
        timestamp_str = "2023-12-07T23:07:51.123456+00:00"
        result = pst_mission_tracking._safe_localize_timestamp(timestamp_str)

        expected_dt = datetime.fromisoformat(timestamp_str)
        expected = expected_dt.timestamp()

        assert result == expected
