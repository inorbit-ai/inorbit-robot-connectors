# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""WAMP client that enables communication with OTTO's FM via websockets."""

import logging
import re

from autobahn.twisted.wamp import ApplicationSession
from autobahn.wamp import EventDetails, SubscribeOptions
from dateutil import parser as date_parser
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks

from .robot import OttoRobot
from .values import (
    InOrbitDataKeys,
    InOrbitModeTags,
    OttoMissionStatus,
)


class WampClient(ApplicationSession):
    """Listens to events on a list of topics of the Fleet Manager websocket API."""

    def __init__(self, *args, **kwargs):
        """Init the WampClient with the configuration provided.

        Args:
            *args: Variable length argument list. Including:
                - robots: list of OTTORobot objects.
                - topics: list of topic names to subscribe to.
                - loglevel: logging level (one of  DEBUG, INFO, WARNING, ERROR, CRITICAL).
                - id_index: dictionary of otto_robot_id->inorbit_robot_id
            **kwargs: Arbitrary keyword arguments.
        """
        super().__init__(*args, **kwargs)
        assert all(i in args[0].extra.keys() for i in ["robots", "topics", "loglevel", "id_index"])

        # Topics list
        self.topics = args[0].extra["topics"]
        # OttoRobot instances
        self.robots: dict = args[0].extra["robots"]
        # Index of otto_robot_id->inorbit_robot_id
        self.id_index: dict = args[0].extra["id_index"]
        # Object for interacting with the Fleet Manager's REST API
        self.http_client: dict = args[0].extra["http_client"]

        self.logger = logging.getLogger(name=self.__class__.__name__)
        self.logger.setLevel(args[0].extra["loglevel"])

    def on_event(self, message, *args, **kwargs):
        """Handle events from the subscribed topics."""
        details: EventDetails = kwargs["details"]
        topic = details.subscription.topic

        self.logger.debug(f"Message `{message}` received from topic {topic}")
        self.logger.debug(f"    args: {args}")
        self.logger.debug(f"    kwargs: {kwargs}")

        # Pose data topic
        if re.fullmatch(r"^v2\.stream\.robots\..*\.pose$", topic) and "pose" in message:
            self._handle_pose_event(topic, args, message)

        # Planned path data topic
        elif re.fullmatch(r"^v2\.stream\.robots\..*\.plan$", topic) and "poses" in message:
            self._handle_path_event(topic, args, message)

        # Batteries data topic
        elif topic == "v2.robots.batteries":
            self._handle_batteries_event(topic, args, message)

        # Places topic
        elif topic == "v2.robots.places":
            self._handle_places_event(topic, args, message)

        # States topic
        elif topic == "v2.robots.states":
            self._handle_states_event(topic, args, message)

        # Mission creation and updates
        elif topic == "v2.missions":
            self._handle_missions_event(topic, args, message)

    def _handle_batteries_event(self, topic, args, message):
        """Handle batteries topic messages. Receives an array with battery data of all robots."""
        # TODO(@Tom743): Check the schema of arguments when having multiple robots.
        # It might be tuple<list<dict>> with ([{robot1 data}, {robot2 data}])
        # or ([{robot1 data}], [{robot2 data}]).

        batteries = args[0]
        for battery in batteries:
            otto_id = battery.get("robot")
            inorbit_id = self.id_index.get(otto_id)
            if not inorbit_id:
                self.logger.warning(
                    f"Received battery data for robot {otto_id} "
                    "which is not registered in the connector"
                )
                return

            robot: OttoRobot = self.robots[inorbit_id]
            charging_status = str(battery.get("charging_status"))
            robot.key_values[InOrbitDataKeys.MISSION_STATUS] = (
                InOrbitModeTags.CHARGING
                if charging_status.lower() == "charging"
                else InOrbitModeTags.IDLE
            )

            percentage = battery.get("percentage")
            if percentage:
                robot.key_values[InOrbitDataKeys.BATTERY_PERCENT] = percentage

            # Update the proxy dictionary to notify the manager
            self.robots[inorbit_id] = robot

    def _handle_pose_event(self, topic, args, message):
        """Update pose data in the robot's data class."""
        otto_id = topic.split(".")[3]
        inorbit_id = self.id_index.get(otto_id)
        if not inorbit_id:
            self.logger.warning(
                f"Received pose data for robot {otto_id} which is not registered in the connector"
            )
            return
        robot = self.robots[inorbit_id]
        robot.pose = message["pose"]

        # Update the proxy dictionary to notify the manager
        self.robots[inorbit_id] = robot

    def _handle_path_event(self, topic, args, message):
        """Update path data in the robots data class."""
        otto_id = topic.split(".")[3]
        inorbit_id = self.id_index.get(otto_id)
        if not inorbit_id:
            self.logger.warning(
                f"Received path data for robot {otto_id} which is not registered in the connector"
            )
            return
        robot = self.robots[inorbit_id]
        planned_path = []
        poses = message["poses"]
        for pose in poses:
            planned_path.append((pose["x"], pose["y"]))
        robot.path = planned_path

        # Update the proxy dictionary to notify the manager
        self.robots[inorbit_id] = robot

    def _handle_states_event(self, topic, args, message):
        """Update robot states."""
        states = args[0]
        for state in states:
            otto_id = state["robot"]
            inorbit_id = self.id_index.get(otto_id)
            if not inorbit_id:
                self.logger.warning(
                    f"Received state data for robot {otto_id} "
                    "which is not registered in the connector"
                )
                return
            robot: OttoRobot = self.robots[inorbit_id]
            self.logger.debug(f"Received state: {state}")
            # The following states are not valid, ignore them
            if (
                not state.get("system_state")
                or not state.get("sub_system_state")
                or state.get(InOrbitDataKeys.SUBSYSTEM_STATE) == "NOT_CLEAR_TO_PROCEED"
            ):
                return

            robot.key_values[InOrbitDataKeys.SYSTEM_STATE] = state.get("system_state")
            robot.key_values[InOrbitDataKeys.SUBSYSTEM_STATE] = state.get("sub_system_state")

            # Send online status on a separate key value
            robot.key_values[InOrbitDataKeys.ONLINE_STATUS] = state.get("system_state") != "OFFLINE"

            # Update the proxy dictionary to notify the manager
            self.robots[inorbit_id] = robot

    def _handle_places_event(self, topic, args, message):
        """Update robot's current place."""
        # TODO(@Tom743): Check schema when having more robots, same situation as in
        # `_handle_batteries_event()`.

        places = args[0]
        for place in places:
            otto_id = place["robot"]
            inorbit_id = self.id_index.get(otto_id)
            if not inorbit_id:
                self.logger.warning(
                    f"Received place data for robot {otto_id} "
                    "which is not registered in the connector"
                )
                return
            robot: OttoRobot = self.robots[inorbit_id]
            robot.key_values[InOrbitDataKeys.LAST_PLACE] = {
                "name": place.get("name"),
                "id": place.get("id"),
            }

            # Update the proxy dictionary to notify the manager
            self.robots[inorbit_id] = robot

    def _handle_missions_event(self, topic, args, message):
        """Handle events from topic `v2.missions`."""
        # TODO(@Tom743): Check schema when having more robots, same situation as in
        # `_handle_batteries_event()`.

        missions = args[0]

        # TODO(b-Tomas): The args list seems to always be a list of one element. Maybe with `all`
        # messages it is a list of more? If there is one event per mission updated/added, then
        # some tracking logic has to be implemented to know when a missions changed to a
        # non-blocking state or when a blocking mission should update the corresponding robot
        # object.

        for mission in missions:
            # Assigned robot. Can be `None`` if the job is not assigned yet.
            assigned_robot = mission["assigned_robot"]
            if not assigned_robot:
                continue
            inorbit_id = self.id_index.get(assigned_robot)
            if not inorbit_id:
                self.logger.info(
                    f"Received mission data for robot {assigned_robot} "
                    "which is not registered in the connector"
                )
                continue

            # Possible values for mission_status:
            # [ ASSIGNED, BLOCKED, CANCELLED, CANCELLING, EXECUTING, FAILED, PAUSED, QUEUED,
            #   REASSIGNED, RESTARTING, REVOKED, STARVED, SUCCEEDED ]
            # A successful straightforward mission usually follows:
            # QUEUED -> ASSIGNED -> EXECUTING -> SUCCEEDED
            mission_status = mission["mission_status"]
            # Ignore any state not in the following list
            if mission_status not in [
                OttoMissionStatus.EXECUTING,
                OttoMissionStatus.FAILED,
                OttoMissionStatus.BLOCKED,
                OttoMissionStatus.STARVED,
                OttoMissionStatus.PAUSED,
                OttoMissionStatus.CANCELLING,
                OttoMissionStatus.CANCELLED,
                OttoMissionStatus.SUCCEEDED,
                OttoMissionStatus.STOPPED,
            ]:
                continue

            # Unique mission id. Can be used to pause/resume/update/cancel/retry the mission.
            mission_id = mission["id"]

            # If `finalized` is False, mission will not complete when all tasks defined are
            # completed. Usually this is not the intention, thus the warning.
            finalize = mission["finalized"]
            if not finalize:
                self.logger.warn(
                    f"Mission {mission_id} has attribute `finalized` set to {finalize}"
                )

            robot: OttoRobot = self.robots[inorbit_id]

            # Mission tracking object
            mission_values = {
                # The mission ID will be the same in InOrbit and in the Fleet Manager.
                "missionId": mission_id,
                # Use the mission name as label, otherwise use description, otherwise the
                # mission_id.
                "label": mission.get("name", mission.get("description", mission_id)),
                # The states used by mission tracking will be the same as the ones reported by the
                # Fleet Manager (in lowercase).
                # The `status` of the mission (ok, warn or error) will be set automatically by the
                # mission tracking configuration.
                "state": str.lower(mission_status),
                # Default completion percentage to 0% unless the state explicitly means the mission
                # is completed. This value will be calculated later or updated when uploading
                # key-values.
                "completedPercent": 0.0
                if mission_status in [OttoMissionStatus.STARVED, OttoMissionStatus.SUCCEEDED]
                else 0.0,
                # Upload all of the received data
                # TODO(@Tom743): Filter out data we don't need
                # We DO need: "current_task", "max_duration", "execution_start" and "execution_end"
                # from the original data and "task_count".
                "data": mission,
            }

            def iso_to_ms(iso):
                # Convert ISO time format to epoch milliseconds
                return int(date_parser.parse(iso).timestamp() * 1000)

            # Calculate start and end times of the mission
            start = mission.get("execution_start")
            if start:
                mission_values["startTs"] = iso_to_ms(start)
            end = mission.get("execution_end")
            if end:
                mission_values["endTs"] = iso_to_ms(end)

            # Missions in the following states are considered in-progress
            if mission_status in [
                OttoMissionStatus.EXECUTING,
                OttoMissionStatus.CANCELLING,
                OttoMissionStatus.PAUSED,
            ]:
                mission_values["inProgress"] = True
                # Update mode tag
                # The `charging` mode is handled by the battery event
                robot.key_values[InOrbitDataKeys.MISSION_STATUS] = InOrbitModeTags.MISSION
            else:
                mission_values["inProgress"] = False
                robot.key_values[InOrbitDataKeys.MISSION_STATUS] = InOrbitModeTags.IDLE

            # Query the amount of tasks this mission currently has. This used for computing
            # mission completion.
            if mission_id:
                # Note: A slow request may block the WAMP session loop, but all new messages
                # will get buffered. It doesn't block the connector's main event loop because
                # the WAMP client runs on a different process.
                total_count = self.http_client.get_tasks(
                    params={"fields": "--", "mission": mission_id}
                ).get("count")
                if total_count:
                    mission_values["data"]["task_count"] = total_count

                current_task = mission_values.get("data", {}).get("current_task")

                # If possible calculate the completion percentage
                if total_count and current_task:
                    percent = current_task / total_count
                    if current_task > total_count:
                        self.logger.warn(
                            f"Current task number ({current_task}) is greater than total "
                            "task count ({total_count})"
                        )
                        percent = 1.0
                    mission_values["completedPercent"] = percent

            self.logger.debug(f"Mission tracking values: {mission_values}")

            # Update the robot's current mission values
            robot.key_values[InOrbitDataKeys.MISSION_TRACKING] = mission_values
            # Update the proxy dictionary to notify the manager
            self.robots[inorbit_id] = robot

    def _subscribe(self, topic):
        """Subscribe to a WAMP topic."""
        # Enable `details`, a kwarg sent to the handler on each event
        return self.subscribe(self.on_event, topic, SubscribeOptions(details=True))

    @inlineCallbacks  # type: ignore
    def onJoin(self, details: EventDetails):
        """Subscribe to topics when connected to the session."""
        self.logger.info("Connected to session")
        self.logger.debug(f"Details: {details}")
        for topic in self.topics:
            sub = yield self._subscribe(str(topic))
            self.logger.info(f"Subscribed to {topic}\n  Sub id: {sub.id}")

    def onDisconnect(self):
        """Subscribe to topics when connected to the session."""
        self.logger.info("Disconnected")
        if reactor.running:  # type: ignore
            reactor.stop()  # type: ignore
