# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""HTTPClient class. Manages requests to the OTTO Fleet Manager REST API."""

import logging
import uuid

import requests
import urllib3


class HTTPClient:
    """Util class to interact with OTTO's Fleet Manager REST API."""

    def __init__(
        self,
        base_url,
        verify_ssl=True,
        loglevel="INFO",
        disable_insecure_request_warning=False,
    ):
        """
        HTTP client constructor.

        Args:
            base_url (str): Fleet manager base URL. e.g. "https://192.168.1.256/api/"
            verify_ssl (bool, optional): Use HTTPS. Defaults to True.
            loglevel (str, optional): Defaults to "INFO".
            disable_insecure_request_warning (bool, optional): Disable warnings on invalid TLS
            connections. Defaults to False.
        """
        self.api_sess = requests.Session()
        self.logger = logging.getLogger(name=self.__class__.__name__)
        self.logger.setLevel(loglevel)
        self.fleet_url = base_url.rstrip("/") + "/fleet/"
        self.dispatch_url = base_url.rstrip("/") + "/dispatch/"
        self.verify_ssl = verify_ssl
        if disable_insecure_request_warning:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _post(self, url, json):
        """Perform a POST request.

        Args:
            url (str): URL where to post.
            json (str): request body.

        Returns:
            Response object.
        """
        self.logger.info(f"POSTing to {url}: json {json}")
        res = self.api_sess.post(
            url,
            headers={"Content-Type": "application/json"},
            json=json,
            verify=self.verify_ssl,
        )
        self.logger.debug(f"Response: {res}")
        if res.status_code >= 300:
            self.logger.warn(f"Non 200 code {res.status_code}")
        return res

    def _get(self, url, json):
        """Perform a GET request.

        Args:
            url (str): URL where to GET.
            json (str): request body.

        Returns:
            Response object.
        """
        self.logger.info(f"GETting {url}: json {json}")
        res = self.api_sess.get(
            url,
            headers={"Content-Type": "application/json"},
            json=json,
            verify=self.verify_ssl,
        )
        self.logger.debug(f"Response: {res}")
        if res.status_code >= 300:
            self.logger.warn(f"Non 200 code {res.status_code}")
        return res

    def simple_move_mission(
        self,
        otto_id,
        place_id,
        name="Move to waypoint",
        description="Simple Move to Place mission created by Edge Connector",
    ):
        """Create a Job with a single task of type Move to a place.

        Args:
            otto_id (str): Robot to control.
            place_id (str): ID of the place where the robot will go.
            name (str, optional): Job name. Defaults to "Move to waypoint".
            description (str, optional): Job description. Defaults to "Simple Move to Place mission
            created by Edge Connector".

        Returns:
            Whether the procedure was dispatched successfully.
        """
        res = self._post(
            self.fleet_url + "/v2/operations",
            {
                "id": uuid.uuid4().int,
                "jsonrpc": "2.0",
                "method": "createMission",
                "params": {
                    "mission": {
                        "name": name,
                        "description": description,
                        "finalized": True,  # Finalize the job once the tasks here are completed
                        "force_robot": otto_id,
                    },
                    "tasks": [
                        {
                            "description": "Move to place task",
                            "place": place_id,
                            "task_type": "MOVE",
                        }
                    ],
                },
            },
        )
        return self._evaluate_jsonrpc_response(res, "createMission")

    def dispatch_mission_template(
        self,
        otto_id,
        mission_template_id,
        name="Mission from template",
        description="Job Template dispatched by Edge Connector",
    ):
        """Create a Job from a template.

        Args:
            otto_id (str): Force mission to be assigned to this robot.
            mission_template_id (str): Template ID.
            name (str, optional): Job name. Defaults to "Mission from template"..
            description (str, optional): Job description. Defaults to "Job Template dispatched by
            Edge Connector".

        Returns:
            Whether the command was dispatched successfully.
        """
        res = self._post(
            self.dispatch_url + "/v2/operations",
            {
                "id": uuid.uuid4().int,
                "jsonrpc": "2.0",
                "method": "dispatch_mission_template",
                "params": {
                    "name": name,
                    "description": description,
                    "dispatch_repeat": "single",
                    "force_robot": otto_id,
                    "mission_id": str(uuid.uuid4()),
                    "mission_template": mission_template_id,
                },
            },
        )
        return self._evaluate_jsonrpc_response(res, "dispatch_mission_template")

    def pause_mission(self, mission_id):
        """Trigger a pauseMission RPC.

        Args:
            mission_id (str): ID of the mission to be paused.

        Returns:
            Whether the command was dispatched successfully.
        """
        res = self._post(
            self.fleet_url + "/v2/operations",
            {
                "id": uuid.uuid4().int,
                "jsonrpc": "2.0",
                "method": "pauseMission",
                "params": {"id": mission_id},
            },
        )
        return self._evaluate_jsonrpc_response(res, "pauseMission")

    def resume_mission(self, mission_id):
        """Trigger a resumeMission RPC.

        Args:
            mission_id (str): ID of the mission to be resumed.

        Returns:
            Whether the command was dispatched successfully.
        """
        res = self._post(
            self.fleet_url + "/v2/operations",
            {
                "id": uuid.uuid4().int,
                "jsonrpc": "2.0",
                "method": "resumeMission",
                "params": {"id": mission_id},
            },
        )
        return self._evaluate_jsonrpc_response(res, "resumeMission")

    def retry_mission(self, mission_id):
        """Trigger a retryMission RPC.

        Args:
            mission_id (str): ID of the mission to be retried.

        Returns:
            Whether the command was dispatched successfully.
        """
        res = self._post(
            self.fleet_url + "/v2/operations",
            {
                "id": uuid.uuid4().int,
                "jsonrpc": "2.0",
                "method": "retryMission",
                "params": {"id": mission_id},
            },
        )
        return self._evaluate_jsonrpc_response(res, "retryMission")

    def cancel_mission(self, mission_id):
        """Trigger a cancelMission RPC.

        Args:
            mission_id (str): ID of the mission to be cancelled.

        Returns:
            Whether the command was dispatched successfully.
        """
        res = self._post(
            self.fleet_url + "/v2/operations",
            {
                "id": uuid.uuid4().int,
                "jsonrpc": "2.0",
                "method": "cancelMission",
                "params": {"id": mission_id},
            },
        )
        return self._evaluate_jsonrpc_response(res, "cancelMission")

    def cancel_all_missions(self):
        """Query all missions and cancel them.

        Returns:
            (int, int): (Number of queried missions, number of missions successfully cancelled).
        """
        # NOTE(b-Tomas): If there are more than 100 missions to be returned in a query, the
        # response will include a "next" field with the URL to the next page.
        # Handling this paging was not implemented here because it is not expected to be needed.

        missions = []
        # For state in all states but CANCELLED, CANCELLING and SUCCEDED
        for state in (
            "ASSIGNED",
            "BLOCKED",
            "EXECUTING",
            "FAILED",
            "PAUSED",
            "QUEUED",
            "REASSIGNED",
            "RESTARTING",
            "REVOKED",
            "STARVED",
        ):
            res = self._get(
                self.fleet_url
                + f"/v2/missions/?fields=id,created,mission_status,name"
                + f"&ordering=-created&mission_status={state}",
                json=None,
            )
            success = self._evaluate_jsonrpc_response(res, "cancelMission")
            if success:
                [missions.append(entry) for entry in res.json().get("results", [])]

        cancelled_count = 0
        for mission in missions:
            if self.cancel_mission(mission.get("id", "")):
                cancelled_count += 1

        self.logger.info(
            f"Cancelled {cancelled_count} missions successfully out of "
            + f"{len(missions)} missions queried"
        )

        return (len(missions), cancelled_count)

    def pause_autonomy(self, otto_id):
        """Trigger a pauseAutonomy RPC.

        Args:
            otto_id (str): ID of the robot whose autonomy will be paused.

        Returns:
            Whether the command was dispatched successfully.
        """
        res = self._post(
            self.fleet_url + "/v2/operations",
            {
                "id": uuid.uuid4().int,
                "jsonrpc": "2.0",
                "method": "pauseRobot",
                "params": {"id": otto_id},
            },
        )
        return self._evaluate_jsonrpc_response(res, "pauseRobot")

    def resume_autonomy(self, otto_id):
        """Trigger a resumeAutonomy RPC.

        Args:
            otto_id (str): ID of the robot whose autonomy will be resumed.

        Returns:
            Whether the command was dispatched successfully.
        """
        res = self._post(
            self.fleet_url + "/v2/operations",
            {
                "id": uuid.uuid4().int,
                "jsonrpc": "2.0",
                "method": "resumeRobot",
                "params": {"id": otto_id},
            },
        )
        return self._evaluate_jsonrpc_response(res, "resumeRobot")

    def set_maintenance_mode(self, otto_id, maintenance):
        """Set a robot into/out of maintenance mode.

        Args:
            otto_id (str): ID of the robot to control.
            maintenance (bool): If True the robot will be put in maintenance mode, and will be
            taken out of maintenance mode if False.

        Returns:
            Whether the command was dispatched successfully.
        """
        res = self._post(
            self.fleet_url + "/v2/operations",
            {
                "id": uuid.uuid4().int,
                "jsonrpc": "2.0",
                "method": "setRobotMaintenanceMode",
                "params": {
                    "id": otto_id,
                    "maintenance": maintenance,
                },
            },
        )
        return self._evaluate_jsonrpc_response(res, "setRobotMaintenanceMode")

    def clear_payload(self, otto_id):
        """Clear the robot's payloads if any.

        Args:
            otto_id (str): ID of the robot to clear the payloads for via the FM.

        Returns:
            Whether the command was dispatched successfully.
        """
        res = self._post(
            self.fleet_url + "/v2/operations",
            {
                "id": uuid.uuid4().int,
                "jsonrpc": "2.0",
                "method": "setRobotPayload",
                "params": {"id": otto_id, "payload_id": None},
            },
        )
        return self._evaluate_jsonrpc_response(res, "setRobotPayload")

    def send_recipe(self, otto_id, recipe_id):
        """Request a robot to dispatch a recipe.

           Note that standalone recipes must be sent with the robot in maintenance mode.

        Args:
            otto_id (str): ID of the robot to execute the recipe.
            recipe_id (str): Recipe ID.

        Returns:
            Whether the command was dispatched successfully.
        """
        res = self._post(
            self.fleet_url + "/v2/operations",
            {
                "id": uuid.uuid4().int,
                "jsonrpc": "2.0",
                "method": "sendRobotRecipe",
                "params": {
                    "id": otto_id,
                    # This line is from the example. Place_id is not listed as required (red *)
                    # "place_id": "30c00c6b-0c65-4ac8-ae50-197108832274",
                    "recipe_id": recipe_id,
                },
            },
        )
        return self._evaluate_jsonrpc_response(res, "sendRobotRecipe")

    def set_availability(self, otto_id, is_available):
        """Set the robot as available / unavailable.

        Args:
            otto_id (str): ID of the robot to set as available/unavailable.
            is_available (bool): Whether the robot is available or not.

        Returns:
            Whether the command was dispatched successfully.
        """
        res = self._post(
            self.fleet_url + "/v2/operations",
            {
                "id": uuid.uuid4().int,
                "jsonrpc": "2.0",
                "method": "setRobotAvailability",
                "params": {"id": otto_id, "available": is_available},
            },
        )
        return self._evaluate_jsonrpc_response(res, "setRobotAvailability")

    def get_tasks(self, params=None):
        """Query a list of tasks with the specified parameters.

        Documentation can be found at file:///{...}/fleet_manager_offline_docs_v2.26/docs/fleet/public_api/v2.html#/Tasks/Mission_Task_list # noqa
        on the FM's offline docs.

        Args:
            params (dict, optional): Query parameters. Defaults to None.
            E.g. {"fields": "*", "mission": mission_id}

        Returns:
            A list of tasks.
        """
        params = params if params is not None else {}
        url = self.fleet_url + "/v2/tasks/?" + "&".join([f"{k}={v}" for k, v in params.items()])
        res = self._get(url=url, json=None)
        if res.headers.get("Content-Type").startswith("application/json"):
            return res.json()
        return None

    def _evaluate_jsonrpc_response(self, res, method):
        """Evaluate the success of a JsonRPC request. In case of an error, a message is logged.

        Args:
            res (Requests.response): Request's response.
            method (str): Used for logging. e.g. POST, GET.

        Returns:
            True if the response indicates a successful outcome.
        """
        try:
            if res.json().get("error"):
                self.logger.warn(f"<{method}> JsonRPC request failed: {res.json()}")
                return False
            if res.status_code >= 300:
                return False
            return True
        except Exception:
            # We got no JSON
            return False
