# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
import asyncio
from unittest.mock import MagicMock, patch

from inorbit_omron_connector.src.connector import OmronConnector
from inorbit_omron_connector.src.omron.robot_manager import RobotManager

@pytest.mark.asyncio
async def test_dock_undock_shutdown(connector_config, mock_omron, mock_arcl):
    # 1. Setup Connector
    # We need to patch RobotSession.connect to avoid real network attempts
    with patch("inorbit_edge.robot.RobotSession.connect"), \
         patch("inorbit_omron_connector.src.connector.OmronMissionExecutor", autospec=True):
        
        manager = RobotManager(connector_config, api_client=mock_omron)
        connector = OmronConnector(connector_config, robot_manager=manager)
        
        # Populate cache
        await manager._update_fleet_state()
        await manager._update_fleet_details()

        options = {"result_function": MagicMock()}

        # 2. Test Dock
        await connector._inorbit_robot_command_handler(
            "Robot1", 
            "customCommand", 
            ["dock", {}], 
            options
        )
        
        options["result_function"].assert_called_with("0")
        await asyncio.sleep(0.2)
        assert any("dock" in cmd for cmd in mock_arcl.received_data)

        # 3. Test Undock
        mock_arcl.received_data.clear() # Clear previous commands
        options["result_function"].reset_mock()
        
        await connector._inorbit_robot_command_handler(
            "Robot1", 
            "customCommand", 
            ["undock", {}], 
            options
        )
        
        options["result_function"].assert_called_with("0")
        await asyncio.sleep(0.2)
        assert any("undock" in cmd for cmd in mock_arcl.received_data)

        # 4. Test Shutdown
        mock_arcl.received_data.clear()
        options["result_function"].reset_mock()

        await connector._inorbit_robot_command_handler(
            "Robot1", 
            "customCommand", 
            ["shutdown", {}], 
            options
        )

        options["result_function"].assert_called_with("0")
        await asyncio.sleep(0.2)
        assert any("shutdown" in cmd for cmd in mock_arcl.received_data)
