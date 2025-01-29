# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from typing import Any
from typing import Dict
from typing import List
from typing import Literal
from typing import Optional
from typing import Union

from inorbit_mir_connector.src.missions.datatypes import MissionDefinition
from inorbit_mir_connector.src.missions.datatypes import MissionRuntimeOptions
from inorbit_mir_connector.src.missions.datatypes import MissionStep
from inorbit_mir_connector.src.missions.datatypes import MissionStepPoseWaypoint
from inorbit_mir_connector.src.missions.datatypes import MissionStepSetData
from inorbit_mir_connector.src.missions.mission import Mission
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from typing_extensions import Self


# class BlueboticsExecuteMissionFeedback(BaseModel):
#     """
#     Represents the format of the feedback message when executing a mission.
#     """

#     inorbit_mission_id: str
#     state: Literal["accepted", "rejected", "pending", "error"]
#     message: Optional[str] = Field(default=None)

#     def feedback_type(self):
#         return MISSION_EXECUTE_FEEDBACK


# class BlueboticsCancelMissionFeedback(BaseModel):
#     """
#     Represents the format of the feedback message when canceling a mission.
#     """

#     inorbit_mission_id: str
#     cancelled: bool
#     message: Optional[str] = Field(default=None)

#     def feedback_type(self):
#         return MISSION_CANCEL_FEEDBACK


# class MissionStepCreateBlueBoticsMission(MissionStep):
#     """
#     Mission step for creating and order at bluebotics.
#     Note that order assigments and updates are done with the same method.
#     """

#     mission: BlueboticsApiMission

#     def accept(self, visitor):
#         return visitor.visit_create_bluebotics_mission(self)


class MissionDefinitionMiR(MissionDefinition):
    """
    Mission Definition. Subclassing InOrbit type, it adds MiR-specific mission steps.
    """

    steps: List[
        Union[
            MissionStepSetData,
            MissionStepPoseWaypoint,
            # Bluebotics:
            # MissionStepCreateBlueBoticsMission,
        ]
    ]


class MissionExecuteRequest(BaseModel):
    mission_id: str = Field(max_length=100, title="Mission ID", alias="missionId")
    robot_id: str = Field(max_length=100, title="Robot ID", alias="robotId")
    mission_definition: MissionDefinitionMiR = Field(alias="missionDefinition")
    arguments: Union[Dict[str, Any], None] = Field(default=None, alias="missionArgs")
    options: Optional[MissionRuntimeOptions] = Field(
        alias="options", default=MissionRuntimeOptions()
    )
    model_config = ConfigDict(extra="forbid")


class MissionCancelRequest(BaseModel):
    mission_id: str = Field(max_length=100, title="Mission ID", alias="missionId")


class UpdateMissionRequest(BaseModel):
    pass


# class BlueboticsInOrbitMission(Mission):
#     """
#     Mission subclass to use in the Bluebotics package. The only difference is
#     the Definition field, which is (must be) a subclass of MissionDefinition and
#     contains some added steps from Bluebotics.
#     """

#     definition: MissionDefinitionBluebotics

#     @model_validator(mode="after")
#     def validate(self) -> Self:
#         super().validate()

#         if len(self.definition.steps) > 3:
#             msg = ("Missions can't have more than 3 steps.",)
#             raise ValueError(msg)

#         if len(self.definition.steps) == 3:
#             if not isinstance(self.definition.steps[0], MissionStepSetData):
#                 msg = "If the mission has 3 steps, the first one type must be 'SetData'"
#                 raise ValueError(msg)

#         for index, step in enumerate(self.definition.steps):
#             if isinstance(step, MissionStepSetData) and index > 0:
#                 msg = "Only the first step can be of type 'SetData'"
#                 raise ValueError(msg)

#         return self
