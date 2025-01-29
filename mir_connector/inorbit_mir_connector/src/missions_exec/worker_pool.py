# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from inorbit_mir_connector.src.missions.behavior_tree import (
    BehaviorTreeBuilderContext,
    BehaviorTreeErrorHandler,
    BehaviorTreeSequential,
    LockRobotNode,
    MissionAbortedNode,
    MissionCompletedNode,
    MissionPausedNode,
    MissionStartNode,
    TaskCompletedNode,
    TaskStartedNode,
    TimeoutNode,
    UnlockRobotNode,
    WaitNode,
)
from inorbit_mir_connector.src.missions.db import WorkerPersistenceDB
from inorbit_mir_connector.src.missions.dummy_backend import DummyDB
from inorbit_mir_connector.src.missions.inorbit import InOrbitAPI, MissionStatus
from inorbit_mir_connector.src.missions.mission import Mission
from inorbit_mir_connector.src.missions.worker_pool import WorkerPool
from inorbit_mir_connector.src.mir_api.mir_api_base import MirApiBaseClass
from inorbit_mir_connector.src.missions_exec.behavior_tree import MirNodeFromStepBuilder
from inorbit_mir_connector.src.missions_exec.translator import InOrbitToMirTranslator


class MirBehaviorTreeBuilderContext(BehaviorTreeBuilderContext):
    """
    It adds the MiR API client to the behavior tree context
    """

    def __init__(self, mir_api: MirApiBaseClass):
        super().__init__()
        self._mir_api = mir_api


class MirWorkerPool(WorkerPool):
    """
    Worker pool for executing missions.
    Note: The framwork is designed with handling multiple robots in mind, but for simplicity this
    worker pool is kept.
    """

    def __init__(
        self,
        mir_api: MirApiBaseClass,
        inorbit_api: InOrbitAPI,
        db: WorkerPersistenceDB = DummyDB(),
    ):
        super().__init__(inorbit_api, db)
        self._mir_api = mir_api

    def create_builder_context(self) -> BehaviorTreeBuilderContext:
        return MirBehaviorTreeBuilderContext(self._mir_api)

    def translate_mission(self, mission: Mission) -> Mission:
        return InOrbitToMirTranslator.translate(mission, self._mir_api)

    def build_tree_for_mission(self, context: BehaviorTreeBuilderContext):
        # NOTE: Most of the code in this method is copied from the superclass implementation
        # It only differs in the step_builder node used

        mission = context.mission
        tree = BehaviorTreeSequential(label=f"mission {mission.id}")
        tree.add_node(MissionStartNode(context, label="mission start"))
        step_builder = MirNodeFromStepBuilder(context)

        for step, ix in zip(mission.definition.steps, range(len(mission.definition.steps))):
            # TODO build the right kind of behavior node
            try:
                node = step.accept(step_builder)
            except Exception as e:  # TODO
                raise Exception(f"Error building step #{ix} [{step}]: {str(e)}")
            # Before every step, keep robot locked
            tree.add_node(LockRobotNode(context, label="lock robot"))
            if step.timeout_secs is not None and not isinstance(node, WaitNode):
                node = TimeoutNode(step.timeout_secs, node, label=f"timeout for {step.label}")
            if step.complete_task is not None:
                tree.add_node(
                    TaskStartedNode(
                        context,
                        step.complete_task,
                        label=f"report task {step.complete_task} started",
                    )
                )
            if node:
                tree.add_node(node)
            if step.complete_task is not None:
                tree.add_node(
                    TaskCompletedNode(
                        context,
                        step.complete_task,
                        label=f"report task {step.complete_task} completed",
                    )
                )

        tree.add_node(MissionCompletedNode(context, label="mission completed"))
        tree.add_node(UnlockRobotNode(context, label="unlock robot after mission completed"))
        # add error handlers
        on_error = BehaviorTreeSequential(label="error handlers")
        on_error.add_node(
            MissionAbortedNode(context, status=MissionStatus.error, label="mission aborted")
        )
        on_error.add_node(UnlockRobotNode(context, label="unlock robot after mission abort"))
        on_cancel = BehaviorTreeSequential(label="cancel handlers")
        on_cancel.add_node(
            MissionAbortedNode(context, status=MissionStatus.ok, label="mission cancelled")
        )
        on_cancel.add_node(UnlockRobotNode(context, label="unlock robot after mission cancel"))
        on_pause = BehaviorTreeSequential(label="pause handlers")
        on_pause.add_node(MissionPausedNode(context, label="mission paused"))
        tree = BehaviorTreeErrorHandler(
            context, tree, on_error, on_cancel, on_pause, context.error_context, label=tree.label
        )
        return tree
