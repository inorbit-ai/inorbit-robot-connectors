# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import logging
from abc import ABC, abstractmethod
from math import radians
from typing import List, Optional, override
from urllib.parse import urljoin

from pydantic import BaseModel, HttpUrl
from requests import Response, Session
from requests.exceptions import HTTPError


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


class GausiumRobotAPI(ABC):
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
        """
        self.logger = logging.getLogger(name=self.__class__.__name__)
        self.logger.setLevel(loglevel)
        self.base_url = str(base_url)
        # Indicates whether the last call to the API was successful
        # Useful for estimating the state of the Connector <> APIs link
        self._last_call_successful: bool | None = None
        self.api_session = Session()
        self.api_req_timeout = api_req_timeout

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
        except HTTPError as e:
            self.logger.error(f"Error making request: {e}\nArguments: {request_args}")
            raise e

    def _get(
        self, url: str, session: Session = None, timeout: int | None = None, **kwargs
    ) -> Response:
        """Perform a GET request."""
        self.logger.debug(f"GETting {url}: {kwargs}")
        session = session or self.api_session
        res = session.get(url, timeout=timeout or self.api_req_timeout, **kwargs)
        self._handle_status(res, kwargs)
        return res

    def _post(
        self, url: str, session: Session = None, timeout: int | None = None, **kwargs
    ) -> Response:
        """Perform a POST request."""
        self.logger.debug(f"POSTing {url}: {kwargs}")
        session = session or self.api_session
        res = session.post(url, timeout=timeout or self.api_req_timeout, **kwargs)
        self.logger.debug(f"Response: {res}")
        self._handle_status(res, kwargs)
        return res

    def _delete(
        self, url: str, session: Session = None, timeout: int | None = None, **kwargs
    ) -> Response:
        """Perform a DELETE request."""
        self.logger.debug(f"DELETEing {url}: {kwargs}")
        session = session or self.api_session
        res = session.delete(url, timeout=timeout or self.api_req_timeout, **kwargs)
        self.logger.debug(f"Response: {res}")
        self._handle_status(res, kwargs)
        return res

    def _put(
        self, url: str, session: Session = None, timeout: int | None = None, **kwargs
    ) -> Response:
        """Perform a PUT request."""
        self.logger.debug(f"PUTing {url}: {kwargs}")
        session = session or self.api_session
        res = session.put(url, timeout=timeout or self.api_req_timeout, **kwargs)
        self.logger.debug(f"Response: {res}")
        self._handle_status(res, kwargs)
        return res

    def _build_url(self, endpoint: str) -> str:
        """Create the full URL for the API endpoint."""
        return urljoin(self.base_url, endpoint)

    @abstractmethod
    def update(self) -> None:
        """Refresh the robot data"""
        pass

    @property
    @abstractmethod
    def pose(self) -> dict:
        """Get the pose of the robot"""
        pass

    @property
    @abstractmethod
    def odometry(self) -> dict:
        """Get the odometry of the robot"""
        pass

    @property
    @abstractmethod
    def key_values(self) -> dict:
        """Get the key values of the robot"""
        pass

    @property
    @abstractmethod
    def current_map(self) -> MapData:
        """Get the current map"""
        pass

    @abstractmethod
    def send_waypoint(self, x: float, y: float, orientation: float) -> bool:
        """Receives a pose and sends a request to command the robot to navigate to the waypoint"""
        pass

    @abstractmethod
    def localize_at(self, x: float, y: float, orientation: float) -> bool:
        """Requests the robot to localize at the given coordinates within the same map"""
        pass

    @abstractmethod
    def pause(self) -> bool:
        """Requests the robot to pause whatever it is doing"""
        pass

    @abstractmethod
    def resume(self) -> bool:
        """Requests the robot to resume whatever it was doing"""
        pass

    @abstractmethod
    def start_cleaning_task(self, **kwargs) -> bool:
        """Starts the cleaning task"""
        pass

    @abstractmethod
    def pause_cleaning_task(self) -> bool:
        """Pauses the cleaning task"""
        pass

    @abstractmethod
    def resume_cleaning_task(self) -> bool:
        """Resumes the cleaning task"""
        pass

    @abstractmethod
    def cancel_cleaning_task(self) -> bool:
        """Cancels the cleaning task"""
        pass

    @abstractmethod
    def send_to_named_waypoint(self, **kwargs) -> bool:
        """Sends the robot to a named waypoint"""
        pass

    @abstractmethod
    def pause_navigation_task(self) -> bool:
        """Pauses the navigation task"""
        pass

    @abstractmethod
    def resume_navigation_task(self) -> bool:
        """Resumes the navigation task"""
        pass

    @abstractmethod
    def cancel_navigation_task(self) -> bool:
        """Cancels the navigation task"""
        pass


class GausiumCloudAPI(GausiumRobotAPI):
    """Gausium cloud API wrapper."""

    def __init__(
        self,
        base_url: HttpUrl,
        loglevel: str = "INFO",
        allowed_model_types: List[str] = [],
    ):
        """Initialize the Gausium Cloud API wrapper.

        Args:
            base_url (HttpUrl): Base URL for the Gausium Cloud API.
            loglevel (str, optional): Logging level. Defaults to "INFO".
            allowed_model_types (List[str], optional): List of robot model types
                supported by this API wrapper. Defaults to an empty list.
                If empty, the model type will not be validated.
        """
        super().__init__(base_url, loglevel)
        self._pose: dict | None = None
        self._odometry: dict | None = None
        self._key_values: dict | None = None
        self._firmware_version: str | None = None
        self._device_status: dict | None = None
        self._current_map: MapData | None = None
        self._is_initialized: bool = False
        self._allowed_model_types: List[str] = allowed_model_types
        self._last_pause_command: str | None = None

    @override
    def update(self) -> None:
        """Update the robot's status data"""

        # Fetch fresh data from the robot
        robot_info = self._get_robot_info().get("data", {})
        device_data = self._get_device_status().get("data", {})
        position_data = self._fetch_position()
        robot_status_data = self._get_robot_status().get("data", {})
        # Validate the model type of the robot and the API wrapper in use match
        model_type = robot_info.get("modelType")
        if self._allowed_model_types and model_type not in self._allowed_model_types:
            raise ModelTypeMismatchError(model_type, self._allowed_model_types)

        # Update the firmware version
        self._firmware_version = robot_info.get("softwareVersion")

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
        self._pose = {
            "x": position_data.get("worldPosition", {}).get("position", {}).get("x"),
            "y": position_data.get("worldPosition", {}).get("position", {}).get("y"),
            "yaw": radians(position_data.get("angle")),
            "frame_id": self._current_map.map_name if self._current_map else "map",
        }
        self._odometry = {}  # TODO: Get the odometry data

    @property
    @override
    def pose(self) -> dict:
        """Get the pose of the robot"""
        if self._pose is None:
            self.update()
        return self._pose

    @property
    @override
    def odometry(self) -> dict:
        """Get the odometry of the robot"""
        if self._odometry is None:
            self.update()
        return self._odometry

    @property
    @override
    def key_values(self) -> dict:
        """Get the key values of the robot"""
        if self._key_values is None:
            self.update()
        return self._key_values

    @property
    def firmware_version(self) -> str:
        """Get the firmware version of the robot"""
        if self._firmware_version is None:
            self.update()
        return self._firmware_version

    @property
    def device_status(self) -> dict:
        """Get the full device status"""
        if self._device_status is None:
            self.update()
        return self._device_status

    @property
    def is_initialized(self) -> bool:
        """Check if the robot is initialized"""
        if self._is_initialized is None:
            self.update()
        return self._is_initialized

    @property
    def current_map(self) -> MapData:
        """Get the current map.
        If the map is not loaded, the update() method will load it.
        If the map image isn't loaded, it will be lazily fetched from the robot."""
        if self._current_map is None:
            self.update()
        if self._current_map and self._current_map.map_image is None:
            self._current_map.map_image = self._get_map_image(self._current_map.map_name)
        return self._current_map

    @override
    def send_waypoint(self, x: float, y: float, orientation: float) -> bool:
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
        return self._success_or_raise(
            self._navigate_to_coordinates(map_name, grid_x, grid_y, orientation)
        )

    @override
    def localize_at(self, x: float, y: float, orientation: float) -> bool:
        """Requests the robot to localize at the given coordinates within the same map"""
        map_name = self._current_map.map_name if self._current_map else None
        if not map_name:
            raise Exception("No current map found to localize at")
        return self._initialize_at_custom_position(map_name, x, y, orientation)

    @override
    def pause(self) -> bool:
        """Requests the robot to pause whatever it is doing.
        It fetches the state of cleaning and navigation and the pauses whichever is running"""
        # In firmware version lower than v3-6-6, navigation and cleaning pause commands are the same
        if not self._is_firmware_post_v3_6_6():
            return self._pause_task_queue()

        # In firmware version v3-6-6 and higher, navigation and cleaning pause commands are
        # different
        if self._is_cleaning_task_finished():
            self._last_pause_command = "cleaning"
            return self._pause_cleaning_task()
        else:
            self._last_pause_command = "navigation"
            return self._pause_navigation_task()

    @override
    def resume(self) -> bool:
        """Requests the robot to resume a previously paused task"""
        # In firmware version lower than v3-6-6, navigation and cleaning resume commands are the
        # same
        if not self._is_firmware_post_v3_6_6():
            return self._resume_task_queue()

        # In firmware version v3-6-6 and higher, navigation and cleaning resume commands are
        # different.
        # Get the previously paused command to know which one to resume
        if self._last_pause_command == "cleaning":
            self._last_pause_command = None
            return self._resume_cleaning_task()
        if self._last_pause_command == "navigation":
            self._last_pause_command = None
            return self._resume_navigation_task()
        else:
            raise Exception("No previously paused command found")

    @override
    def start_cleaning_task(
        self,
        path_name: str,
        task_name: str = "",
        map_name: str | None = None,
        loop: bool = False,
        loop_count: int = 0,
    ) -> bool:
        """Starts the cleaning task.

        Args:
            path_name (str): Name of the path to start the cleaning task on
            task_name (str, optional): Name of the task. Defaults to "".
            map_name (str | None, optional): Name of the map to start the cleaning task on.
                Defaults to the current map.
            loop (bool, optional): Whether to loop the task. Defaults to False.
            loop_count (int, optional): Number of loops. Defaults to 0.

        Returns:
            bool: True if successful, False otherwise
        """
        map_name = map_name if map_name else self._get_current_map_or_raise().map_name
        return self._start_cleaning_task(map_name, path_name, task_name, loop, loop_count)

    @override
    def pause_cleaning_task(self) -> bool:
        """Pauses the cleaning task"""
        return self._pause_task_queue()

    @override
    def resume_cleaning_task(self) -> bool:
        """Resumes the cleaning task"""
        return self._resume_task_queue()

    @override
    def cancel_cleaning_task(self) -> bool:
        """Cancels the cleaning task"""
        return self._cancel_task_queue()

    @override
    def send_to_named_waypoint(self, position_name: str, map_name: str | None = None) -> bool:
        """Sends the robot to a named waypoint.

        Args:
            position_name (str): Name of the waypoint to send the robot to
            map_name (str | None, optional): Name of the map to send the robot to.
                Defaults to the current map.

        Returns:
            bool: True if successful, False otherwise
        """
        map_name = map_name if map_name else self._get_current_map_or_raise().map_name
        return self._navigate_to_named_waypoint(map_name, position_name)

    @override
    def pause_navigation_task(self) -> bool:
        """Pauses the navigation task"""
        return self._pause_navigation_task()

    @override
    def resume_navigation_task(self) -> bool:
        """Resumes the navigation task"""
        return self._resume_navigation_task()

    @override
    def cancel_navigation_task(self) -> bool:
        """Cancels the navigation task"""
        return self._cancel_navigation_task()

    def _get_current_map_or_raise(self) -> MapData:
        """Get the current map or raise an exception if it's not set"""
        if self._current_map is None:
            raise Exception("No current map found")
        return self._current_map

    def _success_or_raise(self, response: dict) -> bool:
        """Check if a Gaussian Cloud API call was successful or raise an exception that shows the
        error message.

        Args:
            response (dict): The response from the API call. Note it should be a successful
                response (200 code).

        Returns:
            bool: True if the API call was successful, raises an exception otherwise
        """
        if response.get("successed", False):
            return response
        else:
            error_code = response.get("errorCode")
            error_msg = response.get("msg")
            data = response.get("data")
            human_readable_err = "API call failed"
            if error_code:
                human_readable_err += f" with error code {error_code}"
            if error_msg:
                human_readable_err += f": {error_msg}"
            if data:
                human_readable_err += f", data: {data}"
            raise Exception(human_readable_err)

    # ---------- General APIs ----------#

    def _get_robot_info(self) -> dict:
        """Fetch the robot info to get firmware version and other details

        Returns:
            dict: The robot info response
        """
        res = self._get(self._build_url("/gs-robot/info"))
        return res.json()

    def _get_robot_status(self) -> dict:
        """Fetch the robot status

        Returns:
            dict: The robot status data
        """
        url = "/gs-robot/real_time_data/robot_status"
        res = self._get(self._build_url(url))
        return res.json()

    def _get_firmware_version(self) -> str:
        """Get the firmware version of the robot

        Returns:
            str: Firmware version string
        """
        info = self._success_or_raise(self._get_robot_info())
        version = info.get("data", {}).get("softwareVersion", "")
        return version

    def _is_firmware_post_v3_6_6(self) -> bool:
        """Check if the firmware version is v3-6-6 or higher

        Returns:
            bool: True if firmware is v3-6-6 or higher, False otherwise
        """
        version = self._get_firmware_version()
        if not version:
            return False

        # Extract version number (e.g., from "GS-ES50-OS1604-PRO800-OTA_V2-19-6" get "2-19-6")
        if "V" in version:
            version_parts = version.split("V")[-1].split("-")
            if len(version_parts) >= 3:
                major = int(version_parts[0])
                minor = int(version_parts[1])
                patch = int(version_parts[2])

                # Compare with v3-6-6
                if major > 3:
                    return True
                elif major == 3 and minor >= 6 and patch >= 6:
                    return True
        return False

    # ---------- Localization APIs ----------#

    def _fetch_position(self) -> dict:
        """Fetch the current position of the robot

        Returns:
            dict: The position data
        """
        res = self._get(self._build_url("/gs-robot/real_time_data/position"))
        return res.json()

    def _load_map(self, map_name: str) -> bool:
        """Load a specified map

        Args:
            map_name (str): Name of the map to load

        Returns:
            bool: True if successful, False otherwise
        """
        url = f"/gs-robot/cmd/load_map?map_name={map_name}"
        res = self._get(self._build_url(url))
        response = res.json()
        success = response.get("successed", False)
        if success:
            self._is_initialized = False  # Map changed, robot needs to be initialized again
        return response

    def _initialize_at_point(
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
        if self._current_map and self._current_map.map_name != map_name:
            self._load_map(map_name)

        if with_rotation:
            url = (
                f"/gs-robot/cmd/initialize?map_name={map_name}"
                f"&init_point_name={init_point_name}"
            )
        else:
            url = (
                f"/gs-robot/cmd/initialize_directly?map_name={map_name}"
                f"&init_point_name={init_point_name}"
            )

        res = self._get(self._build_url(url))
        response = res.json()
        success = response.get("successed", False)
        if success:
            self._is_initialized = True
        return self._success_or_raise(response)

    def _initialize_at_custom_position(
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
        if self._current_map and self._current_map.map_name != map_name:
            self._load_map(map_name)

        url = "/gs-robot/cmd/initialize_customized"
        payload = {"mapName": map_name, "point": {"angle": angle, "gridPosition": {"x": x, "y": y}}}

        res = self._post(self._build_url(url), json=payload)
        response = res.json()
        success = response.get("successed", False)
        if success:
            self._is_initialized = True
        return self._success_or_raise(response)

    # ---------- Map Data APIs ----------#

    def _get_task_queues(self, map_name: str) -> List[dict]:
        """Get the list of task queues for the specified map

        Args:
            map_name (str): Name of the map

        Returns:
            List[dict]: List of task queues
        """
        url = f"/gs-robot/data/task_queues?map_name={map_name}"
        res = self._get(self._build_url(url))
        response = res.json()
        return self._success_or_raise(response)

    def _get_map_image(self, map_name: str) -> bytes:
        """Get the image of the specified map

        Args:
            map_name (str): Name of the map

        Returns:
            bytes: PNG image data of the map
        """
        url = f"/gs-robot/data/map_png?map_name={map_name}"
        # NOTE(b-Tomas): The map image is a large file and may take a while to download
        # so we increase the timeout to 20 seconds
        res = self._get(self._build_url(url), timeout=max(self.api_req_timeout, 20))
        return res.content

    def _get_waypoint_coordinates(self, map_name: str, path_name: str) -> dict:
        """Get the coordinates of waypoints for the specified path

        Args:
            map_name (str): Name of the map
            path_name (str): Name of the path

        Returns:
            dict: Waypoint coordinates data
        """
        url = f"/gs-robot/data/path_data_list?map_name={map_name}&path_name={path_name}"
        res = self._get(self._build_url(url))
        return res.json()

    # ---------- Cleaning Task APIs ----------#

    def _start_cleaning_task(
        self,
        map_name: str,
        path_name: str,
        task_name: str = "",
        loop: bool = False,
        loop_count: int = 0,
    ) -> bool:
        """Start a cleaning task

        Args:
            map_name (str): Name of the map
            path_name (str): Name of the path
            task_name (str, optional): Name of the task. Defaults to "".
            loop (bool, optional): Whether to loop the task. Defaults to False.
            loop_count (int, optional): Number of loops. Defaults to 0.

        Returns:
            bool: True if successful, False otherwise
        """
        url = "/gs-robot/cmd/start_task_queue"
        payload = {
            "name": task_name,
            "loop": loop,
            "loop_count": loop_count,
            "map_name": map_name,
            "tasks": [
                {
                    "name": "PlayPathTask",
                    "start_param": {"map_name": map_name, "path_name": path_name},
                }
            ],
        }

        res = self._post(self._build_url(url), json=payload)
        response = res.json()
        return response.get("successed", False)

    def _pause_task_queue(self) -> bool:
        """Pause the ongoing cleaning task

        Returns:
            bool: True if successful, False otherwise
        """
        url = "/gs-robot/cmd/pause_task_queue"
        res = self._get(self._build_url(url))
        response = res.json()
        return response.get("successed", False)

    def _pause_task(self) -> bool:
        """Pause the ongoing cleaning task. Suitable for pausing a task on a currently loaded map
        or on an unloaded map (v3-6-6 and higher)

        Returns:
            bool: True if successful, False otherwise
        """
        if not self._is_firmware_post_v3_6_6():
            self.logger.warning("pause_task is only available on firmware v3-6-6 and higher")
            return False

        url = "/gs-robot/cmd/pause_task"
        res = self._get(self._build_url(url))
        response = res.json()
        return response.get("successed", False)

    def _pause_multi_map_cleaning_task(self) -> bool:
        """Pause a cleaning task that spans multiple maps (v3-6-6 and higher)

        Returns:
            bool: True if successful, False otherwise
        """
        if not self._is_firmware_post_v3_6_6():
            self.logger.warning(
                "pause_multi_map_cleaning_task is only available on firmware v3-6-6 and higher"
            )
            return False

        url = "/gs-robot/cmd/pause_multi_task"
        res = self._get(self._build_url(url))
        response = res.json()
        return response.get("successed", False)

    def _resume_task_queue(self) -> bool:
        """Resume the paused cleaning task.

        On v3-6-6 and higher it resumes a paused task on currently loaded map
        On pre v3-6-6 it resumes an ongoing task queue that has been paused

        Returns:
            bool: True if successful, False otherwise
        """
        url = "/gs-robot/cmd/resume_task_queue"

        res = self._get(self._build_url(url))
        response = res.json()
        return response.get("successed", False)

    def _resume_task(self) -> bool:
        """Resume the paused cleaning task. Suitable for resuming a task on a currently loaded map
        or on an unloaded map (v3-6-6 and higher)

        Returns:
            bool: True if successful, False otherwise
        """
        if not self._is_firmware_post_v3_6_6():
            self.logger.warning("resume_task is only available on firmware v3-6-6 and higher")
            return False

        url = "/gs-robot/cmd/resume_task"
        res = self._get(self._build_url(url))
        response = res.json()
        return response.get("successed", False)

    def _resume_multi_map_cleaning_task(self) -> bool:
        """Resume a cleaning task that spans multiple maps (v3-6-6 and higher)

        Returns:
            bool: True if successful, False otherwise
        """
        if not self._is_firmware_post_v3_6_6():
            self.logger.warning(
                "resume_multi_map_cleaning_task is only available on firmware v3-6-6 and higher"
            )
            return False

        url = "/gs-robot/cmd/resume_multi_task"
        res = self._get(self._build_url(url))
        response = res.json()
        return response.get("successed", False)

    def _cancel_cleaning_task(self) -> bool:
        """Cancel the ongoing cleaning task

        Returns:
            bool: True if successful, False otherwise
        """
        url = "/gs-robot/cmd/stop_task_queue"
        res = self._get(self._build_url(url))
        response = res.json()
        return response.get("successed", False)

    def _is_cleaning_task_finished(self) -> bool:
        """Check if the cleaning task is finished

        Returns:
            bool: True if the task is finished, False if it's still running
        """
        url = "/gs-robot/cmd/is_task_queue_finished"
        res = self._get(self._build_url(url))
        response = res.json()

        if response.get("successed", False):
            # Response has "data" field that contains "True" or "False" as a string
            return response.get("data") == "True"
        return False

    # ---------- Navigation Task APIs ----------#

    def _navigate_to_named_waypoint(self, map_name: str, position_name: str) -> bool:
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

        if self._is_firmware_post_v3_6_6():
            # For v3-6-6 and higher
            url = (
                f"/gs-robot/cmd/start_cross_task?map_name={map_name}&position_name={position_name}"
            )
            res = self._get(self._build_url(url))
        else:
            # For pre v3-6-6
            url = "/gs-robot/cmd/start_task_queue"
            payload = {
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
            }
            res = self._post(self._build_url(url), json=payload)

        response = res.json()
        return response.get("successed", False)

    def _navigate_to_coordinates(self, map_name: str, x: int, y: int, angle: float = 0.0) -> bool:
        """Navigate the robot to specific coordinates

        Args:
            map_name (str): Name of the map
            x (int): X coordinate in grid units
            y (int): Y coordinate in grid units
            angle (float, optional): Orientation angle in degrees. Defaults to 0.0.

        Returns:
            bool: True if successful, False otherwise
        """
        if self._is_firmware_post_v3_6_6():
            # For v3-6-6 and higher
            url = "/gs-robot/cmd/quick/navigate?type=2"
            payload = {"destination": {"gridPosition": {"x": x, "y": y, "angle": angle}}}
        else:
            # For pre v3-6-6
            url = "/gs-robot/cmd/start_task_queue"
            payload = {
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
            }

        res = self._post(self._build_url(url), json=payload)
        response = res.json()
        return response.get("successed", False)

    def _coordinate_to_grid_units(self, x: float, y: float) -> tuple[int, int]:
        """Convert coordinates to grid units of the current map

        Args:
            x (float): X coordinate in meters
            y (float): Y coordinate in meters

        Returns:
            tuple[int, int]: Grid units of the current map
        """
        map_data = self._get_current_map_or_raise()
        resolution = map_data.resolution
        origin_x = map_data.origin_x
        origin_y = map_data.origin_y

        grid_x = int((x - origin_x) / resolution)
        grid_y = int((y - origin_y) / resolution)
        return grid_x, grid_y

    def _pause_navigation_task(self) -> bool:
        """Pause the ongoing navigation task

        Returns:
            bool: True if successful, False otherwise
        """
        if self._is_firmware_post_v3_6_6():
            url = "/gs-robot/cmd/pause_navigate"
        else:
            url = "/gs-robot/cmd/pause_task_queue"

        res = self._get(self._build_url(url))
        response = res.json()
        return response.get("successed", False)

    def _resume_navigation_task(self) -> bool:
        """Resume the paused navigation task

        Returns:
            bool: True if successful, False otherwise
        """
        if self._is_firmware_post_v3_6_6():
            url = "/gs-robot/cmd/resume_navigate"
        else:
            url = "/gs-robot/cmd/resume_task_queue"

        res = self._get(self._build_url(url))
        response = res.json()
        return response.get("successed", False)

    def _cancel_navigation_task(self) -> bool:
        """Cancel the ongoing navigation task

        Returns:
            bool: True if successful, False otherwise
        """
        if self._is_firmware_post_v3_6_6():
            url = "/gs-robot/cmd/cancel_navigate"
        else:
            url = "/gs-robot/cmd/stop_task_queue"

        res = self._get(self._build_url(url))
        response = res.json()
        return response.get("successed", False)

    def _cancel_cross_map_navigation(self) -> bool:
        """Cancel an ongoing navigation task across maps (for pre v3-6-6)

        Returns:
            bool: True if successful, False otherwise
        """
        if self._is_firmware_post_v3_6_6():
            return self._cancel_navigation_task()
        else:
            url = "/gs-robot/cmd/stop_cross_task"
            res = self._get(self._build_url(url))
            response = res.json()
            return response.get("successed", False)

    def _is_navigation_task_finished(self) -> bool:
        """Check if the navigation task is finished

        Returns:
            bool: True if the task is finished, False if it's still running
        """
        if self._is_firmware_post_v3_6_6():
            url = "/gs-robot/cmd/is_cross_task_finished"
        else:
            # Check if using cross_task API or task_queue
            url = "/gs-robot/cmd/is_task_queue_finished"

        res = self._get(self._build_url(url))
        response = res.json()

        if response.get("successed", False):
            # Response has "data" field that contains "True"/"False" or "true"/"false"
            data = response.get("data", "").lower()
            return data == "true" or data == "True"
        return False

    # ---------- Miscellaneous APIs ----------#

    def _set_cleaning_mode(self, mode_name: str) -> bool:
        """Set the cleaning mode

        Args:
            mode_name (str): Name of the cleaning mode (e.g., "middle_cleaning", "heavy_cleaning")

        Returns:
            bool: True if successful, False otherwise
        """
        url = f"/gs-robot/cmd/set_cleaning_mode?cleaning_mode={mode_name}"
        res = self._get(self._build_url(url))
        response = res.json()
        return response.get("successed", False)

    def _get_device_status(self) -> dict:
        """Fetch the device status

        Returns:
            dict: The device status data
        """
        url = "/gs-robot/data/device_status"
        res = self._get(self._build_url(url))
        return res.json()


class Vaccum40RobotAPI(GausiumCloudAPI):
    """Gausium Vaccum 40 robot API wrapper. Inherits from GausiumCloudAPI, overriding all methods
    that are specific to the Vaccum 40 robot."""

    pass
