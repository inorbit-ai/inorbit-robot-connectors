# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Values representing robot status on both OTTO and InOrbit language."""


class OttoMissionStatus:
    """Possible "mission_status" values published by the FM on "v2.missions" topic."""

    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    CANCELLING = "CANCELLING"
    EXECUTING = "EXECUTING"
    FAILED = "FAILED"
    PAUSED = "PAUSED"
    STARVED = "STARVED"
    STOPPED = "STOPPED"
    SUCCEEDED = "SUCCEEDED"


class InOrbitModeTags:
    """Mission status values to report to InOrbit as the robot's Mode."""

    # Right now only "idle", "charging" and "mission" are supported
    # TODO(@Tom743): Support more modes
    IDLE = "idle"
    MISSION = "mission"
    CHARGING = "charging"
    MANUAL = "manual"
    ERROR = "error"


class InOrbitDataKeys:
    """
    Strings for data source keys.

    The keys must be unique per account, but may differ from one account to another depending on
    the configuration defined for each.
    """

    BATTERY_PERCENT = "battery_percent"
    MISSION_STATUS = "mission_status"
    LAST_PLACE = "last_place"
    MISSION_TRACKING = "mission_tracking"
    ONLINE_STATUS = "online"
    SYSTEM_STATE_FULL = "system_state_full"
    SUBSYSTEM_STATE = "sub_system_state"
