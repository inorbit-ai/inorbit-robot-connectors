# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import logging
from abc import ABC, abstractmethod
from math import radians
from typing import List
from urllib.parse import urljoin
from pydantic import HttpUrl
from requests import Response
from requests import Session
from requests.exceptions import HTTPError


class GausiumRobotAPI(ABC):
    """Gausium robot API wrapper."""

    def __init__(
        self,
        base_url: HttpUrl,
        loglevel: str = "INFO",
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

    def _get(self, url: str, session: Session = None, **kwargs) -> Response:
        """Perform a GET request."""
        self.logger.debug(f"GETting {url}: {kwargs}")
        session = session or self.api_session
        res = session.get(url, **kwargs)
        self._handle_status(res, kwargs)
        return res

    def _post(self, url: str, session: Session = None, **kwargs) -> Response:
        """Perform a POST request."""
        self.logger.debug(f"POSTing {url}: {kwargs}")
        session = session or self.api_session
        res = session.post(url, **kwargs)
        self.logger.debug(f"Response: {res}")
        self._handle_status(res, kwargs)
        return res

    def _delete(self, url: str, session: Session = None, **kwargs) -> Response:
        """Perform a DELETE request."""
        self.logger.debug(f"DELETEing {url}: {kwargs}")
        session = session or self.api_session
        res = session.delete(url, **kwargs)
        self.logger.debug(f"Response: {res}")
        self._handle_status(res, kwargs)
        return res

    def _put(self, url: str, session: Session = None, **kwargs) -> Response:
        """Perform a PUT request."""
        self.logger.debug(f"PUTing {url}: {kwargs}")
        session = session or self.api_session
        res = session.put(url, **kwargs)
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

    @abstractmethod
    def send_waypoint(self, pose: dict) -> bool:
        """Example: Receives a pose and sends a request to command the robot to
        navigate to the waypoint"""
        pass


class GausiumCloudAPI(GausiumRobotAPI):
    """Gausium cloud API wrapper."""

    def __init__(self, base_url: HttpUrl, loglevel: str = "INFO"):
        super().__init__(base_url, loglevel)
        self._pose: dict | None = None
        self._odometry: dict | None = None
        self._key_values: dict | None = None
        self._firmware_version: str | None = None
        self._device_status: dict | None = None
        self._map_name: str | None = None
        self._is_initialized: bool = False

    def update(self) -> None:
        """Update the robot's status data"""
        try:
            # Update pose
            position_data = self._fetch_position()
            self._pose = {
                "x": position_data.get("worldPosition", {}).get("position", {}).get("x"),
                "y": position_data.get("worldPosition", {}).get("position", {}).get("y"),
                # Extract the yaw from the orientation quaternion
                "yaw": radians(
                    position_data.get("worldPosition", {}).get("orientation", {}).get("z")
                ),
                # TODO: Get the frameId
                "frame_id": " ",
            }

            # TODO: Get the odometry data
            self._odometry = {}

            # Update firmware version
            robot_info = self._get_robot_info().get("data", {})
            self._firmware_version = robot_info.get("softwareVersion")

            # Update device status and key values
            device_data = self._get_device_status()
            self._device_status = device_data.get("data", {})

            # Extract key values
            self._key_values = {
                **self._device_status,
                **robot_info,
            }

        except Exception as e:
            self.logger.error(f"Error updating robot status: {e}")

    @property
    def pose(self) -> dict:
        """Get the pose of the robot"""
        if self._pose is None:
            self.update()
        return self._pose

    @property
    def odometry(self) -> dict:
        """Get the odometry of the robot"""
        if self._odometry is None:
            self.update()
        return self._odometry

    @property
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

    # ---------- General APIs ----------#

    def _get_robot_info(self) -> dict:
        """Fetch the robot info to get firmware version and other details

        Returns:
            dict: The robot info response
        """
        res = self._get(self._build_url("/gs-robot/info"))
        return res.json()

    def _get_firmware_version(self) -> str:
        """Get the firmware version of the robot

        Returns:
            str: Firmware version string
        """
        info = self._get_robot_info()
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
            self._map_name = map_name
            self._is_initialized = False  # Map changed, robot needs to be initialized again
        return success

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
        if self._map_name != map_name:
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
        return success

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
        if self._map_name != map_name:
            self._load_map(map_name)

        url = "/gs-robot/cmd/initialize_customized"
        payload = {"mapName": map_name, "point": {"angle": angle, "gridPosition": {"x": x, "y": y}}}

        res = self._post(self._build_url(url), json=payload)
        response = res.json()
        success = response.get("successed", False)
        if success:
            self._is_initialized = True
        return success

    def _get_current_position(self) -> dict:
        """Get the current position of the robot

        Returns:
            dict: The current position data
        """
        return self._fetch_position()

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

        if response.get("successed", False):
            return response.get("data", [])
        else:
            self.logger.error(f"Failed to get task queues: {response.get('msg')}")
            return []

    def _get_map_image(self, map_name: str) -> bytes:
        """Get the image of the specified map

        Args:
            map_name (str): Name of the map

        Returns:
            bytes: PNG image data of the map
        """
        url = f"/gs-robot/data/map_png?map_name={map_name}"
        res = self._get(self._build_url(url))
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
        or on an unloaded map

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
        """Resume the paused cleaning task

        Returns:
            bool: True if successful, False otherwise
        """
        if self._is_firmware_post_v3_6_6():
            # For v3-6-6 and higher, we have multiple options
            url = "/gs-robot/cmd/resume_task_queue"  # For tasks on currently loaded map
        else:
            url = "/gs-robot/cmd/resume_task_queue"

        res = self._get(self._build_url(url))
        response = res.json()
        return response.get("successed", False)

    def _resume_task(self) -> bool:
        """Resume the paused cleaning task. Suitable for resuming a task on a currently loaded map
        or on an unloaded map

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

    def send_waypoint(self, pose: dict) -> bool:
        """Send the robot to a waypoint (named waypoint)

        Args:
            pose (dict): A dictionary containing the waypoint information
                {
                    "map_name": str,
                    "position_name": str
                }

        Returns:
            bool: True if successful, False otherwise
        """
        return self._send_waypoint(pose)

    def _send_waypoint(self, pose: dict) -> bool:
        """Implementation of send_waypoint that handles robot API calls

        Args:
            pose (dict): A dictionary containing the waypoint information
                {
                    "map_name": str,
                    "position_name": str
                }

        Returns:
            bool: True if successful, False otherwise
        """
        map_name = pose.get("map_name")
        position_name = pose.get("position_name")

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
            payload = {"destination": {"gridPosition": {"x": x, "y": y}, "angle": angle}}
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

    def _send_to_dock(self, map_name: str, dock_position_name: str = "Dock") -> bool:
        """Send the robot to the docking station

        Args:
            map_name (str): Name of the map
            dock_position_name (str, optional): Name of the docking station waypoint.
                Defaults to "Dock".

        Returns:
            bool: True if successful, False otherwise
        """
        return self._send_waypoint({"map_name": map_name, "position_name": dock_position_name})

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
