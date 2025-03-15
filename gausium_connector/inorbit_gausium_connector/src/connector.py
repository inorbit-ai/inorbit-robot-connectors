# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import io
import math
import os
import tempfile
from typing import override

from inorbit_connector.connector import Connector
from inorbit_connector.models import MapConfig
from inorbit_edge.robot import (
    COMMAND_CUSTOM_COMMAND,
    COMMAND_INITIAL_POSE,
    COMMAND_MESSAGE,
    COMMAND_NAV_GOAL,
)
from inorbit_gausium_connector.src.robot.robot_api import ModelTypeMismatchError
from PIL import Image

from .. import __version__
from .config.connector_model import ConnectorConfig
from .robot import create_robot_api


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
        self.robot_api = create_robot_api(
            connector_type=config.connector_type,
            base_url=config.connector_config.base_url,
            loglevel=config.log_level.value,
            ignore_model_type_validation=config.connector_config.ignore_model_type_validation,
        )
        self.status = {}

    def _connect(self) -> None:
        """Connect to the robot services.

        This method should always call super.
        """
        super()._connect()

    def _execution_loop(self) -> None:
        """The main execution loop for the connector.

        This is where the meat of your connector is implemented. It is good practice to
        handle things like action requests in a threaded manner so that the connector
        does not block the execution loop.
        """

        # Update the robot data
        # If case of a model type mismatch, raise an exception so that the connector is stopped.
        # Otherwise, log the error and continue.
        try:
            self.robot_api.update()
        except ModelTypeMismatchError as ex:
            raise ex
        except Exception as ex:
            self._logger.error(f"Failed to refresh robot data: {ex}")
            return

        self.publish_pose(**self.robot_api.pose)
        self._robot_session.publish_odometry(**self.robot_api.odometry)
        self._robot_session.publish_key_values(
            {
                **self.robot_api.key_values,
                "connector_version": __version__,
            }
        )

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
            map_data = self.robot_api.current_map
            # HACK(b-Tomas): Create a temporary file with .png extension to store the map image
            # It should be possible to avoid this and work with the in-memory bytes instead
            if map_data and map_data.map_image:
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
                    image = Image.open(io.BytesIO(map_data.map_image))

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
                    flipped_bytes = map_data.map_image
                try:
                    # Write the map image bytes to the temporary file
                    with os.fdopen(fd, "wb") as tmp_file:
                        tmp_file.write(flipped_bytes)

                    # Create a new map configuration
                    self.config.maps[frame_id] = MapConfig(
                        file=temp_path,
                        map_id=map_data.map_id,
                        frame_id=frame_id,
                        origin_x=map_data.origin_x,
                        origin_y=map_data.origin_y,
                        resolution=map_data.resolution,
                    )

                    self._logger.info(f"Added map {frame_id} from robot to configuration")
                except Exception as e:
                    self._logger.error(f"Failed to create temporary map file: {e}")
                    os.unlink(temp_path)  # Clean up the file in case of error
            else:
                self._logger.error(f"No map data available for {frame_id}")
                return
            self.publish_map(frame_id, is_update)

    def _inorbit_command_handler(self, command_name, args, options):
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
        self._logger.info(f"Received '{command_name}'!. {args}")

        # InOrbit custom commands (RunScript actions)
        if command_name == COMMAND_CUSTOM_COMMAND:
            if not self.is_robot_available():
                self._logger.error("Robot is unavailable")
                return options["result_function"]("1", "Robot is not available")

            # Parse command name and arguments
            # script_name = args[0]
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
                return options["result_function"]("1", "Invalid arguments")

            # if script_name == ...:
            #     pass
            # else:
            #     # Other kind if custom commands may be handled by the edge-sdk (e.g. user_scripts)
            #     # and not by the connector code itself
            #     # Do not return any result and leave it to the edge-sdk to handle it
            #     return

            # Return '0' for success
            return options["result_function"]("0")

        # Waypoint navigation
        elif command_name == COMMAND_NAV_GOAL:
            pose = args[0]
            x = float(pose["x"])
            y = float(pose["y"])
            orientation = math.degrees(float(pose["theta"]))
            self.robot_api.send_waypoint(x, y, orientation)

        # Pose initalization
        elif command_name == COMMAND_INITIAL_POSE:
            # Localize the robot within the current map
            current_pose = self.robot_api.pose
            pose_diff = args[0]
            new_x = current_pose["x"] + float(pose_diff["x"])
            new_y = current_pose["y"] + float(pose_diff["y"])
            new_orientation = current_pose["yaw"] + float(pose_diff["theta"])
            # Normalize the angle to be between -pi and pi
            new_orientation = ((new_orientation + math.pi) % (2 * math.pi)) - math.pi
            new_orientation = math.degrees(new_orientation)
            self.robot_api.localize_at(new_x, new_y, new_orientation)

        # InOrbit messages (PublishToTopic actions)
        elif command_name == COMMAND_MESSAGE:
            return options["result_function"]("1", f"'{COMMAND_MESSAGE}' is not implemented")

        else:
            return options["result_function"]("1", f"'{command_name}' is not implemented")

    def is_robot_available(self) -> bool:
        """Check if the robot is available for receiving commands.

        Returns:
            bool: True if the robot is online, False otherwise.
        """
        # If the last call was successful and the robot is online, return True
        # If unable to determine if the robot is online from the status data, assume it is
        return self.robot_api._last_call_successful and self.status.get("online", True)
