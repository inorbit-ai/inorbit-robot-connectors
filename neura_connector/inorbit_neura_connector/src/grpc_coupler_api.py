"""gRPC backend — wraps nrc_grpc_client's MavClient + ArmClient.

Provides async interface over the synchronous gRPC stubs.
Requires `nrc_grpc_client` to be installed (pip install -e /path/to/nrc_grpc_client).
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class GrpcCouplerApi:
    """Async wrapper around nrc_grpc_client for MAV + Arm gRPC services."""

    def __init__(self, server_address: str = "0.0.0.0:50051"):
        from nrc_grpc_client.grpc_interface import MavClient, ArmClient

        self._server_address = server_address
        self._mav_client = MavClient(server_address)
        self._arm_client = ArmClient(server_address)
        logger.info(f"gRPC coupler initialized at {server_address}")

    async def _run(self, func, *args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    async def close(self):
        pass

    # ------------------------------------------------------------------
    # MAV gRPC (MavService)
    # ------------------------------------------------------------------

    async def drive_to_blocking(self, symbolic_point: int) -> Tuple[bool, str]:
        return await self._run(self._mav_client.drive_to_blocking, symbolic_point)

    async def is_target_reached(self, symbolic_point: int) -> Tuple[bool, str]:
        return await self._run(self._mav_client.is_target_reached, symbolic_point)

    # ------------------------------------------------------------------
    # Arm gRPC — connection / lifecycle
    # ------------------------------------------------------------------

    async def arm_connection(self, timeout: float = 10.0) -> Tuple[bool, str]:
        return await self._run(self._arm_client.arm_connection, timeout)

    async def power_on_arm(self) -> Tuple[bool, str]:
        return await self._run(self._arm_client.power_on_arm)

    async def power_off_arm(self) -> Tuple[bool, str]:
        return await self._run(self._arm_client.power_off_arm)

    async def switch_to_automatic_mode(self) -> Tuple[bool, str]:
        return await self._run(self._arm_client.switch_to_automatic_mode)

    async def set_override(self, override: float) -> Tuple[bool, str]:
        return await self._run(self._arm_client.set_override, override)

    async def reset_collision(self) -> Tuple[bool, str]:
        return await self._run(self._arm_client.reset_collision)

    async def stop_arm(self) -> Tuple[bool, str]:
        return await self._run(self._arm_client.stop_arm)

    async def get_status(self) -> Tuple[bool, str]:
        return await self._run(self._arm_client.get_status)

    # ------------------------------------------------------------------
    # Arm gRPC — motion
    # ------------------------------------------------------------------

    async def move_joint(
        self,
        gui_point: Optional[str] = None,
        target_joint: Optional[List[List[float]]] = None,
        speed: float = 0.0,
        acceleration: float = 0.0,
        current_joint_angles: Optional[List[float]] = None,
        safety_toggle: bool = False,
        enable_blending: bool = False,
    ) -> Tuple[bool, str]:
        return await self._run(
            self._arm_client.move_joint,
            gui_point=gui_point,
            target_joint=target_joint,
            speed=speed,
            acceleration=acceleration,
            current_joint_angles=current_joint_angles or [],
            safety_toggle=safety_toggle,
            enable_blending=enable_blending,
        )

    async def move_linear(
        self,
        gui_point: Optional[str] = None,
        target_pose: Optional[List[List[float]]] = None,
        speed: float = 0.0,
        acceleration: float = 0.0,
        jerk: float = 0.0,
        rotation_speed: float = 0.0,
        rotation_acceleration: float = 0.0,
        rotation_jerk: float = 0.0,
        blending: bool = False,
        blending_mode: int = 0,
        blend_radius: float = 0.0,
        current_joint_angles: float = 0.0,
        safety_toggle: bool = False,
    ) -> Tuple[bool, str]:
        return await self._run(
            self._arm_client.move_linear,
            gui_point=gui_point,
            target_pose=target_pose,
            speed=speed,
            acceleration=acceleration,
            jerk=jerk,
            rotation_speed=rotation_speed,
            rotation_acceleration=rotation_acceleration,
            rotation_jerk=rotation_jerk,
            blending=blending,
            blending_mode=blending_mode,
            blend_radius=blend_radius,
            current_joint_angles=current_joint_angles,
            safety_toggle=safety_toggle,
        )

    async def current_joint_angles(self) -> Tuple[List[float], str]:
        return await self._run(self._arm_client.current_joint_angles)

    # ------------------------------------------------------------------
    # Arm gRPC — programs
    # ------------------------------------------------------------------

    async def run_program(
        self,
        name: str,
        loop_count: int = 1,
        background_run: bool = False,
        delay: float = 0.0,
    ) -> Tuple[bool, str]:
        return await self._run(
            self._arm_client.run_program,
            name=name,
            loop_count=loop_count,
            background_run=background_run,
            delay=delay,
        )

    async def end_program(self) -> Tuple[bool, str]:
        return await self._run(self._arm_client.end_program)

    async def pause_arm(self) -> Tuple[bool, str]:
        return await self._run(self._arm_client.pause_arm)

    async def resume_arm(self) -> Tuple[bool, str]:
        return await self._run(self._arm_client.resume_arm)

    async def get_program_status(self) -> Tuple[bool, str]:
        return await self._run(self._arm_client.get_program_status)

    # ------------------------------------------------------------------
    # Arm gRPC — gripper / tools / IO
    # ------------------------------------------------------------------

    async def grasp(self) -> Tuple[bool, str]:
        return await self._run(self._arm_client.grasp)

    async def release(self) -> Tuple[bool, str]:
        return await self._run(self._arm_client.release)

    async def set_tool(self, name: str) -> Tuple[bool, str]:
        return await self._run(self._arm_client.set_tool, name)

    async def gripper_power(self, state: str) -> Tuple[bool, str]:
        return await self._run(self._arm_client.gripper_power, state)

    async def set_io(self, io_name: str, io_value: bool) -> Tuple[bool, str]:
        return await self._run(self._arm_client.set_io, io_name, io_value)

    async def get_io(self, io_name: str) -> Tuple[bool, bool, str]:
        return await self._run(self._arm_client.get_io, io_name)

    # ------------------------------------------------------------------
    # Arm gRPC — audio
    # ------------------------------------------------------------------

    async def play_audio_on_maira(self, name: str) -> Tuple[bool, str]:
        return await self._run(self._arm_client.play_audio_on_maira, name)
