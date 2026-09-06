# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import asyncio
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
    await robot_manager.start()
    # Should start the fleet state and fleet details loops
    assert len(robot_manager._running_tasks) == 2

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

@pytest.mark.asyncio
async def test_stop_closes_api_client(robot_manager):
    robot_manager.api.close = AsyncMock()

    await robot_manager.stop()

    robot_manager.api.close.assert_awaited_once()

@pytest.mark.asyncio
async def test_start_registers_supervised_tasks(manager_config):
    client = MockOmronClient()
    await client.connect()
    registered = []

    def fake_supervisor(name, coro_factory):
        registered.append(name)
        return asyncio.create_task(coro_factory(), name=name)

    manager = RobotManager(
        manager_config, api_client=client, create_supervised_task=fake_supervisor
    )
    await manager.start()

    assert registered == ["flowcore-fleet-state", "flowcore-fleet-details"]

    await asyncio.sleep(0.1)
    for task in manager._running_tasks:
        assert not task.done()

    await manager.stop()


@pytest.mark.asyncio
async def test_grace_is_derived_from_the_poll_rate_with_a_floor(manager_config):
    """Three missed polls, but never under the 10s the Fleet Manager itself takes to
    reflect a change: at 1 Hz the floor is what protects against a ~2s wildcard fetch."""
    assert RobotManager(manager_config, api_client=MockOmronClient())._grace_secs == 10.0
    assert (
        RobotManager(manager_config, api_client=MockOmronClient(), default_update_freq=0.1)._grace_secs
        == 30.0
    )


@pytest.mark.asyncio
async def test_clocks_are_seeded_so_startup_is_not_reported_offline(manager_config):
    """A freshly constructed manager has not polled yet, but the grace period must
    cover startup the same way it covers an outage, or every connector start and
    restart publishes a spurious offline transition."""
    manager_config.fleet = [MagicMock(fleet_robot_id="Robot1", ip_address=None)]
    manager = RobotManager(manager_config, api_client=MockOmronClient())

    assert manager.api_connected() is True
    assert manager.is_online("Robot1") is True


@pytest.mark.asyncio
async def test_online_once_the_fleet_manager_fetches_a_value_from_the_robot(robot_manager):
    await robot_manager._update_fleet_state()
    assert robot_manager.is_online("Robot1") is False, "nothing fetched yet"

    await robot_manager._update_fleet_details()

    assert robot_manager.is_reporting("Robot1") is True
    assert robot_manager.is_online("Robot1") is True
    assert robot_manager.offline_reason("Robot1") is None


def _age_fetch(robot_manager, fleet_robot_id="Robot1"):
    robot_manager._last_fetched_at[fleet_robot_id] -= robot_manager._grace_secs + 1.0


def _age_sweep(robot_manager):
    robot_manager._last_sweep_ok_at -= robot_manager._grace_secs + 1.0


@pytest.mark.asyncio
async def test_offline_as_no_telemetry_once_fetches_stop(robot_manager):
    await robot_manager._update_fleet_state()
    await robot_manager._update_fleet_details()
    _age_fetch(robot_manager)

    assert robot_manager.api_connected() is True
    assert robot_manager.is_attached("Robot1") is True
    assert robot_manager.offline_reason("Robot1") == "no_telemetry"


@pytest.mark.asyncio
async def test_stays_online_while_within_the_grace_period(robot_manager):
    await robot_manager._update_fleet_state()
    await robot_manager._update_fleet_details()
    robot_manager.api._connected = False

    await robot_manager._update_fleet_state()
    await robot_manager._update_fleet_details()

    assert robot_manager.api_connected() is True
    assert robot_manager.is_online("Robot1") is True


@pytest.mark.asyncio
async def test_still_online_while_the_fleet_endpoint_fails_if_fetches_succeed(robot_manager):
    """The fleet sweep is one endpoint; the robot's values are another. A robot the
    Fleet Manager keeps fetching from is reachable, whatever /Robot/UpdatedSince is
    doing. The failing endpoint shows up in `api_connected`, not in availability."""
    await robot_manager._update_fleet_state()
    await robot_manager._update_fleet_details()
    _age_sweep(robot_manager)

    assert robot_manager.api_connected() is False
    assert robot_manager.is_online("Robot1") is True


@pytest.mark.asyncio
async def test_api_unreachable_outranks_every_other_reason(robot_manager):
    robot_manager.api.seed_robot("Robot1", status="Disconnected", sub_status="Disconnected")
    await robot_manager._update_fleet_state()
    await robot_manager._update_fleet_details()
    _age_sweep(robot_manager)
    _age_fetch(robot_manager)

    assert robot_manager.offline_reason("Robot1") == "api_unreachable"


