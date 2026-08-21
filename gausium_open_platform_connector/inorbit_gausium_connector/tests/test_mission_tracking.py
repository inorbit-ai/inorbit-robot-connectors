# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import asyncio
from copy import deepcopy
from time import time
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from inorbit_gausium_connector.src.mission import filter_none
from inorbit_gausium_connector.src.mission import InOrbitMissionStatus
from inorbit_gausium_connector.src.mission import MissionState
from inorbit_gausium_connector.src.mission import MissionTracking
from inorbit_gausium_connector.src.robot import RobotAPI
from inorbit_gausium_connector.src.robot import TaskState


@pytest.fixture
def mock_robot_api():
    """Create a mock RobotAPI for testing."""
    api = MagicMock(spec=RobotAPI)
    api.get_task_reports_v2 = AsyncMock()
    return api


@pytest.fixture
def mock_publish_callback():
    """Create a mock publish callback."""
    return Mock()


@pytest.fixture
def mission_tracking(mock_robot_api, mock_publish_callback):
    """Create a MissionTracking instance for testing."""
    return MissionTracking(mock_robot_api, mock_publish_callback)


@pytest.fixture
def sample_robot_status():
    """Sample robot status data with an executing task."""
    return {
        "executingTask": {
            "id": "task-123",
            "name": "Cleaning Task",
            "progress": 50,
            "timeRemaining": 300,
            "cleaningMileage": 100.5,
        },
        "taskState": TaskState.RUNNING.value,
        "emergencyStop": {"enabled": False},
        "localizationInfo": {
            "map": {"name": "Floor 1", "id": "map-1"},
            "mapPosition": {"x": 10.0, "y": 20.0, "angle": 90.0},
        },
    }


@pytest.fixture
def sample_robot_status_v2():
    """Sample robot status v2 data with current task information."""
    return {
        "currentTask": {
            "taskInstanceId": "task-123",
        },
    }


@pytest.fixture
def sample_task_report():
    """Sample task report data."""
    return {
        "id": "9ef6801e-457f-45e5-bfce-46a44db05e4e",
        "name": "robots/robotsn/taskReports/9ef6801e-457f-45e5-bfce-46a44db05e4e",
        "map": "Spine",
        "displayName": "clean areas 1 and 2",
        "robot": "Panchita",
        "robotSerialNumber": "robotsn",
        "operator": "user",
        "completionPercentage": 0.917,
        "durationSeconds": 8915,
        "areaNameList": "area1、area2",
        "plannedCleaningAreaSquareMeter": 967.26,
        "actualCleaningAreaSquareMeter": 886.918,
        "efficiencySquareMeterPerHour": 358.15,
        "plannedPolishingAreaSquareMeter": 0,
        "actualPolishingAreaSquareMeter": 0,
        "waterConsumptionLiter": 0,
        "startBatteryPercentage": 99,
        "endBatteryPercentage": 49,
        "consumablesResidualPercentage": {
            "brush": 100,
            "filter": 100,
            "suctionBlade": 99.86,
        },
        "taskInstanceId": "task-123",
        "cleaningMode": "洗地",
        "taskReportPngUri": (
            "https://bot.gs-robot.com/robot-task/task/report/png/v2/en/"
            "9ef6801e-457f-45e5-bfce-46a44db05e4e"
        ),
        "startTime": "2025-06-26T03:53:27Z",
        "endTime": "2025-06-26T06:36:50Z",
    }


