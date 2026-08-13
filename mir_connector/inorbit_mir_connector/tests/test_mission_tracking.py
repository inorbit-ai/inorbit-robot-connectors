# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
import pytz
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock
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
        mission_executor=MagicMock(),
    )
    # No InOrbit-dispatched mission active by default.
    mission_tracking.mission_executor.has_active_mission = AsyncMock(return_value=False)
    return mission_tracking


@pytest.mark.asyncio
async def test_get_current_mission(mission_tracking):
    assert mission_tracking.executing_mission_id is None
    entry = {"state": "Executing", "id": 1, "mission_id": "def-guid", "finished": None}
    definition = {"guid": "def-guid", "name": "Charge"}
    def_actions = [
        {"guid": "a1", "action_type": "charging", "parameters": [], "mission_id": "def-guid"}
    ]
    mission_tracking.mir_api.get_executing_mission_id = AsyncMock(return_value=1)
    mission_tracking.mir_api.get_mission_queue_entry = AsyncMock(return_value=dict(entry))
    mission_tracking.mir_api.get_mission_definition = AsyncMock(return_value=dict(definition))
    mission_tracking.mir_api.get_mission_actions = AsyncMock(return_value=def_actions)
    mission_tracking.mir_api.get_action_definitions = AsyncMock(
        return_value=[{"action_type": "charging", "name": "Charging"}]
    )

    mission = await mission_tracking.get_current_mission()
    assert mission["id"] == 1
    assert mission["definition"]["name"] == "Charge"
    assert mission["definition"]["actions"] == def_actions
    assert mission_tracking.executing_mission_id == 1
    assert mission_tracking._tasks_tracker is not None

    # The definition is cached per queue entry: a second tick refetches only the entry.
    await mission_tracking.get_current_mission()
    assert mission_tracking.mir_api.get_mission_definition.await_count == 1
    assert mission_tracking.mir_api.get_mission_actions.await_count == 1
    assert mission_tracking.mir_api.get_mission_queue_entry.await_count == 2

    # A non-executing state clears executing_mission_id but still returns the mission
    # (the just-finished mission is reported exactly once).
    mission_tracking.mir_api.get_mission_queue_entry = AsyncMock(
        return_value={**entry, "state": "Done", "finished": "2026-08-10T10:00:00"}
    )
    mission = await mission_tracking.get_current_mission()
    assert mission["state"] == "Done"
    assert mission_tracking.executing_mission_id is None

    # With no next executing mission, the next tick returns None and drops the tracker.
    mission_tracking.mir_api.get_executing_mission_id = AsyncMock(return_value=None)
    assert await mission_tracking.get_current_mission() is None
    assert mission_tracking._tasks_tracker is None


@pytest.mark.asyncio
async def test_executing_mission_id_comes_from_status(mission_tracking):
    """/status already carries mission_queue_id and is already fetched every tick.

    The queue endpoint is unbounded (2 MB on a robot with history) and polling it once a
    second cannot keep up, so it is only a fallback for when the field is absent.
    """
    mission_tracking.mir_api.get_executing_mission_id = AsyncMock(side_effect=AssertionError)
    assert await mission_tracking._find_executing_mission_id({"mission_queue_id": 7}) == 7
    # Idle robot: the field is present and null, which is an answer, not a gap.
    assert await mission_tracking._find_executing_mission_id({"mission_queue_id": None}) is None

    mission_tracking.mir_api.get_executing_mission_id = AsyncMock(return_value=9)
    assert await mission_tracking._find_executing_mission_id({}) == 9
    assert await mission_tracking._find_executing_mission_id(None) == 9


@pytest.mark.asyncio
async def test_finished_mission_is_not_readopted(mission_tracking):
    # mission_queue_id clears when the mission ends, but if a firmware left it set we would
    # re-adopt the finished entry and republish it on every tick.
    entry = {
        "state": "Done",
        "id": 5,
        "mission_id": None,
        "started": "2026-08-10T10:00:00",
        "finished": "2026-08-10T10:01:00",
    }
    mission_tracking.mir_api.get_mission_queue_entry = AsyncMock(return_value=dict(entry))
    status = {"mission_queue_id": 5}

    assert (await mission_tracking.get_current_mission(status))["id"] == 5
    assert mission_tracking.executing_mission_id is None
    assert await mission_tracking.get_current_mission(status) is None


