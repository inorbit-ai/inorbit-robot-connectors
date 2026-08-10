# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import logging
from datetime import datetime
from inorbit_edge.missions import MISSION_STATE_EXECUTING, MISSION_STATE_ABORTED

# Mission states
MISSION_STATE_DONE = "Done"
MISSION_STATE_ABORT = "Abort"


class MirNativeMissionTasks:
    """Per-action InOrbit task progress for one native (robot-triggered) mission.

    Tasks are the mission definition's actions. Progress comes from the mission
    queue actions endpoints: each executed queue action's ``action_id`` equals a
    definition action guid. Completed tasks never downgrade; poll failures keep
    the previous states.
    """

    def __init__(self, mir_api, queue_id, tasks):
        self.logger = logging.getLogger(name=self.__class__.__name__)
        self._mir_api = mir_api
        self._queue_id = queue_id
        # Ordered {definition action guid: task dict}, mutated in place as progress arrives.
        self._tasks = tasks
        self._current_task_id = None
        # queue-action int id -> (action_id guid, finished bool). Finished entries are
        # never re-fetched, so steady state costs one shallow GET per poll.
        self._detail_cache = {}

    async def poll(self):
        """Refresh task states from the mission queue actions. Never raises."""
        try:
            entries = await self._mir_api.get_mission_queue_actions(self._queue_id)
            for entry in entries:
                int_id = entry.get("id")
                cached = self._detail_cache.get(int_id)
                if cached is not None and cached[1]:
                    continue
                detail = await self._mir_api.get_mission_queue_action(self._queue_id, int_id)
                self._detail_cache[int_id] = (
                    detail.get("action_id"),
                    detail.get("finished") is not None,
                )
        except Exception as e:
            self.logger.warning(f"Failed to poll actions of mission queue {self._queue_id}: {e}")
            return
        self._apply()

    def _apply(self):
        """Fold the detail cache (in execution order) into task states."""
        current = None
        for guid, finished in self._detail_cache.values():
            task = self._tasks.get(guid)
            if task is None:  # foreign guid, e.g. a load_mission inlined sub-action
                continue
            if finished:
                task["completed"] = True
                task["inProgress"] = False
            elif not task["completed"]:
                task["inProgress"] = True
                current = guid
        self._current_task_id = current

    def report_fields(self):
        """``tasks``/``completedPercent``/``currentTaskId`` fields for the report payload."""
        tasks = list(self._tasks.values())
        completed = sum(1 for t in tasks if t["completed"])
        fields = {
            "tasks": [dict(t) for t in tasks],
            "completedPercent": completed / len(tasks) if tasks else 0,
        }
        if self._current_task_id:
            fields["currentTaskId"] = self._current_task_id
        return fields

    def signature(self):
        """Hashable snapshot of task states, for report deduplication."""
        return (
            self._current_task_id,
            tuple((t["inProgress"], t["completed"]) for t in self._tasks.values()),
        )


class MirInorbitMissionTracking:

    def __init__(
        self,
        mir_api,
        inorbit_sess,
        robot_tz_info,
        mission_executor,
    ):
        self.logger = logging.getLogger(name=self.__class__.__name__)
        self.executing_mission_id = None
        self.last_reported_mission_id = None
        self.last_reported_mission_progress = 0.0
        self.waiting_for_text = ""  # Text used to control waitUntil in missions
        self.mir_api = mir_api
        self.inorbit_sess = inorbit_sess
        self.robot_tz_info = robot_tz_info
        self.mission_executor = mission_executor

    def _safe_localize_timestamp(self, timestamp_str: str) -> float:
        """Convert ISO timestamp string to Unix timestamp, handling timezone conversion.

        If timestamp lacks timezone info, applies robot's timezone.
        If timestamp already has timezone info, uses it directly.
        """
        try:
            dt = datetime.fromisoformat(timestamp_str)
            # If datetime already has timezone info, just convert to timestamp
            if dt.tzinfo is not None:
                return dt.timestamp()
            # If datetime is naive, localize it to robot timezone
            else:
                return self.robot_tz_info.localize(dt).timestamp()
        except Exception as e:
            self.logger.warning(f"Failed to parse timestamp '{timestamp_str}': {e}")
            # Return current time as fallback
            return datetime.now().timestamp()

    async def get_current_mission(self):
        """Return the current mission, it's either executing or just ended"""
        mission = None
        if self.executing_mission_id is None:
            self.executing_mission_id = await self.mir_api.get_executing_mission_id()
        if self.executing_mission_id:
            mission = await self.mir_api.get_mission(self.executing_mission_id)
            if mission["state"] != MISSION_STATE_EXECUTING:
                # Update executing_mission_id so the next call to this method returns the next
                # executing mission or None.
                # Note that the current call in this case returns the just finished mission
                self.executing_mission_id = None
        return mission

    async def report_mission(self, status, metrics):
        # When the edge mission executor is running an InOrbit-dispatched mission, it owns
        # mission tracking. Skip robot-side polling to avoid duplicate reports.
        if await self.mission_executor.has_active_mission():
            return
        mission = await self.get_current_mission()
        if mission:
            completed_percent = len(mission["actions"]) / len(mission["definition"]["actions"])
            # Merge 'Abort' and 'Aborted' values into a single state
            if mission["state"] == MISSION_STATE_ABORT:
                mission["state"] = MISSION_STATE_ABORTED
            if (
                mission["id"] == self.last_reported_mission_id
                and mission["state"] == MISSION_STATE_EXECUTING
                and completed_percent == self.last_reported_mission_progress
            ):
                # Avoid flooding mission reports when nothing important has changed
                return
            mission_values = {
                "missionId": mission["id"],
                "inProgress": mission["state"] == MISSION_STATE_EXECUTING,
                "state": mission["state"],
                "label": mission["definition"]["name"],
                "startTs": self._safe_localize_timestamp(mission["started"]) * 1000,
                "data": {
                    "Total Distance (m)": metrics.get(
                        "mir_robot_distance_moved_meters_total", "N/A"
                    ),
                    "Mission Steps": len(mission["definition"]["actions"]),
                    "Total Missions": mission["id"],
                    "Robot Model": status["robot_model"],
                    "Uptime (s)": status["uptime"],
                    "Serial Number": status.get("serial_number", "N/A"),
                    "Battery Time Remaning (s)": status.get("battery_time_remaining", "N/A"),
                    "WiFi RSSI (dbm)": metrics.get("mir_robot_wifi_access_point_rssi_dbm", "N/A"),
                },
            }
            if mission.get("finished") is not None:
                mission_values["endTs"] = self._safe_localize_timestamp(mission["finished"]) * 1000
                mission_values["completedPercent"] = 1
                mission_values["status"] = (
                    "OK" if mission["state"] == MISSION_STATE_DONE else "error"
                )
            else:
                mission_values["completedPercent"] = completed_percent

            self.logger.debug(f"Reporting mission: {mission_values}")
            self.inorbit_sess.publish_key_values(
                key_values={"mission_tracking": mission_values}, is_event=True
            )
            self.last_reported_mission_progress = completed_percent
            self.last_reported_mission_id = mission["id"]
