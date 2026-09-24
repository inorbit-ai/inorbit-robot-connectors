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
#   - 2026-07-23 Tomás Badenes: add GuidedMoveWaypoint + MirGuidedMove (InOrbit routes ->
#     MiR guided_move); widen actions and action_task_ids (a nested list entry carries a
#     guided move's per-waypoint task ids).

"""MiR-specific mission datatypes for mission translation.

Defines custom step types and mission classes used when consecutive
waypoint steps are compiled into a single native MiR mission.
"""

from __future__ import annotations

from typing import Any, List, Optional, Union

from pydantic import BaseModel, Field, model_validator

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


class GuidedMoveWaypoint(BaseModel):
    """One intermediate guided-move waypoint (MiR waypoints JSON entry).

    Radiuses are meters; None means the connector fills its line-following
    defaults at action build (node 0.3, edge 0.0).
    """

    x: float
    y: float
    node_radius: Optional[float] = None
    edge_radius: Optional[float] = None


class MirGuidedMove(MissionStep):
    """A collapsed run of route steps, executed as one MiR guided_move action.

    Goal is the run's last waypoint; ``waypoints`` are the intermediates in
    order. Edge radiuses come from the InOrbit route corridor (width/2,
    clamped); goal_node_radius is an arrival tolerance, not corridor-derived
    (None means the connector default 0.5 at action build).
    """

    goal_x: float
    goal_y: float
    goal_orientation: float = Field(description="Goal orientation in degrees [-180, 180]")
    waypoints: List[GuidedMoveWaypoint] = Field(default_factory=list)
    goal_node_radius: Optional[float] = None
    goal_edge_radius: Optional[float] = None


class MissionStepExecuteMirNativeMission(MissionStep):
    """Custom step that executes a compiled native MiR mission.

    Produced by the translator when consecutive waypoint/action steps are
    grouped. The behavior tree node creates a MiR mission definition, adds
    one action per entry, and queues it.
    """

    actions: List[Union[MirWaypoint, MirAction, MirGuidedMove]] = Field(
        description="Ordered actions for native MiR mission"
    )
    robot_id: str = Field(description="InOrbit robot ID")
    # Parallel to `actions`: a plain action pairs with one task id (or None); a
    # MirGuidedMove covers N route steps in one MiR action, so its entry is a nested list
    # parallel to [*waypoints, goal], e.g. [["t1", "t2", "t3"], "t4"].
    action_task_ids: List[Union[str, None, List[Union[str, None]]]] = Field(
        default_factory=list,
        description=(
            "InOrbit task ids parallel to actions (None = action has no task). A nested "
            "list entry belongs to a guided move action: task ids parallel to its "
            "[*waypoints, goal] route steps."
        ),
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
