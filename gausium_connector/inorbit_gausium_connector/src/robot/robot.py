# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import asyncio
import logging
from math import radians
from typing import Coroutine, List

from inorbit_gausium_connector.src.robot.constants import WorkType
from inorbit_gausium_connector.src.robot.datatypes import MapData, ModelTypeMismatchError, PathData
from inorbit_gausium_connector.src.robot.robot_api import GausiumCloudAPI
from inorbit_gausium_connector.src.robot.utils import grid_units_to_coordinate


class Robot:
    """
    This class contains the main logic fetching data from the robot.
    Each API endpoint is hit in a separate loop at its own specific frequency.
    The property accessors are used to get the latest fetched data from the robot.
    """

    def __init__(
        self,
        api_wrapper: GausiumCloudAPI,
        allowed_model_types: List[str] = [],
        loglevel: str = "INFO",
        default_polling_freq: float = 5,
    ):
        """Initialize the Robot class.

        Args:
            api_wrapper (GausiumRobotAPI): The API wrapper to use.
            allowed_model_types (List[str], optional): The allowed model types. Defaults to an
                empty list.
            loglevel (str, optional): The log level to use. Defaults to "INFO".
            default_polling_freq (float, optional): The default polling frequency. Defaults to 5hz.
        """
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(loglevel)
        self._allowed_model_types: List[str] = allowed_model_types

        # Already initialized API wrapper
        # This class does not manage the API wrapper lifecycle
        self._api_wrapper = api_wrapper

        # Auxiliary data for running polling tasks
        self._default_polling_freq: float = default_polling_freq
        self._running_tasks: list[asyncio.Task] = []
        self._stop_event = asyncio.Event()
        # List of (coroutine, frequency) tuples.
        # The coroutine will be run in a loop at the specified frequency.
        # Populate this list with the _add_polling_target method.
        self._polling_targets: list[tuple[Coroutine, float]] = []

        # Robot state as fetched from the API
        # It is then parsed by every property accessor to InOrbit format
        self._robot_info: dict = {}
        self._firmware_version: str | None = None
        self._add_polling_target(self._update_robot_info)
        self._robot_status: dict = {}
        self._add_polling_target(self._update_robot_status)
        self._device_status: dict = {}
        self._current_map: MapData | None = None
        self._add_polling_target(self._update_device_status)
        self._position: dict = {}
        self._add_polling_target(self._update_position)

    def _add_polling_target(self, coro: Coroutine, frequency: float | None = None) -> None:
        """Add a coroutine to the polling targets"""
        self._polling_targets.append((coro, frequency or self._default_polling_freq))

    def start(self) -> None:
        """Start the tasks that would fetch data from the robot."""
        for coro, frequency in self._polling_targets:
            self._run_in_loop(coro, frequency)

    async def stop(self) -> None:
        """Stop the tasks that would fetch data from the robot."""
        # Signal all tasks to stop
        self._stop_event.set()

        # Give tasks a chance to exit gracefully
        if self._running_tasks:
            try:
                # Wait for tasks to complete with a timeout
                done, pending = await asyncio.wait(
                    self._running_tasks,
                    timeout=1.0,  # Allow 1 second for graceful shutdown
                    return_when=asyncio.ALL_COMPLETED,
                )

                # Only cancel tasks that didn't finish in time
                for task in pending:
                    task.cancel()

                # Wait briefly for cancellations to process
                if pending:
                    await asyncio.wait(pending, timeout=0.5)

            except Exception as e:
                self._logger.error(f"Error during graceful shutdown: {e}")

        # Clear the task list
        self._running_tasks.clear()

    async def _update_robot_info(self) -> None:
        """Fetch the robot info from the robot."""
        robot_info_res = await self._api_wrapper._get_robot_info()
        if not robot_info_res:
            return
        self._robot_info = self._api_call_success_or_log(robot_info_res).get("data", {})
        if not self._robot_info:
            self._logger.warning("Empty robot info data")
            return

        # Validate the model type of the robot and the API wrapper in use match
        model_type = self._robot_info.get("modelType")
        if self._allowed_model_types and model_type not in self._allowed_model_types:
            raise ModelTypeMismatchError(model_type, self._allowed_model_types)

        # Update the firmware version
        software_version = self._robot_info.get("softwareVersion")
        if software_version:
            # Extract version number (e.g., from "GS-ES50-OS1604-PRO800-OTA_V2-19-6" get "2-19-6")
            self._firmware_version = software_version.split("V")[-1]

    async def _update_robot_status(self) -> None:
        """Fetch the robot status from the robot."""
        robot_status_res = await self._api_wrapper._get_robot_status()
        if not robot_status_res:
            return
        self._robot_status = self._api_call_success_or_log(robot_status_res).get("data", {})
        if not self._robot_status:
            self._logger.warning("Empty robot status data")
            return

    async def _update_device_status(self) -> None:
        """Fetch the device status from the robot."""
        device_status_res = await self._api_wrapper._get_device_status()
        if not device_status_res:
            return
        self._device_status = self._api_call_success_or_log(device_status_res).get("data", {})
        if not self._device_status:
            self._logger.warning("Empty device status data")
            return
        # Update the current map data if it's different or not set yet
        curr_map_name = self._device_status.get("currentMapName")
        curr_map_id = self._device_status.get("currentMapID")
        if self._current_map and curr_map_id != self._current_map.map_id:
            self._logger.info(
                f"Current map changed from {self._current_map.map_name} to {curr_map_name}"
            )
            self._current_map = None
        if self._current_map is None and curr_map_name and curr_map_id:
            if self._position:
                self._current_map = MapData(
                    map_name=curr_map_name,
                    map_id=curr_map_id,
                    origin_x=self._position.get("mapInfo", {}).get("originX"),
                    origin_y=self._position.get("mapInfo", {}).get("originY"),
                    resolution=self._position.get("mapInfo", {}).get("resolution"),
                )
            else:
                self._logger.warning("No position data available, skipping map update")

    async def _update_position(self) -> None:
        """Fetch the position from the robot."""
        self._position = await self._api_wrapper._fetch_position()
        if not self._position:
            self._logger.warning("Empty position data")

    def _api_call_success_or_log(self, response_json: dict) -> dict:
        """Check if a Gaussian Cloud API call was successful or log.
        If successful, return the original dict.
        If not, log the error message and return an empty dict.

        Args:
            response_json (dict): The response from the API call. Note it should be a
                successful response (200 code).

        Returns:
            dict: The response from the API call.
        """
        if response_json.get("successed", False):
            # Return the original dict if successful
            return response_json
        else:
            error_code = response_json.get("errorCode")
            error_msg = response_json.get("msg")
            data = response_json.get("data")
            human_readable_err = "API call failed"
            if error_code:
                human_readable_err += f" with error code {error_code}"
            if error_msg:
                human_readable_err += f": {error_msg}"
            if data:
                human_readable_err += f", data: {data}"
            self._logger.error(human_readable_err)
            return {}

    @property
    def frame_id(self) -> str:
        """Return the frame id"""
        return self._current_map.map_name if self._current_map else "map"

    @property
    def pose(self) -> dict | None:
        """Return the robot pose"""
        try:
            return {
                "x": self._position["worldPosition"]["position"]["x"],
                "y": self._position["worldPosition"]["position"]["y"],
                "yaw": radians(self._position["angle"]),
                "frame_id": self.frame_id,
            }
        except KeyError:
            return None

    @property
    def path(self) -> PathData | None:
        return self._path_from_robot_status(self._robot_status, self.frame_id)

    def _path_from_robot_status(self, robot_status_data: dict, frame_id: str) -> PathData | None:
        """Get the path of the robot from the robot status data"""
        work_type = robot_status_data.get("robotStatus", {}).get("workType")
        path_points = []

        # If navigating, publish one path segment connecting the current pose to the target pose
        if work_type == WorkType.NAVIGATING.value:
            target_pose = (
                robot_status_data.get("statusData", {})
                .get("targetPos", {})
                .get("worldPose", {})
                .get("position", {})
            )
            if not target_pose.get("x") or not target_pose.get("y"):
                self._logger.warning("No target pose found for path while navigating")
            else:
                path_points = [
                    (self.pose["x"], self.pose["y"]),
                    (target_pose["x"], target_pose["y"]),
                ]

        # If executing a task, publish the "taskSegments"
        elif work_type == WorkType.EXECUTE_TASK.value:
            # Current map data must be set in order to convert grid units to coordinates
            if not self.current_map:
                self._logger.warning("No current map data available, skipping task path")

            else:
                task_segments = robot_status_data.get("statusData", {}).get("taskSegments", [])
                current_path = (
                    robot_status_data.get("statusData", {})
                    .get("task", {})
                    .get("start_param", {})
                    .get("path_name")
                )
                if not current_path:
                    self._logger.warning("No current path found for task path")

                else:
                    # Filter the task segments by the current path
                    task_segments = [
                        segment
                        for segment in task_segments
                        if segment.get("pathName") == current_path
                    ]

                    # Order the segments within the path by groupPathName to give the points the
                    # correct order.
                    # Each segment has a groupPathName like "__AREA_PATH_0", which doesn't help with
                    # alphabetical sort.
                    task_segments.sort(
                        key=lambda x: int(x.get("groupPathName").split("__AREA_PATH_")[1])
                    )

                    # Reduce each path to a single path
                    path = []
                    for segment in task_segments:
                        data = segment.get("data", [])
                        path.extend(data)

                    path_points.extend(
                        [
                            grid_units_to_coordinate(point["x"], point["y"], self.current_map)
                            for point in path
                        ]
                    )

        return PathData(
            path_points=path_points,
            frame_id=frame_id,
        )

    @property
    def key_values(self) -> dict | None:
        return {
            **self._position,
            **self._robot_info,
            **self._device_status,
            **self._robot_status,
        }

    @property
    def current_map(self) -> MapData:
        """Get the current map"""
        return self._current_map

    @property
    def firmware_version(self) -> str | None:
        """Get the firmware version of the robot."""
        return self._firmware_version

    def _run_in_loop(self, coro: Coroutine, frequency: float | None = None) -> None:
        """Run a coroutine in a loop at a specified frequency. If no frequency is
        provided, the default update frequency will be used."""

        async def loop():
            try:
                while not self._stop_event.is_set():
                    try:
                        # Check stop_event between each iteration
                        if self._stop_event.is_set():
                            break

                        await asyncio.gather(
                            coro(),
                            asyncio.sleep(1 / (frequency or self._default_polling_freq)),
                        )
                    except asyncio.CancelledError:
                        # Handle cancellation gracefully
                        break
                    except Exception as e:
                        self._logger.error(
                            f"Error in loop running {coro.__name__}: "
                            f"{str(e) or e.__class__.__name__}"
                        )
                        # Shorter sleep during errors to check stop_event more
                        # frequently
                        await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                # Exit cleanly when cancelled
                pass

        self._running_tasks.append(asyncio.create_task(loop()))
