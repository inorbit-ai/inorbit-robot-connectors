# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import asyncio
import logging
from copy import deepcopy
from datetime import datetime
from enum import Enum
from numbers import Number
from time import time
from typing import Any
from typing import Callable

from ..config.connector_model import DEFAULT_MISSION_SUCCESS_PERCENTAGE_THRESHOLD
from .robot import RobotAPI
from .robot import TaskState


# The progress bar is advanced to 100% if the progress percentage is greater than this threshold
MISSION_PROGRESS_BAR_ADVANCED_PERCENTAGE_THRESHOLD = 0.90

# Max time to wait for a task report to be available
MAX_TASK_REPORT_WAIT_TIME_SECS = 10 * 60  # 10 minutes

# Cleaning modes in reports are in Chinese
CLEANING_MODE_TRANSLATION = {
    "尘推": "Dust mop",
    "抛光": "Polish",
    "快速尘推": "High-speed dust mop",
    "深度抛光": "Deep polish",
    "低速尘推": "Low-speed dust mop",
    "结晶模式": "Crystallization mode",
    "地毯清洁": "Carpet cleaning",
    "静音推尘": "Slient dust mopping",
    "喷雾消毒": "Disinfection spray",
    "滚刷洗地": "Roller brush scrubbing",
    "布刷尘推": "Cloth brush dust mopping",
    "轻度清洁": "Light cleaning",
    "中度清洁": "Middle cleaning",
    "重度清洁": "Heavy cleaning",
    "吸风清洁": "Suction cleaning",
    "测试": "Test",
    "扫地": "Sweep the floor",
    "洗地": "Wash the floor",
    "吸尘": "Vacuum",
}


class InOrbitMissionStatus(Enum):
    """
    Allowed values for InOrbit for mission Status.
    """

    ok = "OK"
    warn = "warning"
    error = "error"


class MissionState(Enum):
    """
    Possible pairs of mission state and status.
    """

    # The mission finished and targets were achieved
    completed = {
        "state": "completed",
        "status": InOrbitMissionStatus.ok.value,
        "inProgress": False,
    }
    # The mission is in progress and going as expected
    in_progress = {
        "state": "in-progress",
        "status": InOrbitMissionStatus.ok.value,
        "inProgress": True,
    }
    # The mission is paused
    paused = {
        "state": "paused",
        "status": InOrbitMissionStatus.warn.value,
        "inProgress": True,
    }
    # The mission is finished but no report was found
    not_reported = {
        "state": "not-reported",
        "status": InOrbitMissionStatus.error.value,
        "inProgress": False,
    }
    # The mission did not finish
    abandoned = {
        "state": "abandoned",
        "status": InOrbitMissionStatus.error.value,
        "inProgress": False,
    }
    # The mission finished but did not achieve the success threshold
    incomplete = {
        "state": "incomplete",
        "status": InOrbitMissionStatus.warn.value,
        "inProgress": False,
    }
    # Unknown state, likely due to an inconsistency in the data
    unknown = {
        "state": "unknown",
        "status": InOrbitMissionStatus.error.value,
        "inProgress": False,
    }

    @classmethod
    def get_from_status(cls, task_state: str, emergency_stop: bool) -> "MissionState":
        """Returns the mission state based on the status."""
        if emergency_stop or task_state == TaskState.PAUSED.value:
            return cls.paused
        elif task_state == TaskState.RUNNING.value or task_state == TaskState.OTHER.value:
            return cls.in_progress
        else:
            return cls.unknown

    @staticmethod
    def get_for_completion(
        completion_percentage: float,
        completion_percentage_threshold: float,
        progress_percentage: float,
    ) -> "MissionState":
        """Returns the mission state based on the completion percentage."""
        progress_ok = progress_percentage >= MISSION_PROGRESS_BAR_ADVANCED_PERCENTAGE_THRESHOLD
        completion_ok = completion_percentage >= completion_percentage_threshold
        if progress_ok:
            if completion_ok:
                return MissionState.completed
            else:
                return MissionState.incomplete
        else:
            return MissionState.abandoned


