# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from abc import ABC, abstractmethod
import logging
import httpx
from typing import Union, Optional
from tenacity import (
    retry,
    wait_exponential_jitter,
    before_sleep_log,
    stop_after_attempt,
)


def should_retry_http_error(exception):
    """Custom retry condition for HTTP errors.

    Retries on:
    - TimeoutException, ConnectError (always)
    - HTTPStatusError for 5xx, 408, 429 (but not other 4xx)
    """
    if isinstance(exception, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    if isinstance(exception, httpx.HTTPStatusError):
        status_code = exception.response.status_code
        # Retry server errors (5xx) and specific client errors (408, 429)
        return status_code >= 500 or status_code in [408, 429]
    return False


class MirApiBaseClass(ABC):

    def __init__(
        self,
        base_url: str,
        auth: tuple[str, str] | None = None,
        default_headers: dict | None = None,
        timeout: int = 10,
        verify_ssl: bool = True,
        ssl_ca_bundle: Optional[str] = None,
        ssl_verify_hostname: bool = True,
    ):
        self.logger = logging.getLogger(name=self.__class__.__name__)
        self._base_url = base_url
        self._timeout = timeout

        # Configure SSL settings
        verify, ssl_context = self._configure_ssl_verify(
            verify_ssl, ssl_ca_bundle, ssl_verify_hostname
        )

        # Handle custom transport for hostname verification bypass
        if isinstance(verify, httpx.AsyncHTTPTransport):
            self._async_client = httpx.AsyncClient(
                base_url=base_url,
                timeout=timeout,
                auth=auth,
                headers=default_headers or {},
                transport=verify,  # Custom async transport with SSL context
            )
        else:
            self._async_client = httpx.AsyncClient(
                base_url=base_url,
                timeout=timeout,
                auth=auth,
                headers=default_headers or {},
                verify=verify,
            )

        # Store SSL config for sync clients
        self._ssl_verify = verify
        self._ssl_context = ssl_context  # Store SSL context for sync clients

        # If the log level is INFO, reduce the verbosity of httpx
        if self.logger.getEffectiveLevel() == logging.INFO:
            logging.getLogger("httpx").setLevel(logging.WARNING)

        # Store auth for retry logic
        self._auth = auth

    def _configure_ssl_verify(
        self, verify_ssl: bool, ssl_ca_bundle: Optional[str], ssl_verify_hostname: bool
    ) -> tuple[Union[bool, str, httpx.AsyncHTTPTransport], Optional[object]]:
        """Configure SSL verification settings for httpx client.

        Args:
            verify_ssl: Whether to verify SSL certificates
            ssl_ca_bundle: Path to custom CA bundle file
            ssl_verify_hostname: Whether to verify hostname matches certificate

        Returns:
            Tuple of (SSL verification setting for httpx, SSL context for sync clients)
        """
        if not verify_ssl:
            self.logger.warning(
                "SSL certificate verification is DISABLED. This connection is vulnerable to "
                "man-in-the-middle attacks. For secure connections, set verify_ssl=true and "
                "provide ssl_ca_bundle with MiR's certificate."
            )
            return False, None
        elif not ssl_verify_hostname:
            # Create custom SSL context that verifies cert but not hostname
            import ssl

            ssl_context = ssl.create_default_context()
            if ssl_ca_bundle:
                ssl_context.load_verify_locations(ssl_ca_bundle)
                self.logger.info(
                    f"Using custom CA bundle with hostname verification disabled: {ssl_ca_bundle}"
                )
            else:
                self.logger.info("Using default CA bundle with hostname verification disabled")
            ssl_context.check_hostname = False
            # Create custom async transport with our SSL context
            return httpx.AsyncHTTPTransport(verify=ssl_context), ssl_context
        elif ssl_ca_bundle:
            self.logger.info(f"Using custom CA bundle for SSL verification: {ssl_ca_bundle}")
            return ssl_ca_bundle, None
        else:
            return True, None  # Use default CA bundle

    @retry(
        wait=wait_exponential_jitter(initial=1, max=10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
        retry=should_retry_http_error,
        reraise=True,
    )
    async def _get(self, endpoint: str, **kwargs) -> httpx.Response:
        res = await self._async_client.get(endpoint, **kwargs)
        res.raise_for_status()
        return res

    @retry(
        wait=wait_exponential_jitter(initial=1, max=10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
        retry=should_retry_http_error,
        reraise=True,
    )
    async def _post(self, endpoint: str, **kwargs) -> httpx.Response:
        res = await self._async_client.post(endpoint, **kwargs)
        res.raise_for_status()
        return res

    @retry(
        wait=wait_exponential_jitter(initial=1, max=10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
        retry=should_retry_http_error,
        reraise=True,
    )
    async def _put(self, endpoint: str, **kwargs) -> httpx.Response:
        res = await self._async_client.put(endpoint, **kwargs)
        res.raise_for_status()
        return res

    @retry(
        wait=wait_exponential_jitter(initial=1, max=10),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
        retry=should_retry_http_error,
        reraise=True,
    )
    async def _delete(self, endpoint: str, **kwargs) -> httpx.Response:
        res = await self._async_client.delete(endpoint, **kwargs)
        res.raise_for_status()
        return res

    async def close(self):
        await self._async_client.aclose()

    @abstractmethod
    async def send_waypoint(self, pose):
        """Receives a pose and sends a request to command the robot to navigate to the waypoint"""
        pass

    @abstractmethod
    async def abort_all_missions(self):
        """Aborts all missions"""
        pass

    @abstractmethod
    async def queue_mission(self, mission_id: str):
        """Receives a mission ID and sends a request to append it to the robot's mission queue"""
        pass

    @abstractmethod
    async def clear_error(self):
        """Clears robot Error status and sets robot state to Ready"""
        pass

    @abstractmethod
    async def set_state(self, state_id: int):
        """Set the robot state"""
        pass

    @abstractmethod
    async def set_status(self, data):
        """Set the robot status"""
        pass

    @abstractmethod
    async def get_status(self):
        """Queries /status endpoint

        Returns:
            Robot status e.g.
            {
                "joystick_low_speed_mode_enabled": false,
                "mission_queue_url": null,
                "mode_id": 7,
                "moved": 253282.20120412167,
                "mission_queue_id": null,
                "robot_name": "Miriam",
                "joystick_web_session_id": "",
                "uptime": 15283,
                "errors": [],
                "unloaded_map_changes": false,
                "distance_to_next_target": 0.0,
                "serial_number": "200100005001715",
                "mode_key_state": "idle",
                "battery_percentage": 26.899999618530273,
                "map_id": "83e90bf0-2e9c-11ed-850f-0001299981c4",
                "safety_system_muted": false,
                "mission_text": "Mission was stopped..",
                "state_text": "Pause",
                "velocity": {
                    "linear": 0.0,
                    "angular": 0.0
                },
                "footprint": "[[-0.454,0.32],[0.506,0.32],[0.506,-0.32],[-0.454,-0.32]]",
                "user_prompt": null,
                "allowed_methods": null,
                "robot_model": "MiR100",
                "mode_text": "Mission",
                "session_id": "79b105f6-f02b-11e9-b72e-94c691a457cd",
                "state_id": 4,
                "battery_time_remaining": 25829,
                "position": {
                    "y": 10.252535820007324,
                    "x": 21.584815979003906,
                    "orientation": 168.22943115234375
                }
            }
        """
        pass

    @abstractmethod
    async def get_executing_mission_id(self):
        """Returns the id of the mission being currently executed by the robot"""
        pass

    @abstractmethod
    async def get_mission_actions(self, mission_id):
        """Queries a list of actions a mission executes using
        the missions/{mission_id}/actions endpoint"""
        pass

    @abstractmethod
    async def get_mission_definition(self, mission_id):
        """Queries a mission definition using the missions/{mission_id} endpoint"""
        pass

    @abstractmethod
    async def get_mission(self, mission_queue_id):
        """Queries a mission using the mission_queue/{mission_id} endpoint"""
        pass

    @abstractmethod
    async def get_metrics(self):
        """Queries /metrics endpoint

        Note: this endpoint returns a text/plain OpenMetrics response e.g.

        # HELP mir_robot_position_x_meters The x coordinate of the robots current position.
        # TYPE mir_robot_position_x_meters gauge
        # UNIT mir_robot_position_x_meters meters
        mir_robot_position_x_meters -0.008570603094995022
        # HELP mir_robot_position_y_meters The y coordinate of the robots current position.
        # TYPE mir_robot_position_y_meters gauge
        # UNIT mir_robot_position_y_meters meters
        mir_robot_position_y_meters -0.0017353880684822798
        ...

        The response is parsed and transformed into a dictionary e.g.
        {
            'mir_robot_position_x_meters': -0.008570603094995022,
            'mir_robot_position_y_meters': -0.0017353880684822798,
            'mir_robot_orientation_degrees': -0.017513880506157875,
            'mir_robot_info': 1.0,
            'mir_robot_distance_moved_meters_total': 253276.56012271848,
            'mir_robot_errors': 0.0,
            'mir_robot_state_id': 10.0,
            'mir_robot_uptime_seconds': 12660.0,
            'mir_robot_battery_percent': 30.0,
            'mir_robot_battery_time_remaining_seconds': 28822.0,
            'mir_robot_localization_score': 0.22447749211001752,
            'mir_robot_wifi_access_point_info': 1.0,
            'mir_robot_wifi_access_point_frequency_hertz': 0.0
        }
        """
        pass

    @abstractmethod
    async def get_diagnostics(self):
        """Queries /experimental/diagnostics endpoint"""
        pass

    @abstractmethod
    def get_map_sync(self, map_id: str):
        """Queries /maps/{map_id} endpoint

        This is a workaround to the publish_map method in the connnector not being async.

        Returns:
            Map data e.g.
            {
                "base_map": "base64 encoded image",
                "name": "map name",
                "resolution": "map resolution",
                "origin_x": "map origin x",
                "origin_y": "map origin y",
                ...
            }
        """
        pass
