# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Robot manager for FlowCore connector."""

# Standard
import asyncio
import logging
import math
import time
from functools import partial
from typing import Any, Callable, Dict, Optional

# Local
from .api_client import OmronApiClient
from .arcl_client import ArclClient

LOGGER = logging.getLogger(__name__)

# Undocumented status/subStatus value found by probing a live Fleet Manager: it is
# not mentioned anywhere in the Integration Toolkit manual, but both fields carry it
# for a robot that has been unreachable for a long time, and it is a first-class
# value of /Robot/ByStatus. Used to explain an offline robot, never to decide it.
DISCONNECTED_STATUS = "Disconnected"

# Reasons a robot is offline, most fundamental first
OFFLINE_API_UNREACHABLE = "api_unreachable"
OFFLINE_NOT_IN_FLEET = "not_in_fleet"
OFFLINE_DISCONNECTED = "disconnected"
OFFLINE_NO_TELEMETRY = "no_telemetry"

# Missed polls tolerated before a robot or the API counts as gone, and the floor on
# that window whatever update_freq is. The Fleet Manager takes up to 10s to reflect
# an attach or detach, and a wildcard /DataStoreValueLatest fetch takes ~2s by design
# (manual, Table 4-7), so a tighter window at high poll rates flaps on one slow cycle.
MISSED_POLLS_TOLERATED = 3
MIN_GRACE_SECS = 10.0


def to_inorbit_pose(x_mm: float, y_mm: float, theta_deg: float, frame_id: str = "map") -> dict[str, float]:
    """Convert FlowCore pose (mm, deg) to InOrbit pose (m, rad)."""
    return {
        "x": x_mm / 1000.0,
        "y": y_mm / 1000.0,
        "yaw": math.radians(theta_deg),
        "frame_id": frame_id,
    }


