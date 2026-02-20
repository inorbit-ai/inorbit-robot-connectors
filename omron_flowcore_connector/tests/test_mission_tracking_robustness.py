# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT


import pytest
import time
import unittest.mock
from inorbit_omron_connector.src.mission.tracking import OmronMissionTracking, OmronJobStatus
from inorbit_omron_connector.src.omron.mock_client import MockOmronClient

@pytest.fixture
def mock_omron_client():
    client = unittest.mock.AsyncMock(spec=MockOmronClient)
    # Ensure nested async mocks are clean
    client.get_job_details_by_namekey = unittest.mock.AsyncMock()
    client.get_job_details_by_job_id = unittest.mock.AsyncMock()
    return client

@pytest.mark.asyncio
async def test_get_job_state_staleness_check(mock_omron_client):
    """Verify that get_job_state forces API call when cache is stale."""
    # Setup
    mission_tracking = OmronMissionTracking(mock_omron_client)
    job_key = "test-job-stale"
    
    # Pre-populate cache with a stale status
    mission_tracking._job_status_cache[job_key] = "InProgress"
    mission_tracking._job_last_update[job_key] = time.time() - 10.0 # 10 seconds ago (older than 5s TTL)
    
    # Mock API to return a NEW status
    mock_job_details = {
        "namekey": job_key,
        "status": "Completed", # API says Completed
        "lastAssignedRobot": "robot-1"
    }
    mock_omron_client.get_job_details_by_job_id.return_value = mock_job_details
    
    # Call get_job_state
    status = await mission_tracking.get_job_state(job_key, job_key)
    
    # Should have called API
    mock_omron_client.get_job_details_by_job_id.assert_called_with(job_key)
    # Should return the NEW status from API
    assert status == OmronJobStatus.COMPLETED
    # Cache should be updated
    assert mission_tracking._job_status_cache[job_key] == OmronJobStatus.COMPLETED
    
@pytest.mark.asyncio
async def test_get_job_state_cache_hit(mock_omron_client):
    """Verify that get_job_state uses cache when fresh."""
    # Setup
    mission_tracking = OmronMissionTracking(mock_omron_client)
    job_key = "test-job-fresh"
    
    # Pre-populate cache with a fresh status
    mission_tracking._job_status_cache[job_key] = "InProgress"
    mission_tracking._job_last_update[job_key] = time.time() - 1.0 # 1 second ago (fresh)
    
    # Call get_job_state
    status = await mission_tracking.get_job_state(job_key, job_key)
    
    # Should NOT have called API
    mock_omron_client.get_job_details_by_namekey.assert_not_called()
    assert status == "InProgress"

@pytest.mark.asyncio
async def test_normalize_status_enum():
    """Verify status normalization logic."""
    mission_tracking = OmronMissionTracking(unittest.mock.Mock())
    assert mission_tracking._normalize_status("InProgress") == OmronJobStatus.IN_PROGRESS
    assert mission_tracking._normalize_status("inprogress") == OmronJobStatus.IN_PROGRESS # Case insensitive check
    assert mission_tracking._normalize_status("Completed") == OmronJobStatus.COMPLETED
    assert mission_tracking._normalize_status("RandomStatus") == "RandomStatus" # Fallback
