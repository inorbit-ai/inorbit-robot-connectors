# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import asyncio
from enum import Enum
import io
import math
import os
import tempfile
from typing import override

from inorbit_connector.connector import Connector, CommandResultCode
from inorbit_connector.models import MapConfig
from inorbit_edge.robot import (
    COMMAND_CUSTOM_COMMAND,
    COMMAND_INITIAL_POSE,
    COMMAND_MESSAGE,
    COMMAND_NAV_GOAL,
)
from inorbit_gausium_connector.src.mission import MissionTracking
from PIL import Image

from .. import __version__
from .config.connector_model import ConnectorConfig
from .robot import create_robot


class CustomScripts(Enum):
    """Supported InOrbit CustomScript actions"""

    START_TASK_QUEUE = "start_task_queue"
    PAUSE_TASK_QUEUE = "pause_task_queue"
    RESUME_TASK_QUEUE = "resume_task_queue"
    CANCEL_TASK_QUEUE = "cancel_task_queue"

    SEND_TO_NAMED_WAYPOINT = "send_to_named_waypoint"
    PAUSE_NAVIGATION_TASK = "pause_navigation_task"
    RESUME_NAVIGATION_TASK = "resume_navigation_task"
    CANCEL_NAVIGATION_TASK = "cancel_navigation_task"


class CommandMessages(Enum):
    """Supported InOrbit PublishToTopic actions"""

    PAUSE = "inorbit_pause"
    RESUME = "inorbit_resume"


