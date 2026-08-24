# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Fleet data poller: caches per-robot state fetched from the Gausium API."""

# Standard
import asyncio
import logging
import math
import time
from dataclasses import dataclass, field

# Local
from gausium_open_platform_connector.src.api.client import GausiumApiClient

logger = logging.getLogger(__name__)

ROBOTS_PAGE_SIZE = 100
ROBOTS_MAX_PAGES = 10


@dataclass
class RobotState:
    """Last known API data for one robot.

    Attributes:
        status: Per-robot status from the v1 batch status endpoint.
        status_v2: Per-robot status from the v2 batch status endpoint.
        robot_data: Entry from the robots list (displayName, model codes, softwareVersion).
    """

    status: dict = field(default_factory=dict)
    status_v2: dict = field(default_factory=dict)
    robot_data: dict = field(default_factory=dict)


class DataPoller:
    """Polls fleet-wide API data and fans it out into per-robot ``RobotState`` caches.

    Owns no asyncio tasks: the connector runs the single-shot ``poll_*_once`` coroutines
    under its own supervised loops.
    """

    def __init__(self, client: GausiumApiClient, serial_numbers: list[str]) -> None:
        """Initialize the poller.

        Args:
            client: API client shared by the whole fleet.
            serial_numbers: Serial numbers of the fleet robots.
        """
        self._client = client
        self._serial_numbers = list(serial_numbers)
        self._states = {sn: RobotState() for sn in self._serial_numbers}
        self._api_connected = False
        self._last_status_success: float | None = None

    @property
    def api_connected(self) -> bool:
        """Whether the last status poll reached the API."""
        return self._api_connected

    @property
    def api_unreachable_secs(self) -> float:
        """Seconds since the last status poll that reached the API.

        ``0.0`` while connected, ``inf`` until the first success, so a connector starting
        against a dead API reports its robots offline on the first tick.
        """
        if self._api_connected:
            return 0.0
        if self._last_status_success is None:
            return math.inf
        return time.monotonic() - self._last_status_success

    def get_state(self, serial_number: str) -> RobotState:
        """Return the cached state for one robot."""
        return self._states[serial_number]

    async def poll_status_once(self) -> None:
        """Poll both batch status endpoints once and fan results out per robot.

        A failed call keeps cached data; robots absent from a response keep their cache.
        ``api_connected`` reflects whether at least one batch call succeeded.
        """
        status_v1, status_v2 = await asyncio.gather(
            self._client.batch_status_v1(self._serial_numbers),
            self._client.batch_status_v2(self._serial_numbers),
        )
        self._api_connected = status_v1 is not None or status_v2 is not None
        if self._api_connected:
            self._last_status_success = time.monotonic()
        self._fan_out(status_v1, "status")
        self._fan_out(status_v2, "status_v2")

    def _fan_out(self, result: dict[str, dict] | None, field_name: str) -> None:
        if result is None:
            return
        for serial_number, payload in result.items():
            state = self._states.get(serial_number)
            if state is not None:
                setattr(state, field_name, payload)

    async def poll_robot_data_once(self) -> None:
        """Page through the account robot list and update ``robot_data`` for fleet robots.

        Stops early once every fleet serial number was seen or a page comes back short.
        """
        pending = set(self._serial_numbers)
        for page in range(1, ROBOTS_MAX_PAGES + 1):
            response = await self._client.get_robots(page=page, page_size=ROBOTS_PAGE_SIZE)
            if response is None:
                return
            robots = response.get("robots", [])
            for robot in robots:
                serial_number = robot.get("serialNumber")
                if serial_number in self._states:
                    self._states[serial_number].robot_data = robot
                    pending.discard(serial_number)
            if not pending or len(robots) < ROBOTS_PAGE_SIZE:
                return
