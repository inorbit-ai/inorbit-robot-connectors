# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import asyncio
from copy import deepcopy
from datetime import datetime
from time import time
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from inorbit_gausium_connector.src.mission import filter_truthy
from inorbit_gausium_connector.src.mission import gausium_date_to_inorbit_millis
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
        assert published_report["data"]["Task ID"] == "task-123"

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

    def test_update_mission_static_method(self, sample_robot_status, sample_robot_status_v2):
        """Test the static _update_mission method."""
        result = MissionTracking._update_mission(sample_robot_status, sample_robot_status_v2)

        expected = {
            "missionId": "task-123",
            "status": InOrbitMissionStatus.ok.value,
            "state": MissionState.in_progress.value["state"],
            "inProgress": MissionState.in_progress.value["inProgress"],
            "label": "Cleaning Task",
            "completedPercent": 0.5,
            "estimatedDurationSecs": 600,  # 300 / 0.5
            "data": {
                "Map name": "Floor 1",
                "Task ID": "task-123",
                "Task instance ID": "task-123",
                "Task state": TaskState.RUNNING.value,
                "Cleaning mileage": 100.5,
                "Time elapsed [s]": 300,
            },
        }

        assert result == expected

    def test_update_mission_zero_progress(self, sample_robot_status, sample_robot_status_v2):
        """Test _update_mission with zero progress."""
        zero_progress_status = deepcopy(sample_robot_status)
        zero_progress_status["executingTask"]["progress"] = 0

        result = MissionTracking._update_mission(zero_progress_status, sample_robot_status_v2)

        assert result["completedPercent"] == 0.0
        assert result["estimatedDurationSecs"] is None

    def test_update_mission_complete_progress(self, sample_robot_status, sample_robot_status_v2):
        """Test _update_mission with 100% progress."""
        complete_status = deepcopy(sample_robot_status)
        complete_status["executingTask"]["progress"] = 100

        result = MissionTracking._update_mission(complete_status, sample_robot_status_v2)

        assert result["completedPercent"] == 1.0
        assert result["estimatedDurationSecs"] == 300

    def test_update_mission_preserve_progress_when_paused(
        self, sample_robot_status, sample_robot_status_v2
    ):
        """Test that progress is preserved when robot is paused."""
        paused_status = deepcopy(sample_robot_status)
        # Robot reports 0 progress when paused
        paused_status["executingTask"]["progress"] = 0
        paused_status["taskState"] = TaskState.PAUSED.value

        # Previous progress was 50%
        previous_report = {"completedPercent": 0.5}

        result = MissionTracking._update_mission(
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
        assert result["completedPercent"] == 1
        assert result["estimatedDurationSecs"] == 8915
        assert "startTs" in result
        assert "endTs" in result
        assert "Report image URI" in result["data"]

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
            "data": {"Task state": TaskState.RUNNING.value},
            "completedPercent": 0.5,
        }

        result = MissionTracking._report_not_found_mission(last_inorbit_report)

        assert result["inProgress"] is False
        assert result["state"] == MissionState.not_reported.value["state"]
        assert result["status"] == MissionState.not_reported.value["status"]
        assert result["data"]["Error"] == "Unable to find task report."
        assert result["data"]["Task state"] is None


class TestUtilityFunctions:
    """Test cases for utility functions."""

    def test_filter_truthy(self):
        """Test filter_truthy function."""
        data = {
            "valid": "value",
            "empty_string": "",
            "none": None,
            "zero": 0,
            "false": False,
            "true": True,
            "list": [1, 2, 3],
            "empty_list": [],
        }

        result = filter_truthy(data)

        expected = {
            "valid": "value",
            "true": True,
            "list": [1, 2, 3],
        }

        assert result == expected

    def test_gausium_date_to_inorbit_millis(self):
        """Test gausium_date_to_inorbit_millis function."""
        # Test with Z timezone
        date_str = "2023-12-01T10:00:00Z"
        result = gausium_date_to_inorbit_millis(date_str)

        expected = int(datetime.fromisoformat("2023-12-01T10:00:00+00:00").timestamp() * 1000)
        assert result == expected

    def test_gausium_date_to_inorbit_millis_different_date(self):
        """Test gausium_date_to_inorbit_millis with different date."""
        date_str = "2023-06-15T14:30:45Z"
        result = gausium_date_to_inorbit_millis(date_str)

        expected = int(datetime.fromisoformat("2023-06-15T14:30:45+00:00").timestamp() * 1000)
        assert result == expected


class TestCleaningModeTranslation:
    """Test cases for cleaning mode translation functionality."""

    def test_translate_cleaning_mode_known_modes(self):
        """Test translation of known cleaning modes."""
        # Test various known cleaning modes
        test_cases = [
            ("尘推", "Dust mop"),
            ("抛光", "Polish"),
            ("快速尘推", "High-speed dust mop"),
            ("深度抛光", "Deep polish"),
            ("低速尘推", "Low-speed dust mop"),
            ("结晶模式", "Crystallization mode"),
            ("地毯清洁", "Carpet cleaning"),
            ("静音推尘", "Slient dust mopping"),
            ("喷雾消毒", "Disinfection spray"),
            ("滚刷洗地", "Roller brush scrubbing"),
            ("布刷尘推", "Cloth brush dust mopping"),
            ("轻度清洁", "Light cleaning"),
            ("中度清洁", "Middle cleaning"),
            ("重度清洁", "Heavy cleaning"),
            ("吸风清洁", "Suction cleaning"),
            ("测试", "Test"),
            ("扫地", "Sweep the floor"),
            ("洗地", "Wash the floor"),
            ("吸尘", "Vacuum"),
        ]

        for chinese_mode, expected_english in test_cases:
            result = MissionTracking._translate_cleaning_mode(chinese_mode)
            assert (
                result == expected_english
            ), f"Failed to translate '{chinese_mode}' to '{expected_english}'"

    def test_translate_cleaning_mode_unknown_mode(self):
        """Test translation of unknown cleaning mode."""

        unknown_mode = "未知模式"
        result = MissionTracking._translate_cleaning_mode(unknown_mode)

        # Should return the original mode if not found
        assert result == unknown_mode

    def test_translate_cleaning_mode_with_underscores(self):
        """Test translation of cleaning mode with underscores."""

        # Test that underscores are removed before translation
        mode_with_underscores = "尘_推"
        result = MissionTracking._translate_cleaning_mode(mode_with_underscores)

        # Should translate to "Dust mop" after removing underscore
        assert result == "Dust mop"

    def test_translate_cleaning_mode_empty_string(self):
        """Test translation of empty cleaning mode."""

        result = MissionTracking._translate_cleaning_mode("")
        assert result == ""
