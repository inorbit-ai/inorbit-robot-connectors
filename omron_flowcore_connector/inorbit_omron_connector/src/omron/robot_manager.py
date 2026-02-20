# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Robot manager for FlowCore connector."""

# Standard
import asyncio
import logging
import math
from typing import Any, Callable, Coroutine, Dict, Optional

# Local
from .api_client import OmronApiClient
from .arcl_client import ArclClient

LOGGER = logging.getLogger(__name__)


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
    ):
        """Initialize the robot manager.

        Args:
            config: FlowCore connector configuration
            api_client: Optional API client instance (for testing)
            default_update_freq: Default update frequency in Hz
        """
        self.config = config
        # Allow injection of api_client for testing/mocking
        self.api = api_client if api_client else OmronApiClient(config.connector_config)
        self._default_update_freq = default_update_freq
        
        self._stop_event = asyncio.Event()
        self._running_tasks: list[asyncio.Task] = []
        
        # Cached data per InOrbit robot_id
        # Structure: {robot_id: {data_type: value}}
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

        # We start two loops: one for high-level status (fleet state), one for details (telemetry)
        self._run_in_loop(self._update_fleet_state)
        self._run_in_loop(self._update_fleet_details)
        
        LOGGER.info("Started FlowCore API polling")

    async def stop(self) -> None:
        """Stop all background polling tasks."""
        self._stop_event.set()

        if self._running_tasks:
            try:
                done, pending = await asyncio.wait(
                    self._running_tasks,
                    timeout=1.0,
                    return_when=asyncio.ALL_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.wait(pending, timeout=0.5)
            except Exception as e:
                LOGGER.error(f"Error during graceful shutdown: {e}")

        for client in self._arcl_clients.values():
            try:
                await client.disconnect()
            except Exception as e:
                LOGGER.error(f"Error disconnecting ARCL client: {e}")
        self._arcl_clients.clear()

        self._running_tasks.clear()
        LOGGER.info("Stopped FlowCore API polling")

    async def _update_fleet_state(self) -> None:
        """Fetch fleet state and update cached data for all robots."""
        try:
            fleet_state = await self.api.get_fleet_state()
            
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

        except Exception as e:
            LOGGER.error(f"Error updating fleet details: {e}")

    def get_robot_pose(self, robot_id: str) -> Optional[dict]:
        """Get cached pose for a specific robot."""
        data = self._robot_data.get(robot_id, {})
        
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

    def get_robot_key_values(self, robot_id: str) -> Optional[dict]:
        """Get cached key-values for a specific robot."""
        data = self._robot_data.get(robot_id, {})
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

    def get_robot_odometry(self, robot_id: str) -> Optional[dict]:
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

    def _run_in_loop(
        self,
        coro: Callable[[], Coroutine[None, None, None]],
        frequency: float | None = None,
    ) -> None:
        """Run a coroutine in a loop at a specified frequency."""
        freq = frequency if frequency is not None else self._default_update_freq

        async def run_loop():
            while not self._stop_event.is_set():
                try:
                    await asyncio.gather(
                        coro(),
                        asyncio.sleep(1.0 / freq),
                    )
                except Exception as e:
                    LOGGER.error(f"Error in polling loop for {coro.__name__}: {e}")
                    # Prevent tight loop on error
                    await asyncio.sleep(1.0)

        task = asyncio.create_task(run_loop())
        self._running_tasks.append(task)

    async def get_arcl_client(self, robot_id: str) -> ArclClient:
        """Get or create ARCL client for a robot."""
        # Check if we have the robot in cache
        if robot_id not in self._robot_data:
            raise ValueError(f"Robot {robot_id} not found in fleet.")

        # Get IP address
        ip = self._robot_data[robot_id].get("robot_ip")
        if not ip:
            raise ValueError(f"IP address not available for robot {robot_id}.")

        # Return existing client if available
        if robot_id in self._arcl_clients:
            return self._arcl_clients[robot_id]

        # Create new client
        LOGGER.info(f"Creating new ARCL client for {robot_id} at {ip}")
        client = ArclClient(
            host=ip,
            port=self.config.connector_config.arcl_port,
            password=self.config.connector_config.arcl_password,
            connection_timeout=self.config.connector_config.arcl_timeout,
        )
        await client.connect()
        self._arcl_clients[robot_id] = client
        return client
