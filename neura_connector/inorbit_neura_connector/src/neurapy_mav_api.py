"""MAV neurapy_mav backend.
"""

import asyncio
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class NeurapyMavApi:
    """Wraps neurapy_mav.Mav with the same async interface as NexusApi."""

    def __init__(self, config_path: str):
        from neurapy_mav.mav import mav_init
        self._mav, status = mav_init(config_path)
        if not status:
            raise RuntimeError(f"mav_init failed for {config_path}")
        logger.info(f"neurapy_mav initialized from {config_path}")

    async def _run(self, func, *args):
        return await asyncio.to_thread(func, *args)

    async def close(self):
        pass

    # --- Telemetry ---

    async def health(self) -> bool:
        try:
            await self._run(self._mav.get_state)
            return True
        except Exception:
            return False

    async def get_2d_pose(self) -> Dict[str, float]:
        pos = await self._run(self._mav.get_position)
        return {"x": pos[0], "y": pos[1], "theta": pos[2]}

    async def get_state(self) -> Dict[str, Any]:
        result = await self._run(self._mav.get_state)
        return {"state_id": result[0], "description": result[1]}

    async def get_speed(self) -> float:
        pos = await self._run(self._mav.get_position)
        return float(pos[3]) if len(pos) > 3 else 0.0

    async def get_battery_percentage(self) -> float:
        return await self._run(self._mav.get_battery_percentage)

    async def get_battery_voltage(self) -> float:
        return await self._run(self._mav.get_battery_voltage)

    async def get_position_confidence(self) -> int:
        return await self._run(self._mav.get_position_confidence)

    async def is_on_route(self) -> bool:
        return await self._run(self._mav.is_on_route)

    async def is_in_error(self) -> bool:
        return await self._run(self._mav.is_in_error)

    async def is_estop_button(self) -> bool:
        return await self._run(self._mav.is_estop_button)

    async def is_soft_estop(self) -> bool:
        return await self._run(self._mav.is_soft_estop)

    async def get_amr_sw_version(self) -> str:
        return await self._run(self._mav.get_mav_sw_version)

    async def get_machine_id(self) -> int:
        return await self._run(self._mav.get_machine_id)

    # --- Commands ---

    async def drive_to(self, symbolic_point_id: int, timeout_sec: float = 180) -> Dict:
        await self._run(self._mav.drive_to, symbolic_point_id, timeout_sec)
        return {"status": "success"}

    async def abort_drive(self) -> Dict:
        await self._run(self._mav.abort_drive)
        return {"status": "success"}

    async def pause_drive(self) -> Dict:
        await self._run(self._mav.pause_drive)
        return {"status": "success"}

    async def resume_drive(self) -> Dict:
        await self._run(self._mav.resume_drive)
        return {"status": "success"}

    async def extend_lifting_units(self, timeout_sec: float = 60) -> Dict:
        await self._run(self._mav.extend_lifting_units, timeout_sec)
        return {"status": "success"}

    async def retract_lifting_units(self, timeout_sec: float = 60) -> Dict:
        await self._run(self._mav.retract_lifting_units, timeout_sec)
        return {"status": "success"}

    async def lock_amr(self) -> Dict:
        await self._run(self._mav.lock_mav)
        return {"status": "success"}

    async def release_amr(self) -> Dict:
        await self._run(self._mav.release_mav)
        return {"status": "success"}

    async def reset(self, timeout_sec: float = 30) -> Dict:
        await self._run(self._mav.reset, timeout_sec)
        return {"status": "success"}

    async def set_navitrol_soft_estop(self, active: bool, timeout_sec: float = 10) -> Dict:
        await self._run(self._mav.set_navitrol_soft_estop, active, timeout_sec)
        return {"status": "success"}
