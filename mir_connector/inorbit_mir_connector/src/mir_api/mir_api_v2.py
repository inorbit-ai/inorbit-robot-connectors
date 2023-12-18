# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import requests
import hashlib
from prometheus_client import parser
import json
import math
from .mir_api_base import MirApiBaseClass
from inorbit_edge.missions import MISSION_STATE_EXECUTING

API_V2_CONTEXT_URL = "/api/v2.0.0"

# Endpoints
METRICS_ENDPOINT_V2 = "metrics"
MISSION_QUEUE_ENDPOINT_V2 = "mission_queue"
MISSIONS_ENDPOINT_V2 = "missions"
STATUS_ENDPOINT_V2 = "status"


class MirApiV2(MirApiBaseClass):
    def __init__(self, mir_base_url, mir_username, mir_password, loglevel="INFO"):
        super().__init__(loglevel=loglevel)
        self.mir_base_url = mir_base_url
        self.mir_api_url = f"{mir_base_url}{API_V2_CONTEXT_URL}"
        self.mir_username = mir_username
        self.mir_password = mir_password
        self.api_session = self._create_api_session()
        self.web_session = self._create_web_session()

    def _create_api_session(self) -> requests.Session:
        session = requests.Session()
        m = hashlib.sha256()
        m.update(self.mir_password.encode())
        session.auth = (
            self.mir_username,
            m.hexdigest(),
        )
        session.headers.update({"Accept-Language": "en_US"})
        return session

    def _create_web_session(self) -> requests.Session:
        parameters = {
            "mode": "log-in",
        }
        creds = {
            "login_username": self.mir_username,
            "login_password": self.mir_password,
        }
        session = requests.Session()
        response = self._post(self.mir_base_url, session, params=parameters, data=creds)
        if response.text == "error":
            raise ValueError("Invalid Login Credentials")
        else:
            self.logger.info(response.text)
            return session

    def get_metrics(self):
        """Get robot metrics"""
        metrics_api_url = f"{self.mir_api_url}/{METRICS_ENDPOINT_V2}"
        metrics = self._get(metrics_api_url, self.api_session).text
        samples = {}
        for family in parser.text_string_to_metric_families(metrics):
            for sample in family.samples:
                samples[sample.name] = sample.value
        return samples

    def get_mission(self, mission_queue_id):
        """Queries a mission using the mission_queue/{mission_id} endpoint"""
        mission_api_url = f"{self.mir_api_url}/{MISSION_QUEUE_ENDPOINT_V2}/{mission_queue_id}"
        mission = self._get(mission_api_url, self.api_session).json()
        actions = self._get(f"{mission_api_url}/actions", self.api_session).json()

        mission_id = mission["mission_id"]
        # Fetch mission definition to complete the name
        mission["definition"] = self.get_mission_definition(mission_id)
        # Fetch executed actions
        mission["actions"] = actions
        # Fetch mission actions (from mission definition, not from the
        # queued mission)
        mission["definition"]["actions"] = self.get_mission_actions(mission_id)
        return mission

    def get_mission_definition(self, mission_id):
        """Queries a mission definition using the missions/{mission_id} endpoint"""
        mission_api_url = f"{self.mir_api_url}/{MISSIONS_ENDPOINT_V2}/{mission_id}"
        response = self._get(mission_api_url, self.api_session)
        mission = response.json()
        return mission

    def get_mission_actions(self, mission_id):
        """Queries a list of actions a mission executes using
        the missions/{mission_id}/actions endpoint"""
        actions_api_url = f"{self.mir_api_url}/{MISSIONS_ENDPOINT_V2}/{mission_id}/actions"
        response = self._get(actions_api_url, self.api_session)
        actions = response.json()
        return actions

    def get_executing_mission_id(self):
        """Returns the id of the mission being currently executed by the robot"""
        # Note(mike) This could be optimized fetching only some elements, but the API is pretty
        # limited
        missions_api_url = f"{self.mir_api_url}/{MISSION_QUEUE_ENDPOINT_V2}"
        response = self._get(missions_api_url, self.api_session)
        missions = response.json()
        executing = [m for m in missions if m["state"] == MISSION_STATE_EXECUTING]
        return executing[0]["id"] if len(executing) else None

    def queue_mission(self, mission_id):
        """Receives a mission ID and sends a request to append it to the robot's mission queue"""
        queue_mission_url = f"{self.mir_api_url}/{MISSION_QUEUE_ENDPOINT_V2}"
        mission_queues = {
            "mission_id": mission_id,
        }

        response = self._post(
            queue_mission_url,
            self.api_session,
            headers={"Content-Type": "application/json"},
            json=mission_queues,
        )
        self.logger.info(response.text)

    def abort_all_missions(self):
        """Aborts all missions"""
        queue_mission_url = f"{self.mir_api_url}/{MISSION_QUEUE_ENDPOINT_V2}"
        response = self._delete(
            queue_mission_url,
            self.api_session,
            headers={"Content-Type": "application/json"},
        )
        self.logger.info(response.text)

    def set_state(self, state_id):
        """Set robot state

        Allowed values are:
            - 3: READY
            - 4: PAUSE
            - 11: MANUAL CONTROL
        """
        return self.set_status(json.dumps({"state_id": state_id}))

    def set_status(self, data):
        """Set robot status

        This method wraps PUT /status API
        """
        status_api_url = f"{self.mir_api_url}/{STATUS_ENDPOINT_V2}"
        response = self._put(
            status_api_url,
            self.api_session,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        return response.json()

    def clear_error(self):
        """Clears robot Error state and sets robot state to Ready"""
        self.set_status(json.dumps({"clear_error": True}))
        # Also setting robot state to Ready because it stays
        # paused after clearing the error state
        self.set_state(3)

    def send_waypoint(self, pose):
        """Receives a pose and sends a request to command the robot to navigate to the waypoint"""
        self.logger.info("Sending waypoint")
        orientation_degs = math.degrees(float(pose["theta"]))
        parameters = {
            "clearall": "yes",
            "x": pose["x"],
            "y": pose["y"],
            "orientation": orientation_degs,
            "mode": "map-go-to-coordinates",
        }
        response = self._get(self.mir_base_url, self.web_session, params=parameters)
        self.logger.info(response.text)

    def get_status(self):
        status_api_url = f"{self.mir_api_url}/{STATUS_ENDPOINT_V2}"
        response = self._get(status_api_url, self.api_session)
        return response.json()
