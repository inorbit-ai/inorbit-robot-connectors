# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Native-mission runtime-state survival across resume (spec §11.2).

A native MiR step records the MiR queue id and mission guid in the mission's
``shared_memory`` (CreateMirNativeMissionNode), and a later node polls that
queue id until completion (WaitForMirMissionCompletionNode). If a mission is
paused / the connector restarts mid native step, that runtime state must
survive so the resumed mission keeps watching the *same* MiR mission instead
of re-creating it or failing.

inorbit-edge-executor 4.0.x serializes ``shared_memory`` as part of the worker
state (``Worker.dump_object`` -> ``state["shared_memory"]``, restored by
``WorkerPool.build_worker_from_serialized``), and ``BehaviorTreeSequential``
skips already-run nodes (those whose serialized state is terminal) on resume.

The tests cover three slices of the contract:
  * runtime state survives a real serialize -> SQLite -> resume round trip;
  * after the create node has run and is serialized, a resumed native subtree
    skips it (no duplicate MiR mission) and the completion poll resumes from the
    restored queue id;
  * a missing queue id still raises "No MiR queue ID in shared memory".
"""

from __future__ import annotations

import copy
import os
import tempfile
import unittest.mock as mock
from types import SimpleNamespace

import pytest
from inorbit_edge_executor.behavior_tree import BehaviorTreeSequential, build_tree_from_object
from inorbit_edge_executor.datatypes import (
    MissionDefinition,
    MissionRuntimeOptions,
    MissionRuntimeSharedMemory,
    MissionStepPoseWaypoint,
    Pose,
)
from inorbit_edge_executor.db import get_db
from inorbit_edge_executor.mission import Mission
from inorbit_edge_executor.worker import Worker

from inorbit_mir_connector.src.mission.behavior_tree import (
    CreateMirNativeMissionNode,
    MirBehaviorTreeBuilderContext,
    SharedMemoryKeys,
    WaitForMirMissionCompletionNode,
)
from inorbit_mir_connector.src.mission.datatypes import (
    MirWaypoint,
    MissionStepExecuteMirNativeMission,
)
from inorbit_mir_connector.src.mission_exec import MirWorkerPool

ROBOT_ID = "mir-1"
QUEUE_ID = 777
MISSION_GUID = "guid-xyz"


def _native_mission():
    return Mission(
        id="m1",
        robot_id=ROBOT_ID,
        definition=MissionDefinition(
            label="t",
            steps=[
                MissionStepPoseWaypoint(waypoint=Pose(x=1, y=2, theta=0), label="a"),
                MissionStepPoseWaypoint(waypoint=Pose(x=3, y=4, theta=0), label="b"),
            ],
        ),
    )


def _make_pool(db):
    return MirWorkerPool(
        mir_api=mock.MagicMock(),
        api=mock.MagicMock(),
        db=db,
        missions_group=SimpleNamespace(missions_group_id="grp"),
        firmware_version="v3",
        connector_type="mir",
    )


class _FakeMirApi:
    """mir_api stub whose queue entry returns a fixed state."""

    def __init__(self, state="Done"):
        self._state = state
        self.polled = []

    async def get_mission_queue_entry(self, queue_id):
        self.polled.append(queue_id)
        return {"state": self._state}


@pytest.mark.asyncio
async def test_native_runtime_state_survives_sqlite_roundtrip():
    """queue id + guid survive serialize -> SQLite -> resume (the §11.2 concern)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = await get_db(f"sqlite:{tmp.name}")
    try:
        pool = _make_pool(db)
        translated = pool.translate_mission(_native_mission())
        opts = MissionRuntimeOptions()
        sm = MissionRuntimeSharedMemory()
        ctx = pool.create_builder_context()
        pool.prepare_builder_context(ctx, translated)
        ctx.shared_memory = sm
        ctx.options = opts
        tree = pool._behavior_tree_builder.build_tree_for_mission(ctx)
        sm.freeze()

        # Simulate CreateMirNativeMissionNode having queued the mission.
        sm.set(SharedMemoryKeys.MIR_QUEUE_ID, QUEUE_ID)
        sm.set(SharedMemoryKeys.MIR_MISSION_GUID, MISSION_GUID)

        worker = Worker(translated, opts, sm)
        worker.set_behavior_tree(tree)
        worker.set_paused(True)
        await db.save_mission(worker.serialize())

        # New pool over the same DB file = connector restart.
        db2 = await get_db(f"sqlite:{tmp.name}")
        try:
            pool2 = _make_pool(db2)
            fetched = await pool2._db.fetch_mission(mission_id="m1")
            # Rebuilding the tree re-runs CreateMirNativeMissionNode.__init__ (which
            # add()s the keys); the restored values must not be reset to None.
            restored = pool2.build_worker_from_serialized(fetched)
            assert restored.shared_memory.get(SharedMemoryKeys.MIR_QUEUE_ID) == QUEUE_ID
            assert restored.shared_memory.get(SharedMemoryKeys.MIR_MISSION_GUID) == MISSION_GUID
        finally:
            await db2.shutdown()
    finally:
        await db.shutdown()
        os.unlink(tmp.name)


