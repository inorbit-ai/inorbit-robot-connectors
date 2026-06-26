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

import pytest
from inorbit_edge_executor.datatypes import MissionRuntimeSharedMemory

from inorbit_mir_connector.src.mission.behavior_tree import (
    CreateMirNativeMissionNode,
    MirBehaviorTreeBuilderContext,
    SharedMemoryKeys,
)
from inorbit_mir_connector.src.mission.datatypes import (
    MirAction,
    MirWaypoint,
    MissionStepExecuteMirNativeMission,
)

_MARKER = "00000000-0000-0000-0000-00000000aaaa"
_OFFSET = "00000000-0000-0000-0000-00000000bbbb"


class FakeMirApi:
    """Records the native-mission calls CreateMirNativeMissionNode makes."""

    def __init__(self, offsets_by_marker=None, queue_id=42):
        self.created: list[dict] = []
        self.actions: list[dict] = []
        self.queued: list[str] = []
        self._offsets_by_marker = offsets_by_marker or {}
        self._queue_id = queue_id

    async def create_mission(self, group_id, name, guid, description):
        self.created.append(
            {"group_id": group_id, "name": name, "guid": guid, "description": description}
        )

    async def add_action_to_mission(self, action_type, mission_id, parameters, priority):
        self.actions.append(
            {
                "action_type": action_type,
                "mission_id": mission_id,
                "parameters": parameters,
                "priority": priority,
            }
        )

    async def queue_mission(self, mission_guid):
        self.queued.append(mission_guid)
        return {"id": self._queue_id}

    async def get_position_docking_offsets(self, position_guid):
        return self._offsets_by_marker.get(position_guid, [])


def _build_node(api, actions, missions_group_id="grp-1", firmware_version="v3"):
    """Build a CreateMirNativeMissionNode and its (frozen) context.

    Mirrors the real submit_work flow: the node's __init__ registers shared
    memory keys via add(), then the memory is frozen before _execute() runs
    (set() requires a frozen memory).
    """
    ctx = MirBehaviorTreeBuilderContext(
        mir_api=api,
        missions_group_id=missions_group_id,
        firmware_version=firmware_version,
        connector_type="mir",
    )
    ctx.shared_memory = MissionRuntimeSharedMemory()
    step = MissionStepExecuteMirNativeMission(
        label="Native mission", actions=actions, robot_id="mir-1"
    )
    node = CreateMirNativeMissionNode(ctx, step)
    ctx.shared_memory.freeze()
    return node, ctx


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

    with pytest.raises(RuntimeError):
        await node._execute()

    assert api.created == []
    assert ctx.shared_memory.get(SharedMemoryKeys.MIR_ERROR_MESSAGE)


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