@pytest.mark.asyncio
async def test_fleet_action_list_without_mission_id(
    mission_tracking, sample_metrics_data, sample_status_data
):
    """Fleet-dispatched ActionLists have mission_id None: no definition, no tasks, no crash.

    GET /missions/None is a 400, which used to raise out of every tick without ever clearing
    executing_mission_id, wedging mission tracking for the life of the process.
    """
    status = {**sample_status_data, "mission_queue_id": 42}
    mission_tracking.mir_api.get_executing_mission_id = AsyncMock(side_effect=AssertionError)
    mission_tracking.mir_api.get_mission_queue_entry = AsyncMock(
        return_value={
            "state": "Executing",
            "id": 42,
            "mission_id": None,
            "started": "2026-08-10T10:00:00",
            "finished": None,
        }
    )
    mission_tracking.mir_api.get_mission_definition = AsyncMock(side_effect=AssertionError)
    mission_tracking.mir_api.get_mission_actions = AsyncMock(side_effect=AssertionError)

    await mission_tracking.report_mission(status, sample_metrics_data)

    reported = mission_tracking.inorbit_sess.publish_key_values.call_args.kwargs["key_values"][
        "mission_tracking"
    ]
    assert reported["missionId"] == 42
    assert reported["inProgress"] is True
    # Definition-derived fields are absent rather than fabricated.
    assert "label" not in reported
    assert "tasks" not in reported
    assert "Mission Steps" not in reported["data"]
    assert mission_tracking._tasks_tracker is None

    # The next tick still tracks the same entry and still does not fetch a definition.
    await mission_tracking.report_mission(status, sample_metrics_data)
    assert mission_tracking.executing_mission_id == 42


@pytest.mark.asyncio
async def test_skips_reporting_while_edge_executor_busy(
    mission_tracking, sample_metrics_data, sample_status_data, sample_mir_mission_data
):
    mission_tracking.get_current_mission = AsyncMock(return_value=sample_mir_mission_data)

    # No InOrbit-dispatched mission active — robot-side tracking should publish.
    mission_tracking.mission_executor.has_active_mission = AsyncMock(return_value=False)
    await mission_tracking.report_mission(sample_status_data, sample_metrics_data)
    assert len(mission_tracking.get_current_mission.call_args_list) == 1
    assert len(mission_tracking.inorbit_sess.publish_key_values.call_args_list) == 1
    mission_tracking.get_current_mission.reset_mock()
    mission_tracking.inorbit_sess.publish_key_values.reset_mock()

    # An InOrbit-dispatched mission is running in the edge executor — tracker must stay silent.
    mission_tracking.mission_executor.has_active_mission = AsyncMock(return_value=True)
    await mission_tracking.report_mission(sample_status_data, sample_metrics_data)
    assert len(mission_tracking.get_current_mission.call_args_list) == 0
    assert len(mission_tracking.inorbit_sess.publish_key_values.call_args_list) == 0


@pytest.mark.asyncio
async def test_report_mission(
    mission_tracking, sample_metrics_data, sample_status_data, sample_mir_mission_data
):
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
            "status": "OK",
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
        }
    }

    # get_current_mission is mocked out, so no task tracker exists and there is no progress
    # to report. Omitting completedPercent is the point: the previous count-based estimate
    # read the queue entry's "actions", which is a URL string, and always yielded 1.0.
    assert DeepDiff(reported_mission, should_be) == {}


class TestSafeLocalizeTimestamp:
    """Test suite for the _safe_localize_timestamp function."""

    @pytest.fixture
    def pst_mission_tracking(self):
        """Mission tracking with PST timezone."""
        return MirInorbitMissionTracking(
            mir_api=MagicMock(autospec=MirApiV2),
            inorbit_sess=MagicMock(autospec=RobotSession),
            robot_tz_info=pytz.timezone("America/Los_Angeles"),
            mission_executor=MagicMock(),
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
            mission_executor=MagicMock(),
        )

        # Timestamp without timezone should get UTC applied
        timestamp_str = "2023-12-07T23:07:51"
        result = utc_mission_tracking._safe_localize_timestamp(timestamp_str)

        expected_dt = pytz.timezone("UTC").localize(datetime.fromisoformat(timestamp_str))
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
