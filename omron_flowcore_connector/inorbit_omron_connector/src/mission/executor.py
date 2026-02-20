# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Mission execution support for the Omron FlowCore connector."""

from __future__ import annotations

# Standard
import json
import logging
from typing import Any

# InOrbit
from inorbit_connector.connector import CommandFailure, CommandResultCode
from inorbit_edge_executor.datatypes import MissionRuntimeOptions
from inorbit_edge_executor.db import get_db
from inorbit_edge_executor.exceptions import (
    InvalidMissionStateException,
    MissionNotFoundException,
    RobotBusyException,
    TranslationException,
)
from inorbit_edge_executor.inorbit import InOrbitAPI
from inorbit_edge_executor.mission import Mission

# Local
from inorbit_omron_connector.src.omron.api_client import OmronApiClient
from inorbit_omron_connector.src.mission.worker_pool import OmronWorkerPool

LOGGER = logging.getLogger(__name__)


class CustomScripts:
    """Supported custom script names for mission control."""

    EXECUTE_MISSION_ACTION = "executeMissionAction"
    CANCEL_MISSION_ACTION = "cancelMissionAction"
    UPDATE_MISSION_ACTION = "updateMissionAction"


class OmronMissionExecutor:
    """Wrapper around inorbit-edge-executor to run missions for the fleet."""

    def __init__(
        self,
        *,
        api: InOrbitAPI,
        omron_api_client: OmronApiClient,
        robot_id_to_fleet_id: dict[str, str],
        db_path: str | None = None,
        mission_tracking: Any = None,
    ) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)
        self._api = api
        self._db_path = db_path or "sqlite:missions_omron.db"
        self._omron_api_client = omron_api_client
        self._robot_id_to_fleet_id = robot_id_to_fleet_id or {}
        self._mission_tracking = mission_tracking
        self._worker_pool: OmronWorkerPool | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the worker pool if not already started."""
        if self._initialized:
            return

        db = await get_db(self._db_path)
        self._worker_pool = OmronWorkerPool(
            api=self._api,
            db=db,
            api_client=self._omron_api_client,
            robot_id_to_fleet_id=self._robot_id_to_fleet_id,
            mission_tracking=self._mission_tracking,
        )
        await self._worker_pool.start()
        self._initialized = True
        self._logger.info(f"Mission executor initialized with DB {self._db_path}")

    async def shutdown(self) -> None:
        """Shutdown the worker pool gracefully."""
        if self._worker_pool:
            await self._worker_pool.shutdown()
        self._worker_pool = None
        self._initialized = False
        self._logger.info("Mission executor shut down")

    def _report_failure(
        self,
        script_name: str,
        exc: Exception,
        options: dict,
        default_detail: str | None = None,
    ) -> None:
        """Log and propagate command failures through result_function if present."""
        detail = getattr(exc, "execution_status_details", None) or default_detail or str(exc)
        stderr = getattr(exc, "stderr", None)
        self._logger.error(
            "Mission command %s failed: %s (type=%s)", script_name, detail, exc.__class__.__name__,
            exc_info=exc,
        )
        if "result_function" in options:
            options["result_function"](
                CommandResultCode.FAILURE,
                execution_status_details=detail,
                stderr=stderr,
            )

    def _map_worker_pool_error(
        self, exc: Exception, mission_id: str, action: str
    ) -> CommandFailure:
        """Convert worker pool exceptions to CommandFailure with clear messages."""
        if isinstance(exc, RobotBusyException):
            return CommandFailure("Robot is busy with another mission", stderr=str(exc))
        if isinstance(exc, TranslationException):
            return CommandFailure("Failed to translate mission", stderr=str(exc))
        if isinstance(exc, MissionNotFoundException):
            return CommandFailure(f"Mission {mission_id} not found", stderr=str(exc))
        if isinstance(exc, InvalidMissionStateException):
            state_msg = "is not running" if action == "pause" else "is not paused"
            return CommandFailure(f"Mission {mission_id} {state_msg}", stderr=str(exc))
        return CommandFailure(f"Failed to {action} mission {mission_id}", stderr=str(exc))

    async def handle_command(
        self,
        robot_id: str,
        script_name: str,
        script_args: dict[str, Any],
        options: dict,
    ) -> bool:
        """Route mission-related commands. Returns True if handled."""
        if script_name not in {
            CustomScripts.EXECUTE_MISSION_ACTION,
            CustomScripts.CANCEL_MISSION_ACTION,
            CustomScripts.UPDATE_MISSION_ACTION,
        }:
            return False

        if not self._initialized or not self._worker_pool:
            self._logger.warning(f"Mission executor not initialized, cannot handle {script_name}")
            return False

        try:
            if script_name == CustomScripts.EXECUTE_MISSION_ACTION:
                await self._handle_execute_mission_action(robot_id, script_args, options)
                
            elif script_name == CustomScripts.CANCEL_MISSION_ACTION:
                await self._handle_cancel_mission_action(script_args, options)
                
            elif script_name == CustomScripts.UPDATE_MISSION_ACTION:
                await self._handle_update_mission_action(script_args, options)
                
        except CommandFailure as exc:
            self._report_failure(script_name, exc, options)
        except Exception as exc:
            self._report_failure(script_name, exc, options, default_detail="Unexpected error")

        return True

    async def _handle_execute_mission_action(
        self, robot_id: str, args: dict, options: dict
    ) -> None:
        """Handle executeMissionAction command."""
        assert self._worker_pool, "Worker pool not initialized"
        
        mission_robot_id = args.get("robotId") or robot_id
        if not mission_robot_id:
            raise CommandFailure(
                execution_status_details="robotId is required",
                stderr="Missing robotId",
            )
            
        mission_id = args.get("missionId")
        if not mission_id:
             raise CommandFailure(
                execution_status_details="missionId is required",
                stderr="Missing missionId",
            )

        mission_definition = self._parse_json_field(args.get("missionDefinition"))
        mission_args = self._parse_json_field(args.get("missionArgs"))
        mission_options_dict = self._parse_json_field(args.get("options"))
        
        mission = Mission(
            id=mission_id,
            robot_id=mission_robot_id,
            definition=mission_definition,
            arguments=mission_args,
        )
        mission_runtime_options = MissionRuntimeOptions(**mission_options_dict)

        try:
            await self._worker_pool.submit_work(mission, mission_runtime_options)
        except Exception as exc:
            raise self._map_worker_pool_error(exc, mission_id, "submit") from exc
        options["result_function"](CommandResultCode.SUCCESS)

    async def _handle_cancel_mission_action(
        self, args: dict, options: dict
    ) -> None:
        """Handle cancelMissionAction command."""
        assert self._worker_pool
        mission_id = args.get("missionId")
        if not mission_id:
             raise CommandFailure(
                execution_status_details="missionId is required",
                stderr="Missing missionId",
            )
            
        self._logger.info(f"Cancelling mission {mission_id}")
        try:
            result = self._worker_pool.abort_mission(mission_id)
        except Exception as exc:
            # Surface more context to logs and caller
            raise CommandFailure(
                execution_status_details=f"Failed to abort mission {mission_id}",
                stderr=str(exc),
            ) from exc

        if result is False:
            raise CommandFailure(
                execution_status_details=f"Mission {mission_id} not found",
                stderr="Mission not found",
            )

        options["result_function"](CommandResultCode.SUCCESS)

    async def _handle_update_mission_action(
        self, args: dict, options: dict
    ) -> None:
        """Handle updateMissionAction command."""
        assert self._worker_pool
        mission_id = args.get("missionId")
        action = args.get("action")
        
        if not mission_id or not action:
             raise CommandFailure(
                execution_status_details="missionId and action are required",
                stderr="Missing arguments",
            )

        if action == "pause":
            try:
                await self._worker_pool.pause_mission(mission_id)
            except Exception as exc:
                raise self._map_worker_pool_error(exc, mission_id, "pause") from exc
        elif action == "resume":
            try:
                await self._worker_pool.resume_mission(mission_id)
            except Exception as exc:
                raise self._map_worker_pool_error(exc, mission_id, "resume") from exc
        else:
            raise CommandFailure(
                execution_status_details=f"Unknown update action: {action}",
                stderr="Unsupported updateMissionAction",
            )

        options["result_function"](CommandResultCode.SUCCESS)

    @staticmethod
    def _parse_json_field(field_value: Any) -> dict:
        """Parse a JSON string or return dictionaries unchanged."""
        if field_value is None:
            return {}
        if isinstance(field_value, dict):
            return field_value
        if isinstance(field_value, str):
            if field_value.strip() == "":
                return {}
            try:
                parsed = json.loads(field_value)
            except json.JSONDecodeError as exc:
                raise CommandFailure(
                    execution_status_details=f"Invalid JSON provided: {exc}",
                    stderr="Invalid JSON",
                ) from exc
            if not isinstance(parsed, dict):
                raise CommandFailure(
                    execution_status_details="JSON field must parse to an object",
                    stderr="Invalid JSON payload",
                )
            return parsed
        raise CommandFailure(
            execution_status_details="Unsupported field type for JSON parsing",
            stderr=f"Unsupported type: {type(field_value)}",
        )

