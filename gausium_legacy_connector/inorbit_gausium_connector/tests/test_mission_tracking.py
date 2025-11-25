# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import time
import pytest
from unittest.mock import MagicMock, patch

from inorbit_gausium_connector.src.mission import MissionTracking, MissionState, MissionStatus


class TestMissionTracking:
    @pytest.fixture
    def mission_tracking(self):
        publish_callback = MagicMock()
        return MissionTracking(publish_callback)

    def test_mission_update_robot_idle(self, mission_tracking, robot_status_data_idle):
        """Test mission_update when robot is idle"""
        robot_status = robot_status_data_idle["data"]["robotStatus"]
        status_data = robot_status_data_idle["data"].get("statusData", {})

        # Set up a previous mission to test completion when idle
        mission_tracking._last_report = {"missionId": "test-mission"}

        mission_tracking.mission_update(robot_status, status_data)

        # Verify that the last mission was completed
        mission_tracking._publish_callback.assert_called_once()
        published_report = mission_tracking._publish_callback.call_args[0][0]
        assert published_report.get("state") == MissionState.completed.value
        assert published_report.get("inProgress") is False
        assert "endTs" in published_report

    def test_mission_update_robot_executing_task(self, mission_tracking, robot_status_data_task):
        """Test mission_update when robot is executing a task"""
        robot_status = robot_status_data_task["data"]["robotStatus"]
        status_data = robot_status_data_task["data"].get("statusData", {})

        # First call with no previous mission
        mission_tracking.mission_update(robot_status, status_data)

        # Verify callback was called with the right mission report
        mission_tracking._publish_callback.assert_called_once()
        published_report = mission_tracking._publish_callback.call_args[0][0]
        assert published_report.get("missionId") == status_data["taskQueue"]["task_queue_id"]
        assert published_report.get("state") == MissionState.in_progress.value
        assert published_report.get("inProgress") is True

        # Reset the mock to test a second call with a different mission ID
        mission_tracking._publish_callback.reset_mock()

        # Change mission ID in the status data
        new_status_data = status_data.copy()
        new_status_data["taskQueue"] = new_status_data["taskQueue"].copy()
        new_status_data["taskQueue"]["task_queue_id"] = "new-mission-id"

        # Second call should complete the first mission and start the new one
        mission_tracking.mission_update(robot_status, new_status_data)

        # Verify two calls were made - one to complete the old mission and one to start the new one
        assert mission_tracking._publish_callback.call_count == 2

        # The first call should have completed the previous mission
        first_call = mission_tracking._publish_callback.call_args_list[0][0][0]
        assert first_call.get("missionId") == status_data["taskQueue"]["task_queue_id"]
        assert first_call.get("state") == MissionState.completed.value
        assert first_call.get("inProgress") is False

        # The second call should have started the new mission
        second_call = mission_tracking._publish_callback.call_args_list[1][0][0]
        assert second_call.get("missionId") == "new-mission-id"
        assert second_call.get("state") == MissionState.in_progress.value
        assert second_call.get("inProgress") is True

    def test_mission_update_robot_paused_task(
        self, mission_tracking, robot_status_data_task_paused
    ):
        """Test mission_update when robot has a paused task"""
        robot_status = robot_status_data_task_paused["data"]["robotStatus"]
        status_data = robot_status_data_task_paused["data"].get("statusData", {})

        mission_tracking.mission_update(robot_status, status_data)

        # Verify callback was called with the right mission report
        mission_tracking._publish_callback.assert_called_once()
        published_report = mission_tracking._publish_callback.call_args[0][0]
        assert published_report.get("missionId") == status_data["taskQueue"]["task_queue_id"]
        assert published_report.get("state") == MissionState.paused.value
        assert published_report.get("inProgress") is True

    def test_mission_update_navigating(
        self, mission_tracking, robot_status_data_navigating_to_waypoint
    ):
        """Test mission_update when robot is navigating to a waypoint"""
        robot_status = robot_status_data_navigating_to_waypoint["data"]["robotStatus"]
        status_data = robot_status_data_navigating_to_waypoint["data"].get("statusData", {})

        # Set up a previous mission to test completion when navigating
        mission_tracking._last_report = {"missionId": "test-mission"}

        # Since NAVIGATING is not EXECUTE_TASK, it should complete any previous mission
        mission_tracking.mission_update(robot_status, status_data)

        # Verify that the last mission was completed
        mission_tracking._publish_callback.assert_called_once()
        published_report = mission_tracking._publish_callback.call_args[0][0]
        assert published_report.get("state") == MissionState.completed.value
        assert published_report.get("inProgress") is False
        assert "endTs" in published_report

    def test_build_report_from_robot_data_execute_task(self, robot_status_data_task):
        """Test build_report_from_robot_data with EXECUTE_TASK data"""
        robot_status = robot_status_data_task["data"]["robotStatus"]
        status_data = robot_status_data_task["data"]["statusData"]

        report = MissionTracking.build_report_from_robot_data(robot_status, status_data)

        # Verify mission report structure and content
        assert report["missionId"] == status_data["taskQueue"]["task_queue_id"]
        assert report["status"] == MissionStatus.ok.value
        assert report["state"] == MissionState.in_progress.value
        assert report["inProgress"] is True
        assert report["label"] == status_data["taskQueue"]["name"]
        assert "tasks" in report
        assert len(report["tasks"]) == len(status_data["taskQueue"]["tasks"])
        assert "data" in report
        assert "Map name" in report["data"]

    def test_build_report_from_robot_data_not_execute_task(self, robot_status_data_idle):
        """Test build_report_from_robot_data with non-EXECUTE_TASK data"""
        robot_status = robot_status_data_idle["data"]["robotStatus"]
        status_data = robot_status_data_idle["data"].get("statusData", {})

        report = MissionTracking.build_report_from_robot_data(robot_status, status_data)

        # Should return empty dict when not in EXECUTE_TASK mode
        assert report == {}

    def test_gausium_task_state_to_inorbit_state(self):
        """Test translating Gausium task states to InOrbit mission states"""
        assert (
            MissionTracking.gausium_task_state_to_inorbit_state("STARTED")
            == MissionState.in_progress
        )
        assert MissionTracking.gausium_task_state_to_inorbit_state("PAUSED") == MissionState.paused

        # Unknown states default to completed
        assert (
            MissionTracking.gausium_task_state_to_inorbit_state("UNKNOWN") == MissionState.completed
        )

    def test_complete_mission(self):
        """Test mission completion"""
        timestamp = time.time()
        with patch("time.time", return_value=timestamp):
            report = {
                "missionId": "test-mission",
                "inProgress": True,
                "state": MissionState.in_progress.value,
            }

            completed_report = MissionTracking.complete_mission(report)

            assert completed_report["inProgress"] is False
            assert completed_report["state"] == MissionState.completed.value
            assert completed_report["endTs"] == timestamp

            # Original report should not be modified
            assert report["inProgress"] is True
            assert report["state"] == MissionState.in_progress.value

    def test_translate_cleaning_mode_known_modes(self):
        """Test translating known cleaning modes from Chinese to English"""
        # Test various known cleaning modes
        assert MissionTracking._translate_cleaning_mode("尘推") == "Dust mop"
        assert MissionTracking._translate_cleaning_mode("抛光") == "Polish"
        assert MissionTracking._translate_cleaning_mode("快速尘推") == "High-speed dust mop"
        assert MissionTracking._translate_cleaning_mode("深度抛光") == "Deep polish"
        assert MissionTracking._translate_cleaning_mode("地毯清洁") == "Carpet cleaning"
        assert MissionTracking._translate_cleaning_mode("扫地") == "Sweep the floor"
        assert MissionTracking._translate_cleaning_mode("洗地") == "Wash the floor"
        assert MissionTracking._translate_cleaning_mode("吸尘") == "Vacuum"

    def test_translate_cleaning_mode_with_underscores(self):
        """Test that underscores are removed from cleaning mode names"""
        # Test that underscores are properly removed
        assert MissionTracking._translate_cleaning_mode("__地毯清洁") == "Carpet cleaning"
        assert MissionTracking._translate_cleaning_mode("_尘推_") == "Dust mop"
        assert MissionTracking._translate_cleaning_mode("test_mode") == "testmode"

    def test_translate_cleaning_mode_unknown_modes(self):
        """Test that unknown cleaning modes are returned as-is"""
        # Test unknown modes return the original string (with underscores removed)
        assert MissionTracking._translate_cleaning_mode("unknown_mode") == "unknownmode"
        assert MissionTracking._translate_cleaning_mode("custom_cleaning") == "customcleaning"
        assert MissionTracking._translate_cleaning_mode("") == ""

    def test_translate_cleaning_mode_none_and_empty(self):
        """Test handling of None and empty values"""
        # Test None value
        assert MissionTracking._translate_cleaning_mode(None) is None

        # Test empty string
        assert MissionTracking._translate_cleaning_mode("") == ""

    def test_build_report_from_robot_data_includes_work_mode_translation(
        self, robot_status_data_task
    ):
        """Test that build_report_from_robot_data includes translated work mode in the report"""
        robot_status = robot_status_data_task["data"]["robotStatus"]
        status_data = robot_status_data_task["data"]["statusData"]

        report = MissionTracking.build_report_from_robot_data(robot_status, status_data)

        # Verify that work mode is included and translated
        assert "data" in report
        assert "Work mode" in report["data"]
        # The test data has work_mode.name = "vacuum", which should be returned as-is
        # since it's not in Chinese
        assert report["data"]["Work mode"] == "vacuum"

    def test_build_report_from_robot_data_with_chinese_work_mode(self):
        """Test build_report_from_robot_data with Chinese work mode that needs translation"""
        robot_status = {"workType": "EXECUTE_TASK"}
        status_data = {
            "status": "STARTED",
            "taskQueue": {
                "task_queue_id": "test-mission",
                "name": "Test Mission",
                "estimate_time": 1.0,
                "tasks": [{"name": "TestTask", "start_param": {}}],
                "work_mode": {
                    "name": "尘推",  # Chinese for "Dust mop"
                },
                "total_area": 100.0,
                "loop_count": 1,
            },
            "finished_task_count": 0,
            "mapName": "TestMap",
            "startTime": 1234567890,
        }

        report = MissionTracking.build_report_from_robot_data(robot_status, status_data)

        # Verify that the Chinese work mode is translated
        assert report["data"]["Work mode"] == "Dust mop"

    def test_build_report_from_robot_data_missing_work_mode(self):
        """Test build_report_from_robot_data when work_mode is missing"""
        robot_status = {"workType": "EXECUTE_TASK"}
        status_data = {
            "status": "STARTED",
            "taskQueue": {
                "task_queue_id": "test-mission",
                "name": "Test Mission",
                "estimate_time": 1.0,
                "tasks": [{"name": "TestTask", "start_param": {}}],
                # work_mode is missing
                "total_area": 100.0,
                "loop_count": 1,
            },
            "finished_task_count": 0,
            "mapName": "TestMap",
            "startTime": 1234567890,
        }

        report = MissionTracking.build_report_from_robot_data(robot_status, status_data)

        # Verify that work mode is None when missing
        assert report["data"]["Work mode"] is None

    def test_build_report_from_robot_data_work_mode_none(self):
        """Test build_report_from_robot_data when work_mode.name is None"""
        robot_status = {"workType": "EXECUTE_TASK"}
        status_data = {
            "status": "STARTED",
            "taskQueue": {
                "task_queue_id": "test-mission",
                "name": "Test Mission",
                "estimate_time": 1.0,
                "tasks": [{"name": "TestTask", "start_param": {}}],
                "work_mode": {
                    "name": None,
                },
                "total_area": 100.0,
                "loop_count": 1,
            },
            "finished_task_count": 0,
            "mapName": "TestMap",
            "startTime": 1234567890,
        }

        report = MissionTracking.build_report_from_robot_data(robot_status, status_data)

        # Verify that work mode is None
        assert report["data"]["Work mode"] is None
