
# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from inorbit_omron_connector.src.mission.behavior_tree import (
    CreateOmronJobNode,
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
async def test_wait_node_detects_dropoff_completion():
    """Verify WaitForOmronJobCompletionNode detects completion of a Dropoff job."""
    
    # Setup Mocks
    mock_api = MagicMock()
    mock_api.get_job_details_by_namekey = AsyncMock(return_value=None) # No existing job
    mock_api.create_dropoff = AsyncMock(return_value=True) # Success
    
    mock_tracker = MagicMock()
    mock_tracker.get_job_state = AsyncMock()
    
    shared_memory = MockSharedMemory()
    job_id = "mission_dropoff_1"
    
    # Context (same for both nodes)
    context = OmronBehaviorTreeBuilderContext(
        api_client=mock_api,
        robot_id_to_fleet_id={"r1": "fleet_r1"},
        mission_tracking=mock_tracker,
        shared_memory=shared_memory, 
        mission=MagicMock(robot_id="r1")
    )
    
    # 1. Create Dropoff Job
    # Mock step data for Dropoff (single goal)
    step_mock = MagicMock()
    step_mock.job_id = job_id
    step_mock.omron_job_details = [MagicMock(dropoffGoal="Station_A", priority=10)]
    step_mock.fleet_robot_id = "fleet_r1" # Required for use_dropoff logic
    
    create_node = CreateOmronJobNode(context=context, step=step_mock)
    await create_node.execute()
    
    # Verify namekey is stored
    stored_namekey = shared_memory.get(SharedMemoryKeys.OMRON_NAME_KEY)
    assert stored_namekey == job_id
    
    # 2. Wait for Completion
    wait_node = WaitForOmronJobCompletionNode(context=context)
    
    # Mock tracker response for the stored key
    mock_tracker.get_job_state.side_effect = lambda j_id, k: OmronJobStatus.COMPLETED if k == stored_namekey else None
    
    # Execute wait 
    # If it fails to use the correct key, it will timeout or mock will panic if strict
    await asyncio.wait_for(wait_node.execute(), timeout=1.0)
    
    # Verify get_job_state was called with the correct key
    mock_tracker.get_job_state.assert_awaited_with(job_id, stored_namekey)
