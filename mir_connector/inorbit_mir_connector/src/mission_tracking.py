# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import logging
import re
from datetime import datetime
from inorbit_edge.missions import MISSION_STATE_EXECUTING, MISSION_STATE_ABORTED

from .mission.translator import _SCOPE_BEARING_DENIED

# Mission states
MISSION_STATE_DONE = "Done"
MISSION_STATE_ABORT = "Abort"

# Max detail GETs issued in a single poll tick.
_MAX_DETAIL_FETCHES_PER_POLL = 25

# A substitution in a MiR action description, e.g. "%(position)s" or "%(register)d".
_PLACEHOLDER = re.compile(r"%\((\w+)\)[a-z]")
# MiR durations are "HH:MM:SS.ffffff".
_DURATION = re.compile(r"^(\d+):(\d{2}):(\d{2})(?:\.\d+)?$")


def _pretty_duration(value):
    """Render a MiR duration as "1 min 30 sec"; None when the value is not one."""
    match = _DURATION.match(str(value))
    if not match:
        return None
    hours, minutes, seconds = (int(g) for g in match.groups())
    parts = [f"{n} {unit}" for n, unit in ((hours, "h"), (minutes, "min"), (seconds, "sec")) if n]
    return " ".join(parts) or "0 sec"


def _resolve_parameter(value, spec):
    """Display text for one action parameter value, or None when it cannot be resolved.

    ``Reference`` and ``Selection`` parameters carry the whole value-to-name mapping in
    their own constraints, which is how a position guid becomes "Dock charger 285"
    without asking the robot anything.
    """
    param_type = spec.get("type")
    if param_type in ("Reference", "Selection"):
        choices = (spec.get("constraints") or {}).get("choices") or []
        # MiR is loose about types here: a choice value may be int 1 where the action
        # stores the string "1".
        match = next((c for c in choices if str(c.get("value")) == str(value)), None)
        if match is None:
            # Typically a deleted position still referenced by the mission.
            return None
        # Some references (PLC registers) have blank names; the raw value is the label.
        return match.get("name") or str(value)
    if param_type == "Duration":
        return _pretty_duration(value)
    return None if value is None else str(value)


def _render_label(action, definition):
    """Operator-facing label for a definition action, built from MiR's own metadata.

    Every action type ships a ``description`` template ("Move to %(position)s") and, per
    parameter, the type and value list needed to fill it in. Falls back to the action's
    display name, then to its raw type, so an unresolvable placeholder yields "Move"
    rather than a guid. Nothing here is per-action-type.
    """
    # Not every action type is listed in GET /actions (load_mission is not), so the raw
    # type is the last resort: "load_mission" -> "Load mission".
    name = definition.get("name") or action["action_type"].replace("_", " ").capitalize()
    template = definition.get("description")
    if not template:
        return name
    specs = {p["id"]: p for p in definition.get("parameters") or []}
    resolved = {
        p["id"]: _resolve_parameter(p.get("value"), specs.get(p["id"], {}))
        for p in action.get("parameters") or []
        if p.get("id")
    }
    complete = True

    def substitute(match):
        nonlocal complete
        text = resolved.get(match.group(1))
        if not text:
            complete = False
            return ""
        return text

    label = _PLACEHOLDER.sub(substitute, template).strip()
    return label if complete and label else name


