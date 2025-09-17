# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import base64
import os
import tempfile
import pytz
import math
import uuid
from PIL import Image
import io
from typing import Optional

# from typing import override # TODO(b-Tomas): Uncomment when updating to Python 3.13
from inorbit_connector.connector import Connector
from inorbit_connector.connector import CommandResultCode
from inorbit_connector.models import MapConfig
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND
from inorbit_edge.robot import COMMAND_MESSAGE
from inorbit_edge.robot import COMMAND_NAV_GOAL
from inorbit_mir_connector import get_module_version
from inorbit_mir_connector.src.mir_api.missions_group import (
    NullMissionsGroupHandler,
    TmpMissionsGroupHandler,
)
from .mir_api import MirApiV2
from .mir_api import SetStateId
from .mission_tracking import MirInorbitMissionTracking
from .mission_exec import MirMissionExecutor
from inorbit_edge_executor.inorbit import InOrbitAPI as MissionInOrbitAPI
from ..config.connector_model import ConnectorConfig
from .robot.robot import Robot
from .utils import to_inorbit_percent, calculate_usage_percent


# Available MiR states to select via actions
MIR_STATE = {3: "READY", 4: "PAUSE", 11: "MANUALCONTROL"}

# Distance threshold for MiR move missions in meters
# Used in waypoints sent via missions
MIR_MOVE_DISTANCE_THRESHOLD = 0.1

# Diagnostic paths for robot vitals
BATTERY_PATH = "/Power System/Battery"
CPU_LOAD_PATH = "/Computer/PC/CPU Load"
CPU_TEMP_PATH = "/Computer/PC/CPU Temperature"
MEMORY_PATH = "/Computer/PC/Memory"
HARDDRIVE_PATH = "/Computer/PC/Harddrive"
WIFI_PATH = "/Computer/Network/Wifi"


