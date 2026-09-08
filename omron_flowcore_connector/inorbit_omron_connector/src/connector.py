# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""FlowCore fleet connector for InOrbit."""

# Standard
import copy
import logging
from typing import Optional
from typing_extensions import override

# Third Party

# InOrbit
from inorbit_connector.commands import CommandFailure, CommandResultCode
from inorbit_connector.connector import FleetConnector
from inorbit_edge_executor.inorbit import InOrbitAPI

# Local
from .. import __version__
from .key_values import build_health_key_values
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

# Cached items whose upd.millis forms each publish's change token
POSE_KEYS = ("PoseX", "PoseY", "PoseTh")
SUMMARY_KEYS = ("summary",)
TELEMETRY_KEYS = ("StateOfCharge",)

class OmronConnector(FleetConnector):
    """Connector between FlowCore Fleet and InOrbit."""

    def __init__(self, config: FlowCoreConnectorConfig, robot_manager: RobotManager = None) -> None:
        """Initialize the connector.

        Args:
            config: FlowCore connector configuration
            robot_manager: Optional injected RobotManager (for testing)
        """
        # Fills each robot's CPU, RAM and disk defaults with the connector host's real
        # figures instead of zeroes. FlowCore exposes no per-AMR host stats.
        super().__init__(config, publish_connector_system_stats=True)

        api_url = str(config.api_url)

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
            default_update_freq=config.update_freq,
            create_supervised_task=self._create_supervised_task,
        )
        
        # Initialize Mission Tracking
        self._mission_tracking = OmronMissionTracking(
            self.robot_manager.api, create_supervised_task=self._create_supervised_task
        )
        
        # Build robot_id (InOrbit) to fleet_robot_id (FlowCore NameKey) mapping
        self._robot_id_to_fleet_id: dict[str, str] = {}
        for robot_config in config.fleet:
            self._robot_id_to_fleet_id[robot_config.robot_id] = robot_config.fleet_robot_id

        # Last published change token per robot, per publish. Each tier forgets its
        # token when its own precondition next fails, so the first tick after
        # recovery republishes: the summary tier when the API drops, the rest when
        # the robot goes offline.
        self._summary_update_millis: dict[str, tuple] = {}
        self._pose_update_millis: dict[str, tuple] = {}
        self._telemetry_update_millis: dict[str, tuple] = {}
        self._mission_payloads: dict[str, dict] = {}

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
        # Stop the executor and tracker first: they hold the same api client that
        # robot_manager.stop() closes, and a mission worker cancelling mid-call would
        # otherwise reopen it.
        await self._mission_executor.shutdown()
        await self._mission_tracking.stop()
        await self.robot_manager.stop()
        LOGGER.info("Disconnected from FlowCore API.")

    @override
    async def _execution_loop(self) -> None:
        """Main execution loop - publish cached robot data to InOrbit.

        Three tiers, gated on different preconditions because they come from
        different endpoints with different lifetimes:

        - Connector view (health): every tick, ungated.
        - Vendor's view, from `/Robot/UpdatedSince`: gated on its own change token
          and on the API being connected. This is FlowCore's own statement about the
          robot, and it keeps arriving correctly even while the robot itself is
          unreachable, so it must not wait for the robot to be online.
        - Robot telemetry, from `/DataStoreValueLatest`: gated on its own change
          token and on the robot being online. This is the robot's own data, and it
          genuinely goes stale once the robot drops.
        """
        for robot_id in self.robot_ids:
            try:
                fleet_robot_id = self._robot_id_to_fleet_id.get(robot_id)
                if not fleet_robot_id:
                    continue

                api_connected = self.robot_manager.api_connected()

                # Health is the connector's own view. It is never stale and has to keep
                # arriving while nothing else does.
                self.publish_robot_key_values(
                    robot_id,
                    **build_health_key_values(
                        api_connected=api_connected,
                        robot_attached=self.robot_manager.is_attached(fleet_robot_id),
                        connector_version=__version__,
                    ),
                )

                if not api_connected:
                    # Forget the token, so recovery republishes even if FlowCore has
                    # nothing newer than it had before the outage
                    self._summary_update_millis.pop(robot_id, None)
                else:
                    # Token is stored after the publish call, not before: if the
                    # publish raises, the except below skips the store too, so the
                    # next tick sees the same token as unpublished and retries
                    # instead of skipping forever.
                    summary_millis = self.robot_manager.update_millis(
                        fleet_robot_id, SUMMARY_KEYS
                    )
                    if summary_millis is not None and summary_millis != (
                        self._summary_update_millis.get(robot_id)
                    ):
                        if vendor_kv := self.robot_manager.get_vendor_key_values(
                            fleet_robot_id
                        ):
                            self.publish_robot_key_values(robot_id, **vendor_kv)
                        self._summary_update_millis[robot_id] = summary_millis

                if not self._is_fleet_robot_online(robot_id):
                    # Forget the tokens, so recovery republishes even if FlowCore has
                    # nothing newer than it had before the outage
                    self._pose_update_millis.pop(robot_id, None)
                    self._telemetry_update_millis.pop(robot_id, None)
                    self._mission_payloads.pop(robot_id, None)
                    continue

                # Token is stored after the publish calls, not before: if a publish
                # raises, the except below skips the store too, so the next tick sees
                # the same token as unpublished and retries instead of skipping forever.
                pose_millis = self.robot_manager.update_millis(fleet_robot_id, POSE_KEYS)
                if pose_millis is not None and pose_millis != self._pose_update_millis.get(
                    robot_id
                ):
                    if pose := self.robot_manager.get_robot_pose(fleet_robot_id):
                        self.publish_robot_pose(robot_id, **pose)
                    # Odometry rides the pose token; if it starts returning real data,
                    # check that data is actually covered by POSE_KEYS.
                    if odometry := self.robot_manager.get_robot_odometry(fleet_robot_id):
                        self.publish_robot_odometry(robot_id, **odometry)
                    self._pose_update_millis[robot_id] = pose_millis

                kv_millis = self.robot_manager.update_millis(fleet_robot_id, TELEMETRY_KEYS)
                if kv_millis is not None and kv_millis != self._telemetry_update_millis.get(
                    robot_id
                ):
                    if key_values := self.robot_manager.get_robot_key_values(fleet_robot_id):
                        self.publish_robot_key_values(robot_id, **key_values)
                    self._telemetry_update_millis[robot_id] = kv_millis

                # The job streams carry no DataStore token, so the payload itself is
                # the only thing that can say whether the mission changed
                mission_payload = self._mission_tracking.get_mission_tracking(fleet_robot_id)
                if mission_payload and mission_payload != self._mission_payloads.get(robot_id):
                    snapshot = copy.deepcopy(mission_payload)
                    self.publish_robot_key_values(robot_id, mission_tracking=snapshot)
                    self._mission_payloads[robot_id] = snapshot

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

    @override
    def _is_fleet_robot_online(self, robot_id: str) -> bool:
        """Report availability from the Fleet Manager's view of the robot.

        Called once per robot per execution loop iteration and from the edge-SDK
        network thread, so this must stay a cache read.
        """
        fleet_robot_id = self._get_fleet_robot_id(robot_id)
        if fleet_robot_id is None:
            return False
        return self.robot_manager.is_online(fleet_robot_id)

    def _get_fleet_robot_id(self, robot_id: str) -> Optional[str]:
        """Resolve InOrbit robot_id to FlowCore NameKey."""
        return self._robot_id_to_fleet_id.get(robot_id)
