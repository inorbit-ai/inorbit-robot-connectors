# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import math
from inorbit_mir_connector.src.missions.datatypes import MissionStepPoseWaypoint
from inorbit_mir_connector.src.missions.mission import Mission
from inorbit_mir_connector.src.missions_exec.datatypes import (
    MiRInOrbitMission,
    MiRNewMissionData,
    MissionStepCreateMiRMission,
)


class InOrbitToMirTranslator:
    """
    A translator class that converts missions from InOrbit format to MiR format.
    """

    @staticmethod
    def translate(
        inorbit_mission: Mission,
        inorbit_temp_missions_group_id: str,
        waypoint_nav_extra_params: dict,
    ) -> MiRInOrbitMission:
        steps = []

        # TODO(b-Tomas): This only translates individual waypoints without any optimization.
        # Waypoints and actions that dipatch missions should be grouped together.
        for step in inorbit_mission.definition.steps:
            if isinstance(step, MissionStepPoseWaypoint):
                # Create MiR mission data for a waypoint navigation mission
                mir_mission_data = MiRNewMissionData(
                    name=f"Go to {step.waypoint.waypointId}",
                    group_id=inorbit_temp_missions_group_id,
                    description=f"Navigate to waypoint {step.waypoint.waypointId}",
                    actions=[
                        MiRNewMissionData.MiRNewActionData(
                            action_type="move_to_position",
                            parameters=[
                                {
                                    "value": v,
                                    "input_name": None,
                                    # "guid": str(uuid.uuid4()),
                                    "id": k,
                                }
                                for k, v in {
                                    "x": step.waypoint.x,
                                    "y": step.waypoint.y,
                                    "orientation": math.degrees(step.waypoint.theta),
                                    **waypoint_nav_extra_params,
                                }.items()
                            ],
                            priority=0,  # priority should go in increasing order within a mission
                        )
                    ],
                )
                # Convert to MiR mission step
                mir_step = MissionStepCreateMiRMission(
                    label=step.label,
                    timeoutSecs=step.timeout_secs,
                    completeTask=step.complete_task,
                    mir_mission_data=mir_mission_data,
                    first_task_id=step.complete_task,
                    last_task_id=step.complete_task,
                )
                steps.append(mir_step)
            else:
                steps.append(step.model_copy(deep=True))

        # Create a proper MissionDefinitionMiR from mission definition data
        mir_mission = inorbit_mission.model_copy(deep=True)
        mir_mission.definition.steps = steps

        return MiRInOrbitMission(**mir_mission.model_dump(by_alias=True))
