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
