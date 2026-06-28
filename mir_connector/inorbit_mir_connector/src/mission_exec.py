# SPDX-FileCopyrightText: 2024 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT
import asyncio
import logging
import json
from enum import Enum
from typing import Optional

from inorbit_connector.commands import CommandResultCode
from inorbit_edge_executor.datatypes import MissionRuntimeOptions
from inorbit_edge_executor.mission import Mission
from inorbit_edge_executor.worker_pool import WorkerPool
from inorbit_edge_executor.db import get_db
from .mir_api import MirApiV2
from .mir_api import SetStateId
from .mir_api.missions_group import MirMissionsGroupHandler
from .mission.behavior_tree import MirBehaviorTreeBuilderContext
from .mission.datatypes import MirInOrbitMission
from .mission.translator import InOrbitToMirTranslator
from .mission.tree_builder import MirTreeBuilder

# Edge-mission execution module for MiR robots. It extends the inorbit-edge-executor module for
# translating InOrbit missions into native multi-step MiR missions and executing them, with
# native pause/resume/abort. Translation is wired via the vendored mission module
# (src/mission/): MirTreeBuilder compiles each mission into a behavior tree whose
# waypoint/nestable-action runs become native MiR missions.


class MissionScriptName(Enum):
    """Mission-related custom commands."""

    EXECUTE_MISSION_ACTION = "executeMissionAction"
    CANCEL_MISSION_ACTION = "cancelMissionAction"
    UPDATE_MISSION_ACTION = "updateMissionAction"


class MirWorkerPool(WorkerPool):

    def __init__(
        self,
        mir_api: MirApiV2,
        *args,
        missions_group: Optional[MirMissionsGroupHandler] = None,
        firmware_version: str = "v3",
        connector_type: str = "",
        **kwargs,
    ):
        self.mir_api = mir_api
        self._missions_group = missions_group
        self._firmware_version = firmware_version
        self._connector_type = connector_type
        super().__init__(*args, behavior_tree_builder=MirTreeBuilder(), **kwargs)
        self.logger = logging.getLogger(name=self.__class__.__name__)

    # @override
    def create_builder_context(self) -> MirBehaviorTreeBuilderContext:
        """Build the MiR-aware context the tree builder needs.

        Carries the MiR API plus the temporary missions-group id, firmware
        version, and connector type. ``submit_work`` fills in mission,
        options, and shared memory afterwards via ``prepare_builder_context``.
        """
        missions_group_id = None
        if self._missions_group is not None:
            missions_group_id = self._missions_group.missions_group_id
        return MirBehaviorTreeBuilderContext(
            mir_api=self.mir_api,
            missions_group_id=missions_group_id,
            firmware_version=self._firmware_version,
            connector_type=self._connector_type,
        )

    # @override
    def translate_mission(self, mission: Mission) -> MirInOrbitMission:
        """Compile an InOrbit mission into a native-MiR mission definition."""
        self.logger.debug(f"Translating mission {mission.id}")
        return InOrbitToMirTranslator.translate(mission=mission)

    # @override
    def deserialize_mission(self, serialized_mission: dict) -> MirInOrbitMission:
        """Rehydrate a persisted mission (e.g. on resume) as a MiR mission."""
        return MirInOrbitMission.model_validate(serialized_mission)

    # @override
    async def pause_mission(self, mission_id):
        """
        Pauses a running mission. If there's no worker for the mission it raises
        MissionNotFoundException(). If the mission is already paused it raises
        InvalidMissionStateException().
        """
        await asyncio.gather(
            super().pause_mission(mission_id),
            self.mir_api.set_state(SetStateId.PAUSE.value),
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
            self.mir_api.set_state(SetStateId.READY.value),
        )

    # @override
    async def abort_mission(self, mission_id):
        """
        Aborts a mission. If the mission is not found it raises a MissionNotFoundException().
        """
        super().abort_mission(mission_id)
        await self.mir_api.abort_all_missions()


