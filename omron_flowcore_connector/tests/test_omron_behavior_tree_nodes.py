# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from inorbit_omron_connector.src.mission.behavior_tree import (
    WaitForOmronJobCompletionNode, 
    SharedMemoryKeys, 
    OmronBehaviorTreeBuilderContext,
    OmronJobStatus
)

class MockSharedMemory:
    def __init__(self):
        self._data = {}
    
    def get(self, key):
        return self._data.get(key)
    
    def set(self, key, value):
        self._data[key] = value

    def add(self, key, value):
        self._data[key] = value

@pytest.mark.asyncio
async def test_wait_node_uses_stored_namekey():
    """Verify WaitForOmronJobCompletionNode uses OMRON_NAME_KEY if available."""
    
    # Mock Tracker
    mock_tracker = MagicMock()
    mock_tracker.get_job_state = AsyncMock()
    
    # Mock Context & SharedMemory
    shared_memory = MockSharedMemory()
    job_id = "mission_123_0"
    stored_namekey = "mission_123_0"
    
    shared_memory.set(SharedMemoryKeys.OMRON_JOB_ID_KEY, job_id)
    shared_memory.set(SharedMemoryKeys.OMRON_NAME_KEY, stored_namekey)
    
    context = OmronBehaviorTreeBuilderContext(
        api_client=MagicMock(),
        robot_id_to_fleet_id={},
        mission_tracking=mock_tracker,
        shared_memory=shared_memory, 
        mission=MagicMock(robot_id="r1")
    )
    
    node = WaitForOmronJobCompletionNode(context=context)
    
    # Setup mock tracker to return Completed
    mock_tracker.get_job_state.return_value = OmronJobStatus.COMPLETED
    
    # Run
    await asyncio.wait_for(node.execute(), timeout=1.0)
    
    # Verify calls
    # It should have called get_job_state with stored_namekey
    mock_tracker.get_job_state.assert_awaited_with(job_id, stored_namekey)
    
    # Verify it didn't call with the fallback "Job-..." or raw ID if the first one succeeded
    assert mock_tracker.get_job_state.call_count == 1
