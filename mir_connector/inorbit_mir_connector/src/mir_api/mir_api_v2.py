# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import hashlib
import math
import logging
import httpx
from enum import Enum
from typing import Optional
from prometheus_client import parser

from inorbit_edge.missions import MISSION_STATE_EXECUTING
from .mir_api_base import MirApiBaseClass

API_V2_CONTEXT_URL = "/api/v2.0.0"

# Endpoints
METRICS_ENDPOINT_V2 = "metrics"
MISSION_QUEUE_ENDPOINT_V2 = "mission_queue"
MISSION_GROUPS_ENDPOINT_V2 = "mission_groups"
MISSIONS_ENDPOINT_V2 = "missions"
STATUS_ENDPOINT_V2 = "status"
DIAGNOSTICS_ENDPOINT_V2 = "experimental/diagnostics"


class SetStateId(int, Enum):
    """Defined states for the set_state method"""

    READY = 3
    PAUSE = 4
    MANUALCONTROL = 11


class MirApiV2(MirApiBaseClass):

    def __init__(
        self,
        mir_host_address,
        mir_username,
        mir_password,
        mir_host_port=80,
        mir_use_ssl=False,
        verify_ssl=True,
        ssl_ca_bundle: Optional[str] = None,
        ssl_verify_hostname: bool = True,
    ):
        self.logger = logging.getLogger(name=self.__class__.__name__)
        self.mir_base_url = (
            f"{'https' if mir_use_ssl else 'http'}://{mir_host_address}:{mir_host_port}"
        )
        self.mir_api_base_url = f"{self.mir_base_url}{API_V2_CONTEXT_URL}"
        self.mir_username = mir_username
        self.mir_password = mir_password
        m_async = hashlib.sha256()
        m_async.update(self.mir_password.encode())
        self._auth = (self.mir_username, m_async.hexdigest())
        super().__init__(
            base_url=self.mir_api_base_url,
            auth=self._auth,
            default_headers={"Accept-Language": "en_US"},
            timeout=30,
            verify_ssl=verify_ssl,
            ssl_ca_bundle=ssl_ca_bundle,
            ssl_verify_hostname=ssl_verify_hostname,
        )

    async def get_metrics(self):
        """Get robot metrics"""
        metrics_api_url = f"/{METRICS_ENDPOINT_V2}"
        metrics = (await self._get(metrics_api_url)).text
        samples = {}
        for family in parser.text_string_to_metric_families(metrics):
            for sample in family.samples:
                samples[sample.name] = sample.value
        return samples

    async def get_mission_groups(self):
        """Get available mission groups"""
        mission_groups_api_url = f"/{MISSION_GROUPS_ENDPOINT_V2}"
        groups = (await self._get(mission_groups_api_url)).json()
        return groups

    async def get_mission_group_missions(self, mission_group_id: str):
        """Get available missions for a mission group"""
        mission_group_api_url = f"/{MISSION_GROUPS_ENDPOINT_V2}/{mission_group_id}/missions"
        missions = (await self._get(mission_group_api_url)).json()
        return missions

    async def create_mission_group(self, feature, icon, name, priority, **kwargs):
        """Create a new mission group"""
        mission_groups_api_url = f"/{MISSION_GROUPS_ENDPOINT_V2}"
        group = {
            "feature": feature,
            "icon": icon,
            "name": name,
            "priority": priority,
            **kwargs,
        }
        response = await self._post(
            mission_groups_api_url,
            headers={"Content-Type": "application/json"},
            json=group,
        )
        return response.json()

    async def delete_mission_group(self, group_id):
        """Delete a mission group"""
        mission_group_api_url = f"/{MISSION_GROUPS_ENDPOINT_V2}/{group_id}"
        await self._delete(
            mission_group_api_url,
            headers={"Content-Type": "application/json"},
        )

    async def delete_mission_definition(self, mission_id):
        """Delete a mission definition"""
        mission_api_url = f"/{MISSIONS_ENDPOINT_V2}/{mission_id}"
        await self._delete(
            mission_api_url,
            headers={"Content-Type": "application/json"},
        )

    async def create_mission(self, group_id, name, **kwargs):
        """Create a mission"""
        mission_api_url = f"/{MISSIONS_ENDPOINT_V2}"
        mission = {"group_id": group_id, "name": name, **kwargs}
        response = await self._post(
            mission_api_url,
            headers={"Content-Type": "application/json"},
            json=mission,
        )
        return response.json()

    async def add_action_to_mission(self, action_type, mission_id, parameters, priority, **kwargs):
        """Add an action to an existing mission"""
        action_api_url = f"/{MISSIONS_ENDPOINT_V2}/{mission_id}/actions"
        action = {
            "mission_id": mission_id,
            "action_type": action_type,
            "parameters": parameters,
            "priority": priority,
            **kwargs,
        }
        response = await self._post(
            action_api_url,
            headers={"Content-Type": "application/json"},
            json=action,
        )
        return response.json()

    async def get_mission(self, mission_queue_id):
        """Queries a mission using the mission_queue/{mission_id} endpoint"""
        mission_api_url = f"/{MISSION_QUEUE_ENDPOINT_V2}/{mission_queue_id}"
        mission = (await self._get(mission_api_url)).json()
        actions = (await self._get(f"{mission_api_url}/actions")).json()

        mission_id = mission["mission_id"]
        mission["definition"] = await self.get_mission_definition(mission_id)
        mission["actions"] = actions
        mission["definition"]["actions"] = await self.get_mission_actions(mission_id)
        return mission

    async def get_mission_definition(self, mission_id):
        """Queries a mission definition using the missions/{mission_id} endpoint"""
        mission_api_url = f"/{MISSIONS_ENDPOINT_V2}/{mission_id}"
        response = await self._get(mission_api_url)
        mission = response.json()
        return mission

    async def get_mission_actions(self, mission_id):
        """Queries a list of actions a mission executes using
        the missions/{mission_id}/actions endpoint"""
        actions_api_url = f"/{MISSIONS_ENDPOINT_V2}/{mission_id}/actions"
        response = await self._get(actions_api_url)
        actions = response.json()
        return actions

    async def get_missions_queue(self):
        """Returns all missions in the missions queue"""
        missions_api_url = f"/{MISSION_QUEUE_ENDPOINT_V2}"
        response = await self._get(missions_api_url)
        return response.json()

    async def get_executing_mission_id(self):
        """Returns the id of the mission being currently executed by the robot"""
        missions_api_url = f"/{MISSION_QUEUE_ENDPOINT_V2}"
        response = await self._get(missions_api_url)
        missions = response.json()
        executing = [m for m in missions if m["state"] == MISSION_STATE_EXECUTING]
        return executing[0]["id"] if len(executing) else None

    async def queue_mission(
        self,
        mission_id: str,
        message: Optional[str] = None,
        parameters: Optional[list] = None,
        priority: Optional[int] = 0,
        fleet_schedule_guid: Optional[str] = None,
        description: Optional[str] = None,
    ):
        """Receives a mission ID and sends a request to append it to the robot's mission queue"""
        queue_mission_url = f"/{MISSION_QUEUE_ENDPOINT_V2}"
        mission_queues = {
            "mission_id": mission_id,
        }
        if message:
            mission_queues["message"] = message
        if parameters:
            mission_queues["parameters"] = parameters
        if priority:
            mission_queues["priority"] = priority
        if fleet_schedule_guid:
            mission_queues["fleet_schedule_guid"] = fleet_schedule_guid
        if description:
            mission_queues["description"] = description

        response = await self._post(
            queue_mission_url,
            headers={"Content-Type": "application/json"},
            json=mission_queues,
        )
        self.logger.debug(f"Mission queued: {response.text}")

    async def abort_all_missions(self):
        """Aborts all missions"""
        queue_mission_url = f"/{MISSION_QUEUE_ENDPOINT_V2}"
        response = await self._delete(
            queue_mission_url,
            headers={"Content-Type": "application/json"},
        )
        self.logger.debug(f"Missions aborted: {response.text}")

    async def set_state(self, state_id: int):
        """Set robot state

        Some allowed values are defined in the SetStateId enum
        """
        return await self.set_status({"state_id": state_id})

    async def set_status(self, data):
        """Set robot status

        This method wraps PUT /status API
        """
        status_api_url = f"/{STATUS_ENDPOINT_V2}"
        response = await self._put(
            status_api_url,
            headers={"Content-Type": "application/json"},
            json=data,
        )
        return response.json()

    async def clear_error(self):
        """Clears robot Error state and sets robot state to Ready"""
        await self.set_status({"clear_error": True})
        # Also setting robot state to Ready because it stays
        # paused after clearing the error state
        await self.set_state(SetStateId.READY.value)

    async def send_waypoint(self, pose):
        """Receives a pose and sends a request to command the robot to navigate to the waypoint"""
        orientation_degs = math.degrees(float(pose["theta"]))
        parameters = {
            "clearall": "yes",
            "x": pose["x"],
            "y": pose["y"],
            "orientation": orientation_degs,
            "mode": "map-go-to-coordinates",
        }
        self.logger.info(
            f"Sending waypoint to ({pose['x']:.2f}, {pose['y']:.2f}, {orientation_degs:.1f}°)"
        )
        async with httpx.AsyncClient(base_url=self.mir_base_url, timeout=30) as client:
            res = await client.get("/", params=parameters)
            res.raise_for_status()
            self.logger.debug(f"Waypoint response: {res.text}")

    async def get_status(self):
        status_api_url = f"/{STATUS_ENDPOINT_V2}"
        response = await self._get(status_api_url)
        return response.json()

    async def get_diagnostics(self):
        response = await self._get(DIAGNOSTICS_ENDPOINT_V2)
        return response.json()

    async def get_map(self, map_id: str):
        """Queries /maps/{map_id} endpoint.

        Args:
            map_id: The ID of the map to fetch

        Returns:
            Map data including base_map (base64 encoded image), resolution, origin_x, origin_y
        """
        response = await self._get(f"maps/{map_id}")
        return response.json()
