# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from enum import Enum

import httpx
from pydantic import HttpUrl

from .base_api_client import BaseAPIClient


# Find documentation on each command type and their parameters on pages 25-31 of
# "Guide to the use of cleaning line for Gausium Open API open platform (universal version).pdf"
# https://drive.google.com/file/d/1y6s7mnVGxg6vJj3wSJGrPtZ1vAb3hVB2/view?usp=drive_link
class OtherRemoteCommandType(str, Enum):
    OTHER_REMOTE_COMMAND_TYPE_UNSPECIFIED = "OTHER_REMOTE_COMMAND_TYPE_UNSPECIFIED"
    REMOTE_REBOOT = "REMOTE_REBOOT"
    REMOTE_INITIALIZE = "REMOTE_INITIALIZE"
    ABORT_INITIALIZE = "ABORT_INITIALIZE"


class RemoteControlCommandType(str, Enum):
    REMOTE_CONTROL_COMMAND_TYPE_UNSPECIFIED = "REMOTE_CONTROL_COMMAND_TYPE_UNSPECIFIED"
    REMOTE_CONTROL_START = "REMOTE_CONTROL_START"
    REMOTE_CONTROL_STOP = "REMOTE_CONTROL_STOP"
    REMOTE_CONTROL_MOVE = "REMOTE_CONTROL_MOVE"


class RemoteControlCommandParameter(str, Enum):
    DIRECTION_UNSPECIFIED = "DIRECTION_UNSPECIFIED"
    FORWARD = "FORWARD"
    BACKWARD = "BACKWARD"
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class RemoteEmergencyStopCommandType(str, Enum):
    REMOTE_EMERGENCY_STOP_COMMAND_TYPE_UNSPECIFIED = (
        "REMOTE_EMERGENCY_STOP_COMMAND_TYPE_UNSPECIFIED"
    )
    EMERGENCY_STOP = "EMERGENCY_STOP"
    RELEASE_EMERGENCY_STOP = "RELEASE_EMERGENCY_STOP"


class RemoteNavigationCommandType(str, Enum):
    REMOTE_NAVIGATION_COMMAND_TYPE_UNSPECIFIED = "REMOTE_NAVIGATION_COMMAND_TYPE_UNSPECIFIED"
    CROSS_NAVIGATE = "CROSS_NAVIGATE"
    PAUSE_NAVIGATE = "PAUSE_NAVIGATE"
    RESUME_NAVIGATE = "RESUME_NAVIGATE"
    STOP_NAVIGATE = "STOP_NAVIGATE"


class RemoteTaskCommandType(str, Enum):
    REMOTE_TASK_COMMAND_TYPE_UNSPECIFIED = "REMOTE_TASK_COMMAND_TYPE_UNSPECIFIED"
    START_TASK = "START_TASK"
    PAUSE_TASK = "PAUSE_TASK"
    RESUME_TASK = "RESUME_TASK"
    STOP_TASK = "STOP_TASK"


# TODO: Available cleaning modes should be fetched from the status API
class CleaningModes(str, Enum):
    """Cleaning modes that can be used to create tasks"""

    CLEAN = "清洗"
    SWEEP = "清扫"
    DUST = "尘推"
    VACUUM = "吸尘"


class TaskState(Enum):
    """
    Values for reported task states.
    """

    OTHER = "OTHER"
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"


