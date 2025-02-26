# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from inorbit_mir_connector.src.missions.datatypes import (
    MissionDefinition,
    MissionRuntimeOptions,
    MissionStep,
    MissionStepRunAction,
    MissionStepSetData,
    MissionStepWait,
    MissionStepWaitUntil,
)
from inorbit_mir_connector.src.missions.mission import Mission
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from inorbit_mir_connector.src.missions_exec.behavior_tree import MirNodeFromStepBuilder


class MiRNewMissionData(BaseModel):
    """
    Data required for creating a new MiR mission.
    """

    class MiRNewActionData(BaseModel):
        """
        Data required for adding an action to a new MiR mission.
        Note that the mission_id is required, but will be filled by the nodes that
        create the mission.
        """

        action_type: str
        guid: Optional[str] = None
        parameters: List[Dict[str, Any]]
        priority: int
        scope_references: Optional[str] = None

    # Fields required at mission creation
    name: str
    group_id: str
    description: Optional[str] = None
    guid: Optional[str] = None
    created_by_id: Optional[str] = None
    hidden: Optional[bool] = None
    session_id: Optional[str] = None
    # Extra fields required at actions addition
    actions: List[MiRNewActionData]
    # Extra fields required at mission queueing
    priority: Optional[int] = None
    parameters: Optional[List[Dict[str, Any]]] = None
    message: Optional[str] = None
    fleet_schedule_guid: Optional[str] = None


class MissionStepCreateMiRMission(MissionStep):
    """
    Mission step for creating and queueing an MiR mission.
    """

    mir_mission_data: MiRNewMissionData
    # HACK(b-Tomas): Values for allowing task tracking
    # All of the tasks in between the first and last task are not tracked yet,
    # They are all marked as completed when the mission ends.
    first_task_id: str
    last_task_id: str

    def accept(self, visitor: "MirNodeFromStepBuilder"):
        return visitor.visit_create_mir_mission(self)


class MissionDefinitionMiR(MissionDefinition):
    """
    Mission Definition. Subclassing InOrbit type, it adds MiR-specific mission steps and
    ignores InOrbit steps that should be removed during translation.
    """

    steps: List[
        Union[
            # InOrbit-native steps:
            MissionStepSetData,
            MissionStepWait,
            MissionStepWaitUntil,
            # Some actions are not translatable (such as actions run on other robots), so
            # we keep them as-is.
            MissionStepRunAction,
            # MiR-native steps:
            MissionStepCreateMiRMission,
            # TODO: In case of a MiR mission surrounded by InOrbit non-translatable steps,
            # we could add a "MissionStepRunMission" that only queues a mission.
            # The queueing part of "MissionStepCreateMiRMission" could be extracted.
            # Forbidden steps:
            # MissionStepPoseWaypoint,  # Should be translated to MiR-native steps
        ]
    ]


class MiRInOrbitMission(Mission):
    """
    Mission subclass execute by the WorkerPool. The only difference with the
    superclass is that the definition is a MissionDefinitionMiR.
    """

    definition: MissionDefinitionMiR


# Mission commands as received from the edge-sdk
# TODO(b-Tomas): Should be part of the executor package, or edge-sdk package. Maybe connector
# package?
class MissionExecuteRequest(BaseModel):
    mission_id: str = Field(max_length=100, title="Mission ID", alias="missionId")
    robot_id: str = Field(max_length=100, title="Robot ID", alias="robotId")
    mission_definition: MissionDefinition = Field(alias="missionDefinition")
    arguments: Union[Dict[str, Any], None] = Field(default=None, alias="missionArgs")
    options: Optional[MissionRuntimeOptions] = Field(
        alias="options", default=MissionRuntimeOptions()
    )
    model_config = ConfigDict(extra="forbid")


class MissionCancelRequest(BaseModel):
    mission_id: str = Field(max_length=100, title="Mission ID", alias="missionId")


class UpdateMissionRequest(BaseModel):
    pass
