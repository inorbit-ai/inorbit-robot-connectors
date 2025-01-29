# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import asyncio
from enum import Enum
import json
from time import sleep
from inorbit_mir_connector.src.missions_exec.datatypes import MissionExecuteRequest
from inorbit_mir_connector.src.missions_exec.executor import MissionsExecutor
from inorbit_mir_connector.src.missions.inorbit import InOrbitAPI
from pydantic import ValidationError
import pytz
import math
import uuid
from threading import Thread
from inorbit_connector.connector import Connector
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND
from inorbit_edge.robot import COMMAND_MESSAGE
from inorbit_edge.robot import COMMAND_NAV_GOAL
from inorbit_mir_connector import get_module_version
from .mir_api import MirApiV2
from .mir_api import MirWebSocketV2
from .mission import MirInorbitMissionTracking
from ..config.mir100_model import MiR100Config


# Available MiR states to select via actions
MIR_STATE = {3: "READY", 4: "PAUSE", 11: "MANUALCONTROL"}

# Connector missions group name
# If a group with this name exists it will be used, otherwise it will be created
# At shutdown, the group will be deleted
MIR_INORBIT_MISSIONS_GROUP_NAME = "InOrbit Temporary Missions Group"
# Distance threshold for MiR move missions in meters
# Used in waypoints sent via missions when the WS interface is not enabled
MIR_MOVE_DISTANCE_THRESHOLD = 0.1

# Remove missions created in the temporary missions group every 12 hours
MISSIONS_GARBAGE_COLLECTION_INTERVAL_SECS = 12 * 60 * 60


class InOrbitCommands(Enum):
    """InOrbit commands that are handled by the MiR100 connector."""

    INORBIT_MISSION_EXECUTE = "executeMissionAction"
    INORBIT_MISSION_CANCEL = "cancelMissionAction"
    INORBIT_MISSION_UPDATE = "updateMissionAction"
    # TODO(b-Tomas): Add all other commands handled in ._inorbit_command_handler()