def _execution_order(actions):
    """Mission definition actions in the order the robot runs them.

    ``GET /missions/{id}/actions`` returns them in no useful order, and ``priority`` is
    not a global rank: it orders siblings within one scope only, and each scope numbers
    its own children (two actions in different scopes routinely share a priority). The
    list is a tree, linked by ``scope_reference`` -> the guid of a *parameter* of the
    containing action, null at the top level. So this is a DFS pre-order, which is also
    what an operator reads top to bottom.

    No list of scope-bearing action types is needed: a parameter guid that something
    points at is, by definition, a scope.
    """
    children = {}
    for action in actions:
        children.setdefault(action.get("scope_reference"), []).append(action)
    for siblings in children.values():
        siblings.sort(key=lambda a: a.get("priority") or 0)
    ordered = []
    # Guards against a parameter guid that loops back to an enclosing scope. Malformed
    # input would otherwise hang the poll loop; None is seeded because it is the root key
    # and an unset parameter guid must not be read as "nested at the top level".
    walked = {None}

    def walk(scope):
        for action in children.get(scope, []):
            ordered.append(action)
            for param in action.get("parameters") or []:
                nested = param.get("guid")
                if nested in children and nested not in walked:
                    walked.add(nested)
                    walk(nested)

    walk(None)
    # Anything unreachable from the root (a scope_reference we never saw as a parameter)
    # is appended rather than dropped, so a task is never silently lost.
    placed = {id(a) for a in ordered}
    return ordered + [a for a in actions if id(a) not in placed]