def filter_truthy(data: dict[str, Any]) -> dict[str, Any]:
    """Filter out values that are not truthy from a dictionary."""
    return {k: v for k, v in data.items() if bool(v)}


def gausium_date_to_inorbit_millis(date: datetime) -> int:
    """Converts a date from Gausium reports to a date for InOrbit missions."""
    return int(datetime.fromisoformat(date.replace("Z", "+00:00")).timestamp() * 1000)


class MissionTracking:
    """MissionTracking utility class. It preserves data received from the robot to generate up to
    date mission tracking data.
    After a mission is completed, it waits up to MAX_TASK_REPORT_WAIT_TIME_SECS minutes for the
    Gausium report to be available.
    """

    def __init__(
        self,
        robot_api: RobotAPI,
        publish_callback: Callable[[dict], None],
        mission_success_percentage_threshold: float = DEFAULT_MISSION_SUCCESS_PERCENTAGE_THRESHOLD,
    ) -> None:
        self._logger = logging.getLogger(name=self.__class__.__name__)
        # Robot API for fetching task reports
        self._robot_api = robot_api
        # Callback to publish the mission status
        self._publish_callback = publish_callback
        # Configurable threshold for mission success
        self._mission_success_percentage_threshold = mission_success_percentage_threshold
        # Last robot status
        self._last_robot_status: dict[str, Any] = {}
        # Last executing task ID
        self._last_executing_task_id: str | None = None
        # Last published report
        self._last_inorbit_report: dict[str, Any] = {}
        # Tasks waiting for a task report to be available to complete a mission
        self._mission_completion_tasks: set[asyncio.Task] = set()
        # Map of task IDs to their completion tasks for cancellation
        self._pending_completion_tasks: dict[str, asyncio.Task] = {}
        self._shutdown_event = asyncio.Event()

    def update(self, robot_status: dict[str, Any], robot_status_v2: dict[str, Any]) -> None:
        """Update the mission status."""

        last_executing_task = self._last_robot_status.get("executingTask", {})
        curr_executing_task = robot_status.get("executingTask", {})

        last_task_id = self._last_executing_task_id
        curr_task_id = robot_status_v2.get("currentTask", {}).get("taskInstanceId")

        # NOTE(b-Tomas): Since we are getting data from two different sources, we need to check
        # they match.
        # In some instances when a mission is completed, the v1 status stops reporting
        # "executingTask" before the v2 status stops reporting a "currentTask" and "taskInstanceId".
        # Let's define the validity of the compound status report as:
        robot_is_executing_mission = bool(curr_task_id and curr_executing_task)

        if not last_task_id and not curr_task_id:
            self._logger.debug("No mission data to process")
            return

        # There was a mission running before and it now changed
        # It can happen that the curr_task_id reported is still the same as the last one, but the
        # robot is not executing a mission anymore.
        if last_task_id and (last_task_id != curr_task_id or not robot_is_executing_mission):
            self._logger.info(
                f"Mission changed: last task ID: {last_task_id}, current task ID: {curr_task_id}"
            )
            # Start mission completion handling
            completion_data = {
                "task_instance_id": last_task_id,
                "last_inorbit_report": deepcopy(self._last_inorbit_report),
                "timestamp": time(),
            }
            # Wait in the background for the task report to be available and update the mission data
            self._create_mission_completion_task(completion_data)

        # If the current task ID is the same as a task we're waiting for completion, cancel the wait
        if curr_task_id and curr_task_id in self._pending_completion_tasks:
            self._logger.info(f"Task {curr_task_id} resumed, cancelling pending completion task")
            self._cancel_completion_task(curr_task_id)

        # If there is a current mission, update the mission status
        # Only update if the mission data is different from the last update
        if (
            curr_task_id
            and curr_executing_task != last_executing_task
            and robot_is_executing_mission
        ):
            self._logger.debug(f"Updating mission {curr_executing_task.get('name')}")
            self._last_inorbit_report = MissionTracking._update_mission(
                robot_status, robot_status_v2, self._last_inorbit_report
            )
            self._logger.debug(f"InOrbit mission report: {self._last_inorbit_report}")
            self._publish_callback(self._last_inorbit_report)

        self._last_robot_status = robot_status
        self._last_executing_task_id = curr_task_id

    def _create_mission_completion_task(self, completion_data: dict) -> asyncio.Task:
        """Wait for a task report of a finished mission to be available."""

        task_id = completion_data["task_instance_id"]

        # Cancel any existing completion task for this task ID
        if task_id in self._pending_completion_tasks:
            self._logger.info(f"Cancelling existing completion task for task ID: {task_id}")
            self._cancel_completion_task(task_id)

        task = asyncio.create_task(self._handle_mission_completion(completion_data))
        self._mission_completion_tasks.add(task)
        self._pending_completion_tasks[task_id] = task

        def cleanup_task(completed_task):
            self._mission_completion_tasks.discard(completed_task)
            # Remove from pending tasks if it's still there
            pending_task = self._pending_completion_tasks.get(task_id)
            if pending_task == completed_task:
                del self._pending_completion_tasks[task_id]

        task.add_done_callback(cleanup_task)
        return task

    def _cancel_completion_task(self, task_id: str) -> None:
        """Cancel a pending completion task for the given task ID."""
        if task_id in self._pending_completion_tasks:
            task = self._pending_completion_tasks[task_id]
            if not task.done():
                task.cancel()
            del self._pending_completion_tasks[task_id]

    async def _handle_mission_completion(self, completion_data: dict) -> None:
        """Handle mission completion by waiting for task report concurrently."""
        try:
            # Wait for the task report
            last_task_report = await self._wait_for_task_report_async(
                completion_data["task_instance_id"]
            )

            # Complete the last mission based on the report data
            if last_task_report:
                self._logger.info(f"Completing mission with report ID {last_task_report.get('id')}")
                completed_report = self._complete_mission(
                    last_task_report, completion_data["last_inorbit_report"]
                )
                self._publish_callback(completed_report)
            # If the report is not available, mark the mission as abandoned
            else:
                self._logger.info(
                    "Could not find report for mission "
                    f"{completion_data['last_inorbit_report'].get('missionId')}."
                    " Abandoning mission."
                )
                abandoned_report = MissionTracking._report_not_found_mission(
                    completion_data["last_inorbit_report"]
                )
                self._publish_callback(abandoned_report)
        except asyncio.CancelledError:
            self._logger.info(
                f"Mission completion task cancelled for task ID: "
                f"{completion_data['task_instance_id']}"
            )
            # Don't re-raise the CancelledError, just let the task complete
        except Exception as e:
            self._logger.error(f"Error handling mission completion: {e}")

    async def _wait_for_task_report_async(self, task_instance_id: str) -> dict[str, Any] | None:
        """Polls the reports API until a report with the matching taskInstanceId is available.
        Returns the matching task report if it is available, otherwise None."""

        start_time = time()
        max_wait_time = MAX_TASK_REPORT_WAIT_TIME_SECS

        while (time() - start_time) < max_wait_time:
            # Check for shutdown
            if self._shutdown_event.is_set():
                self._logger.info("Shutdown requested, stopping report wait")
                return None

            elapsed = round(time() - start_time, 2)
            self._logger.info(
                f"Waiting for task report with taskInstanceId {task_instance_id}... {elapsed}s"
            )

            try:
                # Fetch reports using v2 API
                task_reports_response = await self._robot_api.get_task_reports_v2(
                    page=1, page_size=10
                )
                task_reports = task_reports_response.get("robotTaskReports", [])

                # Look for a report with the matching taskInstanceId
                for report in task_reports:
                    report_task_instance_id = report.get("taskInstanceId")
                    if report_task_instance_id == task_instance_id:
                        elapsed = round(time() - start_time, 2)
                        self._logger.info(
                            f"Found task report with taskInstanceId {task_instance_id} "
                            f"after {elapsed}s"
                        )
                        return report

                # No matching report found yet, wait and try again
                await asyncio.sleep(0.5)

            except Exception as e:
                self._logger.error(f"Error fetching task reports: {e}")
                await asyncio.sleep(0.5)

        self._logger.error(
            f"Timed out waiting for task report with taskInstanceId {task_instance_id}"
        )
        return None

    async def shutdown(self) -> None:
        """Shutdown mission tracking and cancel tasks waiting for reports."""
        self._shutdown_event.set()

        # Cancel all pending completion tasks by task ID
        for task_id in list(self._pending_completion_tasks.keys()):
            self._cancel_completion_task(task_id)

        # Cancel all mission completion tasks
        for task in list(self._mission_completion_tasks):
            if not task.done():
                task.cancel()

        # Wait for all tasks to complete
        if self._mission_completion_tasks:
            await asyncio.gather(*self._mission_completion_tasks, return_exceptions=True)

    @staticmethod
    def _update_mission(
        robot_status: dict[str, Any],
        robot_status_v2: dict[str, Any],
        previous_report: dict[str, Any] = dict(),
    ) -> dict[str, Any]:
        """Returns an InOrbit mission report based on the robot_status data."""

        executing_task = robot_status.get("executingTask", {})
        # Relevant executing task data
        task_id = robot_status_v2.get("currentTask", {}).get("taskInstanceId")
        name = executing_task.get("name", task_id)
        progress_raw = executing_task.get("progress", 0)
        progress = max(0, min(100, progress_raw))  # From 0 to 100
        # NOTE(b-Tomas): empirically, timeRemaining seems to be the time elapsed
        time_elapsed = executing_task.get("timeRemaining")
        cleaning_mileage = executing_task.get("cleaningMileage")

        # Relevant status data
        task_state = robot_status.get("taskState")
        emergency_stop = robot_status.get("emergencyStop", {}).get("enabled")

        # Calculated InOrbit mission data
        state = MissionState.get_from_status(task_state, emergency_stop)
        label = name

        # Do not allow the completion percentage to be lower than the previous one
        previous_completed_percent = previous_report.get("completedPercent", 0)
        completed_percent = max(previous_completed_percent, progress / 100)  # From 0 to 1

        if completed_percent == 0:
            estimated_duration_secs = None
        elif completed_percent == 1:
            estimated_duration_secs = time_elapsed
        else:
            estimated_duration_secs = (
                time_elapsed / completed_percent if isinstance(time_elapsed, Number) else None
            )

        details = {
            "Map name": robot_status.get("localizationInfo", {}).get("map", {}).get("name"),
            "Task ID": executing_task.get("id"),
            "Task instance ID": robot_status_v2.get("currentTask", {}).get("taskInstanceId"),
            "Task state": task_state,  # Reset when the mission finishes
            "Cleaning mileage": cleaning_mileage,
            "Time elapsed [s]": time_elapsed,
        }

        return {
            **state.value,
            "missionId": task_id,
            "label": label,
            "completedPercent": completed_percent,
            "estimatedDurationSecs": estimated_duration_secs,
            "data": filter_truthy(details),
        }

    def _complete_mission(
        self, task_report: dict[str, Any], last_inorbit_report: dict[str, Any]
    ) -> dict[str, Any]:
        """Completes a previous mission based on its report data"""
        inorbit_report = deepcopy(last_inorbit_report)

        # Relevant task report data
        report_id = task_report.get("id")
        start_time = task_report.get("startTime")
        end_time = task_report.get("endTime")
        display_name = task_report.get("displayName")
        completion_percentage = task_report.get("completionPercentage", 0)  # From 0 to 1
        operator = task_report.get("operator")
        duration_secs = task_report.get("durationSeconds", 0)
        planned_cleaning_area_square_meter = task_report.get("plannedCleaningAreaSquareMeter")
        actual_cleaning_area_square_meter = task_report.get("actualCleaningAreaSquareMeter")
        efficiency_square_meter_per_hour = task_report.get("efficiencySquareMeterPerHour")
        planned_polishing_area_square_meter = task_report.get("plannedPolishingAreaSquareMeter")
        actual_polishing_area_square_meter = task_report.get("actualPolishingAreaSquareMeter")
        water_consumption_liter = task_report.get("waterConsumptionLiter")
        start_battery_percentage = task_report.get("startBatteryPercentage")
        end_battery_percentage = task_report.get("endBatteryPercentage")
        consumables_residual_percentage = task_report.get("consumablesResidualPercentage", {})
        brush_residual_percentage = consumables_residual_percentage.get("brush")
        filter_residual_percentage = consumables_residual_percentage.get("filter")
        suction_blade_residual_percentage = consumables_residual_percentage.get("suctionBlade")
        cleaning_mode = task_report.get("cleaningMode", "")

        details = {
            "Report image URI": task_report.get("taskReportPngUri"),
            "Planned cleaning area [m2]": planned_cleaning_area_square_meter,
            "Actual cleaning area [m2]": actual_cleaning_area_square_meter,
            "Cleaned area percentage [%]": (
                actual_cleaning_area_square_meter / planned_cleaning_area_square_meter * 100
                if actual_cleaning_area_square_meter and planned_cleaning_area_square_meter
                else None
            ),
            "Efficiency [m2/h]": efficiency_square_meter_per_hour,
            "Planned polishing area [m2]": planned_polishing_area_square_meter,
            "Actual polishing area [m2]": actual_polishing_area_square_meter,
            "Water consumption [L]": water_consumption_liter,
            "Start battery percentage [%]": start_battery_percentage,
            "End battery percentage [%]": end_battery_percentage,
            "Brush residual percentage [%]": brush_residual_percentage,
            "Filter residual percentage [%]": filter_residual_percentage,
            "Suction blade residual percentage [%]": suction_blade_residual_percentage,
            "Cleaning mode": self._translate_cleaning_mode(cleaning_mode),
            "Operator": operator,
            "Report ID": report_id,
            "Start time": start_time,
            "End time": end_time,
            # Reset the task state
            "Task state": None,
        }

        # Calculated InOrbit mission data
        inorbit_report["inProgress"] = False
        inorbit_report["label"] = display_name

        # Set the state and status based on the completion percentage (area cleaned)
        # and the progress percentage (progress bar).
        last_progress_bar_percentage = last_inorbit_report.get("completedPercent", 0)
        state = MissionState.get_for_completion(
            completion_percentage,
            self._mission_success_percentage_threshold,
            last_progress_bar_percentage,
        )
        if state is MissionState.incomplete:
            details["Error"] = (
                f"Mission failed to achieve a completion percentage of "
                f"{self._mission_success_percentage_threshold * 100}%"
            )
        inorbit_report.update(state.value)

        # Advance the progress bar to 100% if the previously published progress was enough
        # to consider the mission as finished
        # Otherwise, let the progress bar stay as it was before receiving the report
        # and mark it as abandoned
        if state is MissionState.completed or state is MissionState.incomplete:
            self._logger.info(
                f"Completing mission {report_id} with previous progress "
                f"{last_progress_bar_percentage}"
            )
            inorbit_report["completedPercent"] = 1
        else:
            self._logger.info(
                f"Abandoning mission {report_id} with previous progress "
                f"{last_progress_bar_percentage}"
            )
            inorbit_report["completedPercent"] = last_progress_bar_percentage

        inorbit_report["estimatedDurationSecs"] = duration_secs
        inorbit_report["startTs"] = (
            gausium_date_to_inorbit_millis(start_time) if start_time else None
        )
        inorbit_report["endTs"] = gausium_date_to_inorbit_millis(end_time) if end_time else None

        # Filter out None or zero values
        inorbit_report["data"] = filter_truthy(details)

        return inorbit_report

    @staticmethod
    def _report_not_found_mission(last_inorbit_report: dict[str, Any]) -> dict[str, Any]:
        """Returns an abandoned InOrbit mission report based on a previous report when a report
        has not been found."""
        inorbit_report = deepcopy(last_inorbit_report)
        inorbit_report.update(MissionState.not_reported.value)
        inorbit_report["data"] = {"Error": "Unable to find task report."}
        inorbit_report["data"]["Task state"] = None  # Reset the task state
        return inorbit_report

    @staticmethod
    def _translate_cleaning_mode(cleaning_mode: str) -> str:
        """Translate the reported cleaning mode to english"""

        # Remove special characters
        cleaning_mode_name = cleaning_mode.replace("_", "")

        return CLEANING_MODE_TRANSLATION.get(cleaning_mode_name, cleaning_mode_name)
