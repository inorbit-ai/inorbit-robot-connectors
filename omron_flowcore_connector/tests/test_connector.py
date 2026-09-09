# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest_asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from inorbit_connector.connector import FleetConnector
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

def test_connector_wires_supervisor(connector_config, mock_executor_cls):
    """robot_manager and mission_tracking must use the connector's own supervisor,
    not the create_supervised_task-or-bare-task fallback, or a dropped keyword
    would silently revert them to unsupervised bare tasks."""
    connector = OmronConnector(connector_config)

    assert connector.robot_manager._create_supervised_task == connector._create_supervised_task
    assert connector._mission_tracking._create_supervised_task == connector._create_supervised_task


def test_connector_enables_system_stats_publishing(connector_config, mock_executor_cls):
    """Dropping this kwarg would silently revert every robot's CPU, RAM and disk
    stats to zeroes with no test failing."""
    with patch.object(
        FleetConnector, "__init__", autospec=True, wraps=FleetConnector.__init__
    ) as mock_init:
        OmronConnector(connector_config)

    assert mock_init.call_args.kwargs["publish_connector_system_stats"] is True


@pytest.mark.asyncio
async def test_disconnect_stops_robot_manager_last(connector_config, mock_executor_cls):
    """robot_manager.stop() closes the shared httpx client and must run after the
    executor and the tracker, or a mission worker cancelled mid-call would hit
    _request and silently reopen a client nothing closes again."""
    connector = OmronConnector(connector_config)
    order = []
    connector._mission_executor.shutdown = AsyncMock(
        side_effect=lambda: order.append("executor")
    )
    connector._mission_tracking.stop = AsyncMock(side_effect=lambda: order.append("tracking"))
    connector.robot_manager.stop = AsyncMock(side_effect=lambda: order.append("robot_manager"))

    await connector._disconnect()

    assert order == ["executor", "tracking", "robot_manager"]


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

    # Verify key values. Health, vendor and robot telemetry are three separate publishes.
    calls = connector.publish_robot_key_values.call_args_list
    assert all(call[0][0] == "Robot1" for call in calls)

    health = next(call.kwargs for call in calls if "api_connected" in call.kwargs)
    assert health["connector_version"] == __version__
    assert health["api_connected"] is True
    assert health["robot_attached"] is True

    vendor = next(call.kwargs for call in calls if "omron_sub_status" in call.kwargs)
    assert vendor["omron_status"] == "Available"
    assert vendor["status"] == "IDLE"

    telemetry = next(call.kwargs for call in calls if "battery_percent" in call.kwargs)
    assert telemetry["battery_percent"] == 80.0

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


def test_is_fleet_robot_online_is_actually_overridden():
    """Every other test calls _is_fleet_robot_online directly, which would still pass
    against a typo'd method name or a base-class rename: nothing would exercise the
    framework's own binding. This checks the override took, not just its behavior."""
    assert OmronConnector._is_fleet_robot_online is not FleetConnector._is_fleet_robot_online


@pytest.mark.asyncio
async def test_is_fleet_robot_online_delegates_to_the_manager(
    connector_config, mock_robot_manager, mock_executor_cls
):
    connector = OmronConnector(connector_config, robot_manager=mock_robot_manager)

    assert connector._is_fleet_robot_online("Robot1") is True

    mock_robot_manager._last_fetched_at["Robot1_FlowCore"] -= mock_robot_manager._grace_secs + 1
    assert connector._is_fleet_robot_online("Robot1") is False


@pytest.mark.asyncio
async def test_is_fleet_robot_online_is_false_for_an_unknown_robot(
    connector_config, mock_robot_manager, mock_executor_cls
):
    connector = OmronConnector(connector_config, robot_manager=mock_robot_manager)
    mock_robot_manager.is_online = MagicMock()

    assert connector._is_fleet_robot_online("not-in-the-fleet") is False

    mock_robot_manager.is_online.assert_not_called()


@pytest.mark.asyncio
async def test_health_key_values_publish_every_tick(
    connector_config, mock_robot_manager, mock_executor_cls
):
    connector = OmronConnector(connector_config, robot_manager=mock_robot_manager)
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_key_values = MagicMock()
    connector.publish_robot_odometry = MagicMock()

    await connector._execution_loop()
    await connector._execution_loop()

    health_calls = [
        call
        for call in connector.publish_robot_key_values.call_args_list
        if "api_connected" in call.kwargs
    ]
    assert len(health_calls) == 2
    assert health_calls[0].kwargs["api_connected"] is True
    assert health_calls[0].kwargs["robot_attached"] is True


