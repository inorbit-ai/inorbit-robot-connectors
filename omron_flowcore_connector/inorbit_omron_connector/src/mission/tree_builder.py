# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tree builder for Omron FlowCore missions."""

from __future__ import annotations

from typing import override

from inorbit_edge_executor.behavior_tree import (
    BehaviorTree,
    BehaviorTreeErrorHandler,
    BehaviorTreeSequential,
    DefaultTreeBuilder,
    MissionCompletedNode,
    MissionInProgressNode,
    MissionPausedNode,
)
from inorbit_edge_executor.inorbit import MissionStatus

from inorbit_omron_connector.src.mission.behavior_tree import (
    OmronBehaviorTreeBuilderContext,
    OmronMissionAbortedNode,
    OmronNodeFromStepBuilder,
    CleanupOmronJobNode,
)


class OmronTreeBuilder(DefaultTreeBuilder):
    """Tree builder specialized for Omron FlowCore missions."""

    def __init__(self, **kwargs):
        super().__init__(step_builder_factory=OmronNodeFromStepBuilder, **kwargs)

    @override
    def build_tree_for_mission(self, context: OmronBehaviorTreeBuilderContext) -> BehaviorTree:
        """Build a behavior tree for an Omron mission."""
        mission = context.mission
        tree = BehaviorTreeSequential(label=f"mission {mission.id}")

        tree.add_node(MissionInProgressNode(context, label="mission start"))

        step_builder = OmronNodeFromStepBuilder(context)
        step_builder.add_step_node_decorator(self._build_step_decorator_for_context(context))

        for ix, step in enumerate(mission.definition.steps):
            try:
                node = step.accept(step_builder)
            except Exception as e:
                raise RuntimeError(f"Error building step #{ix} [{step}]: {e}") from e
            if node:
                tree.add_node(node)

        tree.add_node(MissionCompletedNode(context, label="mission completed"))

        # Error handling
        on_error = BehaviorTreeSequential(label="error handlers")
        on_error.add_node(
            OmronMissionAbortedNode(context, status=MissionStatus.error, label="mission aborted")
        )

        on_cancel = BehaviorTreeSequential(label="cancel handlers")
        on_cancel.add_node(
            OmronMissionAbortedNode(context, status=MissionStatus.ok, label="mission cancelled")
        )
        
        on_pause = BehaviorTreeSequential(label="pause handlers")
        on_pause.add_node(CleanupOmronJobNode(context, label="cleanup omron jobs"))
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