# TODO(b-Tomas): Rename all MiR100* to MiR* to make more generic
class Mir100Connector(Connector):
    """MiR100 connector.

    This class handles by-directional interaction between a MiR100 robot and
    the InOrbit platform using mainly the InOrbit python EdgeSDK.

    Arguments:
        robot_id (str): The ID of the MiR100 robot.
        config (MiR100Config): The configuration object for the MiR100 connector.
    """

    def __init__(self, robot_id: str, config: MiR100Config) -> None:
        """Initialize the MiR100 connector."""
        super().__init__(
            robot_id=robot_id,
            config=config,
            register_user_scripts=True,
            create_user_scripts_dir=True,
        )
        self.config = config

        # Configure the connection to the robot
        self.mir_api = MirApiV2(
            mir_host_address=config.connector_config.mir_host_address,
            mir_username=config.connector_config.mir_username,
            mir_password=config.connector_config.mir_password,
            mir_host_port=config.connector_config.mir_host_port,
            mir_use_ssl=config.connector_config.mir_use_ssl,
            loglevel=config.log_level.value,
        )

        # Configure the ws connection to the robot
        self.ws_enabled = config.connector_config.mir_enable_ws
        if self.ws_enabled:
            self.mir_ws = MirWebSocketV2(
                mir_host_address=config.connector_config.mir_host_address,
                mir_ws_port=config.connector_config.mir_ws_port,
                mir_use_ssl=config.connector_config.mir_use_ssl,
                loglevel=config.log_level.value,
            )

        # Configure the timezone
        self.robot_tz_info = pytz.timezone("UTC")
        try:
            self.robot_tz_info = pytz.timezone(config.location_tz)
        except pytz.exceptions.UnknownTimeZoneError as ex:
            self._logger.error(
                f"Unknown timezone: '{config.location_tz}', defaulting to 'UTC'. {ex}"
            )

        # Set up InOrbit Mission Tracking
        self.mission_tracking = MirInorbitMissionTracking(
            mir_api=self.mir_api,
            inorbit_sess=self._robot_session,
            robot_tz_info=self.robot_tz_info,
            loglevel=config.log_level.value,
            enable_io_mission_tracking=config.connector_config.enable_mission_tracking,
        )

        # InOrbit missions executor
        self.missions_executor = MissionsExecutor(
            mir_api=self.mir_api,
            inorbit_api=InOrbitAPI(
                base_url=self._robot_session.inorbit_rest_api_endpoint, api_key=config.api_key
            ),
            loglevel="DEBUG",  # config.log_level.value,
        )
        asyncio.run(self.missions_executor.start())

        # Get or create the required missions and mission groups
        self.setup_connector_missions()

    def _inorbit_command_handler(self, command_name, args, options):
        """Callback method for command messages.

        The callback signature is `callback(command_name, args, options)`

        Arguments:
            command_name -- identifies the specific command to be executed
            args -- is an ordered list with each argument as an entry. Each
                element of the array can be a string or an object, depending on
                the definition of the action.
            options -- is a dictionary that includes:
                - `result_function` can be called to report command execution result.
                It has the following signature: `result_function(return_code)`.
                - `progress_function` can be used to report command output and has
                the following signature: `progress_function(output, error)`.
                - `metadata` is reserved for the future and will contains additional
                information about the received command request.
        """
        self._logger.info(f"Received '{command_name}'!. {args}")
        if command_name == COMMAND_CUSTOM_COMMAND:
            if len(args) < 2:
                self._logger.error("Invalid number of arguments: ", args)
                options["result_function"](
                    "1", execution_status_details="Invalid number of arguments"
                )
                return
            script_name = args[0]
            script_args = args[1]
            # TODO (Elvio): Needs to be re designed.
            # 1. script_name is not standarized at all
            # 2. Consider implementing a callback for handling mission specific commands
            # 3. Needs an interface for supporting mission related actions
            if script_name == "queue_mission" and script_args[0] == "--mission_id":
                self.mission_tracking.mir_mission_tracking_enabled = (
                    self._robot_session.missions_module.executor.wait_until_idle(0)
                )
                self.mir_api.queue_mission(script_args[1])
            elif script_name == "run_mission_now" and script_args[0] == "--mission_id":
                self.mission_tracking.mir_mission_tracking_enabled = (
                    self._robot_session.missions_module.executor.wait_until_idle(0)
                )
                self.mir_api.abort_all_missions()
                self.mir_api.queue_mission(script_args[1])
            elif script_name == "abort_missions":
                self._robot_session.missions_module.executor.cancel_mission("*")
                self.mir_api.abort_all_missions()
            elif script_name == "set_state":
                if script_args[0] == "--state_id":
                    state_id = script_args[1]
                    if not state_id.isdigit() or int(state_id) not in MIR_STATE.keys():
                        error = f"Invalid `state_id` '{state_id}'"
                        self._logger.error(error)
                        options["result_function"]("1", execution_status_details=error)
                        return
                    state_id = int(state_id)
                    self._logger.info(
                        f"Setting robot state to state {state_id}: {MIR_STATE[state_id]}"
                    )
                    self.mir_api.set_state(state_id)
                if script_args[0] == "--clear_error":
                    self._logger.info("Clearing error state")
                    self.mir_api.clear_error()
            elif script_name == "set_waiting_for" and script_args[0] == "--text":
                self._logger.info(f"Setting 'waiting for' value to {script_args[1]}")
                self.mission_tracking.waiting_for_text = script_args[1]
            elif script_name == "localize":
                # The localize command sets the robot's position and current map
                # The expected arguments are "x" and "y" in meters and "orientation" in degrees, as
                # in MiR Fleet, and "map_id" as the target map in MiR Fleet, which matches the
                # uploaded "frame_id" in InOrbit
                if (
                    len(script_args) == 8
                    and script_args[0] == "--x"
                    and script_args[2] == "--y"
                    and script_args[4] == "--orientation"
                    and script_args[6] == "--map_id"
                ):
                    status = {
                        "position": {
                            "x": float(script_args[1]),
                            "y": float(script_args[3]),
                            "orientation": float(script_args[5]),
                        },
                        "map_id": script_args[7],
                    }
                    self._logger.info(f"Changing map to {script_args[7]}")
                    self.mir_api.set_status(status)
                else:
                    self._logger.error("Invalid arguments for 'localize' command")
                    options["result_function"]("1", execution_status_details="Invalid arguments")
                    return

            # InOrbit commands
            elif script_name == InOrbitCommands.INORBIT_MISSION_EXECUTE.value:
                mission_id = self._get_run_script_argument("missionId", list(script_args))
                mission_definition = self._get_run_script_argument(
                    "missionDefinition", list(script_args)
                )
                mission_args = self._get_run_script_argument("missionArgs", list(script_args))
                mission_options = self._get_run_script_argument("options", list(script_args))

                try:
                    mission_execute_request = MissionExecuteRequest(
                        missionId=mission_id,
                        robotId=self.robot_id,
                        missionDefinition=json.loads(mission_definition),
                        missionArgs=json.loads(mission_args),
                        options=json.loads(mission_options),
                    )
                except ValidationError as e:
                    self._logger.error(f"Invalid mission definition. {e}")
                    return options["result_function"]("1", "Invalid mission definition.")

                # TOOD(b-Tomas): Call the result function with the execution result
                asyncio.run(self.missions_executor.execute_mission(mission_execute_request))

            elif script_name == InOrbitCommands.INORBIT_MISSION_CANCEL.value:
                self._logger.warning(f"{script_name} not implemented")
            elif script_name == InOrbitCommands.INORBIT_MISSION_UPDATE.value:
                self._logger.warning(f"{script_name} not implemented")

            else:
                # Other kind if custom commands may be handled by the edge-sdk (e.g. user_scripts)
                # and not by the connector code itself
                # Do not return any result and leave it to the edge-sdk to handle it
                return
            # Return '0' for success
            options["result_function"]("0")
        elif command_name == COMMAND_NAV_GOAL:
            pose = args[0]
            self.send_waypoint_over_missions(pose)
        elif command_name == COMMAND_MESSAGE:
            msg = args[0]
            if msg == "inorbit_pause":
                self.mir_api.set_state(4)
            elif msg == "inorbit_resume":
                self.mir_api.set_state(3)
        else:
            self._logger.info(f"Received unknown command '{command_name}'!. {args}")

    @staticmethod
    def _get_run_script_argument(arg_name: str, script_args: list) -> dict:
        """
        Retrieves the argument value of a given argument name from a list
        of script arguments.

        Args:
            arg_name (str): The name of the argument to retrieve its value.
            script_args (list): A list of script arguments in the format
            ["arg1", "value1", "arg2", "value2"]

        Returns:
            dict: A dictionary containing the argument name and value if found, otherwise None.
        """
        try:
            arg_name_index = script_args.index(arg_name)
        except ValueError as e:
            return None
        if arg_name_index is not None:
            return script_args[arg_name_index + 1]
        return None

    def _connect(self) -> None:
        """Connect to the robot services and to InOrbit"""
        super()._connect()
        # If enabled, initiate the websockets client
        if self.ws_enabled:
            self.mir_ws.connect()
        # Start garbage collection for missions
        # Running with daemon=True will kill the thread when the main thread is done executing
        Thread(target=self._missions_garbage_collector, daemon=True).start()

    def _disconnect(self):
        """Disconnect from any external services"""
        self.cleanup_connector_missions()
        super()._disconnect()
        if self.ws_enabled:
            self.mir_ws.disconnect()

    def _execution_loop(self):
        """The main execution loop for the connector"""

        try:
            # TODO(Elvio): Move this logic to another class to make it easier to maintain and
            # scale in the future
            self.status = self.mir_api.get_status()
            # TODO(Elvio): Move this logic to another class to make it easier to maintain and
            # scale in the future
            self.metrics = self.mir_api.get_metrics()
        except Exception as ex:
            self._logger.error(f"Failed to get robot API data: {ex}")
            return
        # publish pose
        pose_data = {
            "x": self.status["position"]["x"],
            "y": self.status["position"]["y"],
            "yaw": math.radians(self.status["position"]["orientation"]),
            "frame_id": self.status["map_id"],
        }
        # self._logger.debug(f"Publishing pose: {pose_data}")
        self.publish_pose(**pose_data)

        # publish odometry
        odometry = {
            "linear_speed": self.status["velocity"]["linear"],
            "angular_speed": math.radians(self.status["velocity"]["angular"]),
        }
        # self._logger.debug(f"Publishing odometry: {odometry}")
        self._robot_session.publish_odometry(**odometry)
        if self._robot_session.missions_module.executor.wait_until_idle(0):
            mode_text = self.status["mode_text"]
            state_text = self.status["state_text"]
            mission_text = self.status["mission_text"]
        else:
            mode_text = "Mission"
            state_text = "Executing"
            mission_text = "Mission"
        # publish key values
        # TODO(Elvio): Move key values to a "values.py" and represent them with constants
        key_values = {
            "connector_version": get_module_version(),
            "battery percent": self.status["battery_percentage"],
            "battery_time_remaining": self.status["battery_time_remaining"],
            "uptime": self.status["uptime"],
            "localization_score": self.metrics.get("mir_robot_localization_score"),
            "robot_name": self.status["robot_name"],
            "errors": self.status["errors"],
            "distance_to_next_target": self.status["distance_to_next_target"],
            "mission_text": mission_text,
            "state_text": state_text,
            "mode_text": mode_text,
            "robot_model": self.status["robot_model"],
            "waiting_for": self.mission_tracking.waiting_for_text,
        }
        # self._logger.debug(f"Publishing key values: {key_values}")
        self._robot_session.publish_key_values(key_values)

        # Reporting system stats
        # TODO(b-Tomas): Report more system stats

        if self.ws_enabled:
            cpu_usage = self.mir_ws.get_cpu_usage()
            disk_usage = self.mir_ws.get_disk_usage()
            memory_usage = self.mir_ws.get_memory_usage()
            self._robot_session.publish_system_stats(
                cpu_load_percentage=cpu_usage,
                hdd_usage_percentage=disk_usage,
                ram_usage_percentage=memory_usage,
            )

        # publish mission data
        try:
            self.mission_tracking.report_mission(self.status, self.metrics)
        except Exception:
            self._logger.exception("Error reporting mission")

    def send_waypoint_over_missions(self, pose):
        """Use the connector's mission group to create a move mission to a designated pose."""
        mission_id = str(uuid.uuid4())
        connector_type = self.config.connector_type
        firmware_version = self.config.connector_config.mir_firmware_version

        self.mir_api.create_mission(
            group_id=self.tmp_missions_group_id,
            name="Move to waypoint",
            guid=mission_id,
            description="Mission created by InOrbit",
        )
        param_values = {
            "x": float(pose["x"]),
            "y": float(pose["y"]),
            "orientation": math.degrees(float(pose["theta"])),
            "distance_threshold": MIR_MOVE_DISTANCE_THRESHOLD,
        }
        if connector_type == "MiR100" and firmware_version == "v2":
            param_values["retries"] = 5
        elif connector_type == "MiR250" and firmware_version == "v3":
            param_values["blocked_path_timeout"] = 60.0
        else:
            self._logger.warning(
                f"Not supported connector type and firmware version combination for waypoint "
                f"navigation: {connector_type} {firmware_version}. Will attempt to send waypoint "
                "based on firmware version."
            )
            if firmware_version == "v2":
                param_values["retries"] = 5
            else:
                param_values["blocked_path_timeout"] = 60.0

        action_parameters = [
            {"value": v, "input_name": None, "guid": str(uuid.uuid4()), "id": k}
            for k, v in param_values.items()
        ]
        self.mir_api.add_action_to_mission(
            action_type="move_to_position",
            mission_id=mission_id,
            parameters=action_parameters,
            priority=1,
        )
        self.mir_api.queue_mission(mission_id)

    def setup_connector_missions(self):
        """Find and store the required missions and mission groups, or create them if they don't
        exist."""
        self._logger.info("Setting up connector missions")
        # Find or create the missions group
        mission_groups: list[dict] = self.mir_api.get_mission_groups()
        group = next(
            (x for x in mission_groups if x["name"] == MIR_INORBIT_MISSIONS_GROUP_NAME), None
        )
        self.tmp_missions_group_id = group["guid"] if group is not None else str(uuid.uuid4())
        if group is None:
            self._logger.info(f"Creating mission group '{MIR_INORBIT_MISSIONS_GROUP_NAME}'")
            group = self.mir_api.create_mission_group(
                feature=".",
                icon=".",
                name=MIR_INORBIT_MISSIONS_GROUP_NAME,
                priority=0,
                guid=self.tmp_missions_group_id,
            )
            self._logger.info(f"Mission group created with guid '{self.tmp_missions_group_id}'")
        else:
            self._logger.info(
                f"Found mission group '{MIR_INORBIT_MISSIONS_GROUP_NAME}' with "
                f"guid '{self.tmp_missions_group_id}'"
            )

    def cleanup_connector_missions(self):
        """Delete the missions group created at startup"""
        self._logger.info("Cleaning up connector missions")
        self._logger.info(f"Deleting missions group {self.tmp_missions_group_id}")
        self.mir_api.delete_mission_group(self.tmp_missions_group_id)

    def _delete_unused_missions(self):
        """Delete all missions definitions in the temporary group that are not associated to
        pending or executing missions"""
        try:
            mission_defs = self.mir_api.get_mission_group_missions(self.tmp_missions_group_id)
            missions_queue = self.mir_api.get_missions_queue()
            # Do not delete definitions of missions that are pending or executing
            protected_mission_defs = [
                self.mir_api.get_mission(mission["id"])["mission_id"]
                for mission in missions_queue
                if mission["state"].lower() in ["pending", "executing"]
            ]
            # Delete the missions definitions in the temporary group that are not
            # associated to pending or executing missions
            missions_to_delete = [
                mission["guid"]
                for mission in mission_defs
                if mission["guid"] not in protected_mission_defs
            ]
        except Exception as ex:
            self._logger.error(f"Failed to get missions for garbage collection: {ex}")
            self.start_missions_garbage_collector()
            return

        for mission_id in missions_to_delete:
            try:
                self._logger.info(f"Deleting mission {mission_id}")
                self.mir_api.delete_mission_definition(mission_id)
            except Exception as ex:
                self._logger.error(f"Failed to delete mission {mission_id}: {ex}")

    def _missions_garbage_collector(self):
        """Delete unused missions preiodically"""
        while True:
            sleep(MISSIONS_GARBAGE_COLLECTION_INTERVAL_SECS)
            self._delete_unused_missions()