@pytest.mark.asyncio
async def test_pose_and_battery_publish_once_while_their_values_hold(
    connector_config, mock_robot_manager, mock_executor_cls
):
    """The details poll runs between the two ticks on purpose: every
    /DataStoreValueLatest fetch restamps the items, so a gate comparing stamps
    republishes here and only a gate comparing values stays quiet."""
    connector = OmronConnector(connector_config, robot_manager=mock_robot_manager)
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_key_values = MagicMock()
    connector.publish_robot_odometry = MagicMock()

    await connector._execution_loop()
    await mock_robot_manager._update_fleet_details()
    await connector._execution_loop()

    assert connector.publish_robot_pose.call_count == 1
    batteries = [
        call
        for call in connector.publish_robot_key_values.call_args_list
        if "battery_percent" in call.kwargs
    ]
    assert len(batteries) == 1


@pytest.mark.asyncio
async def test_pose_republishes_when_the_robot_moves(
    connector_config, mock_robot_manager, mock_executor_cls
):
    connector = OmronConnector(connector_config, robot_manager=mock_robot_manager)
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_key_values = MagicMock()
    connector.publish_robot_odometry = MagicMock()

    await connector._execution_loop()
    mock_robot_manager.api.seed_robot(
        "Robot1_FlowCore", x=5000.0, y=2000.0, theta=180.0, battery=80.0
    )
    await mock_robot_manager._update_fleet_details()
    await connector._execution_loop()

    assert connector.publish_robot_pose.call_count == 2


@pytest.mark.asyncio
async def test_offline_robot_still_publishes_the_vendor_tier(
    connector_config, mock_robot_manager, mock_executor_cls
):
    """A robot the Fleet Manager has stopped fetching values from is offline, but the
    API is still connected, so the vendor tier (FlowCore's own statement about it)
    must keep publishing. Withholding it is what left a dropped robot displaying its
    pre-disconnect status."""
    connector = OmronConnector(connector_config, robot_manager=mock_robot_manager)
    connector.publish_robot_key_values = MagicMock()
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_odometry = MagicMock()
    mock_robot_manager._last_fetched_at["Robot1_FlowCore"] -= mock_robot_manager._grace_secs + 1

    await connector._execution_loop()

    assert connector._is_fleet_robot_online("Robot1") is False
    calls = connector.publish_robot_key_values.call_args_list

    health = next(call.kwargs for call in calls if "api_connected" in call.kwargs)
    assert health["api_connected"] is True
    assert "robot_attached" in health

    vendor = next(call.kwargs for call in calls if "omron_sub_status" in call.kwargs)
    assert vendor["omron_sub_status"] == "Unallocated"


@pytest.mark.asyncio
async def test_arcl_lost_robot_is_online_and_keeps_publishing_telemetry(
    connector_config, mock_robot_manager, mock_executor_cls
):
    """`OutgoingArclConnectionLost` is the Fleet Manager's command channel, not the
    robot. A robot carrying it that the Fleet Manager still fetches values from is
    online, and its live pose is what somebody needs to go and find it."""
    connector = OmronConnector(connector_config, robot_manager=mock_robot_manager)
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_key_values = MagicMock()
    connector.publish_robot_odometry = MagicMock()

    mock_robot_manager.api.seed_robot(
        "Robot1_FlowCore",
        x=1000.0,
        y=2000.0,
        theta=180.0,
        battery=80.0,
        sub_status="OutgoingArclConnectionLost",
    )
    await mock_robot_manager._update_fleet_state()
    await mock_robot_manager._update_fleet_details()
    assert connector._is_fleet_robot_online("Robot1") is True

    await connector._execution_loop()
    mock_robot_manager.api.seed_robot(
        "Robot1_FlowCore",
        x=5000.0,
        y=2000.0,
        theta=180.0,
        battery=50.0,
        sub_status="OutgoingArclConnectionLost",
    )
    await mock_robot_manager._update_fleet_details()
    await connector._execution_loop()

    assert connector.publish_robot_pose.call_count == 2
    batteries = [
        call.kwargs["battery_percent"]
        for call in connector.publish_robot_key_values.call_args_list
        if "battery_percent" in call.kwargs
    ]
    assert batteries == [80.0, 50.0]


@pytest.mark.asyncio
async def test_mission_tracking_republishes_on_in_place_mutation(
    connector_config, mock_robot_manager, mock_executor_cls
):
    """The mission cache is a plain dict the tracker mutates in place, at both the
    top level and inside its `tasks` list. The gate must snapshot deeply, or an
    in-place mutation of the live payload would be invisible to the equality check
    because both sides of the comparison would be the same mutated object."""
    connector = OmronConnector(connector_config, robot_manager=mock_robot_manager)
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_key_values = MagicMock()
    connector.publish_robot_odometry = MagicMock()

    mission_payload = {
        "missionId": "job-1",
        "completedPercent": 0.0,
        "tasks": [{"taskId": "1", "completed": False}],
    }
    connector._mission_tracking._mission_cache["Robot1_FlowCore"] = mission_payload

    await connector._execution_loop()

    mission_payload["completedPercent"] = 0.5
    mission_payload["tasks"][0]["completed"] = True

    await connector._execution_loop()

    mission_calls = [
        call
        for call in connector.publish_robot_key_values.call_args_list
        if "mission_tracking" in call.kwargs
    ]
    assert len(mission_calls) == 2


