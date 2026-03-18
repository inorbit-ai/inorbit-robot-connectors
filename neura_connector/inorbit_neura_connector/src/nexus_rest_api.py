"""MAV REST API backend (mav_api_server_rest on port 9000).

Provides the same async interface as NexusApi so the connector
can switch backends transparently via config.
"""

import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class NexusRestApi:
    """Async HTTP client for the MAV REST API."""

    def __init__(self, host: str, port: int = 9000, timeout: float = 5.0):
        self._base_url = f"http://{host}:{port}/api/v1"
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        logger.info(f"REST API target: {self._base_url}")

    async def _ensure_client(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _get(self, path: str) -> Dict[str, Any]:
        await self._ensure_client()
        resp = await self._client.get(f"{self._base_url}{path}")
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, json: Optional[Dict] = None) -> Dict[str, Any]:
        await self._ensure_client()
        resp = await self._client.post(f"{self._base_url}{path}", json=json or {})
        resp.raise_for_status()
        return resp.json()

    # --- Telemetry ---

    async def health(self) -> bool:
        try:
            data = await self._get("/health")
            return data.get("status") == "success"
        except Exception:
            return False

    async def get_2d_pose(self) -> Dict[str, float]:
        data = await self._get("/get_2d_pose")
        return data.get("data", data)

    async def get_state(self) -> Dict[str, Any]:
        data = await self._get("/get_state")
        return data.get("data", data)

    async def get_speed(self) -> float:
        data = await self._get("/get_speed")
        return float(data.get("data", {}).get("value", 0))

    async def get_battery_percentage(self) -> float:
        data = await self._get("/get_battery_percentage")
        return float(data.get("data", {}).get("value", 0))

    async def get_battery_voltage(self) -> float:
        data = await self._get("/get_battery_voltage")
        return float(data.get("data", {}).get("value", 0))

    async def get_position_confidence(self) -> int:
        data = await self._get("/get_position_confidence")
        return int(data.get("data", {}).get("value", 0))

    async def is_on_route(self) -> bool:
        data = await self._get("/is_on_route")
        return bool(data.get("data", {}).get("value", False))

    async def is_in_error(self) -> bool:
        data = await self._get("/is_in_error")
        return bool(data.get("data", {}).get("value", False))

    async def is_estop_button(self) -> bool:
        data = await self._get("/is_estop_button")
        return bool(data.get("data", {}).get("value", False))

    async def is_soft_estop(self) -> bool:
        data = await self._get("/is_soft_estop")
        return bool(data.get("data", {}).get("value", False))

    async def get_amr_sw_version(self) -> str:
        data = await self._get("/get_amr_sw_version")
        return str(data.get("data", {}).get("value", ""))

    async def get_machine_id(self) -> int:
        data = await self._get("/get_machine_id")
        return int(data.get("data", {}).get("value", 0))

    # --- Commands ---

    async def drive_to(self, symbolic_point_id: int, timeout_sec: float = 180):
        await self._post("/drive_to", {"symbolic_point_id": symbolic_point_id, "timeout_sec": timeout_sec})

    async def abort_drive(self):
        await self._post("/abort_drive")

    async def pause_drive(self):
        await self._post("/pause_drive")

    async def resume_drive(self):
        await self._post("/resume_drive")

    async def extend_lifting_units(self, timeout_sec: float = 3600):
        await self._post("/extend_lifting_units", {"timeout_sec": timeout_sec})

    async def retract_lifting_units(self, timeout_sec: float = 3600):
        await self._post("/retract_lifting_units", {"timeout_sec": timeout_sec})

    async def lock_amr(self):
        await self._post("/lock_amr")

    async def release_amr(self):
        await self._post("/release_amr")

    async def reset(self, timeout_sec: float = 30):
        await self._post("/reset", {"timeout_sec": timeout_sec})

    async def set_navitrol_soft_estop(self, active: bool, timeout_sec: float = 10):
        await self._post("/set_navitrol_soft_estop", {"active": active, "timeout_sec": timeout_sec})
