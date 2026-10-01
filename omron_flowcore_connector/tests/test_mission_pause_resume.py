# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Pausing and resuming a mission step that runs an Omron job."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from inorbit_edge_executor.behavior_tree import (
    CANCEL_TASK_PAUSE_MESSAGE,
    NODE_STATE_ERROR,
    build_tree_from_object,
)
from inorbit_edge_executor.datatypes import MissionRuntimeOptions, MissionRuntimeSharedMemory
from inorbit_edge_executor.exceptions import TaskPausedException

from inorbit_omron_connector.src.mission.behavior_tree import (
    OmronBehaviorTreeBuilderContext,
    OmronNodeFromStepBuilder,
)
from inorbit_omron_connector.src.mission.datatypes import MissionStepExecuteOmronJob
from inorbit_omron_connector.src.mission.tracking import OmronJobStatus
from inorbit_omron_connector.src.omron.models import JobRequestDetail

JOB_ID = "mission1_0"

STEP = MissionStepExecuteOmronJob(
    label="Go to Goal1",
    omron_job_details=[JobRequestDetail(pickupGoal="Goal1", priority=10)],
    robot_id="robot1",
    fleet_robot_id="Robot1_FlowCore",
    job_id=JOB_ID,
    timeout_secs=60,
)


def _context(api_client, tracker, shared_memory):
    """A builder context like the worker pool's, around the given mocks and memory."""
    context = OmronBehaviorTreeBuilderContext(
        api_client=api_client,
        robot_id_to_fleet_id={"robot1": "Robot1_FlowCore"},
        mission_tracking=tracker,
        shared_memory=shared_memory,
        mission=MagicMock(robot_id="robot1", arguments=None),
        error_context={},
        options=MissionRuntimeOptions(),
    )
    context.mt = AsyncMock()
    return context


@pytest.fixture
def job_step():
    """The subtree a translated gotoGoals step builds, with its API and tracker mocked."""
    api_client = MagicMock()
    api_client.create_dropoff = AsyncMock(return_value=True)
    api_client.stop = AsyncMock(return_value=True)

    tracker = MagicMock()
    tracker.get_job_state = AsyncMock(return_value=OmronJobStatus.IN_PROGRESS)

    context = _context(api_client, tracker, MissionRuntimeSharedMemory())
    node = OmronNodeFromStepBuilder(context).visit_execute_omron_job(STEP)
    # The worker pool freezes the memory once the tree is built
    context.shared_memory.freeze()
    return node, context


async def _pause(node):
    """Run the step until it is waiting on the job, then pause it the way a worker does."""
    task = asyncio.create_task(node.execute())
    await asyncio.sleep(0.05)
    task.cancel(CANCEL_TASK_PAUSE_MESSAGE)
    with pytest.raises(TaskPausedException):
        await task


def _resume(node, context):
    """Rebuild the paused step from its persisted state, as resuming a mission does."""
    memory = MissionRuntimeSharedMemory.model_validate(
        json.loads(context.shared_memory.model_dump_json())
    )
    memory.frozen = False
    resumed = _context(context.api_client, context.mission_tracking, memory)
    node = build_tree_from_object(resumed, json.loads(json.dumps(node.dump_object())))
    memory.freeze()
    return node, resumed


@pytest.mark.asyncio
async def test_pausing_a_job_step_cancels_the_job_and_reports_paused(job_step):
    """FlowCore cannot hold a job, so a paused mission has to cancel it. Without this the
    AMR keeps driving to its goal and the mission is reported as completed."""
    node, context = job_step

    await _pause(node)

    context.api_client.stop.assert_awaited_once()
    assert context.api_client.stop.await_args.args[0]["robot"] == "Robot1_FlowCore"
    context.mt.pause.assert_awaited_once()


@pytest.mark.asyncio
async def test_resuming_a_paused_job_step_creates_a_new_job(job_step):
    """The job the pause cancelled is not coming back, so the resumed step creates another
    one under a new key instead of polling the cancelled one and failing at once."""
    node, context = job_step

    await _pause(node)
    node, context = _resume(node, context)
    context.mission_tracking.get_job_state.return_value = OmronJobStatus.COMPLETED
    await asyncio.wait_for(node.execute(), timeout=2)

    namekeys = [
        call.args[0]["namekey"] for call in context.api_client.create_dropoff.await_args_list
    ]
    assert namekeys == [JOB_ID, f"{JOB_ID}_r1"]
    assert context.mission_tracking.get_job_state.await_args.args == (
        f"{JOB_ID}_r1",
        f"{JOB_ID}_r1",
    )


@pytest.mark.asyncio
async def test_a_failed_job_step_keeps_its_error_for_the_mission(job_step):
    """The mission's abort node reports whatever is in the error context, so a step that
    handles its own errors has to leave the real message there and not an empty state."""
    node, context = job_step
    context.mission_tracking.get_job_state.return_value = OmronJobStatus.FAILED

    await asyncio.wait_for(node.execute(), timeout=2)

    assert node.state == NODE_STATE_ERROR
    assert "ended with state: Failed" in context.error_context["last_error"]
    assert "ended with state: Failed" in node.last_error
