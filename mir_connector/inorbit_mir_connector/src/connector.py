# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import logging
import uuid
import pytz
from time import sleep
import math
import os
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND
from inorbit_edge.robot import COMMAND_MESSAGE
from inorbit_edge.robot import COMMAND_NAV_GOAL
from inorbit_edge.robot import RobotSession
from inorbit_edge.video import OpenCVCamera
from .mir_api import MirApiV2
from .mir_api import MirWebSocketV2
from .mission import MirInorbitMissionTracking
from ..config.mir100_model import MiR100Config


# Publish updates every 1s
CONNECTOR_UPDATE_FREQ = 1

# Available MiR states to select via actions
MIR_STATE = {3: "READY", 4: "PAUSE", 11: "MANUALCONTROL"}


class Mir100Connector:
    """MiR100 connector.

    This class handles by-directional interaction between a MiR100 robot and
    the InOrbit platform using mainly the InOrbit python EdgeSDK.

    Arguments:
        robot_id (str): The ID of the MiR100 robot.
        config (MiR100Config): The configuration object for the MiR100 connector.
    """

    def __init__(self, robot_id: str, config: MiR100Config) -> None:
        """Initialize the MiR100 connector."""

        log_level = config.log_level.value
        self.logger = logging.getLogger(name=self.__class__.__name__)
        self.logger.setLevel(log_level)

        # Configure the connection to the robot
        self.mir_api = MirApiV2(
            mir_host_address=config.connector_config.mir_host_address,
            mir_username=config.connector_config.mir_username,
            mir_password=config.connector_config.mir_password,
            mir_host_port=config.connector_config.mir_host_port,
            mir_use_ssl=config.connector_config.mir_use_ssl,
            loglevel=log_level,
        )

        # Configure the ws connection to the robot
        self.mir_ws = MirWebSocketV2(
            mir_host_address=config.connector_config.mir_host_address,
            mir_ws_port=config.connector_config.mir_ws_port,
            mir_use_ssl=config.connector_config.mir_use_ssl,
            loglevel=log_level,
        )

        # Configure the timezone
        self.robot_tz_info = pytz.timezone("UTC")
        try:
            self.robot_tz_info = pytz.timezone(config.location_tz)
        except pytz.exceptions.UnknownTimeZoneError as ex:
            self.logger.error(
                f"Unknown timezone: '{config.location_tz}', defaulting to 'UTC'. {ex}"
            )

        # The `api_key` is obtained from the `INORBIT_KEY` environment variable
        # to avoid repeting it on the YAML configuration file. Consider adding
        # a 'common' section to be used by all connectors.
        robot_session_params = {
            "robot_id": robot_id,
            "robot_name": robot_id,
            "api_key": os.environ["INORBIT_KEY"],
            "robot_key": config.inorbit_robot_key,
            "use_ssl": False,
        }
        if "INORBIT_URL" in os.environ:
            robot_session_params["endpoint"] = os.environ["INORBIT_URL"]
        # Configure InOrbit session object
        self.inorbit_sess = RobotSession(**robot_session_params)
        self.inorbit_sess.connect()

        # Set up environment variables
        user_scripts_config = config.user_scripts.model_dump()
        for env_var_name, env_var_value in user_scripts_config.get("env_vars", {}).items():
            self.logger.info(f"Setting environment variable '{env_var_name}'")
            os.environ[env_var_name] = env_var_value

        # Get user_scripts path. The model will default the value to None, but the key always exists
        path = user_scripts_config.get("path")
        if path is None:
            path = f"~/.inorbit_connectors/connector-{robot_id}/local/"
        user_scripts_path = os.path.expanduser(path)
        # Create the user_scripts folder if it doesn't exist
        if not os.path.exists(user_scripts_path):
            self.logger.info(f"Creating user_scripts directory: {user_scripts_path}")
            os.makedirs(user_scripts_path, exist_ok=True)

        # Delegate script execution to the RobotSession
        # NOTE: this only supports bash execution (exec_name_regex is set to files with '.sh'
        # extension).
        # More script types can be supported, but right now is only limited to bash scripts
        self.logger.info(f"Registering user_scripts path: {user_scripts_path}")
        self.inorbit_sess.register_commands_path(user_scripts_path, exec_name_regex=r".*\.sh")

        self.inorbit_sess.register_command_callback(self.command_callback)

        # Set up camera feeds
        for idx, camera_config in enumerate(config.cameras):
            self.inorbit_sess.register_camera(str(idx), OpenCVCamera(**camera_config.model_dump()))

        # Set up InOrbit Mission Tracking
        self.mission_tracking = MirInorbitMissionTracking(
            mir_api=self.mir_api,
            inorbit_sess=self.inorbit_sess,
            robot_tz_info=self.robot_tz_info,
            loglevel=log_level,
            enable_io_mission_tracking=config.connector_config.enable_mission_tracking,
        )

    def command_callback(self, command_name, args, options):
        """Callback method for command messages.

        The callback signature is `callback(command_name, args, options)`

        Arguments:
            command_name -- identifies the specific mir_apicommand to be executed
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
        if command_name == COMMAND_CUSTOM_COMMAND:
            self.logger.info(f"Received '{command_name}'!. {args}")
            script_name = args[0]
            script_args = args[1]
            # TODO (Elvio): Needs to be re designed.
            # 1. script_name is not standarized at all
            # 2. Consider implementing a callback for handling mission specific commands
            # 3. Needs an interface for supporting mission related actions
            if script_name == "queue_mission" and script_args[0] == "--mission_id":
                self.mission_tracking.mir_mission_tracking_enabled = (
                    self.inorbit_sess.missions_module.executor.wait_until_idle(0)
                )
                self.mir_api.queue_mission(script_args[1])
            elif script_name == "run_mission_now" and script_args[0] == "--mission_id":
                self.mission_tracking.mir_mission_tracking_enabled = (
                    self.inorbit_sess.missions_module.executor.wait_until_idle(0)
                )
                self.mir_api.abort_all_missions()
                self.mir_api.queue_mission(script_args[1])
            elif script_name == "abort_missions":
                self.inorbit_sess.missions_module.executor.cancel_mission("*")
                self.mir_api.abort_all_missions()
            elif script_name == "set_state":
                if script_args[0] == "--state_id":
                    state_id = script_args[1]
                    if not state_id.isdigit() or int(state_id) not in MIR_STATE.keys():
                        self.logger.error(f"Invalid `state_id` ({state_id})")
                        options["result_function"]("1")
                        return
                    state_id = int(state_id)
                    self.logger.info(
                        f"Setting robot state to state {state_id}: {MIR_STATE[state_id]}"
                    )
                    self.mir_api.set_state(state_id)
                if script_args[0] == "--clear_error":
                    self.logger.info("Clearing error state")
                    self.mir_api.clear_error()
            elif script_name == "set_waiting_for" and script_args[0] == "--text":
                self.logger.info(f"Setting 'waiting for' value to {script_args[1]}")
                self.mission_tracking.waiting_for_text = script_args[1]
            else:
                # Other kind if custom commands may be handled by the edge-sdk (e.g. user_scripts)
                # and not by the connector code itself
                # Do not return any result and leave it to the edge-sdk to handle it
                return
            # Return '0' for success
            options["result_function"]("0")
        elif command_name == COMMAND_NAV_GOAL:
            self.logger.info(f"Received '{command_name}'!. {args}")
            pose = args[0]
            self.send_waypoint(pose)
        elif command_name == COMMAND_MESSAGE:
            msg = args[0]
            if msg == "inorbit_pause":
                self.mir_api.set_state(4)
            elif msg == "inorbit_resume":
                self.mir_api.set_state(3)

        else:
            self.logger.info(f"Received '{command_name}'!. {args}")
    
    def send_waypoint(self, pose):
        # TODO(b-Tomas): This is a poor, highly blocking implementation, only meant to be a patch
        mission_groups: list[dict] = self.mir_api.get_mission_groups()
        group = next((x for x in mission_groups if x["name"] == "inorbit testing"), None)
        if group is None:
            self.logger.error("Could not find mission group 'inorbit testing'")
            return

        mission_id = str(uuid.uuid4())
        self.mir_api.create_mission(
            group["guid"], "Move to waypoint", guid=mission_id, description="Mission created by InOrbit"
        )
        action_parameters = [
            {
                "value": v,
                "input_name": None,
                "guid": str(uuid.uuid4()),
                "id": k
            }
            for k, v in {
                "x": float(pose["x"]),
                "y": float(pose["y"]),
                "orientation": math.degrees(float(pose["theta"])),
                "distance_threshold": 0.2,
                "retries": 5,
            }.items()
        ]
        self.mir_api.add_action_to_mission("move_to_position", mission_id, action_parameters, 1)
        self.mir_api.queue_mission(mission_id)
        

    def start(self):
        """Run the main loop of the Connector"""

        self._should_run = True
        while self._should_run:
            sleep(CONNECTOR_UPDATE_FREQ)
            try:
                # TODO(Elvio): Move this logic to another class to make it easier to maintain and
                # scale in the future
                self.status = self.mir_api.get_status()
                # TODO(Elvio): Move this logic to another class to make it easier to maintain and
                # scale in the future
                self.metrics = self.mir_api.get_metrics()
            except Exception as ex:
                self.logger.error(f"Failed to get robot API data: {ex}")
                continue
            # publish pose
            pose_data = {
                "x": self.status["position"]["x"],
                "y": self.status["position"]["y"],
                "yaw": math.radians(self.status["position"]["orientation"]),
            }
            self.logger.debug(f"Publishing pose: {pose_data}")
            self.inorbit_sess.publish_pose(**pose_data)

            # publish odometry
            odometry = {
                "linear_speed": self.status["velocity"]["linear"],
                "angular_speed": math.radians(self.status["velocity"]["angular"]),
            }
            self.logger.debug(f"Publishing odometry: {odometry}")
            self.inorbit_sess.publish_odometry(**odometry)
            if self.inorbit_sess.missions_module.executor.wait_until_idle(0):
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
            self.logger.debug(f"Publishing key values: {key_values}")
            self.inorbit_sess.publish_key_values(key_values)

            # Reporting system stats
            # TODO(b-Tomas): Report more system stats

            cpu_usage = self.mir_ws.get_cpu_usage()
            disk_usage = self.mir_ws.get_disk_usage()
            memory_usage = self.mir_ws.get_memory_usage()
            self.inorbit_sess.publish_system_stats(
                cpu_load_percentage=cpu_usage,
                hdd_usage_percentage=disk_usage,
                ram_usage_percentage=memory_usage,
            )

            # publish mission data
            try:
                self.mission_tracking.report_mission(self.status, self.metrics)
            except Exception:
                self.logger.exception("Error reporting mission")

    def inorbit_connected(self):
        """Check if the InOrbit MQTT session is connected."""
        return self.inorbit_sess.client.is_connected()

    def stop(self):
        """Exit the Connector cleanly."""
        self._should_run = False
        self.mir_ws.disconnect()
        self.inorbit_sess.disconnect()
