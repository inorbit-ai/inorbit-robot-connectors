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
#   - 2026-06-26: added TestOrientationNormalization (orientation wrapped to MiR's
#     [-180, 180] range; MiR rejects move_to_position outside it with HTTP 400)
#   - 2026-06-29: native-action routing moved from the NESTABLE_MIR_ACTIONS name-match to the
#     reserved `mir_actionType` argument key (spec native-mission-action-steps.md, phase 1).
#     Migrated the 3 name-match tests to drive nesting via arguments.mir_actionType; added
#     None-gate / bare-action_id passthrough, blank-type error, deny-list, typo/zero-param
#     warnings, docking auto-resolve handoff, load_mission nesting, and sole/last-step tests.

"""Unit tests for InOrbitToMirTranslator."""

from __future__ import annotations

import logging
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
    DENIED_NATIVE_ACTIONS,
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


class TestOrientationNormalization:
    """MiR's move_to_position rejects orientation outside [-180, 180] with a 400
    (``input_number_out_of_range``). InOrbit waypoint theta is an unbounded angle
    in radians, so the degrees conversion must wrap into MiR's range."""

    @pytest.mark.parametrize(
        "theta_rad, expected_deg",
        [
            (math.radians(90), 90.0),  # in range, unchanged
            (math.radians(-90), -90.0),  # in range, unchanged
            (math.radians(185), -175.0),  # just over +180
            (math.radians(-185), 175.0),  # just under -180
            (math.radians(364.1), 4.1),  # full turn + a bit
            (6.354400934754617, math.degrees(6.354400934754617) - 360),  # real mission theta
        ],
    )
    def test_orientation_wrapped_into_mir_range(self, theta_rad, expected_deg):
        result = InOrbitToMirTranslator.translate(_mission([_pose_wp(1, 2, theta=theta_rad)]))
        wp = result.definition.steps[0].actions[0]
        assert isinstance(wp, MirWaypoint)
        assert -180 <= wp.orientation <= 180
        assert wp.orientation == pytest.approx(expected_deg, abs=1e-6)


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
        # action_id is intentionally NOT a MiR action name: routing is now purely by the
        # reserved mir_actionType key, and the reserved key is excluded from parameters.
        m = _mission(
            [
                _pose_wp(1, 2),
                _run_action(
                    "inorbit-action-uuid", {"mir_actionType": "docking", "marker": "guid-1"}
                ),
            ]
        )
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 1
        step = result.definition.steps[0]
        assert isinstance(step, MissionStepExecuteMirNativeMission)
        assert len(step.actions) == 2
        assert isinstance(step.actions[1], MirAction)
        assert step.actions[1].action_type == "docking"
        assert step.actions[1].parameters == {"marker": "guid-1"}

    def test_set_footprint_nestable(self):
        m = _mission(
            [
                _pose_wp(1, 2),
                _run_action("x", {"mir_actionType": "set_footprint", "footprint": "guid-fp"}),
            ]
        )
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
        m = _mission(
            [
                _run_action("a", {"mir_actionType": "docking", "marker": "g"}),
                _wait(10),
                _run_action("b", {"mir_actionType": "charging", "minimum_percentage": 80}),
            ]
        )
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


class TestMirActionTypeRouting:
    """Routing is by the reserved ``mir_actionType`` argument key, not the old
    NESTABLE_MIR_ACTIONS name-match (spec native-mission-action-steps.md sections 3-4)."""

    def test_none_arguments_passes_through(self):
        # argument-less runAction: arguments defaults to None; the gate must be None-safe.
        m = _mission([_pose_wp(1, 2), _run_action("docking"), _pose_wp(3, 4)])
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 3
        assert isinstance(result.definition.steps[0], MissionStepExecuteMirNativeMission)
        assert isinstance(result.definition.steps[1], MissionStepRunAction)
        assert isinstance(result.definition.steps[2], MissionStepExecuteMirNativeMission)

    def test_bare_action_id_no_marker_passes_through(self):
        # A former-allowlist name with args but no mir_actionType no longer nests
        # (the allowlist is deleted): it routes to the cloud action path.
        m = _mission([_pose_wp(1, 2), _run_action("docking", {"marker": "g"}), _pose_wp(3, 4)])
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 3
        assert isinstance(result.definition.steps[1], MissionStepRunAction)

    @pytest.mark.parametrize("bad_type", ["", "   ", 123, None, True])
    def test_present_but_blank_type_raises(self, bad_type):
        m = _mission([_run_action("x", {"mir_actionType": bad_type})])
        with pytest.raises(ValueError, match="mir_actionType"):
            InOrbitToMirTranslator.translate(m)

    def test_type_is_stripped(self):
        m = _mission([_run_action("x", {"mir_actionType": "  sound_stop  "})])
        result = InOrbitToMirTranslator.translate(m)
        assert result.definition.steps[0].actions[0].action_type == "sound_stop"

    def test_reserved_key_excluded_from_parameters(self):
        m = _mission([_run_action("x", {"mir_actionType": "set_io", "module": "guid", "port": 1})])
        result = InOrbitToMirTranslator.translate(m)
        action = result.definition.steps[0].actions[0]
        assert action.action_type == "set_io"
        assert action.parameters == {"module": "guid", "port": 1}
        assert "mir_actionType" not in action.parameters