@pytest.mark.asyncio
async def test_not_in_fleet_when_the_sweep_dropped_the_robot(robot_manager):
    await robot_manager._update_fleet_state()
    await robot_manager._update_fleet_details()
    robot_manager.api._robots.pop("Robot1")
    await robot_manager._update_fleet_state()
    _age_fetch(robot_manager)

    assert robot_manager.api_connected() is True
    assert robot_manager.is_attached("Robot1") is False
    assert robot_manager.offline_reason("Robot1") == "not_in_fleet"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, sub_status",
    [
        ("Disconnected", "Disconnected"),
        ("Disconnected", "Unallocated"),
        ("Available", "Disconnected"),
    ],
)
async def test_disconnected_explains_an_offline_robot(robot_manager, status, sub_status):
    robot_manager.api.seed_robot("Robot1", status=status, sub_status=sub_status)
    await robot_manager._update_fleet_state()
    await robot_manager._update_fleet_details()
    _age_fetch(robot_manager)

    assert robot_manager.is_attached("Robot1") is True
    assert robot_manager.offline_reason("Robot1") == "disconnected"


@pytest.mark.asyncio
async def test_a_fetched_value_outranks_a_disconnected_verdict(robot_manager):
    """If the Fleet Manager says Disconnected but is still fetching values from the
    robot, the robot is reachable and the fetch wins. Statuses explain, they do not
    decide."""
    robot_manager.api.seed_robot("Robot1", status="Disconnected", sub_status="Disconnected")
    await robot_manager._update_fleet_state()
    await robot_manager._update_fleet_details()

    assert robot_manager.is_online("Robot1") is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sub_status",
    ["Fault", "Lost", "EstopPressed", "MotorsDisabled", "OutgoingArclConnectionLost"],
)
async def test_stays_online_when_faulted_or_arcl_lost(robot_manager, sub_status):
    """`OutgoingArclConnectionLost` is the Fleet Manager's command channel, not the
    robot: a live one kept fetching battery and pose from a robot carrying it for
    hours, and the robot answered ICMP and its ARCL port."""
    robot_manager.api.seed_robot(
        "Robot1", status="Unavailable_NeedsAssistance", sub_status=sub_status, x=1.0, battery=1.0
    )
    await robot_manager._update_fleet_state()
    await robot_manager._update_fleet_details()

    assert robot_manager.is_online("Robot1") is True


@pytest.mark.asyncio
async def test_is_online_and_offline_reason_cannot_disagree(robot_manager):
    await robot_manager._update_fleet_state()
    await robot_manager._update_fleet_details()
    assert robot_manager.is_online("Robot1") is (robot_manager.offline_reason("Robot1") is None)

    _age_fetch(robot_manager)
    assert robot_manager.is_online("Robot1") is (robot_manager.offline_reason("Robot1") is None)


@pytest.mark.asyncio
async def test_a_failing_details_poll_does_not_refresh_the_fetch_clock(robot_manager):
    await robot_manager._update_fleet_details()
    before = robot_manager._last_fetched_at["Robot1"]
    robot_manager.api._connected = False

    await robot_manager._update_fleet_details()

    assert robot_manager._last_fetched_at["Robot1"] == before


@pytest.mark.asyncio
async def test_update_millis_is_none_until_the_cache_is_populated(robot_manager):
    assert robot_manager.update_millis("Robot1", ("PoseX", "PoseY")) is None


@pytest.mark.asyncio
async def test_update_millis_uses_the_keys_that_are_present(robot_manager):
    await robot_manager._update_fleet_details()

    partial = robot_manager.update_millis("Robot1", ("PoseX", "NeverReported"))
    full = robot_manager.update_millis("Robot1", ("PoseX",))

    assert partial == full
    assert partial is not None


@pytest.mark.asyncio
async def test_update_millis_holds_while_nothing_changed(robot_manager):
    await robot_manager._update_fleet_details()
    first = robot_manager.update_millis("Robot1", ("PoseX", "PoseY", "PoseTh"))

    await robot_manager._update_fleet_details()
    second = robot_manager.update_millis("Robot1", ("PoseX", "PoseY", "PoseTh"))

    assert first is not None
    assert first == second


@pytest.mark.asyncio
async def test_update_millis_changes_when_the_pose_moves(robot_manager):
    await robot_manager._update_fleet_details()
    first = robot_manager.update_millis("Robot1", ("PoseX", "PoseY", "PoseTh"))

    robot_manager.api.seed_robot("Robot1", x=9999.0, y=2000.0, theta=90.0, battery=50.0)
    await robot_manager._update_fleet_details()
    second = robot_manager.update_millis("Robot1", ("PoseX", "PoseY", "PoseTh"))

    assert first != second
