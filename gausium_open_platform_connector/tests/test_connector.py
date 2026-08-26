# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for `gausium_open_platform_connector.src.connector`."""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, Mock, call

import pytest
from inorbit_connector.commands import CommandFailure, CommandResultCode
from inorbit_connector.connector import FleetConnector
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND, COMMAND_MESSAGE, COMMAND_NAV_GOAL

from gausium_open_platform_connector import __version__
from gausium_open_platform_connector.src.commands import (
    RemoteNavigationCommandType,
    RemoteTaskCommandType,
)
from gausium_open_platform_connector.src.config.models import GausiumOpenPlatformConnectorConfig
from gausium_open_platform_connector.src.connector import (
    API_OFFLINE_GRACE_SECS,
    STATUS_MAX_AGE_SECS,
    GausiumOpenPlatformConnector,
)
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
    sessions = defaultdict(MagicMock, {ROBOT_ID: session})
    connector._get_robot_session = Mock(side_effect=sessions.__getitem__)
    connector.publish_robot_pose = Mock()
    connector.publish_robot_odometry = Mock()
    connector.publish_robot_key_values = Mock()
    return connector


def mark_api(connector, unreachable_secs: float) -> None:
    """Leave the poller in the state a status sweep would: 0.0 means the last one reached it."""
    connector._poller._reached = {"v1": unreachable_secs == 0.0}
    connector._poller._last_status_success = time.monotonic() - unreachable_secs


def health_calls(connector, robot_id: str = ROBOT_ID) -> list[dict]:
    """Key-value publishes carrying connector health, which go out every tick."""
    return [
        c.kwargs
        for c in connector.publish_robot_key_values.call_args_list
        if c.args[0] == robot_id and "api_connected" in c.kwargs
    ]


def telemetry_calls(connector, robot_id: str = ROBOT_ID) -> list[dict]:
    """Key-value publishes carrying robot data, which go out only while it is current."""
    return [
        c.kwargs
        for c in connector.publish_robot_key_values.call_args_list
        if c.args[0] == robot_id and "api_connected" not in c.kwargs
    ]


@pytest.fixture()
def robot_state(connector):
    """The cached poller state for ROBOT_ID, primed with realistic data."""
    state = connector._poller.get_state(SN_1)
    state.record_status(sample_status())
    state.status_v2 = sample_status_v2()
    state.robot_data = {
        "serialNumber": SN_1,
        "displayName": "Robot Alpha",
        "modelFamilyCode": "S",
        "modelTypeCode": "Scrubber 50H",
        "softwareVersion": "5.10.2",
    }
    mark_api(connector, 0.0)
    return state


