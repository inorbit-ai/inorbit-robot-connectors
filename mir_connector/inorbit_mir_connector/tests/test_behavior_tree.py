# SPDX-FileCopyrightText: 2026 Mappalink
#
# SPDX-License-Identifier: MIT
#
# Vendored from the Mappalink MiR connector:
#   https://github.com/mappalink/inorbit-mir-connector/blob/c516f7d9e8e6b8b3cbaa396e2984ce149c6e7925/tests/test_behavior_tree.py
# Upstream commit: c516f7d9e8e6b8b3cbaa396e2984ce149c6e7925 (2026-05-21)
#
# Modifications from upstream:
#   - 2026-06-26: rebased import prefix mir_connector.src.* -> inorbit_mir_connector.src.*

"""Unit tests for MiR behavior tree node serialization (dump/from_object)."""

from __future__ import annotations

import pytest

from inorbit_mir_connector.src.mission.datatypes import (
    MirAction,
    MirWaypoint,
    MissionStepExecuteMirNativeMission,
)


class TestMissionStepExecuteMirNativeMissionSerialization:
    """Verify round-trip serialization of MissionStepExecuteMirNativeMission.

    This is critical for pause/resume: the step is serialized to SQLite
    on pause and deserialized on resume via model_validate().
    """

    def _make_step_with_waypoints(self):
        return MissionStepExecuteMirNativeMission(
            label="Navigate 2 waypoints",
            actions=[
                MirWaypoint(label="wp1", x=1.0, y=2.0, orientation=90.0),
                MirWaypoint(label="wp2", x=3.0, y=4.0, orientation=180.0),
            ],
            robot_id="mir200-1",
        )

    def _make_step_with_actions(self):
        return MissionStepExecuteMirNativeMission(
            label="Execute 2 actions",
            actions=[
                MirAction(label="Wait", action_type="wait", parameters={"time": "00:01:00.000000"}),
                MirWaypoint(label="wp1", x=1.0, y=2.0, orientation=90.0),
            ],
            robot_id="mir200-1",
        )

    def _make_step_wait_only(self):
        return MissionStepExecuteMirNativeMission(
            label="Wait only",
            actions=[
                MirAction(
                    label="Wait 60 seconds",
                    action_type="wait",
                    parameters={"time": "00:01:00.000000"},
                ),
            ],
            robot_id="mir200-1",
        )

    def test_round_trip_waypoints(self):
        step = self._make_step_with_waypoints()
        serialized = step.model_dump(mode="json", exclude_none=True)
        restored = MissionStepExecuteMirNativeMission.model_validate(serialized)
        assert len(restored.actions) == 2
        assert isinstance(restored.actions[0], MirWaypoint)
        assert restored.actions[0].x == 1.0
        assert restored.actions[1].orientation == 180.0

    def test_round_trip_mixed_actions(self):
        step = self._make_step_with_actions()
        serialized = step.model_dump(mode="json", exclude_none=True)
        restored = MissionStepExecuteMirNativeMission.model_validate(serialized)
        assert len(restored.actions) == 2
        assert isinstance(restored.actions[0], MirAction)
        assert restored.actions[0].action_type == "wait"
        assert isinstance(restored.actions[1], MirWaypoint)

    def test_round_trip_wait_only(self):
        """Reproduces the v0.1.19 bug: wait-only step failed to deserialize."""
        step = self._make_step_wait_only()
        serialized = step.model_dump(mode="json", exclude_none=True)
        restored = MissionStepExecuteMirNativeMission.model_validate(serialized)
        assert len(restored.actions) == 1
        assert isinstance(restored.actions[0], MirAction)
        assert restored.actions[0].action_type == "wait"

    def test_round_trip_fails_without_exclude_none(self):
        """Confirms the bug: model_dump without exclude_none produces invalid data."""
        step = self._make_step_wait_only()
        serialized = step.model_dump(mode="json")  # no exclude_none
        with pytest.raises(Exception):
            MissionStepExecuteMirNativeMission.model_validate(serialized)
