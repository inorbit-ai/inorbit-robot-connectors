# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from inorbit_mir_connector.src.mir_api.mir_api_v2 import MISSIONS_ENDPOINT_V2
from inorbit_mir_connector.src.missions.behavior_tree import (
    BehaviorTree,
    BehaviorTreeErrorHandler,
    BehaviorTreeSequential,
    MissionInProgressNode,
    NodeFromStepBuilder,
    TaskCompletedNode,
    TaskStartedNode,
)

from inorbit_mir_connector.src.missions_exec.contants import SharedMemoryKeys
from inorbit_mir_connector.src.missions_exec.datatypes import (
    MiRNewMissionData,
    MissionStepCreateMiRMission,
)

if TYPE_CHECKING:
    from inorbit_mir_connector.src.missions_exec.worker_pool import (
        MirBehaviorTreeBuilderContext,
    )

logger = logging.getLogger(name="MiR BehaviorTree")
logger.setLevel(logging.DEBUG)

# NOTE: API calls are all blocking. The API should be reimplemented using asyncio.


class CreateMiRMissionNode(BehaviorTree):
    def __init__(
        self,
        context: "MirBehaviorTreeBuilderContext",
        mir_mission_data: MiRNewMissionData,
        *args,
        **kwargs,
    ):
        # Reference to the tree's shared memory
        self._shared_memory = context.shared_memory
        # Declare the keys that will be used in the tree
        self._shared_memory.add(SharedMemoryKeys.MIR_MISSION_ID)
        self._mir_api = context.mir_api
        self._mir_mission_data = mir_mission_data

        super().__init__(*args, **kwargs)

    async def _execute(self):
        # TODO(b-Tomas): Figure out what happens if the calls fails
        # TODO(b-Tomas): Add error handling
        json_response = self._mir_api.create_mission(
            name=self._mir_mission_data.name,
            group_id=self._mir_mission_data.group_id,
            **{
                k: v
                for k, v in {
                    "guid": self._mir_mission_data.guid,
                    "description": self._mir_mission_data.description,
                    "created_by_id": self._mir_mission_data.created_by_id,
                    "hidden": self._mir_mission_data.hidden,
                    "session_id": self._mir_mission_data.session_id,
                }.items()
                if v is not None
            },
        )
        guid = json_response["guid"]
        logger.debug(f"MiR mission created: {guid}")
        self._shared_memory.set(SharedMemoryKeys.MIR_MISSION_ID, guid)

    def dump_object(self):
        object = super().dump_object()
        object["mir_mission_data"] = self._mir_mission_data.model_dump()
        return object

    @classmethod
    def from_object(cls, context, mir_mission_data, **kwargs):
        return CreateMiRMissionNode(context, MiRNewMissionData(**mir_mission_data), **kwargs)


class AddMiRMissionActionsNode(BehaviorTree):
    def __init__(
        self,
        context: "MirBehaviorTreeBuilderContext",
        actions: List[MiRNewMissionData.MiRNewActionData],
        *args,
        **kwargs,
    ):
        self._shared_memory = context.shared_memory
        self._mir_api = context.mir_api
        self._actions = actions

        super().__init__(*args, **kwargs)

    async def _execute(self):
        mission_id = self._shared_memory.get(SharedMemoryKeys.MIR_MISSION_ID)
        calls = [
            {
                "method": "POST",
                "url": f"{MISSIONS_ENDPOINT_V2}/{mission_id}/actions",
                "body": {
                    k: v
                    for k, v in {**action.model_dump(), "mission_id": mission_id}.items()
                    if v is not None
                },
            }
            for action in self._actions
        ]
        logger.debug(f"Adding actions to mission {mission_id}. Calls: {calls}")
        response = self._mir_api.batch_call(calls)
        logger.debug(f"Added actions to mission {mission_id}")
        logger.debug(f"Response: {response}")
        # Validate response
        if not isinstance(response, list):
            error_msg = f"Expected list response from batch call, got {type(response)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        if len(response) != len(calls):
            error_msg = f"Expected {len(calls)} responses, got {len(response)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    def dump_object(self):
        object = super().dump_object()
        object["actions"] = [action.model_dump() for action in self._actions]
        return object

    @classmethod
    def from_object(cls, context, actions, **kwargs):
        return AddMiRMissionActionsNode(
            context, [MiRNewMissionData.MiRNewActionData(**action) for action in actions], **kwargs
        )


