# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import io
import math
import os
import tempfile
from enum import Enum
from typing import override

from inorbit_connector.connector import CommandResultCode
from inorbit_connector.connector import Connector
from inorbit_connector.models import MapConfig
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND
from inorbit_edge.robot import COMMAND_MESSAGE
from inorbit_edge.robot import COMMAND_NAV_GOAL
from inorbit_gausium_connector.src.robot.robot_api import CleaningModes
from inorbit_gausium_connector.src.robot.robot_api import RemoteNavigationCommandType
from PIL import Image

from .. import __version__
from ..config.connector_model import ConnectorConfig
from .mission import MissionTracking
from .robot import RemoteTaskCommandType
from .robot import RobotAPI
from .robot.robot import Robot


# Pose is received in pixels. It must be coverted to meters before publishing to inorbit
MAP_RESOLUTION = 0.05  # meters per pixel


# InOrbit custom command names
class CustomCommands(str, Enum):
    SUBMIT_TASK = "submit_task"
    TASK_COMMAND = "task_command"
    NAVIGATE_COMMAND = "navigate"


# TODO(b-Tomas): Rename this class and refactor any other references to the Phantas robot
class PhantasConnector(Connector):
    """Gausium Phantas connector.

    This class handles by-directional interaction between a Gausium Phantas robot and
    the InOrbit platform using the InOrbit python EdgeSDK.

    Arguments:
        robot_id (str): The ID of the Gausium Phantas robot.
        config (ConnectorConfig): The configuration object for the Gausium Phantas Connector.
    """

    def __init__(self, robot_id: str, config: ConnectorConfig) -> None:
        """Initialize the Gausium Phantas Connector."""
        super().__init__(
            robot_id,
            config,
            register_user_scripts=True,
        )

        # Initialize the RobotAPI
        self.robot_api = RobotAPI(
            base_url=config.connector_config.base_url,
            serial_number=config.connector_config.serial_number,
            client_id=config.connector_config.client_id,
            client_secret=config.connector_config.client_secret,
            access_key_secret=config.connector_config.access_key_secret,
        )

        # Initialize the Robot abstraction
        self.robot = Robot(
            robot_api=self.robot_api,
            default_update_freq=config.update_freq,
        )

        self.mission_tracking = MissionTracking(
            robot_api=self.robot_api,
            publish_callback=self.publish_mission_tracking,
            mission_success_percentage_threshold=(
                config.connector_config.mission_success_percentage_threshold
            ),
        )

    async def _connect(self) -> None:
        """Connect to the robot services.

        This method should always call super.
        """
        # Initialize the robot API session
        await self.robot_api.init_session()

        # Start the polling loops
        self.robot.start()

    async def _disconnect(self) -> None:
        """Disconnect from the robot services."""
        # Stop the polling loops
        await self.robot.stop()

        # Shutdown mission tracking
        await self.mission_tracking.shutdown()

        # Close the API client
        await self.robot_api.close()

    @override
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
                f"Map with frame_id={frame_id} not found in config, attempting to load from robot"
            )
            try:
                # Get current robot status to find the map information
                # NOTE: We use the v2 status to get the map information because the v1 status
                # doesn't include the map information - the API used to fetch the map image is v2
                status = self.robot.status_v2
                if not status:
                    raise Exception("No robot status available")

                # Extract map information from the robot status
                localization_info = status.get("localizationInfo", {})
                current_map = localization_info.get("map", {})

                if not current_map:
                    raise Exception("No current map information available")

                map_id = current_map.get("id")
                map_name = current_map.get("name")
                map_version = current_map.get("version")

                if not map_id or not map_name:
                    raise Exception(f"Incomplete map information: id={map_id}, name={map_name}")

                if map_id != frame_id:
                    raise Exception(
                        f"Available map data doesn't match the requested frame_id: "
                        f"map_id={map_id} != frame_id={frame_id}"
                    )

                # Get the map image using the new API method
                map_image = self.robot_api.get_map_image_sync(map_id, map_name, map_version)
                if map_image:
                    self._logger.info(f"Map image size: {len(map_image)} bytes")
                else:
                    self._logger.warning("No map image data received from robot")
                    return

            except Exception as ex:
                self._logger.error(f"Failed to load map from robot: {ex}")
                return

            # Process and save the map image
            if map_image:
                # Create a temporary file with .png extension to store the map image
                fd, temp_path = tempfile.mkstemp(suffix=".png")
                self._logger.debug(f"Created temporary file: {temp_path}")

                # Flip the map image bytes vertically
                # NOTE: This is done in order to display the image correctly in the
                # InOrbit platform, but can be computationally expensive
                try:
                    # Create an image from the bytes
                    image = Image.open(io.BytesIO(map_image))

                    # Flip the image vertically
                    flipped_image = image.transpose(Image.FLIP_TOP_BOTTOM)

                    # Convert back to bytes
                    img_byte_arr = io.BytesIO()
                    flipped_image.save(img_byte_arr, format="PNG")
                    flipped_bytes = img_byte_arr.getvalue()

                    self._logger.debug("Successfully flipped map image")
                except Exception as e:
                    self._logger.error(f"Failed to flip map image: {e}")
                    # If flipping fails, use the original bytes
                    flipped_bytes = map_image

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
                        map_label=map_name,
                        origin_x=0.0,
                        origin_y=0.0,
                        resolution=MAP_RESOLUTION,  # Use the same resolution as pose conversion
                    )

                    self._logger.info(
                        f"Added map from robot to configuration: "
                        f"frame_id={frame_id} map_id={map_id} map_label={map_name}"
                    )
                    return super().publish_map(frame_id, is_update)
                except Exception as e:
                    self._logger.error(f"Failed to create temporary map file: {e}")
                    os.unlink(temp_path)  # Clean up the file in case of error
            else:
                self._logger.error(f"No map data available for frame_id={frame_id}")
                return

    async def _execution_loop(self) -> None:
        """The main execution loop for the connector.

        Main execution loop for the connector.

        It gets the latest robot status and publishes it to InOrbit.
        """

        # Get the latest robot status
        status = self.robot.status
        status_v2 = self.robot.status_v2
        if not status:
            self._logger.debug("No robot status available yet")
            return

        # Publish pose
        # mapPosition returns:
        # x: float (pixels)
        # y: float (pixels)
        # angle: float (degrees) (-180;180] Clockwise from positive X axis
        localization_info = status.get("localizationInfo", {})
        map_position = localization_info.get("mapPosition", {})

        frame_id = localization_info.get("map", {}).get("id", "map")
        x = map_position.get("x")
        y = map_position.get("y")
        angle = map_position.get("angle")

        # Note: lost robots publish a mapId but no x and y coordinates
        # x, y and yaw are required for pose publishing
        if x is not None and y is not None and angle is not None:
            pose_data = {
                "frame_id": frame_id,
                "x": x * MAP_RESOLUTION,
                "y": y * MAP_RESOLUTION,
                "yaw": math.radians(angle),
            }
            self.publish_pose(**pose_data)

        # publish odometry
        odometry = {
            "linear_speed": status.get("speedKilometerPerHour", 0.0) / 3.6,
        }
        self._logger.debug(f"Publishing odometry: {odometry}")
        self._robot_session.publish_odometry(**odometry)

        # Update mission tracking data
        self.mission_tracking.update(status, status_v2)

        # Publish key values
        key_values = {
            **status,
            "battery_percentage": status.get("battery", {}).get("powerPercentage"),
            "charging": status.get("battery", {}).get("charging"),
            "api_connected": self.robot.api_connected,
            "connector_version": __version__,
            "display_name": self.robot.robot_data.get("displayName", ""),
            "model_family": self.robot.robot_data.get("modelFamilyCode", ""),
            "model_type": self.robot.robot_data.get("modelTypeCode", ""),
            "software_version": self.robot.robot_data.get("softwareVersion", ""),
            # Convert ft to m. This is the only data expressed in imperial units. Others do
            # not need conversion.
            "total_traveled_distance": self.robot.robot_details.get("totalMileage", 0.0) * 0.3048,
            "total_operation_time": self.robot.robot_details.get("totalDuration", 0.0),  # Seconds
        }
        self._logger.debug(f"Publishing key values: {key_values}")
        self._robot_session.publish_key_values(key_values)

    async def _inorbit_command_handler(self, command_name: str, args: list, options: dict) -> None:
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
        if command_name == COMMAND_CUSTOM_COMMAND:
            self._logger.info(f"Received '{command_name}'!. {args}")
            if not self.is_robot_available():
                self._logger.error("Robot is unavailable")
                return options["result_function"](
                    CommandResultCode.FAILURE, "Robot is not available"
                )

            # Parse command name and arguments
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

            # Submit a new site task
            if script_name == CustomCommands.SUBMIT_TASK:
                area_id = script_args.get("area_id")
                cleaning_mode = script_args.get("cleaning_mode")
                if (
                    not all([area_id, cleaning_mode])
                    or cleaning_mode not in CleaningModes.__members__
                ):
                    return options["result_function"](
                        CommandResultCode.FAILURE, "Invalid arguments"
                    )
                status = self.robot.status
                map_id = status.get("localizationInfo", {}).get("map", {}).get("id")
                map_name = status.get("localizationInfo", {}).get("map", {}).get("name")
                if not all([map_id, map_name]):
                    return options["result_function"](
                        CommandResultCode.FAILURE, "No map data available"
                    )
                await self.robot_api.create_nosite_task(
                    task_name="InOrbit task",
                    map_id=map_id,
                    map_name=map_name,
                    area_id=area_id,
                    cleaning_mode=CleaningModes[cleaning_mode],
                    loop=False,
                )

            # Submit a task related command to the robot
            elif script_name == CustomCommands.TASK_COMMAND:
                command = script_args.get("command")
                if command in [
                    RemoteTaskCommandType.PAUSE_TASK,
                    RemoteTaskCommandType.RESUME_TASK,
                    RemoteTaskCommandType.STOP_TASK,
                ]:
                    await self.robot_api.create_remote_task_command(RemoteTaskCommandType[command])
                else:
                    self._logger.error(f"Invalid command: {command}")
                    return options["result_function"](
                        CommandResultCode.FAILURE, f"Invalid command {command}"
                    )

            # Submit a navigation command to the robot
            elif script_name == CustomCommands.NAVIGATE_COMMAND:
                command = script_args.get("command")
                position = script_args.get("position")
                if (
                    not all([command, position])
                    or command not in RemoteNavigationCommandType.__members__
                ):
                    return options["result_function"](
                        CommandResultCode.FAILURE, "Invalid arguments"
                    )
                status = self.robot.status
                map_name = status.get("localizationInfo", {}).get("map", {}).get("name")
                if not map_name:
                    return options["result_function"](
                        CommandResultCode.FAILURE, "No map data available"
                    )
                await self.robot_api.create_remote_navigation_command(
                    command_type=RemoteNavigationCommandType[command],
                    command_parameter={
                        "startNavigationParameter": {
                            "map": map_name,
                            "position": position,
                        }
                    },
                )

            else:
                # Other kind if custom commands may be handled by the edge-sdk (e.g. user_scripts)
                # and not by the connector code itself
                # Do not return any result and leave it to the edge-sdk to handle it
                return

            # Return success
            return options["result_function"](CommandResultCode.SUCCESS)

        elif command_name == COMMAND_NAV_GOAL:
            self._logger.info(f"Received '{command_name}'!. {args}")
            pose = args[0]
            await self.robot_api.send_waypoint(pose)

        elif command_name == COMMAND_MESSAGE:
            # msg = args[0]
            return options["result_function"](
                CommandResultCode.FAILURE, f"'{COMMAND_MESSAGE}' is not implemented"
            )

        else:
            self._logger.info(f"Received '{command_name}'!. {args}")

    def is_robot_available(self) -> bool:
        """Check if the robot is available for receiving commands.

        Returns:
            bool: True if the robot is online, False otherwise.
        """
        # If the last call was successful and the robot is online, return True
        # If unable to determine if the robot is online from the status data, assume it is
        status = self.robot.status
        return self.robot.api_connected and status.get("online", True)

    def publish_mission_tracking(self, report: dict) -> None:
        """Publish a mission tracking report to InOrbit."""
        self._robot_session.publish_key_values({"mission_tracking": report}, is_event=True)
