"""MAV backend using nexus_amr_api.
"""

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

class NexusPythonApi:
    """Async wrapper around nexus_amr_api.AMR."""

    def __init__(self, robot_ip: str, client_ip: str):
        from nexus_amr_api import AMR

        self._amr = AMR(robot_ip, client_ip)
        self._pose_lock = threading.Lock()
        self._latest_pose: Optional[Dict[str, float]] = None
        self._streaming = False
        logger.info(f"AMR initialized (robot={robot_ip}, client={client_ip})")

    def _on_pose(self, pose_stamped):
        with self._pose_lock:
            self._latest_pose = {
                "x": pose_stamped.pose.x,
                "y": pose_stamped.pose.y,
                "theta": pose_stamped.pose.theta,
            }

    async def _run(self, func, *args):
        return await asyncio.to_thread(func, *args)

    async def start_streaming(self):
        if not self._streaming:
            await self._run(self._amr.start_pose2d_streaming, self._on_pose)
            self._streaming = True
            logger.info("Pose2d streaming started")

    async def stop_streaming(self):
        if self._streaming:
            await self._run(self._amr.stop_pose2d_streaming)
            self._streaming = False
            logger.info("Pose2d streaming stopped")

    async def close(self):
        await self.stop_streaming()

    # --- Telemetry ---

    async def health(self) -> bool:
        try:
            await self._run(self._amr.get_state)
            return True
        except Exception:
            return False

    async def get_2d_pose(self) -> Dict[str, float]:
        with self._pose_lock:
            if self._latest_pose:
                return self._latest_pose
        pose = await self._run(self._amr.get_pose2d)
        return {"x": pose.x, "y": pose.y, "theta": pose.theta}

    async def get_state(self) -> Dict[str, Any]:
        state = await self._run(self._amr.get_state)
        return {"state_id": state.state_id, "description": state.description}

    async def get_speed(self) -> float:
        return await self._run(self._amr.get_speed)

    async def get_battery_percentage(self) -> float:
        return await self._run(self._amr.get_battery_percentage)

    async def get_battery_voltage(self) -> float:
        return await self._run(self._amr.get_battery_voltage)

    async def get_position_confidence(self) -> int:
        return await self._run(self._amr.get_position_confidence)

    async def is_on_route(self) -> bool:
        return await self._run(self._amr.is_on_route)

    async def is_in_error(self) -> bool:
        return await self._run(self._amr.is_in_error)

    async def is_estop_button(self) -> bool:
        return await self._run(self._amr.is_estop_button)

    async def is_soft_estop(self) -> bool:
        return await self._run(self._amr.is_soft_estop)

    async def get_amr_sw_version(self) -> str:
        return await self._run(self._amr.get_amr_sw_version)

    async def get_machine_id(self) -> int:
        return await self._run(self._amr.get_machine_id)

    # --- Commands ---

    async def drive_to(self, symbolic_point_id: int, timeout_sec: float = 180):
        await self._run(self._amr.drive_to, symbolic_point_id, timeout_sec)

    async def abort_drive(self):
        await self._run(self._amr.abort_drive)

    async def pause_drive(self):
        await self._run(self._amr.pause_drive)

    async def resume_drive(self):
        await self._run(self._amr.resume_drive)

    async def extend_lifting_units(self, timeout_sec: float = 3600):
        await self._run(self._amr.extend_lifting_units, timeout_sec)

    async def retract_lifting_units(self, timeout_sec: float = 3600):
        await self._run(self._amr.retract_lifting_units, timeout_sec)

    async def lock_amr(self):
        return await self._run(self._amr.lock_amr)

    async def release_amr(self):
        await self._run(self._amr.release_amr)

    async def reset(self, timeout_sec: float = 30):
        return await self._run(self._amr.reset, timeout_sec)

    async def set_navitrol_soft_estop(self, active: bool, timeout_sec: float = 10):
        await self._run(self._amr.set_navitrol_soft_estop, active, timeout_sec)
