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
#   - 2026-06-29: route runAction -> native MiR action by the reserved `mir_actionType`
#     argument key instead of the NESTABLE_MIR_ACTIONS name-match (deleted). vda5050-parity:
#     present-but-blank type is a hard error; a missing exact key routes to the cloud action
#     path (warning when a stray mir_-prefixed key is present); the reserved key is excluded
#     from the action parameters (each surviving key is a MiR parameter id). Scope-bearing /
#     control-flow / loop-only types are rejected before any robot-side mission exists via
#     DENIED_NATIVE_ACTIONS. Zero surviving params warns. Spec: native-mission-action-steps.md.
#   - 2026-06-30: group consecutive nestable steps even when each carries complete_task (no
#     longer flush the native group per task). The per-action task ids ride on the native
#     step (actionTaskIds, parallel to actions) and the original tasks_list is preserved, so
#     InOrbit per-task tracking still reports each task as its MiR action runs while the
#     whole group compiles into a single native mission.

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

# Reserved argument key that marks a runAction for native MiR translation (vda5050 parity:
# the vda5050 connector uses a reserved-argument-key marker rather than a name allowlist).
RESERVED_MIR_ARG_TYPE_KEY = "mir_actionType"
RESERVED_MIR_ARG_KEYS = frozenset({RESERVED_MIR_ARG_TYPE_KEY})
MIR_RESERVED_PREFIX = "mir_"

# MiR action types that cannot be expressed as a single flat add_action_to_mission call,
# rejected at translate time (before any create_mission, so no orphan mission is left on the
# robot). Two reasons, grounded in live GET /actions/{type} schemas (MiR100, SW v2.0.0):
#   - scope-bearing: the schema carries a Scope parameter (the container holding nested child
#     actions); the connector has no scope_reference machinery, so the flat call would silently
#     drop the body. For two of these the plain leaf action posts the useful part.
#   - loop-only: break/continue carry no params but are only legal inside a Loop scope, so a
#     flat top-level step is an orphaned firmware error.
# (`return` is NOT denied: it is a valid top-level abort.)
_SCOPE_BEARING_DENIED = (
    "if",
    "while",
    "loop",
    "try_catch",
    "prompt_user",
    "reduce_protective_fields",
    "set_reset_io",
    "set_reset_plc",
)
_LOOP_ONLY_DENIED = ("break", "continue")
# Scope-wrapper types whose plain leaf action expresses the postable part without the body.
_SCOPE_DENIED_ALTERNATIVE = {"set_reset_io": "set_io", "set_reset_plc": "set_plc_register"}
_SCOPE_DENIED_REASON = (
    "carries a Scope (child-action) body the connector cannot build as a flat native step; "
    "the body would be silently dropped"
)
_LOOP_ONLY_DENIED_REASON = (
    "is only valid inside a Loop scope; as a flat top-level native step it is an orphaned "
    "firmware error"
)


def _scope_denied_message(action_type: str) -> str:
    msg = f"'{action_type}' {_SCOPE_DENIED_REASON}"
    alt = _SCOPE_DENIED_ALTERNATIVE.get(action_type)
    return f"{msg}; use '{alt}' instead" if alt else msg


