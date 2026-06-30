# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Per-task mission tracking for edge missions.

Two regressions are covered:

  * The translator dropped ``complete_task`` when grouping waypoint/nestable
    steps into a native MiR mission, so ``Mission.tasks_list`` came out empty
    and InOrbit had no tasks to display.
  * ``MirTreeBuilder`` skipped the SDK step-node decorator, so no
    ``TaskStarted``/``TaskCompletedNode`` (nor ``LockRobotNode``) were emitted
    for any step.

These tests pin both the translator's task preservation and the tree builder's
decorator wiring.
"""

from __future__ import annotations

import unittest.mock as mock
from types import SimpleNamespace

from inorbit_edge_executor.behavior_tree import (
    LockRobotNode,
    TaskCompletedNode,
    TaskStartedNode,
)
from inorbit_edge_executor.datatypes import (
    MissionDefinition,
    MissionRuntimeOptions,
    MissionRuntimeSharedMemory,
    MissionStepPoseWaypoint,
    MissionStepRunAction,
    MissionStepSetData,
    MissionStepWait,
    Pose,
)
from inorbit_edge_executor.mission import Mission

from inorbit_mir_connector.src.mission.behavior_tree import WaitForMirMissionCompletionNode
from inorbit_mir_connector.src.mission.datatypes import MissionStepExecuteMirNativeMission
from inorbit_mir_connector.src.mission.translator import InOrbitToMirTranslator
from inorbit_mir_connector.src.mission_exec import MirWorkerPool

ROBOT_ID = "mir-1"


def _wp(x, y, theta=0.0, label="wp", complete_task=None):
    kwargs = {"waypoint": Pose(x=x, y=y, theta=theta), "label": label}
    if complete_task is not None:
        kwargs["completeTask"] = complete_task
    return MissionStepPoseWaypoint(**kwargs)


def _run_action(action_id, label="action", complete_task=None):
    kwargs = {"runAction": {"actionId": action_id}, "label": label}
    if complete_task is not None:
        kwargs["completeTask"] = complete_task
    return MissionStepRunAction(**kwargs)


def _mission(steps):
    return Mission(
        id="m1",
        robot_id=ROBOT_ID,
        definition=MissionDefinition(label="t", steps=steps),
    )


def _task_ids(mission):
    return [t.task_id for t in (mission.tasks_list or [])]


# --------------------------------------------------------------------------- #
# Translator: complete_task preservation
# --------------------------------------------------------------------------- #


class TestTranslatorPreservesCompleteTask:
    def test_grouped_waypoint_task_is_preserved(self):
        m = _mission([_wp(1, 2, complete_task="task-1")])
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 1
        step = result.definition.steps[0]
        assert isinstance(step, MissionStepExecuteMirNativeMission)
        # The native step rides no single task; the task is carried per-action instead.
        assert step.complete_task is None
        assert step.action_task_ids == ["task-1"]
        # The task must reach the mission's tasks_list (what InOrbit displays).
        assert _task_ids(result) == ["task-1"]

    def test_task_on_middle_step_no_longer_splits_group(self):
        # A task on a middle waypoint no longer flushes the group: all three waypoints
        # compile into one native step, the task riding the middle action.
        m = _mission([_wp(1, 2), _wp(3, 4, complete_task="t1"), _wp(5, 6)])
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 1
        step = result.definition.steps[0]
        assert isinstance(step, MissionStepExecuteMirNativeMission)
        assert [type(a).__name__ for a in step.actions] == [
            "MirWaypoint",
            "MirWaypoint",
            "MirWaypoint",
        ]
        assert step.complete_task is None
        assert step.action_task_ids == [None, "t1", None]
        assert _task_ids(result) == ["t1"]

    def test_multiple_tasks_each_reported(self):
        m = _mission(
            [
                _wp(1, 2, complete_task="t1"),
                _wp(3, 4),
                MissionStepWait(timeoutSecs=5, label="w", completeTask="t2"),
            ]
        )
        result = InOrbitToMirTranslator.translate(m)
        # One native step carries both tasks, parallel to its actions.
        assert len(result.definition.steps) == 1
        assert result.definition.steps[0].action_task_ids == ["t1", None, "t2"]
        assert _task_ids(result) == ["t1", "t2"]

    def test_production_payload_groups_into_one_native_mission(self):
        # The reported regression shape: [setData, wp, wp, wait, wp] with a task on each
        # nestable step. setData passes through; the four nestable steps compile into ONE
        # native mission carrying all four tasks (parallel to actions).
        m = _mission(
            [
                MissionStepSetData(data={"waypointDistanceTolerance": 1}, label="set"),
                _wp(1, 2, label="a", complete_task="a"),
                _wp(3, 4, label="b", complete_task="b"),
                MissionStepWait(timeoutSecs=5, label="Wait 5 sec", completeTask="Wait 5 sec"),
                _wp(5, 6, label="c", complete_task="c"),
            ]
        )
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 2
        passthrough, native = result.definition.steps
        assert isinstance(passthrough, MissionStepSetData)
        assert isinstance(native, MissionStepExecuteMirNativeMission)
        assert [type(a).__name__ for a in native.actions] == [
            "MirWaypoint",
            "MirWaypoint",
            "MirAction",
            "MirWaypoint",
        ]
        assert native.complete_task is None
        assert native.action_task_ids == ["a", "b", "Wait 5 sec", "c"]
        assert _task_ids(result) == ["a", "b", "Wait 5 sec", "c"]

    def test_consecutive_no_task_waypoints_still_group(self):
        # Behaviour unchanged when no step carries complete_task.
        m = _mission([_wp(1, 2), _wp(3, 4), _wp(5, 6)])
        result = InOrbitToMirTranslator.translate(m)
        assert len(result.definition.steps) == 1
        assert result.definition.steps[0].complete_task is None
        assert _task_ids(result) == []

    def test_non_nestable_passthrough_keeps_task(self):
        # A non-nestable run_action passes through unchanged and keeps its task.
        m = _mission(
            [
                _wp(1, 2),
                _run_action("unknown_action", complete_task="t-pass"),
                _wp(3, 4),
            ]
        )
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 3
        passthrough = result.definition.steps[1]
        assert isinstance(passthrough, MissionStepRunAction)
        assert passthrough.complete_task == "t-pass"
        assert _task_ids(result) == ["t-pass"]


# --------------------------------------------------------------------------- #
# Tree builder: decorator wiring
# --------------------------------------------------------------------------- #


def _build_tree(mission):
    pool = MirWorkerPool(
        mir_api=mock.MagicMock(),
        api=mock.MagicMock(),
        db=mock.MagicMock(),
        missions_group=SimpleNamespace(missions_group_id="grp"),
        firmware_version="v3",
        connector_type="mir",
    )
    translated = pool.translate_mission(mission)
    ctx = pool.create_builder_context()
    pool.prepare_builder_context(ctx, translated)
    ctx.shared_memory = MissionRuntimeSharedMemory()
    ctx.options = MissionRuntimeOptions()
    tree = pool._behavior_tree_builder.build_tree_for_mission(ctx)
    nodes = []
    tree.collect_nodes(nodes)
    return nodes


def test_grouped_task_tracked_by_wait_node_not_decorator():
    nodes = _build_tree(_mission([_wp(1, 2, complete_task="task-1")]))
    # Grouping drops the per-step decorator task nodes; the wait node carries the task and
    # reports it from the native mission's per-action progress instead.
    assert not any(isinstance(n, TaskStartedNode) for n in nodes)
    assert not any(isinstance(n, TaskCompletedNode) for n in nodes)
    wait_nodes = [n for n in nodes if isinstance(n, WaitForMirMissionCompletionNode)]
    assert len(wait_nodes) == 1
    assert wait_nodes[0]._action_task_ids == ["task-1"]
    # LockRobotNode is always added by the decorator (no-op unless use_locks).
    assert any(isinstance(n, LockRobotNode) for n in nodes)


def test_tree_has_no_task_nodes_without_complete_task():
    nodes = _build_tree(_mission([_wp(1, 2), _wp(3, 4)]))
    assert not any(isinstance(n, TaskStartedNode) for n in nodes)
    assert not any(isinstance(n, TaskCompletedNode) for n in nodes)
    # decorator still runs, so robot-lock nodes are present.
    assert any(isinstance(n, LockRobotNode) for n in nodes)
