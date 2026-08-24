# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Per-robot mission tracking: turns Gausium task status into InOrbit mission events."""

# Standard
import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from copy import deepcopy
from enum import Enum, StrEnum
from numbers import Number
from time import time
from typing import Any

# Local
from gausium_open_platform_connector.src.canonical import (
    TaskState,
    cleaning_mode_keys,
    normalize_task_state,
    report_time_to_millis,
)
from gausium_open_platform_connector.src.report import report_to_data

# The progress bar is advanced to 100% if the progress percentage is greater than this threshold
MISSION_PROGRESS_BAR_ADVANCED_PERCENTAGE_THRESHOLD = 0.90

# Max time to wait for a task report to be available
MAX_TASK_REPORT_WAIT_TIME_SECS = 10 * 60  # 10 minutes

REPORT_POLL_INTERVAL_SECS = 0.5

# Reported task end statuses: -1 unknown, 0 normal, 1 manual, 2 error, 3 startup failure
TASK_END_STATUS_NORMAL = 0
TASK_END_STATUS_ABNORMAL = (1, 2, 3)


class InOrbitMissionStatus(StrEnum):
    """Allowed values for the InOrbit mission status."""

    OK = "OK"
    WARNING = "warning"
    ERROR = "error"


class MissionState(Enum):
    """Possible pairs of mission state and status."""

    # The mission finished and targets were achieved
    completed = {  # noqa: RUF012
        "state": "completed",
        "status": InOrbitMissionStatus.OK.value,
        "inProgress": False,
    }
    # The mission is in progress and going as expected
    in_progress = {  # noqa: RUF012
        "state": "in-progress",
        "status": InOrbitMissionStatus.OK.value,
        "inProgress": True,
    }
    # The mission is paused
    paused = {  # noqa: RUF012
        "state": "paused",
        "status": InOrbitMissionStatus.WARNING.value,
        "inProgress": True,
    }
    # The mission is finished but no report was found
    not_reported = {  # noqa: RUF012
        "state": "not-reported",
        "status": InOrbitMissionStatus.ERROR.value,
        "inProgress": False,
    }
    # The mission did not finish
    abandoned = {  # noqa: RUF012
        "state": "abandoned",
        "status": InOrbitMissionStatus.ERROR.value,
        "inProgress": False,
    }
    # The mission finished but did not achieve the success threshold
    incomplete = {  # noqa: RUF012
        "state": "incomplete",
        "status": InOrbitMissionStatus.WARNING.value,
        "inProgress": False,
    }
    # Unknown state, likely due to an inconsistency in the data
    unknown = {  # noqa: RUF012
        "state": "unknown",
        "status": InOrbitMissionStatus.ERROR.value,
        "inProgress": False,
    }

    @classmethod
    def get_from_status(cls, task_state: str, emergency_stop: bool) -> "MissionState":
        """Return the mission state based on the status."""
        if emergency_stop or task_state == TaskState.PAUSED:
            return cls.paused
        elif task_state == TaskState.RUNNING or task_state == TaskState.OTHER:
            return cls.in_progress
        else:
            return cls.unknown

    @staticmethod
    def get_from_end_status(
        task_end_status: int | None,
        coverage_pct: float | None,
        coverage_threshold: float,
    ) -> "MissionState | None":
        """Return the mission state based on the reported task end status.

        Only a normal end is judged against the coverage threshold; every abnormal end is
        abandoned however much got cleaned. Returns None on a status the robot does not define,
        so the caller falls back instead of guessing.
        """
        if task_end_status in TASK_END_STATUS_ABNORMAL:
            return MissionState.abandoned
        if task_end_status == TASK_END_STATUS_NORMAL:
            if coverage_pct is None or coverage_pct >= coverage_threshold:
                return MissionState.completed
            return MissionState.incomplete
        return None

    @staticmethod
    def get_for_completion(
        completion_percentage: float,
        completion_percentage_threshold: float,
        progress_percentage: float,
    ) -> "MissionState":
        """Return the mission state based on the completion percentage."""
        progress_ok = progress_percentage >= MISSION_PROGRESS_BAR_ADVANCED_PERCENTAGE_THRESHOLD
        completion_ok = completion_percentage >= completion_percentage_threshold
        if progress_ok:
            return MissionState.completed if completion_ok else MissionState.incomplete
        return MissionState.abandoned


