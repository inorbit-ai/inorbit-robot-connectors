# SPDX-FileCopyrightText: 2026 Mappalink
#
# SPDX-License-Identifier: MIT
#
# Vendored from the Mappalink MiR connector:
#   https://github.com/mappalink/inorbit-mir-connector/blob/c516f7d9e8e6b8b3cbaa396e2984ce149c6e7925/mir_connector/src/mission/behavior_tree.py
# Upstream commit: c516f7d9e8e6b8b3cbaa396e2984ce149c6e7925 (2026-05-21)
#
# Modifications from upstream:
#   - 2026-06-26: rebased import prefix mir_connector.src.* -> inorbit_mir_connector.src.*
#   - 2026-06-26: MirApi -> MirApiV2 (our class is MirApiV2; no alias) in import + type hints
#   - 2026-06-26: added "# noqa: E501" to one long line (vendored ruff style, not relinted)
#   - 2026-06-26: StrEnum import fallback for Python 3.10 (enum.StrEnum added in 3.11)
#   - 2026-06-27: replaced _STATE_DONE/_STATE_ABORT string constants with a
#     MirMissionQueueState(StrEnum) for consistency with connector enums
#   - 2026-06-27: renamed local n -> n_actions in CreateMirNativeMissionNode._execute
#   - 2026-06-27: scoped abort: MirMissionAbortedNode/CleanupMirMissionNode now call
#     abort_mission(queue_id) (DELETE /mission_queue/{id}) instead of abort_all_missions,
#     so other queued/fleet missions survive; no fallback when the queue id is absent
#   - 2026-06-27: CleanupMirMissionNode.__init__ now stores context.shared_memory (needed
#     to read the queue id for the scoped abort above)
#   - 2026-06-27: made the missing-missions-group runtime error operator-actionable (names the
#     two fixes: enable_temporary_mission_group, or configure a predefined missions group)
#   - 2026-06-30: CreateMirNativeMissionNode.dump_object now dumps the step with by_alias=True
#     so a bounded/tracked native step (timeoutSecs/completeTask) round-trips on resume
#   - 2026-06-30: WaitForMirMissionCompletionNode now reports per-action InOrbit task
#     progress, replacing the per-step TaskStarted/CompletedNode the SDK decorator can no
#     longer emit once steps are grouped. A grouped native step carries action_task_ids
#     (parallel to its actions). CreateMirNativeMissionNode captures the guid each
#     add_action_to_mission returns into shared memory (MIR_ACTION_GUIDS, ordered parallel to
#     the actions); the completion node pairs each guid with its task id, then per poll
#     resolves each queued action's action_id (== that guid) via GET /mission_queue/{id}/
#     actions/{int_id} and marks the paired task in_progress/completed from the action's
#     `finished` timestamp. Matching by guid (not list length) ignores a load_mission's
#     inlined sub-actions, whose guids are foreign to our set, so nested missions no longer
#     over-complete. Best-effort: a tracking error never aborts the completion poll.
#   - 2026-07-29 Tomás Badenes: InOrbit routes support: build MiR guided_move actions from
#     MirGuidedMove entries (the full schema parameter set is required, the robot applies
#     no server-side defaults; center-based deviation, as footprint mode rejects
#     corridors narrower than the robot diagonal; no-corridor legs use line-following
#     radiuses, edge 0 / node 0.3, so overlapping edges cannot cut the corner;
#     guided_move_id carries a deterministic identity) and track their per-waypoint
#     tasks via GET /guided_move, applying a status only when its guided_move_id matches the
#     identity sent with the action (the endpoint reports current-or-latest); otherwise
#     degrade to mark-at-end.

