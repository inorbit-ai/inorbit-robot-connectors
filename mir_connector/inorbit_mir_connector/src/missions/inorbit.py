# Wrappers around InOrbit APIs
import json
import logging
from datetime import datetime
from enum import Enum

import httpx
from inorbit_mir_connector.src.missions.datatypes import Pose
from inorbit_mir_connector.src.missions.datatypes import Robot
from inorbit_mir_connector.src.missions.mission import Mission
from inorbit_mir_connector.src.missions.mission import MissionTask


def current_timestamp_ms():
    """
    Return the current timestamp in UNIX-milliseconds for input to our APIs.
    """
    return int(datetime.now().timestamp() * 1000)


class MissionStatus(Enum):
    """
    Values for mission Status. They match the status used everywhere in our infra;
    see lib/status (STATUS dict).
    This type is an Enum to ensure typing.
    It's important that the `value` of the enums match those in STATUS dict.
    """

    ok = "OK"
    warn = "warn"
    error = "error"

    def __str__(self):
        """
        Custom serialization to use the exact string we use in our infra and APIs.
        """
        return self.value


class MissionState(Enum):
    """
    Values for mission States. They match our States from shared/missions.js, MISSION_STATES dict.
    This type is an Enum to ensure typing. Only some constants are added here: those we use from
    the API wrapper.
    It's important that the `value` of the enums match those in MISSION_STATES.
    """

    completed = "completed"
    in_progress = "in-progress"
    paused = "paused"
    abandoned = "abandoned"
    starting = "starting"

    def __str__(self):
        """
        Custom serialization to use the exact string we use in our infra and APIs.
        """
        return self.value


logger = logging.getLogger("executor")

# Id of the action to send a robot to a waypoint
ACTION_NAVIGATE_TO_ID = "NavigateTo-000000"
# id of the action to cancel robot navigation
ACTION_CANCEL_NAV_ID = "CancelNavGoal-000000"

# Special action parameter keys (see MissionDataResolver)
ARG_OPERATOR_SYMBOL = "_"
ARG_KEY_DATA = "_data"
ARG_KEY_ARGUMENTS = "_arguments"
ARG_KEY_EXPRESSION = "_expression"

# Constants for InOrbit REST API paths (and builders for
# parameterized API paths)


def build_mission_api_path(mission_id):
    return f"missions/{mission_id}"


def build_actions_api_path(robot_id):
    return f"robots/{robot_id}/actions"


def build_waypoints_api_path(robot_id):
    return f"robots/{robot_id}/navigation/waypoints"


def build_tags_api_path(robot_id):
    return f"robots/{robot_id}/tags"


def build_tag_api_path(robot_id, tag_id):
    return f"robots/{robot_id}/tags/{tag_id}"


def build_locks_api_path(robot_id):
    return f"robots/{robot_id}/lock"


def build_pose_api_path(robot_id):
    return f"robots/{robot_id}/localization/pose"


def build_expression_eval_api_path(robot_id):
    return f"expressions/robot/{robot_id}/eval"


class InOrbitAPI:
    HTTP_API_KEY_HEADER = "x-auth-inorbit-app-key"

    def __init__(self, base_url="https://api.inorbit.ai", api_key=None):
        logger.info("InOrbit API: " + base_url)
        self._base_url = base_url
        self._api_key = api_key

    @property
    def headers(self):
        headers = {}
        if self._api_key:
            headers[InOrbitAPI.HTTP_API_KEY_HEADER] = self._api_key
        return headers

    async def get(self, path):
        return httpx.get(f"{self._base_url}/{path}", headers=self.headers)

    async def post(self, path, body):
        return httpx.post(f"{self._base_url}/{path}", json=body, headers=self.headers)

    async def put(self, path, body=None):
        return httpx.put(f"{self._base_url}/{path}", json=body, headers=self.headers)

    async def delete(self, path, body=None):
        if not body:
            return httpx.delete(f"{self._base_url}/{path}", headers=self.headers)
        else:
            # httpx library does not allow sending a body payload in DELETE requests (as it appears
            # to be a non-recommended practice). Instead, se request() directly; which is equivalent
            return httpx.request(
                method="DELETE", url=f"{self._base_url}/{path}", json=body, headers=self.headers
            )