class GausiumConnector(Connector):
    """Gausium connector.

    This class handles by-directional interaction between a Gausium robot and
    the InOrbit platform using the InOrbit python EdgeSDK.

    Arguments:
        robot_id (str): The ID of the Gausium robot.
        config (ConnectorConfig): The configuration object for the Gausium Connector.
    """

    def __init__(self, robot_id: str, config: ConnectorConfig) -> None:
        """Initialize the Gausium Connector."""
        super().__init__(robot_id, config)
        self.robot_api, self.robot_state = create_robot(
            connector_type=config.connector_type,
            base_url=config.connector_config.base_url,
            loglevel=config.log_level.value,
            ignore_model_type_validation=config.connector_config.ignore_model_type_validation,
        )
        self.mission_tracking = MissionTracking(self.publish_mission_tracking)

    @override
    async def _connect(self) -> None:
        """Connect to the robot services.

        It starts the API polling loops.
        """
        self._logger.info("Starting API polling")
        self.robot_state.start()

    @override
    async def _disconnect(self) -> None:
        """Disconnect from the robot services."""
        self._logger.info("Stopping API polling")
        await self.robot_state.stop()
        await self.robot_api.close()

    @override
    async def _execution_loop(self) -> None:
        """The main execution loop for the connector.

        It publishes the last updated robot data to InOrbit.
        """
        if pose := self.robot_state.pose:
            self.publish_pose(**pose)

        if path := self.robot_state.path:
            self._robot_session.publish_path(**path.model_dump())

        if key_values := self.robot_state.key_values:
            self._robot_session.publish_key_values(
                {
                    **key_values,
                    "connector_version": __version__,
                    "robot_available": self.is_robot_available(),
                }
            )

            # Update mission tracking data
            robot_status = key_values.get("robotStatus", {})
            status_data = key_values.get("statusData", {})
            self.mission_tracking.mission_update(robot_status, status_data)

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
                f"Map with frame_id {frame_id} not found in config, attempting to load from robot"
            )
            try:
                map_data = self.robot_state.current_map

                if map_data is None:
                    raise Exception("No map data available")
                elif map_data.map_name != frame_id:
                    raise Exception(
                        f"Available map data doesn't match the requested frame_id: "
                        f"{map_data.map_name} != {frame_id}"
                    )

                map_image = self.robot_api.get_map_image_sync(map_data.map_name)
                if map_image:
                    self._logger.info(f"Map image size: {len(map_image)} bytes")
                else:
                    self._logger.warning("No map image data received from robot")

            except Exception as ex:
                self._logger.error(f"Failed to load map from robot: {ex}")
                return
            # HACK(b-Tomas): Create a temporary file with .png extension to store the map image
            # It should be possible to avoid this and work with the in-memory bytes instead
            if map_data and map_image:
                # Create a temporary file with .png extension to store the map image
                fd, temp_path = tempfile.mkstemp(suffix=".png")
                self._logger.debug(f"Created temporary file: {temp_path}")
                # Flip the map image bytes vertically
                # NOTE(b-Tomas): This is done in order to display the image correctly in the
                # InOrbit platform, but can be computationally expensive
                # TODO(b-Tomas): Find a better solution
                # Convert the map image bytes to a PIL Image
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
                    self.config.maps[frame_id] = MapConfig(
                        file=temp_path,
                        map_id=map_data.map_name,
                        frame_id=frame_id,
                        origin_x=map_data.origin_x,
                        origin_y=map_data.origin_y,
                        resolution=map_data.resolution,
                    )

                    self._logger.info(f"Added map {frame_id} from robot to configuration")
                    return super().publish_map(frame_id, is_update)
                except Exception as e:
                    self._logger.error(f"Failed to create temporary map file: {e}")
                    os.unlink(temp_path)  # Clean up the file in case of error
            else:
                self._logger.error(f"No map data available for {frame_id}")
                return

    @override
    async def _inorbit_command_handler(self, command_name, args, options):
        """Callback method for command messages. This method is called when a command
        is received from InOrbit.

        Args:
            command_name (str): The name of the command
            args (list): The list of arguments
            options (dict): The dictionary of options.
                It contains the `result_function` explained above.
        """
        self._logger.info(f"Received '{command_name}'!. {args}")

        # InOrbit custom commands (RunScript actions)
        if command_name == COMMAND_CUSTOM_COMMAND:
            # If the robot is not available, wait for it to become available
            # If it doesn't become available in time, continue anyway at risk of failure
            interval_secs = 0.1
            max_wait_secs = 3
            for i in range(0, int(max_wait_secs / interval_secs)):
                if self.is_robot_available():
                    break
                await asyncio.sleep(interval_secs)

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

            # If the command to run is a script (or anything with a dot), ignore it and let the
            # edge-sdk run it. If the script doesn't exist or can't be run, the edge-sdk will
            # handle the errors.
            if "." in script_name:
                return

            success = False
            if script_name == CustomScripts.START_TASK_QUEUE.value:
                # The most important argument
                task_queue_name = script_args.get("task_queue_name")
                # Defaults to the current map. Usually not needed
                map_name = script_args.get("map_name")
                # Whether to loop the task. Defaults to False
                loop = script_args.get("loop", False)
                # Number of loops. Defaults to 0
                loop_count = script_args.get("loop_count", 0)
                success = await self.robot_api.start_task_queue(
                    task_queue_name, map_name, loop, loop_count
                )

            elif script_name == CustomScripts.PAUSE_TASK_QUEUE.value:
                success = await self.robot_api.pause_task_queue()
            elif script_name == CustomScripts.RESUME_TASK_QUEUE.value:
                success = await self.robot_api.resume_task_queue()
            elif script_name == CustomScripts.CANCEL_TASK_QUEUE.value:
                success = await self.robot_api.cancel_task_queue()

            elif script_name == CustomScripts.SEND_TO_NAMED_WAYPOINT.value:
                # The most important argument
                position_name = script_args.get("position_name")
                # Defaults to the current map
                map_name = script_args.get("map_name", self.robot_state.current_map.map_name)
                success = await self.robot_api.send_to_named_waypoint(
                    position_name, map_name, self.robot_state.firmware_version
                )
            elif script_name == CustomScripts.PAUSE_NAVIGATION_TASK.value:
                success = await self.robot_api.pause_navigation_task(
                    self.robot_state.firmware_version
                )
            elif script_name == CustomScripts.RESUME_NAVIGATION_TASK.value:
                success = await self.robot_api.resume_navigation_task(
                    self.robot_state.firmware_version
                )
            elif script_name == CustomScripts.CANCEL_NAVIGATION_TASK.value:
                success = await self.robot_api.cancel_navigation_task(
                    self.robot_state.firmware_version
                )

            else:
                return options["result_function"](
                    CommandResultCode.FAILURE, f"Custom command '{script_name}' is not implemented"
                )

            if success:
                return options["result_function"](CommandResultCode.SUCCESS)
            else:
                return options["result_function"](
                    CommandResultCode.FAILURE, "Failed to execute command"
                )

        try:
            # Waypoint navigation
            if command_name == COMMAND_NAV_GOAL:
                pose = args[0]
                x = float(pose["x"])
                y = float(pose["y"])
                orientation = math.degrees(float(pose["theta"]))
                map = self.robot_state.current_map
                if map is None:
                    return options["result_function"](CommandResultCode.FAILURE, "No map available")
                success = await self.robot_api.send_waypoint(
                    x,
                    y,
                    orientation,
                    map.map_name,
                    self.robot_state.firmware_version,
                )
                if success:
                    return options["result_function"](CommandResultCode.SUCCESS)
                else:
                    return options["result_function"](
                        CommandResultCode.FAILURE, "Failed to execute command"
                    )

            # Pose initalization
            elif command_name == COMMAND_INITIAL_POSE:
                # Localize the robot within the current map
                map = self.robot_state.current_map
                if map is None:
                    return options["result_function"](CommandResultCode.FAILURE, "No map available")
                current_pose = self.robot_state.pose
                pose_diff = args[0]
                new_x = current_pose["x"] + float(pose_diff["x"])
                new_y = current_pose["y"] + float(pose_diff["y"])
                new_orientation = current_pose["yaw"] + float(pose_diff["theta"])
                # Normalize the angle to be between -pi and pi
                new_orientation = ((new_orientation + math.pi) % (2 * math.pi)) - math.pi
                new_orientation = math.degrees(new_orientation)
                success = await self.robot_api.localize_at(
                    new_x, new_y, new_orientation, map.map_name
                )
                if success:
                    return options["result_function"](CommandResultCode.SUCCESS)
                else:
                    return options["result_function"](
                        CommandResultCode.FAILURE, "Failed to execute command"
                    )

        except Exception as e:
            # HACK(b-Tomas): If navGoal or initalPose fail, the edge-sdk crashes because it
            # attempts to use args[0] (a pose) as the filename for the command result.
            # Converting it to a string prevents the connector from crashing, but the command
            # also appears successful, which is misleading.
            # TODO(b-Tomas): Fix this in the edge-sdk, and then remove this hack.
            args[0] = command_name
            raise e

        # InOrbit messages (PublishToTopic actions)
        if command_name == COMMAND_MESSAGE:
            message = args[0]
            if message == CommandMessages.PAUSE.value:
                success = await self.robot_api.pause()
            elif message == CommandMessages.RESUME.value:
                success = await self.robot_api.resume()
            else:
                return options["result_function"](
                    CommandResultCode.FAILURE, f"Message '{message}' is not implemented"
                )

            if success:
                return options["result_function"](CommandResultCode.SUCCESS)
            else:
                return options["result_function"](
                    CommandResultCode.FAILURE, "Failed to execute command"
                )

        else:
            return options["result_function"](
                CommandResultCode.FAILURE, f"'{command_name}' is not implemented"
            )

    def is_robot_available(self) -> bool:
        """Check if the robot is available for receiving commands.

        Returns:
            bool: True if the robot is online, False otherwise.
        """
        # If the last call was successful, return True
        return self.robot_api._last_call_successful

    def publish_mission_tracking(self, report: dict) -> None:
        """Publish a mission tracking report to InOrbit."""
        self._robot_session.publish_key_values({"mission_tracking": report}, is_event=True)
