# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""FlowCore fleet connector for InOrbit."""

# Standard
import logging
from typing import Optional
from typing_extensions import override

# Third Party

# InOrbit
from inorbit_connector.connector import (
    CommandFailure,
    CommandResultCode,
    FleetConnector,
)
from inorbit_edge_executor.inorbit import InOrbitAPI

# Local
from .. import __version__
from .omron.robot_manager import RobotManager
from .omron.models import JobCancelByRobotName
from .omron.mock_client import MockOmronClient
from .commands import (
    CommandStop,
    CustomScripts,
    parse_custom_command_args
)
from .config.models import FlowCoreConnectorConfig
from .mission.tracking import OmronMissionTracking
from .mission.executor import OmronMissionExecutor

LOGGER = logging.getLogger(__name__)

class OmronConnector(FleetConnector):
    """Connector between FlowCore Fleet and InOrbit."""

    def __init__(self, config: FlowCoreConnectorConfig, robot_manager: RobotManager = None) -> None:
        """Initialize the connector.

        Args:
            config: FlowCore connector configuration
            robot_manager: Optional injected RobotManager (for testing)
        """
        super().__init__(config)

        # HACK: get the API url from one of the RobotSessions. This value should be expected in the config.
        api_url = self._get_robot_session(self.robot_ids[0]).inorbit_rest_api_endpoint

        # Initialize InOrbit API client
        self.inorbit_api = InOrbitAPI(
            base_url=api_url,
            api_key=config.api_key,
        )
        
        # Initialize API client (Real or Mock)
        api_client = None
        if config.connector_config.use_mock:
            self._logger.info("Using MockOmronClient")
            api_client = MockOmronClient()
            # Seed robots from configuration
            for robot in config.fleet:
                # Seed with custom mock data if provided, else use defaults
                seed_kwargs = robot.mock_data if robot.mock_data else {}
                api_client.seed_robot(robot.fleet_robot_id, **seed_kwargs)
                self._logger.info(f"Seeded mock robot: {robot.fleet_robot_id} with data: {seed_kwargs}")

        # Initialize Robot Manager (Data Layer)
        # We pass the FlowCore specific config part
        self.robot_manager = robot_manager if robot_manager else RobotManager(
            config,
            api_client=api_client,
            default_update_freq=config.update_freq
        )
        
        # Initialize Mission Tracking
        self._mission_tracking = OmronMissionTracking(self.robot_manager.api)
        
        # Build robot_id (InOrbit) to fleet_robot_id (FlowCore NameKey) mapping
        self._robot_id_to_fleet_id: dict[str, str] = {}
        for robot_config in config.fleet:
            self._robot_id_to_fleet_id[robot_config.robot_id] = robot_config.fleet_robot_id

        # Initialize Mission Executor
        self._mission_executor = OmronMissionExecutor(
            api=self.inorbit_api,
            omron_api_client=self.robot_manager.api,
            robot_id_to_fleet_id=self._robot_id_to_fleet_id,
            mission_tracking=self._mission_tracking,
        )

    @override
    async def _connect(self) -> None:
        """Connect to FlowCore API and start polling."""
        await self.robot_manager.start()
        self._mission_tracking.start()
        await self._mission_executor.initialize()
        LOGGER.info("Connected to FlowCore and started polling.")

    @override
    async def _disconnect(self) -> None:
        """Disconnect from FlowCore API and stop polling."""
        await self.robot_manager.stop()
        await self._mission_executor.shutdown()
        await self._mission_tracking.stop()
        LOGGER.info("Disconnected from FlowCore API.")

    @override
    async def _execution_loop(self) -> None:
        """Main execution loop - publish cached robot data to InOrbit."""
        published_count = 0

        for robot_id in self.robot_ids:
            try:
                fleet_robot_id = self._robot_id_to_fleet_id.get(robot_id)
                if not fleet_robot_id:
                    continue

                if pose := self.robot_manager.get_robot_pose(fleet_robot_id):
                    self.publish_robot_pose(robot_id, **pose)
                    published_count += 1

                if odometry := self.robot_manager.get_robot_odometry(fleet_robot_id):
                    self.publish_robot_odometry(robot_id, **odometry)

                key_values = self.robot_manager.get_robot_key_values(fleet_robot_id) or {}
                key_values["connector_version"] = __version__

                if mission_payload := self._mission_tracking.get_mission_tracking(fleet_robot_id):
                    key_values["mission_tracking"] = mission_payload

                if key_values:
                    self.publish_robot_key_values(robot_id, **key_values)

            except Exception as e:
                LOGGER.error(f"Error publishing data for robot {robot_id}: {e}")

    @override
    async def _inorbit_robot_command_handler(
        self, robot_id: str, command_name: str, args: list, options: dict
    ) -> None:
        """Handle InOrbit commands for a specific robot.
        
        Args:
            robot_id: Robot ID that received the command
            command_name: Name of the command (e.g., 'custom_command')
            args: Command arguments
            options: Command options including result_function
        """
        self._logger.debug(
            f"Received command '{command_name}' for robot '{robot_id}'\n"
            f"  Args: {args}\n"
            f"  Options: {options}"
        )

        try:
            fleet_robot_id = self._get_fleet_robot_id(robot_id)

            if command_name == "customCommand":
                script_name, script_args = parse_custom_command_args(args)
            else:
                 raise CommandFailure(
                    stderr=f"Command '{command_name}' not supported",
                    execution_status_details=f"Command '{command_name}' not supported"
                )

            # --- Dispatch based on script name ---

            if script_name == CustomScripts.STOP:
                if not fleet_robot_id:
                     raise CommandFailure(stderr=f"No configuration found for robot {robot_id}", execution_status_details="Config Error")

                cmd = CommandStop(**script_args)
                job_cancel = JobCancelByRobotName(
                    robot=fleet_robot_id,
                    cancelReason=cmd.reason
                )
                
                success = await self.robot_manager.api.stop(job_cancel.model_dump())
                if not success:
                    raise CommandFailure(stderr="Failed to cancel job in FlowCore", execution_status_details="API Error")

            elif script_name in (
                CustomScripts.PAUSE_ROBOT, 
                CustomScripts.RESUME_ROBOT, 
                CustomScripts.DOCK, 
                CustomScripts.UNDOCK, 
                CustomScripts.SHUTDOWN
            ):
                if not fleet_robot_id:
                    raise CommandFailure(stderr=f"No configuration found for robot {robot_id}", execution_status_details="Config Error")
                
                client = await self.robot_manager.get_arcl_client(fleet_robot_id)

                if script_name == CustomScripts.PAUSE_ROBOT:
                    await client.set_block_driving(
                        name="inorbit_traffic",
                        short_desc="Paused by InOrbit",
                        long_desc="Paused by InOrbit Traffic Zone"
                    )

                elif script_name == CustomScripts.RESUME_ROBOT:
                    await client.clear_block_driving(name="inorbit_traffic")
                    await client.go()

                elif script_name == CustomScripts.DOCK:
                    await client.dock()

                elif script_name == CustomScripts.UNDOCK:
                    await client.undock()

                elif script_name == CustomScripts.SHUTDOWN:
                    await client.shutdown_robot()

            elif await self._mission_executor.handle_command(
                robot_id, script_name, script_args, options
            ):
                return

            else:
                 raise CommandFailure(
                    stderr=f"Script '{script_name}' not implemented",
                    execution_status_details="Not Implemented"
                )

        except CommandFailure:
            raise
        except Exception as e:
            self._logger.error(f"Error processing command {command_name}: {e}")
            raise CommandFailure(stderr=str(e), execution_status_details="Internal Error")

        # Indicate success
        options["result_function"](CommandResultCode.SUCCESS)

    def _get_fleet_robot_id(self, robot_id: str) -> Optional[str]:
        """Resolve InOrbit robot_id to FlowCore NameKey."""
        return self._robot_id_to_fleet_id.get(robot_id)