class TestMirActionTypeDenyList:
    """Scope-bearing / control-flow / loop-only types are rejected at translate time,
    before any robot-side mission exists (spec section 3.1). The translator never calls
    create_mission, so raising during translate inherently leaves no orphan mission."""

    DENIED = [
        "if",
        "while",
        "loop",
        "try_catch",
        "prompt_user",
        "reduce_protective_fields",
        "set_reset_io",
        "set_reset_plc",
        "break",
        "continue",
    ]

    def test_deny_list_membership_is_exactly_the_ten_types(self):
        # Guards the template-built DENIED_NATIVE_ACTIONS against silently gaining/losing a type.
        assert set(DENIED_NATIVE_ACTIONS) == set(self.DENIED)

    @pytest.mark.parametrize("action_type", DENIED)
    def test_denied_type_raises(self, action_type):
        m = _mission([_run_action("x", {"mir_actionType": action_type})])
        with pytest.raises(ValueError, match=action_type):
            InOrbitToMirTranslator.translate(m)

    def test_return_is_allowed(self):
        # `return` is a valid top-level abort, not denied (spec section 3.1 note).
        m = _mission([_run_action("x", {"mir_actionType": "return"})])
        result = InOrbitToMirTranslator.translate(m)
        assert result.definition.steps[0].actions[0].action_type == "return"


class TestMirActionTypeWarnings:
    def test_mir_prefix_typo_warns_and_passes_through(self, caplog):
        # A fat-fingered key (mir_actionTYpe) has no exact mir_actionType: route to the
        # cloud path but warn so it fails loudly instead of silently vanishing.
        m = _mission([_run_action("x", {"mir_actionTYpe": "docking"})])
        with caplog.at_level(logging.WARNING):
            result = InOrbitToMirTranslator.translate(m)
        assert isinstance(result.definition.steps[0], MissionStepRunAction)
        assert "mir_actionType" in caplog.text

    def test_zero_parameters_warns(self, caplog):
        m = _mission([_run_action("x", {"mir_actionType": "sound_stop"})])
        with caplog.at_level(logging.WARNING):
            result = InOrbitToMirTranslator.translate(m)
        action = result.definition.steps[0].actions[0]
        assert action.action_type == "sound_stop"
        assert action.parameters == {}
        assert "sound_stop" in caplog.text


class TestMirActionTypeDocking:
    """docking nests via mir_actionType with the marker preserved, so the downstream
    resolve_marker_type (tested in test_marker_type.py / test_mir_native_mission_node.py)
    fills in marker_type. The reserved key must be stripped (spec section 7)."""

    def test_docking_via_mir_action_type_preserves_marker(self):
        m = _mission([_run_action("x", {"mir_actionType": "docking", "marker": "marker-guid"})])
        result = InOrbitToMirTranslator.translate(m)
        action = result.definition.steps[0].actions[0]
        assert isinstance(action, MirAction)
        assert action.action_type == "docking"
        assert action.parameters == {"marker": "marker-guid"}


class TestMirActionTypeLoadMission:
    """A pre-existing MiR mission runs in-flow as a native load_mission action; it needs
    no special-casing, just the generic marker path (spec section 13)."""

    def test_load_mission_nests(self):
        m = _mission(
            [_run_action("x", {"mir_actionType": "load_mission", "mission_id": "child-guid"})]
        )
        result = InOrbitToMirTranslator.translate(m)
        assert len(result.definition.steps) == 1
        action = result.definition.steps[0].actions[0]
        assert isinstance(action, MirAction)
        assert action.action_type == "load_mission"
        assert action.parameters == {"mission_id": "child-guid"}


class TestMirActionTypePositioning:
    def test_native_action_as_sole_step(self):
        m = _mission([_run_action("x", {"mir_actionType": "adjust_localization"})])
        result = InOrbitToMirTranslator.translate(m)
        assert len(result.definition.steps) == 1
        step = result.definition.steps[0]
        assert isinstance(step, MissionStepExecuteMirNativeMission)
        assert len(step.actions) == 1
        assert step.actions[0].action_type == "adjust_localization"

    def test_native_action_as_last_step_after_waypoint(self):
        # exercises the trailing flush_actions() after the loop
        m = _mission([_pose_wp(1, 2), _run_action("x", {"mir_actionType": "adjust_localization"})])
        result = InOrbitToMirTranslator.translate(m)
        assert len(result.definition.steps) == 1
        step = result.definition.steps[0]
        assert isinstance(step, MissionStepExecuteMirNativeMission)
        assert len(step.actions) == 2
        assert isinstance(step.actions[0], MirWaypoint)
        assert step.actions[1].action_type == "adjust_localization"
