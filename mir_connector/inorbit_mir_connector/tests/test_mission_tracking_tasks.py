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
    _execution_order,
)

# Real GET /missions/{id}/actions?whitelist=...,scope_reference payloads, trimmed to the
# fields the ordering depends on.

# "test mission tracking with movement": flat, but returned out of order. Ground truth from
# GET /mission_queue/28525/actions is p12, p13 (the move), p14, p15, p16.
FLAT_MISALIGNED = [
    {"guid": "01cfdccd", "action_type": "wait", "priority": 12, "scope_reference": None},
    {"guid": "aac8f71e", "action_type": "wait", "priority": 14, "scope_reference": None},
    {"guid": "2d8240b7", "action_type": "wait", "priority": 15, "scope_reference": None},
    {"guid": "60675cad", "action_type": "wait", "priority": 16, "scope_reference": None},
    {"guid": "b7809d30", "action_type": "move", "priority": 13, "scope_reference": None},
]

# MiR's shipped "mirconst-guid-0000-0024-actionlist00": two scopes, each numbering its own
# children from 0, so priority is meaningless as a global sort key.
IF_SCOPE = "mirconst-guid-0002-0065-actlistparam"
FIELDS_SCOPE = "mirconst-guid-0002-0073-actlistparam"
SCOPED = [
    {
        "guid": "a-if",
        "action_type": "if",
        "priority": 0,
        "scope_reference": None,
        "parameters": [{"id": "true", "guid": IF_SCOPE, "value": ""}],
    },
    {
        "guid": "a-throw",
        "action_type": "throw_error",
        "priority": 0,
        "scope_reference": IF_SCOPE,
        "parameters": [{"id": "message", "guid": "p-msg", "value": "no shelf"}],
    },
    {
        "guid": "a-fields",
        "action_type": "reduce_protective_fields",
        "priority": 1,
        "scope_reference": None,
        "parameters": [{"id": "content", "guid": FIELDS_SCOPE, "value": ""}],
    },
    {
        "guid": "a-load",
        "action_type": "load_mission",
        "priority": 0,
        "scope_reference": FIELDS_SCOPE,
        "parameters": [{"id": "mission_id", "guid": "p-mid", "value": "other"}],
    },
    {
        "guid": "a-footprint",
        "action_type": "set_footprint",
        "priority": 1,
        "scope_reference": FIELDS_SCOPE,
        "parameters": [{"id": "footprint", "guid": "p-fp", "value": "fp"}],
    },
    {
        "guid": "a-relmove",
        "action_type": "relative_move",
        "priority": 2,
        "scope_reference": FIELDS_SCOPE,
        "parameters": [{"id": "x", "guid": "p-x", "value": -2.0}],
    },
]


def test_execution_order_flat_mission_uses_priority_not_list_order():
    assert [a["guid"] for a in _execution_order(FLAT_MISALIGNED)] == [
        "01cfdccd",
        "b7809d30",
        "aac8f71e",
        "2d8240b7",
        "60675cad",
    ]


def test_execution_order_keeps_nested_actions_inside_their_scope():
    ordered = [a["guid"] for a in _execution_order(SCOPED)]
    assert ordered == ["a-if", "a-throw", "a-fields", "a-load", "a-footprint", "a-relmove"]
    # A global sort by priority hoists the nested load_mission out of its scope, above the
    # top-level action that contains it. That is the trap this function exists to avoid.
    naive = [a["guid"] for a in sorted(SCOPED, key=lambda a: a["priority"])]
    assert naive.index("a-load") < naive.index("a-fields")
    assert ordered.index("a-load") > ordered.index("a-fields")


def test_execution_order_survives_malformed_input():
    # Parameters without guids must not be read as nesting at the root, and a scope cycle
    # must not hang the poll loop.
    cyclic = [
        {
            "guid": "x",
            "action_type": "loop",
            "priority": 0,
            "scope_reference": "s",
            "parameters": [{"id": "content", "guid": "s"}, {"id": "noguid"}],
        }
    ]
    assert [a["guid"] for a in _execution_order(cyclic)] == ["x"]
    assert _execution_order([]) == []


def make_tasks(*guids):
    return {
        g: {"taskId": g, "label": f"Task {g}", "inProgress": False, "completed": False}
        for g in guids
    }