# action_type -> operator-facing reason it cannot be a native step.
DENIED_NATIVE_ACTIONS: dict[str, str] = {
    **{a: _scope_denied_message(a) for a in _SCOPE_BEARING_DENIED},
    **{a: f"'{a}' {_LOOP_ONLY_DENIED_REASON}" for a in _LOOP_ONLY_DENIED},
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
        # timeout_secs of each grouped step (None if a step is unbounded), parallel to
        # pending_actions, so the flushed native step can carry an aggregate timeout.
        pending_timeouts: list[Union[float, None]] = []
        # complete_task of each grouped step (None if untracked), parallel to
        # pending_actions, so the native step can report each task as its MiR action runs.
        pending_task_ids: list[Union[str, None]] = []

        def flush_actions():
            """Emit the buffered actions as one native MiR mission step.

            Builds a ``MissionStepExecuteMirNativeMission`` from the pending
            waypoints and actions, derives its label from their count and kind,
            carries the per-action task ids (so each task is reported as its MiR
            action runs), appends it to ``translated_steps``, and clears the
            buffers. A no-op when nothing is buffered.
            """
            if not pending_actions:
                pending_timeouts.clear()
                pending_task_ids.clear()
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
                # Per-action task ids (None where a step has no task), parallel to actions.
                # The completion node marks each as its MiR action runs; the native step's
                # own completeTask stays None so the SDK decorator adds no single-task wrap.
                "action_task_ids": list(pending_task_ids),
            }
            # Bound the completion poll only when every grouped step is bounded; the native
            # mission's timeout is the sum of the grouped steps' timeouts. If any step is
            # unbounded the native step stays unbounded (no premature abort). The field is
            # typed float (default None), so only set it when computed.
            if pending_timeouts and all(t is not None for t in pending_timeouts):
                native_kwargs["timeoutSecs"] = sum(pending_timeouts)
            translated_steps.append(MissionStepExecuteMirNativeMission(**native_kwargs))
            pending_actions.clear()
            pending_labels.clear()
            pending_timeouts.clear()
            pending_task_ids.clear()

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
                pending_task_ids.append(step.complete_task)
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
                pending_task_ids.append(step.complete_task)
                continue

            if isinstance(step, MissionStepRunAction):
                # None-safe: MissionStepRunAction.arguments defaults to None.
                args = step.arguments or {}
                if RESERVED_MIR_ARG_TYPE_KEY in args:
                    action_type = args.get(RESERVED_MIR_ARG_TYPE_KEY)
                    if not isinstance(action_type, str) or not action_type.strip():
                        raise ValueError(
                            f"runAction step {step.label!r}: {RESERVED_MIR_ARG_TYPE_KEY} must be "
                            f"a non-empty string"
                        )
                    action_type = action_type.strip()
                    # Reject scope-bearing / control-flow types here, before create_mission,
                    # so no orphan mission is created on the robot.
                    if action_type in DENIED_NATIVE_ACTIONS:
                        raise ValueError(
                            f"runAction step {step.label!r}: {DENIED_NATIVE_ACTIONS[action_type]}"
                        )
                    # Each surviving (non-reserved) key is a MiR action parameter id. Extract by
                    # exact reserved-key exclusion (not prefix-strip), matching vda5050.
                    parameters = {k: v for k, v in args.items() if k not in RESERVED_MIR_ARG_KEYS}
                    if not parameters:
                        logger.warning(
                            f"runAction step {step.label!r}: native MiR action {action_type!r} "
                            f"has no parameters after excluding reserved keys (all params "
                            f"mis-keyed?)"
                        )
                    pending_actions.append(
                        MirAction(
                            label=step.label,
                            action_type=action_type,
                            parameters=parameters,
                        )
                    )
                    pending_labels.append(step.label or "")
                    pending_timeouts.append(step.timeout_secs)
                    pending_task_ids.append(step.complete_task)
                    continue
                # No exact reserved key: route to the cloud action path. Warn on a stray
                # mir_-prefixed key so a fat-fingered type key fails loudly, not silently.
                if any(isinstance(k, str) and k.startswith(MIR_RESERVED_PREFIX) for k in args):
                    logger.warning(
                        f"runAction step {step.label!r} has {MIR_RESERVED_PREFIX}-prefixed "
                        f"arg(s) but no {RESERVED_MIR_ARG_TYPE_KEY}; routing to the cloud action "
                        f"path (typo?)"
                    )
                # fall through to flush + passthrough below

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
            # Grouped native steps no longer expose complete_task to the task extractor, so
            # pass the original per-step tasks through to keep InOrbit's task list intact.
            tasks_list=mission.tasks_list,
        )

        logger.debug(
            "Translated mission %s: %d original steps -> %d translated steps",
            mission.id,
            len(mission.definition.steps),
            len(translated_steps),
        )

        return translated_mission
