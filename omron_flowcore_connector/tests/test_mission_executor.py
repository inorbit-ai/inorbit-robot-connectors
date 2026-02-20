# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from inorbit_connector.connector import CommandResultCode
from inorbit_omron_connector.src.mission.executor import OmronMissionExecutor, CustomScripts

@pytest.fixture
def mock_executor_dependencies():
    api = MagicMock()
    omron_api = AsyncMock()
    robot_id_to_fleet = {"r1": "fleet_r1"}
    
    return api, omron_api, robot_id_to_fleet

@pytest.mark.asyncio
async def test_handle_execute_mission(mock_executor_dependencies):
    api, omron_api, mapping = mock_executor_dependencies
    
    with patch("inorbit_omron_connector.src.mission.executor.OmronWorkerPool") as MockPool, \
         patch("inorbit_omron_connector.src.mission.executor.get_db", AsyncMock()):
        
        pool_instance = MockPool.return_value
        pool_instance.start = AsyncMock()
        pool_instance.submit_work = AsyncMock()
        
        executor = OmronMissionExecutor(
            api=api, omron_api_client=omron_api, robot_id_to_fleet_id=mapping
        )
        await executor.initialize()
        
        options = {"result_function": MagicMock()}
        script_args = {
            "missionId": "m1",
            "missionDefinition": '{"steps": []}',
            "missionArgs": {},
            "options": {},
            "robotId": "r1"
        }
        
        handled = await executor.handle_command(
            "r1", CustomScripts.EXECUTE_MISSION_ACTION, script_args, options
        )
        
        assert handled is True
        pool_instance.submit_work.assert_awaited_once()
        options["result_function"].assert_called_with(CommandResultCode.SUCCESS)

@pytest.mark.asyncio
async def test_handle_cancel_mission(mock_executor_dependencies):
    api, omron_api, mapping = mock_executor_dependencies
    
    with patch("inorbit_omron_connector.src.mission.executor.OmronWorkerPool") as MockPool, \
         patch("inorbit_omron_connector.src.mission.executor.get_db", AsyncMock()):
        
        pool_instance = MockPool.return_value
        pool_instance.start = AsyncMock()
        pool_instance.abort_mission = MagicMock(return_value=True)
        
        executor = OmronMissionExecutor(
            api=api, omron_api_client=omron_api, robot_id_to_fleet_id=mapping
        )
        await executor.initialize()
        
        options = {"result_function": MagicMock()}
        script_args = {"missionId": "m1"}
        
        handled = await executor.handle_command(
            "r1", CustomScripts.CANCEL_MISSION_ACTION, script_args, options
        )
        
        assert handled is True
        pool_instance.abort_mission.assert_called_with("m1")
        options["result_function"].assert_called_with(CommandResultCode.SUCCESS)

@pytest.mark.asyncio
async def test_handle_update_mission_pause(mock_executor_dependencies):
    api, omron_api, mapping = mock_executor_dependencies
    
    with patch("inorbit_omron_connector.src.mission.executor.OmronWorkerPool") as MockPool, \
         patch("inorbit_omron_connector.src.mission.executor.get_db", AsyncMock()):
         
        pool_instance = MockPool.return_value
        pool_instance.start = AsyncMock()
        pool_instance.pause_mission = AsyncMock()
        
        executor = OmronMissionExecutor(
            api=api, omron_api_client=omron_api, robot_id_to_fleet_id=mapping
        )
        await executor.initialize()
        
        options = {"result_function": MagicMock()}
        script_args = {"missionId": "m1", "action": "pause"}
        
        handled = await executor.handle_command(
            "r1", CustomScripts.UPDATE_MISSION_ACTION, script_args, options
        )
        
        assert handled is True
        pool_instance.pause_mission.assert_awaited_with("m1")
        options["result_function"].assert_called_with(CommandResultCode.SUCCESS)
