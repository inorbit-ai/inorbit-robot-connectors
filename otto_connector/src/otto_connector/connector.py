# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""
OTTO to InOrbit Connector.

It connects a fleet of OTTO robots to InOrbit's platform for observability and operation
using InOrbit's Python Edge SDK: https://github.com/inorbit-ai/edge-sdk-python
"""

import logging
import re
import subprocess
from multiprocessing import Manager, Process
from threading import Thread
from time import sleep

import pytz
from autobahn.twisted.wamp import ApplicationRunner
from inorbit_edge.robot import (
    COMMAND_CUSTOM_COMMAND,
    COMMAND_MESSAGE,
    RobotSessionFactory,
    RobotSessionPool,
)
from inorbit_edge.video import OpenCVCamera
from twisted.internet import ssl

from .http_client import HTTPClient
from .robot import OttoRobot
from .values import InOrbitDataKeys
from .wamp_client import WampClient

# Publish updates every 1s
CONNECTOR_UPDATE_FREQ = 1

# Wait 5 seconds after executing a recipe to get out of Maintenance mode
RECIPE_EXECUTION_WAIT_DEFAULT = 5


class OTTOConnector:
    """
    OTTO connector class.

    Provides the methods to listen to and control an OTTO robot from InOrbit by talking to OTTO's
    Fleet Manager (FM).
    """

    def __init__(
        self,
        fleet_manager_address,
        inorbit_api_key,
        location_tz,
        user_scripts_dir,
        robot_definitions=None,
        loglevel="INFO",
        inorbit_api_use_ssl=True,
        inorbit_api_endpoint=None,
    ):
        """
        Build the connector: launch a Robot Session on the Edge SDK and connect to the FM.

        Args:
            fleet_manager_address (str): IP address of OTTO's Fleet Manager.
            inorbit_api_key (str): API key for authenticating against InOrbit Cloud services.
            location_tz (str): Timezone code compatible with the Pytz Python library.
            robot_definitions(list[str]): List of definitions (inorbit_id, otto_id, etc.) for
            the robots to connect.
            loglevel (str): Connector's logging level (one of  DEBUG, INFO, WARNING, ERROR,
            CRITICAL). INFO by default.
            inorbit_api_use_ssl (bool): Configures MQTT client to use SSL. Defaults: True.
            inorbit_api_endpoint (str): InOrbit's URL. Points to https://control.inorbit.ai by
            default.
        """
        self.logger = logging.getLogger(name=self.__class__.__name__)
        self.logger.setLevel(loglevel)

        # List of robot definition objects with the following schema:
        # {
        #   "inorbit_id": str,
        #   "otto_id": str,
        #   "camera_url": (optional) str,
        # }
        self.robot_definitions = robot_definitions if robot_definitions is not None else []
        self.logger.debug(f"Robot Definitions: {self.robot_definitions}")

        # Set local timezone
        try:
            self.robot_tz_info = pytz.timezone(location_tz)
        except pytz.exceptions.UnknownTimeZoneError as ex:
            self.logger.error(f"Unknown timezone: '{location_tz}', defaulting to 'UTC'. {ex}")
            self.robot_tz_info = pytz.timezone("UTC")

        # Configure InOrbit
        params = {"api_key": inorbit_api_key, "use_ssl": inorbit_api_use_ssl}
        if inorbit_api_endpoint:
            params["endpoint"] = inorbit_api_endpoint

        # The Connector supports handling a set of robots connected to the OTTO Fleet Manager
        self.user_scripts_dir = user_scripts_dir
        robot_factory = RobotSessionFactory(**params)
        robot_factory.register_command_callback(self.command_callback)
        self.robot_pool = RobotSessionPool(robot_factory)

        # Manager for proxy objects
        # The proxies will be sent to the websocket client on a different process
        self.manager = Manager()
        # Dictionary mapping inorbit_robot_id->OttoRobot instance
        self.robots = self.manager.dict()
        # Index of otto_robot_id->inorbit_robot_id
        self.otto_to_io_id = self.manager.dict()
        # Populate dictionaries
        for definition in robot_definitions:
            inorbit_id = definition["inorbit_id"]
            otto_id = definition["otto_id"]
            self.robots[inorbit_id] = OttoRobot(otto_id)
            self.otto_to_io_id[otto_id] = inorbit_id

        # Configure OTTO Fleet Manager REST API client
        self.http_client = HTTPClient(
            f"https://{fleet_manager_address}/api/",
            verify_ssl=False,
            loglevel=loglevel,
            disable_insecure_request_warning=True,
        )

        # Configure OTTO Fleet Manager Websocket API client using the guide shared at:
        #   <OTTO_FM_offline_docs>/docs/fleet/public_api/websocket/introduction/getting_started_py.html
        #    WebSocket API docs: <OTTO_FM_offline_docs>/docs/fleet/public_api/websocket/index.html
        url = f"wss://{fleet_manager_address}/api/fleet/wamp/"
        cert_options = ssl.CertificateOptions(verify=False)
        self.topics = (
            *[f"v2.stream.robots.{robot.otto_id}.pose" for robot in self.robots.values()],
            *[f"v2.stream.robots.{robot.otto_id}.plan" for robot in self.robots.values()],
            "v2.robots.batteries",
            "v2.robots.places",
            "v2.robots.states",
            "v2.robots.payloads",
            "v2.missions",
        )
        self.runner = ApplicationRunner(
            url,
            realm="default",
            extra={
                "topics": self.topics,
                "robots": self.robots,
                "id_index": self.otto_to_io_id,
                "http_client": self.http_client,
                "loglevel": loglevel,
            },
            ssl=cert_options,
        )

    def command_callback(self, robot_id, command_name, args, options):
        """Handle commands received from InOrbit.

        Args:
            robot_id (str): InOrbit's robot ID.
            command_name (str): Name of the command received.
            args(list[str]): Command arguments.
            options (list[str]): Edge SDK command callback options.
        """
        self.logger.info(f"Command received for robot {robot_id}: {command_name} {args}")

        # Find the robot
        robot: OttoRobot = self.robots.get(robot_id)
        if not robot:
            self.logger.warn(f"Robot {robot_id} not found")
            return
        otto_id = robot.otto_id

        # Handle `RunScript` type actions and other custom commands
        if command_name == COMMAND_CUSTOM_COMMAND:
            script_name = args[0]
            script_args = args[1]
            success = False

            if script_name == "move_to_place" and script_args[0] == "--place_id":
                place_id = script_args[1]
                success = self.http_client.simple_move_mission(otto_id, place_id)

            elif script_name == "dispatch_template" and script_args[0] == "--mission_template_id":
                template_id = script_args[1]
                success = self.http_client.dispatch_mission_template(otto_id, template_id)
            elif script_name[-3:] == ".sh":
                # Run local script
                self.run_local_script(self.user_scripts_dir + "/" + script_name, list(script_args))
                success = True  # We actually don't know, but waiting would block execution
            elif script_name == "run_recipe" and script_args[0] == "--recipe_id":
                # If the --waiting_time argument was provided and the value exists use it,
                # otherwise use the default value.
                try:
                    if script_args[2] == "--waiting_time":
                        waiting_time = int(script_args[3])
                except Exception:
                    waiting_time = RECIPE_EXECUTION_WAIT_DEFAULT

                Thread(target=self.run_recipe, args=(otto_id, script_args[1], waiting_time)).start()
                success = True  # We actually don't know, but waiting would block execution

            if success:
                # Return '0' for success
                return options["result_function"]("0")
            else:
                # Request failed. Return '1'
                return options["result_function"]("1")

        elif command_name == COMMAND_MESSAGE:
            msg = args[0]
            if msg == "pause_autonomy":
                self.http_client.pause_autonomy(otto_id)
            elif msg == "resume_autonomy":
                self.http_client.resume_autonomy(otto_id)
            elif msg == "clear_payload":
                self.http_client.clear_payload(otto_id)
            elif msg == "available":
                self.http_client.set_availability(otto_id, True)
            elif msg == "unavailable":
                self.http_client.set_availability(otto_id, False)
            elif re.search("_mission$", msg):
                # Get current mission ID from the Mission Tracking data
                mission_id = robot.event_key_values.get(InOrbitDataKeys.MISSION_TRACKING, {}).get(
                    "missionId"
                )
                if not mission_id:
                    self.logger.warn(
                        f"{msg} received but robot {robot_id} does not have an active mission"
                    )
                    return
                if msg == "pause_mission":
                    self.http_client.pause_mission(mission_id)
                elif msg == "resume_mission":
                    self.http_client.resume_mission(mission_id)
                elif msg == "retry_mission":
                    self.http_client.retry_mission(mission_id)
                elif msg == "cancel_mission":
                    self.http_client.cancel_mission(mission_id)
                else:
                    self.logger.warn(f"{msg} is not a valid message")
            elif msg == "cancel_all_missions":
                Thread(
                    target=self.http_client.cancel_all_missions
                ).start()  # This one may take some time to complete
        else:
            self.logger.info(f"Unknown command received: {command_name}")

    def run_recipe(self, otto_id, recipe_id, waiting_time):
        """Run a maintenance recipe on the robot.

        Args:
            otto_id (str): ID of the robot in the FM.
            recipe_id (str): ID of the recipe to execute.
            waiting_time (str): Time to wait before taking the robot out of maintenance mode,
            once the recipe is sent for execution.
        """
        # Put the robot in maintenance mode
        success = self.http_client.set_maintenance_mode(otto_id, maintenance=True)
        if not success:
            self.logger.warn("Unable to put the robot in maintenance mode to run recipe")
            return

        success = self.http_client.send_recipe(otto_id, recipe_id)
        if not success:
            self.logger.warn(f"Unable trigger recipe {recipe_id}")

        # Wait to disable maintenance mode, otherwise the robot gets all steps at
        # the same time and never gets into this mode.
        sleep(waiting_time)

        # Take the robot out of maintenance mode
        success = self.http_client.set_maintenance_mode(otto_id, maintenance=False)
        if not success:
            self.logger.warn("Unable to take the robot out of maintenance mode")

    def run_local_script(self, script_name, script_args):
        """Run a script from ./user_scripts."""
        self.logger.info(f"Running script : {script_name}")
        try:
            subprocess.Popen([f"{script_name}"] + script_args, shell=False)
        except Exception as e:
            self.logger.error(f"Exception when running script {script_name}: {e}")

    def start(self):
        """Start the main loop of the Connector."""
        # Start Websocket client in a separate process, because it needs its own event loop
        self.wamp_client_process = Process(target=self.runner.run, args=[WampClient])
        self.wamp_client_process.start()
        # Start robot sessions
        for i, definition in enumerate(self.robot_definitions):
            inorbit_id = definition["inorbit_id"]
            camera_url = definition.get("camera_url")
            sess = self.robot_pool.get_session(inorbit_id)
            if camera_url:
                sess.register_camera(
                    str(i), OpenCVCamera(camera_url, rate=8, scaling=0.2, quality=35)
                )

        while True and self.wamp_client_process.is_alive():
            for robot_id, robot in self.robots.items():
                robot_sess = self.robot_pool.get_session(robot_id)

                # If we have complete pose data, publish it
                pose = robot.pose
                if all(isinstance(v, float) for v in pose.values()):
                    # self.logger.debug(f"Publishing pose: {pose}")
                    robot_sess.publish_pose(**pose)

                # Publish path data
                path = robot.path
                # if path:
                # self.logger.debug(f"Publishing path: {path}")
                robot_sess.publish_path(path)

                # NOTE(@b-Tomas): Separation between telemetry and event key-values is made because
                # the edge-sdk does not support different sampling modes yet (v1.11.1)
                # TODO(@b-Tomas): Handle this on the edge-sdk instead, in order to configure
                # different QoS for events and telemetry data sent over MQTT.

                # Add telemetry key-values filtering out None values
                telemetry_key_values = {
                    k: v for k, v in robot.telemetry_key_values.items() if v is not None
                }

                # Pick the event key-value pairs that have changed since the last update
                event_key_values = {
                    k: v
                    for k, v in robot.event_key_values.items()
                    if v != robot.last_published_event_values.get(k)
                }

                # Save last published event key-values and update the robots proxy dict
                for k, v in event_key_values.items():
                    robot.last_published_event_values[k] = v
                self.robots[robot_id] = robot

                key_values = {**telemetry_key_values, **event_key_values}
                # self.logger.debug(f"Publishing kv: {key_values}")
                robot_sess.publish_key_values(key_values)

            sleep(1 / CONNECTOR_UPDATE_FREQ)

    def stop(self):
        """Exit the Connector cleanly."""
        # TODO(b-Tomas): Look into the errors appearing in the console at shutdown time
        self.robot_pool.tear_down()
        self.wamp_client_process.kill()
        self.wamp_client_process.join()
