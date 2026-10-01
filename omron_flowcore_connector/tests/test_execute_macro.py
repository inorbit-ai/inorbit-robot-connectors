# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
import asyncio
from unittest.mock import MagicMock, patch
from inorbit_connector.commands import CommandFailure

from inorbit_omron_connector.src.connector import OmronConnector
from inorbit_omron_connector.src.omron.robot_manager import RobotManager


@pytest.mark.asyncio
async def test_execute_macro(connector_config, mock_omron, mock_arcl):
    with patch("inorbit_edge.robot.RobotSession.connect"), \
         patch("inorbit_omron_connector.src.connector.OmronMissionExecutor", autospec=True):

        manager = RobotManager(connector_config, api_client=mock_omron)
        connector = OmronConnector(connector_config, robot_manager=manager)

        await manager._update_fleet_state()
        await manager._update_fleet_details()

        options = {"result_function": MagicMock()}

        await connector._inorbit_robot_command_handler(
            "Robot1", "customCommand", ["executeMacro", {"macro": "Macro1"}], options
        )

        options["result_function"].assert_called_with("0")
        await asyncio.sleep(0.2)
        assert any(cmd == "executeMacro Macro1" for cmd in mock_arcl.received_data)


@pytest.mark.asyncio
async def test_execute_macro_requires_name(connector_config, mock_omron, mock_arcl):
    with patch("inorbit_edge.robot.RobotSession.connect"), \
         patch("inorbit_omron_connector.src.connector.OmronMissionExecutor", autospec=True):

        manager = RobotManager(connector_config, api_client=mock_omron)
        connector = OmronConnector(connector_config, robot_manager=manager)

        await manager._update_fleet_state()
        await manager._update_fleet_details()

        options = {"result_function": MagicMock()}

        with pytest.raises(CommandFailure):
            await connector._inorbit_robot_command_handler(
                "Robot1", "customCommand", ["executeMacro", {}], options
            )

        await asyncio.sleep(0.2)
        assert not any("executeMacro" in cmd for cmd in mock_arcl.received_data)