class MissionTrackingMission:
    """Wrapper for Mission Tracking API"""

    def __init__(self, mission: Mission, api: InOrbitAPI):
        self._id = mission.id
        self._api = api
        self._mission = mission

    @property
    def id(self):
        return self._id

    @property
    def robot_id(self):
        return self._mission.robot_id

    async def start(self, is_resume=False):
        """
        Starts a new Mission in Mission Tracking API and marks it as in progress.
        send is_resume=True if the mission was paused and its execution is being resumed
        """
        try:
            req = {
                "state": str(MissionState.starting),
                "inProgress": False,
            }
            if not is_resume:
                req["startTs"] = current_timestamp_ms()
            if self._mission.arguments:
                req["arguments"] = self._mission.arguments
            r = await self._api.put(build_mission_api_path(self.id), req)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"Error marking mission as started in mission-tracking {e}")
            return False

    async def mark_in_progress(self):
        """
        Marks a mission as in progress on Mission Tracking API.
        """
        try:
            req = {
                "state": str(MissionState.in_progress),
                "inProgress": True,
            }
            r = await self._api.put(build_mission_api_path(self.id), req)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"Error marking mission as in-progress in mission-tracking {e}")
            return False

    async def get_mission(self):
        """
        Fetches the current mission state. Note that the mission may be changing through Mission
        Tracking service from updates sent from the robot or other sources.
        """
        try:
            r = await self._api.get(build_mission_api_path(self.id))
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"Error fetching mission state {e}")
            # TODO count this error for metrics
            return False

    def _build_tasks_list(self):
        return [t.model_dump(mode="json", by_alias=True) for t in self._mission.tasks_list]

    def _find_current_task_id(self):
        current_task: MissionTask = next(
            (task for task in self._mission.tasks_list if not task.completed), None
        )
        return current_task.task_id if current_task else None

    async def completed(self):
        """Marks the mission as Completed in Mission Tracking API"""
        try:
            req = {
                "state": str(MissionState.completed),
                "inProgress": False,
                "tasks": self._build_tasks_list(),
                "endTs": current_timestamp_ms(),
            }
            r = await self._api.put(build_mission_api_path(self.id), req)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"Error marking mission as completed in mission-tracking {e}")
            return False

    async def pause(self):
        """Marks the mission as paused in Mission Tracking API"""
        try:
            req = {
                "state": str(MissionState.paused),
                "inProgress": True,
                "tasks": self._build_tasks_list(),
            }
            r = await self._api.put(build_mission_api_path(self.id), req)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"Error marking mission as paused in mission-tracking {e}")
            return False

    async def abort(self, status: MissionStatus = MissionStatus.error):
        """Marks the mission as Aborted in Mission Tracking API"""
        try:
            req = {
                # NOTE(herchu) State could be "aborted" but we have not defined it in
                # https://docs.google.com/document/d/16KxmbmkiKhZ1IU_zkorJzZscMWFU2FrIJoTlenM8gwY ,
                # so until then we use the one currently mapped from Actionlib's "ABORTED=4"
                "state": str(MissionState.abandoned),
                "inProgress": False,
                "tasks": self._build_tasks_list(),
                "status": str(status),
                "endTs": current_timestamp_ms(),
            }
            await self._api.put(build_mission_api_path(self.id), req)
            return True
        except Exception as e:
            logger.warning(f"Error marking mission as aborted in mission-tracking {e}")
            return False

    async def report_tasks(self):
        """Updates the "tasks" list of the mission in Mission Tracking."""
        try:
            # NOTE(herchu) Mission Tracking API has at least some support for auto-updating
            # percentages based on completed tasks. Some customers want to report their own
            # completion percentage (e.g. Karcher even if they do not use this executor).
            # We should test if updating percentages when completing tasks work in MT API service,
            # and if it does, remove it from here. Consider also making it optional, ie. a flag
            # from configuration and for the runtime options of this mission.
            tasks = self._build_tasks_list()
            req = {"tasks": tasks}
            current_task_id = self._find_current_task_id()
            if current_task_id:
                req["currentTaskId"] = current_task_id
            await self._api.put(build_mission_api_path(self.id), req)
            return True
        except Exception as e:
            logger.warning(f"Error reporting tasks in mission-tracking {e}")
            return False

    async def add_data(self, data):
        """Adds keys to the "data" field of a mission in Mission Tracking."""
        try:
            req = {"data": data}
            await self._api.put(build_mission_api_path(self.id), req)
            return True
        except Exception as e:
            logger.warning(f"Error sending mission data to mission-tracking {e}")
            return False

    async def resolve_arguments(self, arguments):
        return await MissionDataResolver(arguments, self._mission, self).resolve()


