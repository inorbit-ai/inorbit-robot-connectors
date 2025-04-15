# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import logging
from abc import ABC
from typing import List

import httpx
from pydantic import HttpUrl

from inorbit_gausium_connector.src.robot.datatypes import MapData


class BaseRobotAPI(ABC):
    """Gausium robot API wrapper."""

    def __init__(
        self,
        base_url: HttpUrl,
        loglevel: str = "INFO",
        api_req_timeout: int = 10,
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


class GausiumCloudAPI(BaseRobotAPI):
    """Gausium Cloud API wrapper."""

    def __init__(
        self,
        base_url: HttpUrl,
        loglevel: str = "INFO",
        api_req_timeout: int = 10,
    ):
        """Initialize the Gausium Cloud API wrapper.

        Args:
            base_url (HttpUrl): Base URL for the Gausium Cloud API.
            loglevel (str, optional): Logging level. Defaults to "INFO".
            api_req_timeout (int, optional): Default timeout for API requests. Defaults to 10.
        """
        super().__init__(base_url, loglevel, api_req_timeout)
        self._is_initialized: bool = False
        self._last_pause_command: str | None = None

    @property
    def is_initialized(self) -> bool:
        """Check if the robot is initialized"""
        return self._is_initialized

    async def send_waypoint(
        self, x: float, y: float, orientation: float, map: MapData, firmware_version: str
    ) -> bool:
        """Send the robot to a waypoint (named waypoint)

        Args:
            x (float): X coordinate in grid units
            y (float): Y coordinate in grid units
            orientation (float): Orientation angle in degrees
            map (MapData): The target map

        Returns:
            bool: True if successful, False otherwise
        """
        map_name = map.map_name
        grid_x, grid_y = self._coordinate_to_grid_units(x, y)
        self.logger.debug(f"Converted {x}, {y} coordinates to grid units: {grid_x}, {grid_y}")
        return await self._navigate_to_coordinates(
            map_name, firmware_version, grid_x, grid_y, orientation
        )

    async def localize_at(self, x: float, y: float, orientation: float, map: MapData) -> bool:
        """Requests the robot to localize at the given coordinates within the same map"""
        map_name = map.map_name
        return await self._initialize_at_custom_position(map_name, x, y, orientation)

    async def pause(self, firmware_version: str) -> bool:
        """Requests the robot to pause whatever it is doing.
        It fetches the state of cleaning and navigation and the pauses whichever is running"""

        # In firmware version lower than v3-6-6, nav and cleaning pause commands are the same
        if not await self._is_firmware_post_v3_6_6(firmware_version):
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

    async def resume(self, firmware_version: str) -> bool:
        """Requests the robot to resume a previously paused task"""
        # In firmware version lower than v3-6-6, commands are the same
        if not await self._is_firmware_post_v3_6_6(firmware_version):
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

    async def start_task_queue(
        self,
        task_queue_name: str,
        map: MapData,
        loop: bool = False,
        loop_count: int = 0,
    ) -> bool:
        """Starts the cleaning task.

        Args:
            task_queue_name (str): Name of the task queue to start the cleaning task on
            map (MapData): The map to start the cleaning task on
            loop (bool, optional): Whether to loop the task. Defaults to False.
            loop_count (int, optional): Number of loops. Defaults to 0.

        Returns:
            bool: True if successful, False otherwise
        """
        return await self._start_cleaning_task(map.map_name, task_queue_name, loop, loop_count)

    async def pause_task_queue(self) -> bool:
        """Pauses the cleaning task"""
        return await self._pause_task_queue()

    async def resume_task_queue(self) -> bool:
        """Resumes the cleaning task"""
        return await self._resume_task_queue()

    async def cancel_task_queue(self) -> bool:
        """Cancels the cleaning task"""
        return await self._cancel_cleaning_task()

    async def send_to_named_waypoint(
        self, position_name: str, map: MapData, firmware_version: str
    ) -> bool:
        """Sends the robot to a named waypoint.

        Args:
            position_name (str): Name of the waypoint to send the robot to
            map (MapData): The target map
            firmware_version (str): The firmware version of the robot
        Returns:
            bool: True if successful, False otherwise
        """
        return await self._navigate_to_named_waypoint(map.map_name, position_name, firmware_version)

    async def pause_navigation_task(self) -> bool:
        """Pauses the navigation task"""
        return await self._pause_navigation_task()

    async def resume_navigation_task(self) -> bool:
        """Resumes the navigation task"""
        return await self._resume_navigation_task()

    async def cancel_navigation_task(self) -> bool:
        """Cancels the navigation task"""
        return await self._cancel_navigation_task()

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
        robot_info = res.json()
        # Update the firmware version
        software_version = robot_info.get("data", {}).get("softwareVersion")
        if software_version:
            # Extract version number (e.g., from "GS-ES50-OS1604-PRO800-OTA_V2-19-6" get "2-19-6")
            self._firmware_version = software_version.split("V")[-1]
        return robot_info

    async def _get_robot_status(self) -> dict:
        """Fetch the robot status

        Returns:
            dict: The robot status data
        """
        res = await self._get("/gs-robot/real_time_data/robot_status")
        return res.json()

    async def _is_firmware_post_v3_6_6(self, firmware_version: str) -> bool:
        """Check if the firmware version is v3-6-6 or higher

        Returns:
            bool: True if firmware is v3-6-6 or higher, False otherwise
        """
        # Extract version number parts
        version_parts = firmware_version.split("-")
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
        self,
        current_map: MapData,
        target_map: MapData,
        init_point_name: str,
        with_rotation: bool = True,
    ) -> bool:
        """Initialize the robot on the specified map at the specified point

        Args:
            current_map (MapData): The current map
            target_map (MapData): The target map
            init_point_name (str): Name of the initialization point
            with_rotation (bool, optional): Whether to perform rotation for
                initialization. Defaults to True.

        Returns:
            bool: True if successful, False otherwise
        """
        # Check if the map needs loading (using cached _current_map)
        if current_map is None or current_map.map_name != target_map.map_name:
            self.logger.info(f"Current map is not '{target_map.map_name}'. Loading map...")
            await self._load_map(target_map.map_name)

        if with_rotation:
            endpoint = (
                f"/gs-robot/cmd/initialize?map_name={target_map.map_name}"
                f"&init_point_name={init_point_name}"
            )
        else:
            endpoint = (
                f"/gs-robot/cmd/initialize_directly?map_name={target_map.map_name}"
                f"&init_point_name={init_point_name}"
            )

        res = await self._get(endpoint)
        response = res.json()
        processed_response = self._success_or_raise(response)
        success = processed_response is not None
        if success:
            self._is_initialized = True
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

    async def _pause_task(self, firmware_version: str) -> bool:
        """Pause the ongoing cleaning task. Suitable for pausing a task on a currently loaded map
        or on an unloaded map (v3-6-6 and higher)

        Returns:
            bool: True if successful, False otherwise
        """
        if not await self._is_firmware_post_v3_6_6(firmware_version):
            self.logger.warning("_pause_task is only available on firmware v3-6-6 and higher")
            return False

        res = await self._get("/gs-robot/cmd/pause_task")
        return self._success_or_raise(res.json()) is not None

    async def _pause_multi_map_cleaning_task(self, firmware_version: str) -> bool:
        """Pause a cleaning task that spans multiple maps (v3-6-6 and higher)

        Returns:
            bool: True if successful, False otherwise
        """
        if not await self._is_firmware_post_v3_6_6(firmware_version):
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

    async def _resume_task(self, firmware_version: str) -> bool:
        """Resume the paused cleaning task. Suitable for resuming a task on a currently loaded map
        or on an unloaded map (v3-6-6 and higher)

        Returns:
            bool: True if successful, False otherwise
        """
        if not await self._is_firmware_post_v3_6_6(firmware_version):
            self.logger.warning("_resume_task is only available on firmware v3-6-6 and higher")
            return False

        res = await self._get("/gs-robot/cmd/resume_task")
        # This endpoint seems to return success directly in response
        response = res.json()
        return response.get("successed", False)

    async def _resume_multi_map_cleaning_task(self, firmware_version: str) -> bool:
        """Resume a cleaning task that spans multiple maps (v3-6-6 and higher)

        Returns:
            bool: True if successful, False otherwise
        """
        if not await self._is_firmware_post_v3_6_6(firmware_version):
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

    async def _navigate_to_named_waypoint(
        self, map_name: str, position_name: str, firmware_version: str
    ) -> bool:
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

        if await self._is_firmware_post_v3_6_6(firmware_version):
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
        self, map_name: str, firmware_version: str, x: int, y: int, angle: float = 0.0
    ) -> bool:
        """Navigate the robot to specific coordinates

        Args:
            map_name (str): Name of the map
            x (int): X coordinate in grid units
            y (int): Y coordinate in grid units
            angle (float, optional): Orientation angle in degrees. Defaults to 0.0.
            firmware_version (str): The firmware version of the robot
        Returns:
            bool: True if successful, False otherwise
        """
        if await self._is_firmware_post_v3_6_6(firmware_version):
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

    async def _coordinate_to_grid_units(self, x: float, y: float, map: MapData) -> tuple[int, int]:
        """Convert coordinates to grid units of the current map

        Args:
            x (float): X coordinate in meters
            y (float): Y coordinate in meters

        Returns:
            tuple[int, int]: Grid units of the current map
        """
        resolution = map.resolution
        origin_x = map.origin_x
        origin_y = map.origin_y

        grid_x = round((x - origin_x) / resolution)
        grid_y = round((y - origin_y) / resolution)
        return grid_x, grid_y

    async def _pause_navigation_task(self, firmware_version: str) -> bool:
        """Pause the ongoing navigation task

        Returns:
            bool: True if successful, False otherwise
        """
        if await self._is_firmware_post_v3_6_6(firmware_version):
            res = await self._get("/gs-robot/cmd/pause_navigate")
        else:
            res = await self._get("/gs-robot/cmd/pause_task_queue")

        return self._success_or_raise(res.json()) is not None

    async def _resume_navigation_task(self, firmware_version: str) -> bool:
        """Resume the paused navigation task

        Returns:
            bool: True if successful, False otherwise
        """
        if await self._is_firmware_post_v3_6_6(firmware_version):
            res = await self._get("/gs-robot/cmd/resume_navigate")
        else:
            res = await self._get("/gs-robot/cmd/resume_task_queue")

        return self._success_or_raise(res.json()) is not None

    async def _cancel_navigation_task(self, firmware_version: str) -> bool:
        """Cancel the ongoing navigation task

        Returns:
            bool: True if successful, False otherwise
        """
        if await self._is_firmware_post_v3_6_6(firmware_version):
            res = await self._get("/gs-robot/cmd/cancel_navigate")
        else:
            res = await self._get("/gs-robot/cmd/stop_task_queue")

        return self._success_or_raise(res.json()) is not None

    async def _cancel_cross_map_navigation(self, firmware_version: str) -> bool:
        """Cancel an ongoing navigation task across maps (for pre v3-6-6)

        Returns:
            bool: True if successful, False otherwise
        """
        if await self._is_firmware_post_v3_6_6(firmware_version):
            return await self._cancel_navigation_task(firmware_version)
        else:
            res = await self._get("/gs-robot/cmd/stop_cross_task")
            return self._success_or_raise(res.json()) is not None

    async def _is_navigation_task_finished(self, firmware_version: str) -> bool:
        """Check if the navigation task is finished

        Returns:
            bool: True if the task is finished, False if it's still running
        """
        if await self._is_firmware_post_v3_6_6(firmware_version):
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
