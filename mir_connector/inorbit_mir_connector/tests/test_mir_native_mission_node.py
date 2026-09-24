# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Execution tests for CreateMirNativeMissionNode.

Unlike the vendored ``test_behavior_tree.py`` (which only covers step
serialization), this exercises the node's ``_execute`` against a mocked
``MirApiV2``: it must create a native MiR mission in the missions group, add
one action per entry (resolving docking markers), queue it, and record the
mission/queue ids in shared memory. Written here (not vendored) because the
upstream module ships no execution test for this node.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from inorbit_edge_executor.datatypes import MissionRuntimeSharedMemory

from inorbit_mir_connector.src.mir_api import MirApiV2
from inorbit_mir_connector.src.mission.behavior_tree import (
    CleanupMirMissionNode,
    MirBehaviorTreeBuilderContext,
    MirMissionAbortedNode,
    SharedMemoryKeys,
)
from inorbit_mir_connector.src.mission.datatypes import (
    MirAction,
    MirWaypoint,
)

from inorbit_mir_connector.tests.conftest import (
    FakeMirApi,
    build_create_node as _build_node,
)

_MARKER = "00000000-0000-0000-0000-00000000aaaa"
_OFFSET = "00000000-0000-0000-0000-00000000bbbb"


def _action_param_ids(action):
    """Set of MiR parameter ``id``s recorded for an add_action_to_mission call."""
    return {p["id"] for p in action["parameters"]}


@pytest.mark.asyncio
async def test_creates_adds_actions_and_queues():
    api = FakeMirApi(queue_id=99)
    node, ctx = _build_node(
        api,
        [
            MirWaypoint(label="wp1", x=1.0, y=2.0, orientation=90.0),
            MirWaypoint(label="wp2", x=3.0, y=4.0, orientation=180.0),
            MirAction(label="Wait", action_type="wait", parameters={"time": "00:00:05.000000"}),
        ],
    )

    await node._execute()

    # One mission created in the configured group.
    assert len(api.created) == 1
    assert api.created[0]["group_id"] == "grp-1"
    mission_guid = api.created[0]["guid"]

    # One action per entry, in order, priorities 1..N.
    assert [a["action_type"] for a in api.actions] == [
        "move_to_position",
        "move_to_position",
        "wait",
    ]
    assert [a["priority"] for a in api.actions] == [1, 2, 3]
    assert all(a["mission_id"] == mission_guid for a in api.actions)

    # Queued once, ids stashed in shared memory.
    assert api.queued == [mission_guid]
    assert ctx.shared_memory.get(SharedMemoryKeys.MIR_MISSION_GUID) == mission_guid
    assert ctx.shared_memory.get(SharedMemoryKeys.MIR_QUEUE_ID) == 99


@pytest.mark.asyncio
async def test_waypoint_params_v3_use_blocked_path_timeout():
    api = FakeMirApi()
    node, _ = _build_node(
        api, [MirWaypoint(label="wp", x=1, y=2, orientation=0)], firmware_version="v3"
    )

    await node._execute()

    ids = _action_param_ids(api.actions[0])
    assert "blocked_path_timeout" in ids
    assert "retries" not in ids


@pytest.mark.asyncio
async def test_waypoint_params_v2_use_retries():
    api = FakeMirApi()
    node, _ = _build_node(
        api, [MirWaypoint(label="wp", x=1, y=2, orientation=0)], firmware_version="v2"
    )

    await node._execute()

    ids = _action_param_ids(api.actions[0])
    assert "retries" in ids
    assert "blocked_path_timeout" not in ids


@pytest.mark.asyncio
async def test_missing_missions_group_raises():
    api = FakeMirApi()
    node, ctx = _build_node(
        api, [MirWaypoint(label="wp", x=1, y=2, orientation=0)], missions_group_id=None
    )

    with pytest.raises(RuntimeError, match="enable_temporary_mission_group"):
        await node._execute()

    assert api.created == []
    # The operator-facing error names both remedies so it is actionable.
    error_msg = ctx.shared_memory.get(SharedMemoryKeys.MIR_ERROR_MESSAGE)
    assert "enable_temporary_mission_group" in error_msg
    assert "predefined missions group" in error_msg


@pytest.mark.asyncio
async def test_docking_marker_type_resolved():
    api = FakeMirApi(offsets_by_marker={_MARKER: [{"guid": _OFFSET}]})
    node, ctx = _build_node(
        api, [MirAction(label="Dock", action_type="docking", parameters={"marker": _MARKER})]
    )

    await node._execute()

    params = {p["id"]: p["value"] for p in api.actions[0]["parameters"]}
    assert params["marker_type"] == _OFFSET
    assert api.queued == [api.created[0]["guid"]]


