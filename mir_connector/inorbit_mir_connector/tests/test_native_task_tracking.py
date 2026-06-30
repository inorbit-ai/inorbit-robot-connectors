# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Per-task tracking inside WaitForMirMissionCompletionNode.

After grouping, a native MiR mission carries several InOrbit tasks (action_task_ids,
parallel to its actions). The SDK step decorator no longer emits TaskStarted/CompletedNode
for them, so the completion node marks each task as its MiR action runs, using the
executed-action count from GET /mission_queue/{id}/actions (the same signal robot-side
mission tracking uses). These tests pin that marking.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from inorbit_edge_executor.datatypes import (
    MissionDefinition,
    MissionRuntimeSharedMemory,
    MissionStepPoseWaypoint,
    MissionTask,
    Pose,
)
from inorbit_edge_executor.mission import Mission

from inorbit_mir_connector.src.mission.behavior_tree import (
    MirBehaviorTreeBuilderContext,
    SharedMemoryKeys,
    WaitForMirMissionCompletionNode,
)

ROBOT_ID = "mir-1"
QUEUE_ID = 42


class _ProgressMirApi:
    """Reports ``action_count`` executed actions and a fixed queue-entry state."""

    def __init__(self, action_count=0, state="Executing"):
        self.action_count = action_count
        self.state = state
        self.action_polls = 0

    async def get_mission_queue_entry(self, queue_id):
        return {"state": self.state}

    async def get_mission_queue_actions(self, queue_id):
        self.action_polls += 1
        return [{"id": i} for i in range(self.action_count)]


def _mission_with_tasks(task_ids):
    tasks = [MissionTask(taskId=t, label=t) for t in task_ids if t is not None]
    return Mission(
        id="m1",
        robot_id=ROBOT_ID,
        definition=MissionDefinition(
            label="t",
            steps=[MissionStepPoseWaypoint(waypoint=Pose(x=0, y=0, theta=0), label="wp")],
        ),
        tasks_list=tasks,
    )


def _wait_node(api, action_task_ids, mission):
    sm = MissionRuntimeSharedMemory()
    sm.add(SharedMemoryKeys.MIR_QUEUE_ID, None)
    sm.add(SharedMemoryKeys.MIR_MISSION_GUID, None)
    sm.add(SharedMemoryKeys.MIR_ERROR_MESSAGE, None)
    sm.freeze()
    sm.set(SharedMemoryKeys.MIR_QUEUE_ID, QUEUE_ID)
    ctx = MirBehaviorTreeBuilderContext(
        mir_api=api,
        missions_group_id="grp",
        firmware_version="v3",
        connector_type="mir",
        mission=mission,
        mt=AsyncMock(),
    )
    ctx.shared_memory = sm
    return WaitForMirMissionCompletionNode(ctx, action_task_ids=action_task_ids), ctx


def _status(mission, task_id):
    task = mission.find_task(task_id)
    return (task.in_progress, task.completed)


@pytest.mark.asyncio
async def test_marks_each_task_as_its_action_progresses():
    ids = ["t1", None, "t2"]
    mission = _mission_with_tasks(ids)
    api = _ProgressMirApi()
    node, ctx = _wait_node(api, ids, mission)

    api.action_count = 1  # action 0 (t1) running
    await node._report_progress(QUEUE_ID)
    assert _status(mission, "t1") == (True, False)

    api.action_count = 2  # action 0 finished, action 1 (no task) running
    await node._report_progress(QUEUE_ID)
    assert _status(mission, "t1") == (False, True)

    api.action_count = 3  # action 2 (t2) running
    await node._report_progress(QUEUE_ID)
    assert _status(mission, "t2") == (True, False)

    await node._finish_tasks()
    assert _status(mission, "t2") == (False, True)
    ctx.mt.report_tasks.assert_awaited()


@pytest.mark.asyncio
async def test_done_marks_all_remaining_tasks_completed():
    ids = ["t1", "t2"]
    mission = _mission_with_tasks(ids)
    api = _ProgressMirApi(action_count=1, state="Done")
    node, ctx = _wait_node(api, ids, mission)

    await node._execute()  # Done on the first poll, before the count reaches both actions

    assert _status(mission, "t1") == (False, True)
    assert _status(mission, "t2") == (False, True)
    assert api.action_polls >= 1
    ctx.mt.report_tasks.assert_awaited()


@pytest.mark.asyncio
async def test_untracked_group_does_not_poll_actions():
    mission = _mission_with_tasks([])
    api = _ProgressMirApi(action_count=0, state="Done")
    node, ctx = _wait_node(api, [None, None], mission)

    await node._execute()

    # No tasks -> the per-action progress endpoint is never polled, nothing reported.
    assert api.action_polls == 0
    ctx.mt.report_tasks.assert_not_awaited()