"""Custom behavior tree nodes for executing compiled native MiR missions.

The tree for a single MissionStepExecuteMirNativeMission step:

    BehaviorTreeSequential("Navigate N waypoints")
      +-- CreateMirNativeMissionNode   -> create_mission + N x add_action + queue
      +-- WaitForMirMissionCompletionNode -> poll mission_queue until Done/Abort
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

try:
    from enum import StrEnum  # Python >= 3.11
except ImportError:  # Python 3.10
    from enum import Enum

    class StrEnum(str, Enum):
        pass


from typing import Optional

from inorbit_edge_executor.behavior_tree import (
    BehaviorTree,
    BehaviorTreeBuilderContext,
    BehaviorTreeSequential,
    MissionAbortedNode,
    NodeFromStepBuilder,
    register_accepted_node_types,
)
from inorbit_edge_executor.inorbit import MissionStatus

from inorbit_mir_connector.src.mir_api import (
    DockingOffsetError,
    MirApiV2,
    resolve_marker_type,
)
from inorbit_mir_connector.src.mission.datatypes import (
    MirAction,
    MirGuidedMove,
    MirWaypoint,
    MissionStepExecuteMirNativeMission,
)

logger = logging.getLogger(__name__)

# Distance threshold for MiR move missions (meters)
_MIR_MOVE_DISTANCE_THRESHOLD = 0.1

_MIR_GUIDED_MOVE_ACTION_TYPE = "guided_move"

# Polling interval for mission queue state checks
_POLL_INTERVAL_SECS = 1.0


class MirMissionQueueState(StrEnum):
    """MiR mission queue entry states we act on while polling."""

    DONE = "Done"
    ABORTED = "Aborted"


class SharedMemoryKeys(StrEnum):
    MIR_MISSION_GUID = "mir_mission_guid"
    MIR_QUEUE_ID = "mir_queue_id"
    MIR_ERROR_MESSAGE = "mir_error_message"
    # Ordered guids of the created mission actions (parallel to the step's actions, and so
    # to action_task_ids). Written by CreateMirNativeMissionNode, read by the completion node
    # to pair each guid with its InOrbit task id. Serialized -> survives resume.
    MIR_ACTION_GUIDS = "mir_action_guids"


class MirBehaviorTreeBuilderContext(BehaviorTreeBuilderContext):
    """Extended context carrying MiR API, missions group ID, and firmware version."""

    def __init__(
        self,
        mir_api: MirApiV2,
        missions_group_id: Optional[str],
        firmware_version: str,
        connector_type: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._mir_api = mir_api
        self._missions_group_id = missions_group_id
        self._firmware_version = firmware_version
        self._connector_type = connector_type

    @property
    def mir_api(self) -> MirApiV2:
        return self._mir_api

    @property
    def missions_group_id(self) -> Optional[str]:
        return self._missions_group_id

    @property
    def firmware_version(self) -> str:
        return self._firmware_version

    @property
    def connector_type(self) -> str:
        return self._connector_type


class CreateMirNativeMissionNode(BehaviorTree):
    """Creates a native MiR mission with move_to_position actions and queues it."""

    def __init__(
        self,
        context: MirBehaviorTreeBuilderContext,
        step: MissionStepExecuteMirNativeMission,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._mir_api = context.mir_api
        self._missions_group_id = context.missions_group_id
        self._firmware_version = context.firmware_version
        self._shared_memory = context.shared_memory
        self._step = step

        self._shared_memory.add(SharedMemoryKeys.MIR_MISSION_GUID, None)
        self._shared_memory.add(SharedMemoryKeys.MIR_QUEUE_ID, None)
        self._shared_memory.add(SharedMemoryKeys.MIR_ERROR_MESSAGE, None)
        self._shared_memory.add(SharedMemoryKeys.MIR_ACTION_GUIDS, None)

    async def _execute(self):
        actions = self._step.actions
        n_actions = len(actions)
        mission_guid = str(uuid.uuid4())

        logger.info(f"Creating MiR native mission with {n_actions} actions: {mission_guid}")

        if not self._missions_group_id:
            error_msg = (
                "Cannot create native MiR mission: no MiR missions group is configured. "
                "Enable 'enable_temporary_mission_group' in the connector config, or configure "
                "a predefined missions group, then retry."
            )
            logger.error(error_msg)
            self._shared_memory.set(SharedMemoryKeys.MIR_ERROR_MESSAGE, error_msg)
            raise RuntimeError(error_msg)

        try:
            await self._mir_api.create_mission(
                group_id=self._missions_group_id,
                name=f"InOrbit Mission ({n_actions} actions)",
                guid=mission_guid,
                description="Compiled mission created by InOrbit edge executor",
            )

            action_guids = []
            for i, action in enumerate(actions):
                if isinstance(action, MirWaypoint):
                    action_type = "move_to_position"
                    param_values = {
                        "x": action.x,
                        "y": action.y,
                        "orientation": action.orientation,
                        "distance_threshold": _MIR_MOVE_DISTANCE_THRESHOLD,
                    }
                    if self._firmware_version == "v2":
                        param_values["retries"] = 5
                    else:
                        param_values["blocked_path_timeout"] = 60.0
                elif isinstance(action, MirGuidedMove):
                    action_type = _MIR_GUIDED_MOVE_ACTION_TYPE
                    # Legs without a corridor follow the line exactly: edge radius 0 keeps
                    # adjacent edges from overlapping (an overlap lets the robot skip the
                    # waypoint and cut the corner), while node radius 0.3 rounds the corner
                    # enough to keep cycle time.
                    waypoints_json = [
                        {
                            "x": w.x,
                            "y": w.y,
                            "node_radius": w.node_radius if w.node_radius is not None else 0.3,
                            "edge_radius": w.edge_radius if w.edge_radius is not None else 0.0,
                        }
                        for w in action.waypoints
                    ]
                    # Every schema parameter must be present: the robot applies no
                    # server-side defaults and rejects the action with
                    # input_required_argument_missing otherwise.
                    param_values = {
                        "position": None,
                        "x": action.goal_x,
                        "y": action.goal_y,
                        "orientation": action.goal_orientation,
                        "start_node_radius": 0.5,
                        "goal_node_radius": (
                            action.goal_node_radius if action.goal_node_radius is not None else 0.5
                        ),
                        "goal_edge_radius": (
                            action.goal_edge_radius if action.goal_edge_radius is not None else 0.0
                        ),
                        "blocked_path_timeout": 60.0,
                        "waypoints": json.dumps(waypoints_json),
                        # Center-based deviation (MiR default): the footprint may exceed
                        # the corridor, e.g. to skirt an obstacle. Footprint mode requires
                        # every radius (incl. the fixed start node) to contain the whole
                        # footprint and rejects corridors narrower than the robot diagonal
                        # ("Start node radius is too low"), so the MVP does not use it.
                        "keep_footprint_within_inflation": False,
                        "enable_node_resource_handling": False,
                        # Identity echoed back by GET /guided_move; deterministic so the
                        # completion node can recompute it (UNVERIFIED whether the robot
                        # reports it with node resource handling disabled).
                        "guided_move_id": _guided_move_identity(mission_guid, i),
                        "assigned_waypoint_index": None,
                    }
                elif isinstance(action, MirAction):
                    action_type = action.action_type
                    param_values = dict(action.parameters)
                else:
                    raise TypeError(f"Unexpected action type: {type(action)}")

                param_values = await resolve_marker_type(
                    self._mir_api, action_type, param_values, logger
                )

                action_parameters = [
                    {"value": v, "input_name": None, "guid": str(uuid.uuid4()), "id": k}
                    for k, v in param_values.items()
                ]

                created = await self._mir_api.add_action_to_mission(
                    action_type=action_type,
                    mission_id=mission_guid,
                    parameters=action_parameters,
                    priority=i + 1,
                )
                # action_id reported by the mission queue at runtime == this guid; the
                # completion node matches on it to mark the paired InOrbit task. A missing
                # guid (unexpected response shape) becomes None -> that task just falls back
                # to mark-at-end rather than crashing the dispatch.
                action_guids.append((created or {}).get("guid"))

            queue_response = await self._mir_api.queue_mission(mission_guid)
            queue_id = queue_response.get("id")
            self._shared_memory.set(SharedMemoryKeys.MIR_MISSION_GUID, mission_guid)
            self._shared_memory.set(SharedMemoryKeys.MIR_QUEUE_ID, queue_id)
            self._shared_memory.set(SharedMemoryKeys.MIR_ACTION_GUIDS, action_guids)
            logger.info(f"Queued MiR native mission: {mission_guid} (queue id: {queue_id})")

        except DockingOffsetError as e:
            # Already a clear, operator-facing message — surface it as-is.
            error_msg = str(e)
            logger.error(error_msg)
            self._shared_memory.set(SharedMemoryKeys.MIR_ERROR_MESSAGE, error_msg)
            raise RuntimeError(error_msg) from e
        except Exception as e:
            error_msg = f"Failed to create/queue MiR native mission: {e}"
            if any(isinstance(a, MirGuidedMove) for a in actions):
                error_msg += (
                    " (mission contains a route/guided_move action; MiR software 3.8.0+ "
                    "is required for guided moves)"
                )
            logger.error(error_msg)
            self._shared_memory.set(SharedMemoryKeys.MIR_ERROR_MESSAGE, error_msg)
            raise RuntimeError(error_msg) from e

    def dump_object(self):
        obj = super().dump_object()
        # by_alias: step model is extra="forbid" alias-only; snake_case keys fail resume.
        obj["step"] = self._step.model_dump(mode="json", exclude_none=True, by_alias=True)
        return obj

    @classmethod
    def from_object(cls, context, step, **kwargs):
        if isinstance(step, dict):
            step = MissionStepExecuteMirNativeMission.model_validate(step)
        return CreateMirNativeMissionNode(context, step, **kwargs)


def _guided_move_identity(mission_guid, action_index):
    """Deterministic ``guided_move_id`` for the action at ``action_index``: sent as an
    action parameter and matched against ``GET /guided_move`` while tracking."""
    return f"{mission_guid}:{action_index}"


def _iter_task_ids(entries):
    """Yield every task id in an ``action_task_ids`` list, one level flattened
    (a nested list entry carries a guided move's per-waypoint task ids; only
    ``_mark_guided_progress`` cares about the positions)."""
    for entry in entries:
        if isinstance(entry, list):
            yield from entry
        else:
            yield entry


class WaitForMirMissionCompletionNode(BehaviorTree):
    """Polls MiR mission queue until the queued native mission completes."""

    def __init__(
        self,
        context: MirBehaviorTreeBuilderContext,
        timeout_secs: Optional[float] = None,
        action_task_ids: Optional[list] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._mir_api = context.mir_api
        self._shared_memory = context.shared_memory
        self._timeout_secs = timeout_secs
        # Ordered InOrbit task ids parallel to the native mission's actions (None = no task).
        self._action_task_ids = action_task_ids or []
        # mission/mt drive InOrbit per-task tracking; both are None outside a real dispatch
        # (e.g. some unit tests), so _report_progress no-ops when either is missing.
        self._mission = context.mission
        self._mt = context.mt
        # action index -> last reported status ("p"=in_progress, "c"=completed), to avoid
        # re-reporting. Not serialized: on resume it re-derives from MiR (marking is
        # idempotent, so a re-report is harmless).
        self._reported: dict = {}
        # {our action guid -> InOrbit task id}, built lazily on first poll from
        # MIR_ACTION_GUIDS (shared memory) zipped with action_task_ids. None until built.
        self._guid_to_task: Optional[dict] = None
        # {guided action guid -> expected guided_move_id}, built alongside _guid_to_task.
        self._guid_to_gm_id: dict = {}
        # queue-action int id -> (action_id, finished_bool). Once finished, never re-fetched,
        # so steady state is ~1 detail GET/poll. Not serialized: re-derives on resume.
        self._detail_cache: dict = {}
        # warn once if our guids never match any queued action_id (fail-safe degradation).
        self._warned_no_match = False

    def _tracking_tasks(self) -> bool:
        """True when this group has at least one task to report and the tracking
        collaborators (mission + mt) are available."""
        return (
            self._mt is not None
            and self._mission is not None
            and any(t is not None for t in _iter_task_ids(self._action_task_ids))
        )

    def _build_pairing(self):
        """Build ``{our action guid -> task id}`` from MIR_ACTION_GUIDS (set by
        CreateMirNativeMissionNode) zipped with the parallel ``action_task_ids``.
        A list entry pairs a guided_move guid with its per-waypoint task ids."""
        guids = self._shared_memory.get(SharedMemoryKeys.MIR_ACTION_GUIDS) or []
        self._guid_to_task = {
            g: t for g, t in zip(guids, self._action_task_ids) if g is not None and t is not None
        }
        mission_guid = self._shared_memory.get(SharedMemoryKeys.MIR_MISSION_GUID)
        self._guid_to_gm_id = {
            g: _guided_move_identity(mission_guid, i)
            for i, (g, t) in enumerate(zip(guids, self._action_task_ids))
            if g is not None and isinstance(t, list)
        }

    async def _report_progress(self, queue_id):
        """Mark each grouped task as the MiR action it is paired with runs.

        The queue action list (``GET /mission_queue/{id}/actions``) is shallow
        (``[{id, url}]``); each entry's ``action_id`` and ``finished`` come from the
        detail endpoint. ``action_id`` equals the guid we captured at creation, so we
        map it back to the paired InOrbit task. A ``load_mission``'s inlined
        sub-actions carry foreign guids and are simply not in the pairing, so they are
        ignored. Best-effort: never raises into the completion poll.
        """
        if not self._tracking_tasks():
            return
        if self._guid_to_task is None:
            self._build_pairing()
        if not self._guid_to_task:
            return
        try:
            entries = await self._mir_api.get_mission_queue_actions(queue_id)
            for entry in entries:
                int_id = entry.get("id")
                cached = self._detail_cache.get(int_id)
                if cached is not None and cached[1]:  # already resolved as finished
                    continue
                detail = await self._mir_api.get_mission_queue_action(queue_id, int_id)
                self._detail_cache[int_id] = (
                    detail.get("action_id"),
                    detail.get("finished") is not None,
                )
        except Exception as e:
            logger.warning(f"Failed to poll per-action progress for {queue_id}: {e}")
            return
        finished_by_guid = {action_id: fin for action_id, fin in self._detail_cache.values()}
        await self._mark(finished_by_guid, polled=bool(entries))

    async def _mark(self, finished_by_guid, polled):
        """Mark each paired task from its action's queue state: present and finished
        -> completed, present and running -> in progress, absent -> leave for later.
        A list entry (guided_move) is marked per-waypoint: finished completes every
        task in the entry, running defers to ``_mark_guided_progress``."""
        changed = False
        matched = False
        for guid, entry in self._guid_to_task.items():
            if guid not in finished_by_guid:
                continue  # not started yet, or a foreign sub-action guid
            matched = True
            finished = finished_by_guid[guid]
            if isinstance(entry, list):
                if finished:
                    for task_id in entry:
                        changed |= self._mark_one(task_id, "c")
                else:
                    changed |= await self._mark_guided_progress(guid, entry)
                continue
            changed |= self._mark_one(entry, "c" if finished else "p")
        if changed:
            await self._mt.report_tasks()
        elif polled and not matched and not self._warned_no_match:
            # The queue has actions but none carry our guids: granular tracking is
            # degrading to mark-at-end (_finish_tasks still completes everything at Done).
            self._warned_no_match = True
            logger.warning(
                "MiR per-task tracking: no queued action_id matched the created action "
                "guids; tasks will be completed at mission end (action_id/guid mismatch?)"
            )

    def _mark_one(self, task_id, status):
        """Mark one task ("c"/"p"); no-op on None, repeats, and downgrades."""
        if task_id is None:
            return False
        previous = self._reported.get(task_id)
        if previous == status or previous == "c":
            return False
        if status == "c":
            self._mission.mark_task_completed(task_id)
        else:
            self._mission.mark_task_in_progress(task_id)
        self._reported[task_id] = status
        return True

    async def _mark_guided_progress(self, guid, entry):
        """Granular tracking for a RUNNING guided_move action.

        ``entry`` is the task-id list parallel to the run's [*waypoints, goal]
        steps. ``GET /guided_move`` reports the current-or-latest guided move
        with current_waypoint_index over [start, *waypoints, goal] (0 = start,
        so run step i is reached at index i + 1). The status is applied only
        when its ``guided_move_id`` matches the identity we sent with the
        action (any other status may belong to a previous or concurrent guided
        move). Best-effort: poll failures and unmatched statuses degrade to
        mark-at-end.
        """
        try:
            status = await self._mir_api.get_guided_move()
        except Exception as e:
            logger.warning(f"Failed to poll guided move status: {e}")
            return False
        if not status or status.get("guided_move_id") != self._guid_to_gm_id.get(guid):
            return False
        index = status.get("current_waypoint_index")

        changed = False
        marked_in_progress = False
        for i, task_id in enumerate(entry):
            if task_id is None:
                continue
            if isinstance(index, int) and index >= i + 1:
                changed |= self._mark_one(task_id, "c")
            elif not marked_in_progress and self._reported.get(task_id) != "c":
                changed |= self._mark_one(task_id, "p")
                marked_in_progress = True
        return changed

    async def _finish_tasks(self):
        """Mark every remaining task completed (the mission reached Done; covers a
        fast group whose actions all flipped between polls)."""
        if not self._tracking_tasks():
            return
        changed = False
        for task_id in _iter_task_ids(self._action_task_ids):
            if task_id is None or self._reported.get(task_id) == "c":
                continue
            self._mission.mark_task_completed(task_id)
            self._reported[task_id] = "c"
            changed = True
        if changed:
            await self._mt.report_tasks()

    async def _execute(self):
        queue_id = self._shared_memory.get(SharedMemoryKeys.MIR_QUEUE_ID)
        mission_guid = self._shared_memory.get(SharedMemoryKeys.MIR_MISSION_GUID)
        if not queue_id:
            raise RuntimeError("No MiR queue ID in shared memory")

        logger.info(
            f"Waiting for MiR mission queue entry {queue_id} (mission {mission_guid}) to complete"
        )
        start_time = time.time()
        consecutive_errors = 0
        max_consecutive_errors = 10

        while True:
            if self._timeout_secs and (time.time() - start_time) > self._timeout_secs:
                raise RuntimeError(f"MiR mission {queue_id} timed out after {self._timeout_secs}s")

            try:
                entry = await self._mir_api.get_mission_queue_entry(queue_id)
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                logger.warning(
                    f"Failed to poll mission queue entry {queue_id} "
                    f"({consecutive_errors}/{max_consecutive_errors}): {e}"
                )
                if consecutive_errors >= max_consecutive_errors:
                    error_msg = f"MiR mission {queue_id} lost: {consecutive_errors} consecutive poll failures"  # noqa: E501
                    logger.error(error_msg)
                    self._shared_memory.set(SharedMemoryKeys.MIR_ERROR_MESSAGE, error_msg)
                    raise RuntimeError(error_msg)
                await asyncio.sleep(_POLL_INTERVAL_SECS)
                continue

            state = entry.get("state", "")

            await self._report_progress(queue_id)

            if state == MirMissionQueueState.DONE:
                await self._finish_tasks()
                logger.info(f"MiR mission {queue_id} completed successfully")
                return

            if state == MirMissionQueueState.ABORTED:
                error_msg = (
                    f"MiR mission {queue_id} was aborted: {entry.get('message', 'no message')}"
                )
                logger.error(error_msg)
                self._shared_memory.set(SharedMemoryKeys.MIR_ERROR_MESSAGE, error_msg)
                raise RuntimeError(error_msg)

            logger.debug(f"MiR mission {queue_id} state: {state}")
            await asyncio.sleep(_POLL_INTERVAL_SECS)

    def dump_object(self):
        obj = super().dump_object()
        if self._timeout_secs is not None:
            obj["timeout_secs"] = self._timeout_secs
        if self._action_task_ids:
            obj["action_task_ids"] = self._action_task_ids
        return obj

    @classmethod
    def from_object(cls, context, timeout_secs=None, action_task_ids=None, **kwargs):
        return WaitForMirMissionCompletionNode(
            context, timeout_secs=timeout_secs, action_task_ids=action_task_ids, **kwargs
        )


class MirMissionAbortedNode(MissionAbortedNode):
    """Extended abort node that also aborts MiR mission queue."""

    def __init__(
        self,
        context: MirBehaviorTreeBuilderContext,
        status: MissionStatus = MissionStatus.error,
        **kwargs,
    ):
        super().__init__(context, status, **kwargs)
        self._mir_api = context.mir_api
        self._shared_memory = context.shared_memory

    async def _execute(self):
        error_message = self._shared_memory.get(SharedMemoryKeys.MIR_ERROR_MESSAGE)
        if error_message:
            logger.error(f"MiR mission aborted: {error_message}")

        queue_id = self._shared_memory.get(SharedMemoryKeys.MIR_QUEUE_ID)
        if queue_id is not None:
            try:
                await self._mir_api.abort_mission(queue_id)
                logger.info(f"Aborted MiR mission queue entry {queue_id}")
            except Exception as e:
                logger.warning(f"Failed to abort MiR mission queue entry {queue_id}: {e}")
        else:
            logger.warning("No MiR queue id in shared memory; nothing to abort")

        await super()._execute()

    @classmethod
    def from_object(cls, context, status, **kwargs):
        return MirMissionAbortedNode(context, MissionStatus(status), **kwargs)


class CleanupMirMissionNode(BehaviorTree):
    """Cancels the active MiR mission during cleanup (e.g. on pause)."""

    def __init__(self, context: MirBehaviorTreeBuilderContext, **kwargs):
        super().__init__(**kwargs)
        self._mir_api = context.mir_api
        self._shared_memory = context.shared_memory

    async def _execute(self):
        queue_id = self._shared_memory.get(SharedMemoryKeys.MIR_QUEUE_ID)
        if queue_id is None:
            logger.warning("No MiR queue id in shared memory; nothing to clean up")
            return
        logger.info(f"Cleaning up MiR mission (aborting queue entry {queue_id})")
        try:
            await self._mir_api.abort_mission(queue_id)
        except Exception as e:
            logger.warning(
                f"Failed to abort MiR mission queue entry {queue_id} during cleanup: {e}"
            )

    @classmethod
    def from_object(cls, context, **kwargs):
        return CleanupMirMissionNode(context, **kwargs)


class MirNodeFromStepBuilder(NodeFromStepBuilder):
    """Step builder that handles MiR-specific step types."""

    def __init__(self, context: MirBehaviorTreeBuilderContext):
        super().__init__(context)
        self._mir_context = context

    def visit_execute_mir_native_mission(
        self, step: MissionStepExecuteMirNativeMission
    ) -> BehaviorTree:
        sequence = BehaviorTreeSequential(label=step.label)
        sequence.add_node(
            CreateMirNativeMissionNode(
                self._mir_context, step, label=f"Create MiR mission '{step.label}'"
            )
        )
        sequence.add_node(
            WaitForMirMissionCompletionNode(
                self._mir_context,
                timeout_secs=step.timeout_secs,
                action_task_ids=step.action_task_ids,
                label=f"Wait for MiR mission '{step.label}'",
            )
        )
        return sequence


# Register node types for serialization/deserialization
mir_node_types = [
    CreateMirNativeMissionNode,
    WaitForMirMissionCompletionNode,
    MirMissionAbortedNode,
    CleanupMirMissionNode,
]
register_accepted_node_types(mir_node_types)
