# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for FlowCore connector extended features."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from inorbit_omron_connector.src.connector import OmronConnector
from inorbit_omron_connector.src.config.models import (
    FlowCoreConnectorConfig,
    FlowCoreRobotConfig,
    FlowCoreConfig,
)
from inorbit_connector.models import MapConfig
from inorbit_omron_connector.src.omron.robot_manager import RobotManager


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    return FlowCoreConnectorConfig(
        connector_type="flowcore",
        update_freq=1.0,
        connector_config=FlowCoreConfig(
            url="http://mock",
            username="user",
            password="password",
            arcl_password="omron",
            use_mock=True,
        ),
        fleet=[
            FlowCoreRobotConfig(
                robot_id="robot_1", fleet_robot_id="AMR_1", map_id="map1"
            )
        ],
        maps={
            "map1": MapConfig(
                file="tests/data/map.png",
                map_id="map1",
                map_label="Map 1",
                origin_x=0.0,
                origin_y=0.0,
                resolution=0.05,
            )
        },
    )


@pytest.mark.asyncio
async def test_get_robot_pose_uses_map_id(mock_config):
    """Test that get_robot_pose uses the configured map ID."""
    robot_manager = RobotManager(mock_config)

    # Mock data with pose
    # RobotManager expects objects with a .value attribute
    robot_manager._robot_data = {
        "AMR_1": {
            "PoseX": MagicMock(value="1000"),
            "PoseY": MagicMock(value="2000"),
            "PoseTh": MagicMock(value="90"),
        }
    }

    pose = robot_manager.get_robot_pose("AMR_1")

    assert pose is not None
    assert pose["frame_id"] == "map_frame"
    assert pose["x"] == 1.0
    assert pose["y"] == 2.0


@pytest.mark.asyncio
async def test_stop_action_triggers_api(mock_config):
    """Test that Stop action triggers the API stop method."""
    with patch(
        "inorbit_omron_connector.src.connector.RobotManager"
    ) as MockManager, patch(
        "inorbit_omron_connector.src.connector.OmronMissionExecutor"
    ) as MockExecutor, patch(
        "inorbit_edge.robot.RobotSession.connect"
    ):

        mock_manager_instance = MockManager.return_value
        mock_manager_instance.api.stop = AsyncMock(return_value=True)
        # Mock _get_fleet_robot_id logic if needed, but it uses config directly

        MockExecutor.return_value

        connector = OmronConnector(mock_config)
        # Inject the mock manager into the connector
        connector.robot_manager = mock_manager_instance

        # Manually trigger command handler
        # command_name="custom_command", args=["stop", {"reason": "test"}]
        args = ["stop", {"reason": "test"}]
        options = {"result_function": MagicMock()}

        await connector._inorbit_robot_command_handler(
            "robot_1", "customCommand", args, options
        )

        # Verify stop was called
        mock_manager_instance.api.stop.assert_called_once()
        call_args = mock_manager_instance.api.stop.call_args[0][0]
        assert call_args["robot"] == "AMR_1"
        assert call_args["cancelReason"] == "test"

        # Verify success result
        options["result_function"].assert_called_with(
            "0"
        )  # CommandResultCode.SUCCESS is 0