class TestMissionTracking:
    """Test cases for MissionTracking class."""

    def test_initialization(self, mock_robot_api, mock_publish_callback):
        """Test MissionTracking initialization."""
        mission_tracking = MissionTracking(mock_robot_api, mock_publish_callback)

        assert mission_tracking._robot_api is mock_robot_api
        assert mission_tracking._publish_callback is mock_publish_callback
        assert mission_tracking._last_robot_status == {}
        assert mission_tracking._last_inorbit_report == {}
        assert mission_tracking._mission_completion_tasks == set()
        assert not mission_tracking._shutdown_event.is_set()

    def test_update_new_mission_starts(
        self, mission_tracking, sample_robot_status, sample_robot_status_v2, mock_publish_callback
    ):
        """Test updating when a new mission starts."""
        # First update with no previous mission
        mission_tracking.update(sample_robot_status, sample_robot_status_v2)

        # Should publish the mission status
        mock_publish_callback.assert_called_once()
        published_report = mock_publish_callback.call_args[0][0]

        assert published_report["missionId"] == "task-123"
        assert published_report["status"] == InOrbitMissionStatus.ok.value
        assert published_report["state"] == MissionState.in_progress.value["state"]
        assert published_report["inProgress"] == MissionState.in_progress.value["inProgress"]
        assert published_report["label"] == "Cleaning Task"
        assert published_report["completedPercent"] == 0.5
        assert published_report["data"]["task_id"] == "task-123"

    def test_update_mission_progress(
        self, mission_tracking, sample_robot_status, sample_robot_status_v2, mock_publish_callback
    ):
        """Test updating mission progress."""
        # Start with initial mission
        mission_tracking.update(sample_robot_status, sample_robot_status_v2)
        mock_publish_callback.reset_mock()

        # Update progress
        updated_status = deepcopy(sample_robot_status)
        updated_status["executingTask"]["progress"] = 75
        updated_status["executingTask"]["timeRemaining"] = 200

        mission_tracking.update(updated_status, sample_robot_status_v2)

        # Should publish updated progress
        mock_publish_callback.assert_called_once()
        published_report = mock_publish_callback.call_args[0][0]
        assert published_report["completedPercent"] == 0.75

    @pytest.mark.asyncio
    async def test_update_mission_completion_triggers_background_task(
        self, mission_tracking, sample_robot_status, sample_robot_status_v2, mock_publish_callback
    ):
        """Test that mission completion triggers a background task."""
        # Start with initial mission
        mission_tracking.update(sample_robot_status, sample_robot_status_v2)
        mock_publish_callback.reset_mock()

        # Change to different mission (completing the first one)
        new_status = deepcopy(sample_robot_status)
        new_status["executingTask"]["id"] = "task-456"
        new_status_v2 = deepcopy(sample_robot_status_v2)
        new_status_v2["currentTask"]["taskInstanceId"] = "task-456"

        mission_tracking.update(new_status, new_status_v2)

        # Should have created a completion task
        assert len(mission_tracking._mission_completion_tasks) == 1

        # Clean up the task to avoid warnings
        for task in mission_tracking._mission_completion_tasks:
            task.cancel()
        await asyncio.gather(*mission_tracking._mission_completion_tasks, return_exceptions=True)

    def test_update_no_change_no_publish(
        self, mission_tracking, sample_robot_status, sample_robot_status_v2, mock_publish_callback
    ):
        """Test that no change in mission doesn't trigger publish."""
        # First update
        mission_tracking.update(sample_robot_status, sample_robot_status_v2)
        mock_publish_callback.reset_mock()

        # Same update again
        mission_tracking.update(sample_robot_status, sample_robot_status_v2)

        # Should not publish again
        mock_publish_callback.assert_not_called()

    def test_update_mission_with_emergency_stop(
        self, mission_tracking, sample_robot_status, sample_robot_status_v2, mock_publish_callback
    ):
        """Test mission update with emergency stop enabled."""
        emergency_status = deepcopy(sample_robot_status)
        emergency_status["emergencyStop"]["enabled"] = True

        mission_tracking.update(emergency_status, sample_robot_status_v2)

        published_report = mock_publish_callback.call_args[0][0]
        assert published_report["status"] == MissionState.paused.value["status"]
        assert published_report["state"] == MissionState.paused.value["state"]

    def test_update_mission_with_paused_state(
        self, mission_tracking, sample_robot_status, sample_robot_status_v2, mock_publish_callback
    ):
        """Test mission update with paused task state."""
        paused_status = deepcopy(sample_robot_status)
        paused_status["taskState"] = TaskState.PAUSED.value

        mission_tracking.update(paused_status, sample_robot_status_v2)

        published_report = mock_publish_callback.call_args[0][0]
        assert published_report["status"] == MissionState.paused.value["status"]
        assert published_report["state"] == MissionState.paused.value["state"]

    @pytest.mark.asyncio
    async def test_wait_for_task_report_by_task_instance_id(self, mission_tracking, mock_robot_api):
        """Test waiting for task report by taskInstanceId."""
        task_instance_id = "task-123"
        mock_robot_api.get_task_reports_v2.return_value = {
            "robotTaskReports": [
                {"id": "report-123", "taskInstanceId": task_instance_id, "data": "test"}
            ]
        }

        result = await mission_tracking._wait_for_task_report_async(task_instance_id)

        assert result == {"id": "report-123", "taskInstanceId": task_instance_id, "data": "test"}

    @pytest.mark.asyncio
    async def test_wait_for_task_report_timeout(
        self, mission_tracking, mock_robot_api, monkeypatch
    ):
        """Test timeout when waiting for task report."""
        # Mock time to speed up test
        monkeypatch.setattr(
            "inorbit_gausium_connector.src.mission.MAX_TASK_REPORT_WAIT_TIME_SECS", 0.1
        )

        task_instance_id = "task-123"
        mock_robot_api.get_task_reports_v2.return_value = {
            "robotTaskReports": [
                {"id": "report-other", "taskInstanceId": "task-other", "data": "other"}
            ]
        }

        result = await mission_tracking._wait_for_task_report_async(task_instance_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_wait_for_task_report_shutdown(self, mission_tracking, mock_robot_api):
        """Test shutdown during task report wait."""
        task_instance_id = "task-123"
        mission_tracking._shutdown_event.set()

        result = await mission_tracking._wait_for_task_report_async(task_instance_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_handle_mission_completion_success(
        self, mission_tracking, mock_robot_api, mock_publish_callback, sample_task_report
    ):
        """Test successful mission completion handling."""
        task_instance_id = "task-123"
        mock_robot_api.get_task_reports_v2.return_value = {
            "robotTaskReports": [
                {
                    **sample_task_report,
                    "taskInstanceId": task_instance_id,
                    "taskReportPngUri": "https://example.com/report.png",
                }
            ]
        }

        completion_data = {
            "task_instance_id": task_instance_id,
            "interruptions_count": 2,
            "last_inorbit_report": {
                "missionId": task_instance_id,
                "status": InOrbitMissionStatus.ok.value,
                "state": MissionState.in_progress.value["state"],
                "inProgress": True,
                "completedPercent": 0.95,  # Above the 0.90 threshold for completion
            },
            "timestamp": time(),
        }

        await mission_tracking._handle_mission_completion(completion_data)

        # Should publish completed mission
        mock_publish_callback.assert_called_once()
        published_report = mock_publish_callback.call_args[0][0]
        assert published_report["inProgress"] is False
        assert published_report["state"] == MissionState.completed.value["state"]
        # The count captured when the mission ended, not the live one
        assert published_report["data"]["interruptions_count"] == 2

    @pytest.mark.asyncio
    async def test_handle_mission_completion_no_report(
        self, mission_tracking, mock_robot_api, mock_publish_callback, monkeypatch
    ):
        """Test mission completion when no report is found."""
        # Speed up timeout for test
        monkeypatch.setattr(
            "inorbit_gausium_connector.src.mission.MAX_TASK_REPORT_WAIT_TIME_SECS", 0.1
        )

        task_instance_id = "task-123"
        mock_robot_api.get_task_reports_v2.return_value = {
            "robotTaskReports": [
                {"id": "report-other", "taskInstanceId": "task-other", "data": "other"}
            ]
        }

        completion_data = {
            "task_instance_id": task_instance_id,
            "last_inorbit_report": {
                "missionId": task_instance_id,
                "status": InOrbitMissionStatus.ok.value,
                "state": MissionState.in_progress.value["state"],
                "inProgress": True,
                "completedPercent": 0.9,
            },
            "timestamp": time(),
        }

        await mission_tracking._handle_mission_completion(completion_data)

        mock_publish_callback.assert_called_once()
        published_report = mock_publish_callback.call_args[0][0]
        assert published_report["inProgress"] is False
        assert published_report["status"] == MissionState.not_reported.value["status"]
        # The state depends on the completion percentage
        assert published_report["state"] == MissionState.not_reported.value["state"]

    @pytest.mark.asyncio
    async def test_shutdown(self, mission_tracking):
        """Test shutdown functionality."""
        # Create a mock task that behaves like an asyncio.Task
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel = Mock()

        # Create a real async task to test proper shutdown
        async def dummy_task():
            await asyncio.sleep(10)

        real_task = asyncio.create_task(dummy_task())
        mission_tracking._mission_completion_tasks.add(real_task)

        await mission_tracking.shutdown()

        assert mission_tracking._shutdown_event.is_set()
        assert real_task.cancelled()

    def test_update_mission(self, mission_tracking, sample_robot_status, sample_robot_status_v2):
        """Test the _update_mission method."""
        result = mission_tracking._update_mission(sample_robot_status, sample_robot_status_v2)

        expected = {
            "missionId": "task-123",
            "status": InOrbitMissionStatus.ok.value,
            "state": MissionState.in_progress.value["state"],
            "inProgress": MissionState.in_progress.value["inProgress"],
            "label": "Cleaning Task",
            "completedPercent": 0.5,
            "estimatedDurationSecs": 600,  # 300 / 0.5
            "data": {
                "map_name": "Floor 1",
                "task_id": "task-123",
                "task_instance_id": "task-123",
                "distance_m": 100.5,
                "active_cleaning_time_s": 300,
                "task_state": "cleaning",
                "task_state_raw": TaskState.RUNNING.value,
                "interruptions_count": 0,
            },
        }

        assert result == expected

    def test_update_mission_publishes_cleaning_mode(
        self, mission_tracking, sample_robot_status, sample_robot_status_v2
    ):
        """Test that the live cleaning mode is published while a task runs."""
        sample_robot_status_v2["currentTask"]["workMode"] = {"name": "__洗地"}

        result = mission_tracking._update_mission(sample_robot_status, sample_robot_status_v2)

        assert result["data"]["cleaning_mode"] == "scrub"
        assert result["data"]["cleaning_mode_raw"] == "__洗地"
        assert result["data"]["cleaning_mode_label"] == "Wash the floor"

    def test_update_mission_zero_progress(
        self, mission_tracking, sample_robot_status, sample_robot_status_v2
    ):
        """Test _update_mission with zero progress."""
        zero_progress_status = deepcopy(sample_robot_status)
        zero_progress_status["executingTask"]["progress"] = 0

        result = mission_tracking._update_mission(zero_progress_status, sample_robot_status_v2)

        assert result["completedPercent"] == 0.0
        assert result["estimatedDurationSecs"] is None

    def test_update_mission_complete_progress(
        self, mission_tracking, sample_robot_status, sample_robot_status_v2
    ):
        """Test _update_mission with 100% progress."""
        complete_status = deepcopy(sample_robot_status)
        complete_status["executingTask"]["progress"] = 100

        result = mission_tracking._update_mission(complete_status, sample_robot_status_v2)

        assert result["completedPercent"] == 1.0
        assert result["estimatedDurationSecs"] == 300

    def test_update_mission_preserve_progress_when_paused(
        self, mission_tracking, sample_robot_status, sample_robot_status_v2
    ):
        """Test that progress is preserved when robot is paused."""
        paused_status = deepcopy(sample_robot_status)
        # Robot reports 0 progress when paused
        paused_status["executingTask"]["progress"] = 0
        paused_status["taskState"] = TaskState.PAUSED.value

        # Previous progress was 50%
        previous_report = {"completedPercent": 0.5}

        result = mission_tracking._update_mission(
            paused_status, sample_robot_status_v2, previous_report
        )

        # Should preserve the previous progress instead of using 0
        assert result["completedPercent"] == 0.5
        assert result["state"] == MissionState.paused.value["state"]
        assert result["status"] == MissionState.paused.value["status"]

    def test_complete_mission_static_method(self, mission_tracking, sample_task_report):
        """Test the _complete_mission method."""
        last_inorbit_report = {
            "missionId": "task-123",
            "status": InOrbitMissionStatus.ok.value,
            "state": MissionState.in_progress.value["state"],
            "inProgress": True,
            "label": "Original Task",
            "completedPercent": 0.95,  # Above the 0.90 threshold for completion
        }

        result = mission_tracking._complete_mission(sample_task_report, last_inorbit_report)

        assert result["inProgress"] is False
        assert result["label"] == "clean areas 1 and 2"
        assert result["state"] == MissionState.completed.value["state"]
        assert result["status"] == MissionState.completed.value["status"]
        assert result["completedPercent"] == 0.9169
        # Wall time, not the vendor's active cleaning time of 8915 s
        assert result["estimatedDurationSecs"] == 9803
        assert "startTs" in result
        assert "endTs" in result
        assert result["data"]["report_image_url"] == sample_task_report["taskReportPngUri"]
        assert result["data"]["active_cleaning_time_s"] == 8915
        assert result["data"]["coverage_pct"] == 0.9169
        assert result["data"]["water_used_l"] == 0
        assert result["data"]["cleaning_mode_label"] == "Wash the floor"

    def test_complete_mission_low_completion(self, mission_tracking, sample_task_report):
        """Test _complete_mission with low completion percentage."""
        low_completion_report = deepcopy(sample_task_report)
        low_completion_report["completionPercentage"] = 0.5  # Below threshold

        last_inorbit_report = {
            "missionId": "task-123",
            "status": InOrbitMissionStatus.ok.value,
            "state": MissionState.in_progress.value["state"],
            "inProgress": True,
        }

        result = mission_tracking._complete_mission(low_completion_report, last_inorbit_report)

        assert result["state"] == MissionState.abandoned.value["state"]
        assert result["status"] == MissionState.abandoned.value["status"]

    def test_report_not_found_mission_static_method(self):
        """Test the static _report_not_found_mission method."""
        last_inorbit_report = {
            "missionId": "task-123",
            "status": InOrbitMissionStatus.ok.value,
            "state": MissionState.in_progress.value["state"],
            "inProgress": True,
            "data": {"task_state": "cleaning"},
            "completedPercent": 0.5,
        }

        result = MissionTracking._report_not_found_mission(last_inorbit_report)

        assert result["inProgress"] is False
        assert result["state"] == MissionState.not_reported.value["state"]
        assert result["status"] == MissionState.not_reported.value["status"]
        assert result["data"]["Error"] == "Unable to find task report."


class TestUtilityFunctions:
    """Test cases for utility functions."""

    def test_filter_none(self):
        """Test filter_none function."""
        data = {
            "valid": "value",
            "empty_string": "",
            "none": None,
            "zero": 0,
            "false": False,
        }

        assert filter_none(data) == {
            "valid": "value",
            "empty_string": "",
            "zero": 0,
            "false": False,
        }


class TestTaskEndStatus:
    """Test cases for the mission outcome derived from the vendor task end status."""

    @pytest.mark.parametrize(
        "end_status, coverage, expected",
        [
            (0, 0.95, MissionState.completed),
            (0, 0.10, MissionState.incomplete),
            (0, None, MissionState.completed),
            (1, 0.95, MissionState.abandoned),
            (2, 0.95, MissionState.abandoned),
            (3, 0.10, MissionState.abandoned),
            (-1, 0.95, None),
            (None, 0.95, None),
        ],
    )
    def test_get_from_end_status(self, end_status, coverage, expected):
        assert MissionState.get_from_end_status(end_status, coverage, 0.9) is expected

    def test_completed_mission_publishes_task_outcome(self, mission_tracking, sample_task_report):
        sample_task_report["taskEndStatus"] = 0
        sample_task_report["actualCleaningAreaSquareMeter"] = sample_task_report[
            "plannedCleaningAreaSquareMeter"
        ]

        result = mission_tracking._complete_mission(sample_task_report, {"completedPercent": 0.95})

        assert result["state"] == MissionState.completed.value["state"]
        assert result["data"]["task_outcome"] == "completed"
        assert result["completedPercent"] == 1.0

    def test_manual_stop_is_abandoned_whatever_the_coverage(
        self, mission_tracking, sample_task_report
    ):
        sample_task_report["taskEndStatus"] = 1
        sample_task_report["actualCleaningAreaSquareMeter"] = sample_task_report[
            "plannedCleaningAreaSquareMeter"
        ]

        result = mission_tracking._complete_mission(sample_task_report, {"completedPercent": 0.95})

        assert result["state"] == MissionState.abandoned.value["state"]
        assert result["data"]["task_outcome"] == "abandoned"
        assert "1" in result["data"]["Error"]

    def test_unknown_end_status_omits_the_key_and_falls_back(
        self, mission_tracking, sample_task_report
    ):
        sample_task_report["taskEndStatus"] = -1

        result = mission_tracking._complete_mission(sample_task_report, {"completedPercent": 0.95})

        assert "task_outcome" not in result["data"]
        assert result["state"] == MissionState.completed.value["state"]

    def test_completed_percent_reflects_coverage(self, mission_tracking, sample_task_report):
        sample_task_report["taskEndStatus"] = 0

        result = mission_tracking._complete_mission(sample_task_report, {"completedPercent": 0.95})

        assert result["completedPercent"] == 0.9169


class TestInterruptionsCount:
    """Test cases for the per task instance interruptions counter."""

    def _tick(self, mission_tracking, task_state, task_instance_id, progress=10):
        mission_tracking.update(
            {
                "taskState": task_state,
                "executingTask": {"id": "task-1", "progress": progress, "timeRemaining": 1},
                "emergencyStop": {"enabled": False},
            },
            {"currentTask": {"taskInstanceId": task_instance_id}},
        )

    def test_increments_on_pause(self, mission_tracking):
        self._tick(mission_tracking, "RUNNING", "instance-1")
        self._tick(mission_tracking, "PAUSED", "instance-1")
        self._tick(mission_tracking, "PAUSED", "instance-1")
        self._tick(mission_tracking, "RUNNING", "instance-1")
        self._tick(mission_tracking, "PAUSED", "instance-1")

        assert mission_tracking._interruptions_count == 2

    @pytest.mark.asyncio
    async def test_resets_on_a_new_task_instance(self, mission_tracking):
        self._tick(mission_tracking, "RUNNING", "instance-1")
        self._tick(mission_tracking, "PAUSED", "instance-1")
        self._tick(mission_tracking, "RUNNING", "instance-2")

        assert mission_tracking._interruptions_count == 0

        await mission_tracking.shutdown()

    def test_is_published_in_progress_and_on_completion(self, mission_tracking, sample_task_report):
        self._tick(mission_tracking, "RUNNING", "instance-1", progress=10)
        self._tick(mission_tracking, "PAUSED", "instance-1", progress=20)

        assert mission_tracking._last_inorbit_report["data"]["interruptions_count"] == 1

        result = mission_tracking._complete_mission(sample_task_report, {"completedPercent": 0.3})
        assert result["data"]["interruptions_count"] == 1
