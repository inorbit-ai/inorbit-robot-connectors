# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
import pytz
from unittest.mock import AsyncMock, MagicMock

from inorbit_edge.robot import RobotSession
from inorbit_mir_connector.src.mir_api import MirApiV2
from inorbit_mir_connector.src.mission_tracking import (
    MirInorbitMissionTracking,
    MirNativeMissionTasks,
)


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


ACTION_DEFS = [
    {"action_type": "move", "name": "Move"},
    {"action_type": "docking", "name": "Docking"},
    {"action_type": "charging", "name": "Charging"},
]


def make_tracking():
    tracking = MirInorbitMissionTracking(
        mir_api=MagicMock(autospec=MirApiV2),
        inorbit_sess=MagicMock(autospec=RobotSession),
        robot_tz_info=pytz.timezone("UTC"),
        mission_executor=MagicMock(),
    )
    tracking.mission_executor.has_active_mission = AsyncMock(return_value=False)
    tracking.mir_api.get_action_definitions = AsyncMock(return_value=ACTION_DEFS)
    tracking.mir_api.get_position = AsyncMock(return_value={"name": "Warehouse-1"})
    return tracking


def def_action(guid, action_type="move", parameters=None):
    return {
        "guid": guid,
        "action_type": action_type,
        "parameters": parameters or [],
        "priority": 1,
        "mission_id": "def-guid",
    }


@pytest.mark.asyncio
async def test_build_tasks_labels_and_order():
    tracking = make_tracking()
    actions = [
        def_action("g1", "move", [{"id": "position", "value": "pos-guid"}]),
        def_action("g2", "docking", [{"id": "marker", "value": "pos-guid"}]),
        def_action("g3", "charging"),
        def_action("g4", "unknown_type"),
    ]
    tasks = await tracking._build_tasks(actions)
    assert list(tasks) == ["g1", "g2", "g3", "g4"]
    assert tasks["g1"]["label"] == "Move to Warehouse-1"
    assert tasks["g2"]["label"] == "Docking at Warehouse-1"
    assert tasks["g3"]["label"] == "Charging"
    assert tasks["g4"]["label"] == "unknown_type"
    assert tasks["g1"] == {
        "taskId": "g1",
        "label": "Move to Warehouse-1",
        "inProgress": False,
        "completed": False,
    }


@pytest.mark.asyncio
async def test_build_tasks_variable_position_falls_back_to_action_name():
    # Parameterized missions carry input_name and a null value in the definition.
    tracking = make_tracking()
    actions = [def_action("g1", "move", [{"id": "position", "value": None, "input_name": "p"}])]
    tasks = await tracking._build_tasks(actions)
    assert tasks["g1"]["label"] == "Move"


@pytest.mark.asyncio
async def test_build_tasks_position_lookup_failure_falls_back():
    tracking = make_tracking()
    tracking.mir_api.get_position = AsyncMock(side_effect=RuntimeError("404"))
    actions = [def_action("g1", "move", [{"id": "position", "value": "pos-guid"}])]
    tasks = await tracking._build_tasks(actions)
    assert tasks["g1"]["label"] == "Move"


@pytest.mark.asyncio
async def test_position_names_cached_across_actions():
    tracking = make_tracking()
    actions = [
        def_action("g1", "move", [{"id": "position", "value": "pos-guid"}]),
        def_action("g2", "move", [{"id": "position", "value": "pos-guid"}]),
    ]
    await tracking._build_tasks(actions)
    assert tracking.mir_api.get_position.await_count == 1


@pytest.mark.asyncio
async def test_action_definitions_failure_uses_raw_types_and_retries():
    tracking = make_tracking()
    tracking.mir_api.get_action_definitions = AsyncMock(side_effect=RuntimeError("boom"))
    tasks = await tracking._build_tasks([def_action("g1", "move")])
    assert tasks["g1"]["label"] == "move"
    # A later mission retries the fetch instead of caching the failure.
    tracking.mir_api.get_action_definitions = AsyncMock(return_value=ACTION_DEFS)
    tasks = await tracking._build_tasks([def_action("g2", "move")])
    assert tasks["g2"]["label"] == "Move"
