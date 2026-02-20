
# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from inorbit_omron_connector.src.omron.mock_client import MockOmronClient

@pytest.mark.asyncio
async def test_create_dropoff_uses_provided_namekey():
    """Verify create_dropoff uses the namekey from the request if provided."""
    
    mock_client = MockOmronClient()
    mock_client._robots = {"r1": {"status": "Available", "subStatus": "Unallocated", "jobs": []}}
    await mock_client.connect()
    
    job_id = "mission_123"
    expected_namekey = job_id
    
    request = {
        "jobId": job_id,
        "namekey": expected_namekey,
        "goal": "Station_A",
        "robot": "r1",
        "priority": 10
    }
    
    await mock_client.create_dropoff(request)
    
    # Check what key was stored in the DB
    stored_job = mock_client._jobs_db.get(expected_namekey)
    assert stored_job is not None, f"Job was not stored with key {expected_namekey}"
    assert stored_job["namekey"] == expected_namekey
    
    # Check that it wasn't stored as the default Job-{id}
    wrong_key = f"Job-{job_id}"
    assert wrong_key not in mock_client._jobs_db, f"Job should NOT be stored with key {wrong_key}"