@pytest.mark.asyncio
async def test_docking_without_offset_raises_and_does_not_queue():
    api = FakeMirApi(offsets_by_marker={})  # no offset for the marker
    node, ctx = _build_node(
        api, [MirAction(label="Dock", action_type="docking", parameters={"marker": _MARKER})]
    )

    with pytest.raises(RuntimeError):
        await node._execute()

    assert api.queued == []
    assert ctx.shared_memory.get(SharedMemoryKeys.MIR_ERROR_MESSAGE)


@pytest.mark.asyncio
async def test_create_failure_surfaces_mir_reason_in_error_message(httpx_mock):
    """A MiR 4xx body (the reason it rejected the request) must reach the
    operator-facing abort, not just the logs.

    Drives the real MirApiV2 so the full chain is exercised: create_mission
    400s -> mir_api_base._request augments the HTTPStatusError with the body ->
    CreateMirNativeMissionNode surfaces ``{e}`` into MIR_ERROR_MESSAGE. A bare
    HTTPStatusError would put only the status line ("400 Bad Request") there.
    """
    api = MirApiV2(
        mir_host_address="example.com",
        mir_host_port=8080,
        mir_use_ssl=False,
        mir_username="user",
        mir_password="pass",
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{api.mir_api_base_url}/missions",
        status_code=400,
        json={"error": {"message": "action parameter 'time' is invalid"}},
    )
    node, ctx = _build_node(
        api, [MirAction(label="Wait", action_type="wait", parameters={"time": "nope"})]
    )

    with pytest.raises(RuntimeError):
        await node._execute()

    error_msg = ctx.shared_memory.get(SharedMemoryKeys.MIR_ERROR_MESSAGE)
    assert "action parameter 'time' is invalid" in error_msg


def _build_abort_context(api, queue_id):
    """Context with a frozen shared memory holding (optionally) a queue id.

    Mirrors the shape CreateMirNativeMissionNode leaves behind: the queue/error
    keys are declared, the memory is frozen, then the queue id is stored. Pass
    queue_id=None to model an abort before any mission was queued.
    """
    ctx = MirBehaviorTreeBuilderContext(
        mir_api=api,
        missions_group_id="grp-1",
        firmware_version="v3",
        connector_type="mir",
        mt=AsyncMock(),
        error_context={"last_error": "boom"},
    )
    sm = MissionRuntimeSharedMemory()
    sm.add(SharedMemoryKeys.MIR_QUEUE_ID, None)
    sm.add(SharedMemoryKeys.MIR_ERROR_MESSAGE, None)
    sm.freeze()
    if queue_id is not None:
        sm.set(SharedMemoryKeys.MIR_QUEUE_ID, queue_id)
    ctx.shared_memory = sm
    return ctx


@pytest.mark.asyncio
async def test_abort_node_scopes_abort_to_queue_entry():
    api = FakeMirApi()
    ctx = _build_abort_context(api, queue_id=42)
    node = MirMissionAbortedNode(ctx)

    await node._execute()

    # Only the one queued mission is aborted; the queue is left otherwise intact.
    assert api.aborted_entries == [42]
    assert api.abort_all_count == 0
    # Base MissionAbortedNode still reports the abort to mission tracking.
    ctx.mt.abort.assert_awaited_once()


@pytest.mark.asyncio
async def test_abort_node_without_queue_id_aborts_nothing():
    api = FakeMirApi()
    ctx = _build_abort_context(api, queue_id=None)
    node = MirMissionAbortedNode(ctx)

    await node._execute()

    # No queue id -> no MiR abort call at all (no fallback to abort_all_missions).
    assert api.aborted_entries == []
    assert api.abort_all_count == 0
    ctx.mt.abort.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_node_scopes_abort_to_queue_entry():
    api = FakeMirApi()
    ctx = _build_abort_context(api, queue_id=42)
    node = CleanupMirMissionNode(ctx)

    await node._execute()

    assert api.aborted_entries == [42]
    assert api.abort_all_count == 0


@pytest.mark.asyncio
async def test_cleanup_node_without_queue_id_is_noop():
    api = FakeMirApi()
    ctx = _build_abort_context(api, queue_id=None)
    node = CleanupMirMissionNode(ctx)

    await node._execute()

    assert api.aborted_entries == []
    assert api.abort_all_count == 0
