# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Native-mission completion timeout (translator timeout aggregation).

The translator never set a timeout on the compiled
``MissionStepExecuteMirNativeMission``, so ``WaitForMirMissionCompletionNode``
polled the MiR mission queue forever. The translator now stamps ``timeout_secs``
onto the emitted native step as the SUM of the grouped steps' ``timeout_secs``,
but ONLY when every grouped step is bounded; if any grouped step is unbounded the
native step stays unbounded (preserving prior behavior).

These tests pin that aggregation.
"""

from __future__ import annotations

from inorbit_edge_executor.datatypes import (
    MissionDefinition,
    MissionStepPoseWaypoint,
    MissionStepWait,
    Pose,
)
from inorbit_edge_executor.mission import Mission

from inorbit_mir_connector.src.mission.datatypes import MissionStepExecuteMirNativeMission
from inorbit_mir_connector.src.mission.translator import InOrbitToMirTranslator

ROBOT_ID = "mir-1"


def _wp(timeout=None, x=1.0, y=2.0, theta=0.0, label="wp", complete_task=None):
    kwargs = {"waypoint": Pose(x=x, y=y, theta=theta), "label": label}
    if timeout is not None:
        kwargs["timeoutSecs"] = timeout
    if complete_task is not None:
        kwargs["completeTask"] = complete_task
    return MissionStepPoseWaypoint(**kwargs)


def _wait(timeout, label="wait"):
    return MissionStepWait(timeoutSecs=timeout, label=label)


def _mission(steps):
    return Mission(
        id="m1",
        robot_id=ROBOT_ID,
        definition=MissionDefinition(label="t", steps=steps),
    )


class TestNativeMissionTimeout:
    def test_all_bounded_waypoints_sum(self):
        # [wp(10), wp(20)] -> one native step with timeout 30.
        m = _mission([_wp(10), _wp(20)])
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 1
        step = result.definition.steps[0]
        assert isinstance(step, MissionStepExecuteMirNativeMission)
        assert step.timeout_secs == 30

    def test_any_unbounded_step_leaves_native_unbounded(self):
        # [wp(10), wp()] -> native step unbounded (no premature abort).
        m = _mission([_wp(10), _wp()])
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 1
        step = result.definition.steps[0]
        assert isinstance(step, MissionStepExecuteMirNativeMission)
        assert step.timeout_secs is None

    def test_single_bounded_waypoint(self):
        # [wp(15)] -> timeout 15.
        m = _mission([_wp(15)])
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 1
        step = result.definition.steps[0]
        assert isinstance(step, MissionStepExecuteMirNativeMission)
        assert step.timeout_secs == 15

    def test_wait_duration_contributes(self):
        # [wp(10), wait(5)] -> timeout 15.
        m = _mission([_wp(10), _wait(5)])
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 1
        step = result.definition.steps[0]
        assert isinstance(step, MissionStepExecuteMirNativeMission)
        assert step.timeout_secs == 15

    def test_no_timeouts_anywhere_stays_unbounded(self):
        # [wp(), wp()] -> unbounded (parity with old behavior).
        m = _mission([_wp(), _wp()])
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 1
        step = result.definition.steps[0]
        assert isinstance(step, MissionStepExecuteMirNativeMission)
        assert step.timeout_secs is None

    def test_task_boundary_split_computes_per_group(self):
        # [wp(10, completeTask="t1"), wp(20)] -> first native step timeout 10,
        # second native step unbounded (no timeout aggregated across the split).
        m = _mission([_wp(10, complete_task="t1"), _wp(20)])
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 2
        first, second = result.definition.steps
        assert isinstance(first, MissionStepExecuteMirNativeMission)
        assert first.timeout_secs == 10
        assert isinstance(second, MissionStepExecuteMirNativeMission)
        assert second.timeout_secs == 20
