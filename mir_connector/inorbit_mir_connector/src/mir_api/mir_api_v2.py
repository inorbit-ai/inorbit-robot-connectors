# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import hashlib
from prometheus_client import parser
import json
import math
import websocket
import logging
import threading
from time import sleep
import httpx
from .mir_api_base import MirApiBaseClass
from inorbit_edge.missions import MISSION_STATE_EXECUTING

API_V2_CONTEXT_URL = "/api/v2.0.0"

# Endpoints
METRICS_ENDPOINT_V2 = "metrics"
MISSION_QUEUE_ENDPOINT_V2 = "mission_queue"
MISSION_GROUPS_ENDPOINT_V2 = "mission_groups"
MISSIONS_ENDPOINT_V2 = "missions"
STATUS_ENDPOINT_V2 = "status"
DIAGNOSTICS_ENDPOINT_V2 = "experimental/diagnostics"


class MirApiV2(MirApiBaseClass):

    def __init__(
        self,
        mir_host_address,
        mir_username,
        mir_password,
        mir_host_port=80,
        mir_use_ssl=False,
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
            timeout=10,
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
        group = {"feature": feature, "icon": icon, "name": name, "priority": priority, **kwargs}
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

    async def queue_mission(self, mission_id):
        """Receives a mission ID and sends a request to append it to the robot's mission queue"""
        queue_mission_url = f"/{MISSION_QUEUE_ENDPOINT_V2}"
        mission_queues = {
            "mission_id": mission_id,
        }

        response = await self._post(
            queue_mission_url,
            headers={"Content-Type": "application/json"},
            json=mission_queues,
        )
        self.logger.info(response.text)

    async def abort_all_missions(self):
        """Aborts all missions"""
        queue_mission_url = f"/{MISSION_QUEUE_ENDPOINT_V2}"
        response = await self._delete(
            queue_mission_url,
            headers={"Content-Type": "application/json"},
        )
        self.logger.info(response.text)

    async def set_state(self, state_id):
        """Set robot state

        Allowed values are:
            - 3: READY
            - 4: PAUSE
            - 11: MANUAL CONTROL
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
        await self.set_state(3)

    async def send_waypoint(self, pose):
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
        async with httpx.AsyncClient(base_url=self.mir_base_url, timeout=10) as client:
            res = await client.get("/", params=parameters)
            res.raise_for_status()
            self.logger.info(res.text)

    async def get_status(self):
        status_api_url = f"/{STATUS_ENDPOINT_V2}"
        response = await self._get(status_api_url)
        return response.json()

    async def get_diagnostics(self):
        response = await self._get(DIAGNOSTICS_ENDPOINT_V2)
        return response.json()

    def get_map_sync(self, map_id: str):
        """Queries /maps/{map_id} endpoint synchronously

        This is a workaround to the publish_map method in the connnector not being async.
        """
        # Timeout for the second part of the request, where the actual image is downloaded
        image_timeout = max(self._timeout, 30)

        # Download the image
        with httpx.Client(base_url=self._base_url, timeout=image_timeout) as client:
            try:
                response = client.get(
                    f"maps/{map_id}", headers={"Accept-Language": "en_US"}, auth=self._auth
                )
                response.raise_for_status()
            except Exception as e:
                self._last_call_successful = False
                raise e

            return response.json()


class MirWebSocketV2:

    def __init__(self, mir_host_address, mir_ws_port=9090, mir_use_ssl=False):
        self.logger = logging.getLogger(name=self.__class__.__name__)

        self.mir_ws_url = f"{'wss' if mir_use_ssl else 'ws'}://{mir_host_address}:{mir_ws_port}/"
        # Store the last diagnostics_agg message (raw)
        self.last_diagnostics_agg_msg = {}

        # Create WebSocket object
        self.ws = websocket.WebSocketApp(
            url=self.mir_ws_url, on_message=self.on_message, on_close=self.on_close
        )

    def on_close(self, ws, close_status_code, close_msg):
        self.logger.info("Disconnected from server")

    def on_message(self, ws, message):
        try:
            json_msg = json.loads(message)
        except ValueError:
            self.logger.debug(f"Ignored malformed message: {message}")
        else:
            topic = json_msg.get("topic")
            if topic == "/diagnostics_agg":
                self.handle_diagnostics_agg_msg(json_msg)

    def connect(self):
        # Start listening to web socket on a daemon thread.
        self.ws_thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self.ws_thread.start()

        conn_retries = 5
        while not self.ws.sock or not self.ws.sock.connected:
            conn_retries -= 1
            self.logger.info(f"Waiting for ws connection: '{self.mir_ws_url}")
            sleep(1)
            if not conn_retries:
                raise RuntimeError(f"Failed to connect to ws: '{self.mir_ws_url}")

        self.subscribe_diagnostics_agg()

    def disconnect(self):
        self.logger.info("Closing ws connection")
        self.ws.close()
        self.logger.info("Waiting for ws thread to finish")
        self.ws_thread.join()

    def subscribe_diagnostics_agg(self):
        self.logger.info("Subscribing to 'diagnostics_agg' topic")
        # This is the same command the MiR web UI sends
        msg = json.dumps(
            {
                "op": "subscribe",
                "id": "subscribe:/diagnostics_agg:1",
                "type": "diagnostic_msgs/DiagnosticArray",
                "topic": "/diagnostics_agg",
                "compression": "none",
                "throttle_rate": 0,
                "queue_length": 0,
            }
        )

        self.logger.debug(f"Sending message: {msg}")
        self.ws.send(msg)

    def handle_diagnostics_agg_msg(self, message):
        self.logger.debug(f"Got diagnostics_agg message: {message}")
        self.last_diagnostics_agg_msg = message

    def get_diagnostics_agg_value(self, status_name, key_name):
        status_list = self.last_diagnostics_agg_msg.get("msg", {}).get("status", [])
        status = next((status for status in status_list if status["name"] == status_name), None)
        # Caller should handle 'None' return values and ignore them
        if not status:
            return None
        values = status.get("values", [])
        # Finally, look for the key/value dictionary having key = key_name (fn param)
        status_kv = next((value for value in values if value["key"] == key_name), None)
        if not status_kv:
            return None
        return status_kv.get("value")

    def get_cpu_usage(self):
        cpu_status_name = "/Computer/PC/CPU Load"
        average_cpu_load_key_name = "Average CPU load"
        average_cpu_load = self.get_diagnostics_agg_value(
            status_name=cpu_status_name, key_name=average_cpu_load_key_name
        )
        if average_cpu_load:
            return float(average_cpu_load) / 100
        else:
            return None

    def get_disk_usage(self):
        hdd_status_name = "/Computer/PC/Harddrive"
        hdd_total_size_key_name = '{"message": "Total size %(unit)s", "args": {"unit":"[GB]"}}'
        hdd_used_size_key_name = '{"message": "Used %(unit)s", "args": {"unit":"[GB]"}}'
        hdd_total_size = self.get_diagnostics_agg_value(
            status_name=hdd_status_name, key_name=hdd_total_size_key_name
        )
        hdd_used_size = self.get_diagnostics_agg_value(
            status_name=hdd_status_name, key_name=hdd_used_size_key_name
        )
        if not hdd_total_size or not hdd_used_size:
            return None
        try:
            hdd_used_percentage = ((float(hdd_used_size) * 100) / float(hdd_total_size)) / 100
            return hdd_used_percentage
        except ZeroDivisionError:
            # Adding extra validation in case for some reason the hdd_total_size equals 0
            return None

    def get_memory_usage(self):
        memory_status_name = "/Computer/PC/Memory"
        memory_total_size_key_name = '{"message": "Total size %(unit)s", "args": {"unit":"[GB]"}}'
        memory_used_size_key_name = '{"message": "Used %(unit)s", "args": {"unit":"[GB]"}}'
        memory_total_size = self.get_diagnostics_agg_value(
            status_name=memory_status_name, key_name=memory_total_size_key_name
        )
        memory_used_size = self.get_diagnostics_agg_value(
            status_name=memory_status_name, key_name=memory_used_size_key_name
        )

        if not memory_used_size or not memory_total_size:
            return None
        try:
            memory_used_percentage = (
                (float(memory_used_size) * 100) / float(memory_total_size)
            ) / 100
            return memory_used_percentage
        except ZeroDivisionError:
            # Adding extra validation in case for some reason the memory_total_size equals 0
            return None
