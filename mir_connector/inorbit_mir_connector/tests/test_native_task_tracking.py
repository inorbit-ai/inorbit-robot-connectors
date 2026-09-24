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

import pytest

from inorbit_mir_connector.tests.conftest import (
    ProgressMirApi as _ProgressMirApi,
    mission_with_tasks as _mission_with_tasks,
    queue_entry as _entry,
    task_status as _status,
    wait_node as _wait_node,
)

QUEUE_ID = 42


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
