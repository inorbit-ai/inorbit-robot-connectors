# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import logging
import asyncio
from abc import ABC, abstractmethod
from math import radians
from typing import Coroutine, List, Optional, Tuple, override

import httpx
from pydantic import BaseModel, HttpUrl

from inorbit_gausium_connector.src.robot.constants import WorkType


class ModelTypeMismatchError(Exception):
    """Exception raised when the model type of the robot and the API wrapper in use do not match."""

    def __init__(self, robot_model_type: str, supported_model_types: List[str]):
        super().__init__(
            f"Robot model type '{robot_model_type}' is not supported by the API wrapper. "
            f"Supported model types are: {supported_model_types}.\n"
            "Make sure the `connector_type` value in the configuration matches the robot "
            "model."
        )


class MapData(BaseModel):
    """Data class to hold gausium map information."""

    map_name: str
    map_id: str
    origin_x: float
    origin_y: float
    resolution: float
    # Lazy loaded map image
    # NOTE: Maybe not a great solution, since some maps may be quite large
    map_image: Optional[bytes] = None


class PathData(BaseModel):
    """Data class to hold gausium path information."""

    path_points: List[Tuple[float, float]]
    path_id: str = "0"
    frame_id: str


class GausiumRobotAPI(ABC):
    """Gausium robot API wrapper."""

    def __init__(
        self,
        base_url: HttpUrl,
        loglevel: str = "INFO",
        api_req_timeout: int = 10,
        default_polling_freq: float = 10,
    ):
        """Initializes the connection with the Gausium Phantas robot

        Args:
            base_url (HttpUrl): Base URL of the robot API. e.g. "http://192.168.0.256:80/"
            loglevel (str, optional): Defaults to "INFO"
            api_req_timeout (int, optional): Default timeout for API requests. Defaults to 10.
        """
        self.logger = logging.getLogger(name=self.__class__.__name__)
        self.logger.setLevel(loglevel)
        # Use str(base_url) because httpx requires string URLs
        self.base_url = str(base_url)
        self.api_req_timeout = api_req_timeout
        # Indicates whether the last call to the API was successful
        # Useful for estimating the state of the Connector <> APIs link
        self._last_call_successful: bool | None = None
        # Initialize httpx.AsyncClient
        self.api_client = httpx.AsyncClient(base_url=self.base_url, timeout=self.api_req_timeout)
        # Auxiliary data for running polling tasks
        self._default_polling_freq: float = default_polling_freq
        self._running_tasks: list[asyncio.Task] = []
        self._stop_event = asyncio.Event()
        # List of (coroutine, frequency) tuples.
        # The coroutine will be run in a loop at the specified frequency.
        # Populate this list with the _add_polling_target method.
        self._polling_targets: list[tuple[Coroutine, float]] = []

    def _add_polling_target(self, coro: Coroutine, frequency: float | None = None) -> None:
        """Add a coroutine to the polling targets"""
        self._polling_targets.append((coro, frequency or self._default_polling_freq))

    async def start(self):
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
                self.logger.error(f"Error during graceful shutdown: {e}")

        # Clear the task list
        self._running_tasks.clear()

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
                        self.logger.error(f"Error in loop running {coro.__name__}: {e}")
                        # Shorter sleep during errors to check stop_event more
                        # frequently
                        await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                # Exit cleanly when cancelled
                pass

        self._running_tasks.append(asyncio.create_task(loop()))

    async def close(self):
        """Closes the httpx client session."""
        await self.api_client.aclose()
        self.logger.info("HTTPX client closed.")

    @property
    def last_call_successful(self) -> bool:
        """Get the last call successful status"""
        return self._last_call_successful

    def _handle_status(self, res, request_args) -> None:
        """Log and raise an exception if the request failed. Update the status of the last call if
        required"""
        self._last_call_successful = False
        try:
            res.raise_for_status()
            self._last_call_successful = True
        except httpx.HTTPStatusError as e:
            self.logger.error(f"Error making request: {e.request.method} {e.request.url}")
            self.logger.error(f"Arguments: {request_args}")
            self.logger.error(f"Response Status: {e.response.status_code}")
            self.logger.error(f"Response Body: {e.response.text[:500]}...")
            raise e

    async def _get(self, endpoint: str, timeout: int | None = None, **kwargs) -> httpx.Response:
        """Perform a GET request."""
        url_for_logging = self.base_url + endpoint.lstrip("/")
        self.logger.debug(f"GETting {url_for_logging}: {kwargs}")
        try:
            res = await self.api_client.get(
                endpoint, timeout=timeout or self.api_req_timeout, **kwargs
            )
            self._handle_status(res, kwargs)
            return res
        except httpx.RequestError as e:
            self._last_call_successful = False
            self.logger.error(f"HTTPX GET Error for {endpoint}: {e}")
            raise e

    async def _post(self, endpoint: str, timeout: int | None = None, **kwargs) -> httpx.Response:
        """Perform a POST request."""
        url_for_logging = self.base_url + endpoint.lstrip("/")
        self.logger.debug(f"POSTing {url_for_logging}: {kwargs}")
        try:
            res = await self.api_client.post(
                endpoint, timeout=timeout or self.api_req_timeout, **kwargs
            )
            log_body = res.text[:200] + "..." if len(res.text) > 200 else res.text
            self.logger.debug(f"Response status: {res.status_code}, Response body: {log_body}")
            self._handle_status(res, kwargs)
            return res
        except httpx.RequestError as e:
            self._last_call_successful = False
            self.logger.error(f"HTTPX POST Error for {endpoint}: {e}")
            raise e

    async def _delete(self, endpoint: str, timeout: int | None = None, **kwargs) -> httpx.Response:
        """Perform a DELETE request."""
        url_for_logging = self.base_url + endpoint.lstrip("/")
        self.logger.debug(f"DELETEing {url_for_logging}: {kwargs}")
        try:
            res = await self.api_client.delete(
                endpoint, timeout=timeout or self.api_req_timeout, **kwargs
            )
            log_body = res.text[:200] + "..." if len(res.text) > 200 else res.text
            self.logger.debug(f"Response status: {res.status_code}, Response body: {log_body}")
            self._handle_status(res, kwargs)
            return res
        except httpx.RequestError as e:
            self._last_call_successful = False
            self.logger.error(f"HTTPX DELETE Error for {endpoint}: {e}")
            raise e

    async def _put(self, endpoint: str, timeout: int | None = None, **kwargs) -> httpx.Response:
        """Perform a PUT request."""
        url_for_logging = self.base_url + endpoint.lstrip("/")
        self.logger.debug(f"PUTing {url_for_logging}: {kwargs}")
        try:
            res = await self.api_client.put(
                endpoint, timeout=timeout or self.api_req_timeout, **kwargs
            )
            self.logger.debug(
                f"Response status: {res.status_code}, Response body: {res.text[:200]}..."
            )
            self._handle_status(res, kwargs)
            return res
        except httpx.RequestError as e:
            self._last_call_successful = False
            self.logger.error(f"HTTPX PUT Error for {endpoint}: {e}")
            raise e

    @property
    @abstractmethod
    def pose(self) -> dict:
        """Get the pose of the robot. Returns cached data. Call update() or initialize() first."""
        pass

    @property
    @abstractmethod
    def odometry(self) -> dict:
        """Get the odometry of the robot. Returns cached data. Call update() or initialize()
        first."""
        pass

    @property
    @abstractmethod
    def path(self) -> PathData:
        """Get the current path of the robot. Returns cached data. Call update() or initialize()
        first."""
        pass

    @property
    @abstractmethod
    def key_values(self) -> dict:
        """Get the key values of the robot. Returns cached data. Call update() or initialize()
        first."""
        pass

    @property
    @abstractmethod
    def current_map(self) -> MapData:
        """Get the current map. Returns cached data. Call update() or initialize() first."""
        pass

    @abstractmethod
    async def send_waypoint(self, x: float, y: float, orientation: float) -> bool:
        """Receives a pose and sends a request to command the robot to navigate to the waypoint"""
        pass

    @abstractmethod
    async def localize_at(self, x: float, y: float, orientation: float) -> bool:
        """Requests the robot to localize at the given coordinates within the same map"""
        pass

    @abstractmethod
    async def pause(self) -> bool:
        """Requests the robot to pause whatever it is doing"""
        pass

    @abstractmethod
    async def resume(self) -> bool:
        """Requests the robot to resume whatever it was doing"""
        pass

    @abstractmethod
    async def start_task_queue(self, **kwargs) -> bool:
        """Starts the cleaning task"""
        pass

    @abstractmethod
    async def pause_task_queue(self) -> bool:
        """Pauses the cleaning task"""
        pass

    @abstractmethod
    async def resume_task_queue(self) -> bool:
        """Resumes the cleaning task"""
        pass

    @abstractmethod
    async def cancel_task_queue(self) -> bool:
        """Cancels the cleaning task"""
        pass

    @abstractmethod
    async def send_to_named_waypoint(self, **kwargs) -> bool:
        """Sends the robot to a named waypoint"""
        pass

    @abstractmethod
    async def pause_navigation_task(self) -> bool:
        """Pauses the navigation task"""
        pass

    @abstractmethod
    async def resume_navigation_task(self) -> bool:
        """Resumes the navigation task"""
        pass

    @abstractmethod
    async def cancel_navigation_task(self) -> bool:
        """Cancels the navigation task"""
        pass


