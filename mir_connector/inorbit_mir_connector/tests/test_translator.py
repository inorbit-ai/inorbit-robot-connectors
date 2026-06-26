# SPDX-FileCopyrightText: 2026 Mappalink
#
# SPDX-License-Identifier: MIT
#
# Vendored from the Mappalink MiR connector:
#   https://github.com/mappalink/inorbit-mir-connector/blob/c516f7d9e8e6b8b3cbaa396e2984ce149c6e7925/tests/test_translator.py
# Upstream commit: c516f7d9e8e6b8b3cbaa396e2984ce149c6e7925 (2026-05-21)
#
# Modifications from upstream:
#   - 2026-06-26: rebased import prefix mir_connector.src.* -> inorbit_mir_connector.src.*

"""Unit tests for InOrbitToMirTranslator."""

from __future__ import annotations

import math

import pytest
from inorbit_edge_executor.datatypes import (
    MissionDefinition,
    MissionStepPoseWaypoint,
    MissionStepRunAction,
    MissionStepSetData,
    MissionStepWait,
    Pose,
)
from inorbit_edge_executor.mission import Mission

from inorbit_mir_connector.src.mission.datatypes import (
    MirAction,
    MirWaypoint,
    MissionStepExecuteMirNativeMission,
)
from inorbit_mir_connector.src.mission.translator import (
    InOrbitToMirTranslator,
    _seconds_to_mir_duration,
)

ROBOT_ID = "test-robot-01"


def _pose_wp(x: float, y: float, theta: float = 0.0, label: str = "wp"):
    """Helper to build a MissionStepPoseWaypoint."""
    return MissionStepPoseWaypoint(
        waypoint=Pose(x=x, y=y, theta=theta),
        label=label,
    )


def _wait(secs: float, label: str = "wait"):
    return MissionStepWait(timeoutSecs=secs, label=label)


def _run_action(action_id: str, arguments: dict | None = None, label: str = "action"):
    kwargs: dict = {"actionId": action_id}
    if arguments is not None:
        kwargs["arguments"] = arguments
    return MissionStepRunAction(runAction=kwargs, label=label)


def _set_data(data: dict, label: str = "data"):
    return MissionStepSetData(data=data, label=label)


def _mission(steps, label: str = "test"):
    return Mission(
        id="mission-001",
        robot_id=ROBOT_ID,
        definition=MissionDefinition(label=label, steps=steps),
    )


class TestTranslateWaypointsOnly:
    def test_consecutive_waypoints_compiled(self):
        m = _mission([_pose_wp(1, 2), _pose_wp(3, 4)])
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 1
        step = result.definition.steps[0]
        assert isinstance(step, MissionStepExecuteMirNativeMission)
        assert len(step.actions) == 2
        assert all(isinstance(a, MirWaypoint) for a in step.actions)
        assert step.label == "Navigate 2 waypoints"


class TestTranslateWaitNested:
    def test_wait_nested_between_waypoints(self):
        m = _mission([_pose_wp(1, 2), _wait(5), _pose_wp(3, 4)])
        result = InOrbitToMirTranslator.translate(m)

        # All three should be in a single compiled mission
        assert len(result.definition.steps) == 1
        step = result.definition.steps[0]
        assert isinstance(step, MissionStepExecuteMirNativeMission)
        assert len(step.actions) == 3
        assert isinstance(step.actions[0], MirWaypoint)
        assert isinstance(step.actions[1], MirAction)
        assert step.actions[1].action_type == "wait"
        assert step.actions[1].parameters["time"] == "00:00:05.000000"
        assert isinstance(step.actions[2], MirWaypoint)
        assert step.label == "Execute 3 actions"


class TestTranslateRunActionNestable:
    def test_nestable_action_compiled(self):
        m = _mission([_pose_wp(1, 2), _run_action("docking", {"marker": "guid-1"})])
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 1
        step = result.definition.steps[0]
        assert isinstance(step, MissionStepExecuteMirNativeMission)
        assert len(step.actions) == 2
        assert isinstance(step.actions[1], MirAction)
        assert step.actions[1].action_type == "docking"
        assert step.actions[1].parameters == {"marker": "guid-1"}

    def test_set_footprint_nestable(self):
        m = _mission([_pose_wp(1, 2), _run_action("set_footprint", {"footprint": "guid-fp"})])
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 1
        step = result.definition.steps[0]
        assert isinstance(step, MissionStepExecuteMirNativeMission)
        assert len(step.actions) == 2
        assert isinstance(step.actions[1], MirAction)
        assert step.actions[1].action_type == "set_footprint"
        assert step.actions[1].parameters == {"footprint": "guid-fp"}


class TestTranslateRunActionNonNestable:
    def test_non_nestable_action_flushes(self):
        m = _mission([_pose_wp(1, 2), _run_action("unknown_action"), _pose_wp(3, 4)])
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 3
        assert isinstance(result.definition.steps[0], MissionStepExecuteMirNativeMission)
        assert isinstance(result.definition.steps[1], MissionStepRunAction)
        assert isinstance(result.definition.steps[2], MissionStepExecuteMirNativeMission)


class TestTranslateSetDataFlushes:
    def test_set_data_flushes(self):
        m = _mission([_pose_wp(1, 2), _set_data({"key": "val"}), _pose_wp(3, 4)])
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 3
        assert isinstance(result.definition.steps[0], MissionStepExecuteMirNativeMission)
        assert isinstance(result.definition.steps[1], MissionStepSetData)
        assert isinstance(result.definition.steps[2], MissionStepExecuteMirNativeMission)


class TestTranslateActionsOnly:
    def test_actions_only_no_waypoints(self):
        m = _mission([_run_action("docking"), _wait(10), _run_action("charging")])
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 1
        step = result.definition.steps[0]
        assert isinstance(step, MissionStepExecuteMirNativeMission)
        assert len(step.actions) == 3
        assert all(isinstance(a, MirAction) for a in step.actions)
        assert step.actions[0].action_type == "docking"
        assert step.actions[1].action_type == "wait"
        assert step.actions[2].action_type == "charging"


class TestDurationHelper:
    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (0, "00:00:00.000000"),
            (65.5, "00:01:05.500000"),
            (3661.123, "01:01:01.123000"),
            (0.001, "00:00:00.001000"),
        ],
    )
    def test_seconds_to_mir_duration(self, seconds, expected):
        assert _seconds_to_mir_duration(seconds) == expected


class TestTranslateEmpty:
    def test_empty_mission_raises(self):
        m = _mission([])
        with pytest.raises(ValueError, match="no steps"):
            InOrbitToMirTranslator.translate(m)


class TestWaypointOrientationConversion:
    def test_theta_converted_to_degrees(self):
        theta = math.pi / 4  # 45 degrees
        m = _mission([_pose_wp(1, 2, theta)])
        result = InOrbitToMirTranslator.translate(m)

        step = result.definition.steps[0]
        wp = step.actions[0]
        assert isinstance(wp, MirWaypoint)
        assert wp.orientation == pytest.approx(45.0)