class MirMissionExecutor:
    """
    Mission executor for MIR connector using InOrbit edge executor.
    Handles mission submission, pause, resume, and abort operations.
    """

    def __init__(
        self,
        robot_id,
        inorbit_api,
        mir_api,
        database_file=None,
        missions_group: Optional[MirMissionsGroupHandler] = None,
        firmware_version: str = "v3",
        connector_type: str = "",
    ):
        """
        Initialize the mission executor.

        Args:
            robot_id: InOrbit robot ID
            inorbit_api: InOrbit API client instance
            mir_api: MIR robot API client instance
            database_file: Optional path to SQLite database file for mission storage
            missions_group: Handler owning the temporary MiR missions group native
                missions are created in (None disables native translation's group).
            firmware_version: MiR firmware ("v2"/"v3"); selects move-action params.
            connector_type: InOrbit connector type identity, carried on the context.
        """
        self.logger = logging.getLogger(name=self.__class__.__name__)
        self.robot_id = robot_id
        self.inorbit_api = inorbit_api
        self.mir_api = mir_api
        self._missions_group = missions_group
        self._firmware_version = firmware_version
        self._connector_type = connector_type
        # Format database filename for inorbit-edge-executor
        # (expects "sqlite:<filename>" or "dummy")
        if database_file:
            if database_file == "dummy":
                self.database_file = "dummy"
            else:
                self.database_file = f"sqlite:{database_file}"
        else:
            self.database_file = f"sqlite:missions_{robot_id}.db"
        self._worker_pool = None
        self._initialized = False

    async def initialize(self):
        """Initialize the worker pool if not already done."""
        if not self._initialized:
            # Use configurable database filename, defaulting to robot-specific name
            db = await get_db(self.database_file)
            self._worker_pool = MirWorkerPool(
                mir_api=self.mir_api,
                api=self.inorbit_api,
                db=db,
                missions_group=self._missions_group,
                firmware_version=self._firmware_version,
                connector_type=self._connector_type,
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

    async def has_active_mission(self) -> bool:
        """True if an InOrbit-dispatched mission is currently executing for this robot.

        Used by robot-side mission tracking to avoid double-reporting a mission the edge
        executor already owns. Backed by the executor's persisted busy-check (the same
        query ``submit_work`` uses to reject new work for a busy robot), so it stays
        accurate after a mission finishes even though completed workers linger in the
        in-memory pool. Returns False before initialization (no executor, so no
        dispatched mission can be running).
        """
        if not self._initialized or not self._worker_pool:
            return False
        # TODO: this busy-check belongs on WorkerPool itself (it owns the DB). Once
        # inorbit-edge-executor exposes a public `WorkerPool.has_active_mission(robot_id)`,
        # replace the private `_db` access below with
        # `return await self._worker_pool.has_active_mission(self.robot_id)`.
        active = await self._worker_pool._db.fetch_robot_active_mission(self.robot_id)
        return active is not None

    async def handle_command(self, script_name: str, script_args: dict, options: dict) -> bool:
        """
        Handle mission-related custom commands.

        Args:
            script_name: The command name (e.g., 'cancelMissionAction', 'updateMissionAction')
            script_args: Command arguments as a dictionary
            options: Dictionary containing result_function and other options

        Returns:
            True if the command was handled, False if it should be passed to the next handler
        """
        if not self._initialized:
            self.logger.warning("Mission executor not initialized, cannot handle commands")
            return False

        if script_name == MissionScriptName.EXECUTE_MISSION_ACTION.value:
            await self._handle_execute_mission_action(script_args, options)
            return True
        elif script_name == MissionScriptName.CANCEL_MISSION_ACTION.value:
            await self._handle_cancel_mission(script_args, options)
            return True
        elif script_name == MissionScriptName.UPDATE_MISSION_ACTION.value:
            await self._handle_update_mission_action(script_args, options)
            return True
        else:
            # Not a mission command, let the connector handle it
            return False

    async def _handle_execute_mission_action(self, script_args: dict, options: dict) -> None:
        """Handle executeMissionAction command."""
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

    async def _handle_cancel_mission(self, script_args: dict, options: dict) -> None:
        """Handle cancelMission command."""
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

    async def _handle_update_mission_action(self, script_args: dict, options: dict) -> None:
        """Handle updateMissionAction command."""
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
