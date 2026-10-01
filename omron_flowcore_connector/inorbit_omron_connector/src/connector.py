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
from .omron.arcl_client import BLOCK_DRIVING_FAULT
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

# Cached items the summary tier is gated on: upd.millis is a real change token on
# /Robot/UpdatedSince, and the charge state and faults it does not cover.
SUMMARY_KEYS = ("summary",)
CHARGE_KEYS = ("ChargeStateNumber",)


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

        # Last published summary token per robot. Forgotten while the API is down, so
        # the first tick after recovery republishes even if FlowCore has nothing newer.
        self._vendor_tokens: dict[str, tuple] = {}
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
        - Robot telemetry, from `/DataStoreValueLatest`: gated on `is_reporting`,
          published every tick while it holds. Every call to that endpoint fetches
          from the AMR, so an unchanged value is a fresh observation that the robot
          is parked, not a stale one; withholding it is what left gaps in an idle
          robot's pose and battery timelines. `is_reporting` going false is the one
          case where the cache really is old. No online check on top of it: a
          reachable robot's live pose is what an operator needs whatever its status.
        """
        for robot_id in self.robot_ids:
            try:
                fleet_robot_id = self._get_fleet_robot_id(robot_id)
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
                        offline_reason=self.robot_manager.offline_reason(fleet_robot_id),
                    ),
                )

                if not api_connected:
                    # Forget the token, so recovery republishes even if FlowCore has
                    # nothing newer than it had before the outage
                    self._vendor_tokens.pop(robot_id, None)
                else:
                    # Token is stored after the publish call, not before: if the
                    # publish raises, the except below skips the store too, so the
                    # next tick sees the same token as unpublished and retries
                    # instead of skipping forever.
                    summary_millis = self.robot_manager.update_millis(
                        fleet_robot_id, SUMMARY_KEYS
                    )
                    vendor_token = (
                        summary_millis,
                        self.robot_manager.data_values(fleet_robot_id, CHARGE_KEYS),
                        # The summary stamp does not move when a robot is held.
                        self.robot_manager.active_fault_names(fleet_robot_id),
                    )
                    if summary_millis is not None and vendor_token != (
                        self._vendor_tokens.get(robot_id)
                    ):
                        if vendor_kv := self.robot_manager.get_vendor_key_values(
                            fleet_robot_id
                        ):
                            self.publish_robot_key_values(robot_id, **vendor_kv)
                        self._vendor_tokens[robot_id] = vendor_token

                if self.robot_manager.is_reporting(fleet_robot_id):
                    if pose := self.robot_manager.get_robot_pose(fleet_robot_id):
                        self.publish_robot_pose(robot_id, **pose)
                    if odometry := self.robot_manager.get_robot_odometry(fleet_robot_id):
                        self.publish_robot_odometry(robot_id, **odometry)
                    if key_values := self.robot_manager.get_robot_key_values(fleet_robot_id):
                        self.publish_robot_key_values(robot_id, **key_values)

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
                CustomScripts.SHUTDOWN,
                CustomScripts.EXECUTE_MACRO
            ):
                if not fleet_robot_id:
                    raise CommandFailure(stderr=f"No configuration found for robot {robot_id}", execution_status_details="Config Error")

                client = await self.robot_manager.get_arcl_client(fleet_robot_id)

                if script_name == CustomScripts.PAUSE_ROBOT:
                    await client.set_block_driving(
                        name=BLOCK_DRIVING_FAULT,
                        short_desc="Paused by InOrbit",
                        long_desc="Paused by InOrbit Traffic Zone"
                    )

                elif script_name == CustomScripts.RESUME_ROBOT:
                    await client.clear_block_driving(name=BLOCK_DRIVING_FAULT)
                    await client.go()

                elif script_name == CustomScripts.DOCK:
                    await client.dock()

                elif script_name == CustomScripts.UNDOCK:
                    await client.undock()

                elif script_name == CustomScripts.SHUTDOWN:
                    await client.shutdown_robot()

                elif script_name == CustomScripts.EXECUTE_MACRO:
                    macro = str(script_args.get("macro") or "").strip()
                    if not macro:
                        raise CommandFailure(
                            stderr="Missing macro",
                            execution_status_details="macro is required"
                        )
                    await client.execute_macro(macro)

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