class MissionDataResolver:
    """
    This object "resolves" any operator field in a data object, e.g. { _data: "key" } or
    { _argument: "key" }, by replacing those objects by the data or argument value. If necessary,
    the current mission state is retrieved from Mission Tracking API.
    This resolving is used for RunAction nodes, which can take elements from the mission data
    or arguments; but we can use them in other places later.

    TODO Expressions evaluation is not implemented
    """

    def __init__(self, data_object, mission, mt: MissionTrackingMission):
        self._data = data_object
        self._mission = mission
        self._mt = mt

    async def resolve(self):
        """
        Resolves the data object, fetching current mission if necessary from Mission Tracking API.
        It returns either the same data object received in the constructor, or a fresh new copy
        if there were elements to replace (the data object is never modified)
        """
        [data_keys, argument_keys, expressions] = self.collect_keys()
        if len(expressions):
            # TODO implement this! Code is still incomplete
            raise Exception("Support for _expression is not yet implemented")

        if len(data_keys) + len(argument_keys) + len(expressions) == 0:
            return self._data  # Nothing to do, save all work below

        data_values = {}
        argument_values = self._mission.arguments or {}
        if len(data_keys):
            # Retrieve mission, and replace any { _data: <keyName> } by its value
            logger.debug(f"Retrieving mission state to resolve action data arguments: {data_keys}")
            current_mission = await self._mt.get_mission()
            data_values = (current_mission and current_mission["data"]) or {}

        return self.build_resolved_data(data_values, argument_values)

    def build_resolved_data(self, data_values, argument_values):
        """
        Returns a new 'data' object, replacing _data, _arguments keys by their value (already
        retrieved, in dictionaries data_values and argument_values)
        """

        def recursively_replace_keys(obj):
            if not obj:
                return obj
            key = self._is_operator_obj(obj)
            if key:  # This is an operator, e.g. _data or _arguments,
                if key == ARG_KEY_DATA:
                    return data_values.get(obj[key], None)
                elif key == ARG_KEY_ARGUMENTS:
                    return argument_values.get(obj[key], None)
                elif key == ARG_KEY_EXPRESSION:
                    raise Exception("Evaluating _expression is not implemented")
                else:
                    raise Exception(f"Unsupported operator key {key}")
            elif type(obj) == dict:  # recurse into sub-objects.
                d = {}
                for k, v in obj.items():
                    d[k] = recursively_replace_keys(v)
                return d
            else:
                return obj

        return recursively_replace_keys(self._data)

    def collect_keys(self):
        """
        Collects any varaibles and expressions from the data object. It returns a 3 element
        tuple with:
         - All keys used in _data elements
         - All keys used in _arguments elements
         - All _expressions to evaluate (Even if evaluation is still TODO)
        """
        expressions = set()
        data_keys = set()
        argument_keys = set()
        # Recursively collect all _data, _arguments or _expression keys. In this way we need
        # if it is necessary to retrieve the current mission state or not

        def recursively_collect_keys(obj):
            if not obj:
                return
            key = self._is_operator_obj(obj)
            if key:  # This is an operator, e.g. _data or _arguments,
                if key == ARG_KEY_DATA:
                    data_keys.add(obj[key])
                elif key == ARG_KEY_ARGUMENTS:
                    argument_keys.add(obj[key])
                elif key == ARG_KEY_EXPRESSION:
                    expressions.add(obj[key])
                else:
                    raise Exception(f"Unsupported operator key {key}")
            elif type(obj) == dict:  # recurse into sub-objects
                for sub_obj in obj.values():
                    recursively_collect_keys(sub_obj)

        recursively_collect_keys(self._data)
        return [data_keys, argument_keys, expressions]

    def _is_operator_obj(self, obj):
        """
        Tells is a sub-object is an "operator", such as `{ _data: "arg" }`. Only objects with
        one key, starting with "_", are considered operators for now. It returns the key name,
        or None.
        """
        # TODO better validation and error reporting, e.g. reject if there are multiple keys
        # with "_"
        keys = list(obj.keys()) if type(obj) == dict else []
        if len(keys) == 1 and keys[0].startswith(ARG_OPERATOR_SYMBOL):
            return keys[0]
        else:
            return None