def _wait_node(mir_api, queue_id=QUEUE_ID, guid=MISSION_GUID):
    """Build a WaitForMirMissionCompletionNode on a frozen, populated context."""
    sm = MissionRuntimeSharedMemory()
    sm.add(SharedMemoryKeys.MIR_QUEUE_ID, None)
    sm.add(SharedMemoryKeys.MIR_MISSION_GUID, None)
    sm.add(SharedMemoryKeys.MIR_ERROR_MESSAGE, None)
    sm.freeze()
    if queue_id is not None:
        sm.set(SharedMemoryKeys.MIR_QUEUE_ID, queue_id)
        sm.set(SharedMemoryKeys.MIR_MISSION_GUID, guid)
    ctx = MirBehaviorTreeBuilderContext(
        mir_api=mir_api,
        missions_group_id="grp",
        firmware_version="v3",
        connector_type="mir",
    )
    ctx.shared_memory = sm
    return WaitForMirMissionCompletionNode(ctx)


@pytest.mark.asyncio
async def test_wait_node_resumes_from_restored_queue_id():
    """With the queue id restored, the completion poll resumes (no 'No queue ID')."""
    api = _FakeMirApi(state="Done")
    node = _wait_node(api)
    await node._execute()  # returns cleanly when the entry is Done
    assert api.polled == [QUEUE_ID]


@pytest.mark.asyncio
async def test_wait_node_without_queue_id_raises():
    """Contract: a missing queue id (the old stale-resume failure) raises clearly."""
    api = _FakeMirApi(state="Done")
    node = _wait_node(api, queue_id=None)
    with pytest.raises(RuntimeError, match="No MiR queue ID"):
        await node._execute()


class _RecordingMirApi:
    """mir_api stub recording the native-mission calls, for the resume-skip test."""

    def __init__(self, state="Done"):
        self._state = state
        self.created = []
        self.queued = []
        self.polled = []

    async def create_mission(self, group_id, name, guid, description):
        self.created.append(guid)

    async def add_action_to_mission(self, action_type, mission_id, parameters, priority):
        pass

    async def queue_mission(self, mission_guid):
        self.queued.append(mission_guid)
        return {"id": QUEUE_ID}

    async def get_mission_queue_entry(self, queue_id):
        self.polled.append(queue_id)
        return {"state": self._state}


def _native_subtree(ctx, step):
    """Mirror MirNodeFromStepBuilder.visit_execute_mir_native_mission."""
    seq = BehaviorTreeSequential(label=step.label)
    seq.add_node(CreateMirNativeMissionNode(ctx, step, label="create"))
    seq.add_node(WaitForMirMissionCompletionNode(ctx, label="wait"))
    return seq


@pytest.mark.asyncio
async def test_resume_skips_create_node_no_duplicate_mission():
    """After the create node ran and was serialized, resume must NOT re-create/queue.

    Drives the real node-skip path: execute the create node (which queues the MiR
    mission and records the queue id), serialize the subtree + shared_memory, then
    rebuild and execute against a fresh recording API. The rebuilt create node is
    skipped (terminal serialized state) so no second create/queue happens, and the
    wait node resumes from the restored queue id.
    """
    step = MissionStepExecuteMirNativeMission(
        label="grp",
        actions=[MirWaypoint(label="wp", x=1.0, y=2.0, orientation=0.0)],
        robot_id=ROBOT_ID,
    )

    api1 = _RecordingMirApi(state="Executing")  # mission still running at pause time
    sm = MissionRuntimeSharedMemory()
    ctx = MirBehaviorTreeBuilderContext(
        mir_api=api1, missions_group_id="grp", firmware_version="v3", connector_type="mir"
    )
    ctx.shared_memory = sm
    subtree = _native_subtree(ctx, step)
    sm.freeze()

    # Run only the create node (simulates a pause taken during the wait poll).
    await subtree.nodes[0].execute()
    assert api1.created and api1.queued  # mission was created + queued once
    assert sm.get(SharedMemoryKeys.MIR_QUEUE_ID) == QUEUE_ID

    # Serialize subtree + shared memory (what the worker persists).
    tree_dump = copy.deepcopy(subtree.dump_object())
    sm_dump = sm.model_dump()

    # Rebuild on a fresh API = resume after restart.
    api2 = _RecordingMirApi(state="Done")
    sm2 = MissionRuntimeSharedMemory.model_validate(sm_dump)
    ctx2 = MirBehaviorTreeBuilderContext(
        mir_api=api2, missions_group_id="grp", firmware_version="v3", connector_type="mir"
    )
    ctx2.shared_memory = sm2
    sm2.frozen = False
    subtree2 = build_tree_from_object(ctx2, tree_dump)
    sm2.freeze()

    await subtree2.execute()

    # Create node skipped: no second mission created or queued on resume.
    assert api2.created == []
    assert api2.queued == []
    # Wait node resumed from the restored queue id and saw it complete.
    assert api2.polled == [QUEUE_ID]