def filter_none(data: dict[str, Any]) -> dict[str, Any]:
    """Drop ``None`` values from a dictionary, keeping falsy values like 0 and False."""
    return {k: v for k, v in data.items() if v is not None}


class MissionTracker:
    """Tracks one robot's missions and publishes InOrbit ``mission_tracking`` reports.

    After a mission finishes, it waits up to ``MAX_TASK_REPORT_WAIT_TIME_SECS`` for the
    Gausium task report to be available before publishing the final mission state.
    """

    def __init__(
        self,
        serial_number: str,
        fetch_reports: Callable[[], Awaitable[list[dict] | None]],
        fetch_report_map_images: Callable[[str], Awaitable[list[dict] | None]],
        publish: Callable[[dict], None],
        spawn_task: Callable[[str, Coroutine], asyncio.Task],
        success_threshold: float,
    ) -> None:
        """Initialize the tracker.

        Args:
            serial_number: Robot serial number, used for logging.
            fetch_reports: Zero-arg coroutine factory returning the robot's task reports
                (or ``None`` on API failure).
            fetch_report_map_images: Coroutine factory returning the coverage map images
                of one task report (or ``None`` on API failure).
            publish: Callback publishing one InOrbit mission report.
            spawn_task: Scheduler for completion waits (the connector's logged-task spawner).
            success_threshold: Cleaned-area ratio above which a finished mission is successful.
        """
        self._logger = logging.getLogger(f"{self.__class__.__name__}[{serial_number}]")
        self._fetch_reports = fetch_reports
        self._fetch_report_map_images = fetch_report_map_images
        self._publish = publish
        self._spawn_task = spawn_task
        self._success_threshold = success_threshold
        self._last_robot_status: dict[str, Any] = {}
        self._last_executing_task_id: str | None = None
        self._last_inorbit_report: dict[str, Any] = {}
        self._interruptions = 0
        # Pending completion waits keyed by task instance ID, for cancel/dedupe
        self._pending_completion_tasks: dict[str, asyncio.Task] = {}
        self._shutdown_event = asyncio.Event()

    def update(self, robot_status: dict[str, Any], robot_status_v2: dict[str, Any]) -> None:
        """Update the mission status from the latest v1 and v2 robot statuses."""
        last_executing_task = self._last_robot_status.get("executingTask", {})
        curr_executing_task = robot_status.get("executingTask", {})

        last_task_id = self._last_executing_task_id
        curr_task_id = robot_status_v2.get("currentTask", {}).get("taskInstanceId")

        # The two status sources can disagree briefly when a mission completes (v1 drops
        # "executingTask" before v2 drops "currentTask"), so require both to agree.
        robot_is_executing_mission = bool(curr_task_id and curr_executing_task)

        if not last_task_id and not curr_task_id:
            return

        # A mission was running before and it changed (or the robot stopped executing it)
        if last_task_id and (last_task_id != curr_task_id or not robot_is_executing_mission):
            self._logger.info(
                f"Mission changed: last task ID: {last_task_id}, current task ID: {curr_task_id}"
            )
            completion_data = {
                "task_instance_id": last_task_id,
                "last_inorbit_report": deepcopy(self._last_inorbit_report),
                "interruptions": self._interruptions,
            }
            self._create_mission_completion_task(completion_data)
            # Reset so the next mission's progress does not inherit this one's
            self._last_inorbit_report = {}

        if curr_task_id != last_task_id:
            self._interruptions = 0
        if (
            self._last_robot_status.get("taskState") == TaskState.RUNNING
            and robot_status.get("taskState") == TaskState.PAUSED
        ):
            self._interruptions += 1

        # If the current task actually resumed while we were waiting for its report, cancel
        # the wait. The executing check matters: while v1 has dropped "executingTask" but v2
        # still reports "currentTask" (common ordering at completion), the task is not resumed.
        if (
            curr_task_id
            and robot_is_executing_mission
            and curr_task_id in self._pending_completion_tasks
        ):
            self._logger.info(f"Task {curr_task_id} resumed, cancelling pending completion task")
            self._cancel_completion_task(curr_task_id)

        if (
            curr_task_id
            and curr_executing_task != last_executing_task
            and robot_is_executing_mission
        ):
            self._last_inorbit_report = MissionTracker._update_mission(
                robot_status, robot_status_v2, self._interruptions, self._last_inorbit_report
            )
            self._publish(self._last_inorbit_report)

        self._last_robot_status = robot_status
        self._last_executing_task_id = curr_task_id

    def _create_mission_completion_task(self, completion_data: dict) -> asyncio.Task:
        """Wait in the background for a finished mission's task report."""
        task_id = completion_data["task_instance_id"]
        if task_id in self._pending_completion_tasks:
            # Already waiting for this mission's report (the mission-changed condition
            # re-triggers every tick while v1 and v2 disagree)
            return self._pending_completion_tasks[task_id]

        task = self._spawn_task(
            f"mission-completion-{task_id}",
            self._handle_mission_completion(completion_data),
        )
        self._pending_completion_tasks[task_id] = task

        def cleanup(completed_task: asyncio.Task) -> None:
            if self._pending_completion_tasks.get(task_id) is completed_task:
                del self._pending_completion_tasks[task_id]

        task.add_done_callback(cleanup)
        return task

    def _cancel_completion_task(self, task_id: str) -> None:
        """Cancel the pending completion task for the given task ID."""
        task = self._pending_completion_tasks.pop(task_id, None)
        if task is not None and not task.done():
            task.cancel()

    async def _handle_mission_completion(self, completion_data: dict) -> None:
        """Wait for the finished mission's report and publish the final mission state."""
        try:
            last_task_report = await self._wait_for_task_report_async(
                completion_data["task_instance_id"]
            )
            if last_task_report:
                self._logger.info(f"Completing mission with report ID {last_task_report.get('id')}")
                map_images = await self._fetch_report_map_images(last_task_report.get("id"))
                completed_report = self._complete_mission(
                    last_task_report,
                    completion_data["last_inorbit_report"],
                    map_images or [],
                    completion_data["interruptions"],
                )
                self._publish(completed_report)
            else:
                self._logger.info(
                    "Could not find report for mission "
                    f"{completion_data['last_inorbit_report'].get('missionId')}."
                    " Abandoning mission."
                )
                self._publish(
                    MissionTracker._report_not_found_mission(completion_data["last_inorbit_report"])
                )
        except asyncio.CancelledError:
            self._logger.info(
                "Mission completion task cancelled for task ID: "
                f"{completion_data['task_instance_id']}"
            )
        except Exception as e:  # noqa: BLE001 -- a failed completion must not kill the task
            self._logger.error(f"Error handling mission completion: {e}")

    async def _wait_for_task_report_async(self, task_instance_id: str) -> dict[str, Any] | None:
        """Poll the reports API until a report matching ``task_instance_id`` is available."""
        start_time = time()
        while (time() - start_time) < MAX_TASK_REPORT_WAIT_TIME_SECS:
            if self._shutdown_event.is_set():
                return None
            try:
                reports = await self._fetch_reports()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 -- keep polling until the deadline
                self._logger.warning(f"Error fetching task reports: {e}")
                reports = None
            for report in reports or []:
                if report.get("taskInstanceId") == task_instance_id:
                    elapsed = round(time() - start_time, 2)
                    self._logger.info(
                        f"Found task report with taskInstanceId {task_instance_id} after {elapsed}s"
                    )
                    return report
            await asyncio.sleep(REPORT_POLL_INTERVAL_SECS)

        self._logger.error(
            f"Timed out waiting for task report with taskInstanceId {task_instance_id}"
        )
        return None

    async def shutdown(self) -> None:
        """Cancel and await all pending report waits."""
        self._shutdown_event.set()
        tasks = [task for task in self._pending_completion_tasks.values() if not task.done()]
        self._pending_completion_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _update_mission(
        robot_status: dict[str, Any],
        robot_status_v2: dict[str, Any],
        interruptions: int,
        previous_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return an InOrbit mission report based on the robot status data."""
        previous_report = previous_report or {}
        executing_task = robot_status.get("executingTask", {})
        task_id = robot_status_v2.get("currentTask", {}).get("taskInstanceId")
        name = executing_task.get("name", task_id)
        progress = max(0, min(100, executing_task.get("progress", 0)))  # From 0 to 100
        # Empirically, timeRemaining seems to be the time elapsed
        time_elapsed = executing_task.get("timeRemaining")

        task_state = robot_status.get("taskState")
        emergency_stop = robot_status.get("emergencyStop", {}).get("enabled")

        state = MissionState.get_from_status(task_state, emergency_stop)

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
            "map_name": robot_status.get("localizationInfo", {}).get("map", {}).get("name"),
            "task_id": executing_task.get("id"),
            "task_instance_id": task_id,
            "distance_m": executing_task.get("cleaningMileage"),
            "active_cleaning_time_s": (
                round(time_elapsed) if isinstance(time_elapsed, Number) else None
            ),
            "task_state": normalize_task_state(task_state) if task_state else None,
            "task_state_raw": task_state,
            "interruptions_count": interruptions,
            **cleaning_mode_keys(
                robot_status_v2.get("currentTask", {}).get("workMode", {}).get("name")
            ),
        }

        return {
            **state.value,
            "missionId": task_id,
            "label": name,
            "completedPercent": completed_percent,
            "estimatedDurationSecs": estimated_duration_secs,
            "data": filter_none(details),
        }

    def _complete_mission(
        self,
        task_report: dict[str, Any],
        last_inorbit_report: dict[str, Any],
        map_images: list[dict],
        interruptions: int,
    ) -> dict[str, Any]:
        """Complete a previous mission based on its report data."""
        inorbit_report = deepcopy(last_inorbit_report)

        report_id = task_report.get("id")
        task_end_status = task_report.get("taskEndStatus")
        data = report_to_data(
            task_report,
            current_map_name=self._last_robot_status.get("localizationInfo", {})
            .get("map", {})
            .get("name"),
            interruptions_count=interruptions,
        )
        # Coverage renders, one key with the URLs joined in vendor index order
        heatmap_urls = [
            image.get("url")
            for image in sorted(map_images, key=lambda image: image.get("map_image_id", 0))
            if image.get("url")
        ]
        if heatmap_urls:
            data["coverage_heatmap_url"] = ", ".join(heatmap_urls)

        # Calculated InOrbit mission data
        inorbit_report["inProgress"] = False
        inorbit_report["label"] = task_report.get("displayName")

        # Set the state and status based on how the robot says the task ended, falling back to
        # the coverage and progress bar heuristic when it reports a status it does not define
        coverage_pct = data.get("coverage_pct")
        last_progress_bar_percentage = last_inorbit_report.get("completedPercent", 0)
        state = MissionState.get_from_end_status(
            task_end_status, coverage_pct, self._success_threshold
        )
        if state:
            data["task_outcome"] = state.value["state"]
        else:
            state = MissionState.get_for_completion(
                coverage_pct or 0, self._success_threshold, last_progress_bar_percentage
            )

        if state is MissionState.incomplete:
            data["Error"] = (
                f"Mission failed to achieve a completion percentage of "
                f"{self._success_threshold * 100}%"
            )
        elif state is MissionState.abandoned:
            data["Error"] = f"Mission ended with task end status {task_end_status}"
        inorbit_report.update(state.value)

        self._logger.info(
            f"Mission {report_id} ended as {state.value['state']} with coverage {coverage_pct}"
        )
        # Show the fraction of the plan actually covered
        inorbit_report["completedPercent"] = (
            coverage_pct if coverage_pct is not None else last_progress_bar_percentage
        )
        # Wall time is the honest figure for a finished mission
        inorbit_report["estimatedDurationSecs"] = data.get("duration_s")
        inorbit_report["startTs"] = report_time_to_millis(task_report.get("startTime"))
        inorbit_report["endTs"] = report_time_to_millis(task_report.get("endTime"))
        inorbit_report["data"] = filter_none(data)

        return inorbit_report

    @staticmethod
    def _report_not_found_mission(last_inorbit_report: dict[str, Any]) -> dict[str, Any]:
        """Return an InOrbit mission report for a mission whose report was never found."""
        inorbit_report = deepcopy(last_inorbit_report)
        inorbit_report.update(MissionState.not_reported.value)
        inorbit_report["data"] = {"Error": "Unable to find task report."}
        return inorbit_report
