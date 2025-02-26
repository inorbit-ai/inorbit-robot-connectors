# SPDX-FileCopyrightText: 2024 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT
"""
datatypes

Defines different types shared by various modules.
"""
from enum import Enum
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

# FIXME(herchu) Remove Bluebotics dependency
# from inorbit_mir_connector.src.missions.datatypes import MissionStepCreateBlueBoticsMission


class MissionStepTypes(Enum):
    SET_DATA = "setData"
    RUN_ACTION = "runAction"
    WAIT = "wait"
    WAIT_UNTIL = "waitUntil"
    NAMED_WAYPOINT = "namedWaypoint"
    POSE_WAYPOINT = "poseWaypoint"


class Robot(BaseModel):
    id: str  # InOrbit robot id


class Pose(BaseModel):
    """
    Waypoint to be used for MissionStepPoseWaypoint
    """

    class WaypointProperties(BaseModel):
        waypointKind: str = Field(alias="x-bluebotics-waypoint-kind", default=None)

    x: float
    y: float
    theta: float
    frame_id: Optional[str] = Field(alias="frameId", default=None)
    waypointId: str = Field(alias="waypointId", default=None)
    properties: Optional[WaypointProperties] = Field(default=None)


class MissionStep(BaseModel):
    """
    Superclass for all mission steps.
    """

    label: str = Field(default=None)
    timeout_secs: float = Field(default=None, alias="timeoutSecs", ge=0)
    complete_task: str = Field(default=None, alias="completeTask")
    model_config = ConfigDict(extra="forbid")


class Target(BaseModel):
    """
    Target can be specified in some steps to use a robot different than the mission's one
    """

    robot_id: str = Field(default=None, alias="robotId")

    def dump_object(self):
        return dict(robot_id=self.robot_id)

    @classmethod
    def from_object(cls, robot_id, **kwargs):
        return Target(robotId=robot_id)


class MissionStepWait(MissionStep):
    """
    Mission step for simply waiting for some time.

    TODO(herchu) make timeout_secs NOT optional for this field (or just execute it ºas no-wait)
    """

    def accept(self, visitor):
        return visitor.visit_wait(self)

    def get_type(self):
        return MissionStepTypes.WAIT.value


class MissionStepSetData(MissionStep):
    """
    Mission step for adding metadata to a mission
    """

    data: Dict[str, Union[str, int, float, bool]]

    def accept(self, visitor):
        return visitor.visit_set_data(self)

    def get_type(self):
        return MissionStepTypes.SET_DATA.value


class MissionStepPoseWaypoint(MissionStep):
    """
    Mission step for navigating to a named waypoint.

    Note that like MissionStepNamedWaypoint, both are represented with a 'waypoint' field
    """

    waypoint: Pose

    def accept(self, visitor):
        return visitor.visit_pose_waypoint(self)

    def get_type(self):
        return MissionStepTypes.POSE_WAYPOINT.value


class MissionStepWaitUntil(MissionStep):
    """
    Mission step for waiting until a condition is true.
    """

    class WaitUntilArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        expression: str
        target: Target = Field(default=None)

    # TODO(herchu) find a better way to parse the nested { waitUntil: { expression } }
    wait_until: WaitUntilArgs = Field(alias="waitUntil")

    def _get_expression(self):
        return self.wait_until.expression

    expression = property(fget=_get_expression)

    def _get_target(self):
        return self.wait_until.target

    target = property(fget=_get_target)

    def accept(self, visitor):
        return visitor.visit_wait_until(self)

    def get_type(self):
        return MissionStepTypes.WAIT_UNTIL.value


class MissionStepRunAction(MissionStep):
    """
    Mission step for running robot actions
    """

    class RunActionArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        action_id: str = Field(alias="actionId")
        arguments: dict = Field(default=None)
        target: Target = Field(default=None)

    # TODO(herchu) find a better way to parse the nested { runAction: { actionId, arguments } }
    run_action: RunActionArgs = Field(alias="runAction")

    def _get_action_id(self):
        return self.run_action.action_id

    def _get_arguments(self):
        return self.run_action.arguments

    def _get_target(self):
        return self.run_action.target

    action_id = property(fget=_get_action_id)
    arguments = property(fget=_get_arguments)
    target = property(fget=_get_target)

    def get_type(self):
        return MissionStepTypes.RUN_ACTION.value


