# SPDX-FileCopyrightText: 2026 Mappalink
#
# SPDX-License-Identifier: MIT
#
# Vendored from the Mappalink MiR connector:
#   https://github.com/mappalink/inorbit-mir-connector/blob/c516f7d9e8e6b8b3cbaa396e2984ce149c6e7925/mir_connector/src/mission/translator.py
# Upstream commit: c516f7d9e8e6b8b3cbaa396e2984ce149c6e7925 (2026-05-21)
#
# Modifications from upstream:
#   - 2026-06-26: normalize waypoint orientation into MiR's [-180, 180] range. Upstream
#     emitted raw math.degrees(theta); MiR's move_to_position rejects orientation outside
#     [-180, 180] with HTTP 400 (input_number_out_of_range) and InOrbit theta is an
#     unbounded radian angle (e.g. 6.35 rad -> 364deg).
#   - 2026-06-27: renamed local n -> n_pending_actions in flush_actions
#   - 2026-06-27: waypoint_count via sum(map(...)) instead of a generator expression
#   - 2026-06-27: preserve InOrbit per-task tracking. A grouped (nestable) step
#     carrying complete_task now flushes the current native group and stamps complete_task onto
#     the emitted MissionStepExecuteMirNativeMission, so the task is reported (it lands in
#     Mission.tasks_list and the tree builder's decorator emits TaskStarted/TaskCompletedNode).
#     Non-nestable steps already pass through verbatim and keep their complete_task. Grouping is
#     unchanged for missions whose steps carry no complete_task.
#   - 2026-06-28: enforce native-mission timeout. The translator now stamps timeout_secs onto the
#     emitted native step as the SUM of the grouped steps' timeout_secs, but ONLY when every
#     grouped step is bounded; if any grouped step has no timeout the native step stays unbounded
#     (preserving prior behavior). WaitForMirMissionCompletionNode then bounds its completion poll
#     instead of polling indefinitely.

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
        # complete_task to stamp onto the next flushed native group, so InOrbit per-task
        # tracking survives the grouping (set when a grouped step carries complete_task).
        pending_complete_task: Union[str, None] = None
        # timeout_secs of each grouped step (None if a step is unbounded), parallel to
        # pending_actions, so the flushed native step can carry an aggregate timeout.
        pending_timeouts: list[Union[float, None]] = []

        def flush_actions():
            """Emit the buffered actions as one native MiR mission step.

            Builds a ``MissionStepExecuteMirNativeMission`` from the pending
            waypoints and actions, derives its label from their count and kind,
            stamps ``completeTask`` when one is pending, appends it to
            ``translated_steps``, and clears the buffers. A no-op (beyond
            resetting the pending task) when nothing is buffered.
            """
            nonlocal pending_complete_task
            if not pending_actions:
                pending_complete_task = None
                pending_timeouts.clear()
                return
            n_pending_actions = len(pending_actions)
            waypoint_count = sum(map(lambda a: isinstance(a, MirWaypoint), pending_actions))
            if waypoint_count == n_pending_actions:
                # All waypoints
                label = (
                    (pending_labels[0] if pending_labels[0] else "Navigate to waypoint")
                    if n_pending_actions == 1
                    else f"Navigate {n_pending_actions} waypoints"
                )
            elif n_pending_actions == 1:
                label = pending_labels[0] if pending_labels[0] else pending_actions[0].label or ""
            else:
                label = f"Execute {n_pending_actions} actions"
            native_kwargs: dict = {
                "label": label,
                "actions": list(pending_actions),
                "robot_id": mission.robot_id,
            }
            # Only set completeTask when present: the field is typed ``str`` (default None),
            # so passing None explicitly fails validation.
            if pending_complete_task is not None:
                native_kwargs["completeTask"] = pending_complete_task
            # Bound the completion poll only when every grouped step is bounded; the native
            # mission's timeout is the sum of the grouped steps' timeouts. If any step is
            # unbounded the native step stays unbounded (no premature abort). The field is
            # typed float (default None), so only set it when computed.
            if pending_timeouts and all(t is not None for t in pending_timeouts):
                native_kwargs["timeoutSecs"] = sum(pending_timeouts)
            translated_steps.append(MissionStepExecuteMirNativeMission(**native_kwargs))
            pending_actions.clear()
            pending_labels.clear()
            pending_complete_task = None
            pending_timeouts.clear()

        for step in mission.definition.steps:
            if isinstance(step, MissionStepPoseWaypoint):
                wp = step.waypoint
                x, y, theta = wp.x, wp.y, wp.theta

                # MiR expects orientation in degrees, wrapped to [-180, 180]:
                # move_to_position rejects anything outside that range with HTTP 400
                # (input_number_out_of_range). InOrbit theta is an unbounded radian
                # angle, so normalize after converting.
                orientation_deg = (math.degrees(theta) + 180) % 360 - 180

                pending_actions.append(
                    MirWaypoint(label=step.label, x=x, y=y, orientation=orientation_deg)
                )
                pending_labels.append(step.label or "")
                pending_timeouts.append(step.timeout_secs)
                if step.complete_task is not None:
                    pending_complete_task = step.complete_task
                    flush_actions()
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
                pending_timeouts.append(step.timeout_secs)
                if step.complete_task is not None:
                    pending_complete_task = step.complete_task
                    flush_actions()
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
                pending_timeouts.append(step.timeout_secs)
                if step.complete_task is not None:
                    pending_complete_task = step.complete_task
                    flush_actions()
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
