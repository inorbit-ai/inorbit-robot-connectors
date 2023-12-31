# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""OTTO robot class."""

from .values import (
    InOrbitDataKeys,
    InOrbitModeTags,
)


class OttoRobot:
    """Holds the data of a single robot instance, which is updated by the FM's WAMP client."""

    def __init__(self, otto_id):
        """
        Build an OTTO robot instance.

        Args:
            otto_id (str): Robot ID assigned by the OTTO Fleet Manager
        """
        # NOTE: `None` values are replaced in the first update of each field.
        # `None` values are not be published.

        # Specific ID assigned to the OTTO robot by the OTTO Fleet Manager
        self.otto_id = otto_id
        # Pose as registered in the Fleet Manager. Type: Float | None
        self.pose = {"x": None, "y": None, "yaw": None}

        # Robot's planned path
        self.path = []

        # Supported key-values.
        # NOTE(@b-Tomas): Separation between telemetry and event key-values is made because the
        # edge-sdk does not support different sampling modes yet (v1.11.1)
        self.telemetry_key_values = {
            InOrbitDataKeys.BATTERY_PERCENT: None,  # In range 0..1
            InOrbitDataKeys.MISSION_STATUS: InOrbitModeTags.ERROR,  # Start in ERROR mode
        }
        self.event_key_values = {
            # {"name": "string", "id": "string"},
            InOrbitDataKeys.LAST_PLACE: None,
            # Mission Tracking data
            InOrbitDataKeys.MISSION_TRACKING: {},
            # Consider offline at startup until FM launches
            InOrbitDataKeys.ONLINE_STATUS: False,
            # List of { system_state: <state>, subsystem_state: <sub_state> } values
            InOrbitDataKeys.ROBOT_STATES: [],
            # List of current `sub_system_state` values (unrepeated)
            InOrbitDataKeys.SUBSYSTEM_STATES: [],
            # List of current payload ids for the robot
            InOrbitDataKeys.PAYLOAD_IDS: [],
        }

        # Save the last published event key-values to avoid publishing them every time.
        self.last_published_event_values = {}

        # Dictionary of currently active state records of a robot as published by the FM, indexed
        # by record id.
        self.current_robot_status_raw = {}

        # Set of current payload ids for a robot as published by the FM.
        self.current_payloads = set()
