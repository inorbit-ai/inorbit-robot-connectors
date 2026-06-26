# SPDX-FileCopyrightText: 2026 Mappalink
#
# SPDX-License-Identifier: MIT
#
# Vendored from the Mappalink MiR connector:
#   https://github.com/mappalink/inorbit-mir-connector/blob/c516f7d9e8e6b8b3cbaa396e2984ce149c6e7925/mir_connector/src/mission/tree_builder.py
# Upstream commit: c516f7d9e8e6b8b3cbaa396e2984ce149c6e7925 (2026-05-21)
#
# Modifications from upstream:
#   - 2026-06-26: rebased import prefix mir_connector.src.* -> inorbit_mir_connector.src.*

"""Tree builder for MiR missions with compiled native mission steps."""

from __future__ import annotations

import logging

from inorbit_edge_executor.behavior_tree import (
    BehaviorTree,
    BehaviorTreeErrorHandler,
    BehaviorTreeSequential,
    DefaultTreeBuilder,
    MissionCompletedNode,
    MissionInProgressNode,
    MissionPausedNode,
    register_accepted_node_types,
)
from inorbit_edge_executor.inorbit import MissionStatus
from inorbit_mir_connector.src.mission.behavior_tree import (
    MirBehaviorTreeBuilderContext,
    MirMissionAbortedNode,
    MirNodeFromStepBuilder,
)

logger = logging.getLogger(__name__)


class LoggingMissionCompletedNode(MissionCompletedNode):
    """MissionCompletedNode with debug logging around mt.completed()."""

    async def _execute(self):
        logger.info(f"MissionCompletedNode: calling mt.completed() for mission {self.mt.id}")
        try:
            result = await self.mt.completed()
            logger.info(f"MissionCompletedNode: mt.completed() returned {result}")
        except Exception as e:
            logger.error(f"MissionCompletedNode: mt.completed() raised {e}")
            raise


register_accepted_node_types([LoggingMissionCompletedNode])


class MirTreeBuilder(DefaultTreeBuilder):
    """Tree builder specialized for MiR missions with compiled native steps."""

    def __init__(self, **kwargs):
        super().__init__(step_builder_factory=MirNodeFromStepBuilder, **kwargs)

    def build_tree_for_mission(self, context: MirBehaviorTreeBuilderContext) -> BehaviorTree:
        mission = context.mission
        tree = BehaviorTreeSequential(label=f"mission {mission.id}")

        tree.add_node(MissionInProgressNode(context, label="mission start"))

        step_builder = MirNodeFromStepBuilder(context)

        for ix, step in enumerate(mission.definition.steps):
            try:
                node = step.accept(step_builder)
            except Exception as e:
                raise RuntimeError(f"Error building step #{ix} [{step}]: {e}") from e
            if node:
                tree.add_node(node)

        tree.add_node(LoggingMissionCompletedNode(context, label="mission completed"))

        # Error handling
        on_error = BehaviorTreeSequential(label="error handlers")
        on_error.add_node(
            MirMissionAbortedNode(context, status=MissionStatus.error, label="mission aborted")
        )

        on_cancel = BehaviorTreeSequential(label="cancel handlers")
        on_cancel.add_node(
            MirMissionAbortedNode(context, status=MissionStatus.ok, label="mission cancelled")
        )

        on_pause = BehaviorTreeSequential(label="pause handlers")
        # No CleanupMirMissionNode here — MiR mission stays queued.
        # MirWorkerPool.pause_mission() sets robot state to PAUSE, which
        # suspends the active MiR mission in place. On resume, set_state(READY)
        # lets the MiR mission continue from where it was.
        on_pause.add_node(MissionPausedNode(context, label="mission paused"))

        tree = BehaviorTreeErrorHandler(
            context,
            tree,
            on_error,
            on_cancel,
            on_pause,
            context.error_context,
            label=f"mission {mission.id}",
        )

        return tree