def make_api(queue_actions=None, details=None, states=None):
    """details: {int_id: (action_id, finished_or_None)}; states: {int_id: state} (default "").

    MiR reports a successful action with an empty state and a failed one with "Failed" or
    "Aborted"; both carry a `finished` timestamp.
    """
    api = MagicMock()
    api.get_mission_queue_actions = AsyncMock(return_value=queue_actions or [])

    async def get_detail(queue_id, int_id):
        action_id, finished = details[int_id]
        state = (states or {}).get(int_id, "")
        return {"id": int_id, "action_id": action_id, "finished": finished, "state": state}

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
async def test_failed_action_is_not_reported_completed():
    # A failed action carries a `finished` timestamp just like a successful one; only the
    # non-empty state distinguishes them. Reporting it completed put a green checkmark on the
    # step that broke the mission.
    api = make_api(
        queue_actions=[{"id": 1, "url": "u"}, {"id": 2, "url": "u"}],
        details={1: ("g1", "2026-08-10T10:00:00"), 2: ("g2", "2026-08-10T10:00:05")},
        states={2: "Failed"},
    )
    tracker = MirNativeMissionTasks(api, 99, make_tasks("g1", "g2"))
    await tracker.poll()
    fields = tracker.report_fields()
    by_id = {t["taskId"]: t for t in fields["tasks"]}
    assert by_id["g1"]["completed"] is True
    # A failed action is neither completed nor still running, and is not the current task.
    assert by_id["g2"]["completed"] is False
    assert by_id["g2"]["inProgress"] is False
    assert "currentTaskId" not in fields
    assert fields["completedPercent"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_aborted_action_is_not_reported_completed():
    api = make_api(
        queue_actions=[{"id": 1, "url": "u"}],
        details={1: ("g1", "2026-08-10T10:00:00")},
        states={1: "Aborted"},
    )
    tracker = MirNativeMissionTasks(api, 99, make_tasks("g1"))
    await tracker.poll()
    task = tracker.report_fields()["tasks"][0]
    assert task["completed"] is False and task["inProgress"] is False


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
async def test_detail_fetches_capped_per_poll_and_converge_over_ticks():
    # Long queue-action history (e.g. attaching mid-patrol): entry 1 is already finished,
    # entries 2-30 are still unfinished.
    guids = [f"g{i}" for i in range(1, 31)]
    details = {1: ("g1", "2026-08-10T10:00:00")}
    details.update({i: (f"g{i}", None) for i in range(2, 31)})
    api = make_api(
        queue_actions=[{"id": i, "url": "u"} for i in range(1, 31)],
        details=details,
    )
    tracker = MirNativeMissionTasks(api, 99, make_tasks(*guids))

    await tracker.poll()
    assert api.get_mission_queue_action.await_count == 25
    by_id = {t["taskId"]: t for t in tracker.report_fields()["tasks"]}
    assert by_id["g1"]["completed"] is True  # fetched-and-finished entry still applies

    await tracker.poll()
    assert api.get_mission_queue_action.await_count > 25  # cache-missing ones refetched


@pytest.mark.asyncio
async def test_empty_task_list_reports_zero_percent():
    api = make_api(queue_actions=[])
    tracker = MirNativeMissionTasks(api, 99, {})
    await tracker.poll()
    fields = tracker.report_fields()
    assert fields["tasks"] == [] and fields["completedPercent"] == 0


POSITION_CHOICES = {
    "choices": [
        {"name": "Warehouse-1", "value": "pos-guid"},
        {"name": "Dock charger 285", "value": "dock-guid"},
    ]
}

# Shaped like GET /actions?whitelist=action_type,name,description,parameters on a real
# robot: a label template plus, per parameter, the type and value list to fill it in.
ACTION_DEFS = [
    {
        "action_type": "move",
        "name": "Move",
        "description": "Move to %(position)s",
        "parameters": [{"id": "position", "type": "Reference", "constraints": POSITION_CHOICES}],
    },
    {
        "action_type": "docking",
        "name": "Docking",
        "description": "Dock to %(marker)s",
        "parameters": [{"id": "marker", "type": "Reference", "constraints": POSITION_CHOICES}],
    },
    {"action_type": "charging", "name": "Charging", "description": "Charging", "parameters": []},
    {
        "action_type": "wait",
        "name": "Wait",
        "description": "Wait for %(time)s.",
        "parameters": [{"id": "time", "type": "Duration", "constraints": {}}],
    },
    {
        "action_type": "wait_for_plc_register",
        "name": "Wait for PLC register",
        "description": "Wait for PLC register %(register)d to become %(value)f.",
        "parameters": [
            # Real PLC register choices have blank names.
            {
                "id": "register",
                "type": "Reference",
                "constraints": {"choices": [{"name": "", "value": 1}]},
            },
            {"id": "value", "type": "Float", "constraints": {}},
        ],
    },
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
    return tracking


def def_action(guid, action_type="move", parameters=None, priority=1, scope_reference=None):
    return {
        "guid": guid,
        "action_type": action_type,
        "parameters": parameters or [],
        "priority": priority,
        "scope_reference": scope_reference,
        "mission_id": "def-guid",
    }


@pytest.mark.asyncio
async def test_build_tasks_drops_scope_containers_but_keeps_their_body():
    tracking = make_tracking()
    body_scope = "p-content"
    actions = [
        def_action(
            "g-loop",
            "loop",
            [{"id": "content", "guid": body_scope, "value": ""}],
            priority=0,
        ),
        def_action("g-inner", "move", priority=0, scope_reference=body_scope),
        def_action("g-after", "docking", priority=1),
    ]
    tasks = await tracking._build_tasks(actions)
    # The loop itself is a container: it may never report finished, and while its body runs
    # it would show as a second task in progress.
    assert list(tasks) == ["g-inner", "g-after"]


@pytest.mark.asyncio
async def test_build_tasks_labels_and_order():
    tracking = make_tracking()
    actions = [
        def_action("g1", "move", [{"id": "position", "value": "pos-guid"}], priority=1),
        def_action("g2", "docking", [{"id": "marker", "value": "dock-guid"}], priority=2),
        def_action("g3", "charging", priority=3),
        def_action("g4", "unknown_type", priority=4),
        def_action("g5", "wait", [{"id": "time", "value": "00:01:30.000000"}], priority=5),
    ]
    tasks = await tracking._build_tasks(actions)
    assert list(tasks) == ["g1", "g2", "g3", "g4", "g5"]
    assert tasks["g1"]["label"] == "Move to Warehouse-1"
    assert tasks["g2"]["label"] == "Dock to Dock charger 285"
    assert tasks["g3"]["label"] == "Charging"
    # No definition at all (GET /actions does not list every type, e.g. load_mission):
    # the raw action type, tidied up, is the last resort.
    assert tasks["g4"]["label"] == "Unknown type"
    assert tasks["g5"]["label"] == "Wait for 1 min 30 sec."
    assert tasks["g1"] == {
        "taskId": "g1",
        "label": "Move to Warehouse-1",
        "inProgress": False,
        "completed": False,
    }


@pytest.mark.asyncio
async def test_build_tasks_renders_non_reference_parameters():
    # A reference whose choice has a blank name still resolves, to the raw value.
    tracking = make_tracking()
    actions = [
        def_action(
            "g1",
            "wait_for_plc_register",
            # MiR stores the register as a string where the choice value is an int.
            [{"id": "register", "value": "1"}, {"id": "value", "value": 1.0}],
        )
    ]
    tasks = await tracking._build_tasks(actions)
    assert tasks["g1"]["label"] == "Wait for PLC register 1 to become 1.0."


@pytest.mark.asyncio
async def test_build_tasks_variable_position_falls_back_to_action_name():
    # Parameterized missions carry input_name and a null value in the definition.
    tracking = make_tracking()
    actions = [def_action("g1", "move", [{"id": "position", "value": None, "input_name": "p"}])]
    tasks = await tracking._build_tasks(actions)
    assert tasks["g1"]["label"] == "Move"


@pytest.mark.asyncio
async def test_build_tasks_unknown_position_falls_back_to_action_name():
    # A position deleted from the robot is no longer among the action's choices. The label
    # degrades to the action name rather than showing a bare guid.
    tracking = make_tracking()
    actions = [def_action("g1", "move", [{"id": "position", "value": "deleted-guid"}])]
    tasks = await tracking._build_tasks(actions)
    assert tasks["g1"]["label"] == "Move"


@pytest.mark.asyncio
async def test_build_tasks_labels_need_no_extra_requests():
    # Everything a label needs comes from the one cached /actions response.
    tracking = make_tracking()
    actions = [
        def_action("g1", "move", [{"id": "position", "value": "pos-guid"}]),
        def_action("g2", "move", [{"id": "position", "value": "pos-guid"}]),
    ]
    await tracking._build_tasks(actions)
    await tracking._build_tasks(actions)
    assert tracking.mir_api.get_action_definitions.await_count == 1
    assert not [c for c in tracking.mir_api.mock_calls if "position" in str(c)]


@pytest.mark.asyncio
async def test_action_definitions_failure_uses_raw_types_and_retries():
    tracking = make_tracking()
    tracking.mir_api.get_action_definitions = AsyncMock(side_effect=RuntimeError("boom"))
    tasks = await tracking._build_tasks([def_action("g1", "move")])
    assert tasks["g1"]["label"] == "Move"
    # A later mission retries the fetch instead of caching the failure.
    tracking.mir_api.get_action_definitions = AsyncMock(return_value=ACTION_DEFS)
    tasks = await tracking._build_tasks([def_action("g2", "move")])
    assert tasks["g2"]["label"] == "Move"


def wire_mission(tracking, def_actions, entry_state="Executing", finished=None):
    """Wire mir_api mocks for one native mission (queue id 7)."""
    entry = {
        "state": entry_state,
        "id": 7,
        "mission_id": "def-guid",
        "started": "2026-08-10T10:00:00",
        "finished": finished,
    }
    tracking.mir_api.get_executing_mission_id = AsyncMock(return_value=7)
    tracking.mir_api.get_mission_queue_entry = AsyncMock(return_value=dict(entry))
    tracking.mir_api.get_mission_definition = AsyncMock(
        return_value={"guid": "def-guid", "name": "Patrol"}
    )
    tracking.mir_api.get_mission_actions = AsyncMock(return_value=def_actions)
    tracking.mir_api.get_mission_queue_actions = AsyncMock(return_value=[])
    tracking.mir_api.get_mission_queue_action = AsyncMock()


def published(tracking):
    calls = tracking.inorbit_sess.publish_key_values.call_args_list
    return [c.kwargs["key_values"]["mission_tracking"] for c in calls]


STATUS = {"robot_model": "MiR250", "uptime": 10, "serial_number": "s1", "state_id": 3}


@pytest.mark.asyncio
async def test_report_mission_sends_status_while_executing():
    """Without an explicit status the mission renders grey for its whole run.

    The platform can only default a status from its own canonical state names, and MiR's
    "Executing" is not one of them.
    """
    tracking = make_tracking()
    wire_mission(tracking, [def_action("g1")])
    tracking.mir_api.get_mission_queue_actions = AsyncMock(return_value=[])
    await tracking.report_mission(STATUS, {})
    report = published(tracking)[-1]
    assert report["inProgress"] is True
    assert report["status"] == "OK"


@pytest.mark.asyncio
async def test_report_mission_warns_while_robot_is_blocked():
    # Paused (4), emergency stop (10) and error (12) all stop the mission progressing. The
    # mission has not failed, so it is a warning rather than an error.
    for state_id in (4, 10, 12):
        tracking = make_tracking()
        wire_mission(tracking, [def_action("g1")])
        tracking.mir_api.get_mission_queue_actions = AsyncMock(return_value=[])
        await tracking.report_mission({**STATUS, "state_id": state_id}, {})
        report = published(tracking)[-1]
        assert report["status"] == "warning", state_id
        assert report["inProgress"] is True


@pytest.mark.asyncio
async def test_report_mission_republishes_when_status_changes():
    # Nothing else changes when the robot pauses, so without status in the dedup key the
    # warning would never reach the platform.
    tracking = make_tracking()
    wire_mission(tracking, [def_action("g1")])
    tracking.mir_api.get_mission_queue_actions = AsyncMock(return_value=[])
    await tracking.report_mission(STATUS, {})
    await tracking.report_mission(STATUS, {})
    assert len(published(tracking)) == 1  # unchanged, deduplicated
    await tracking.report_mission({**STATUS, "state_id": 4}, {})
    assert [r["status"] for r in published(tracking)] == ["OK", "warning"]


@pytest.mark.asyncio
async def test_report_mission_done_is_ok_and_complete():
    tracking = make_tracking()
    wire_mission(tracking, [def_action("g1")], entry_state="Done", finished="2026-08-10T10:05:00")
    tracking.mir_api.get_mission_queue_actions = AsyncMock(return_value=[])
    await tracking.report_mission(STATUS, {})
    report = published(tracking)[-1]
    assert report["status"] == "OK"
    assert report["completedPercent"] == 1
    assert report["inProgress"] is False


@pytest.mark.asyncio
async def test_report_mission_publishes_tasks_and_current_task():
    tracking = make_tracking()
    wire_mission(tracking, [def_action("g1"), def_action("g2")])
    tracking.mir_api.get_mission_queue_actions = AsyncMock(return_value=[{"id": 1, "url": "u"}])
    tracking.mir_api.get_mission_queue_action = AsyncMock(
        return_value={"id": 1, "action_id": "g1", "finished": None}
    )
    await tracking.report_mission(STATUS, {})
    report = published(tracking)[-1]
    assert report["currentTaskId"] == "g1"
    assert [t["taskId"] for t in report["tasks"]] == ["g1", "g2"]
    assert report["tasks"][0]["inProgress"] is True
    assert report["completedPercent"] == 0
    assert report["inProgress"] is True and report["state"] == "Executing"
    assert report["label"] == "Patrol"


@pytest.mark.asyncio
async def test_report_mission_percent_counts_completed_tasks():
    tracking = make_tracking()
    wire_mission(tracking, [def_action("g1"), def_action("g2")])
    tracking.mir_api.get_mission_queue_actions = AsyncMock(return_value=[{"id": 1, "url": "u"}])
    tracking.mir_api.get_mission_queue_action = AsyncMock(
        return_value={"id": 1, "action_id": "g1", "finished": "2026-08-10T10:01:00"}
    )
    await tracking.report_mission(STATUS, {})
    assert published(tracking)[-1]["completedPercent"] == 0.5


@pytest.mark.asyncio
async def test_report_mission_dedupes_until_task_state_changes():
    tracking = make_tracking()
    wire_mission(tracking, [def_action("g1"), def_action("g2")])
    await tracking.report_mission(STATUS, {})
    await tracking.report_mission(STATUS, {})
    assert len(published(tracking)) == 1  # no change, no republish

    # g1 starts: task transition must republish even though percent is still 0.
    tracking.mir_api.get_mission_queue_actions = AsyncMock(return_value=[{"id": 1, "url": "u"}])
    tracking.mir_api.get_mission_queue_action = AsyncMock(
        return_value={"id": 1, "action_id": "g1", "finished": None}
    )
    await tracking.report_mission(STATUS, {})
    assert len(published(tracking)) == 2
    assert published(tracking)[-1]["currentTaskId"] == "g1"


@pytest.mark.asyncio
async def test_report_mission_done_completes_observed_only():
    # Mission with an untaken if-branch action (g2 never appears in queue actions).
    tracking = make_tracking()
    wire_mission(
        tracking,
        [def_action("g1"), def_action("g2")],
        entry_state="Done",
        finished="2026-08-10T10:05:00",
    )
    tracking.mir_api.get_mission_queue_actions = AsyncMock(return_value=[{"id": 1, "url": "u"}])
    tracking.mir_api.get_mission_queue_action = AsyncMock(
        return_value={"id": 1, "action_id": "g1", "finished": "2026-08-10T10:04:00"}
    )
    await tracking.report_mission(STATUS, {})
    report = published(tracking)[-1]
    by_id = {t["taskId"]: t for t in report["tasks"]}
    assert by_id["g1"]["completed"] is True
    assert by_id["g2"]["completed"] is False  # untaken branch stays incomplete
    assert report["completedPercent"] == 1  # finished missions keep the existing contract
    assert report["status"] == "OK"
    assert "endTs" in report


@pytest.mark.asyncio
async def test_report_mission_abort_completes_observed_only():
    # Mission aborted with an untaken if-branch action (g2 never appears in queue actions).
    tracking = make_tracking()
    wire_mission(
        tracking,
        [def_action("g1"), def_action("g2")],
        entry_state="Abort",
        finished="2026-08-10T10:05:00",
    )
    tracking.mir_api.get_mission_queue_actions = AsyncMock(return_value=[{"id": 1, "url": "u"}])
    tracking.mir_api.get_mission_queue_action = AsyncMock(
        return_value={"id": 1, "action_id": "g1", "finished": "2026-08-10T10:04:00"}
    )
    await tracking.report_mission(STATUS, {})
    report = published(tracking)[-1]
    by_id = {t["taskId"]: t for t in report["tasks"]}
    assert report["state"] == "Aborted"  # merged from 'Abort'
    assert report["status"] == "error"
    assert by_id["g1"]["completed"] is True
    assert by_id["g2"]["completed"] is False  # untaken branch stays incomplete
    assert "endTs" in report
    # An aborted mission is not 100% done. Forcing 1 here contradicted the task list sent
    # in the very same payload.
    assert report["completedPercent"] == 0.5