@pytest.mark.asyncio
async def test_disconnected_robot_still_publishes_vendor_key_values(
    connector_config, mock_robot_manager, mock_executor_cls
):
    """FlowCore's own statement about the robot (the fleet summary) keeps arriving
    correctly even while the robot itself is unreachable, so it must still publish
    once the robot is reported disconnected.

    Telemetry is not asserted here: a truly disconnected robot answers
    `/DataStoreValueLatest` with nothing, so its cached values hold and the tier
    goes quiet on its own. That is the same mechanism
    `test_pose_and_battery_publish_once_while_their_values_hold` pins."""
    connector = OmronConnector(connector_config, robot_manager=mock_robot_manager)
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_key_values = MagicMock()
    connector.publish_robot_odometry = MagicMock()

    mock_robot_manager.api.seed_robot(
        "Robot1_FlowCore", status="Disconnected", sub_status="Disconnected"
    )
    await mock_robot_manager._update_fleet_state()

    await connector._execution_loop()

    vendor_calls = [
        call
        for call in connector.publish_robot_key_values.call_args_list
        if "omron_sub_status" in call.kwargs
    ]
    assert len(vendor_calls) == 1
    assert vendor_calls[0].kwargs["omron_sub_status"] == "Disconnected"


@pytest.mark.asyncio
async def test_vendor_key_values_do_not_republish_while_the_token_holds(
    connector_config, mock_robot_manager, mock_executor_cls
):
    connector = OmronConnector(connector_config, robot_manager=mock_robot_manager)
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_key_values = MagicMock()
    connector.publish_robot_odometry = MagicMock()

    await connector._execution_loop()
    await connector._execution_loop()

    vendor_calls = [
        call
        for call in connector.publish_robot_key_values.call_args_list
        if "omron_sub_status" in call.kwargs
    ]
    assert len(vendor_calls) == 1


@pytest.mark.asyncio
async def test_vendor_key_values_skipped_and_token_forgotten_when_the_api_is_down(
    connector_config, mock_robot_manager, mock_executor_cls
):
    connector = OmronConnector(connector_config, robot_manager=mock_robot_manager)
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_key_values = MagicMock()
    connector.publish_robot_odometry = MagicMock()

    await connector._execution_loop()
    connector.publish_robot_key_values.reset_mock()

    mock_robot_manager.api_connected = MagicMock(return_value=False)
    await connector._execution_loop()

    vendor_calls = [
        call
        for call in connector.publish_robot_key_values.call_args_list
        if "omron_sub_status" in call.kwargs
    ]
    assert vendor_calls == []
    assert "Robot1" not in connector._summary_update_millis

    # Recovery republishes even though FlowCore has nothing newer to report
    mock_robot_manager.api_connected = MagicMock(return_value=True)
    connector.publish_robot_key_values.reset_mock()
    await connector._execution_loop()

    vendor_calls = [
        call
        for call in connector.publish_robot_key_values.call_args_list
        if "omron_sub_status" in call.kwargs
    ]
    assert len(vendor_calls) == 1


@pytest.mark.asyncio
async def test_vendor_key_values_retry_after_a_failed_publish(
    connector_config, mock_robot_manager, mock_executor_cls
):
    """A publish that raises must not let the vendor token get stored, or the retry
    that depends on statement ordering (store after publish, not before) silently
    regresses back to skipping forever. This matters more here than for pose: a
    robot that has permanently dropped may never change its summary again, so a
    swallowed failure on this tier is permanent rather than transient."""
    connector = OmronConnector(connector_config, robot_manager=mock_robot_manager)
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_odometry = MagicMock()

    attempts = {"vendor": 0}

    def maybe_fail(*args, **kwargs):
        if "omron_sub_status" in kwargs:
            attempts["vendor"] += 1
            if attempts["vendor"] == 1:
                raise Exception("boom")

    connector.publish_robot_key_values = MagicMock(side_effect=maybe_fail)

    await connector._execution_loop()
    await connector._execution_loop()

    vendor_calls = [
        call
        for call in connector.publish_robot_key_values.call_args_list
        if "omron_sub_status" in call.kwargs
    ]
    assert len(vendor_calls) == 2


@pytest.mark.asyncio
async def test_pose_retries_after_a_failed_publish(
    connector_config, mock_robot_manager, mock_executor_cls
):
    """A publish that raises must not let its token get stored, or the retry that
    depends on statement ordering (store after publish, not before) silently
    regresses back to skipping forever."""
    connector = OmronConnector(connector_config, robot_manager=mock_robot_manager)
    connector.publish_robot_pose = MagicMock(side_effect=[Exception("boom"), None])
    connector.publish_robot_key_values = MagicMock()
    connector.publish_robot_odometry = MagicMock()

    await connector._execution_loop()
    await connector._execution_loop()

    assert connector.publish_robot_pose.call_count == 2
