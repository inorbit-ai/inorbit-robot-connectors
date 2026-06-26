# SPDX-FileCopyrightText: 2026 Mappalink
#
# SPDX-License-Identifier: MIT
#
# Vendored from the Mappalink MiR connector:
#   https://github.com/mappalink/inorbit-mir-connector/blob/c516f7d9e8e6b8b3cbaa396e2984ce149c6e7925/mir_connector/src/mission/translator.py
# Upstream commit: c516f7d9e8e6b8b3cbaa396e2984ce149c6e7925 (2026-05-21)
#
# Modifications from upstream:
#   - none (verbatim; intra-package imports are relative, e.g. ``from .datatypes import ...``)

"""Mission translator that compiles consecutive InOrbit waypoint and
nestable action steps into single native MiR missions.

Step grouping:
    Input:  [wp_A, wp_B, wait_5s, wp_C, wp_D]
    Output: [MirNativeMission([A, B, wait, C, D])]

Nestable actions (docking, charging, wait, etc.) are compiled into the
same native mission alongside waypoints. Non-nestable steps flush the
current group and pass through to cloud-side execution.
"""

from __future__ import annotations

import logging
import math
from typing import Union

from inorbit_edge_executor.datatypes import (
    MissionStepPoseWaypoint,
    MissionStepRunAction,
    MissionStepWait,
)
from inorbit_edge_executor.mission import Mission

from .datatypes import (
    MirAction,
    MirInOrbitMission,
    MirStepsList,
    MirWaypoint,
    MissionDefinitionMir,
    MissionStepExecuteMirNativeMission,
)

logger = logging.getLogger(__name__)

# MiR action types that can be nested into a compiled native mission.
NESTABLE_MIR_ACTIONS: set[str] = {
    "docking",
    "charging",
    "wait",
    "relative_move",
    "adjust_localization",
    "set_plc_register",
    "wait_for_plc_register",
    "sound",
    "sound_stop",
    "light",
    "pickup_cart",
    "place_cart",
    "set_footprint",
}


def _seconds_to_mir_duration(seconds: float) -> str:
    """Convert seconds to MiR duration string ``HH:MM:SS.ffffff``."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:09.6f}"


class InOrbitToMirTranslator:
    """Translates InOrbit missions by compiling consecutive waypoint and
    nestable action steps into native MiR missions.

    Non-nestable steps flush the current group and pass through unchanged.
    """

    @staticmethod
    def translate(
        mission: Mission,
    ) -> MirInOrbitMission:
        """Translate an InOrbit mission to MiR format.

        Consecutive waypoint and nestable action steps are grouped into a
        single ``MissionStepExecuteMirNativeMission``. Non-nestable steps
        flush the current group and pass through.
        """
        if not mission.definition.steps:
            raise ValueError("Mission has no steps to translate")

        translated_steps: MirStepsList = []
        pending_actions: list[Union[MirWaypoint, MirAction]] = []
        pending_labels: list[str] = []

        def flush_actions():
            if not pending_actions:
                return
            n = len(pending_actions)
            waypoint_count = sum(1 for a in pending_actions if isinstance(a, MirWaypoint))
            if waypoint_count == n:
                # All waypoints
                label = (
                    (pending_labels[0] if pending_labels[0] else "Navigate to waypoint")
                    if n == 1
                    else f"Navigate {n} waypoints"
                )
            elif n == 1:
                label = pending_labels[0] if pending_labels[0] else pending_actions[0].label or ""
            else:
                label = f"Execute {n} actions"
            translated_steps.append(
                MissionStepExecuteMirNativeMission(
                    label=label,
                    actions=list(pending_actions),
                    robot_id=mission.robot_id,
                )
            )
            pending_actions.clear()
            pending_labels.clear()

        for step in mission.definition.steps:
            if isinstance(step, MissionStepPoseWaypoint):
                wp = step.waypoint
                x, y, theta = wp.x, wp.y, wp.theta

                # MiR expects orientation in degrees
                orientation_deg = math.degrees(theta)

                pending_actions.append(
                    MirWaypoint(label=step.label, x=x, y=y, orientation=orientation_deg)
                )
                pending_labels.append(step.label or "")
                continue

            if isinstance(step, MissionStepWait):
                pending_actions.append(
                    MirAction(
                        label=step.label,
                        action_type="wait",
                        parameters={"time": _seconds_to_mir_duration(step.timeout_secs or 0)},
                    )
                )
                pending_labels.append(step.label or "")
                continue

            if isinstance(step, MissionStepRunAction) and step.action_id in NESTABLE_MIR_ACTIONS:
                pending_actions.append(
                    MirAction(
                        label=step.label,
                        action_type=step.action_id,
                        parameters=step.arguments or {},
                    )
                )
                pending_labels.append(step.label or "")
                continue

            # Non-nestable step — flush pending actions first
            flush_actions()
            translated_steps.append(step)

        flush_actions()

        translated_definition = MissionDefinitionMir(
            label=mission.definition.label,
            steps=translated_steps,
        )

        translated_mission = MirInOrbitMission(
            id=mission.id,
            robot_id=mission.robot_id,
            definition=translated_definition,
            arguments=mission.arguments,
        )

        logger.debug(
            "Translated mission %s: %d original steps -> %d translated steps",
            mission.id,
            len(mission.definition.steps),
            len(translated_steps),
        )

        return translated_mission
