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
from gausium_open_platform_connector.src.api.data_poller import DataPoller, RobotState
from gausium_open_platform_connector.src.canonical import report_times
from gausium_open_platform_connector.src.commands import (
    CleaningModes,
    CustomScripts,
    RemoteNavigationCommandType,
    RemoteTaskCommandType,
)
from gausium_open_platform_connector.src.config.models import GausiumOpenPlatformConnectorConfig
from gausium_open_platform_connector.src.key_values import (
    build_health_key_values,
    build_key_values,
)
from gausium_open_platform_connector.src.mission import MissionTracker

ROBOT_DATA_POLL_INTERVAL_SECS = 60.0
# Nominal v2 status interval; the real period is max(v2 sweep, this). Only the v2 payload
# carries the mission id, so it bounds mission-event latency, not the pose rate.
STATUS_V2_POLL_INTERVAL_SECS = 5.0
# How long the API may stay unreachable before robots are reported offline. 4xx and 5xx are
# deliberately not retried, so one gateway error fails every chunk of a sweep and would
# otherwise flap the whole fleet.
API_OFFLINE_GRACE_SECS = 60.0
# Extra delay added to the status poll interval while the API is unreachable
API_BACKOFF_START_SECS = 1.0
API_BACKOFF_MAX_SECS = 30.0


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
        # Reachability last mirrored into the InOrbit online status, per robot.
        # See _mirror_online_status.
        self._online: dict[str, bool] = {}
        # Vendor report times behind the last telemetry publish, per robot.
        self._report_times: dict[str, tuple[str, ...]] = {}

    def _mirror_online_status(self, robot_id: str, online: bool) -> None:
        """Mirror reachability into the InOrbit online status, on transitions only.

        Uses the same retained state message the MQTT last-will uses. Re-sending offline
        would keep refreshing the robot's updateStamp, hiding how long it has been offline.
        TODO: move this into inorbit-connector; _send_robot_status is an edge-SDK internal.
        """
        if online == self._online.get(robot_id):
            return
        # connect already published the initial online report
        if robot_id in self._online or not online:
            session = self._get_robot_session(robot_id)
            if session is not None:
                session._send_robot_status(online=online)
        self._online[robot_id] = online

    def _publish_mission_tracking(self, robot_id: str, report: dict) -> None:
        """Publish a mission tracking report as an InOrbit event."""
        session = self._get_robot_session(robot_id)
        if session is not None:
            session.publish_key_values({"mission_tracking": report}, is_event=True)

    @override
    async def _connect(self) -> None:
        """Connect to the Gausium Open Platform API and start the polling loops."""
        await self._client.connect()
        # Prime both payloads: the v2 keys are missing from the first ticks otherwise
        await asyncio.gather(self._poller.poll_status_v1_once(), self._poller.poll_status_v2_once())
        await self._poller.poll_robot_data_once()
        self._create_supervised_task("status-poll", self._poll_status_loop)
        self._create_supervised_task("status-v2-poll", self._poll_status_v2_loop)
        self._create_supervised_task("robot-data-poll", self._poll_robot_data_loop)

    async def _poll_status_loop(self) -> None:
        """Poll v1 status at ``update_freq``, backing off while the API is unreachable.

        The pacing sleep runs alongside the poll, not after it, so the period is
        ``max(sweep, pacing)``.
        """
        backoff = 0.0
        while True:
            await asyncio.gather(
                self._poller.poll_status_v1_once(),
                asyncio.sleep(1.0 / self.config.update_freq + backoff),
            )
            if self._poller.api_connected:
                backoff = 0.0
            else:
                backoff = min(max(2 * backoff, API_BACKOFF_START_SECS), API_BACKOFF_MAX_SECS)

    async def _poll_status_v2_loop(self) -> None:
        """Poll v2 status on its own loop, off the pose path.

        It is the slower sweep and nothing time-critical reads it, so it gets a fixed
        interval instead of `update_freq` and the unreachable-API backoff.
        """
        while True:
            await asyncio.gather(
                self._poller.poll_status_v2_once(),
                asyncio.sleep(STATUS_V2_POLL_INTERVAL_SECS),
            )

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
        """Publish one robot's health every tick, its telemetry only when it changed.

        Health describes the connector's own view, is never stale, and is what has to keep
        arriving while nothing else does. Telemetry restates robot data the connector cannot
        refresh once the API or the robot is unreachable, or once the vendor stops reporting.
        """
        state = self._poller.get_state(self._sn_by_robot_id[robot_id])
        available = self._is_available(robot_id)
        self._mirror_online_status(robot_id, available)
        self.publish_robot_key_values(
            robot_id,
            **build_health_key_values(
                self._api_reachable(), state.status, state.status_v2, __version__
            ),
        )
        if not available or not state.status:
            # Forget the change token, so the first tick after recovery republishes even if
            # the vendor has nothing newer than what it had before the outage
            self._report_times.pop(robot_id, None)
            return
        # The vendor advances its report times whenever it has new data. The poll cycle is
        # far slower than the publish tick, so without this most publishes are byte-identical
        # restatements carrying a fresh timestamp.
        times = report_times(state.status, state.status_v2)
        if times and times == self._report_times.get(robot_id):
            return
        self._report_times[robot_id] = times
        self._publish_telemetry(robot_id, state)

    def _publish_telemetry(self, robot_id: str, state: RobotState) -> None:
        """Publish the robot's own data: pose, odometry, mission tracking and key-values."""
        status = state.status
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

        key_values = build_key_values(status, state.status_v2, state.robot_data)
        self.publish_robot_key_values(robot_id, **key_values)

    def _api_reachable(self) -> bool:
        """Whether a status poll reached the API within the grace period."""
        return self._poller.api_unreachable_secs <= API_OFFLINE_GRACE_SECS

    def _is_available(self, robot_id: str) -> bool:
        """API reachable within the grace period and vendor reports the robot reachable."""
        status = self._poller.get_state(self._sn_by_robot_id[robot_id]).status
        return self._api_reachable() and status.get("online", True)

    @override
    def _is_fleet_robot_online(self, robot_id: str) -> bool:
        """Reachability last mirrored by _mirror_online_status."""
        return self._online.get(robot_id, True)

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
            if not self._is_available(robot_id):
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
