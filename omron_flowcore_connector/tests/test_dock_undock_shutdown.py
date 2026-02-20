# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
import asyncio
import pytest_asyncio
from unittest.mock import MagicMock, patch

from inorbit_omron_connector.src.connector import OmronConnector
from inorbit_omron_connector.src.config.models import FlowCoreConnectorConfig, FlowCoreConfig
from inorbit_omron_connector.src.omron.robot_manager import RobotManager
from inorbit_omron_connector.src.omron.mock_client import MockOmronClient
from inorbit_omron_connector.src.omron.mock_arcl_server import MockArclServer

@pytest_asyncio.fixture
async def mock_arcl(unused_tcp_port):
    server = MockArclServer(port=unused_tcp_port)
    await server.start()
    yield server
    await server.stop()

@pytest.fixture
def connector_config(unused_tcp_port):
    omron_config = FlowCoreConfig(
        url="https://mock.com", 
        password="mock",
        arcl_port=unused_tcp_port,
        arcl_password="omron"
    )
    return FlowCoreConnectorConfig(
        connector_type="flowcore",
        connector_config=omron_config,
        account_id="test_account",
        location_id="test_location",
        api_key="test_key",
        fleet=[{"robot_id": "Robot1", "fleet_robot_id": "Robot1_FlowCore"}]
    )

@pytest_asyncio.fixture
async def mock_omron():
    client = MockOmronClient()
    await client.connect()
    client.seed_robot("Robot1_FlowCore", status="Available", sub_status="Available", ip_address="127.0.0.1")
    return client

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