class RobotApi:
    """Wrapper for Robot APIs"""

    def __init__(self, robot_id: Robot, api: InOrbitAPI):
        self._robot_id = robot_id.id
        self._api = api

    @property
    def robot_id(self):
        return self._robot_id

    async def execute_action(self, action_id: str, arguments):
        req = {"actionId": action_id, "parameters": arguments if arguments is not None else {}}
        try:
            resp = await self._api.post(build_actions_api_path(self.robot_id), req)
            respData = None
            respData = resp.json()
        except Exception as e:
            raise Exception("Error executing action: " + str(e))
        if resp.status_code == 200:
            return respData
        else:
            error_msg = "Error executing action"
            # we cannot guarantee the error is a proper JSON object
            if respData and "error" in respData:
                error_msg += ": " + respData["error"]
            if respData and "validations" in respData:
                error_msg += " - " + json.dumps(respData["validations"])
            else:
                logger.warning("Cannot parse error execution message")
            raise Exception(error_msg)

    async def goto_waypoint(self, waypoint: Pose):
        req = {
            "waypoints": [
                {
                    "x": waypoint.x,
                    "y": waypoint.y,
                    "theta": waypoint.theta,
                    "frameId": waypoint.frame_id,
                }
            ]
        }
        await self._api.post(build_waypoints_api_path(self.id), req)

    async def get_pose(self):
        r = await self._api.get(build_pose_api_path(self.id))
        pose = r.json()
        return Pose(x=pose["x"], y=pose["y"], theta=pose["theta"], frame_id=pose["frameId"])

    async def evaluate_expression(self, expression):
        body = dict(expression=expression)
        r = await self._api.post(build_expression_eval_api_path(self.robot_id), body)
        res = r.json()
        if not res["success"]:
            raise Exception(f"Error evaluating expression ({expression}): {res.get('message')}")
        return res["value"]

    async def add_tag(self, tag_id):
        """Adds a tag to a robot"""
        body = dict(id=tag_id)
        resp = await self._api.post(build_tags_api_path(self.robot_id), body)
        if resp.status_code == 201:
            return True
        else:
            try:
                error = resp.json()
            except Exception:
                error = "<no data>"
            logger.error(
                f"Error {resp.status_code} adding tag {tag_id} to robot {self.robot_id}: {error}"
            )
            raise Exception("Error applying robot tags")

    async def remove_tag(self, tag_id):
        """Removes a tag from a robot"""
        resp = await self._api.delete(build_tag_api_path(self.robot_id), tag_id)
        if resp.status_code == 204:
            return True
        else:
            try:
                error = resp.json()
            except Exception:
                error = "<no data>"
            logger.error(
                f"Error {resp.status_code} removing tag {tag_id} from robot {self.robot_id}: "
                f"{error}"
            )
            raise Exception("Error applying robot tags")

    async def lock_robot(self, soft=False):
        """Locks a robot (or renews an existing lock)"""
        body = {"soft": True} if soft else None
        resp = await self._api.put(build_locks_api_path(self.robot_id), body)
        if resp.status_code == 201:
            return True
        else:
            try:
                error = resp.json()
            except Exception:
                error = "<no data>"
            logger.error(f"Error {resp.status_code} locking robot {self.robot_id}: {error}")
            raise Exception("Error locking robot")

    async def unlock_robot(self, soft=False):
        """Unlocks a robot (breaking only one's lock or someone elses)"""
        body = {"soft": True} if soft else None
        resp = await self._api.delete(build_locks_api_path(self.robot_id), body)
        if resp.status_code == 204:
            return True
        else:
            try:
                error = resp.json()
            except Exception:
                error = "<no data>"
            logger.error(f"Error {resp.status_code} unlocking robot {self.robot_id}: {error}")
            raise Exception("Error unlocking robot")


class RobotApiFactory:
    def __init__(self, api: InOrbitAPI):
        self._api = api

    def build(self, robot_id: str):
        return RobotApi(Robot(id=robot_id), self._api)
