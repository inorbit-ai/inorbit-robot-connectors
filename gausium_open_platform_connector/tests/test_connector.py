# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for `gausium_open_platform_connector.src.connector`."""

from __future__ import annotations

import io
import logging
import math
import threading
from unittest.mock import AsyncMock, MagicMock, Mock, call

import pytest
from inorbit_connector.commands import CommandFailure, CommandResultCode
from inorbit_connector.connector import FleetConnector
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND, COMMAND_MESSAGE, COMMAND_NAV_GOAL
from PIL import Image

from gausium_open_platform_connector import __version__
from gausium_open_platform_connector.src.commands import (
    RemoteNavigationCommandType,
    RemoteTaskCommandType,
)
from gausium_open_platform_connector.src.config.models import GausiumOpenPlatformConnectorConfig
from gausium_open_platform_connector.src.connector import GausiumOpenPlatformConnector
from gausium_open_platform_connector.src.key_values import build_key_values

ROBOT_ID = "robot-alpha"
SN_1 = "GS000-0000-000-0001"
SN_2 = "GS000-0000-000-0002"
MAP_ID = "map-1"


def sample_status() -> dict:
    """Realistic v1 batch status entry (modeled on sanitized API captures)."""
    return {
        "serialNumber": SN_1,
        "name": f"robots/{SN_1}",
        "position": {"latitude": 0, "longitude": 0, "angle": 0},
        "taskState": "IDLE",
        "online": True,
        "speedKilometerPerHour": 3.6,
        "battery": {"charging": False, "powerPercentage": 87, "soc": 87, "soh": "HEALTHY"},
        "emergencyStop": {"enabled": False},
        "localizationInfo": {
            "localizationState": "SUCCEED",
            "map": {"id": MAP_ID, "name": "floor_1"},
            "mapPosition": {"x": 100.0, "y": 200.0, "angle": 90.0},
        },
        "navStatus": "NAVI_IDLE",
        "latestReportTime": "1786912977060",
    }


def sample_status_v2() -> dict:
    return {
        "serialNumber": SN_1,
        "taskState": "IDLE",
        "online": True,
        "localizationInfo": {
            "localizationState": "SUCCEED",
            "map": {"id": MAP_ID, "name": "floor_1", "version": "maps/x/versions/y"},
        },
        "currentTask": {"taskInstanceId": ""},
    }


@pytest.fixture()
def config() -> GausiumOpenPlatformConnectorConfig:
    return GausiumOpenPlatformConnectorConfig(
        api_key="test-api-key",
        connector_type="gausium_open_platform",
        connector_config={
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
            "access_key_secret": "test-access-key",
        },
        fleet=[
            {"robot_id": ROBOT_ID, "serial_number": SN_1, "cameras": []},
            {"robot_id": "robot-beta", "serial_number": SN_2, "cameras": []},
        ],
        _env_file=None,
    )


@pytest.fixture()
def session() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def connector(monkeypatch, config, session) -> GausiumOpenPlatformConnector:
    """Connector with only FleetConnector.__init__ stubbed, so its own __init__ runs."""

    def fake_init(self, cfg, **kwargs):
        self.config = cfg
        self._logger = logging.getLogger("test-connector")
        self._FleetConnector__fleet_lock = threading.RLock()
        self._FleetConnector__background_tasks = []

    monkeypatch.setattr(FleetConnector, "__init__", fake_init)
    connector = GausiumOpenPlatformConnector(config)
    connector._client = AsyncMock()
    connector._get_robot_session = Mock(return_value=session)
    connector.publish_robot_pose = Mock()
    connector.publish_robot_odometry = Mock()
    connector.publish_robot_key_values = Mock()
    return connector


@pytest.fixture()
def robot_state(connector):
    """The cached poller state for ROBOT_ID, primed with realistic data."""
    state = connector._poller.get_state(SN_1)
    state.status = sample_status()
    state.status_v2 = sample_status_v2()
    state.robot_data = {
        "serialNumber": SN_1,
        "displayName": "Robot Alpha",
        "modelFamilyCode": "S",
        "modelTypeCode": "Scrubber 50H",
        "softwareVersion": "5.10.2",
    }
    state.api_connected = True
    return state


# --- Publishing ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_canonical_key_values_are_published(connector, robot_state) -> None:
    await connector._execution_loop()

    connector.publish_robot_key_values.assert_called_once()
    args, kwargs = connector.publish_robot_key_values.call_args
    assert args == (ROBOT_ID,)
    assert kwargs == {
        **build_key_values(robot_state.status, robot_state.status_v2),
        "api_connected": True,
        "connector_version": __version__,
        "display_name": "Robot Alpha",
        "model_family": "S",
        "model_type": "Scrubber 50H",
        "software_version": "5.10.2",
    }
    # The raw vendor status is no longer splatted into the key-values
    assert "taskState" not in kwargs
    assert kwargs["task_state"] == "idle"
    assert kwargs["battery_pct"] == 0.87


