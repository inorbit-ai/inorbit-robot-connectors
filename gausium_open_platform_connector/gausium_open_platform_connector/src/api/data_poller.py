# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Fleet data poller: caches per-robot state fetched from the Gausium API."""

# Standard
import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

# InOrbit
from inorbit_connector.metrics import get_connector_meter

# Local
from gausium_open_platform_connector.src.api.client import VENDOR, GausiumApiClient

logger = logging.getLogger(__name__)

ROBOTS_PAGE_SIZE = 100
ROBOTS_MAX_PAGES = 10
# Serial numbers per batch status request. The API's cost per request grows with the serial
# count and it serves concurrent requests in parallel, so a sweep is split into chunks. The
# size is fixed rather than the count, so requests grow with the fleet, not the chunk.
STATUS_CHUNK_SIZE = 11
# Chunks one sweep may have in flight. The account is capped at 20 requests/second and the
# chunk count grows with the fleet.
MAX_CONCURRENT_CHUNKS = 5

# `upstream.http.duration` times one chunk; this times the whole sweep
_status_poll_duration = get_connector_meter(VENDOR).create_histogram(
    "status_poll.duration",
    unit="s",
    description="Time to read the status of the whole fleet once (attribute: payload)",
    # A sweep takes seconds; the default boundaries sit mostly below that range
    explicit_bucket_boundaries_advisory=[1.0, 2.0, 4.0, 8.0, 16.0, 32.0],
)

# One chunk of a batch status endpoint: ``(serial_numbers, chunk=index)``
BatchStatusFetch = Callable[..., Awaitable[dict[str, dict] | None]]


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
    under its own supervised loops. Each status payload gets its own sweep, so the pose path
    does not wait for the slower v2 endpoint.
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
        # Whether the last sweep of each status payload reached the API
        self._reached: dict[str, bool] = {}
        self._last_status_success: float | None = None

    @property
    def api_connected(self) -> bool:
        """Whether the last sweep of either status endpoint reached the API.

        Tracked per payload and OR-ed here: two loops write it, so a single bool would flap
        as their sweeps interleave. It gates the online mirror and the command guard, which
        must stay open while either endpoint answers.
        """
        return any(self._reached.values())

    @property
    def api_unreachable_secs(self) -> float:
        """Seconds since the last status poll that reached the API.

        ``0.0`` while connected, ``inf`` until the first success, so a connector starting
        against a dead API reports its robots offline on the first tick.
        """
        if self.api_connected:
            return 0.0
        if self._last_status_success is None:
            return math.inf
        return time.monotonic() - self._last_status_success

    def get_state(self, serial_number: str) -> RobotState:
        """Return the cached state for one robot."""
        return self._states[serial_number]

    async def poll_status_v1_once(self) -> None:
        """Sweep the v1 batch status endpoint once and fan the results out per robot.

        Only the v1 payload carries map coordinates, so this is the pose path and it runs
        on its own loop.
        """
        self._fan_out(await self._sweep("v1", self._client.batch_status_v1), "status")

    async def poll_status_v2_once(self) -> None:
        """Sweep the v2 batch status endpoint once and fan the results out per robot."""
        self._fan_out(await self._sweep("v2", self._client.batch_status_v2), "status_v2")

    async def _sweep(self, payload: str, fetch: BatchStatusFetch) -> dict[str, dict] | None:
        """Fetch one status payload for the whole fleet as concurrent chunks.

        Returns the merged per-robot rows, or ``None`` when every chunk failed. A failed
        chunk costs only its own robots one cycle, and the API counts as reached as long as
        one chunk answered.
        """
        chunks = [
            self._serial_numbers[first : first + STATUS_CHUNK_SIZE]
            for first in range(0, len(self._serial_numbers), STATUS_CHUNK_SIZE)
        ]
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHUNKS)

        async def fetch_chunk(index: int, serial_numbers: list[str]) -> dict[str, dict] | None:
            async with semaphore:
                return await fetch(serial_numbers, chunk=index)

        start = time.monotonic()
        results = await asyncio.gather(
            *(fetch_chunk(index, chunk) for index, chunk in enumerate(chunks))
        )
        _status_poll_duration.record(time.monotonic() - start, {"payload": payload})

        fetched = [result for result in results if result is not None]
        self._reached[payload] = bool(fetched)
        if not fetched:
            return None
        self._last_status_success = time.monotonic()
        return {sn: row for result in fetched for sn, row in result.items()}

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