class QueueMiRMissionNode(BehaviorTree):
    def __init__(
        self,
        context: "MirBehaviorTreeBuilderContext",
        priority: Optional[int] = None,
        parameters: Optional[List[Dict[str, Any]]] = None,
        message: Optional[str] = None,
        description: Optional[str] = None,
        fleet_schedule_guid: Optional[str] = None,
        *args,
        **kwargs,
    ):
        self._shared_memory = context.shared_memory
        self._shared_memory.add(SharedMemoryKeys.QUEUED_MISSION_ID)
        self._mir_api = context.mir_api
        self._priority = priority
        self._parameters = parameters
        self._message = message
        self._description = description
        self._fleet_schedule_guid = fleet_schedule_guid

        super().__init__(*args, **kwargs)

    async def _execute(self):
        mission_id = self._shared_memory.get(SharedMemoryKeys.MIR_MISSION_ID)

        # Build mission queue request body with only non-None values
        body = {}
        if self._priority is not None:
            body["priority"] = self._priority
        if self._parameters is not None:
            body["parameters"] = self._parameters
        if self._message is not None:
            body["message"] = self._message
        if self._description is not None:
            body["description"] = self._description
        if self._fleet_schedule_guid is not None:
            body["fleet_schedule_guid"] = self._fleet_schedule_guid

        # Queue the mission using the MiR API method
        queued_mission = self._mir_api.queue_mission(mission_id=mission_id, **body)
        logger.debug(f"Queued mission {queued_mission}")
        self._shared_memory.set(SharedMemoryKeys.QUEUED_MISSION_ID, queued_mission["id"])

    def dump_object(self):
        object = super().dump_object()
        object.update(
            {
                "priority": self._priority,
                "parameters": self._parameters,
                "message": self._message,
                "description": self._description,
                "fleet_schedule_guid": self._fleet_schedule_guid,
            }
        )
        return object

    @classmethod
    def from_object(
        cls,
        context,
        priority=None,
        parameters=None,
        message=None,
        description=None,
        fleet_schedule_guid=None,
        **kwargs,
    ):
        return QueueMiRMissionNode(
            context,
            priority=priority,
            parameters=parameters,
            message=message,
            description=description,
            fleet_schedule_guid=fleet_schedule_guid,
            **kwargs,
        )


class WaitUntilMiRMissionIsRunningNode(BehaviorTree):
    def __init__(self, context: "MirBehaviorTreeBuilderContext", *args, **kwargs):
        self._shared_memory = context.shared_memory
        self._mir_api = context.mir_api

        super().__init__(*args, **kwargs)

    async def _execute(self):
        queued_mission_id = self._shared_memory.get(SharedMemoryKeys.QUEUED_MISSION_ID)
        while True:
            mission = self._mir_api.get_mission(queued_mission_id)
            logger.debug(f"MiR mission state: {mission['state']}")
            # TODO(b-Tomas): Proper handling of the mission state
            if mission["state"].lower() in ["executing", "done"]:
                break
            await asyncio.sleep(1)


class TrackRunningMiRMissionNode(BehaviorTree):
    def __init__(self, context: "MirBehaviorTreeBuilderContext", *args, **kwargs):
        self._shared_memory = context.shared_memory
        self._mir_api = context.mir_api

        super().__init__(*args, **kwargs)

    async def _execute(self):
        queued_mission_id = self._shared_memory.get(SharedMemoryKeys.QUEUED_MISSION_ID)
        while True:
            logger.debug(f"Getting queued mission {queued_mission_id}")
            mission = self._mir_api.get_mission(queued_mission_id)
            logger.debug(f"MiR mission state: {mission['state']}")
            # TODO(b-Tomas): Proper handling of the mission state
            # TODO(b-Tomas): Task tracking
            if mission["state"].lower() != "executing":
                break
            await asyncio.sleep(1)


class MirNodeFromStepBuilder(NodeFromStepBuilder):
    """
    A node builder that creates MiR nodes from InOrbit mission steps.
    """

    def __init__(self, context: "MirBehaviorTreeBuilderContext"):
        super().__init__(context)

    def visit_create_mir_mission(self, step: MissionStepCreateMiRMission):
        bt_sequential = BehaviorTreeSequential(label=step.label)

        bt_sequential.add_node(
            CreateMiRMissionNode(
                self.context,
                step.mir_mission_data,
                label=f"'{step.label}' create MiR mission",
            )
        )
        bt_sequential.add_node(
            AddMiRMissionActionsNode(
                self.context,
                step.mir_mission_data.actions,
                label=f"'{step.label}' add MiR mission actions",
            )
        )
        bt_sequential.add_node(
            QueueMiRMissionNode(
                self.context,
                step.mir_mission_data.priority,
                step.mir_mission_data.parameters,
                step.mir_mission_data.message,
                step.mir_mission_data.description,
                step.mir_mission_data.fleet_schedule_guid,
                label=f"'{step.label}' queue MiR mission",
            )
        )
        bt_sequential.add_node(
            WaitUntilMiRMissionIsRunningNode(
                self.context,
                label=f"'{step.label}' wait until MiR mission is running",
            )
        )
        bt_sequential.add_node(TaskStartedNode(self.context, step.first_task_id))  # HACK
        bt_sequential.add_node(
            MissionInProgressNode(self.context)
        )  # HACK: Why is this not in the superclass??
        bt_sequential.add_node(TrackRunningMiRMissionNode(self.context))
        bt_sequential.add_node(TaskCompletedNode(self.context, step.last_task_id))  # HACK

        # TODO(b-Tomas): Error handlers
        on_error = None
        on_cancelled = None
        on_pause = None

        return BehaviorTreeErrorHandler(
            context=self.context,
            behavior=bt_sequential,
            error_handler=on_error,
            cancelled_handler=on_cancelled,
            pause_handler=on_pause,
            error_context=self.context.error_context,
            # TODO(b-Tomas): Determine what reset_execution_on_pause is and what value it should
            # have
            reset_execution_on_pause=True,
            label=f"'{bt_sequential.label}' error handler",
        )
