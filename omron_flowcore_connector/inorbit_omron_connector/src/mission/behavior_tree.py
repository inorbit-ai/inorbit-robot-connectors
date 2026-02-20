# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Custom behavior tree nodes for Omron FlowCore mission execution."""

from __future__ import annotations

import asyncio
import logging
from enum import StrEnum
from typing import Any, Optional, override
import time

from inorbit_edge_executor.behavior_tree import (
    BehaviorTree,
    BehaviorTreeBuilderContext,
    BehaviorTreeSequential,
    MissionAbortedNode,
    NodeFromStepBuilder,
    register_accepted_node_types,
)
from inorbit_edge_executor.inorbit import MissionStatus

from inorbit_omron_connector.src.mission.datatypes import (
    MissionStepExecuteOmronJob,
)
from inorbit_omron_connector.src.mission.tracking import OmronJobStatus
from inorbit_omron_connector.src.omron.api_client import OmronApiClient
from inorbit_omron_connector.src.omron.models import (
    JobRequest,
    JobCancelByJobNamekey,
    JobCancelByRobotName,
    DropoffJob
)

logger = logging.getLogger(__name__)


class SharedMemoryKeys(StrEnum):
    """Keys for Omron-specific shared memory entries."""

    OMRON_JOB_ID_KEY = "omron_job_id_key"
    OMRON_NAME_KEY = "omron_name_key"
    OMRON_JOB_STATUS = "omron_job_status"
    OMRON_ERROR_MESSAGE = "omron_error_message"


# Polling interval for job state checks
OMRON_POLLING_INTERVAL_SECS = 1.0


