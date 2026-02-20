# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
import asyncio
from inorbit_omron_connector.src.omron.mock_client import MockOmronClient
from inorbit_omron_connector.src.omron.models import JobRequest, JobRequestDetail

@pytest.mark.asyncio
async def test_mock_simulation_dispatch():
    """Verify that a pending job is dispatched to an available robot."""
    client = MockOmronClient()
    await client.connect()
    
    # 1. Seed an available robot
    client.seed_robot("robot1", status="Available", sub_status="Unallocated")
    
    # 2. Create a job (M type)
    job_request = JobRequest(
        namekey="job1",
        jobId="mission1",
        defaultPriority=True,
        details=[
            JobRequestDetail(pickupGoal="StationA", priority=10),
            JobRequestDetail(dropoffGoal="StationB", priority=10)
        ]
    )
    await client.create_job(job_request.model_dump())
    
    # 3. Simulate client behavior: connecting to stream drives the simulation
    # We need to consume the stream to let the internal loop run
    stream = client.get_job_stream()
    
    async def consume_stream():
        async for _ in stream:
            pass
            
    task = asyncio.create_task(consume_stream())
    
    # Allow some time for the background dispatch logic to run
    # The simulation loop waits 1s between iterations and 2s for startup
    await asyncio.sleep(4.0)
    
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    
    # Check directly in the DB if dispatch happened
    job_data = await client.get_job_details_by_namekey("job1")
    assert job_data["lastAssignedRobot"] == "robot1"
    assert job_data["status"] == "InProgress"

@pytest.mark.asyncio
async def test_mock_segment_generation_M():
    """Verify segment generation for Multi-goal job."""
    client = MockOmronClient()
    await client.connect()
    client.seed_robot("robot1", status="Available")
    
    job_request = JobRequest(
        namekey="job_M",
        jobId="mission_M",
        defaultPriority=True,
        details=[
            JobRequestDetail(pickupGoal="PointA", priority=10),
            JobRequestDetail(dropoffGoal="PointB", priority=10)
        ]
    )
    await client.create_job(job_request.model_dump())
    
    # Generate segments
    segments = await client.get_job_segment_list("job_M")
    assert len(segments) == 2
    assert segments[0]["goalName"] == "PointA"
    assert segments[0]["segmentType"] == "Pickup"
    assert segments[1]["goalName"] == "PointB"
    assert segments[1]["segmentType"] == "Dropoff"

@pytest.mark.asyncio
async def test_mock_segment_generation_D():
    """Verify segment generation for Dropoff job."""
    client = MockOmronClient()
    await client.connect()
    
    await client.create_dropoff({
        "jobId": "mission_D",
        "goal": "PointC",
        "robot": "robot1",
        "priority": 10
    })
    
    segments = await client.get_job_segment_list("Job-mission_D")
    assert len(segments) == 1
    assert segments[0]["goalName"] == "PointC"
    assert segments[0]["segmentType"] == "Dropoff"
