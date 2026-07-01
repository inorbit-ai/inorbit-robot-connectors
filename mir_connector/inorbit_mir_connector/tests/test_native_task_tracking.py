# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Per-task tracking inside WaitForMirMissionCompletionNode.

After grouping, a native MiR mission carries several InOrbit tasks (action_task_ids,
parallel to its actions). The SDK step decorator no longer emits TaskStarted/CompletedNode
for them, so the completion node marks each task as its MiR action runs. It pairs each task
with the guid captured when the action was created, then per poll resolves each queued
action's action_id (== that guid) and finished timestamp via the mission-queue detail
endpoint. Matching by guid -- not list length -- ignores a load_mission's inlined
sub-actions (foreign guids), so nested missions no longer over-complete. These tests pin
that marking.
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


def _entry(int_id, action_id, finished=False):
    """One executed mission-queue action, as the detail endpoint reports it."""
    return {"id": int_id, "action_id": action_id, "finished": "ts" if finished else None}


class _ProgressMirApi:
    """Models the queue LIST (``[{id, url}]``) + DETAIL (``{action_id, finished}``)
    endpoints plus the queue-entry state, driven by an ``executed`` list the test advances."""

    def __init__(self, executed=None, state="Executing"):
        self.executed = executed or []
        self.state = state
        self.list_polls = 0
        self.detail_polls = 0

    async def get_mission_queue_entry(self, queue_id):
        return {"state": self.state}

    async def get_mission_queue_actions(self, queue_id):
        self.list_polls += 1
        return [
            {"id": e["id"], "url": f"/mission_queue/{queue_id}/actions/{e['id']}"}
            for e in self.executed
        ]

    async def get_mission_queue_action(self, queue_id, action_int_id):
        self.detail_polls += 1
        for e in self.executed:
            if e["id"] == action_int_id:
                return {"id": e["id"], "action_id": e["action_id"], "finished": e["finished"]}
        raise KeyError(action_int_id)


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


def _wait_node(api, action_task_ids, mission, action_guids):
    sm = MissionRuntimeSharedMemory()
    sm.add(SharedMemoryKeys.MIR_QUEUE_ID, None)
    sm.add(SharedMemoryKeys.MIR_MISSION_GUID, None)
    sm.add(SharedMemoryKeys.MIR_ERROR_MESSAGE, None)
    sm.add(SharedMemoryKeys.MIR_ACTION_GUIDS, None)
    sm.freeze()
    sm.set(SharedMemoryKeys.MIR_QUEUE_ID, QUEUE_ID)
    sm.set(SharedMemoryKeys.MIR_ACTION_GUIDS, action_guids)
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
    guids = ["g0", "g1", "g2"]
    mission = _mission_with_tasks(ids)
    api = _ProgressMirApi()
    node, ctx = _wait_node(api, ids, mission, guids)

    api.executed = [_entry(0, "g0")]  # action g0 (t1) running
    await node._report_progress(QUEUE_ID)
    assert _status(mission, "t1") == (True, False)

    api.executed = [
        _entry(0, "g0", finished=True),
        _entry(1, "g1"),
    ]  # g0 done, g1 (no task) running
    await node._report_progress(QUEUE_ID)
    assert _status(mission, "t1") == (False, True)

    api.executed += [_entry(2, "g2")]  # g2 (t2) running
    await node._report_progress(QUEUE_ID)
    assert _status(mission, "t2") == (True, False)

    await node._finish_tasks()
    assert _status(mission, "t2") == (False, True)
    ctx.mt.report_tasks.assert_awaited()


@pytest.mark.asyncio
async def test_done_marks_all_remaining_tasks_completed():
    ids = ["t1", "t2"]
    guids = ["g0", "g1"]
    mission = _mission_with_tasks(ids)
    api = _ProgressMirApi(executed=[_entry(0, "g0")], state="Done")
    node, ctx = _wait_node(api, ids, mission, guids)

    await node._execute()  # Done before g1 ever appears in the queue

    assert _status(mission, "t1") == (False, True)
    assert _status(mission, "t2") == (False, True)
    assert api.list_polls >= 1
    ctx.mt.report_tasks.assert_awaited()


@pytest.mark.asyncio
async def test_untracked_group_does_not_poll_actions():
    mission = _mission_with_tasks([])
    api = _ProgressMirApi(executed=[_entry(0, "g0")], state="Done")
    node, ctx = _wait_node(api, [None, None], mission, ["g0", "g1"])

    await node._execute()

    # No tasks -> the per-action progress endpoints are never polled, nothing reported.
    assert api.list_polls == 0
    assert api.detail_polls == 0
    ctx.mt.report_tasks.assert_not_awaited()


@pytest.mark.asyncio
async def test_nested_mission_ignores_foreign_subactions():
    # g1 is a load_mission; at runtime its sub-mission's actions inline with FOREIGN guids.
    ids = ["t1", "t2", "t3"]
    guids = ["g0", "g1", "g2"]
    mission = _mission_with_tasks(ids)
    api = _ProgressMirApi()
    node, _ = _wait_node(api, ids, mission, guids)

    # Robot on the first action only: t3 must NOT complete (the old count bug did).
    api.executed = [_entry(0, "g0")]
    await node._report_progress(QUEUE_ID)
    assert _status(mission, "t1") == (True, False)
    assert _status(mission, "t3") == (False, False)

    # load_mission (g1) running with its sub-actions inlined as foreign guids fa/fb.
    api.executed = [
        _entry(0, "g0", finished=True),
        _entry(1, "g1"),
        _entry(2, "fa", finished=True),
        _entry(3, "fb"),
    ]
    await node._report_progress(QUEUE_ID)
    assert _status(mission, "t1") == (False, True)
    assert _status(mission, "t2") == (True, False)  # load_mission's own task, from its own entry
    assert _status(mission, "t3") == (False, False)  # foreign sub-actions did not advance t3

    # load_mission done, real action g2 starts -> only now does t3 advance.
    api.executed = [
        _entry(0, "g0", finished=True),
        _entry(1, "g1", finished=True),
        _entry(2, "fa", finished=True),
        _entry(3, "fb", finished=True),
        _entry(4, "g2"),
    ]
    await node._report_progress(QUEUE_ID)
    assert _status(mission, "t2") == (False, True)
    assert _status(mission, "t3") == (True, False)


@pytest.mark.asyncio
async def test_no_guid_match_falls_back_to_finish_at_done():
    # Fail-safe: if no queued action_id matches our guids, nothing is marked mid-flight,
    # a single warning fires, and _finish_tasks still completes everything at Done.
    ids = ["t1", "t2"]
    mission = _mission_with_tasks(ids)
    api = _ProgressMirApi(executed=[_entry(0, "x0"), _entry(1, "x1")])
    node, ctx = _wait_node(api, ids, mission, ["g0", "g1"])

    await node._report_progress(QUEUE_ID)
    assert _status(mission, "t1") == (False, False)
    assert _status(mission, "t2") == (False, False)
    assert node._warned_no_match is True
    ctx.mt.report_tasks.assert_not_awaited()

    await node._finish_tasks()
    assert _status(mission, "t1") == (False, True)
    assert _status(mission, "t2") == (False, True)
    ctx.mt.report_tasks.assert_awaited()
