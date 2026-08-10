# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import AsyncMock, MagicMock

from inorbit_mir_connector.src.mission_tracking import MirNativeMissionTasks


def make_tasks(*guids):
    return {
        g: {"taskId": g, "label": f"Task {g}", "inProgress": False, "completed": False}
        for g in guids
    }


def make_api(queue_actions=None, details=None):
    """details: {int_id: (action_id, finished_or_None)}"""
    api = MagicMock()
    api.get_mission_queue_actions = AsyncMock(return_value=queue_actions or [])

    async def get_detail(queue_id, int_id):
        action_id, finished = details[int_id]
        return {"id": int_id, "action_id": action_id, "finished": finished, "state": ""}

    api.get_mission_queue_action = AsyncMock(side_effect=get_detail)
    return api


@pytest.mark.asyncio
async def test_progresses_tasks_from_queue_actions():
    api = make_api(
        queue_actions=[{"id": 1, "url": "u"}, {"id": 2, "url": "u"}],
        details={1: ("g1", "2026-08-10T10:00:00"), 2: ("g2", None)},
    )
    tracker = MirNativeMissionTasks(api, 99, make_tasks("g1", "g2", "g3"))
    await tracker.poll()
    fields = tracker.report_fields()
    by_id = {t["taskId"]: t for t in fields["tasks"]}
    assert by_id["g1"] == {
        "taskId": "g1",
        "label": "Task g1",
        "inProgress": False,
        "completed": True,
    }
    assert by_id["g2"]["inProgress"] is True and by_id["g2"]["completed"] is False
    assert by_id["g3"]["inProgress"] is False and by_id["g3"]["completed"] is False
    assert fields["currentTaskId"] == "g2"
    assert fields["completedPercent"] == pytest.approx(1 / 3)


@pytest.mark.asyncio
async def test_finished_details_are_not_refetched():
    api = make_api(
        queue_actions=[{"id": 1, "url": "u"}],
        details={1: ("g1", "2026-08-10T10:00:00")},
    )
    tracker = MirNativeMissionTasks(api, 99, make_tasks("g1"))
    await tracker.poll()
    await tracker.poll()
    assert api.get_mission_queue_action.await_count == 1


@pytest.mark.asyncio
async def test_loop_reexecution_never_downgrades_completed():
    # A loop re-runs the same definition action: new int id, same action_id (guid).
    api = make_api(
        queue_actions=[{"id": 1, "url": "u"}, {"id": 2, "url": "u"}],
        details={1: ("g1", "2026-08-10T10:00:00"), 2: ("g1", None)},
    )
    tracker = MirNativeMissionTasks(api, 99, make_tasks("g1", "g2"))
    await tracker.poll()
    task = {t["taskId"]: t for t in tracker.report_fields()["tasks"]}["g1"]
    assert task["completed"] is True and task["inProgress"] is False
    assert "currentTaskId" not in tracker.report_fields()


@pytest.mark.asyncio
async def test_foreign_guids_ignored():
    # load_mission inlines sub-mission actions whose guids are not in the definition.
    api = make_api(
        queue_actions=[{"id": 1, "url": "u"}],
        details={1: ("foreign-guid", None)},
    )
    tracker = MirNativeMissionTasks(api, 99, make_tasks("g1"))
    await tracker.poll()
    fields = tracker.report_fields()
    assert fields["tasks"][0]["inProgress"] is False
    assert "currentTaskId" not in fields
    assert fields["completedPercent"] == 0


@pytest.mark.asyncio
async def test_poll_failure_keeps_previous_states_and_does_not_raise():
    api = make_api(
        queue_actions=[{"id": 1, "url": "u"}],
        details={1: ("g1", "2026-08-10T10:00:00")},
    )
    tracker = MirNativeMissionTasks(api, 99, make_tasks("g1"))
    await tracker.poll()
    api.get_mission_queue_actions = AsyncMock(side_effect=RuntimeError("boom"))
    await tracker.poll()  # must not raise
    assert tracker.report_fields()["tasks"][0]["completed"] is True


@pytest.mark.asyncio
async def test_signature_changes_only_on_state_change():
    api = make_api(
        queue_actions=[{"id": 1, "url": "u"}],
        details={1: ("g1", None)},
    )
    tracker = MirNativeMissionTasks(api, 99, make_tasks("g1", "g2"))
    sig0 = tracker.signature()
    await tracker.poll()
    sig1 = tracker.signature()
    assert sig0 != sig1
    await tracker.poll()
    assert tracker.signature() == sig1


@pytest.mark.asyncio
async def test_empty_task_list_reports_zero_percent():
    api = make_api(queue_actions=[])
    tracker = MirNativeMissionTasks(api, 99, {})
    await tracker.poll()
    fields = tracker.report_fields()
    assert fields["tasks"] == [] and fields["completedPercent"] == 0
