# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Mission translator that converts InOrbit missions to Omron FlowCore format.

Handles custom gotoGoals action into Omron Jobs.
"""

from __future__ import annotations

import logging
from typing import Optional

from inorbit_edge_executor.datatypes import (
    MissionStepSetData,
    MissionStepRunAction
)
from inorbit_edge_executor.mission import Mission

from inorbit_omron_connector.src.mission.datatypes import (
    OmronInOrbitMission,
    MissionDefinitionOmron,
    MissionStepExecuteOmronJob,
    OmronStepsList,
)
from inorbit_omron_connector.src.omron.models import JobRequestDetail

logger = logging.getLogger(__name__)


class InOrbitToOmronTranslator:
    """Translates InOrbit mission steps into Omron FlowCore jobs.

    The translator handles gotoGoals actions into Omron jobs.

    Args:
        mission: The original InOrbit mission
        fleet_robot_id: The FlowCore robot namekey to assign missions to (optional)

    Returns:
        Translated mission with Omron-specific step types

    Raises:
        ValueError: If the mission has no steps to translate
    """

    @staticmethod
    def translate(
        mission: Mission,
        fleet_robot_id: Optional[str] = None,
    ) -> OmronInOrbitMission:
        """Translate an InOrbit mission to Omron FlowCore format.

        Args:
            mission: The original InOrbit mission
            fleet_robot_id: The FlowCore robot namekey to assign missions to
        
        Returns:
            Translated mission with Omron-specific step types
        """
        if not mission.definition.steps:
            raise ValueError("Mission has no steps to translate")

        translated_steps: OmronStepsList = []
        mission_params: dict = {}

        for i, step in enumerate(mission.definition.steps):
            if isinstance(step, MissionStepRunAction) and step.action_id == "gotoGoals":
                if (
                    not step.arguments or
                    "goals" not in step.arguments or
                    not isinstance(step.arguments["goals"], str)
                ):
                    raise ValueError("gotoGoals action must have argument 'goals' as a comma-separated string of goal names")
                
                goals = [g.strip() for g in step.arguments["goals"].split(",") if g.strip()]
                
                if not goals:
                    raise ValueError("gotoGoals action must have at least one non-empty goal name")
                
                omron_step = InOrbitToOmronTranslator._create_omron_job_step(
                    goals=goals,
                    mission_id=mission.id,
                    robot_id=mission.robot_id,
                    fleet_robot_id=fleet_robot_id,
                    params=mission_params.copy(),
                    start_index=i,
                    timeout_secs=step.timeout_secs
                )
                translated_steps.append(omron_step)

                continue

            if isinstance(step, MissionStepSetData):
                InOrbitToOmronTranslator._extract_mission_params(step, mission_params)
                translated_steps.append(step)
                continue

            translated_steps.append(step)

        translated_definition = MissionDefinitionOmron(
            label=mission.definition.label,
            steps=translated_steps,
        )

        translated_mission = OmronInOrbitMission(
            id=mission.id,
            robot_id=mission.robot_id,
            definition=translated_definition,
            arguments=mission.arguments,
        )

        logger.debug(
            "Translated mission %s: %d original steps -> %d translated steps",
            mission.id,
            len(mission.definition.steps),
            len(translated_steps),
        )

        return translated_mission

    @staticmethod
    def _create_omron_job_step(
        goals: list[str],
        mission_id: str,
        robot_id: str,
        fleet_robot_id: Optional[str],
        params: dict,
        start_index: int = 0,
        timeout_secs: Optional[int] = None,
    ) -> MissionStepExecuteOmronJob:
        """Create an Omron job step from gotoGoals action.

        Args:
            goals: List of consecutive goal steps to convert
            mission_id: Parent InOrbit mission ID
            robot_id: InOrbit robot ID
            fleet_robot_id: Target fleet robot namekey
            params: Additional mission parameters
            start_index: Index of the gotoGoals action in the original mission steps
        
        Returns:
            MissionStepExecuteOmronJob containing the Omron job details
        """
        # Generate deterministic job ID segment based on step index
        # This allows matching the job on mission resume
        job_id = f"{mission_id}_{start_index}"

        omron_details: list[JobRequestDetail] = []
        
        # Default priority
        priority = params.get("priority", 10)

        for i, goal in enumerate(goals):
            goal_name = goal
            
            # First goal must be a pickup goal
            if i == 0:
                detail = JobRequestDetail(
                    pickupGoal=goal_name,
                    priority=priority
                )
            else:
                detail = JobRequestDetail(
                    dropoffGoal=goal_name,
                    priority=priority
                )
            omron_details.append(detail)

        # Build label
        if len(goals) == 1:
            label = goals[0]
        else:
            label = f"Navigate through {len(goals)} goals"

        return MissionStepExecuteOmronJob(
            label=label,
            omron_job_details=omron_details,
            robot_id=robot_id,
            fleet_robot_id=fleet_robot_id,
            job_id=job_id,
            timeout_secs=timeout_secs,
        )

    @staticmethod
    def _extract_mission_params(step: MissionStepSetData, params: dict) -> None:
        """Extract Omron-specific parameters from SetData step.

        Recognized keys:
        - omron_priority: Job priority (int)

        Args:
            step: SetData step to extract from
            params: Dictionary to update with extracted parameters
        """
        data = step.data

        if "omron_priority" in data:
            value = data["omron_priority"]
            if isinstance(value, (int, float, str)):
                try:
                    params["priority"] = int(value)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid priority value: {value}")