@pytest.mark.asyncio
async def test_pose_is_converted_and_published(connector, robot_state) -> None:
    await connector._execution_loop()

    connector.publish_robot_pose.assert_called_once_with(
        ROBOT_ID,
        x=100.0 * 0.05,
        y=200.0 * 0.05,
        yaw=math.radians(90.0),
        frame_id=MAP_ID,
    )
    connector.publish_robot_odometry.assert_called_once_with(ROBOT_ID, linear_speed=1.0)


@pytest.mark.asyncio
async def test_map_resolution_config_moves_pose(monkeypatch, config, session) -> None:
    config.connector_config.map_resolution = 0.1

    def fake_init(self, cfg, **kwargs):
        self.config = cfg
        self._logger = logging.getLogger("test-connector")
        self._FleetConnector__fleet_lock = threading.RLock()
        self._FleetConnector__background_tasks = []

    monkeypatch.setattr(FleetConnector, "__init__", fake_init)
    connector = GausiumOpenPlatformConnector(config)
    connector._get_robot_session = Mock(return_value=session)
    connector.publish_robot_pose = Mock()
    connector.publish_robot_odometry = Mock()
    connector.publish_robot_key_values = Mock()
    state = connector._poller.get_state(SN_1)
    state.status = sample_status()
    state.status_v2 = sample_status_v2()

    await connector._execution_loop()

    assert connector.publish_robot_pose.call_args.kwargs["x"] == 100.0 * 0.1
    assert connector.publish_robot_pose.call_args.kwargs["y"] == 200.0 * 0.1


@pytest.mark.asyncio
async def test_pose_skipped_when_coordinates_missing(connector, robot_state) -> None:
    # Lost robots publish a map id but no coordinates
    del robot_state.status["localizationInfo"]["mapPosition"]["x"]

    await connector._execution_loop()

    connector.publish_robot_pose.assert_not_called()
    connector.publish_robot_key_values.assert_called_once()


@pytest.mark.asyncio
async def test_robot_without_status_is_skipped(connector) -> None:
    await connector._execution_loop()

    connector.publish_robot_key_values.assert_not_called()
    connector.publish_robot_pose.assert_not_called()


# --- Vendor-offline mirror ----------------------------------------------------


@pytest.mark.asyncio
async def test_vendor_offline_mirror(connector, robot_state, session) -> None:
    # Initial online=True is not re-sent (connect already published it)
    await connector._execution_loop()
    session._send_robot_status.assert_not_called()
    assert connector._is_fleet_robot_online(ROBOT_ID) is True

    # Vendor goes offline: status is mirrored once and publishing stops
    robot_state.status["online"] = False
    connector.publish_robot_key_values.reset_mock()
    await connector._execution_loop()
    session._send_robot_status.assert_called_once_with(online=False)
    connector.publish_robot_key_values.assert_not_called()
    assert connector._is_fleet_robot_online(ROBOT_ID) is False

    # Still offline: the offline status is re-asserted every tick (the edge SDK re-sends
    # a retained online=True on MQTT reconnects), still no publishing
    await connector._execution_loop()
    assert session._send_robot_status.call_args_list == [call(online=False), call(online=False)]
    connector.publish_robot_key_values.assert_not_called()

    # Vendor comes back: status is mirrored and publishing resumes
    robot_state.status["online"] = True
    await connector._execution_loop()
    session._send_robot_status.assert_called_with(online=True)
    connector.publish_robot_key_values.assert_called_once()
    assert connector._is_fleet_robot_online(ROBOT_ID) is True


# --- Command handler ----------------------------------------------------------


def command_options() -> dict:
    return {"result_function": Mock()}


@pytest.mark.asyncio
async def test_submit_task_success(connector, robot_state) -> None:
    options = command_options()

    await connector._inorbit_robot_command_handler(
        ROBOT_ID,
        COMMAND_CUSTOM_COMMAND,
        ["submit_task", ["area_id", "area-1", "cleaning_mode", "CLEAN"]],
        options,
    )

    connector._client.create_nosite_task.assert_awaited_once_with(
        SN_1,
        task_name="InOrbit task",
        map_id=MAP_ID,
        map_name="floor_1",
        area_id="area-1",
        cleaning_mode="清洗",
        loop=False,
    )
    options["result_function"].assert_called_once_with(CommandResultCode.SUCCESS)


@pytest.mark.asyncio
async def test_submit_task_invalid_cleaning_mode(connector, robot_state) -> None:
    with pytest.raises(CommandFailure, match="Invalid arguments"):
        await connector._inorbit_robot_command_handler(
            ROBOT_ID,
            COMMAND_CUSTOM_COMMAND,
            ["submit_task", ["area_id", "area-1", "cleaning_mode", "SCRUB"]],
            command_options(),
        )
    connector._client.create_nosite_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_task_without_map_data(connector, robot_state) -> None:
    robot_state.status["localizationInfo"] = {}

    with pytest.raises(CommandFailure, match="No map data available"):
        await connector._inorbit_robot_command_handler(
            ROBOT_ID,
            COMMAND_CUSTOM_COMMAND,
            ["submit_task", ["area_id", "area-1", "cleaning_mode", "CLEAN"]],
            command_options(),
        )