# --- Polling ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_loop_period_is_the_max_of_sweep_and_pacing(connector, monkeypatch) -> None:
    # asyncio.sleep is stubbed to a no-op yield (conftest), so time here is virtual: a sleep
    # advances the clock from the instant it began, so concurrent sleeps overlap and
    # sequential ones add up
    yield_control = asyncio.sleep
    clock = {"now": 0.0}
    starts: list[float] = []
    connector.config.update_freq = 0.5  # 2 s pacing tick
    sweep_secs = 3.0

    async def sleep(delay: float) -> None:
        started = clock["now"]
        await yield_control(0)
        clock["now"] = max(clock["now"], started + delay)

    async def poll_status_v1_once() -> None:
        starts.append(clock["now"])
        if len(starts) == 4:
            raise asyncio.CancelledError
        # The API is unreachable until the third sweep
        connector._poller.api_connected = len(starts) == 3
        await sleep(sweep_secs)

    connector._poller = Mock(api_connected=False, poll_status_v1_once=poll_status_v1_once)
    monkeypatch.setattr(asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await connector._poll_status_loop()

    # A 3 s sweep against a 2 s tick costs 3 s, not 5 s; the last period is 2+2 s of pacing
    assert starts == [0.0, 3.0, 6.0, 10.0]


# --- Publishing ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_canonical_key_values_are_published(connector, robot_state) -> None:
    await connector._execution_loop()

    (health,) = health_calls(connector)
    assert health["api_connected"] is True
    assert health["robot_online"] is True
    assert health["connector_version"] == __version__
    (kwargs,) = telemetry_calls(connector)
    assert kwargs == build_key_values(
        robot_state.status, robot_state.status_v2, robot_state.robot_data
    )
    assert kwargs["display_name"] == "Robot Alpha"
    assert kwargs["software_version"] == "5.10.2"
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
    state.record_status(sample_status())
    state.status_v2 = sample_status_v2()
    mark_api(connector, 0.0)

    await connector._execution_loop()

    assert connector.publish_robot_pose.call_args.kwargs["x"] == 100.0 * 0.1
    assert connector.publish_robot_pose.call_args.kwargs["y"] == 200.0 * 0.1


@pytest.mark.asyncio
async def test_pose_skipped_when_coordinates_missing(connector, robot_state) -> None:
    # Lost robots publish a map id but no coordinates
    del robot_state.status["localizationInfo"]["mapPosition"]["x"]

    await connector._execution_loop()

    connector.publish_robot_pose.assert_not_called()
    assert len(telemetry_calls(connector)) == 1


@pytest.mark.asyncio
async def test_robot_without_status_is_skipped(connector) -> None:
    # The API is reachable, the batch response just carried nothing for this robot
    mark_api(connector, 0.0)

    await connector._execution_loop()

    assert telemetry_calls(connector) == []
    connector.publish_robot_pose.assert_not_called()
    # Health still goes out, without a vendor reachability it cannot know
    assert health_calls(connector) == [{"api_connected": True, "connector_version": __version__}]


# --- Data freshness -----------------------------------------------------------


@pytest.mark.asyncio
async def test_telemetry_is_republished_only_when_the_vendor_reports_again(
    connector, robot_state
) -> None:
    # The poll cycle is far slower than the publish tick, so most ticks have nothing new
    await connector._execution_loop()
    await connector._execution_loop()
    assert len(telemetry_calls(connector)) == 1
    connector.publish_robot_pose.assert_called_once()
    # Health carries the growing age, so a frozen cache is visible without the telemetry
    assert len(health_calls(connector)) == 2

    robot_state.status["latestReportTime"] = "1786912999999"
    await connector._execution_loop()
    assert len(telemetry_calls(connector)) == 2

    # A v2-only advance counts too: the two payloads report independently
    robot_state.status_v2["latestReportTime"] = "1786913000000"
    await connector._execution_loop()
    assert len(telemetry_calls(connector)) == 3


@pytest.mark.asyncio
async def test_telemetry_publishes_every_tick_without_a_report_time(connector, robot_state) -> None:
    # Not every model reports one, and staleness is not knowable without it
    del robot_state.status["latestReportTime"]

    await connector._execution_loop()
    await connector._execution_loop()

    assert len(telemetry_calls(connector)) == 2


@pytest.mark.asyncio
async def test_recovery_republishes_even_without_a_newer_report(connector, robot_state) -> None:
    await connector._execution_loop()
    mark_api(connector, API_OFFLINE_GRACE_SECS + 1)
    await connector._execution_loop()

    # The vendor has nothing newer than before the outage, but the platform still needs
    # the state it stopped receiving
    mark_api(connector, 0.0)
    connector.publish_robot_key_values.reset_mock()
    await connector._execution_loop()

    assert len(telemetry_calls(connector)) == 1


# --- Reachability mirror ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_single_failed_tick_does_not_flap_the_fleet(
    connector, robot_state, session
) -> None:
    # 4xx and 5xx are not retried, so one gateway error fails both batch endpoints at once
    mark_api(connector, API_OFFLINE_GRACE_SECS / 2)

    await connector._execution_loop()

    session._send_robot_status.assert_not_called()
    assert connector._is_fleet_robot_online(ROBOT_ID) is True
    assert len(telemetry_calls(connector)) == 1


@pytest.mark.asyncio
async def test_one_robot_going_stale_is_reported_offline(connector, robot_state, session) -> None:
    """The API answers for the fleet while one robot stops appearing in the sweeps.

    Observed on a 55-robot fleet: the vendor rate-limits and times out, and can omit a
    robot from a sweep that otherwise succeeded. 49 of 55 robots held values up to ten
    hours old while still reading as online, so a robot that stopped reporting mid-task
    kept showing that task. `_api_reachable` cannot see this: the API is reachable.
    """
    await connector._execution_loop()
    assert connector._is_fleet_robot_online(ROBOT_ID) is True

    robot_state.status_at -= STATUS_MAX_AGE_SECS + 1
    connector.publish_robot_key_values.reset_mock()
    connector.publish_robot_pose.reset_mock()

    await connector._execution_loop()

    session._send_robot_status.assert_called_once_with(online=False)
    assert connector._is_fleet_robot_online(ROBOT_ID) is False
    assert telemetry_calls(connector) == []
    connector.publish_robot_pose.assert_not_called()


@pytest.mark.asyncio
async def test_a_stale_robot_recovers_when_its_status_returns(
    connector, robot_state, session
) -> None:
    """Offline-on-stale is not a one-way door."""
    robot_state.status_at -= STATUS_MAX_AGE_SECS + 1
    await connector._execution_loop()
    assert connector._is_fleet_robot_online(ROBOT_ID) is False

    session._send_robot_status.reset_mock()
    connector.publish_robot_key_values.reset_mock()
    robot_state.record_status(sample_status())

    await connector._execution_loop()

    session._send_robot_status.assert_called_once_with(online=True)
    assert connector._is_fleet_robot_online(ROBOT_ID) is True
    assert len(telemetry_calls(connector)) == 1


