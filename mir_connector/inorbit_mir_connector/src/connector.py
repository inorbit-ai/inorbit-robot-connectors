# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytz
import math
from inorbit_connector.connector import Connector
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND
from inorbit_edge.robot import COMMAND_MESSAGE
from inorbit_edge.robot import COMMAND_NAV_GOAL
from .mir_api import MirApiV2
from .mir_api import MirWebSocketV2
from .mission import MirInorbitMissionTracking
from ..config.mir100_model import MiR100Config


# Publish updates every 1s
CONNECTOR_UPDATE_FREQ = 1

# Available MiR states to select via actions
MIR_STATE = {3: "READY", 4: "PAUSE", 11: "MANUALCONTROL"}


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
        if command_name == COMMAND_CUSTOM_COMMAND:
            self._logger.info(f"Received '{command_name}'!. {args}")
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
                        self._logger.error(f"Invalid `state_id` ({state_id})")
                        options["result_function"]("1")
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
            else:
                # Other kind if custom commands may be handled by the edge-sdk (e.g. user_scripts)
                # and not by the connector code itself
                # Do not return any result and leave it to the edge-sdk to handle it
                return
            # Return '0' for success
            options["result_function"]("0")
        elif command_name == COMMAND_NAV_GOAL:
            self._logger.info(f"Received '{command_name}'!. {args}")
            pose = args[0]
            self.mir_api.send_waypoint(pose)
        elif command_name == COMMAND_MESSAGE:
            msg = args[0]
            if msg == "inorbit_pause":
                self.mir_api.set_state(4)
            elif msg == "inorbit_resume":
                self.mir_api.set_state(3)

        else:
            self._logger.info(f"Received '{command_name}'!. {args}")

    def _connect(self) -> None:
        """Connect to the robot services and to InOrbit"""
        super()._connect()
        if self.ws_enabled:
            self.mir_ws.connect()

    def _disconnect(self):
        """Disconnect from any external services"""
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
        self._logger.debug(f"Publishing pose: {pose_data}")
        self.publish_pose(**pose_data)

        # publish odometry
        odometry = {
            "linear_speed": self.status["velocity"]["linear"],
            "angular_speed": math.radians(self.status["velocity"]["angular"]),
        }
        self._logger.debug(f"Publishing odometry: {odometry}")
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
        self._logger.debug(f"Publishing key values: {key_values}")
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
