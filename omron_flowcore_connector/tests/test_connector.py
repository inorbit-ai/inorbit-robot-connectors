# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest_asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from inorbit_omron_connector import __version__
from inorbit_omron_connector.src.connector import OmronConnector
from inorbit_omron_connector.src.config.models import FlowCoreConnectorConfig, FlowCoreConfig
from inorbit_omron_connector.src.omron.robot_manager import RobotManager
from inorbit_omron_connector.src.omron.mock_client import MockOmronClient

@pytest.fixture
def mock_executor_cls():
    with patch("inorbit_omron_connector.src.connector.OmronMissionExecutor", autospec=True) as mock, \
         patch("inorbit_edge.robot.RobotSession.connect"):
        yield mock

@pytest.mark.asyncio
async def test_connector_initialization(connector_config, mock_robot_manager, mock_executor_cls):
    connector = OmronConnector(connector_config, robot_manager=mock_robot_manager)
    mock_executor_instance = mock_executor_cls.return_value

    await connector._connect()
    
    # Verify initialize called
    mock_executor_instance.initialize.assert_called_once()
    
    await connector._disconnect()
    
    # Verify shutdown called
    mock_executor_instance.shutdown.assert_called_once()


@pytest.fixture
def connector_config():
    omron_config = FlowCoreConfig(url="https://mock.com", password="mock", arcl_password="omron")
    return FlowCoreConnectorConfig(
        connector_type="flowcore",
        connector_config=omron_config,
        account_id="test_account",
        location_id="test_location",
        api_key="test_key",
        fleet=[{"robot_id": "Robot1", "fleet_robot_id": "Robot1_FlowCore"}]
    )

@pytest_asyncio.fixture
async def mock_robot_manager(connector_config):
    client = MockOmronClient()
    await client.connect()
    # Seed using the FlowCore ID (NameKey). 
    client.seed_robot("Robot1_FlowCore", x=1000.0, y=2000.0, theta=180.0, battery=80.0, status="Available", sub_status="Unallocated")
    
    manager = RobotManager(connector_config, api_client=client)
    # Manually populate cache for test stability (bypassing async poll timing issues)
    await manager._update_fleet_state()
    await manager._update_fleet_details()
    
    return manager

@pytest.mark.asyncio
async def test_connector_execution_loop(connector_config, mock_robot_manager, mock_executor_cls):
    connector = OmronConnector(connector_config, robot_manager=mock_robot_manager)
    
    # Mock publish methods to avoid FleetConnector internal logic/network calls
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_key_values = MagicMock()
    connector.publish_robot_odometry = MagicMock()
    
    await connector._execution_loop()
    
    # Verify pose published (converted to meters and radians)
    # x=1.0m, y=2.0m, theta=180deg -> pi rad
    
    connector.publish_robot_pose.assert_called_once()
    call_args = connector.publish_robot_pose.call_args
    # call_args[0] are args, call_args[1] are kwargs
    assert call_args[0][0] == "Robot1" # robot_id
    assert call_args[1]["x"] == 1.0
    assert call_args[1]["y"] == 2.0
    assert abs(call_args[1]["yaw"] - 3.14159) < 0.001
    assert call_args[1]["frame_id"] == "map_frame"

    # Verify key values
    # Battery 80.0 -> 0.8
    # Status: Unallocated -> IDLE
    connector.publish_robot_key_values.assert_called() # might be called multiple times?
    # Check calls
    kv_call = connector.publish_robot_key_values.call_args
    assert kv_call[0][0] == "Robot1"
    assert kv_call[1]["battery_percent"] == 80.0
    assert kv_call[1]["status"] == "IDLE"
    assert kv_call[1]["connector_version"] == __version__

@pytest.mark.asyncio
async def test_connector_command_handler_stop(connector_config, mock_robot_manager, mock_executor_cls):
    connector = OmronConnector(connector_config, robot_manager=mock_robot_manager)
    
    # Mock api.stop
    mock_robot_manager.api.stop = AsyncMock(return_value=True)
    
    options = {"result_function": MagicMock()}
    
    await connector._inorbit_robot_command_handler(
        "Robot1", 
        "customCommand", 
        ["stop", {"reason": "Test Stop"}], 
        options
    )
    
    mock_robot_manager.api.stop.assert_called_once()
    job_cancel = mock_robot_manager.api.stop.call_args[0][0]
    
    # Verify it targeted the fleet_robot_id ("Robot1_FlowCore")
    assert job_cancel["robot"] == "Robot1_FlowCore"
    assert job_cancel["cancelReason"] == "Test Stop"
    
    options["result_function"].assert_called_with("0")

