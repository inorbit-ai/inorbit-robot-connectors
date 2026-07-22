# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for InOrbit routes -> MiR guided_move translation and datatypes.

Spec: specs/routes-guided-move.md
"""

from __future__ import annotations

from inorbit_edge_executor.datatypes import RouteSegmentCorridor
from inorbit_mir_connector.src.mission.datatypes import (
    GuidedMoveWaypoint,
    MirGuidedMove,
    MissionStepExecuteMirNativeMission,
)
from inorbit_mir_connector.src.mission.translator import (
    GUIDED_MOVE_MAX_RADIUS,
    _corridor_to_radius,
)


class TestGuidedMoveDatatypes:
    def test_native_step_accepts_guided_move_and_nested_task_ids(self):
        gm = MirGuidedMove(
            label="route",
            goal_x=5.0,
            goal_y=6.0,
            goal_orientation=90.0,
            waypoints=[GuidedMoveWaypoint(x=1.0, y=2.0, node_radius=0.6, edge_radius=0.6)],
            goal_node_radius=0.5,
            goal_edge_radius=0.5,
        )
        step = MissionStepExecuteMirNativeMission(
            label="native",
            actions=[gm],
            robot_id="mir-1",
            action_task_ids=[["t-wp", "t-goal"]],
        )
        assert step.actions[0].waypoints[0].node_radius == 0.6
        assert step.action_task_ids == [["t-wp", "t-goal"]]

    def test_native_step_round_trips_through_serialization(self):
        gm = MirGuidedMove(
            label="route",
            goal_x=5.0,
            goal_y=6.0,
            goal_orientation=90.0,
            waypoints=[GuidedMoveWaypoint(x=1.0, y=2.0)],
        )
        step = MissionStepExecuteMirNativeMission(
            label="native",
            actions=[gm],
            robot_id="mir-1",
            action_task_ids=[[None, "t-goal"]],
        )
        dumped = step.model_dump(mode="json", exclude_none=True, by_alias=True)
        restored = MissionStepExecuteMirNativeMission.model_validate(dumped)
        assert isinstance(restored.actions[0], MirGuidedMove)
        assert restored.actions[0].goal_x == 5.0
        assert restored.actions[0].waypoints[0].edge_radius is None
        assert restored.action_task_ids == [[None, "t-goal"]]


class TestCorridorToRadius:
    def test_symmetric_width_halved(self):
        assert _corridor_to_radius(RouteSegmentCorridor(width=1.2)) == 0.6

    def test_asymmetric_uses_min_side(self):
        c = RouteSegmentCorridor(leftWidth=0.4, rightWidth=0.9)
        assert _corridor_to_radius(c) == 0.4

    def test_clamped_to_mir_max(self):
        assert _corridor_to_radius(RouteSegmentCorridor(width=14.0)) == GUIDED_MOVE_MAX_RADIUS

    def test_none_corridor_is_none(self):
        assert _corridor_to_radius(None) is None
