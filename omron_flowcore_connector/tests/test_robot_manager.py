# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from inorbit_omron_connector.src.omron.robot_manager import RobotManager
from inorbit_omron_connector.src.config.models import FlowCoreConfig
from inorbit_omron_connector.src.omron.mock_client import MockOmronClient
from inorbit_omron_connector.src.omron.models import RobotResponse

@pytest.fixture
def manager_config():
    omron_config = FlowCoreConfig(url="http://test", password="pass", arcl_password="arcl")
    config = MagicMock()
    config.connector_config = omron_config
    config.connector_config.arcl_port = 7171
    config.connector_config.arcl_password = "arcl-pass"
    config.fleet = [] 
    config.maps = {}
    return config

@pytest_asyncio.fixture
async def robot_manager(manager_config):
    client = MockOmronClient()
    await client.connect()
    # Seed a robot
    client.seed_robot("Robot1", x=1000.0, y=2000.0, theta=90.0, battery=50.0)
    
    manager = RobotManager(manager_config, api_client=client)
    return manager

@pytest.mark.asyncio
async def test_update_fleet_state(robot_manager):
    await robot_manager._update_fleet_state()
    
    # Check if robot is discovered and added to cache
    assert "Robot1" in robot_manager._robot_data
    assert robot_manager._robot_data["Robot1"]["summary"].namekey == "Robot1"

@pytest.mark.asyncio
async def test_update_fleet_details(robot_manager):
    # Ensure cache entry exists
    robot_manager._robot_data["Robot1"] = {}
    robot_manager._robot_data["Robot2"] = {}

    # Seed two robots
    robot_manager.api.seed_robot("Robot1", x=1000.0, y=2000.0, theta=90.0, battery=50.0)
    robot_manager.api.seed_robot("Robot2", x=3000.0, y=4000.0, theta=180.0, battery=80.0)
    
    await robot_manager._update_fleet_details()
    
    # Check Robot1
    data1 = robot_manager._robot_data["Robot1"]
    assert data1["PoseX"].value == 1000.0
    assert data1["PoseY"].value == 2000.0
    assert data1["StateOfCharge"].value == 50.0

    # Check Robot2
    data2 = robot_manager._robot_data["Robot2"]
    assert data2["PoseX"].value == 3000.0
    assert data2["PoseY"].value == 4000.0 
    assert data2["StateOfCharge"].value == 80.0

@pytest.mark.asyncio
async def test_getters(robot_manager):
    # Manually populate cache to simulate polling
    summary = RobotResponse(namekey="Robot1", status="Available", subStatus="Unallocated", upd={"millis": 1000}) 
    robot_manager._robot_data["Robot1"] = {
        "summary": summary,
        "PoseX": MagicMock(value=1000.0),
        "PoseY": MagicMock(value=2000.0),
        "PoseTh": MagicMock(value=180.0),
        "StateOfCharge": MagicMock(value=75.0)
    }
    
    # Test pose
    pose = robot_manager.get_robot_pose("Robot1")
    assert pose["x"] == 1.0
    assert pose["y"] == 2.0
    assert abs(pose["yaw"] - 3.14159) < 0.001
    
    # Test key values
    kv = robot_manager.get_robot_key_values("Robot1")
    assert kv["battery_percent"] == 75.0
    assert kv["status"] == "IDLE"

@pytest.mark.asyncio
async def test_start_stop(robot_manager):
    # Spy on _run_in_loop
    with patch.object(robot_manager, '_run_in_loop') as mock_run:
        await robot_manager.start()
        # Should start fleet update loop
        assert mock_run.call_count >= 1
        
    await robot_manager.stop()
    assert robot_manager._running_tasks == []

@pytest.mark.asyncio
async def test_arcl_client_lifecycle(robot_manager):
    # Mock ArclClient
    with patch("inorbit_omron_connector.src.omron.robot_manager.ArclClient") as mock_arcl_class:
        mock_client = AsyncMock()
        mock_arcl_class.return_value = mock_client
        
        # 1. Error when no robot/IP
        with pytest.raises(ValueError, match="Robot Unknown not found"):
            await robot_manager.get_arcl_client("Unknown")
            
        # Seed robot without IP
        robot_manager._robot_data["Robot1"] = {}
        with pytest.raises(ValueError, match="IP address not available"):
            await robot_manager.get_arcl_client("Robot1")
            
        # 2. Lazy init
        robot_manager._robot_data["Robot1"]["robot_ip"] = "1.2.3.4"
        client1 = await robot_manager.get_arcl_client("Robot1")
        
        assert client1 == mock_client
        mock_arcl_class.assert_called_with(
            host="1.2.3.4", port=7171, password="arcl-pass", connection_timeout=5
        )
        mock_client.connect.assert_called_once()
        
        # 3. Reuse
        client2 = await robot_manager.get_arcl_client("Robot1")
        assert client1 == client2
        assert mock_arcl_class.call_count == 1
        
        # 4. IP Change
        # Prepare a second mock for the new IP
        mock_client2 = AsyncMock()
        mock_arcl_class.return_value = mock_client2
        
        summary_new_ip = RobotResponse(
            namekey="Robot1", 
            ipAddress="5.6.7.8", 
            status="Available", 
            subStatus="Unallocated", 
            upd={"millis": 1000}
        )
        
        # Update fleet state (manually to avoid background loop timing issues)
        # We need to mock get_fleet_state to return our summary
        robot_manager.api.get_fleet_state = AsyncMock(return_value=[summary_new_ip])
        
        await robot_manager._update_fleet_state()
        
        # Original client should have been disconnected and removed
        mock_client.disconnect.assert_called()
        assert "Robot1" not in robot_manager._arcl_clients
        
        # 5. Get again with new IP
        client3 = await robot_manager.get_arcl_client("Robot1")
        assert client3 == mock_client2
        mock_arcl_class.assert_called_with(
            host="5.6.7.8", port=7171, password="arcl-pass", connection_timeout=5
        )
        mock_client2.connect.assert_called_once()
        
        # 6. Stop disconnects all
        await robot_manager.stop()
        mock_client2.disconnect.assert_called()
        assert robot_manager._arcl_clients == {}
