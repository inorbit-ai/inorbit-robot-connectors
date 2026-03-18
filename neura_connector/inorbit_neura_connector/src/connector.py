"""NEURA <-> InOrbit connector.

Polls the robot for telemetry and publishes to InOrbit.
Receives commands from InOrbit and dispatches them to the robot.
"""

import asyncio
import json
import logging
from pathlib import Path

import yaml as pyyaml

from inorbit_connector.connector import Connector, CommandResultCode
from inorbit_connector.models import MapConfigTemp
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND, COMMAND_MESSAGE, COMMAND_NAV_GOAL

from inorbit_neura_connector import get_module_version
from inorbit_neura_connector.config.connector_model import RobotConfig
from inorbit_neura_connector.src.mission_executor import MissionExecutor

logger = logging.getLogger(__name__)

MAV_STATES = {
    1: "START",
    2: "STANDBY",
    3: "AUTO",
    4: "FSTOP",
    5: "LOAD",
    6: "HOLD",
    7: "MANUAL",
    8: "PAUSE",
}


class NeuraConnector(Connector):
    """Bridges a NEURA robot with InOrbit."""

    def __init__(self, robot_config: RobotConfig) -> None:
        from inorbit_connector.models import ConnectorConfig
        config = ConnectorConfig(
            connector_type=robot_config.robot_type,
            connector_version=get_module_version(),
            api_key=robot_config.inorbit_api_key or "",
            connector_config={"serial_number": robot_config.serial_number},
            fleet=[{"robot_id": robot_config.robot_name}],
        )
        super().__init__(
            robot_id=robot_config.robot_name,
            config=config,
        )

        self.robot_config = robot_config
        self._backend = robot_config.backend_type

        if self._backend == "nexus_python":
            from .nexus_python_api import NexusPythonApi
            self.api = NexusPythonApi(
                robot_ip=robot_config.robot_ip,
                client_ip=robot_config.client_ip,
            )
        elif self._backend == "nexus_rest":
            from .nexus_rest_api import NexusRestApi
            self.api = NexusRestApi(
                host=robot_config.rest_api_ip,
                port=robot_config.rest_api_port,
            )
        elif self._backend == "neurapy_mav":
            from .neurapy_mav_api import NeurapyMavApi
            self.api = NeurapyMavApi(config_path=robot_config.mav_config_path)
        else:
            raise ValueError(f"Unknown backend: {self._backend}")

        self._map_frame_id = robot_config.map_frame_id
        self._map_config = self._load_map_from_yaml(robot_config.map_yaml_path)

        self._api_connected = False
        self._sw_version: str = ""
        self._machine_id: int = 0
        self._mission_executor: MissionExecutor | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _is_robot_online(self) -> bool:
        return self._api_connected

    async def _connect(self) -> None:
        try:
            self._sw_version = await self.api.get_amr_sw_version()
            self._machine_id = await self.api.get_machine_id()
            if hasattr(self.api, "start_streaming"):
                await self.api.start_streaming()
            self._api_connected = True
            self._mission_executor = MissionExecutor(
                api=self.api,
                publish_fn=self.publish_key_values,
            )
            self._logger.info(
                f"Connected to {self.robot_config.robot_type} "
                f"'{self.robot_config.robot_name}' via {self._backend}"
            )
        except Exception as exc:
            self._logger.warning(f"Initial connection failed, will retry: {exc}")

    async def _disconnect(self) -> None:
        await self.api.close()

    # ------------------------------------------------------------------
    # Map
    # ------------------------------------------------------------------

    def _load_map_from_yaml(self, map_yaml_path: str | None) -> MapConfigTemp | None:
        if not map_yaml_path:
            return None
        yaml_path = Path(map_yaml_path)
        if not yaml_path.is_file():
            self._logger.warning(f"Map YAML not found: {yaml_path}")
            return None
        try:
            with open(yaml_path, "r") as f:
                meta = pyyaml.safe_load(f)
            image_file = yaml_path.parent / meta["image"]
            if not image_file.is_file():
                alt = image_file.with_suffix(".png")
                image_file = alt if alt.is_file() else image_file
            if not image_file.is_file():
                self._logger.warning(f"Map image not found: {image_file}")
                return None
            resolution = float(meta["resolution"])
            origin = meta.get("origin", [0.0, 0.0, 0.0])
            image_bytes = image_file.read_bytes()
            self._logger.info(
                f"Loaded map {image_file.name} "
                f"(res={resolution}, origin=[{origin[0]}, {origin[1]}], "
                f"{len(image_bytes)} bytes)"
            )
            return MapConfigTemp(
                image=image_bytes,
                map_id=self._map_frame_id,
                map_label=yaml_path.stem,
                origin_x=float(origin[0]),
                origin_y=float(origin[1]),
                resolution=resolution,
            )
        except Exception as exc:
            self._logger.error(f"Failed to load map: {exc}")
            return None

    async def fetch_map(self, frame_id: str) -> MapConfigTemp | None:
        if self._map_config and self._map_config.map_id == frame_id:
            self._logger.info(f"Serving map for frame '{frame_id}'")
            return self._map_config
        return None

    # ------------------------------------------------------------------
    # Telemetry loop — MAV
    # ------------------------------------------------------------------

    async def _execution_loop(self) -> None:
        kv = {
            "connector_version": get_module_version(),
            "robot_name": self.robot_config.robot_name,
            "robot_type": self.robot_config.robot_type,
            "serial_number": self.robot_config.serial_number,
            "machine_id": self._machine_id,
            "backend": self._backend,
        }

        try:
            if not await self.api.health():
                if self._api_connected:
                    self._logger.warning("Health check failed")
                self._api_connected = False
                self.publish_key_values(api_connected=False)
                return
            self._api_connected = True
        except Exception:
            self._api_connected = False
            self.publish_key_values(api_connected=False)
            return

        try:
            pose, state, speed, batt_pct, batt_v = await asyncio.gather(
                self.api.get_2d_pose(),
                self.api.get_state(),
                self.api.get_speed(),
                self.api.get_battery_percentage(),
                self.api.get_battery_voltage(),
            )
        except Exception as exc:
            self._logger.error(f"Telemetry poll error: {exc}")
            return

        x = float(pose.get("x", 0))
        y = float(pose.get("y", 0))
        theta = float(pose.get("theta", 0))
        self.publish_pose(x=x, y=y, yaw=theta, frame_id=self._map_frame_id)
        self.publish_odometry(linear_speed=speed, angular_speed=0.0)

        extras = {"pos_confidence": 0, "is_on_route": False, "is_in_error": False,
                  "is_estop": False, "is_soft_estop": False}
        try:
            (extras["pos_confidence"], extras["is_on_route"], extras["is_in_error"],
             extras["is_estop"], extras["is_soft_estop"]) = await asyncio.gather(
                self.api.get_position_confidence(),
                self.api.is_on_route(),
                self.api.is_in_error(),
                self.api.is_estop_button(),
                self.api.is_soft_estop(),
            )
        except Exception:
            pass

        state_id = state.get("state_id", 0)
        kv.update({
            "api_connected": True,
            "sw_version": self._sw_version,
            "state_id": state_id,
            "state_text": state.get("description", MAV_STATES.get(state_id, "UNKNOWN")),
            "battery percent": batt_pct / 100.0,
            "battery_voltage": batt_v,
            "speed": speed,
            **extras,
        })
        self.publish_key_values(**kv)

    # ------------------------------------------------------------------
    # Commands (InOrbit -> robot)
    # ------------------------------------------------------------------

    async def _inorbit_command_handler(self, command_name, args, options):
        self._logger.info(f"Command '{command_name}' ({len(args)} args)")
        result_fn = options.get("result_function", lambda *a, **kw: None)

        if command_name == COMMAND_CUSTOM_COMMAND:
            await self._handle_custom_command(args, options)

        elif command_name == COMMAND_NAV_GOAL:
            self._logger.warning("NAV_GOAL not supported — use 'drive_to --point_id <id>'")
            result_fn(CommandResultCode.FAILURE,
                      execution_status_details="Use 'drive_to' with --point_id instead")

        elif command_name == COMMAND_MESSAGE:
            msg = args[0] if args else ""
            if msg == "inorbit_pause":
                await self.api.pause_drive()
                result_fn(CommandResultCode.SUCCESS)
            elif msg == "inorbit_resume":
                await self.api.resume_drive()
                result_fn(CommandResultCode.SUCCESS)
            else:
                self._logger.warning(f"Unknown message: {msg}")

    async def _handle_custom_command(self, args, options):
        result_fn = options.get("result_function", lambda *a, **kw: None)
        if len(args) < 2:
            return result_fn(CommandResultCode.FAILURE,
                             execution_status_details="Expected >=2 arguments")

        cmd = args[0]
        raw = list(args[1])
        params = {}
        if isinstance(raw, list) and len(raw) % 2 == 0:
            params = dict(zip(raw[::2], raw[1::2]))
        else:
            return result_fn(CommandResultCode.FAILURE,
                             execution_status_details="Invalid arguments")

        try:
            # --- Mission commands ---
            if cmd == "executeMissionAction":
                await self._handle_execute_mission(params, result_fn)
                return
            elif cmd == "cancelMissionAction":
                await self._handle_cancel_mission(params, result_fn)
                return
            elif cmd == "updateMissionAction":
                await self._handle_update_mission(params, result_fn)
                return

            # --- Single-step commands ---
            if cmd == "drive_to":
                pid = int(params.get("--point_id", params.get("point_id", 0)))
                await self.api.drive_to(pid, float(params.get("--timeout", 180)))
            elif cmd == "abort_drive":
                await self.api.abort_drive()
            elif cmd == "pause_drive":
                await self.api.pause_drive()
            elif cmd == "resume_drive":
                await self.api.resume_drive()
            elif cmd == "extend_lifting":
                await self.api.extend_lifting_units()
            elif cmd == "retract_lifting":
                await self.api.retract_lifting_units()
            elif cmd == "lock_amr":
                await self.api.lock_amr()
            elif cmd == "release_amr":
                await self.api.release_amr()
            elif cmd == "reset":
                await self.api.reset()
            elif cmd == "soft_estop":
                active = params.get("--active", "true").lower() == "true"
                await self.api.set_navitrol_soft_estop(active)
            else:
                return result_fn(CommandResultCode.FAILURE,
                                 execution_status_details=f"Unknown command: {cmd}")
            result_fn(CommandResultCode.SUCCESS)
        except Exception as exc:
            self._logger.error(f"Command '{cmd}' failed: {exc}")
            result_fn(CommandResultCode.FAILURE, execution_status_details=str(exc))

    # ------------------------------------------------------------------
    # Mission handling
    # ------------------------------------------------------------------

    async def _handle_execute_mission(self, params, result_fn):
        if not self._mission_executor:
            return result_fn(CommandResultCode.FAILURE,
                             execution_status_details="Not connected")
        try:
            mission_id = params.get("missionId", params.get("--missionId", ""))
            definition = json.loads(params.get("missionDefinition", params.get("--missionDefinition", "{}")))
            mission_args = json.loads(params.get("missionArgs", params.get("--missionArgs", "{}")))
            await self._mission_executor.execute(mission_id, definition, mission_args)
            result_fn(CommandResultCode.SUCCESS)
        except Exception as exc:
            self._logger.error(f"Mission execute failed: {exc}")
            result_fn(CommandResultCode.FAILURE, execution_status_details=str(exc))

    async def _handle_cancel_mission(self, params, result_fn):
        if not self._mission_executor:
            return result_fn(CommandResultCode.FAILURE,
                             execution_status_details="Not connected")
        try:
            await self._mission_executor.cancel()
            result_fn(CommandResultCode.SUCCESS)
        except Exception as exc:
            self._logger.error(f"Mission cancel failed: {exc}")
            result_fn(CommandResultCode.FAILURE, execution_status_details=str(exc))

    async def _handle_update_mission(self, params, result_fn):
        if not self._mission_executor:
            return result_fn(CommandResultCode.FAILURE,
                             execution_status_details="Not connected")
        action = params.get("action", params.get("--action", ""))
        try:
            if action == "pause":
                await self._mission_executor.pause()
            elif action == "resume":
                await self._mission_executor.resume()
            else:
                return result_fn(CommandResultCode.FAILURE,
                                 execution_status_details=f"Unknown action: {action}")
            result_fn(CommandResultCode.SUCCESS)
        except Exception as exc:
            self._logger.error(f"Mission update failed: {exc}")
            result_fn(CommandResultCode.FAILURE, execution_status_details=str(exc))
