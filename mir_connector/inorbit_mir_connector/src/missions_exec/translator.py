# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import math
from typing import List
from inorbit_mir_connector.src.missions.datatypes import (
    MissionStep,
    MissionStepPoseWaypoint,
    MissionStepRunAction,
)
from inorbit_mir_connector.src.missions.mission import Mission
from inorbit_mir_connector.src.missions_exec.contants import CustomCommands
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

        # Group consecutive waypoints and run_mission actions into batches
        batched_steps = InOrbitToMirTranslator._batch_steps(inorbit_mission.definition.steps)

        for batch in batched_steps:
            if len(batch) == 1 and not InOrbitToMirTranslator._is_groupable_step(batch[0]):
                # For single non-groupable steps, add them as-is
                steps.append(batch[0].model_copy(deep=True))
            else:
                # For batches of waypoints and actions that run missions, create a single mission
                mir_mission_data = InOrbitToMirTranslator._create_mission_for_batch(
                    batch, inorbit_temp_missions_group_id, waypoint_nav_extra_params
                )

                # Get the first and last task IDs from the batch for reporting
                first_task_id = batch[0].complete_task if batch[0].complete_task else None
                last_task_id = batch[-1].complete_task if batch[-1].complete_task else None

                # Create a label that describes the batch
                batch_label = f"Batch: {batch[0].label} to {batch[-1].label}"
                # Calculate the total timeout as the sum of all step timeouts (or use a default)
                total_timeout = sum(step.timeout_secs or 0 for step in batch)
                if total_timeout == 0:
                    total_timeout = None

                # Convert to MiR mission step
                mir_step = MissionStepCreateMiRMission(
                    label=batch_label,
                    timeoutSecs=total_timeout,
                    completeTask=last_task_id,  # Use the last step's task
                    mir_mission_data=mir_mission_data,
                    first_task_id=first_task_id,
                )
                steps.append(mir_step)

        # Return the translated mission
        mir_mission = inorbit_mission.model_copy(deep=True)
        mir_mission.definition.steps = steps

        return MiRInOrbitMission(**mir_mission.model_dump(by_alias=True))

    @staticmethod
    def _is_groupable_step(step: MissionStep) -> bool:
        """
        Determine if a step is groupable (waypoint or action that runs a mission)
        """
        if isinstance(step, MissionStepPoseWaypoint):
            return True

        if isinstance(step, MissionStepRunAction):
            # TODO(b-Tomas): Run action steps only include the actionId. The action definition is
            # not sent and it would have to be fetched somehow without dispatching.
            # For now, we'll just return False. A workaround could be to encode missions in the
            # action steps of the mission definition.
            return False

        return False

    @staticmethod
    def _batch_steps(steps: List[MissionStep]) -> List[List[MissionStep]]:
        """
        Group consecutive waypoints and actions that run missions into batches
        """
        batches = []
        current_batch = []

        for step in steps:
            if InOrbitToMirTranslator._is_groupable_step(step):
                current_batch.append(step)
            else:
                # If we have a non-groupable step, flush the current batch if it exists
                if current_batch:
                    batches.append(current_batch)
                    current_batch = []
                # Add the non-groupable step as its own batch
                batches.append([step])

        # Don't forget the last batch if it exists
        if current_batch:
            batches.append(current_batch)

        return batches

    @staticmethod
    def _create_mission_for_batch(
        batch: List[MissionStep], group_id: str, waypoint_nav_extra_params: dict
    ) -> MiRNewMissionData:
        """
        Create a MiR mission from a batch of steps
        """
        actions = []
        priority = 0

        mission_name = f"{batch[0].label} to {batch[-1].label}"

        for step in batch:
            if isinstance(step, MissionStepPoseWaypoint):
                # Add a waypoint action
                params = [
                    {
                        "value": v,
                        "input_name": None,
                        "id": k,
                    }
                    for k, v in {
                        "x": step.waypoint.x,
                        "y": step.waypoint.y,
                        "orientation": math.degrees(step.waypoint.theta),
                        **waypoint_nav_extra_params,
                    }.items()
                ]

                actions.append(
                    MiRNewMissionData.MiRNewActionData(
                        action_type="move_to_position",
                        parameters=params,
                        priority=priority,
                    )
                )

            elif isinstance(
                step, MissionStepRunAction
            ) and InOrbitToMirTranslator._is_groupable_step(step):
                # Add a mission run action that references another MiR mission
                args = step.arguments
                mission_id = None

                if args.get("--mission_id"):
                    mission_id = args.get("--mission_id")

                if mission_id:
                    actions.append(
                        MiRNewMissionData.MiRNewActionData(
                            action_type="load_mission",
                            parameters=[
                                {
                                    "type": "Hidden",
                                    "id": "mission_id",
                                    "name": "mission_id",
                                    "constraints": {
                                        "default": mission_id,
                                    },
                                }
                            ],
                            priority=priority,
                        )
                    )

            priority += 1

        # Create the mission data
        return MiRNewMissionData(
            name=mission_name,
            group_id=group_id,
            description=f"Combined mission created by InOrbit: {mission_name}",
            actions=actions,
        )
