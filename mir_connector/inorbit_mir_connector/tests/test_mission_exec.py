# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Wiring tests for MirWorkerPool.

Confirms the worker pool routes the SDK mission engine through the vendored
mission module: native tree builder, translation, context construction, and
deserialization. The pool is built with sentinel ``api``/``db`` and never
started — only the synchronous override hooks are exercised.
"""

from __future__ import annotations

import json
import logging
import unittest.mock as mock
from types import SimpleNamespace

import pytest
from inorbit_connector.commands import CommandResultCode
from inorbit_edge_executor.datatypes import (
    MissionDefinition,
    MissionStepPoseWaypoint,
    Pose,
)
from inorbit_edge_executor.exceptions import TranslationException
from inorbit_edge_executor.mission import Mission

from inorbit_mir_connector.src.mission.behavior_tree import (
    MirBehaviorTreeBuilderContext,
)
from inorbit_mir_connector.src.mission.datatypes import (
    MirInOrbitMission,
    MissionStepExecuteMirNativeMission,
)
from inorbit_mir_connector.src.mission.tree_builder import MirTreeBuilder
from inorbit_mir_connector.src.mission_exec import MirMissionExecutor, MirWorkerPool

ROBOT_ID = "mir-1"


def _make_pool(missions_group=None, firmware_version="v3", connector_type="mir"):
    # WorkerPool only requires a truthy ``api``; ``db`` is untouched until start().
    return MirWorkerPool(
        mir_api=SimpleNamespace(),
        api=object(),
        db=object(),
        missions_group=missions_group,
        firmware_version=firmware_version,
        connector_type=connector_type,
    )


def _waypoint_mission():
    return Mission(
        id="mission-001",
        robot_id=ROBOT_ID,
        definition=MissionDefinition(
            label="test",
            steps=[
                MissionStepPoseWaypoint(waypoint=Pose(x=1, y=2, theta=0), label="a"),
                MissionStepPoseWaypoint(waypoint=Pose(x=3, y=4, theta=0), label="b"),
            ],
        ),
    )


def test_uses_mir_tree_builder():
    pool = _make_pool()
    assert isinstance(pool._behavior_tree_builder, MirTreeBuilder)


def test_translate_mission_compiles_to_native():
    pool = _make_pool()
    result = pool.translate_mission(_waypoint_mission())

    assert isinstance(result, MirInOrbitMission)
    assert len(result.definition.steps) == 1
    assert isinstance(result.definition.steps[0], MissionStepExecuteMirNativeMission)


def test_create_builder_context_carries_handles():
    group = SimpleNamespace(missions_group_id="grp-xyz")
    mir_api = SimpleNamespace()
    pool = MirWorkerPool(
        mir_api=mir_api,
        api=object(),
        db=object(),
        missions_group=group,
        firmware_version="v2",
        connector_type="mir",
    )
    ctx = pool.create_builder_context()

    assert isinstance(ctx, MirBehaviorTreeBuilderContext)
    assert ctx.mir_api is mir_api
    assert ctx.missions_group_id == "grp-xyz"
    assert ctx.firmware_version == "v2"
    assert ctx.connector_type == "mir"


def test_create_builder_context_without_group():
    pool = _make_pool(missions_group=None)
    ctx = pool.create_builder_context()
    assert ctx.missions_group_id is None


def test_deserialize_mission_round_trips():
    pool = _make_pool()
    translated = pool.translate_mission(_waypoint_mission())
    serialized = translated.model_dump(mode="json", exclude_none=True)

    restored = pool.deserialize_mission(serialized)

    assert isinstance(restored, MirInOrbitMission)
    assert isinstance(restored.definition.steps[0], MissionStepExecuteMirNativeMission)


@pytest.mark.asyncio
async def test_translate_failure_surfaces_reason():
    """A swallowed translate-time error reaches result_function, not an empty detail."""
    reason = "runAction step 'x': 'if' is a control-flow action"

    async def fail(*_a, **_kw):
        try:
            raise ValueError(reason)
        except ValueError:
            raise TranslationException()  # bare, chains the ValueError on __context__

    executor = MirMissionExecutor.__new__(MirMissionExecutor)
    executor.logger = logging.getLogger("test")
    executor.robot_id = ROBOT_ID
    executor._worker_pool = SimpleNamespace(submit_work=fail)

    result_function = mock.MagicMock()
    await executor._handle_execute_mission_action(
        {"missionId": "m1", "missionDefinition": json.dumps({"steps": []})},
        {"result_function": result_function},
    )

    result_function.assert_called_once()
    assert result_function.call_args.args[0] == CommandResultCode.FAILURE
    assert reason in result_function.call_args.kwargs["execution_status_details"]