class RobotAPI(BaseAPIClient):
    """Gausium Phantas robot API wrapper."""

    def __init__(
        self,
        base_url: HttpUrl,
        serial_number: str,
        client_id: str,
        client_secret: str,
        access_key_secret: str,
    ):
        """Initializes the connection with the Gausium Phantas robot

        Args:
            base_url (HttpUrl): Base URL of the robot API. e.g. "http://192.168.0.256:80/"
            serial_number (str): Robot to connect
            client_id (str): Client ID for OAuth authentication
            client_secret (str): Client secret for OAuth authentication
            access_key_secret (str): Access key secret for OAuth authentication
        """
        super().__init__(
            base_url=base_url,
            client_id=client_id,
            client_secret=client_secret,
            access_key_secret=access_key_secret,
        )
        self.serial_number = serial_number

    def _build_url(self, endpoint: str) -> str:
        """Create the full URL for the API endpoint."""
        # Base URL is already a URL (including the trailing /), so we can just append the endpoint
        return f"{self.base_url}{endpoint}"

    async def get_robot_list(
        self,
        filter: str = "",
        page: int = 1,
        page_size: int = 10,
        relation: str = "cugrup",
    ) -> dict:
        """Get a list of robots from the robot list API."""
        endpoint = (
            "v1alpha1/robots"
            f"?filter={filter}&page={page}&pageSize={page_size}&relation={relation}"
        )
        response = await self._get(endpoint)
        return response.json()

    async def get_status(self):
        """Get the status of the robot"""
        response = await self._get(f"v1alpha1/robots/{self.serial_number}/status")
        return response.json()

    async def get_status_v2(self):
        """Get the status of the robot"""
        response = await self._get(f"openapi/v2alpha1/s/robots/{self.serial_number}/status")
        return response.json()

    async def get_task_reports(self, page: int = 1, page_size: int = 10) -> dict:
        """Get a list of task reports for the robot"""
        endpoint = (
            f"v1alpha1/robots/{self.serial_number}/taskReports?page={page}&pageSize={page_size}"
        )
        response = await self._get(endpoint)
        return response.json()

    async def get_task_reports_v2(self, page: int = 1, page_size: int = 10) -> dict:
        """Get a list of task reports for the robot"""
        endpoint = (
            f"openapi/v2alpha1/robots/{self.serial_number}/taskReports?"
            f"page={page}&pageSize={page_size}"
        )
        response = await self._get(endpoint)
        return response.json()

    async def get_robot_details(self):
        """Get details of the robot.

        Returns:
            dict: A dictionary containing robot details with the following structure:
                {
                    "data": {
                        "firstReportDate": str,  # First report date in YYYY-MM-DD format
                        "totalMileage": float,   # Total distance traveled in ft
                        "totalDuration": int     # Total operation time in seconds
                    },
                    "errorCode": int,           # Error code, 0 indicates success
                    "code": Any,                # Additional code info
                    "msg": str,                 # Message string
                    "success": bool,            # Whether request was successful
                    "count": int,               # Count value
                    "page": int,                # Page number
                    "pagesize": int             # Page size
                }
        """
        endpoint = f"https://bot.gs-robot.com/robot-task/robot/details/{self.serial_number}"
        response = await self._get(endpoint)
        return response.json()

    async def create_remote_task_command(
        self, command_type: RemoteTaskCommandType, command_parameter: dict = None
    ) -> dict:
        """Execute a command on the robot."""
        json_data = {
            "serialNumber": self.serial_number,
            "remoteTaskCommandType": command_type.value,
        }
        if command_parameter:
            json_data["commandParameter"] = command_parameter

        response = await self._post(
            f"v1alpha1/robots/{self.serial_number}/commands", json=json_data
        )
        return response.json()

    async def create_remote_navigation_command(
        self, command_type: RemoteNavigationCommandType, command_parameter: dict = None
    ) -> dict:
        """Execute a command on the robot."""
        json_data = {
            "serialNumber": self.serial_number,
            "remoteNavigationCommandType": command_type.value,
        }
        if command_parameter:
            json_data["commandParameter"] = command_parameter

        response = await self._post(
            f"v1alpha1/robots/{self.serial_number}/commands", json=json_data
        )
        return response.json()

    async def send_waypoint(self, pose: dict):
        """Example: Receives a pose and sends a request to command the robot to
        navigate to the waypoint"""
        # TODO: see startNavigationParameter in the PDF
        self.logger.warning("Send waypoint not implemented")
        raise NotImplementedError

    async def create_nosite_task(
        self,
        task_name: str,
        map_id: str,
        map_name: str,
        area_id: str,
        cleaning_mode: CleaningModes,
        loop: bool,
        loop_count: int = 1,
    ):
        """Submit a temporary no-site task to the robot"""
        # NOTE: no-site tasks don't return success/failure status, it has to be inferred from the
        # status endpoint. Temporary site tasks are more reliable, but require a site to be created
        # (or use the map instead of the site)
        # List robot commands can be used to get the status of this task
        data = {
            "productId": self.serial_number,
            "tempTaskCommand": {
                "taskName": task_name,
                "cleaningMode": cleaning_mode.value,
                "loop": str(loop).lower(),
                "loopCount": str(loop_count),
                "mapName": map_name,
                "startParam": {
                    "mapId": map_id,
                    "areaId": area_id,
                },
            },
        }

        response = await self._post("openapi/v2alpha1/robotCommand/tempTask:send", json=data)
        return response.json()

    def get_map_image_sync(self, map_id: str, map_name: str, map_version: str) -> bytes:
        """Get the map image synchronously

        This is a workaround to the publish_map method in the connnector no being async.

        Args:
            map_id (str): ID of the map
            map_name (str): Name of the map
            map_version (str): Version of the map

        Returns:
            bytes: PNG image data of the map
        """
        # Timeout for the second part of the request, where the actual image is downloaded
        image_timeout = max(self.api_req_timeout, 30)

        # Get the download URI
        with httpx.Client(base_url=self.base_url, timeout=self.api_req_timeout) as client:
            # Add authentication headers
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token.access_token}"
                headers["Content-Type"] = "application/json"

            # Get the download URI
            endpoint = f"openapi/v2alpha1/robots/{self.serial_number}/map"
            params = {"mapId": map_id, "mapName": map_name, "mapVersion": map_version}
            # Note: the following is usually handled by self._get(), but since this is a hack for
            # sync calls, it has to be done here
            try:
                response = client.get(endpoint, params=params, headers=headers)
            except Exception as e:
                self._last_call_successful = False
                raise e

            self._handle_status(response, {"params": params})

            response_data = response.json()

            download_uri = response_data.get("downloadUri")
            if not download_uri:
                raise ValueError(f"No download URI found in response: {response_data}")

        # Download the image
        self.logger.debug(
            f"Getting map image for {map_name} (ID: {map_id}) with timeout {image_timeout}s"
        )
        with httpx.Client(timeout=image_timeout) as download_client:
            try:
                response = download_client.get(download_uri)
            except Exception as e:
                self._last_call_successful = False
                raise e

            self._handle_status(response, None)

            return response.content