class GausiumCloudAPI(GausiumRobotAPI):
    """Gausium cloud API wrapper."""

    def __init__(
        self,
        base_url: HttpUrl,
        loglevel: str = "INFO",
        allowed_model_types: List[str] = [],
        api_req_timeout: int = 10,
        default_polling_freq: float = 10,
    ):
        """Initialize the Gausium Cloud API wrapper.

        Args:
            base_url (HttpUrl): Base URL for the Gausium Cloud API.
            loglevel (str, optional): Logging level. Defaults to "INFO".
            allowed_model_types (List[str], optional): List of robot model types
                supported by this API wrapper. Defaults to an empty list.
                If empty, the model type will not be validated.
            api_req_timeout (int, optional): Default timeout for API requests. Defaults to 10.
            default_polling_freq (float, optional): Default polling frequency. Defaults to 10.
        """
        super().__init__(base_url, loglevel, api_req_timeout, default_polling_freq)
        self._pose: dict | None = None
        self._odometry: dict | None = None
        self._path: PathData | None = None
        self._key_values: dict | None = None
        self._firmware_version: str | None = None
        self._device_status: dict | None = None
        self._current_map: MapData | None = None
        self._is_initialized: bool = False
        self._allowed_model_types: List[str] = allowed_model_types
        self._last_pause_command: str | None = None

        self._add_polling_target(self._update)

    async def _update(self) -> None:
        """Update the robot's status data concurrently using asyncio."""

        # Fetch fresh data from the robot concurrently using asyncio.gather
        tasks = [
            self._get_robot_info(),
            self._get_device_status(),
            self._fetch_position(),
            self._get_robot_status(),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check for exceptions before processing results
        exceptions = [res for res in results if isinstance(res, Exception)]
        if exceptions:
            for exc in exceptions:
                self.logger.error(f"Error during concurrent update: {exc}")
            # Decide how to handle partial failure - here we raise the first one
            raise exceptions[0]

        robot_info_res, device_status_res, position_res, robot_status_res = results

        # Process results (assuming successful calls return dicts)
        robot_info = robot_info_res.get("data", {})
        device_data = device_status_res.get("data", {})
        # _fetch_position returns the full JSON response, not just data field
        position_data = position_res
        robot_status_data = robot_status_res.get("data", {})

        # Validate the model type of the robot and the API wrapper in use match
        model_type = robot_info.get("modelType")
        if self._allowed_model_types and model_type not in self._allowed_model_types:
            raise ModelTypeMismatchError(model_type, self._allowed_model_types)

        # Update the firmware version
        software_version = robot_info.get("softwareVersion")
        if software_version:
            # Extract version number (e.g., from "GS-ES50-OS1604-PRO800-OTA_V2-19-6" get "2-19-6")
            self._firmware_version = software_version.split("V")[-1]

        # Update current device status
        self._device_status = device_data

        # Update the current map data if it's different or not set yet
        curr_map_name = self._device_status.get("currentMapName")
        curr_map_id = self._device_status.get("currentMapID")
        if self._current_map and curr_map_id != self._current_map.map_id:
            self.logger.info(
                f"Current map changed from {self._current_map.map_name} to {curr_map_name}"
            )
            self._current_map = None
        if self._current_map is None and curr_map_name and curr_map_id:
            self._current_map = MapData(
                map_name=curr_map_name,
                map_id=curr_map_id,
                origin_x=position_data.get("mapInfo", {}).get("originX"),
                origin_y=position_data.get("mapInfo", {}).get("originY"),
                resolution=position_data.get("mapInfo", {}).get("resolution"),
            )

        # Update publishable data
        # The dictionaries are unpacked into key-value pairs. Deep nested dictionaries are
        # published as such, requiring the corresponding datasources to be defined as json
        # type, or derived to access nested values.
        self._key_values = {
            **position_data,
            **robot_info,
            **device_data,
            **robot_status_data,
        }
        frame_id = self._current_map.map_name if self._current_map else "map"
        self._pose = {
            "x": position_data.get("worldPosition", {}).get("position", {}).get("x"),
            "y": position_data.get("worldPosition", {}).get("position", {}).get("y"),
            "yaw": radians(position_data.get("angle")),
            "frame_id": frame_id,
        }
        self._odometry = {}  # TODO: Get the odometry data
        self._path = self._path_from_robot_status(robot_status_data, frame_id)

    def _path_from_robot_status(self, robot_status_data: dict, frame_id: str) -> PathData:
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
                self.logger.warning("No target pose found for path while navigating")
                path_points = []
            else:
                path_points = [
                    (self.pose["x"], self.pose["y"]),
                    (target_pose["x"], target_pose["y"]),
                ]

        # If executing a task, publish the "taskSegments"
        elif work_type == WorkType.EXECUTE_TASK.value:
            task_segments = robot_status_data.get("statusData", {}).get("taskSegments", [])
            for segment in task_segments:
                data = segment.get("data", [])
                path_points.extend(
                    [self._grid_units_to_coordinate(point["x"], point["y"]) for point in data]
                )

        return PathData(
            path_points=path_points,
            frame_id=frame_id,
        )

    @property
    @override
    def pose(self) -> dict:
        """Get the pose of the robot"""
        if self._pose is None:
            raise AttributeError("Pose data not available. Call update() first.")
        return self._pose

    @property
    @override
    def odometry(self) -> dict:
        """Get the odometry of the robot"""
        if self._odometry is None:
            raise AttributeError("Odometry data not available. Call update() first.")
        return self._odometry

    @property
    @override
    def path(self) -> PathData:
        """Get the current path of the robot"""
        if self._path is None:
            raise AttributeError("Path data not available. Call update() first.")
        return self._path

    @property
    @override
    def key_values(self) -> dict:
        """Get the key values of the robot"""
        if self._key_values is None:
            raise AttributeError("Key values data not available. Call update() first.")
        return self._key_values

    @property
    def firmware_version(self) -> str:
        """Get the firmware version of the robot"""
        if self._firmware_version is None:
            raise AttributeError("Firmware version not available. Call update() first.")
        return self._firmware_version

    @property
    def device_status(self) -> dict:
        """Get the full device status"""
        if self._device_status is None:
            raise AttributeError("Device status data not available. Call update() first.")
        return self._device_status

    @property
    def is_initialized(self) -> bool:
        """Check if the robot is initialized"""
        return self._is_initialized

    @property
    def current_map(self) -> MapData:
        """Get the current map.
        If the map is not loaded, the update() method will load it.
        If the map image isn't loaded, it will be lazily fetched from the robot."""
        if self._current_map is None:
            raise AttributeError("Current map data not available. Call update() first.")
        if self._current_map and self._current_map.map_image is None:
            self._current_map.map_image = self._get_map_image(self._current_map.map_name)
        return self._current_map

    @override
    async def send_waypoint(self, x: float, y: float, orientation: float) -> bool:
        """Send the robot to a waypoint (named waypoint)

        Args:
            x (float): X coordinate in grid units
            y (float): Y coordinate in grid units
            orientation (float): Orientation angle in degrees

        Returns:
            bool: True if successful, False otherwise
        """
        map_name = self._current_map.map_name if self._current_map else None
        if not map_name:
            raise Exception("No current map found to send waypoint to")
        grid_x, grid_y = self._coordinate_to_grid_units(x, y)
        self.logger.debug(f"Converted {x}, {y} coordinates to grid units: {grid_x}, {grid_y}")
        return await self._navigate_to_coordinates(map_name, grid_x, grid_y, orientation)

    @override
    async def localize_at(self, x: float, y: float, orientation: float) -> bool:
        """Requests the robot to localize at the given coordinates within the same map"""
        map_name = self._current_map.map_name if self._current_map else None
        if not map_name:
            raise Exception("No current map found to localize at")
        return await self._initialize_at_custom_position(map_name, x, y, orientation)

    @override
    async def pause(self) -> bool:
        """Requests the robot to pause whatever it is doing.
        It fetches the state of cleaning and navigation and the pauses whichever is running"""
        # Fetch firmware version if not already known
        if self._firmware_version is None:
            await self.update()  # Update caches firmware version

        # In firmware version lower than v3-6-6, nav and cleaning pause commands are the same
        if not await self._is_firmware_post_v3_6_6():
            return await self._pause_task_queue()

        # In firmware version v3-6-6 and higher, commands are different
        try:
            is_finished = await self._is_cleaning_task_finished()
        except Exception as e:
            self.logger.warning(
                f"Could not determine cleaning task status: {e}. Assuming navigation pause."
            )
            is_finished = True  # Assume finished if check fails, try pausing navigation

        if is_finished:
            self.logger.info("Cleaning task finished or unknown, attempting to pause navigation.")
            self._last_pause_command = "navigation"
            return await self._pause_navigation_task()
        else:
            self.logger.info("Cleaning task active, attempting to pause cleaning.")
            self._last_pause_command = "cleaning"
            # Decide which pause command to use based on firmware
            # Assuming _pause_task_queue works for both single/multi map < 3.6.6
            # and _pause_task works for >= 3.6.6 (check Gausium docs for specifics)
            # Let's stick to pause_task_queue for now based on original logic separation
            return (
                await self._pause_task_queue()
            )  # Or potentially _pause_task() or _pause_multi_map_cleaning_task()

    @override
    async def resume(self) -> bool:
        """Requests the robot to resume a previously paused task"""
        if self._firmware_version is None:
            await self.update()

        # In firmware version lower than v3-6-6, commands are the same
        if not await self._is_firmware_post_v3_6_6():
            return await self._resume_task_queue()

        # In firmware version v3-6-6 and higher, commands are different.
        # Get the previously paused command to know which one to resume
        if self._last_pause_command == "cleaning":
            self.logger.info("Resuming previously paused cleaning task.")
            self._last_pause_command = None
            # Decide which resume command to use based on firmware/context
            # Let's stick to resume_task_queue for now
            return (
                await self._resume_task_queue()
            )  # Or potentially _resume_task() or _resume_multi_map_cleaning_task()
        elif self._last_pause_command == "navigation":
            self.logger.info("Resuming previously paused navigation task.")
            self._last_pause_command = None
            return await self._resume_navigation_task()
        else:
            self.logger.warning("No previously paused command recorded. Attempting general resume.")
            # Attempt a general resume if state is unknown (could try both or pick one)
            # Let's try resuming task queue as a default guess
            try:
                success = await self._resume_task_queue()
                if success:
                    return True
            except Exception:
                pass  # Ignore error and try navigation resume
            # If task resume fails or wasn't tried, try navigation resume
            try:
                return await self._resume_navigation_task()
            except Exception as e:
                self.logger.error(f"Failed to resume any task: {e}")
                return False

    @override
    async def start_task_queue(
        self,
        task_queue_name: str,
        map_name: str | None = None,
        loop: bool = False,
        loop_count: int = 0,
    ) -> bool:
        """Starts the cleaning task.

        Args:
            task_queue_name (str): Name of the task queue to start the cleaning task on
            map_name (str | None, optional): Name of the map to start the cleaning task on.
                Defaults to the current map.
            loop (bool, optional): Whether to loop the task. Defaults to False.
            loop_count (int, optional): Number of loops. Defaults to 0.

        Returns:
            bool: True if successful, False otherwise
        """
        map_name = map_name if map_name else await self._get_current_map_or_raise().map_name
        return await self._start_cleaning_task(map_name, task_queue_name, loop, loop_count)

    @override
    async def pause_task_queue(self) -> bool:
        """Pauses the cleaning task"""
        return await self._pause_task_queue()

    @override
    async def resume_task_queue(self) -> bool:
        """Resumes the cleaning task"""
        return await self._resume_task_queue()

    @override
    async def cancel_task_queue(self) -> bool:
        """Cancels the cleaning task"""
        return await self._cancel_cleaning_task()

    @override
    async def send_to_named_waypoint(self, position_name: str, map_name: str | None = None) -> bool:
        """Sends the robot to a named waypoint.

        Args:
            position_name (str): Name of the waypoint to send the robot to
            map_name (str | None, optional): Name of the map to send the robot to.
                Defaults to the current map.

        Returns:
            bool: True if successful, False otherwise
        """
        map_name = map_name if map_name else await self._get_current_map_or_raise().map_name
        return await self._navigate_to_named_waypoint(map_name, position_name)

    @override
    async def pause_navigation_task(self) -> bool:
        """Pauses the navigation task"""
        return await self._pause_navigation_task()

    @override
    async def resume_navigation_task(self) -> bool:
        """Resumes the navigation task"""
        return await self._resume_navigation_task()

    @override
    async def cancel_navigation_task(self) -> bool:
        """Cancels the navigation task"""
        return await self._cancel_navigation_task()

    def _get_current_map_or_raise(self) -> MapData:
        """Get the current map or raise an exception if it's not set"""
        if self._current_map is None:
            raise Exception("No current map found")
        return self._current_map

    def _success_or_raise(self, response_json: dict) -> dict:
        """Check if a Gaussian Cloud API call was successful or raise an exception that shows the
        error message.

        Args:
            response_json (dict): The response from the API call. Note it should be a successful
                response (200 code).

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
            raise Exception(human_readable_err)

    # ---------- General APIs ----------#

    async def _get_robot_info(self) -> dict:
        """Fetch the robot info to get firmware version and other details

        Returns:
            dict: The robot info response
        """
        res = await self._get("/gs-robot/info")
        return res.json()

    async def _get_robot_status(self) -> dict:
        """Fetch the robot status

        Returns:
            dict: The robot status data
        """
        res = await self._get("/gs-robot/real_time_data/robot_status")
        return res.json()

    async def _is_firmware_post_v3_6_6(self) -> bool:
        """Check if the firmware version is v3-6-6 or higher

        Returns:
            bool: True if firmware is v3-6-6 or higher, False otherwise
        """
        # Ensure firmware version is available
        if self._firmware_version is None:
            self.logger.warning("Firmware version not cached. Calling update() to fetch it.")
            await self.update()
            if self._firmware_version is None:
                self.logger.error(
                    "Failed to fetch firmware version after update(). Assuming >= v3.6.6."
                )
                return True  # Or False, depending on desired default behaviour

        version = self._firmware_version
        # Extract version number parts
        version_parts = version.split("-")
        if len(version_parts) >= 3:
            major = int(version_parts[0])
            minor = int(version_parts[1])
            patch = int(version_parts[2])

            # Compare with v3-6-6
            if major < 3:
                return False
            elif major == 3 and minor < 6:
                return False
            elif major == 3 and minor == 6 and patch < 6:
                return False
        return True

    # ---------- Localization APIs ----------#

    async def _fetch_position(self) -> dict:
        """Fetch the current position of the robot

        Returns:
            dict: The position data
        """
        res = await self._get("/gs-robot/real_time_data/position")
        return res.json()

    async def _load_map(self, map_name: str) -> bool:
        """Load a specified map

        Args:
            map_name (str): Name of the map to load

        Returns:
            bool: True if successful, False otherwise
        """
        res = await self._get(f"/gs-robot/cmd/load_map?map_name={map_name}")
        response = res.json()
        # Check success using the helper
        processed_response = self._success_or_raise(response)
        success = processed_response is not None  # success_or_raise returns dict on success
        if success:
            self.logger.info(f"Map '{map_name}' loaded successfully. Clearing cached map data.")
            self._is_initialized = False  # Map changed, robot needs to be initialized again
            self._current_map = None  # Clear cached map data
        return success

    async def _initialize_at_point(
        self, map_name: str, init_point_name: str, with_rotation: bool = True
    ) -> bool:
        """Initialize the robot on the specified map at the specified point

        Args:
            map_name (str): Name of the map
            init_point_name (str): Name of the initialization point
            with_rotation (bool, optional): Whether to perform rotation for
                initialization. Defaults to True.

        Returns:
            bool: True if successful, False otherwise
        """
        # Check if the map needs loading (using cached _current_map)
        if self._current_map is None or self._current_map.map_name != map_name:
            self.logger.info(f"Current map is not '{map_name}'. Loading map...")
            await self._load_map(map_name)

        if with_rotation:
            endpoint = (
                f"/gs-robot/cmd/initialize?map_name={map_name}"
                f"&init_point_name={init_point_name}"
            )
        else:
            endpoint = (
                f"/gs-robot/cmd/initialize_directly?map_name={map_name}"
                f"&init_point_name={init_point_name}"
            )

        res = await self._get(endpoint)
        response = res.json()
        processed_response = self._success_or_raise(response)
        success = processed_response is not None
        if success:
            self._is_initialized = True
            # Attempt to update map info after successful initialization
            await self.update()  # Update state after initialization
        return success

    async def _initialize_at_custom_position(
        self, map_name: str, x: int, y: int, angle: float = 0.0
    ) -> bool:
        """Initialize the robot at a custom position (x, y, angle)

        Args:
            map_name (str): Name of the map
            x (int): X coordinate in grid units
            y (int): Y coordinate in grid units
            angle (float, optional): Orientation angle in degrees. Defaults to 0.0.

        Returns:
            bool: True if successful, False otherwise
        """
        if self._current_map is None or self._current_map.map_name != map_name:
            self.logger.info(f"Current map is not '{map_name}'. Loading map...")
            await self._load_map(map_name)

        res = await self._post(
            "/gs-robot/cmd/initialize_customized",
            json={"mapName": map_name, "point": {"angle": angle, "gridPosition": {"x": x, "y": y}}},
        )
        response = res.json()
        processed_response = self._success_or_raise(response)
        success = processed_response is not None
        if success:
            self._is_initialized = True
            # Attempt to update map info after successful initialization
            await self.update()  # Update state after initialization
        return success

    # ---------- Map Data APIs ----------#

    async def _get_task_queues(self, map_name: str) -> List[dict]:
        """Get the list of task queues for the specified map

        Args:
            map_name (str): Name of the map

        Returns:
            List[dict]: List of task queues
        """
        res = await self._get(f"/gs-robot/data/task_queues?map_name={map_name}")
        response = res.json()
        # Assuming success_or_raise is appropriate here and returns the data list on success
        # Adjust based on the actual API response structure for this endpoint
        processed_response = self._success_or_raise(response)
        # Example: if success_or_raise returns {'data': [...]} on success:
        return processed_response.get("data", [])

    async def _get_map_image(self, map_name: str) -> bytes:
        """Get the image of the specified map

        Args:
            map_name (str): Name of the map

        Returns:
            bytes: PNG image data of the map
        """
        # NOTE(b-Tomas): The map image is a large file and may take a while to download
        # Increase the timeout specifically for this request
        # Use a larger timeout than the default instance timeout if needed
        image_timeout = max(self.api_req_timeout, 30)  # e.g., 30 seconds
        self.logger.debug(f"Getting map image for {map_name} with timeout {image_timeout}s")
        res = await self._get(f"/gs-robot/data/map_png?map_name={map_name}", timeout=image_timeout)
        # No json() call for image content
        return res.content

    async def _get_waypoint_coordinates(self, map_name: str, path_name: str) -> dict:
        """Get the coordinates of waypoints for the specified path

        Args:
            map_name (str): Name of the map
            path_name (str): Name of the path

        Returns:
            dict: Waypoint coordinates data (full JSON response)
        """
        res = await self._get(
            f"/gs-robot/data/path_data_list?map_name={map_name}&path_name={path_name}"
        )
        # Return the raw JSON, let caller handle success/data extraction
        return res.json()

    # ---------- Cleaning Task APIs ----------#

    async def _start_cleaning_task(
        self,
        map_name: str,
        task_queue_name: str,
        loop: bool = False,
        loop_count: int = 0,
    ) -> bool:
        """Start a cleaning task

        Args:
            map_name (str): Name of the map the task queue is associated with.
            task_queue_name (str): Name of the task queue to run.
            loop (bool, optional): Whether to loop the task queue. Defaults to False.
            loop_count (int, optional): Number of loops. Defaults to 0.

        Returns:
            bool: True if successful, False otherwise
        """
        res = await self._post(
            "/gs-robot/cmd/start_task_queue",
            json={
                "name": task_queue_name,
                "loop": loop,
                "loop_count": loop_count,
                "map_name": map_name,
            },
        )
        return self._success_or_raise(res.json()) is not None

    async def _pause_task_queue(self) -> bool:
        """Pause the ongoing cleaning task

        Returns:
            bool: True if successful, False otherwise
        """
        res = await self._get("/gs-robot/cmd/pause_task_queue")
        return self._success_or_raise(res.json()) is not None

    async def _pause_task(self) -> bool:
        """Pause the ongoing cleaning task. Suitable for pausing a task on a currently loaded map
        or on an unloaded map (v3-6-6 and higher)

        Returns:
            bool: True if successful, False otherwise
        """
        if not await self._is_firmware_post_v3_6_6():
            self.logger.warning("_pause_task is only available on firmware v3-6-6 and higher")
            return False

        res = await self._get("/gs-robot/cmd/pause_task")
        return self._success_or_raise(res.json()) is not None

    async def _pause_multi_map_cleaning_task(self) -> bool:
        """Pause a cleaning task that spans multiple maps (v3-6-6 and higher)

        Returns:
            bool: True if successful, False otherwise
        """
        if not await self._is_firmware_post_v3_6_6():
            self.logger.warning(
                "_pause_multi_map_cleaning_task is only available on firmware v3-6-6 and higher"
            )
            return False

        res = await self._get("/gs-robot/cmd/pause_multi_task")
        return self._success_or_raise(res.json()) is not None

    async def _resume_task_queue(self) -> bool:
        """Resume the paused cleaning task.

        On v3-6-6 and higher it resumes a paused task on currently loaded map
        On pre v3-6-6 it resumes an ongoing task queue that has been paused

        Returns:
            bool: True if successful, False otherwise
        """
        res = await self._get("/gs-robot/cmd/resume_task_queue")
        return self._success_or_raise(res.json()) is not None

    async def _resume_task(self) -> bool:
        """Resume the paused cleaning task. Suitable for resuming a task on a currently loaded map
        or on an unloaded map (v3-6-6 and higher)

        Returns:
            bool: True if successful, False otherwise
        """
        if not await self._is_firmware_post_v3_6_6():
            self.logger.warning("_resume_task is only available on firmware v3-6-6 and higher")
            return False

        res = await self._get("/gs-robot/cmd/resume_task")
        # This endpoint seems to return success directly in response
        response = res.json()
        return response.get("successed", False)

    async def _resume_multi_map_cleaning_task(self) -> bool:
        """Resume a cleaning task that spans multiple maps (v3-6-6 and higher)

        Returns:
            bool: True if successful, False otherwise
        """
        if not await self._is_firmware_post_v3_6_6():
            self.logger.warning(
                "_resume_multi_map_cleaning_task is only available on firmware v3-6-6 and higher"
            )
            return False

        res = await self._get("/gs-robot/cmd/resume_multi_task")
        # This endpoint seems to return success directly in response
        response = res.json()
        return response.get("successed", False)

    async def _cancel_cleaning_task(self) -> bool:
        """Cancel the ongoing cleaning task

        Returns:
            bool: True if successful, False otherwise
        """
        res = await self._get("/gs-robot/cmd/stop_task_queue")
        # This endpoint seems to return success directly in response
        response = res.json()
        return response.get("successed", False)

    async def _is_cleaning_task_finished(self) -> bool:
        """Check if the cleaning task is finished

        Returns:
            bool: True if the task is finished, False if it's still running
        """
        res = await self._get("/gs-robot/cmd/is_task_queue_finished")
        response_json = self._success_or_raise(res.json())  # Ensure base call succeeded
        # Response has "data" field that contains "True" or "False" as a string
        data_str = response_json.get("data", "false")  # Default to false if data missing
        return str(data_str).lower() == "true"

    # ---------- Navigation Task APIs ----------#

    async def _navigate_to_named_waypoint(self, map_name: str, position_name: str) -> bool:
        """Implementation of send_to_named_waypoint that handles robot API calls

        Args:
            map_name (str): Name of the map
            position_name (str): Name of the waypoint

        Returns:
            bool: True if successful, False otherwise
        """

        if not map_name or not position_name:
            self.logger.error("Map name and position name are required for send_waypoint")
            return False

        if await self._is_firmware_post_v3_6_6():
            # For v3-6-6 and higher
            res = await self._get(
                f"/gs-robot/cmd/start_cross_task?map_name={map_name}&position_name={position_name}"
            )
        else:
            # For pre v3-6-6
            res = await self._post(
                "/gs-robot/cmd/start_task_queue",
                json={
                    "name": "",
                    "loop": False,
                    "loop_count": 0,
                    "map_name": map_name,
                    "tasks": [
                        {
                            "name": "NavigationTask",
                            "start_param": {"map_name": map_name, "position_name": position_name},
                        }
                    ],
                },
            )

        return self._success_or_raise(res.json()) is not None

    async def _navigate_to_coordinates(
        self, map_name: str, x: int, y: int, angle: float = 0.0
    ) -> bool:
        """Navigate the robot to specific coordinates

        Args:
            map_name (str): Name of the map
            x (int): X coordinate in grid units
            y (int): Y coordinate in grid units
            angle (float, optional): Orientation angle in degrees. Defaults to 0.0.

        Returns:
            bool: True if successful, False otherwise
        """
        if await self._is_firmware_post_v3_6_6():
            # For v3-6-6 and higher
            res = await self._post(
                "/gs-robot/cmd/quick/navigate?type=2",
                json={"destination": {"gridPosition": {"x": x, "y": y, "angle": angle}}},
            )
        else:
            # For pre v3-6-6
            res = await self._post(
                "/gs-robot/cmd/start_task_queue",
                json={
                    "name": "",
                    "loop": False,
                    "loop_count": 0,
                    "map_name": map_name,
                    "tasks": [
                        {
                            "name": "NavigationTask",
                            "start_param": {
                                "destination": {"angle": angle, "gridPosition": {"x": x, "y": y}}
                            },
                        }
                    ],
                },
            )

        return self._success_or_raise(res.json()) is not None

    async def _coordinate_to_grid_units(self, x: float, y: float) -> tuple[int, int]:
        """Convert coordinates to grid units of the current map

        Args:
            x (float): X coordinate in meters
            y (float): Y coordinate in meters

        Returns:
            tuple[int, int]: Grid units of the current map
        """
        map_data = await self._get_current_map_or_raise()
        resolution = map_data.resolution
        origin_x = map_data.origin_x
        origin_y = map_data.origin_y

        grid_x = round((x - origin_x) / resolution)
        grid_y = round((y - origin_y) / resolution)
        return grid_x, grid_y

    async def _grid_units_to_coordinate(self, x: int, y: int) -> tuple[float, float]:
        """Convert grid units to coordinates of the current map

        Args:
            x (int): X coordinate in grid units
            y (int): Y coordinate in grid units

        Returns:
            tuple[float, float]: Coordinates of the current map
        """
        map_data = await self._get_current_map_or_raise()
        resolution = map_data.resolution
        origin_x = map_data.origin_x
        origin_y = map_data.origin_y

        coordinate_x = x * resolution + origin_x
        coordinate_y = y * resolution + origin_y
        return coordinate_x, coordinate_y

    async def _pause_navigation_task(self) -> bool:
        """Pause the ongoing navigation task

        Returns:
            bool: True if successful, False otherwise
        """
        if await self._is_firmware_post_v3_6_6():
            res = await self._get("/gs-robot/cmd/pause_navigate")
        else:
            res = await self._get("/gs-robot/cmd/pause_task_queue")

        return self._success_or_raise(res.json()) is not None

    async def _resume_navigation_task(self) -> bool:
        """Resume the paused navigation task

        Returns:
            bool: True if successful, False otherwise
        """
        if await self._is_firmware_post_v3_6_6():
            res = await self._get("/gs-robot/cmd/resume_navigate")
        else:
            res = await self._get("/gs-robot/cmd/resume_task_queue")

        return self._success_or_raise(res.json()) is not None

    async def _cancel_navigation_task(self) -> bool:
        """Cancel the ongoing navigation task

        Returns:
            bool: True if successful, False otherwise
        """
        if await self._is_firmware_post_v3_6_6():
            res = await self._get("/gs-robot/cmd/cancel_navigate")
        else:
            res = await self._get("/gs-robot/cmd/stop_task_queue")

        return self._success_or_raise(res.json()) is not None

    async def _cancel_cross_map_navigation(self) -> bool:
        """Cancel an ongoing navigation task across maps (for pre v3-6-6)

        Returns:
            bool: True if successful, False otherwise
        """
        if await self._is_firmware_post_v3_6_6():
            return await self._cancel_navigation_task()
        else:
            res = await self._get("/gs-robot/cmd/stop_cross_task")
            return self._success_or_raise(res.json()) is not None

    async def _is_navigation_task_finished(self) -> bool:
        """Check if the navigation task is finished

        Returns:
            bool: True if the task is finished, False if it's still running
        """
        if await self._is_firmware_post_v3_6_6():
            endpoint = "/gs-robot/cmd/is_cross_task_finished"
        else:
            # Check if using cross_task API or task_queue
            # Assuming task_queue check is sufficient for pre-3.6.6 nav check
            endpoint = "/gs-robot/cmd/is_task_queue_finished"

        res = await self._get(endpoint)
        response_json = self._success_or_raise(res.json())  # Ensure base call succeeded
        # Response has "data" field that contains "True"/"False" or "true"/"false"
        data_str = response_json.get("data", "false")
        return str(data_str).lower() == "true"

    # ---------- Miscellaneous APIs ----------#

    async def _set_cleaning_mode(self, mode_name: str) -> bool:
        """Set the cleaning mode

        Args:
            mode_name (str): Name of the cleaning mode (e.g., "middle_cleaning", "heavy_cleaning")

        Returns:
            bool: True if successful, False otherwise
        """
        res = await self._get(f"/gs-robot/cmd/set_cleaning_mode?cleaning_mode={mode_name}")
        # This endpoint seems to return success directly in response
        response = res.json()
        return response.get("successed", False)

    async def _get_device_status(self) -> dict:
        """Fetch the device status

        Returns:
            dict: The device status data (full JSON response)
        """
        res = await self._get("/gs-robot/data/device_status")
        # Return the raw JSON, let caller handle success/data extraction
        return res.json()


class Vaccum40RobotAPI(GausiumCloudAPI):
    """Gausium Vaccum 40 robot API wrapper. Inherits from GausiumCloudAPI, overriding methods
    that are specific to the Vaccum 40 robot if needed.
    Currently, no overrides are needed, assuming Vaccum40 uses the same cloud API structure.
    """

    pass
