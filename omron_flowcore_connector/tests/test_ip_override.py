# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import AsyncMock, patch

from inorbit_omron_connector.src.omron.robot_manager import RobotManager
from inorbit_omron_connector.src.config.models import FlowCoreConnectorConfig, FlowCoreConfig, FlowCoreRobotConfig
from inorbit_omron_connector.src.omron.mock_client import MockOmronClient

@pytest.mark.asyncio
async def test_ip_override_priority():
    # 1. Setup config with override
    omron_config = FlowCoreConfig(
        url="http://test", 
        password="pass", 
        arcl_password="omron"
    )
    
    robot_config = FlowCoreRobotConfig(
        robot_id="Robot1", 
        fleet_robot_id="Robot1_FlowCore",
        ip_address="10.0.0.50" # OVERRIDE
    )
    
    config = FlowCoreConnectorConfig(
        connector_type="flowcore",
        connector_config=omron_config,
        account_id="acc",
        location_id="loc",
        api_key="key",
        fleet=[robot_config]
    )
    
    # 2. Setup mock client with DIFFERENT IP
    client = MockOmronClient()
    await client.connect()
    # Mock return IP is 127.0.0.1
    client.seed_robot("Robot1_FlowCore", ip_address="127.0.0.1")
    
    manager = RobotManager(config, api_client=client)
    
    # Check initial state (should be pre-populated from config)
    assert manager._robot_data["Robot1_FlowCore"]["robot_ip"] == "10.0.0.50"
    
    # 3. Simulate polling
    await manager._update_fleet_state()
    # Should still be 10.0.0.50 despite mock return 127.0.0.1
    assert manager._robot_data["Robot1_FlowCore"]["robot_ip"] == "10.0.0.50"
    
    await manager._update_fleet_details()
    # Should still be 10.0.0.50 despite RobotIP DataStore fetch
    assert manager._robot_data["Robot1_FlowCore"]["robot_ip"] == "10.0.0.50"
    
    # 4. Verify ARCL client uses the override
    # Inject AsyncMock for connect manually on the instance
    with patch("inorbit_omron_connector.src.omron.robot_manager.ArclClient") as mock_arcl_class:
        mock_instance = AsyncMock()
        mock_arcl_class.return_value = mock_instance
        
        await manager.get_arcl_client("Robot1_FlowCore")
        
        mock_arcl_class.assert_called_with(
            host="10.0.0.50", 
            port=7171, 
            password="omron",
            connection_timeout=5
        )
        mock_instance.connect.assert_called_once()
