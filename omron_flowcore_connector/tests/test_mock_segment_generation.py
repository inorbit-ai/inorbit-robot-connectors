# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from inorbit_omron_connector.src.omron.mock_client import MockOmronClient
from inorbit_omron_connector.src.omron.models import JobRequest, JobRequestDetail

@pytest.mark.asyncio
async def test_dynamic_segment_generation_list():
    """Verify get_job_segment_list returns correct dynamic segments."""
    client = MockOmronClient()
    await client.connect()
    
    # 1. Test Dropoff Job
    dropoff_job_id = "Dropoff123"
    await client.create_dropoff({
        "jobId": dropoff_job_id,
        "goal": "Station_A",
        "robot": "Robo1",
        "priority": 5
    })
    
    segments = await client.get_job_segment_list(f"Job-{dropoff_job_id}")
    assert len(segments) == 1
    assert segments[0]["segmentType"] == "Dropoff"
    assert segments[0]["goalName"] == "Station_A"
    assert segments[0]["seq"] == 1
    
    # 2. Test Multi-Goal Job
    multi_job_id = "Multi456"
    details = [
        JobRequestDetail(dropoffGoal="Goal_1"),
        JobRequestDetail(dropoffGoal="Goal_2")
    ]
    job_req = JobRequest(
        jobId=multi_job_id,
        namekey=f"Job-{multi_job_id}",
        details=details,
        defaultPriority=1
    )
    
    await client.create_job(job_req.model_dump())
    
    segments = await client.get_job_segment_list(f"Job-{multi_job_id}")
    assert len(segments) == 2
    assert segments[0]["goalName"] == "Goal_1"
    assert segments[0]["seq"] == 1
    assert segments[1]["goalName"] == "Goal_2"
    assert segments[1]["seq"] == 2
    
    # 3. Test Fallback (Unknown Job)
    segments = await client.get_job_segment_list("UnknownJob")
    assert len(segments) == 3 # Default fallback list has 3 items