@pytest.mark.asyncio
async def test_task_command_success(connector, robot_state) -> None:
    options = command_options()
    await connector._inorbit_robot_command_handler(
        ROBOT_ID,
        COMMAND_CUSTOM_COMMAND,
        ["task_command", ["command", "PAUSE_TASK"]],
        options,
    )

    connector._client.send_remote_task_command.assert_awaited_once_with(
        SN_1, RemoteTaskCommandType.PAUSE_TASK
    )
    options["result_function"].assert_called_once_with(CommandResultCode.SUCCESS)


@pytest.mark.asyncio
async def test_task_command_invalid(connector, robot_state) -> None:
    with pytest.raises(CommandFailure, match="Invalid command"):
        await connector._inorbit_robot_command_handler(
            ROBOT_ID,
            COMMAND_CUSTOM_COMMAND,
            ["task_command", ["command", "START_TASK"]],
            command_options(),
        )
    connector._client.send_remote_task_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_navigate_success(connector, robot_state) -> None:
    options = command_options()
    await connector._inorbit_robot_command_handler(
        ROBOT_ID,
        COMMAND_CUSTOM_COMMAND,
        ["navigate", ["command", "CROSS_NAVIGATE", "position", "Maintenance"]],
        options,
    )

    connector._client.send_remote_navigation_command.assert_awaited_once_with(
        SN_1,
        RemoteNavigationCommandType.CROSS_NAVIGATE,
        {"startNavigationParameter": {"map": "floor_1", "position": "Maintenance"}},
    )
    options["result_function"].assert_called_once_with(CommandResultCode.SUCCESS)


@pytest.mark.asyncio
async def test_navigate_invalid_command(connector, robot_state) -> None:
    with pytest.raises(CommandFailure, match="Invalid arguments"):
        await connector._inorbit_robot_command_handler(
            ROBOT_ID,
            COMMAND_CUSTOM_COMMAND,
            ["navigate", ["command", "FLY", "position", "Maintenance"]],
            command_options(),
        )
    connector._client.send_remote_navigation_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unavailable", ["api_disconnected", "vendor_offline"], ids=["api", "vendor"]
)
async def test_commands_fail_when_robot_unavailable(connector, robot_state, unavailable) -> None:
    if unavailable == "api_disconnected":
        robot_state.api_connected = False
    else:
        robot_state.status["online"] = False

    with pytest.raises(CommandFailure, match="Robot is not available"):
        await connector._inorbit_robot_command_handler(
            ROBOT_ID,
            COMMAND_CUSTOM_COMMAND,
            ["task_command", ["command", "PAUSE_TASK"]],
            command_options(),
        )


@pytest.mark.asyncio
async def test_unknown_custom_script_is_left_to_user_scripts(connector, robot_state) -> None:
    options = command_options()

    await connector._inorbit_robot_command_handler(
        ROBOT_ID, COMMAND_CUSTOM_COMMAND, ["my_script.sh", []], options
    )

    options["result_function"].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("command_name", [COMMAND_NAV_GOAL, COMMAND_MESSAGE])
async def test_unsupported_commands_fail(connector, robot_state, command_name) -> None:
    with pytest.raises(CommandFailure, match="is not supported"):
        await connector._inorbit_robot_command_handler(
            ROBOT_ID, command_name, [], command_options()
        )


# --- Map fetching ---------------------------------------------------------------


def make_png() -> bytes:
    """1x2 PNG: red on top, blue on the bottom."""
    image = Image.new("RGB", (1, 2))
    image.putpixel((0, 0), (255, 0, 0))
    image.putpixel((0, 1), (0, 0, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_fetch_robot_map_flips_image(connector, robot_state) -> None:
    connector._client.get_map_image.return_value = make_png()

    result = await connector.fetch_robot_map(ROBOT_ID, MAP_ID)

    connector._client.get_map_image.assert_awaited_once_with(
        SN_1, MAP_ID, "floor_1", "maps/x/versions/y"
    )
    assert result is not None
    assert result.map_id == MAP_ID
    assert result.map_label == "floor_1"
    assert result.origin_x == 0.0
    assert result.origin_y == 0.0
    assert result.resolution == 0.05
    flipped = Image.open(io.BytesIO(result.image))
    assert flipped.getpixel((0, 0)) == (0, 0, 255)
    assert flipped.getpixel((0, 1)) == (255, 0, 0)


@pytest.mark.asyncio
async def test_fetch_robot_map_mismatched_frame_id(connector, robot_state) -> None:
    result = await connector.fetch_robot_map(ROBOT_ID, "some-other-map-id")

    assert result is None
    connector._client.get_map_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_robot_map_download_failure(connector, robot_state) -> None:
    connector._client.get_map_image.return_value = None

    assert await connector.fetch_robot_map(ROBOT_ID, MAP_ID) is None