class MissionDefinition(BaseModel):
    """
    Mission Definition. Corresponds to the 'spec' schema of MissionDefinition kind in Config APIs
    """

    label: str = ""
    steps: List[
        Union[
            MissionStepSetData,
            MissionStepPoseWaypoint,
            MissionStepRunAction,
            MissionStepWait,
            MissionStepWaitUntil,
        ]
    ]
    selector: Any = Field(
        default=None
    )  # Accepted from API just to complete schema in struct mode (and ignore the field)
    model_config = ConfigDict(extra="forbid")


class MissionTask(BaseModel):
    """
    Represents one of the 'tasks' in the mission from Mission Tracking API point of view.
    It contains the state about being in progress or completed.
    """

    task_id: str = Field(alias="taskId")
    label: str
    in_progress: bool = Field(alias="inProgress", default=False)
    completed: bool = Field(default=False)


class MissionRuntimeOptions(BaseModel):
    """
    Options for running a mission. These are not part of the mission definition,
    but configuration or other fields that the executor adapter is passing
    to this (cloud) executor. They include information to change robot modes,
    using locks or waypoint tolerances during the mission.
    """

    start_mode: Union[str, None] = Field(default=None, alias="startMode")
    end_mode: Union[str, None] = Field(default=None, alias="endMode")
    use_locks: bool = Field(default=False, alias="useLocks")
    waypoint_distance_tolerance: Union[float, None] = Field(
        default=None, alias="waypointsDistanceTolerance"
    )
    waypoint_angular_tolerance: Union[float, None] = Field(
        default=None, alias="waypointsAngularTolerance"
    )
    model_config = ConfigDict(extra="forbid")


# Mission state stored in DB
class MissionWorkerState(BaseModel):
    """
    Serializable state for mission executor workers. This object is serialized
    directly to the DB. Only three of its fields are given semantics in the DB:
    the id, to find it, the 'finished' flag to avoid fishing for already finished
    missions, and the 'paused' flag that indicates if a mission is paused or not.
    The other field, `state`, is a freeform dict coming from serializing the behavior
    tree and other complex objects, not representable or serializable through
    Pydantic (see dump_json()).
    """

    mission_id: str
    finished: bool = Field(default=True)
    state: dict
    robot_id: str
    paused: bool = Field(default=False)


class MissionRuntimeSharedMemory(BaseModel):
    """
    Holds arbitrary data during mission during runtime as a shared memory.
    This object is passed during tree construction, and it is unique for the mission
    (ie. shared across all nodes). Tree nodes should not serialize it (since de-serialization
    would create *different instances*), but they should just store a reference during construction
    if needed.

    It can be used for several purposes:
     - to store connector-specific information such as the id of the robot in the fleet
       manager
     - to pass results from one step to another; ie. the mission from a specific fleet manager
     - to store error data (TODO: migrate current error_context to this object)

    Data is stored in 'keys' (kind of namespaces) which can have any value.
    For some weak typing and prevent runtime errors, keys need to be *declared* with
    add_data(), and then accessed with get_data(). After tree construction, this context
    is "frozen" so no additional calls to add_data() can be made. Note that only the "structure"
    ie. the keys set are frozen, but the "memory" is still mutable.

    They key "error" is reserved for storing the (to be migrated) initial error_context.
    """

    data: dict[str, Any] = Field(default={})
    frozen: bool = Field(default=False)
    model_config = ConfigDict(extra="forbid")

    def add(self, key, default_value=None) -> None:
        """
        Adds data to the context memory. The key must not exist yet, and this
        context cannot be frozen.
        """
        if self.frozen:
            raise Exception("MissionRuntimeSharedMemory is already frozen")
        if key not in self.data:
            self.data[key] = default_value

    def get(self, key) -> Any:
        """
        Gets some data from the context memory. The key must already exist.
        """
        if key not in self.data:
            raise Exception(f"Key {key} not found in MissionRuntimeSharedMemory")
        return self.data[key]

    def set(self, key, value) -> None:
        """
        Sets some data from the context memory. The key must already exist,
        and the context *must* be frozen (ie. no new keys being added; already in
        mission execution).
        """
        if not self.frozen:
            raise Exception("MissionRuntimeSharedMemory is not yet frozen; use add()")
        if key not in self.data:
            raise Exception(f"Key {key} not found in MissionRuntimeSharedMemory")
        self.data[key] = value

    def freeze(self):
        """
        Freeze this memory holder. Once frozen, no keys can be added (but values
        can still be modified).
        """
        self.frozen = True
