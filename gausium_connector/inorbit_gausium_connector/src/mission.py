# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import time
from typing import Callable

from inorbit_gausium_connector.src.constants import MissionState, MissionStatus
from inorbit_gausium_connector.src.robot.constants import TaskState, WorkType


class MissionTracking:
    """Translate Gausium robot data to InOrbit mission tracking data. In order for this to work,
    the manifests in /cac_examples/MissionTracking.yaml must be applied."""

    def __init__(self, publish_callback: Callable[[dict], None]):
        """
        Args:
            publish_callback: A callback function that takes the mission tracking dictionary and
            publishes it to InOrbit.
        """
        self._publish_callback = publish_callback
        self._last_report = {}

    def mission_update(self, robot_status: dict, status_data: dict) -> None:
        """Update the mission tracking data based on new robot data. self._publish_callback may be
        called multiple times."""
        work_type = robot_status.get("workType")
        report = None

        # If the robot is executing a mission, build a new report
        if work_type == WorkType.EXECUTE_TASK.value:
            report = self.build_report_from_robot_data(robot_status, status_data)
            # If the mission ID has changed, complete the previous mission first
            if self._last_report and report.get("missionId") != self._last_report.get("missionId"):
                completed_last_mission = self.complete_mission(self._last_report)
                self._publish_callback(completed_last_mission)

        # If the robot is no longer executing a mission, mark the previous mission as completed
        else:
            if self._last_report:
                report = self.complete_mission(self._last_report)

        # If there is a report to publish, publish it
        if report:
            self._publish_callback(report)

        # Update the last report
        self._last_report = report

    @staticmethod
    def build_report_from_robot_data(robot_status: dict, status_data: dict) -> dict:
        """Translate Gausium robot data to InOrbit mission tracking data.
        Only tracks EXECUTE_TASK work"""

        work_type = robot_status.get("workType")
        task_queue = status_data.get("taskQueue")
        if work_type != WorkType.EXECUTE_TASK.value or not task_queue:
            return {}

        tasks = task_queue.get("tasks", [])
        finished_task_count = status_data.get("finished_task_count")
        progress = (finished_task_count / len(tasks)) if tasks else 0

        mission_tracking = {
            "missionId": task_queue.get("task_queue_id"),
            "status": MissionStatus.ok.value,  # TODO
            "state": MissionTracking.gausium_task_state_to_inorbit_state(
                status_data.get("status")
            ).value,
            "inProgress": status_data.get("status")
            in [TaskState.STARTED.value, TaskState.PAUSED.value],
            "label": task_queue.get("name"),
            "startTs": status_data.get("startTime"),
            "completedPercent": progress,
            "estimatedDurationSecs": task_queue.get("estimate_time") * 3600,
            "tasks": [
                {
                    "taskId": str(i),
                    "inProgress": i == finished_task_count,
                    "completed": i < finished_task_count,
                    "label": task.get("name"),
                    "arguments": {
                        "name": task.get("name"),
                        "map_name": task.get("start_param", {}).get("map_name"),
                        "path_name": task.get("start_param", {}).get("path_name"),
                    },
                }
                for i, task in enumerate(tasks)
            ],
            "data": {
                "Map name": status_data.get("mapName"),
                "Task queue ID": task_queue.get("task_queue_id"),
                "Work mode": task_queue.get("work_mode", {}).get("name"),
                "Total area": task_queue.get("total_area"),
                "Loop count": task_queue.get("loop_count"),
            },
        }
        return mission_tracking

    @staticmethod
    def gausium_task_state_to_inorbit_state(state: str) -> MissionState:
        """Translate Gausium task state to InOrbit mission state"""
        if state == TaskState.STARTED.value:
            return MissionState.in_progress
        elif state == TaskState.PAUSED.value:
            return MissionState.paused
        print(f"Unknown task state: {state}")
        return MissionState.completed

    @staticmethod
    def complete_mission(report: dict) -> dict:
        """Complete a mission"""
        new_report = report.copy()
        new_report["inProgress"] = False
        new_report["state"] = MissionState.completed.value
        new_report["endTs"] = time.time()
        return new_report
