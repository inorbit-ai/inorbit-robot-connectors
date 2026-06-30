# SPDX-FileCopyrightText: 2026 Mappalink
#
# SPDX-License-Identifier: MIT
#
# Vendored from the Mappalink MiR connector:
#   https://github.com/mappalink/inorbit-mir-connector/blob/c516f7d9e8e6b8b3cbaa396e2984ce149c6e7925/mir_connector/src/mission/datatypes.py
# Upstream commit: c516f7d9e8e6b8b3cbaa396e2984ce149c6e7925 (2026-05-21)
#
# Modifications from upstream:
#   - 2026-06-30 Tomás Badenes: add action_task_ids to MissionStepExecuteMirNativeMission.
#     Ordered InOrbit task ids parallel to actions (None = action has no task), so a grouped
#     native mission reports each task as its MiR action runs instead of needing one native
#     step per task. No alias (it is built internally, not parsed from InOrbit JSON), so it
#     round-trips under every dump convention. Default empty for back-compat.

"""MiR-specific mission datatypes for mission translation.

Defines custom step types and mission classes used when consecutive
waypoint steps are compiled into a single native MiR mission.
"""

from __future__ import annotations

from typing import Any, List, Union

from pydantic import Field, model_validator

from inorbit_edge_executor.datatypes import (
    MissionDefinition,
    MissionStep,
    MissionStepPoseWaypoint,
    MissionStepRunAction,
    MissionStepSetData,
    MissionStepWait,
    MissionStepWaitUntil,
)
from inorbit_edge_executor.mission import Mission


class MirWaypoint(MissionStep):
    """A single waypoint in MiR-native coordinates.

    Carries x, y (meters) and orientation (degrees) ready to be sent
    as a ``move_to_position`` action.
    """

    x: float = Field(description="X coordinate in MiR native frame (meters)")
    y: float = Field(description="Y coordinate in MiR native frame (meters)")
    orientation: float = Field(description="Orientation in degrees (MiR convention)")


class MirAction(MissionStep):
    """Generic MiR action with pass-through parameters."""

    action_type: str = Field(description="MiR action type (e.g. 'docking', 'charging', 'wait')")
    parameters: dict[str, Any] = Field(default_factory=dict)


class MissionStepExecuteMirNativeMission(MissionStep):
    """Custom step that executes a compiled native MiR mission.

    Produced by the translator when consecutive waypoint/action steps are
    grouped. The behavior tree node creates a MiR mission definition, adds
    one action per entry, and queues it.
    """

    actions: List[Union[MirWaypoint, MirAction]] = Field(
        description="Ordered actions for native MiR mission"
    )
    robot_id: str = Field(description="InOrbit robot ID")
    action_task_ids: List[Union[str, None]] = Field(
        default_factory=list,
        description="InOrbit task ids parallel to actions (None = action has no task)",
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_waypoints(cls, data):
        """Backward-compat: accept serialized missions that still use 'waypoints'."""
        if isinstance(data, dict) and "waypoints" in data and "actions" not in data:
            data["actions"] = data.pop("waypoints")
        return data

    def accept(self, visitor):
        if hasattr(visitor, "visit_execute_mir_native_mission"):
            return visitor.visit_execute_mir_native_mission(self)
        if hasattr(visitor, "collect_step"):
            return visitor.collect_step(self)
        return None


# Type alias for MiR-specific steps list
MirStepsList = List[
    Union[
        MissionStepSetData,
        MissionStepPoseWaypoint,
        MissionStepRunAction,
        MissionStepWait,
        MissionStepWaitUntil,
        MissionStepExecuteMirNativeMission,
    ]
]


class MissionDefinitionMir(MissionDefinition):
    """Mission definition that supports MiR-specific step types."""

    steps: MirStepsList  # type: ignore[assignment]


class MirInOrbitMission(Mission):
    """Mission subclass using MiR-specific definition after translation."""

    definition: MissionDefinitionMir  # type: ignore[assignment]