class RobotManager:
    """Manages polling of FlowCore API and caches robot data to be published.

    This class runs background polling loops to fetch data from the API at configurable
    frequencies. The connector's execution loop then retrieves the data to be published without
    blocking on API calls.
    """

    def __init__(
        self,
        config,
        api_client: Optional[Any] = None,
        default_update_freq: float = 1.0,
        create_supervised_task: Optional[Callable] = None,
    ):
        """Initialize the robot manager.

        Args:
            config: FlowCore connector configuration
            api_client: Optional API client instance (for testing)
            default_update_freq: Default update frequency in Hz
            create_supervised_task: Callable scheduling a supervised background task,
                normally FleetConnector._create_supervised_task
        """
        self.config = config
        # Allow injection of api_client for testing/mocking
        self.api = api_client if api_client else OmronApiClient(config.connector_config)
        self._default_update_freq = default_update_freq
        self._grace_secs = max(MISSED_POLLS_TOLERATED / default_update_freq, MIN_GRACE_SECS)
        # Monotonic time of the last /Robot/UpdatedSince that did not raise, and the
        # robots it listed. Listing tracks fleet membership, not reachability: a
        # robot stays listed indefinitely after it disconnects, until it is removed
        # from the fleet.
        #
        # Monotonic time the Fleet Manager last fetched any DataStore value from each
        # robot. /DataStoreValueLatest reaches the AMR on every call (manual, p.23), so
        # a value coming back is the Fleet Manager saying it just reached the robot.
        # That is the availability signal; the status vocabulary only explains it.
        #
        # Both clocks are seeded at construction so the grace period covers startup
        # the same way it covers an outage. Without this every start and restart
        # publishes a spurious offline tick while the first polls are in flight.
        now = time.monotonic()
        self._last_sweep_ok_at: float = now
        self._present: set[str] = set()
        self._last_fetched_at: Dict[str, float] = {r.fleet_robot_id: now for r in config.fleet}

        # Falls back to a bare task when no supervisor is injected, which is what the
        # tests use. In production the connector passes the framework's supervisor.
        self._create_supervised_task = create_supervised_task or (
            lambda name, coro_factory: asyncio.create_task(coro_factory(), name=name)
        )
        self._running_tasks: list[asyncio.Task] = []
        
        # Cached data keyed by FlowCore namekey (fleet_robot_id)
        # Structure: {fleet_robot_id: {data_type: value}}
        self._robot_data: Dict[str, Dict[str, Any]] = {}

        # Map of FlowCore robot_id (NameKey) to configuration
        self._fleet_config = {r.fleet_robot_id: r for r in config.fleet}

        # Pre-populate cache with configured IPs
        for robot in config.fleet:
            if robot.ip_address:
                if robot.fleet_robot_id not in self._robot_data:
                    self._robot_data[robot.fleet_robot_id] = {}
                self._robot_data[robot.fleet_robot_id]["robot_ip"] = robot.ip_address

        # Map of robot_id to ArclClient instance
        self._arcl_clients: Dict[str, ArclClient] = {}

    async def start(self) -> None:
        """Connect to API and start background polling tasks."""
        try:
            await self.api.connect()
            LOGGER.info("Connected to FlowCore API")
        except Exception as e:
            LOGGER.error(f"Failed to connect to FlowCore API: {e}")
            raise

        # One loop for high-level status (fleet state), one for details (telemetry)
        self._running_tasks = [
            self._create_supervised_task(
                "flowcore-fleet-state", partial(self._poll_loop, self._update_fleet_state)
            ),
            self._create_supervised_task(
                "flowcore-fleet-details", partial(self._poll_loop, self._update_fleet_details)
            ),
        ]

        LOGGER.info("Started FlowCore API polling")

    async def stop(self) -> None:
        """Stop all background polling tasks."""
        for task in self._running_tasks:
            task.cancel()
        if self._running_tasks:
            await asyncio.gather(*self._running_tasks, return_exceptions=True)
        self._running_tasks.clear()

        for client in self._arcl_clients.values():
            try:
                await client.disconnect()
            except Exception as e:
                LOGGER.error(f"Error disconnecting ARCL client: {e}")
        self._arcl_clients.clear()

        await self.api.close()

        LOGGER.info("Stopped FlowCore API polling")

    async def _update_fleet_state(self) -> None:
        """Fetch fleet state and update cached data for all robots."""
        try:
            fleet_state = await self.api.get_fleet_state()
            self._last_sweep_ok_at = time.monotonic()
            self._present = {robot.namekey for robot in fleet_state}

            for robot_summary in fleet_state:
                robot_id = robot_summary.namekey # We use namekey as robot_id
                
                # Initialize cache entry if not exists
                if robot_id not in self._robot_data:
                    self._robot_data[robot_id] = {}

                self._robot_data[robot_id]["summary"] = robot_summary

                # Check for IP change and invalidate ARCL client if needed
                if robot_id in self._arcl_clients:
                    old_ip = self._robot_data[robot_id].get("robot_ip")
                    new_ip = robot_summary.ipAddress
                    
                    conf = self._fleet_config.get(robot_id)
                    if conf and conf.ip_address:
                        new_ip = conf.ip_address

                    if new_ip and old_ip and new_ip != old_ip:
                        LOGGER.info(
                            f"IP changed for {robot_id} from {old_ip} to {new_ip}. "
                            "Invalidating ARCL client."
                        )
                        client = self._arcl_clients.pop(robot_id)
                        asyncio.create_task(client.disconnect())

                # Update IP in cache only if not overridden by config
                conf = self._fleet_config.get(robot_id)
                if conf and conf.ip_address:
                    self._robot_data[robot_id]["robot_ip"] = conf.ip_address
                elif robot_summary.ipAddress:
                    self._robot_data[robot_id]["robot_ip"] = robot_summary.ipAddress

        except Exception as e:
            LOGGER.error(f"Error updating fleet state: {e}")

    async def _update_fleet_details(self) -> None:
        """Fetch detailed telemetry for the entire fleet using bulk endpoint."""
        try:
            # Map keys to result indices
            # 0: PoseX, 1: PoseY, 2: PoseTh, 3: StateOfCharge, 4: RobotIP
            keys = ["PoseX", "PoseY", "PoseTh", "StateOfCharge", "RobotIP"]
            calls = [self.api.get_data_store_value(key, "*") for key in keys]
            
            # Bulk fetch using wildcard '*'
            # Each call returns a list of DataStoreResponse objects for all robots
            results = await asyncio.gather(*calls, return_exceptions=True)
            fetched: set[str] = set()

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    LOGGER.error(f"Error bulk fetching {keys[i]}: {result}")
                    continue
                
                # result is assumed to be List[DataStoreResponse]
                if not isinstance(result, list):
                    # Should not happen with '*' but defensive check
                    continue

                for item in result:
                    # namekey format: "Key:RobotID"
                    parts = item.namekey.split(":")
                    if len(parts) >= 2:
                        robot_id = parts[1]
                        fetched.add(robot_id)

                        # Initialize cache if needed (though fleet state update should have done it)
                        if robot_id not in self._robot_data:
                            self._robot_data[robot_id] = {}
                            
                        self._robot_data[robot_id][keys[i]] = item

                        # Specific handling for IP discovery
                        if keys[i] == "RobotIP" and item.value:
                            conf = self._fleet_config.get(robot_id)
                            if conf and conf.ip_address:
                                # Prioritize config override
                                if item.value != conf.ip_address:
                                    LOGGER.debug(f"DataStore IP {item.value} ignored for {robot_id}, using override {conf.ip_address}")
                                continue

                            old_ip = self._robot_data[robot_id].get("robot_ip")
                            if item.value != old_ip:
                                self._robot_data[robot_id]["robot_ip"] = item.value
                                LOGGER.info(f"Discovered IP {item.value} for robot {robot_id} via DataStore")

            now = time.monotonic()
            for robot_id in fetched:
                self._last_fetched_at[robot_id] = now

        except Exception as e:
            LOGGER.error(f"Error updating fleet details: {e}")

    def api_connected(self) -> bool:
        """Whether a fleet sweep succeeded within the grace period."""
        return (time.monotonic() - self._last_sweep_ok_at) <= self._grace_secs

    def is_attached(self, fleet_robot_id: str) -> bool:
        """Whether this robot is still registered with the Fleet Manager.

        This reflects fleet membership, not reachability: a robot that has lost
        communication stays listed here indefinitely, until it is deregistered from
        the fleet.
        """
        return fleet_robot_id in self._present

    def is_reporting(self, fleet_robot_id: str) -> bool:
        """Whether the Fleet Manager fetched a DataStore value from this robot recently.

        This is the one fact availability rests on. A robot the Fleet Manager cannot
        reach returns nothing from /DataStoreValueLatest; one it can reach returns
        values whatever its status says, including `OutgoingArclConnectionLost`, which
        only means the Fleet Manager's own command channel is down.
        """
        last = self._last_fetched_at.get(fleet_robot_id)
        return last is not None and (time.monotonic() - last) <= self._grace_secs

    def offline_reason(self, fleet_robot_id: str) -> Optional[str]:
        """Why this robot is offline, or None while it is online.

        Cache reads only: this runs once per robot per execution loop iteration and
        also on the edge-SDK network thread.

        The decision is `is_reporting`. Everything below it is explanation, ordered
        so the most fundamental cause wins: an unreachable API is why nothing else
        about the robot can be known, a deregistered robot is why no fetch was
        attempted, and the Fleet Manager's own `Disconnected` verdict, when it has
        one, beats the bare observation that values stopped coming back.

        A robot in a bad but reachable state (Fault, Lost, EstopPressed,
        MotorsDisabled, OutgoingArclConnectionLost) stays online: it is still
        reporting, and its pose is what an operator needs to go find it. The
        condition surfaces through its status instead.
        """
        if self.is_reporting(fleet_robot_id):
            return None
        if not self.api_connected():
            return OFFLINE_API_UNREACHABLE
        if not self.is_attached(fleet_robot_id):
            return OFFLINE_NOT_IN_FLEET
        summary = self._robot_data.get(fleet_robot_id, {}).get("summary")
        if summary is not None and DISCONNECTED_STATUS in (summary.status, summary.subStatus):
            return OFFLINE_DISCONNECTED
        return OFFLINE_NO_TELEMETRY

    def is_online(self, fleet_robot_id: str) -> bool:
        """Whether InOrbit should consider this robot online. See `offline_reason`."""
        return self.offline_reason(fleet_robot_id) is None

    def get_robot_pose(self, fleet_robot_id: str) -> Optional[dict]:
        """Get cached pose for a specific robot."""
        data = self._robot_data.get(fleet_robot_id, {})
        
        pose_x = data.get("PoseX")
        pose_y = data.get("PoseY")
        pose_th = data.get("PoseTh")

        if pose_x and pose_y and pose_th:
            return to_inorbit_pose(
                float(pose_x.value), 
                float(pose_y.value), 
                float(pose_th.value),
                frame_id="map_frame"
            )
            
        return None

    def get_robot_key_values(self, fleet_robot_id: str) -> Optional[dict]:
        """Get cached key-values for a specific robot."""
        data = self._robot_data.get(fleet_robot_id, {})
        summary = data.get("summary")
        battery = data.get("StateOfCharge")
        
        if not summary and not battery:
            return None
            
        kv = {}
        
        if battery:
            kv["battery_percent"] = float(battery.value)
            
        if summary:
            kv["omron_status"] = summary.status
            kv["omron_sub_status"] = summary.subStatus
            kv["status"] = self._map_status(summary.subStatus)
            
            # Add more summary fields if available
            if summary.ipAddress:
                kv["robot_ip"] = summary.ipAddress
            
        return kv

    def get_robot_odometry(self, fleet_robot_id: str) -> Optional[dict]:
        """Get cached odometry for a specific robot.
        
        Note: FlowCore generic API might not expose velocity easily in 
        standard DataStore values without custom setup. 
        Returning None for now unless we find velocity keys.
        """
        return None

    def _map_status(self, sub_status: str) -> str:
        """Map Omron sub-status to InOrbit status."""
        # Simple mapping logic
        busy_states = ["Driving", "BeforePickup", "AfterDropoff", "BeforeDropoff", "BeforeEvery", "AfterEvery"]
        charging_states = ["Docked", "Docking", "Charging", "DockParking", "DockParked", "ForcedDocking"]
        idle_states = ["Available", "Parked", "Allocated", "Unallocated"]
        error_states = ["EStopPressed", "Fault", "MotorsDisabled", "Lost", "NotLocalized"]

        if sub_status in busy_states:
            return "BUSY"
        elif sub_status in charging_states:
            return "CHARGING"
        elif sub_status in idle_states:
            return "IDLE"
        elif sub_status in error_states:
            return "ERROR"
        return "IDLE" # Default

    async def _poll_loop(self, poll) -> None:
        """Poll `poll` forever at the configured frequency. Supervised: a crash restarts it."""
        while True:
            await asyncio.gather(poll(), asyncio.sleep(1.0 / self._default_update_freq))

    async def get_arcl_client(self, fleet_robot_id: str) -> ArclClient:
        """Get or create ARCL client for a robot."""
        # Check if we have the robot in cache
        if fleet_robot_id not in self._robot_data:
            raise ValueError(f"Robot {fleet_robot_id} not found in fleet.")

        # Get IP address
        ip = self._robot_data[fleet_robot_id].get("robot_ip")
        if not ip:
            raise ValueError(f"IP address not available for robot {fleet_robot_id}.")

        # Return existing client if available
        if fleet_robot_id in self._arcl_clients:
            return self._arcl_clients[fleet_robot_id]

        # Create new client
        LOGGER.info(f"Creating new ARCL client for {fleet_robot_id} at {ip}")
        client = ArclClient(
            host=ip,
            port=self.config.connector_config.arcl_port,
            password=self.config.connector_config.arcl_password,
            connection_timeout=self.config.connector_config.arcl_timeout,
        )
        await client.connect()
        self._arcl_clients[fleet_robot_id] = client
        return client
