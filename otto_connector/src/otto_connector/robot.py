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
        # `None` values are not uploaded.
        self.key_values = {
            InOrbitDataKeys.BATTERY_PERCENT: None,  # In range 0..1
            InOrbitDataKeys.MISSION_STATUS: InOrbitModeTags.ERROR,  # Start in ERROR mode
            InOrbitDataKeys.LAST_PLACE: None,  # {"name": "string", "id": "string"},
            InOrbitDataKeys.MISSION_TRACKING: {},  # Mission Tracking data
            InOrbitDataKeys.ONLINE_STATUS: False,  # Consider offline at startup until FM launches
            InOrbitDataKeys.SYSTEM_STATE: None,  # string
            InOrbitDataKeys.SUBSYSTEM_STATE: None,  # string
        }