@pytest.mark.asyncio
async def test_the_age_limit_is_what_catches_the_frozen_robot(
    connector, robot_state, session, monkeypatch
) -> None:
    """Pins the limit: without it a robot frozen for hours still reads as online."""
    monkeypatch.setattr(
        "gausium_open_platform_connector.src.connector.STATUS_MAX_AGE_SECS", float("inf")
    )
    robot_state.status_at -= 10 * 3600

    await connector._execution_loop()

    assert connector._is_fleet_robot_online(ROBOT_ID) is True


@pytest.mark.asyncio
async def test_api_unreachable_mirror(connector, robot_state, session) -> None:
    await connector._execution_loop()
    session._send_robot_status.assert_not_called()
    assert connector._is_fleet_robot_online(ROBOT_ID) is True

    # Unreachable past the grace period freezes the cache: report offline instead of
    # republishing it, which would keep refreshing updateStamp
    mark_api(connector, API_OFFLINE_GRACE_SECS + 1)
    connector.publish_robot_key_values.reset_mock()
    connector.publish_robot_pose.reset_mock()
    await connector._execution_loop()
    session._send_robot_status.assert_called_once_with(online=False)
    assert telemetry_calls(connector) == []
    connector.publish_robot_pose.assert_not_called()
    assert connector._is_fleet_robot_online(ROBOT_ID) is False
    # Health keeps going out, so the api_connected alert can fire on the account, and the
    # data age keeps growing off the frozen cache
    (health,) = health_calls(connector)
    assert health["api_connected"] is False
    assert health["data_age_secs"] > 0
    assert "robot_online" not in health

    # Still unreachable: the offline status is not re-sent
    connector.publish_robot_key_values.reset_mock()
    await connector._execution_loop()
    assert session._send_robot_status.call_args_list == [call(online=False)]
    assert telemetry_calls(connector) == []

    # API comes back: status is mirrored and telemetry resumes
    mark_api(connector, 0.0)
    connector.publish_robot_key_values.reset_mock()
    await connector._execution_loop()
    session._send_robot_status.assert_called_with(online=True)
    assert len(telemetry_calls(connector)) == 1
    assert connector._is_fleet_robot_online(ROBOT_ID) is True


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
    assert telemetry_calls(connector) == []
    # The API is still reachable, so health carries the vendor's own verdict
    (health,) = health_calls(connector)
    assert health["api_connected"] is True
    assert health["robot_online"] is False
    assert connector._is_fleet_robot_online(ROBOT_ID) is False

    # Still offline: the offline status is not re-sent (it would refresh updateStamp,
    # hiding how long the robot has been offline), still no telemetry
    connector.publish_robot_key_values.reset_mock()
    await connector._execution_loop()
    assert session._send_robot_status.call_args_list == [call(online=False)]
    assert telemetry_calls(connector) == []

    # Vendor comes back: status is mirrored and telemetry resumes
    robot_state.status["online"] = True
    connector.publish_robot_key_values.reset_mock()
    await connector._execution_loop()
    session._send_robot_status.assert_called_with(online=True)
    assert len(telemetry_calls(connector)) == 1
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
        mark_api(connector, API_OFFLINE_GRACE_SECS + 1)
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


@pytest.mark.asyncio
async def test_fetch_robot_map_publishes_image_as_downloaded(connector, robot_state) -> None:
    # format_version 2 (the default) displays the map as uploaded, so no flipping
    connector._client.get_map_image.return_value = b"\x89PNG-bytes"

    result = await connector.fetch_robot_map(ROBOT_ID, MAP_ID)

    connector._client.get_map_image.assert_awaited_once_with(
        SN_1, MAP_ID, "floor_1", "maps/x/versions/y"
    )
    assert result is not None
    assert result.image == b"\x89PNG-bytes"
    assert result.map_id == MAP_ID
    assert result.map_label == "floor_1"
    assert result.origin_x == 0.0
    assert result.origin_y == 0.0
    assert result.resolution == 0.05
    assert result.format_version == 2


@pytest.mark.asyncio
async def test_fetch_robot_map_mismatched_frame_id(connector, robot_state) -> None:
    result = await connector.fetch_robot_map(ROBOT_ID, "some-other-map-id")

    assert result is None
    connector._client.get_map_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_robot_map_download_failure(connector, robot_state) -> None:
    connector._client.get_map_image.return_value = None

    assert await connector.fetch_robot_map(ROBOT_ID, MAP_ID) is None
