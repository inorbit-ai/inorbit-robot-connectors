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

"""Custom behavior tree nodes for executing compiled native MiR missions.

The tree for a single MissionStepExecuteMirNativeMission step:

    BehaviorTreeSequential("Navigate N waypoints")
      +-- CreateMirNativeMissionNode   -> create_mission + N x add_action + queue
      +-- WaitForMirMissionCompletionNode -> poll mission_queue until Done/Abort
"""

from __future__ import annotations

import asyncio
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

from inorbit_mir_connector.src.mission.datatypes import (
    MirAction,
    MirWaypoint,
    MissionStepExecuteMirNativeMission,
)
from inorbit_mir_connector.src.mir_api import DockingOffsetError, MirApiV2, resolve_marker_type

logger = logging.getLogger(__name__)

# Distance threshold for MiR move missions (meters)
_MIR_MOVE_DISTANCE_THRESHOLD = 0.1

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

                await self._mir_api.add_action_to_mission(
                    action_type=action_type,
                    mission_id=mission_guid,
                    parameters=action_parameters,
                    priority=i + 1,
                )

            queue_response = await self._mir_api.queue_mission(mission_guid)
            queue_id = queue_response.get("id")
            self._shared_memory.set(SharedMemoryKeys.MIR_MISSION_GUID, mission_guid)
            self._shared_memory.set(SharedMemoryKeys.MIR_QUEUE_ID, queue_id)
            logger.info(f"Queued MiR native mission: {mission_guid} (queue id: {queue_id})")

        except DockingOffsetError as e:
            # Already a clear, operator-facing message — surface it as-is.
            error_msg = str(e)
            logger.error(error_msg)
            self._shared_memory.set(SharedMemoryKeys.MIR_ERROR_MESSAGE, error_msg)
            raise RuntimeError(error_msg) from e
        except Exception as e:
            error_msg = f"Failed to create/queue MiR native mission: {e}"
            logger.error(error_msg)
            self._shared_memory.set(SharedMemoryKeys.MIR_ERROR_MESSAGE, error_msg)
            raise RuntimeError(error_msg) from e

    def dump_object(self):
        obj = super().dump_object()
        obj["step"] = self._step.model_dump(mode="json", exclude_none=True)
        return obj

    @classmethod
    def from_object(cls, context, step, **kwargs):
        if isinstance(step, dict):
            step = MissionStepExecuteMirNativeMission.model_validate(step)
        return CreateMirNativeMissionNode(context, step, **kwargs)


class WaitForMirMissionCompletionNode(BehaviorTree):
    """Polls MiR mission queue until the queued native mission completes."""

    def __init__(
        self,
        context: MirBehaviorTreeBuilderContext,
        timeout_secs: Optional[float] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._mir_api = context.mir_api
        self._shared_memory = context.shared_memory
        self._timeout_secs = timeout_secs

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

            if state == MirMissionQueueState.DONE:
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
        return obj

    @classmethod
    def from_object(cls, context, timeout_secs=None, **kwargs):
        return WaitForMirMissionCompletionNode(context, timeout_secs=timeout_secs, **kwargs)


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