class OmronBehaviorTreeBuilderContext(BehaviorTreeBuilderContext):
    """Extended context for Omron FlowCore behavior tree construction."""

    def __init__(
        self,
        api_client: OmronApiClient,
        robot_id_to_fleet_id: dict[str, str],
        mission_tracking: Any = None, # Avoid cyclic import hint by using Any or generic
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._api_client = api_client
        self._robot_id_to_fleet_id = robot_id_to_fleet_id
        self._mission_tracking = mission_tracking

    @property
    def api_client(self) -> OmronApiClient:
        return self._api_client

    @property
    def robot_id_to_fleet_id(self) -> dict[str, str]:
        return self._robot_id_to_fleet_id
        
    @property
    def mission_tracking(self) -> Any:
        return self._mission_tracking

    def get_fleet_robot_id(self, robot_id: str) -> Optional[str]:
        """Get Fleet robot ID (namekey) for an InOrbit robot ID."""
        return self._robot_id_to_fleet_id.get(robot_id)


class CreateOmronJobNode(BehaviorTree):
    """Creates an Omron job via the FlowCore API."""

    def __init__(
        self,
        context: OmronBehaviorTreeBuilderContext,
        step: MissionStepExecuteOmronJob,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._api_client = context.api_client
        self._shared_memory = context.shared_memory
        self._step = step
        self._mission_tracking = context.mission_tracking

        # Declare shared memory keys
        self._shared_memory.add(SharedMemoryKeys.OMRON_JOB_ID_KEY, None)
        self._shared_memory.add(SharedMemoryKeys.OMRON_NAME_KEY, None)
        self._shared_memory.add(SharedMemoryKeys.OMRON_JOB_STATUS, "")
        self._shared_memory.add(SharedMemoryKeys.OMRON_ERROR_MESSAGE, None)

    @override
    async def _execute(self):
        job_id = self._step.job_id
        # We construct a namekey for the job. FlowCore usually expects unique namekeys.
        namekey = job_id

        logger.info(f"Creating Omron Job: {job_id}")

        # 2. Create Job (Dropoff or Standard)
        try:
            success = False
            
            # Use Dropoff if it's a single goal and we have a target robot
            # This enables strict assignment for "Drop a Pin" equivalent
            # We also verify that dropoffGoal is present, as generic JobRequest checks might produce pickupGoal
            use_dropoff = (
                len(self._step.omron_job_details) == 1 
                and self._step.fleet_robot_id is not None
            )

            self._mission_tracking.set_inorbit_mission_current_robot_job_id(self._step.fleet_robot_id, job_id)

            if use_dropoff:
                # Use Dropoff Job for strict assignment
                detail = self._step.omron_job_details[0]
                fleet_robot_id = self._step.fleet_robot_id
                
                dropoff_job = DropoffJob(
                    namekey=namekey,
                    jobId=job_id,
                    priority=detail.priority or 10,
                    goal=detail.dropoffGoal or detail.pickupGoal,
                    robot=fleet_robot_id
                )
                logger.info(f"Sending Dropoff strategy for robot {fleet_robot_id}")
                success = await self._api_client.create_dropoff(dropoff_job.model_dump())
            else:
                # Standard JobRequest (Fleet Managed)
                job_request = JobRequest(
                    namekey=namekey,
                    jobId=job_id,
                    defaultPriority=True,
                    details=self._step.omron_job_details
                )
                success = await self._api_client.create_job(job_request.model_dump())

            if not success:
                error_msg = f"Failed to create Omron job {job_id}"
                logger.error(error_msg)
                self._shared_memory.set(SharedMemoryKeys.OMRON_ERROR_MESSAGE, error_msg)
                raise RuntimeError(error_msg)

            logger.info(f"Created Omron job with ID: {job_id}")
            self._shared_memory.set(SharedMemoryKeys.OMRON_JOB_ID_KEY, job_id)
            self._shared_memory.set(SharedMemoryKeys.OMRON_NAME_KEY, namekey)

        except Exception as e:
            error_msg = f"Exception creating Omron job: {e}"
            logger.error(error_msg)
            self._shared_memory.set(SharedMemoryKeys.OMRON_ERROR_MESSAGE, error_msg)
            raise RuntimeError(error_msg) from e

    @classmethod
    def from_object(cls, context, step, **kwargs):
        if isinstance(step, dict):
            step = MissionStepExecuteOmronJob.model_validate(step)
        return CreateOmronJobNode(context, step, **kwargs)


class CleanupOmronJobNode(BehaviorTree):
    """Cancels the active Omron job during cleanup (e.g. on pause)."""

    def __init__(self, context: OmronBehaviorTreeBuilderContext, **kwargs):
        super().__init__(**kwargs)
        self._api_client = context.api_client
        self._shared_memory = context.shared_memory
        self._robot_id_to_fleet_id = context.robot_id_to_fleet_id
        self._mission = context.mission

    @override
    async def _execute(self):
        job_namekey = self._shared_memory.get(SharedMemoryKeys.OMRON_NAME_KEY)
        if not job_namekey:
            return

        logger.info(f"Cleaning up Omron Job {job_namekey} (cancelling)")

        # Cancel by robot to be safe
        robot_id = getattr(self._mission, "robot_id", None)
        fleet_robot_id = self._robot_id_to_fleet_id.get(robot_id) if robot_id else None

        cancel_payload = {}
        if fleet_robot_id:
            cancel_payload = JobCancelByRobotName(
                robot=fleet_robot_id,
                cancelReason="InOrbit Mission Cleanup/Pause"
            ).model_dump()
        else:
            cancel_payload = JobCancelByJobNamekey(
                jobNamekey=job_namekey,
                cancelReason="InOrbit Mission Cleanup/Pause"
            ).model_dump()

        try:
            await self._api_client.stop(cancel_payload)
            logger.info(f"Cancelled Omron Job {job_namekey} during cleanup")
        except Exception as e:
            logger.warning(f"Failed to cancel Omron job during cleanup: {e}")

    @classmethod
    def from_object(cls, context, **kwargs):
        return CleanupOmronJobNode(context, **kwargs)

class WaitForOmronJobCompletionNode(BehaviorTree):
    """Polls for job completion status using MissionTracking."""

    # Wait for tracking updates
    POLL_INTERVAL = 1.0

    def __init__(
        self,
        context: OmronBehaviorTreeBuilderContext,
        timeout_secs: Optional[int] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._tracker = getattr(context, "mission_tracking", None)
        self._shared_memory = context.shared_memory
        self._mission = context.mission
        self._timeout_secs = timeout_secs
        
        if not self._tracker:
             logger.warning("MissionTracking not available in context. WaitForOmronJobCompletionNode might fail.")

    @override
    async def _execute(self):
        job_id = self._shared_memory.get(SharedMemoryKeys.OMRON_JOB_ID_KEY)
        namekey = self._shared_memory.get(SharedMemoryKeys.OMRON_NAME_KEY)


        if not job_id:
            logger.error("No job ID found in shared memory")
            raise RuntimeError("No job ID to wait for")

        if not namekey:
            logger.error("No namekey found in shared memory")
            raise RuntimeError("No namekey to wait for")

        if not self._tracker:
             raise RuntimeError("MissionTracking not initialized")

        logger.info(f"Waiting for completion of job {job_id} via MissionTracking")

        start_time = time.time()

        while True:
            if self._timeout_secs and time.time() - start_time > self._timeout_secs:
                raise RuntimeError(f"Job {namekey} timed out after {self._timeout_secs} seconds")
            
            status = await self._tracker.get_job_state(job_id, namekey)
            
            if status:
                self._shared_memory.set(SharedMemoryKeys.OMRON_JOB_STATUS, status)
                
                if status in [
                    OmronJobStatus.COMPLETED
                ]:
                    logger.info(f"Job {namekey} completed successfully")
                    return
                
                if status in [
                    OmronJobStatus.FAILED,
                    OmronJobStatus.CANCELLED,
                    OmronJobStatus.CANCELED,
                    OmronJobStatus.INTERRUPTED
                ]:
                    error_msg = f"Job {namekey} ended with state: {status}"
                    logger.error(error_msg)
                    self._shared_memory.set(SharedMemoryKeys.OMRON_ERROR_MESSAGE, error_msg)
                    raise RuntimeError(error_msg)
                
                # If "Pending", "InProgress", "Waiting" continue waiting
            
            await asyncio.sleep(self.POLL_INTERVAL)

class OmronMissionAbortedNode(MissionAbortedNode):
    """Extended abort node that also cancels the Omron Job."""

    def __init__(
        self,
        context: OmronBehaviorTreeBuilderContext,
        status: MissionStatus = MissionStatus.error,
        **kwargs,
    ):
        super().__init__(context, status, **kwargs)
        self._api_client = context.api_client
        self._shared_memory = context.shared_memory
        self._robot_id_to_fleet_id = context.robot_id_to_fleet_id
        self._mission = context.mission
        self._status = status
        self._error_context = context.error_context

    @override
    async def _execute(self):
        error_message = self._shared_memory.get(SharedMemoryKeys.OMRON_ERROR_MESSAGE)
        if error_message:
            logger.error(f"Mission aborted due to error: {error_message}")

        job_namekey = self._shared_memory.get(SharedMemoryKeys.OMRON_NAME_KEY)
        robot_id = getattr(self._mission, "robot_id", None)
        fleet_robot_id = self._robot_id_to_fleet_id.get(robot_id) if robot_id else None
        
        cancel_payload = {}
        if fleet_robot_id:
            cancel_payload = JobCancelByRobotName(
                robot=fleet_robot_id,
                cancelReason="InOrbit Mission Aborted"
            ).model_dump()
        elif job_namekey:
            cancel_payload = JobCancelByJobNamekey(
                jobNamekey=job_namekey,
                cancelReason="InOrbit Mission Aborted"
            ).model_dump()

        try:
            await self._api_client.stop(cancel_payload)
            logger.info(f"Sent cancel request to Omron with status: {self._status}")
            logger.info(f"Error context: {self._error_context}")
        except Exception as e:
            logger.warning(f"Failed to cancel Omron job: {e}")
        
        await super()._execute()

    @classmethod
    def from_object(cls, context, status, **kwargs):
        return OmronMissionAbortedNode(context, MissionStatus(status), **kwargs)


class OmronNodeFromStepBuilder(NodeFromStepBuilder):
    """Step builder that handles Omron-specific step types."""

    def __init__(self, context: OmronBehaviorTreeBuilderContext):
        super().__init__(context)
        self._omron_context = context

    def visit_execute_omron_job(self, step: MissionStepExecuteOmronJob) -> BehaviorTree:
        """Build behavior tree for executing an Omron job."""
        sequence = BehaviorTreeSequential(label=step.label)

        sequence.add_node(
            CreateOmronJobNode(
                self._omron_context,
                step,
                label=f"Create Omron Job '{step.label}'",
            )
        )

        sequence.add_node(
            WaitForOmronJobCompletionNode(
                self._omron_context,
                timeout_secs=step.timeout_secs,
                label=f"Wait for Omron Job '{step.label}'",
            )
        )

        return sequence

# Register types
omron_node_types = [
    CreateOmronJobNode,
    WaitForOmronJobCompletionNode,
    OmronMissionAbortedNode,
    CleanupOmronJobNode,
]
register_accepted_node_types(omron_node_types)
