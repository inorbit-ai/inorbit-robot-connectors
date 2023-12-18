# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import logging
from datetime import datetime
from inorbit_edge.missions import MISSION_STATE_EXECUTING, MISSION_STATE_ABORTED

# Mission states
MISSION_STATE_DONE = "Done"
MISSION_STATE_ABORT = "Abort"


class MirInorbitMissionTracking:
    def __init__(
        self,
        mir_api,
        inorbit_sess,
        robot_tz_info,
        loglevel="INFO",
        enable_io_mission_tracking=True,
    ):
        self.logger = logging.getLogger(name=self.__class__.__name__)
        self.logger.setLevel(loglevel)
        # Use for mission tracking
        # If set to False, mission tracking data will not be published to InOrbit
        self.io_mission_tracking_enabled = enable_io_mission_tracking
        # Hack to allow MiR defined missions and InOrbit missions to co-exist
        # When an InOrbit mission is running, we disable tracking for MiR defined
        # missions. if `self.io_mission_tracking_enabled` is False, data will not be
        # published anyway
        self.mir_mission_tracking_enabled = False
        self.executing_mission_id = None
        self.last_reported_mission_id = None
        self.last_reported_mission_progress = 0.0
        self.waiting_for_text = ""  # Text used to control waitUntil in missions
        self.mir_api = mir_api
        self.inorbit_sess = inorbit_sess
        self.robot_tz_info = robot_tz_info

    def get_current_mission(self):
        """Return the current mission, it's either executing or just ended"""
        mission = None
        if self.executing_mission_id is None:
            self.executing_mission_id = self.mir_api.get_executing_mission_id()
        if self.executing_mission_id:
            mission = self.mir_api.get_mission(self.executing_mission_id)
            if mission["state"] != MISSION_STATE_EXECUTING:
                # Update executing_mission_id so the next call to this method returns the next
                # executing mission or None.
                # Note that the current call in this case returns the just finished mission
                self.executing_mission_id = None
        return mission

    def report_mission(self, status, metrics):
        # Hack to allow MiR defined missions and InOrbit missions to co-exist
        # When an InOrbit mission is running, we disable tracking for MiR defined
        # missions
        if not self.inorbit_sess.missions_module.executor.wait_until_idle(0):
            self.mir_mission_tracking_enabled = False
        if not self.mir_mission_tracking_enabled:
            return
        mission = self.get_current_mission()
        if mission:
            completed_percent = len(mission["actions"]) / len(mission["definition"]["actions"])
            # Merge 'Abort' and 'Aborted' values into a single state
            if mission["state"] == MISSION_STATE_ABORT:
                mission["state"] = MISSION_STATE_ABORTED
            if (
                mission["id"] == self.last_reported_mission_id
                and mission["state"] == MISSION_STATE_EXECUTING
                and completed_percent == self.last_reported_mission_progress
            ):
                # Avoid flooding mission reports when nothing important has changed
                return
            mission_values = {
                "missionId": mission["id"],
                "inProgress": mission["state"] == MISSION_STATE_EXECUTING,
                "state": mission["state"],
                "label": mission["definition"]["name"],
                "startTs": self.robot_tz_info.localize(
                    datetime.fromisoformat(mission["started"])
                ).timestamp()
                * 1000,
                "data": {
                    "Total Distance (m)": metrics.get(
                        "mir_robot_distance_moved_meters_total", "N/A"
                    ),
                    "Mission Steps": len(mission["definition"]["actions"]),
                    "Total Missions": mission["id"],
                    "Robot Model": status["robot_model"],
                    "Uptime (s)": status["uptime"],
                    "Serial Number": status.get("serial_number", "N/A"),
                    "Battery Time Remaning (s)": status.get("battery_time_remaining", "N/A"),
                    "WiFi RSSI (dbm)": metrics.get("mir_robot_wifi_access_point_rssi_dbm", "N/A"),
                },
            }
            if mission.get("finished") is not None:
                mission_values["endTs"] = (
                    self.robot_tz_info.localize(
                        datetime.fromisoformat(mission["finished"])
                    ).timestamp()
                    * 1000
                )
                mission_values["completedPercent"] = 1
                mission_values["status"] = (
                    "OK" if mission["state"] == MISSION_STATE_DONE else "error"
                )
            else:
                mission_values["completedPercent"] = completed_percent

            if self.io_mission_tracking_enabled:
                self.logger.info(f"Reporting mission: {mission_values}")
                self.inorbit_sess.publish_key_values(
                    key_values={"mission_tracking": mission_values}, is_event=True
                )
            self.last_reported_mission_progress = completed_percent
            self.last_reported_mission_id = mission["id"]