class MirConnector(Connector):
    """MiR connector.

    This class handles by-directional interaction between a MiR robot and
    the InOrbit platform using mainly the InOrbit python EdgeSDK.

    Arguments:
        robot_id (str): The ID of the MiR robot.
        config (ConnectorConfig): The configuration object for the MiR connector.
    """

    def __init__(self, robot_id: str, config: ConnectorConfig) -> None:
        """Initialize the MiR connector."""
        super().__init__(
            robot_id=robot_id,
            config=config,
            register_user_scripts=True,
            create_user_scripts_dir=True,
        )
        self.config = config

        # Configure the connection to the robot
        self.mir_api = MirApiV2(
            mir_host_address=config.connector_config.mir_host_address,
            mir_username=config.connector_config.mir_username,
            mir_password=config.connector_config.mir_password,
            mir_host_port=config.connector_config.mir_host_port,
            mir_use_ssl=config.connector_config.mir_use_ssl,
            verify_ssl=config.connector_config.verify_ssl,
            ssl_ca_bundle=config.connector_config.ssl_ca_bundle,
            ssl_verify_hostname=config.connector_config.ssl_verify_hostname,
        )

        # Async robot wrapper managing polling
        self.robot = Robot(
            mir_api=self.mir_api,
            default_update_freq=1.0,  # 1 Hz status by default
        )

        # Configure the timezone
        self.robot_tz_info = pytz.timezone("UTC")
        try:
            self.robot_tz_info = pytz.timezone(config.location_tz)
        except pytz.exceptions.UnknownTimeZoneError as ex:
            self._logger.error(
                f"Unknown timezone: '{config.location_tz}', defaulting to 'UTC'. {ex}"
            )

        # Set up InOrbit Mission Tracking
        mission_tracking_enabled = config.connector_config.enable_mission_tracking
        self.mission_tracking: Optional[MirInorbitMissionTracking] = None
        if mission_tracking_enabled:
            self.mission_tracking = MirInorbitMissionTracking(
                mir_api=self.mir_api,
                inorbit_sess=self._robot_session,
                robot_tz_info=self.robot_tz_info,
                enable_io_mission_tracking=config.connector_config.enable_mission_tracking,
            )

        # Set up InOrbit Edge Executor for mission execution
        # TODO(b-Tomas): dynamically enable/disable mission tracking when executing a mission
        mission_execution_enabled = not mission_tracking_enabled
        self.mission_executor: Optional[MirMissionExecutor] = None
        if mission_execution_enabled:
            self.mission_executor = MirMissionExecutor(
                robot_id=robot_id,
                inorbit_api=MissionInOrbitAPI(
                    base_url=self._robot_session.inorbit_rest_api_endpoint,
                    api_key=self.config.api_key,
                ),
                mir_api=self.mir_api,
                database_file=config.connector_config.mission_database_file,
            )

        # Set up temporary mission groups
        if config.connector_config.enable_temporary_mission_group:
            self.mission_group = TmpMissionsGroupHandler(mir_api=self.mir_api)
        else:
            self.mission_group = NullMissionsGroupHandler()

        # Initialize status as None to prevent publishing before the robot is connected
        self.status = None

    async def _inorbit_command_handler(self, command_name, args, options):
        """Callback method for command messages.

        The callback signature is `callback(command_name, args, options)`

        Arguments:
            command_name -- identifies the specific command to be executed
            args -- is an ordered list with each argument as an entry. Each
                element of the array can be a string or an object, depending on
                the definition of the action.
            options -- is a dictionary that includes:
                - `result_function` can be called to report command execution result.
                It has the following signature: `result_function(return_code)`.
                - `progress_function` can be used to report command output and has
                the following signature: `progress_function(output, error)`.
                - `metadata` is reserved for the future and will contains additional
                information about the received command request.
        """
        self._logger.info(f"Received command '{command_name}' with {len(args)} arguments")
        self._logger.debug(f"Command details: {command_name} - {args}")

        if command_name == COMMAND_CUSTOM_COMMAND:
            if len(args) < 2:
                self._logger.error(
                    f"Invalid number of arguments for '{command_name}': "
                    f"expected >=2, got {len(args)}"
                )
                options["result_function"](
                    CommandResultCode.FAILURE,
                    execution_status_details="Invalid number of arguments",
                )
                return

            # Parse command name and arguments
            # TODO: Use parsed arguments on all custom commands
            script_name = args[0]
            args_raw = list(args[1])
            script_args = {}
            if (
                isinstance(args_raw, list)
                and len(args_raw) % 2 == 0
                and all(isinstance(key, str) for key in args_raw[::2])
            ):
                script_args = dict(zip(args_raw[::2], args_raw[1::2]))
                self._logger.debug(f"Parsed arguments are: {script_args}")
            else:
                return options["result_function"](CommandResultCode.FAILURE, "Invalid arguments")

            # Delegate mission commands to the mission executor
            if self.mission_executor:
                handled = await self.mission_executor.handle_command(
                    script_name, script_args, options
                )
                if handled:
                    self._logger.info(f"Mission executor handled command '{script_name}'")
                    # The executor handles calling the result function
                    return

            # TODO: Use parsed arguments on all custom commands
            script_name = args[0]
            script_args = args[1]
            # TODO (Elvio): Needs to be re designed.
            # 1. script_name is not standarized at all
            # 2. Consider implementing a callback for handling mission specific commands
            # 3. Needs an interface for supporting mission related actions

            if script_name == "queue_mission" and script_args[0] == "--mission_id":
                if self.mission_tracking:
                    self.mission_tracking.mir_mission_tracking_enabled = (
                        self._robot_session.missions_module.executor.wait_until_idle(0)
                    )
                await self.mir_api.queue_mission(script_args[1])
            elif script_name == "run_mission_now" and script_args[0] == "--mission_id":
                if self.mission_tracking:
                    self.mission_tracking.mir_mission_tracking_enabled = (
                        self._robot_session.missions_module.executor.wait_until_idle(0)
                    )
                await self.mir_api.abort_all_missions()
                await self.mir_api.queue_mission(script_args[1])
            elif script_name == "abort_missions":
                self._robot_session.missions_module.executor.cancel_mission("*")
                await self.mir_api.abort_all_missions()
            elif script_name == "set_state":
                if script_args[0] == "--state_id":
                    state_id = script_args[1]
                    if not state_id.isdigit() or int(state_id) not in MIR_STATE.keys():
                        error = f"Invalid `state_id` '{state_id}'"
                        self._logger.error(error)
                        options["result_function"](
                            CommandResultCode.FAILURE, execution_status_details=error
                        )
                        return
                    state_id = int(state_id)
                    self._logger.info(
                        f"Setting robot state to state {state_id}: {MIR_STATE[state_id]}"
                    )
                    await self.mir_api.set_state(state_id)
                if script_args[0] == "--clear_error":
                    self._logger.info("Clearing error state")
                    await self.mir_api.clear_error()
            elif script_name == "set_waiting_for" and script_args[0] == "--text":
                self._logger.info(f"Setting 'waiting for' value to {script_args[1]}")
                if self.mission_tracking:
                    self.mission_tracking.waiting_for_text = script_args[1]
                else:
                    self._logger.warning(
                        "Mission tracking is not enabled, skipping 'waiting for' value"
                    )
                    options["result_function"](
                        CommandResultCode.FAILURE, "Mission tracking is not enabled"
                    )
                    return

            elif script_name == "localize":
                # The localize command sets the robot's position and current map
                # The expected arguments are "x" and "y" in meters and "orientation" in degrees, as
                # in MiR Fleet, and "map_id" as the target map in MiR Fleet, which matches the
                # uploaded "frame_id" in InOrbit
                if (
                    len(script_args) == 8
                    and script_args[0] == "--x"
                    and script_args[2] == "--y"
                    and script_args[4] == "--orientation"
                    and script_args[6] == "--map_id"
                ):
                    status = {
                        "position": {
                            "x": float(script_args[1]),
                            "y": float(script_args[3]),
                            "orientation": float(script_args[5]),
                        },
                        "map_id": script_args[7],
                    }
                    self._logger.info(f"Changing map to {script_args[7]}")
                    await self.mir_api.set_status(status)
                else:
                    self._logger.error("Invalid arguments for 'localize' command")
                    options["result_function"](
                        CommandResultCode.FAILURE, execution_status_details="Invalid arguments"
                    )
                    return
            else:
                # Other kind if custom commands may be handled by the edge-sdk (e.g. user_scripts)
                # and not by the connector code itself
                # Do not return any result and leave it to the edge-sdk to handle it
                return
            # Return success
            options["result_function"](CommandResultCode.SUCCESS)
        elif command_name == COMMAND_NAV_GOAL:
            pose = args[0]
            # If the temporary mission group is enabled, send the waypoint over missions
            # TODO: Make it more generic if/when we support predefined missions groups
            if self.config.connector_config.enable_temporary_mission_group:
                await self.send_waypoint_over_missions(pose)
            elif mission_id := self.config.connector_config.default_waypoint_mission_id:
                x, y, orientation = (
                    float(pose["x"]),
                    float(pose["y"]),
                    math.degrees(float(pose["theta"])),
                )
                await self.mir_api.abort_all_missions()
                await self.mir_api.queue_mission(
                    mission_id,
                    message="InOrbit Waypoint",
                    parameters=[
                        {"id": "X", "value": x, "label": f"{x}"},
                        {"id": "Y", "value": y, "label": f"{y}"},
                        {"id": "Orientation", "value": orientation, "label": f"{orientation}"},
                    ],
                    description="Mission created by InOrbit",
                )
            else:
                self._logger.error("No waypoint mission id or temporary missions group enabled")
                return options["result_function"](
                    CommandResultCode.FAILURE,
                    execution_status_details=(
                        "No waypoint mission id or temporary missions group enabled"
                    ),
                )

        elif command_name == COMMAND_MESSAGE:
            msg = args[0]
            if msg == "inorbit_pause":
                await self.mir_api.set_state(SetStateId.PAUSE.value)
            elif msg == "inorbit_resume":
                await self.mir_api.set_state(SetStateId.READY.value)
        else:
            self._logger.warning(f"Received unknown command '{command_name}' - ignoring")
            self._logger.debug(f"Unknown command details: {command_name} - {args}")

    async def _connect(self) -> None:
        """Connect to the robot services and initialize background tasks."""
        # Start robot polling loops
        self.robot.start()

        # Initialize mission executor
        if self.mission_executor:
            try:
                await self.mission_executor.initialize()
                self._logger.info("Mission executor initialized successfully")
            except Exception as e:
                self._logger.error(f"Failed to initialize mission executor: {e}")
                self.mission_executor = None

        # Start temporary mission groups
        await self.mission_group.start()

    async def _disconnect(self):
        """Disconnect from any external services"""
        await self.mission_group.cleanup_connector_missions()
        await self.mission_group.stop()
        await self.robot.stop()
        await self.mir_api.close()

        # Shutdown mission executor
        if self.mission_executor:
            try:
                await self.mission_executor.shutdown()
                self._logger.info("Mission executor shut down successfully")
            except Exception as e:
                self._logger.error(f"Error shutting down mission executor: {e}")

    async def _execution_loop(self):
        """The main execution loop for the connector"""

        # Read latest robot data from Robot wrapper
        status = self.robot.status
        if not status and self.status is None:
            return
        self.status = status
        self.metrics = self.robot.metrics
        # TODO(b-Tomas): there is a lot of valuable data here. Make sure to parse it and publish it
        self.diagnostics = self.robot.diagnostics

        # publish pose
        pose_data = {
            "x": self.status.get("position", {}).get("x", 0),
            "y": self.status.get("position", {}).get("y", 0),
            "yaw": math.radians(self.status.get("position", {}).get("orientation", 0)),
            "frame_id": self.status.get("map_id", ""),
        }
        self._robot_session.publish_pose(**pose_data)

        # publish odometry
        odometry = {
            "linear_speed": self.status.get("velocity", {}).get("linear", 0),
            "angular_speed": math.radians(self.status.get("velocity", {}).get("angular", 0)),
        }
        self._robot_session.publish_odometry(**odometry)

        # publish key values
        if self._robot_session.missions_module.executor.wait_until_idle(0):
            mode_text = self.status.get("mode_text")
            state_text = self.status.get("state_text")
            mission_text = self.status.get("mission_text")
        else:
            mode_text = "Mission"
            state_text = "Executing"
            mission_text = "Mission"

        # TODO(Elvio): Move key values to a "values.py" and represent them with constants
        key_values = {
            "connector_version": get_module_version(),
            "robot_name": self.status.get("robot_name"),
            "errors": self.status.get("errors"),
            "distance_to_next_target": self.status.get("distance_to_next_target"),
            "mission_text": mission_text,
            "state_text": state_text,
            "mode_text": mode_text,
            "robot_model": self.status.get("robot_model"),
            "waiting_for": (
                self.mission_tracking.waiting_for_text if self.mission_tracking else None
            ),
            "api_connected": self.robot.api_connected,
        }

        # Add vitals from diagnostics (preferred) or status (fallback)
        # Keep localization_score from metrics only
        key_values["localization_score"] = (self.metrics or {}).get("mir_robot_localization_score")

        # Uptime always from status (more reliable)
        key_values["uptime"] = self.status.get("uptime")

        diagnostics = self.diagnostics or {}
        try:
            # Battery from diagnostics, fallback to status
            batt_vals = (diagnostics.get(BATTERY_PATH, {}) or {}).get("values", {})
            remaining_pct = None
            remaining_sec = None
            for k, v in batt_vals.items():
                if "Remaining battery capacity" in k:
                    remaining_pct = float(v)
                elif "Remaining battery time [sec]" in k:
                    remaining_sec = float(v)
            if remaining_pct is not None:
                key_values["battery percent"] = to_inorbit_percent(remaining_pct)
            if remaining_sec is not None:
                key_values["battery_time_remaining"] = int(remaining_sec)

            # CPU load from diagnostics
            cpu_vals = (diagnostics.get(CPU_LOAD_PATH, {}) or {}).get("values", {})
            avg_cpu = None
            for k, v in cpu_vals.items():
                if "Average CPU load" in k and "30 second" not in k and "3 minute" not in k:
                    avg_cpu = float(v)
                    break
            if avg_cpu is not None:
                key_values["cpu_usage_percent"] = to_inorbit_percent(avg_cpu)

            # CPU temperature from diagnostics
            cpu_temp_vals = (diagnostics.get(CPU_TEMP_PATH, {}) or {}).get("values", {})
            pkg_temp = None
            for k, v in cpu_temp_vals.items():
                if "Package id" in k:
                    pkg_temp = float(v)
                    break
            if pkg_temp is not None:
                key_values["temperature_celsius"] = pkg_temp

            # Memory and disk usage from diagnostics
            memory_vals = (diagnostics.get(MEMORY_PATH, {}) or {}).get("values", {})
            memory_usage_pct = calculate_usage_percent(memory_vals, "memory_usage_percent")
            if memory_usage_pct is not None:
                key_values["memory_usage_percent"] = to_inorbit_percent(memory_usage_pct)

            disk_vals = (diagnostics.get(HARDDRIVE_PATH, {}) or {}).get("values", {})
            disk_usage_pct = calculate_usage_percent(disk_vals, "disk_usage_percent")
            if disk_usage_pct is not None:
                key_values["disk_usage_percent"] = to_inorbit_percent(disk_usage_pct)

            # WiFi details from diagnostics
            wifi_vals = (diagnostics.get(WIFI_PATH, {}) or {}).get("values", {})
            ssid = wifi_vals.get("SSID")
            freq = wifi_vals.get("Frequency")
            signal = wifi_vals.get("Signal level")
            if ssid is not None:
                key_values["wifi_ssid"] = ssid
            if freq is not None:
                # Frequency provided as MHz in examples
                try:
                    key_values["wifi_frequency_mhz"] = float(freq)
                except (ValueError, TypeError):
                    # Expected parsing errors for malformed frequency values
                    pass
            if signal is not None:
                try:
                    key_values["wifi_signal_dbm"] = float(signal)
                except (ValueError, TypeError):
                    # Expected parsing errors for malformed signal values
                    pass
        except Exception:
            # Never fail the loop due to parsing issues; values just won't be present
            self._logger.debug("Failed to parse diagnostics vitals", exc_info=True)

        # Key values published every second - too noisy for debug logs
        # Only log when api_connected status changes
        if hasattr(self, "_last_api_connected") and self._last_api_connected != key_values.get(
            "api_connected"
        ):
            self._logger.info(f"API connection status changed: {key_values.get('api_connected')}")
        self._last_api_connected = key_values.get("api_connected")
        self._robot_session.publish_key_values(key_values)

        # publish mission data if available
        if self.mission_tracking:
            try:
                await self.mission_tracking.report_mission(self.status, self.metrics or {})
            except Exception:
                self._logger.exception("Error reporting mission")

    def publish_api_error(self):
        """Publish an error message when the API call fails.
        This value can be used for setting up status and incidents in InOrbit"""
        self._robot_session.publish_key_values({"api_connected": False})

    async def send_waypoint_over_missions(self, pose):
        """Use the connector's mission group to create a move mission to a designated pose."""
        mission_id = str(uuid.uuid4())
        connector_type = self.config.connector_type
        firmware_version = self.config.connector_config.mir_firmware_version

        if not self.mission_group.missions_group_id:
            # Ensure missions group is created if not yet initialized by background thread
            try:
                await self.mission_group.setup_connector_missions()
            except Exception as ex:
                self._logger.error(f"Failed to setup connector missions: {ex}")
            if not self.mission_group.missions_group_id:
                raise Exception("Connector missions group not set up")

        await self.mir_api.create_mission(
            group_id=self.mission_group.missions_group_id,
            name="Move to waypoint",
            guid=mission_id,
            description="Mission created by InOrbit",
        )
        param_values = {
            "x": float(pose["x"]),
            "y": float(pose["y"]),
            "orientation": math.degrees(float(pose["theta"])),
            "distance_threshold": MIR_MOVE_DISTANCE_THRESHOLD,
        }
        if connector_type == "MiR100" and firmware_version == "v2":
            param_values["retries"] = 5
        elif connector_type == "MiR250" and firmware_version == "v3":
            param_values["blocked_path_timeout"] = 60.0
        else:
            self._logger.warning(
                f"Not supported connector type and firmware version combination for waypoint "
                f"navigation: {connector_type} {firmware_version}. Will attempt to send waypoint "
                "based on firmware version."
            )
            if firmware_version == "v2":
                param_values["retries"] = 5
            else:
                param_values["blocked_path_timeout"] = 60.0

        action_parameters = [
            {"value": v, "input_name": None, "guid": str(uuid.uuid4()), "id": k}
            for k, v in param_values.items()
        ]
        await self.mir_api.add_action_to_mission(
            action_type="move_to_position",
            mission_id=mission_id,
            parameters=action_parameters,
            priority=1,
        )
        await self.mir_api.queue_mission(mission_id)

    async def _delete_unused_missions(self):
        """Delete unused mission definitions from the temporary missions group."""
        if not hasattr(self, 'tmp_missions_group_id') or not self.tmp_missions_group_id:
            self._logger.warning("Cannot delete unused missions: missions group not set up")
            return
        
        try:
            mission_defs = await self.mir_api.get_mission_group_missions(self.tmp_missions_group_id)
            missions_queue = await self.mir_api.get_missions_queue()
            # Do not delete definitions of missions that are pending or executing
            protected_mission_defs = [
                (await self.mir_api.get_mission(mission["id"]))["mission_id"]
                for mission in missions_queue
                if mission["state"] in ["Pending", "Executing"]
            ]
            # Delete mission definitions that are not protected
            for mission_def in mission_defs:
                mission_id = mission_def["guid"]
                if mission_id not in protected_mission_defs:
                    await self.mir_api.delete_mission_definition(mission_id)
        except Exception as ex:
            self._logger.error(f"Error deleting unused missions: {ex}")

    # HACK(b-Tomas): This is a hack to publish the map data through the connector.
    # All of this logic should be moved to the Connector base class.
    # @override # TODO(b-Tomas): Uncomment when updating to Python 3.13
    def publish_map(self, frame_id: str, is_update: bool = False) -> None:
        """Publish a map to InOrbit. If `frame_id` is present in the maps config, it acts normal.
        If `frame_id` is not present in the maps config, it will attempt to load the map from the
        robot.
        """
        # If a map was provided by the user, publish it as normal
        if frame_id in self.config.maps:
            super().publish_map(frame_id, is_update)
        # Else, attempt to load the map from the robot and publish it instead
        else:
            self._logger.info(
                f"Map with frame_id {frame_id} not found in config, attempting to load from robot"
            )
            try:
                map_id = frame_id

                # Get the map image using the new API method
                map_data = self.mir_api.get_map_sync(map_id)
                if not map_data:
                    self._logger.warning("No map data received from robot")
                    return

                image = map_data.get("base_map")
                map_name = map_data.get("name")
                resolution = map_data.get("resolution")
                origin_x = map_data.get("origin_x")
                origin_y = map_data.get("origin_y")

            except Exception as ex:
                self._logger.error(f"Failed to load map from robot: {ex}")
                return

            # Process and save the map image
            if image and map_name and resolution and origin_x is not None and origin_y is not None:
                # Generate a byte array from the base64 encoded image
                map_data = base64.b64decode(image)
                self._logger.debug(f"Map image size: {len(map_data)} bytes")
                # Create a temporary file with .png extension to store the map image
                fd, temp_path = tempfile.mkstemp(suffix=".png")
                self._logger.debug(f"Created temporary file: {temp_path}")

                # Flip the map image bytes vertically
                # NOTE: This is done in order to display the image correctly in the
                # InOrbit platform, but can be computationally expensive
                try:
                    # Create an image from the bytes
                    image = Image.open(io.BytesIO(map_data))

                    # Flip the image vertically
                    flipped_image = image.transpose(Image.FLIP_TOP_BOTTOM)

                    # Convert back to bytes
                    img_byte_arr = io.BytesIO()
                    flipped_image.save(img_byte_arr, format="PNG")
                    flipped_bytes = img_byte_arr.getvalue()
                except Exception as e:
                    self._logger.error(f"Failed to flip map image: {e}")
                    # If flipping fails, use the original bytes
                    flipped_bytes = map_data

                try:
                    # Write the map image bytes to the temporary file
                    with os.fdopen(fd, "wb") as tmp_file:
                        tmp_file.write(flipped_bytes)

                    # Create a new map configuration
                    # Note: For Gausium robots, we may need to adjust origin and resolution
                    # based on the robot's coordinate system
                    self.config.maps[frame_id] = MapConfig(
                        file=temp_path,
                        map_id=map_id,
                        origin_x=origin_x,
                        origin_y=origin_y,
                        resolution=resolution,
                    )

                    self._logger.info(f"Added map {frame_id} from robot to configuration")
                    return super().publish_map(frame_id, is_update)
                except Exception as e:
                    self._logger.error(f"Failed to create temporary map file: {e}")
                    os.unlink(temp_path)  # Clean up the file in case of error
            else:
                self._logger.error(f"No map data available for {frame_id}")
                return
