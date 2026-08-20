# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Per-robot mission tracking: turns Gausium task status into InOrbit mission events."""

# Standard
import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Coroutine
from copy import deepcopy
from datetime import datetime
from enum import Enum, StrEnum
from numbers import Number
from time import time
from typing import Any

# The progress bar is advanced to 100% if the progress percentage is greater than this threshold
MISSION_PROGRESS_BAR_ADVANCED_PERCENTAGE_THRESHOLD = 0.90

# Max time to wait for a task report to be available
MAX_TASK_REPORT_WAIT_TIME_SECS = 10 * 60  # 10 minutes

REPORT_POLL_INTERVAL_SECS = 0.5

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

# Vendor cleaning modes mapped to the cleaning-vertical contract enum. Only unambiguous
# modes are mapped; intensity variants and the rest normalize to "other", with the vendor
# value always preserved under cleaning_mode_raw.
CLEANING_MODE_CANONICAL = {
    "洗地": "scrub",
    "滚刷洗地": "scrub",
    "尘推": "dust_mop",
    "快速尘推": "dust_mop",
    "低速尘推": "dust_mop",
    "静音推尘": "dust_mop",
    "布刷尘推": "dust_mop",
    "抛光": "polish",
    "深度抛光": "polish",
    "结晶模式": "polish",
    "吸尘": "vacuum",
    "吸风清洁": "vacuum",
    "suction_cleaning": "vacuum",
    "扫地": "sweep",
    "喷雾消毒": "disinfect",
}

# taskEndStatus enum from the vendor docs: -1 Unknown, 0 Normal, 1 Manual, 2 Error,
# 3 Startup failure. Any abnormal end is abandoned regardless of coverage.
TASK_END_STATUS_LABELS = {1: "manual stop", 2: "error", 3: "startup failure"}


class TaskState(StrEnum):
    """Task states reported by the Gausium status endpoints."""

    OTHER = "OTHER"
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"


# Vendor task states mapped to the cleaning-vertical contract enum
TASK_STATE_CANONICAL = {
    TaskState.IDLE: "idle",
    TaskState.RUNNING: "cleaning",
    TaskState.PAUSED: "paused",
}


def normalize_task_state(task_state: str | None) -> str | None:
    """Normalize a vendor task state to the contract enum (unrecognized -> "unknown")."""
    if task_state is None:
        return None
    return TASK_STATE_CANONICAL.get(task_state, "unknown")


def normalize_cleaning_mode(cleaning_mode: str) -> str:
    """Normalize a vendor cleaning mode to the contract enum (unmapped -> "other")."""
    return CLEANING_MODE_CANONICAL.get(cleaning_mode.lstrip("_"), "other")


def derive_task_outcome(
    task_end_status: Any, coverage: float | None, success_threshold: float
) -> str | None:
    """Derive the contract task outcome from the vendor task end status.

    Only a normal end is judged against the coverage threshold; abnormal ends are
    abandoned regardless. An unknown or absent status returns ``None`` (key omitted).
    """
    if task_end_status in TASK_END_STATUS_LABELS:
        return "abandoned"
    if task_end_status == 0:
        if coverage is not None and coverage < success_threshold:
            return "incomplete"
        return "completed"
    return None


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


def to_inorbit_millis(date: str | float | None) -> int | None:
    """Convert a report timestamp to epoch milliseconds for InOrbit missions.

    Accepts both transports: the polled API sends ISO 8601 strings, the push
    callback sends epoch milliseconds.
    """
    if date is None or date == "":
        return None
    if isinstance(date, Number):
        return int(date)
    return int(datetime.fromisoformat(date).timestamp() * 1000)