def _action_outcome(detail):
    """``(finished, succeeded)`` for a queue action detail.

    ``finished`` is a timestamp on failures too, so it alone does not mean success: a
    successful action reports an empty ``state``, a failed one "Failed" or "Aborted".
    The two flags are kept apart because a failed action is neither still running nor
    completed, and InOrbit tasks express that as both booleans false.
    """
    finished = detail.get("finished") is not None
    return finished, finished and not detail.get("state")


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
        # queue-action int id -> (action_id guid, finished bool, succeeded bool). Finished
        # entries are never re-fetched, so steady state costs one shallow GET per poll.
        self._detail_cache = {}

    async def poll(self):
        """Refresh task states from the mission queue actions. Never raises."""
        try:
            entries = await self._mir_api.get_mission_queue_actions(self._queue_id)
            fetched = 0
            for entry in entries:
                int_id = entry.get("id")
                cached = self._detail_cache.get(int_id)
                if cached is not None and cached[1]:
                    continue
                if fetched >= _MAX_DETAIL_FETCHES_PER_POLL:
                    # ponytail: caps the catch-up burst when attaching mid-mission; later
                    # ticks converge.
                    break
                detail = await self._mir_api.get_mission_queue_action(self._queue_id, int_id)
                self._detail_cache[int_id] = (detail.get("action_id"), *_action_outcome(detail))
                fetched += 1
        except Exception as e:
            self.logger.warning(f"Failed to poll actions of mission queue {self._queue_id}: {e}")
            return
        self._apply()

    def _apply(self):
        """Fold the detail cache (in execution order) into task states."""
        current = None
        for guid, finished, succeeded in self._detail_cache.values():
            task = self._tasks.get(guid)
            if task is None:  # foreign guid, e.g. a load_mission inlined sub-action
                continue
            if succeeded:
                task["completed"] = True
                task["inProgress"] = False
            elif finished:
                # Ran and failed: not completed, and no longer running either.
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
        # {action_type: definition}, one fetch for the life of the connector. Carries the
        # label templates and the parameter value lists task labels are rendered from.
        self._action_definitions = None
        self._mission_definition = None  # definition of the tracked mission, one fetch per entry
        self._tasks_tracker = None  # MirNativeMissionTasks for the tracked queue entry
        self.last_reported_tasks_signature = None

    async def _get_action_definitions(self):
        """{action_type: definition}, fetched once and cached; {} (and a retry on the next
        mission) when the fetch fails."""
        if self._action_definitions is None:
            try:
                defs = await self.mir_api.get_action_definitions()
                self._action_definitions = {
                    d["action_type"]: d for d in defs if d.get("action_type")
                }
            except Exception as e:
                self.logger.warning(f"Failed to fetch MiR action definitions: {e}")
                return {}
        return self._action_definitions

    async def _build_tasks(self, actions):
        """{guid: task dict} in execution order, one task per real mission step.

        Scope-bearing actions (loop, if, try_catch, ...) are containers, not steps: they
        are what the nested actions hang off, they need not ever report finished, and
        while their body runs they would show as a second task in progress. Their
        children stay, in place.
        """
        definitions = await self._get_action_definitions()
        tasks = {}
        for action in _execution_order(actions):
            guid = action.get("guid")
            if not guid or action.get("action_type") in _SCOPE_BEARING_DENIED:
                continue
            tasks[guid] = {
                "taskId": guid,
                "label": _render_label(action, definitions.get(action["action_type"], {})),
                "inProgress": False,
                "completed": False,
            }
        return tasks

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
        """Return the current mission, it's either executing or just ended.

        The queue entry is fetched every tick; the definition (with actions) once per
        queue entry, when the per-action task tracker is also (re)built. Entries with no
        ``mission_id`` have no definition and get ``None`` for it.
        """
        if self.executing_mission_id is None:
            self.executing_mission_id = await self.mir_api.get_executing_mission_id()
            self._mission_definition = None
            self._tasks_tracker = None
        if not self.executing_mission_id:
            return None
        queue_id = self.executing_mission_id
        mission = await self.mir_api.get_mission_queue_entry(queue_id)
        # Fleet-dispatched ActionLists carry no mission_id, and are the majority of the queue
        # on a fleet-managed robot. There is no definition to fetch (GET /missions/None is a
        # 400) and their queue actions have a null action_id, so they are reported without a
        # task list rather than raising on every tick.
        if mission.get("mission_id") and self._mission_definition is None:
            definition = await self.mir_api.get_mission_definition(mission["mission_id"])
            definition["actions"] = await self.mir_api.get_mission_actions(mission["mission_id"])
            self._mission_definition = definition
            self._tasks_tracker = MirNativeMissionTasks(
                self.mir_api, queue_id, await self._build_tasks(definition["actions"])
            )
        mission["definition"] = self._mission_definition
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
        if not mission:
            return
        tracker = self._tasks_tracker
        task_fields = {}
        completed_percent = None
        if tracker is not None:
            await tracker.poll()
            task_fields = tracker.report_fields()
            completed_percent = task_fields.pop("completedPercent")
        # Merge 'Abort' and 'Aborted' values into a single state
        if mission["state"] == MISSION_STATE_ABORT:
            mission["state"] = MISSION_STATE_ABORTED
        tasks_signature = tracker.signature() if tracker is not None else None
        if (
            mission["id"] == self.last_reported_mission_id
            and mission["state"] == MISSION_STATE_EXECUTING
            and completed_percent == self.last_reported_mission_progress
            and tasks_signature == self.last_reported_tasks_signature
        ):
            # Avoid flooding mission reports when nothing important has changed
            return
        definition = mission["definition"]
        mission_values = {
            "missionId": mission["id"],
            "inProgress": mission["state"] == MISSION_STATE_EXECUTING,
            "state": mission["state"],
            "startTs": self._safe_localize_timestamp(mission["started"]) * 1000,
            "data": {
                "Total Distance (m)": metrics.get("mir_robot_distance_moved_meters_total", "N/A"),
                "Total Missions": mission["id"],
                "Robot Model": status["robot_model"],
                "Uptime (s)": status["uptime"],
                "Serial Number": status.get("serial_number", "N/A"),
                "Battery Time Remaning (s)": status.get("battery_time_remaining", "N/A"),
                "WiFi RSSI (dbm)": metrics.get("mir_robot_wifi_access_point_rssi_dbm", "N/A"),
            },
            **task_fields,
        }
        if definition is not None:
            mission_values["label"] = definition["name"]
            mission_values["data"]["Mission Steps"] = len(definition["actions"])
        if mission.get("finished") is not None:
            mission_values["endTs"] = self._safe_localize_timestamp(mission["finished"]) * 1000
            mission_values["completedPercent"] = 1
            mission_values["status"] = "OK" if mission["state"] == MISSION_STATE_DONE else "error"
        elif completed_percent is not None:
            mission_values["completedPercent"] = completed_percent

        self.logger.debug(f"Reporting mission: {mission_values}")
        self.inorbit_sess.publish_key_values(
            key_values={"mission_tracking": mission_values}, is_event=True
        )
        self.last_reported_mission_progress = completed_percent
        self.last_reported_mission_id = mission["id"]
        self.last_reported_tasks_signature = tasks_signature
