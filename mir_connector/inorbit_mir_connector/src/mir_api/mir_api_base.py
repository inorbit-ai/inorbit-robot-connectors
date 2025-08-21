# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from requests import Session, Response
from requests.exceptions import HTTPError
from abc import ABC, abstractmethod
import logging


class MirApiBaseClass(ABC):

    def __init__(self):
        self.logger = logging.getLogger(name=self.__class__.__name__)

    def _handle_status(self, res, request_args):
        """Log and raise an exception if the request failed."""
        try:
            res.raise_for_status()
        except HTTPError as e:
            self.logger.error(f"Error making request: {e}\nArguments: {request_args}")
            raise e

    def _get(self, url: str, session: Session, **kwargs) -> Response:
        """Perform a GET request."""
        self.logger.debug(f"GETting {url}: {kwargs}")
        res = session.get(url, **kwargs)
        self._handle_status(res, kwargs)
        return res

    def _post(self, url: str, session: Session, **kwargs) -> Response:
        """Perform a POST request."""
        self.logger.debug(f"POSTing {url}: {kwargs}")
        res = session.post(url, **kwargs)
        self.logger.debug(f"Response: {res}")
        self._handle_status(res, kwargs)
        return res

    def _delete(self, url: str, session: Session, **kwargs) -> Response:
        """Perform a DELETE request."""
        self.logger.debug(f"DELETEing {url}: {kwargs}")
        res = session.delete(url, **kwargs)
        self.logger.debug(f"Response: {res}")
        self._handle_status(res, kwargs)
        return res

    def _put(self, url: str, session: Session, **kwargs) -> Response:
        """Perform a PUT request."""
        self.logger.debug(f"PUTing {url}: {kwargs}")
        res = session.put(url, **kwargs)
        self.logger.debug(f"Response: {res}")
        self._handle_status(res, kwargs)
        return res

    @abstractmethod
    def _create_api_session(self) -> Session:
        """Configures a session object to interact with the MiR API."""
        pass

    @abstractmethod
    def _create_web_session(self) -> Session:
        """Makes a login request to MiR using stored credentials.
        This stores cookies on the session, which is required for the subsequent queries to work.
        """
        pass

    @abstractmethod
    def send_waypoint(self, pose):
        """Receives a pose and sends a request to command the robot to navigate to the waypoint"""
        pass

    @abstractmethod
    def abort_all_missions(self):
        """Aborts all missions"""
        pass

    @abstractmethod
    def queue_mission(self, mission_id: str):
        """Receives a mission ID and sends a request to append it to the robot's mission queue"""
        pass

    @abstractmethod
    def clear_error(self):
        """Clears robot Error status and sets robot state to Ready"""
        pass

    @abstractmethod
    def set_state(self, state_id: int):
        """Set the robot state"""
        pass

    @abstractmethod
    def set_status(self, data):
        """Set the robot status"""
        pass

    @abstractmethod
    def get_status(self):
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
    def get_executing_mission_id(self):
        """Returns the id of the mission being currently executed by the robot"""
        pass

    @abstractmethod
    def get_mission_actions(self, mission_id):
        """Queries a list of actions a mission executes using
        the missions/{mission_id}/actions endpoint"""
        pass

    @abstractmethod
    def get_mission_definition(self, mission_id):
        """Queries a mission definition using the missions/{mission_id} endpoint"""
        pass

    @abstractmethod
    def get_mission(self, mission_queue_id):
        """Queries a mission using the mission_queue/{mission_id} endpoint"""
        pass

    @abstractmethod
    def get_metrics(self):
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