def _slug(name: str) -> str:
    """Lowercase a map name and collapse non-alphanumeric runs to ``_``."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "unnamed"


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
            "task_state": normalize_task_state(task_state),
            "distance_m": executing_task.get("cleaningMileage"),
            "active_cleaning_time_s": (
                round(time_elapsed) if isinstance(time_elapsed, Number) else None
            ),
            "interruptions_count": interruptions,
        }
        cleaning_mode = robot_status_v2.get("currentTask", {}).get("workMode", {}).get("name")
        if cleaning_mode:
            details["cleaning_mode"] = normalize_cleaning_mode(cleaning_mode)
            details["cleaning_mode_raw"] = cleaning_mode

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
        previous_data = last_inorbit_report.get("data", {})

        start_ts = to_inorbit_millis(task_report.get("startTime"))
        end_ts = to_inorbit_millis(task_report.get("endTime"))
        duration_s = (
            round((end_ts - start_ts) / 1000)
            if start_ts is not None and end_ts is not None
            else None
        )
        active_time_s = task_report.get("durationSeconds")

        planned_area = task_report.get("plannedCleaningAreaSquareMeter")
        cleaned_area = task_report.get("actualCleaningAreaSquareMeter")
        # Cleaned over planned, per the contract; the vendor's own completionPercentage is
        # only the fallback when an area is missing
        if planned_area and cleaned_area is not None:
            coverage = round(min(max(cleaned_area / planned_area, 0.0), 1.0), 4)
        else:
            coverage = task_report.get("completionPercentage")

        # Computed from cleaned area and active time, per the contract; the vendor divides
        # by an undocumented time base
        if cleaned_area is not None and active_time_s:
            efficiency = round(cleaned_area / (active_time_s / 3600), 1)
        else:
            efficiency = task_report.get("efficiencySquareMeterPerHour")

        battery_start = task_report.get("startBatteryPercentage")
        battery_end = task_report.get("endBatteryPercentage")
        # A run that recharges mid-task ends higher than it started; withhold the
        # difference rather than publish a negative figure
        battery_used = (
            (battery_start - battery_end) / 100
            if battery_start is not None
            and battery_end is not None
            and battery_start >= battery_end
            else None
        )

        end_status = task_report.get("taskEndStatus")
        outcome = derive_task_outcome(end_status, coverage, self._success_threshold)

        sub_tasks = task_report.get("subTasks") or []
        map_names = list(dict.fromkeys(st.get("mapName") for st in sub_tasks if st.get("mapName")))
        heatmap_urls = [
            image.get("url")
            for image in sorted(map_images, key=lambda image: image.get("map_image_id", 0))
            if image.get("url")
        ]
        cleaning_mode = task_report.get("cleaningMode")
        consumables = task_report.get("consumablesResidualPercentage", {})

        details = {
            "task_outcome": outcome,
            "task_end_status_raw": end_status,
            "planned_area_m2": planned_area,
            "cleaned_area_m2": cleaned_area,
            "coverage_pct": coverage,
            "duration_s": duration_s,
            "active_cleaning_time_s": active_time_s,
            "efficiency_m2ph": efficiency,
            "water_used_l": task_report.get("waterConsumptionLiter"),
            "battery_start_pct": battery_start / 100 if battery_start is not None else None,
            "battery_end_pct": battery_end / 100 if battery_end is not None else None,
            "battery_used_pct": battery_used,
            "interruptions_count": interruptions,
            "cleaning_mode": normalize_cleaning_mode(cleaning_mode) if cleaning_mode else None,
            "cleaning_mode_raw": cleaning_mode or None,
            "task_instance_id": task_report.get("taskInstanceId"),
            "task_progress": task_report.get("taskProgress"),
            "map_name": ", ".join(map_names) if map_names else previous_data.get("map_name"),
            "floors_cleaned_count": len(sub_tasks) if sub_tasks else None,
            "report_image_url": task_report.get("taskReportPngUri"),
            "coverage_heatmap_url": ", ".join(heatmap_urls) if heatmap_urls else None,
            "polished_area_planned_m2": task_report.get("plannedPolishingAreaSquareMeter"),
            "polished_area_m2": task_report.get("actualPolishingAreaSquareMeter"),
            "operator": task_report.get("operator"),
            "report_id": task_report.get("id"),
            "task_id": task_report.get("taskId"),
            "plan_id": task_report.get("planId"),
            "area_names": task_report.get("areaNameList"),
            "loop_count": task_report.get("loopCount"),
            "expected_loop_count": task_report.get("expectedLoopCount"),
            "consumable_brush_pct": (
                consumables["brush"] / 100 if consumables.get("brush") is not None else None
            ),
            "consumable_filter_pct": (
                consumables["filter"] / 100 if consumables.get("filter") is not None else None
            ),
            "consumable_suction_blade_pct": (
                consumables["suctionBlade"] / 100
                if consumables.get("suctionBlade") is not None
                else None
            ),
        }
        # Per-map cleaned area, one scalar per sub-task so it stays KPI-definable.
        # Per-map planned area has no vendor field, so no per-map coverage is computed.
        slug_counts: dict[str, int] = {}
        for sub_task in sub_tasks:
            slug = _slug(sub_task.get("mapName") or "")
            slug_counts[slug] = slug_counts.get(slug, 0) + 1
            if slug_counts[slug] > 1:
                slug = f"{slug}_{slug_counts[slug]}"
            details[f"map_{slug}_cleaned_area_m2"] = sub_task.get("actualCleaningAreaSquareMeter")

        inorbit_report["inProgress"] = False
        inorbit_report["label"] = task_report.get("displayName")

        last_progress_bar_percentage = last_inorbit_report.get("completedPercent", 0)
        if outcome is not None:
            state = MissionState[outcome]
        else:
            # Unknown vendor end status: fall back to the progress-bar heuristic
            state = MissionState.get_for_completion(
                coverage or 0, self._success_threshold, last_progress_bar_percentage
            )
        if state is MissionState.incomplete:
            details["Error"] = (
                f"Mission failed to achieve a completion percentage of "
                f"{self._success_threshold * 100}%"
            )
        elif outcome == "abandoned":
            details["Error"] = f"Task ended abnormally: {TASK_END_STATUS_LABELS[end_status]}"
        inorbit_report.update(state.value)

        self._logger.info(
            f"Completing mission {task_report.get('id')} as {state.value['state']} "
            f"with coverage {coverage}"
        )
        # The progress bar shows the fraction of the plan actually covered
        inorbit_report["completedPercent"] = (
            coverage if coverage is not None else last_progress_bar_percentage
        )
        inorbit_report["estimatedDurationSecs"] = (
            duration_s if duration_s is not None else active_time_s
        )
        inorbit_report["startTs"] = start_ts
        inorbit_report["endTs"] = end_ts
        inorbit_report["data"] = filter_none(details)

        return inorbit_report

    @staticmethod
    def _report_not_found_mission(last_inorbit_report: dict[str, Any]) -> dict[str, Any]:
        """Return an InOrbit mission report for a mission whose report was never found."""
        inorbit_report = deepcopy(last_inorbit_report)
        inorbit_report.update(MissionState.not_reported.value)
        inorbit_report["data"] = {"Error": "Unable to find task report."}
        return inorbit_report

    @staticmethod
    def _translate_cleaning_mode(cleaning_mode: str) -> str:
        """Translate the reported cleaning mode to English."""
        cleaning_mode_name = cleaning_mode.replace("_", "")
        return CLEANING_MODE_TRANSLATION.get(cleaning_mode_name, cleaning_mode_name)
