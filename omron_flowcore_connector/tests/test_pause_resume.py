# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
import asyncio
from unittest.mock import MagicMock, patch

from inorbit_omron_connector.src.connector import OmronConnector
from inorbit_omron_connector.src.omron.robot_manager import RobotManager

@pytest.mark.asyncio
async def test_connector_pause_resume_with_state_update(connector_config, mock_omron, mock_arcl):
    # 1. Setup Connector
    # We need to patch RobotSession.connect to avoid real network attempts
    with patch("inorbit_edge.robot.RobotSession.connect"), \
         patch("inorbit_omron_connector.src.connector.OmronMissionExecutor", autospec=True):
        
        manager = RobotManager(connector_config, api_client=mock_omron)
        connector = OmronConnector(connector_config, robot_manager=manager)
        
        # 2. Setup ARCL Callbacks to update MockOmronClient state
        def abds_handler(msg):
            mock_omron._robots["Robot1_FlowCore"]["subStatus"] = "Driving"
        
        def abdc_handler(msg):
            mock_omron._robots["Robot1_FlowCore"]["subStatus"] = "Available"

        mock_arcl.register_command_handler("abds", abds_handler)
        mock_arcl.register_command_handler("abdc", abdc_handler)

        options = {"result_function": MagicMock()}

        # Populate cache
        await manager._update_fleet_state()
        await manager._update_fleet_details()

        # 3. Test Pause
        await connector._inorbit_robot_command_handler(
            "Robot1", 
            "customCommand", 
            ["pauseRobot", {}], 
            options
        )
        
        # Verify result called
        options["result_function"].assert_called_with("0")
        
        # Wait for ARCL processing and state update
        await asyncio.sleep(0.5)
        
        # Verify ARCL server received the command
        assert any("abds" in cmd for cmd in mock_arcl.received_data)
        
        # Verify state in mock_omron updated
        # We need to manually trigger update_fleet_state since the polling loop is suppressed in this test style
        await manager._update_fleet_state()
        kv = manager.get_vendor_key_values("Robot1_FlowCore")
        assert kv["status"] == "BUSY" # Driving maps to BUSY

        # 4. Test Resume
        options["result_function"].reset_mock()
        await connector._inorbit_robot_command_handler(
            "Robot1", 
            "customCommand", 
            ["resumeRobot", {}], 
            options
        )
        
        options["result_function"].assert_called_with("0")
        
        await asyncio.sleep(0.5)
        
        # Verify ARCL server received abdc and go
        assert any("abdc" in cmd for cmd in mock_arcl.received_data)
        assert any("go" == cmd for cmd in mock_arcl.received_data)
        
        # Verify state in mock_omron updated back to IDLE
        await manager._update_fleet_state()
        kv = manager.get_vendor_key_values("Robot1_FlowCore")
        assert kv["status"] == "IDLE" # Available maps to IDLE
