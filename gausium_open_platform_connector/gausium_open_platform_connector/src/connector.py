# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Gausium Open Platform multi-robot connector for InOrbit."""

# Standard
import asyncio
import math
from functools import partial
from typing import override

# InOrbit
from inorbit_connector.commands import CommandFailure, CommandResultCode, parse_custom_command_args
from inorbit_connector.connector import FleetConnector
from inorbit_connector.models import MapConfigTemp
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND, COMMAND_MESSAGE, COMMAND_NAV_GOAL

# Local
from gausium_open_platform_connector import __version__
from gausium_open_platform_connector.src.api.client import GausiumApiClient
from gausium_open_platform_connector.src.api.data_poller import DataPoller
from gausium_open_platform_connector.src.commands import (
    CleaningModes,
    CustomScripts,
    RemoteNavigationCommandType,
    RemoteTaskCommandType,
)
from gausium_open_platform_connector.src.config.models import GausiumOpenPlatformConnectorConfig
from gausium_open_platform_connector.src.key_values import build_key_values
from gausium_open_platform_connector.src.mission import MissionTracker

ROBOT_DATA_POLL_INTERVAL_SECS = 60.0


class GausiumOpenPlatformConnector(FleetConnector):
    """Connector between the Gausium Open Platform and InOrbit."""

    def __init__(self, config: GausiumOpenPlatformConnectorConfig) -> None:
        """Initialize the connector.

        Args:
            config: Gausium Open Platform connector configuration.
        """
        super().__init__(
            config,
            register_user_scripts=True,
            create_user_scripts_dir=True,
            publish_connector_system_stats=True,
        )
        connector_config = config.connector_config
        self._client = GausiumApiClient(
            base_url=str(connector_config.base_url),
            client_id=connector_config.client_id,
            client_secret=connector_config.client_secret,
            access_key_secret=connector_config.access_key_secret,
            timeout=connector_config.api_timeout,
        )
        # Poses arrive in map pixels; convert to meters before publishing
        self._map_resolution = connector_config.map_resolution
        self._sn_by_robot_id = {robot.robot_id: robot.serial_number for robot in config.fleet}
        self._poller = DataPoller(self._client, list(self._sn_by_robot_id.values()))
        self._trackers = {
            robot_id: MissionTracker(
                serial_number,
                fetch_reports=partial(self._client.get_task_reports_v2, serial_number),
                fetch_report_map_images=partial(self._client.get_report_map_images, serial_number),
                publish=partial(self._publish_mission_tracking, robot_id),
                spawn_task=self._spawn_logged_task,
                success_threshold=connector_config.mission_success_percentage_threshold,
            )
            for robot_id, serial_number in self._sn_by_robot_id.items()
        }
        # Last vendor-reported reachability (status "online" field) per robot, mirrored
        # into the InOrbit online status. See _execution_loop.
        self._vendor_online: dict[str, bool] = {}

    def _send_robot_online_status(self, robot_id: str, online: bool) -> None:
        """Mirror the vendor-reported reachability into the InOrbit online status.

        Uses the same retained state message the MQTT last-will uses.
        TODO: move this into inorbit-connector; _send_robot_status is a private SDK API.
        """
        session = self._get_robot_session(robot_id)
        if session is not None:
            session._send_robot_status(online=online)

    def _publish_mission_tracking(self, robot_id: str, report: dict) -> None:
        """Publish a mission tracking report as an InOrbit event."""
        session = self._get_robot_session(robot_id)
        if session is not None:
            session.publish_key_values({"mission_tracking": report}, is_event=True)

    @override
    async def _connect(self) -> None:
        """Connect to the Gausium Open Platform API and start the polling loops."""
        await self._client.connect()
        await self._poller.poll_status_once()
        await self._poller.poll_robot_data_once()
        self._create_supervised_task("status-poll", self._poll_status_loop)
        self._create_supervised_task("robot-data-poll", self._poll_robot_data_loop)

    async def _poll_status_loop(self) -> None:
        while True:
            await self._poller.poll_status_once()
            await asyncio.sleep(1.0 / self.config.update_freq)

    async def _poll_robot_data_loop(self) -> None:
        while True:
            await self._poller.poll_robot_data_once()
            await asyncio.sleep(ROBOT_DATA_POLL_INTERVAL_SECS)

    @override
    async def _disconnect(self) -> None:
        """Stop mission tracking and close the API client."""
        for tracker in self._trackers.values():
            await tracker.shutdown()
        await self._client.close()

    @override
    async def _execution_loop(self) -> None:
        """Publish the cached state of every robot to InOrbit."""
        for robot_id in self.robot_ids:
            try:
                self._publish_robot(robot_id)
            except Exception:
                self._logger.exception(f"Error publishing data for robot '{robot_id}'")

    def _publish_robot(self, robot_id: str) -> None:
        """Publish one robot's cached state (pose, odometry, missions, key-values)."""
        state = self._poller.get_state(self._sn_by_robot_id[robot_id])
        status = state.status
        if not status:
            return

        # Mirror the vendor cloud's reachability (status "online" field) into the InOrbit
        # online status — the same retained state message the MQTT last-will uses.
        # TODO: move this into inorbit-connector; _send_robot_status is a private SDK API.
        online = status.get("online")
        if isinstance(online, bool) and online != self._vendor_online.get(robot_id):
            # Skip the initial online report: connect already published it
            if robot_id in self._vendor_online and online:
                self._send_robot_online_status(robot_id, True)
            self._vendor_online[robot_id] = online
        if self._vendor_online.get(robot_id) is False:
            # Re-assert every tick: the edge SDK re-sends a retained online=True on every
            # MQTT reconnect, which would otherwise mask the vendor-offline state
            self._send_robot_online_status(robot_id, False)
            # Publishing while vendor-offline would keep refreshing the robot's
            # updateStamp with stale data; keep polling and resume on reconnect
            return

        localization_info = status.get("localizationInfo", {})
        map_position = localization_info.get("mapPosition", {})
        x, y = map_position.get("x"), map_position.get("y")
        # Angle is in degrees, clockwise from the +X axis, in (-180, 180]
        angle = map_position.get("angle")
        # Lost robots publish a map id but no coordinates
        if x is not None and y is not None and angle is not None:
            self.publish_robot_pose(
                robot_id,
                x=x * self._map_resolution,
                y=y * self._map_resolution,
                yaw=math.radians(angle),
                frame_id=localization_info.get("map", {}).get("id") or "map",
            )

        self.publish_robot_odometry(
            robot_id, linear_speed=status.get("speedKilometerPerHour", 0.0) / 3.6
        )

        self._trackers[robot_id].update(status, state.status_v2)

        key_values = {
            **build_key_values(status, state.status_v2),
            "api_connected": state.api_connected,
            "connector_version": __version__,
            "display_name": state.robot_data.get("displayName", ""),
            "model_family": state.robot_data.get("modelFamilyCode", ""),
            "model_type": state.robot_data.get("modelTypeCode", ""),
            "software_version": state.robot_data.get("softwareVersion", ""),
        }
        self.publish_robot_key_values(robot_id, **key_values)

    @override
    def _is_fleet_robot_online(self, robot_id: str) -> bool:
        """Report a robot offline only while the vendor cloud says it is unreachable."""
        return self._vendor_online.get(robot_id, True) is not False

    @override
    async def fetch_robot_map(self, robot_id: str, frame_id: str) -> MapConfigTemp | None:
        """Fetch the robot's current map image from the Gausium Open Platform API.

        Only the v2 status exposes the map version required by the map download API.
        """
        serial_number = self._sn_by_robot_id.get(robot_id)
        if serial_number is None:
            return None
        state = self._poller.get_state(serial_number)
        current_map = state.status_v2.get("localizationInfo", {}).get("map", {})
        map_id, map_name = current_map.get("id"), current_map.get("name")
        if not map_id or not map_name:
            self._logger.warning(f"No current map data available for robot '{robot_id}'")
            return None
        if map_id != frame_id:
            self._logger.warning(
                f"Current map for robot '{robot_id}' doesn't match the requested frame_id: "
                f"map_id={map_id} != frame_id={frame_id}"
            )
            return None
        image_bytes = await self._client.get_map_image(
            serial_number, map_id, map_name, current_map.get("version", "")
        )
        if image_bytes is None:
            return None
        # No orientation correction: map format_version 2 (the default) displays the
        # image exactly as uploaded; only version 1 maps are mirrored by the platform
        return MapConfigTemp(
            image=image_bytes,
            map_id=map_id,
            map_label=map_name,
            origin_x=0.0,
            origin_y=0.0,
            resolution=self._map_resolution,
        )

    @override
    async def _inorbit_robot_command_handler(
        self, robot_id: str, command_name: str, args: list, options: dict
    ) -> None:
        """Handle InOrbit commands for a specific robot.

        Args:
            robot_id: Robot ID that received the command.
            command_name: Name of the command.
            args: Command arguments.
            options: Command options including result_function.
        """
        self._logger.debug(f"Received command '{command_name}' for '{robot_id}': {args}")
        result_fn = options["result_function"]

        if command_name == COMMAND_CUSTOM_COMMAND:
            script_name, script_args = parse_custom_command_args(args)
            if script_name not in CustomScripts:
                # Other custom commands may be handled by the edge-sdk (e.g. user_scripts)
                return

            serial_number = self._sn_by_robot_id[robot_id]
            state = self._poller.get_state(serial_number)
            if not state.api_connected or not state.status.get("online", True):
                raise CommandFailure(
                    execution_status_details="Robot is not available",
                    stderr=f"Robot '{robot_id}' is offline or the API is unreachable",
                )

            match CustomScripts(script_name):
                case CustomScripts.SUBMIT_TASK:
                    area_id = script_args.get("area_id")
                    cleaning_mode = script_args.get("cleaning_mode")
                    if not area_id or cleaning_mode not in CleaningModes.__members__:
                        raise CommandFailure(
                            execution_status_details="Invalid arguments",
                            stderr="submit_task requires area_id and a valid cleaning_mode",
                        )
                    current_map = state.status.get("localizationInfo", {}).get("map", {})
                    map_id, map_name = current_map.get("id"), current_map.get("name")
                    if not map_id or not map_name:
                        raise CommandFailure(
                            execution_status_details="No map data available",
                            stderr=f"Robot '{robot_id}' reported no current map",
                        )
                    await self._client.create_nosite_task(
                        serial_number,
                        task_name="InOrbit task",
                        map_id=map_id,
                        map_name=map_name,
                        area_id=area_id,
                        cleaning_mode=CleaningModes[cleaning_mode].value,
                        loop=False,
                    )
                case CustomScripts.TASK_COMMAND:
                    command = script_args.get("command")
                    if command not in (
                        RemoteTaskCommandType.PAUSE_TASK,
                        RemoteTaskCommandType.RESUME_TASK,
                        RemoteTaskCommandType.STOP_TASK,
                    ):
                        raise CommandFailure(
                            execution_status_details=f"Invalid command {command}",
                            stderr="task_command requires PAUSE_TASK, RESUME_TASK or STOP_TASK",
                        )
                    await self._client.send_remote_task_command(
                        serial_number, RemoteTaskCommandType[command]
                    )
                case CustomScripts.NAVIGATE:
                    command = script_args.get("command")
                    position = script_args.get("position")
                    if (
                        not command
                        or not position
                        or command not in RemoteNavigationCommandType.__members__
                    ):
                        raise CommandFailure(
                            execution_status_details="Invalid arguments",
                            stderr="navigate requires a valid command and a position",
                        )
                    map_name = state.status.get("localizationInfo", {}).get("map", {}).get("name")
                    if not map_name:
                        raise CommandFailure(
                            execution_status_details="No map data available",
                            stderr=f"Robot '{robot_id}' reported no current map",
                        )
                    await self._client.send_remote_navigation_command(
                        serial_number,
                        RemoteNavigationCommandType[command],
                        {"startNavigationParameter": {"map": map_name, "position": position}},
                    )
            result_fn(CommandResultCode.SUCCESS)

        elif command_name in (COMMAND_NAV_GOAL, COMMAND_MESSAGE):
            raise CommandFailure(
                execution_status_details=f"'{command_name}' is not supported",
                stderr=f"The Gausium connector does not support '{command_name}'",
            )
