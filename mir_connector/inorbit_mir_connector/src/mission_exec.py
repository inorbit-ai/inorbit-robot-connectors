# SPDX-FileCopyrightText: 2024 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT
import asyncio
import logging
import json

from inorbit_connector.connector import CommandResultCode
from inorbit_edge_executor.datatypes import MissionRuntimeOptions
from inorbit_edge_executor.mission import Mission
from inorbit_edge_executor.worker_pool import WorkerPool
from inorbit_edge_executor.db import get_db
from .mir_api import MirApiV2

# Edge-mission execution module for MiR robots. It extends the inorbit-edge-executor module for translating missions
# into MiR language and executing them.
# TODO(b-Tomas): Impleemnt proper translation from InOrbit mission definitions into multi-step MiR missions.
#   - So far, this implements native pause/resume/abort methods for MiR missions.

class MiRWorkerPool(WorkerPool):

    def __init__(self, mir_api: MirApiV2, *args, **kwargs):
        self.mir_api = mir_api
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(name=self.__class__.__name__)

    # @override
    async def pause_mission(self, mission_id):
        """
        Pauses a running mission. If there's no worker for the mission it raises
        MissionNotFoundException(). If the mission is already paused it raises
        InvalidMissionStateException().
        """
        await asyncio.gather(
            super().pause_mission(mission_id),
            # TODO(b-Tomas): add pause/resume methods to the API class or reorganize the code
            self.mir_api.set_state(4),
        )

    # @override
    async def resume_mission(self, mission_id):
        """
        Resumes a paused mission. Paused missions are retrieved from the db, they are serialized
        and they should not be running in a worker. If the mission is finished or not present in
        the db it raises a MissionNotFoundException(). If the mission is not paused it raises
        InvalidMissionStateException().
        """
        await asyncio.gather(
            super().resume_mission(mission_id),
            # TODO(b-Tomas): add pause/resume methods to the API class or reorganize the code
            self.mir_api.set_state(3),
        )

    # @override
    async def abort_mission(self, mission_id):
        """
        Aborts a mission. If the mission is not found it raises a MissionNotFoundException().
        """
        super().abort_mission(mission_id)
        # TODO(b-Tomas): add abort methods to the API class or reorganize the code
        await self.mir_api.abort_all_missions()


class MirMissionExecutor:
    """
    Mission executor for MIR connector using InOrbit edge executor.
    Handles mission submission, pause, resume, and abort operations.
    """

    def __init__(self, robot_id, inorbit_api, mir_api):
        """
        Initialize the mission executor.

        Args:
            robot_id: InOrbit robot ID
            inorbit_api: InOrbit API client instance
            mir_api: MIR robot API client instance
        """
        self.logger = logging.getLogger(name=self.__class__.__name__)
        self.robot_id = robot_id
        self.inorbit_api = inorbit_api
        self.mir_api = mir_api
        self._worker_pool = None
        self._initialized = False

    async def initialize(self):
        """Initialize the worker pool if not already done."""
        if not self._initialized:
            # TODO: Use a proper database
            db = await get_db("dummy")
            self._worker_pool = MiRWorkerPool(
                mir_api=self.mir_api,
                api=self.inorbit_api,
                db=db,
            )
            await self._worker_pool.start()
            self._initialized = True
            self.logger.info("MIR Mission Executor initialized successfully")

    async def shutdown(self):
        """Shutdown the mission executor."""
        if self._worker_pool:
            await self._worker_pool.shutdown()
            self.logger.info("MIR Mission Executor shut down")

    def is_initialized(self) -> bool:
        """Check if the mission executor is initialized."""
        return self._initialized

    async def handle_command(self, script_name: str, script_args: list, options: dict) -> bool:
        """
        Handle mission-related custom commands.

        Args:
            script_name: The command name (e.g., 'cancelMission', 'updateMissionAction')
            script_args: Command arguments as a dictionary
            options: Dictionary containing result_function and other options

        Returns:
            True if the command was handled, False if it should be passed to the next handler
        """
        if not self._initialized:
            self.logger.warning("Mission executor not initialized, cannot handle commands")
            return False

        if script_name == "executeMissionAction":
            await self._handle_execute_mission_action(script_args, options)
            return True
        elif script_name == "cancelMission":
            await self._handle_cancel_mission(script_args, options)
            return True
        elif script_name == "updateMissionAction":
            await self._handle_update_mission_action(script_args, options)
            return True
        else:
            # Not a mission command, let the connector handle it
            return False

    async def _handle_execute_mission_action(self, script_args: dict, options: dict) -> None:
        """Handle executeMissionAction command."""
        self.logger.info(f"Handling executeMissionAction command with arguments: {script_args}")

        try:
            # Parse arguments
            mission_id = script_args.get("missionId")
            mission_definition = json.loads(script_args.get("missionDefinition", "{}"))
            mission_args = json.loads(script_args.get("missionArgs", "{}"))
            mission_options_dict = json.loads(script_args.get("options", "{}"))

            # Create Mission object
            mission = Mission(
                id=mission_id,
                robot_id=self.robot_id,
                definition=mission_definition,
                arguments=mission_args,
            )

            # Convert options dict to MissionRuntimeOptions
            mission_runtime_options = MissionRuntimeOptions(**mission_options_dict)

            # Submit the mission
            # If submission fails, it raises an exception
            await self._worker_pool.submit_work(mission, mission_runtime_options)

            options["result_function"](CommandResultCode.SUCCESS)

        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in mission definition: {e}")
            options["result_function"](
                CommandResultCode.FAILURE,
                execution_status_details=f"Invalid JSON: {e}",
            )
        except Exception as e:
            self.logger.error(f"Failed to execute mission: {e}")
            options["result_function"](
                CommandResultCode.FAILURE,
                execution_status_details=str(e),
            )

    async def _handle_cancel_mission(self, script_args: list, options: dict) -> None:
        """Handle cancelMission command."""
        self.logger.info(f"Handling cancelMission command with arguments: {script_args}")

        mission_id = script_args.get("missionId")
        self.logger.info(f"Handling cancelMission command for mission {mission_id}")

        try:
            result = await self._worker_pool.abort_mission(mission_id)
            self.logger.info(f"Cancelled mission {mission_id}: {result}")
            if result is False:
                options["result_function"](CommandResultCode.FAILURE, "Mission not found")
            else:
                options["result_function"](CommandResultCode.SUCCESS)

        except Exception as e:
            self.logger.error(f"Failed to cancel mission {mission_id}: {e}")
            options["result_function"](
                CommandResultCode.FAILURE,
                execution_status_details=str(e),
            )

    async def _handle_update_mission_action(self, script_args: list, options: dict) -> None:
        """Handle updateMissionAction command."""
        self.logger.info(f"Handling updateMissionAction command with arguments: {script_args}")

        mission_id = script_args.get("missionId")
        action = script_args.get("action")
        self.logger.info(
            f"Handling updateMissionAction command for mission {mission_id} with action {action}"
        )

        try:
            if action == "pause":
                await self._worker_pool.pause_mission(mission_id)
            elif action == "resume":
                await self._worker_pool.resume_mission(mission_id)
            else:
                raise Exception(f"Unknown action: {action}")

            options["result_function"](CommandResultCode.SUCCESS)

        except Exception as e:
            self.logger.error(f"Failed to update mission {mission_id} with action {action}: {e}")
            options["result_function"](
                CommandResultCode.FAILURE,
                execution_status_details=str(e),
            )
