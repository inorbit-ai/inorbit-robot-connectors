# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Omron FlowCore-specific mission datatypes for mission translation."""

from __future__ import annotations

from typing import List, Optional, Union, override

from pydantic import Field

from inorbit_edge_executor.datatypes import (
    MissionDefinition,
    MissionStep,
    MissionStepRunAction,
    MissionStepSetData,
    MissionStepWait,
    MissionStepWaitUntil,
    MissionStepIf,
)
from inorbit_edge_executor.mission import Mission
from inorbit_omron_connector.src.omron.models import JobRequestDetail


class MissionStepExecuteOmronJob(MissionStep):
    """Custom mission step that executes a translated Omron Job.

    This step type is produced by the translator when the gotoGoals action is used.
    """

    omron_job_details: List[JobRequestDetail] = Field(description="The Omron job details to execute")
    robot_id: str = Field(description="InOrbit robot ID for session lookup")
    fleet_robot_id: Optional[str] = Field(
        default=None, description="Target fleet robot ID for mission assignment"
    )
    job_id: str = Field(description="Unique Job ID for tracking")
    timeout_secs: Optional[int] = Field(
        default=None, description="Timeout in seconds for the job"
    )

    @override
    def accept(self, visitor):
        """Visitor pattern for behavior tree construction and task extraction."""
        if hasattr(visitor, "visit_execute_omron_job"):
            return visitor.visit_execute_omron_job(self)
        # Fallback for task extraction and other generic visitors
        if hasattr(visitor, "collect_step"):
            return visitor.collect_step(self)
        return None


# Type alias for Omron-specific steps list
OmronStepsList = List[
    Union[
        MissionStepSetData,
        MissionStepRunAction,
        MissionStepWait,
        MissionStepWaitUntil,
        MissionStepIf,
        MissionStepExecuteOmronJob,
    ]
]


class MissionDefinitionOmron(MissionDefinition):
    """Mission definition that supports Omron-specific step types.

    Extends the base MissionDefinition to include MissionStepExecuteOmronJob
    which is produced during translation.
    """

    steps: OmronStepsList  # type: ignore[assignment]


class OmronInOrbitMission(Mission):
    """Mission subclass for Omron FlowCore that uses Omron-specific definition.

    This class is used after translation to hold the converted mission
    with Omron-specific step types.
    """

    definition: MissionDefinitionOmron  # type: ignore[assignment]
